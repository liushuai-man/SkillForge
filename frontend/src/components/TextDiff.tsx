import { MergeView } from '@codemirror/merge'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { useEffect, useRef } from 'react'

type Hunk = { path: string; before: { text: string } | null; after: { text: string } | null }
type FileChange = { path: string; op: string; before_path?: string }
const labels: Record<string, string> = { add: '新增', delete: '删除', modify: '修改', move: '移动' }
const reasons: Record<string, string> = { unsupported_encoding: '不是可显示的 UTF-8 文本', text_limit_exceeded: '超过文字展示上限', parse_failed: '结构解析失败，仍可查看文字变化', unsupported_file_type: '未支持此文件的结构分析，仍可查看文字变化' }

function Merge({ before, after, dark }: { before: string; after: string; dark: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!host.current) return
    const extensions = [EditorState.readOnly.of(true), EditorView.editable.of(false), EditorView.theme({
      '&': { backgroundColor: 'var(--surface)', color: 'var(--text)' },
      '.cm-content': { fontFamily: 'Consolas, monospace' },
      '.cm-gutters': { backgroundColor: 'var(--subtle)', color: 'var(--muted)', borderColor: 'var(--border)' },
    }, { dark })]
    const view = new MergeView({ a: { doc: before, extensions }, b: { doc: after, extensions }, parent: host.current })
    return () => view.destroy()
  }, [after, before, dark])
  return <div className="merge" ref={host} />
}

export default function TextDiff({ files, hunks, degraded, dark, status, selected, onSelect }: { files: FileChange[]; hunks: Hunk[]; degraded: Array<{ path: string; reason_code: string }>; dark: boolean; status: string; selected: string; onSelect: (path: string) => void }) {
  const selectedPath = files.some((file) => file.path === selected) ? selected : ''
  if (!files.length) return <div className="empty">没有文件变化。</div>
  return <section className="text-diffs">
    <div className="diff-controls"><label>变更文件 <select value={selectedPath} onChange={(event) => onSelect(event.target.value)}><option value="">全部变更文件（{files.length}）</option>{files.map((file) => <option key={file.path} value={file.path}>{labels[file.op]} · {file.path}</option>)}</select></label><span>变更片段 · 只读</span></div>
    <p className="diff-note">左：修改前 · 右：修改后 · 仅变更片段</p>
    {status === 'not_requested' && <p className="notice">本次未请求文字层；下方仅列文件变化，选择 L1 或更高层级可查看文字片段。</p>}
    {files.filter((file) => !selectedPath || file.path === selectedPath).map((file) => {
      const fileHunks = hunks.filter((hunk) => hunk.path === file.path || hunk.path === file.before_path)
      const diagnostic = degraded.find((item) => item.path === file.path)
      return <article key={file.path}><h3>{labels[file.op]} · {file.before_path ? `${file.before_path} → ` : ''}{file.path}</h3>
        {diagnostic && <p className="file-note">{reasons[diagnostic.reason_code] ?? diagnostic.reason_code}</p>}
        {fileHunks.length > 0 && <div className="diff-side-labels"><span>修改前</span><span>修改后</span></div>}
        {fileHunks.length ? fileHunks.map((hunk, index) => <Merge key={index} before={hunk.before?.text ?? ''} after={hunk.after?.text ?? ''} dark={dark} />) : <p className="file-note">{status === 'not_requested' ? '文字层未计算。' : diagnostic ? '未生成可展示的文字片段，请参考上方原因。' : '仅路径、文件模式或格式变化，没有逐行文字片段。'}</p>}
      </article>
    })}
  </section>
}
