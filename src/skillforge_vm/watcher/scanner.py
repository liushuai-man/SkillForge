"""M-02 稳定扫描：目录清单 + 文件身份 / 大小 / mtime（§7.2）。

扫描本身不写任何东西；它只产出「候选清单」，供快照执行器判断是否发生了真实变化，
以及判断读取期间工作区是否仍在变动（两端清单一致才算稳定）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.paths import is_link_like
from ..core.types import MODE_EXECUTABLE, MODE_REGULAR
from ..objectstore.store import IgnoreFn


@dataclass(frozen=True)
class ScanEntry:
    """一个候选文件的稳定标识。``mtime`` 只用于稳定性比对，不参与是否变化的判定。"""

    rel_path: str
    mode: str
    size: int
    mtime_ns: int


def scan_files(root: Path, ignore: IgnoreFn | None = None) -> tuple[ScanEntry, ...]:
    """按忽略规则遍历工作区，返回按路径 UTF-8 字节序排序的文件清单。

    跳过符号链接 / junction 与非常规文件（AC-16）。目录清单变化会影响结果，
    因此调用方以「前后两次扫描结果相同」作为稳定判据。
    """
    entries: list[ScanEntry] = []
    _walk(Path(root), Path("."), ignore, entries)
    entries.sort(key=lambda entry: entry.rel_path.encode("utf-8"))
    return tuple(entries)


def _walk(
    root: Path,
    rel: Path,
    ignore: IgnoreFn | None,
    entries: list[ScanEntry],
) -> None:
    current = root if rel == Path(".") else root / rel
    for child in current.iterdir():
        child_rel = child.relative_to(root)
        if ignore is not None and ignore(child_rel):
            continue
        if is_link_like(child):
            continue
        if child.is_dir():
            _walk(root, child_rel, ignore, entries)
        elif child.is_file():
            stat = child.stat()
            mode = MODE_EXECUTABLE if stat.st_mode & 0o111 else MODE_REGULAR
            entries.append(
                ScanEntry(
                    rel_path=child_rel.as_posix(),
                    mode=mode,
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                )
            )
