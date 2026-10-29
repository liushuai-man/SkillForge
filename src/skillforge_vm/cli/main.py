"""M-12 命令行客户端入口。

与服务完全等价（设计 §4.6）：业务命令只调用服务，不直连数据库。
`start` 是本机服务启动入口；其余命令在服务未启动时给出明确提示。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from ..core.config import Settings
from .client import CliError, VmClient, resolve_base_url
from .report_view import format_comparison, format_report
from .service import run_service

app = typer.Typer(add_completion=False, help="留痕版本管理器（服务客户端）")

_TRIGGERS = {"init": "首次纳管", "manual": "手动保存", "watch": "自动保存"}
_SOURCES = {"initial": "初始内容", "edit": "文件编辑", "external": "外部修改"}
_OPERATIONS = {
    "workspace.init": "纳管目录",
    "snapshot": "记录快照",
    "ref.set": "设置锚点",
    "restore.plan": "预览恢复",
    "restore.begin": "开始恢复",
    "restore.done": "完成恢复",
}

UrlOpt = Annotated[
    str | None,
    typer.Option("--url", help="服务地址；省略时按环境变量/运行时文件/默认端口解析"),
]
WsOpt = Annotated[str | None, typer.Option("--ws", help="工作区标识")]


def _client(ctx: typer.Context) -> VmClient:
    return VmClient(ctx.obj["base_url"])


def _resolve_ws(client: VmClient, ws: str | None) -> str:
    """未显式指定时，唯一工作区可省略；多个工作区必须显式指定。"""
    if ws:
        return ws
    workspaces = client.get("/api/workspaces")
    if len(workspaces) == 1:
        return workspaces[0]["workspace_id"]
    if not workspaces:
        raise CliError("还没有纳管任何工作区，先运行 `skillforge-vm init <path>`")
    current = Path.cwd().resolve()
    matches = [
        row for row in workspaces if current.is_relative_to(Path(row["root_path"]).resolve())
    ]
    if len(matches) == 1:
        return matches[0]["workspace_id"]
    raise CliError("存在多个工作区；在 技能目录中运行，或用 --ws <id> 指定。")


def _fail(message: str) -> None:
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1)


@app.callback()
def main(
    ctx: typer.Context,
    url: UrlOpt = None,
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
) -> None:
    ctx.obj = {"base_url": resolve_base_url(url, data_root=data_root), "data_root": data_root}


@app.command()
def start(
    ctx: typer.Context,
    host: Annotated[str, typer.Option(help="监听地址（默认仅本机）")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="首选端口；被占用时自动改用系统分配端口")] = 8756,
    data_root: Annotated[
        Path | None, typer.Option("--data-root", help="数据根目录；省略用默认位置")
    ] = None,
) -> None:
    """启动本机服务（阻塞运行）。"""
    resolved_root = data_root or ctx.obj["data_root"] or Settings().data_root

    def ready(base_url: str) -> None:
        typer.echo(f"留痕 服务已启动：{base_url}")
        typer.echo(f"数据根：{resolved_root}")
        typer.echo(f"端口记录：{resolved_root / 'runtime.json'}")

    try:
        run_service(resolved_root, host, port, on_ready=ready)
    except CliError as exc:
        _fail(str(exc))


@app.command()
def gui(
    ctx: typer.Context,
    no_browser: Annotated[bool, typer.Option("--no-browser", hidden=True)] = False,
) -> None:
    """启动或复用本机服务，并打开可视化界面。"""
    from .gui import launch

    try:
        base = launch(ctx.obj["data_root"], open_browser=not no_browser)
    except (CliError, OSError) as exc:
        _fail(str(exc))
    typer.echo(f"可视化界面：{base}/")


@app.command()
def init(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="要纳管的 技能目录")],
    name: Annotated[str | None, typer.Option(help="工作区名称")] = None,
) -> None:
    """纳管一个 技能目录。"""
    try:
        data = _client(ctx).post("/api/workspaces", {"path": str(path), "name": name})
    except CliError as exc:
        _fail(str(exc))
    typer.echo(f"已纳管：{data['workspace']['workspace_id']}")
    typer.echo(f"首个修订：{data['revision_id']}（{data['file_count']} 个文件）")


@app.command()
def workspaces(ctx: typer.Context) -> None:
    """列出已纳管的工作区。"""
    try:
        rows = _client(ctx).get("/api/workspaces")
    except CliError as exc:
        _fail(str(exc))
    if not rows:
        typer.echo("（暂无工作区）")
        return
    for row in rows:
        typer.echo(f"{row['workspace_id']}  {row['name']}  {row['root_path']}")


@app.command()
def status(ctx: typer.Context, ws: WsOpt = None) -> None:
    """查看是否有未纳管改动、当前与谁比较。"""
    client = _client(ctx)
    try:
        workspace_id = _resolve_ws(client, ws)
        data = client.get(f"/api/workspaces/{workspace_id}/status")
    except CliError as exc:
        _fail(str(exc))
    pending = "有未纳管改动" if data["has_pending_changes"] else "无改动"
    typer.echo(f"工作区：{data['workspace_id']}")
    typer.echo(f"当前修订：{data['head_revision']}（序号 {data['head_seq']}）")
    typer.echo(f"状态：{pending}")
    if plan_id := data.get("pending_restore"):
        typer.echo(f"恢复尚未完成：{plan_id}")
        typer.echo(f"继续恢复：restore --resume {plan_id} --ws {workspace_id}")


@app.command()
def snapshot(
    ctx: typer.Context,
    message: Annotated[str | None, typer.Option(help="快照注解（可空）")] = None,
    ws: WsOpt = None,
) -> None:
    """手动快照（无变化时不会制造空快照）。"""
    client = _client(ctx)
    try:
        workspace_id = _resolve_ws(client, ws)
        data = client.post(f"/api/workspaces/{workspace_id}/snapshots", {"message": message})
    except CliError as exc:
        _fail(str(exc))
    if data["created"]:
        typer.echo(f"已提交修订 {data['revision']['rev_id']}（序号 {data['revision']['seq']}）")
    else:
        typer.echo(f"内容未变化，当前修订 {data['revision']['rev_id']}")


@app.command()
def log(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option(help="最多显示的修订数")] = 20,
    ws: WsOpt = None,
) -> None:
    """按时间线列出修订。"""
    client = _client(ctx)
    try:
        workspace_id = _resolve_ws(client, ws)
        rows = client.get(f"/api/workspaces/{workspace_id}/revisions", limit=limit)
    except CliError as exc:
        _fail(str(exc))
    if not rows:
        typer.echo("（暂无修订）")
        return
    for row in rows:
        marker = (
            f"{_TRIGGERS.get(row['trigger'], row['trigger'])}/"
            f"{_SOURCES.get(row['source'], row['source'])}"
        )
        typer.echo(f"{row['seq']:>4}  {row['rev_id']}  {row['ts']}  {marker}")


@app.command()
def show(
    ctx: typer.Context,
    rev: Annotated[str, typer.Argument(help="修订表达式（@ / last / <ref> / <rev>~N）")],
    ws: WsOpt = None,
) -> None:
    """查看单个修订详情。"""
    client = _client(ctx)
    try:
        workspace_id = _resolve_ws(client, ws)
        data = client.get(f"/api/workspaces/{workspace_id}/revisions/{rev}")
    except CliError as exc:
        _fail(str(exc))
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@app.command()
def tag(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="锚点名（稳定版 / 已验证 等）")],
    rev: Annotated[str | None, typer.Option(help="目标修订表达式；省略取当前修订")] = None,
    ws: WsOpt = None,
) -> None:
    """打锚点。"""
    client = _client(ctx)
    try:
        workspace_id = _resolve_ws(client, ws)
        data = client.post(f"/api/workspaces/{workspace_id}/refs", {"name": name, "rev": rev})
    except CliError as exc:
        _fail(str(exc))
    typer.echo(f"锚点 {data['name']} → {data['rev_id']}")


@app.command()
def ops(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option(help="最多显示的条数")] = 20,
    ws: WsOpt = None,
) -> None:
    """查看操作日志。"""
    client = _client(ctx)
    try:
        workspace_id = _resolve_ws(client, ws)
        rows = client.get(f"/api/workspaces/{workspace_id}/ops", limit=limit)
    except CliError as exc:
        _fail(str(exc))
    if not rows:
        typer.echo("（暂无操作记录）")
        return
    for row in rows:
        typer.echo(f"{row['ts']}  {_OPERATIONS.get(row['kind'], row['kind'])}  {row['op_id']}")


@app.command()
def diff(
    ctx: typer.Context,
    old: Annotated[str | None, typer.Argument(help="旧版本或锚点")] = None,
    new: Annotated[str | None, typer.Argument(help="新版本；只给一个版本时与最新比较")] = None,
    base: Annotated[
        str | None, typer.Option(help="基线修订/锚点；省略使用目标的上一个修订")
    ] = None,
    head: Annotated[str | None, typer.Option(help="目标修订/锚点；省略使用当前修订")] = None,
    layer: Annotated[str | None, typer.Option(hidden=True)] = None,
    file: Annotated[str | None, typer.Option("--file", "-f", help="仅比较此文件路径")] = None,
    context: Annotated[int, typer.Option("--context", "-U", min=0, max=100, help="上下文行数")] = 3,
    summary: Annotated[bool, typer.Option("--summary", help="仅显示结论与计数")] = False,
    ws: WsOpt = None,
) -> None:
    """查看文件和行级差异：diff [旧版本] [新版本]，默认比较最新两版。"""
    if (old is not None or new is not None) and (base is not None or head is not None):
        _fail("位置参数与 --base/--head 请选择一种方式。")
    base, head = (old, new or "@") if old is not None else (base, head)
    client = _client(ctx)
    try:
        workspace_id = _resolve_ws(client, ws)
        if layer is not None:
            report = client.get(
                f"/api/workspaces/{workspace_id}/diff", base=base, head=head, layer=layer
            )
        else:
            report = client.get(
                f"/api/workspaces/{workspace_id}/compare",
                base=base,
                head=head,
                context=context,
                file=file,
            )
    except CliError as exc:
        _fail(str(exc))
    formatter = format_report if layer is not None else format_comparison
    typer.echo(formatter(report, summary_only=summary))


def _confirm_restore(client: VmClient, ws: str, plan: dict, *, yes: bool) -> None:
    if plan["no_change"]:
        typer.echo("目标内容与当前一致，无需恢复。")
        return
    typer.echo(f"恢复计划：{plan['plan_id']}")
    typer.echo(f"当前 {plan['before_rev']} → 目标 {plan['target_rev']}")
    labels = {
        "add": "新增",
        "modify": "修改",
        "delete": "删除",
        "mkdir": "建目录",
        "rmdir": "删目录",
    }
    for change in plan["changes"]:
        typer.echo(f"  {labels[change['action']]}  {change['path']}")
    typer.echo("将回写整个技能目录 的纳管内容；请先保存并暂停编辑。历史快照保留。")
    if not yes and not typer.confirm("确认执行？", default=False):
        typer.echo("已取消，未回写 技能文件。")
        return
    data = client.post(
        f"/api/workspaces/{ws}/restore/plans/{plan['plan_id']}/apply", {"confirm": True}
    )
    if data["created"]:
        typer.echo(f"恢复完成：{data['revision']['rev_id']}（序号 {data['revision']['seq']}）")
    else:
        typer.echo(f"计划此前已完成，本次未回写文件：{data['revision']['rev_id']}")


@app.command()
def restore(
    ctx: typer.Context,
    rev: Annotated[str | None, typer.Argument(help="目标修订或锚点")] = None,
    resume: Annotated[str | None, typer.Option(help="继续指定恢复计划")] = None,
    ws: WsOpt = None,
    yes: Annotated[bool, typer.Option("--yes", help="显式确认回写，适用于自动化")] = False,
) -> None:
    """预览并确认恢复整个技能目录；中断后用 --resume 继续。"""
    if (rev is None) == (resume is None):
        _fail("请提供目标修订，或使用 --resume <计划 ID>，二者只能选一个。")
    client = _client(ctx)
    try:
        workspace_id = _resolve_ws(client, ws)
        base = f"/api/workspaces/{workspace_id}/restore"
        plan = (
            client.get(f"{base}/plans/{resume}")
            if resume is not None
            else client.post(f"{base}/preview", {"rev": rev})
        )
        _confirm_restore(client, workspace_id, plan, yes=yes)
    except CliError as exc:
        _fail(str(exc))


@app.command()
def undo(
    ctx: typer.Context,
    ws: WsOpt = None,
    yes: Annotated[bool, typer.Option("--yes", help="显式确认撤销最近一次恢复")] = False,
) -> None:
    """预览并确认撤销最近一次文件恢复；已有后续改动时拒绝覆盖。"""
    client = _client(ctx)
    try:
        workspace_id = _resolve_ws(client, ws)
        plan = client.post(f"/api/workspaces/{workspace_id}/undo/preview", {})
        _confirm_restore(client, workspace_id, plan, yes=yes)
    except CliError as exc:
        _fail(str(exc))


if __name__ == "__main__":  # pragma: no cover
    app()
