import { MergeView } from '@codemirror/merge'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { useEffect, useRef, useState } from 'react'

type Hunk = { path: string; before: { text: string } | null; after: { text: string } | null }
type FileChange = { path: string; op: string; before_path?: string }
const labels: Record<string, string> = { add: '新增', delete: '删除', modify: '修改', move: '移动' }
const reasons: Record<string, string> = { unsupported_encoding: '不是可显示的 UTF-8 文本', text_limit_exceeded: '超过文字展示上限', parse_failed: '结构解析失败，仍可查看文字变化', unsupported_file_type: '未支持此文件的结构分析，仍可查看文字变化' }

function Merge({ before, after }: { before: string; after: string }) {
  const host = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!host.current) return
    const extensions = [EditorState.readOnly.of(true), EditorView.editable.of(false)]
    const view = new MergeView({ a: { doc: before, extensions }, b: { doc: after, extensions }, parent: host.current })
    return () => view.destroy()
  }, [after, before])
  return <div className="merge" ref={host} />
}

export default function TextDiff({ files, hunks, degraded }: { files: FileChange[]; hunks: Hunk[]; degraded: Array<{ path: string; reason_code: string }> }) {
  const [selected, setSelected] = useState('')
  const selectedPath = files.some((file) => file.path === selected) ? selected : ''
  if (!files.length) return <div className="empty">没有文件变化。</div>
  return <section className="text-diffs">
    <label>变更文件 <select value={selectedPath} onChange={(event) => setSelected(event.target.value)}><option value="">全部变更文件（{files.length}）</option>{files.map((file) => <option key={file.path} value={file.path}>{labels[file.op]} · {file.path}</option>)}</select></label>
    <p>左侧为修改前，右侧为修改后。以下只展示变更片段，不是该版本的完整文件。</p>
    {files.filter((file) => !selectedPath || file.path === selectedPath).map((file) => {
      const fileHunks = hunks.filter((hunk) => hunk.path === file.path || hunk.path === file.before_path)
      const diagnostic = degraded.find((item) => item.path === file.path)
      return <article key={file.path}><h3>{labels[file.op]} · {file.before_path ? `${file.before_path} → ` : ''}{file.path}</h3>
        {diagnostic && <p className="file-note">{reasons[diagnostic.reason_code] ?? diagnostic.reason_code}</p>}
        {fileHunks.length ? fileHunks.map((hunk, index) => <Merge key={index} before={hunk.before?.text ?? ''} after={hunk.after?.text ?? ''} />) : <p className="file-note">{diagnostic ? '未生成可展示的文字片段，请参考上方原因。' : '仅路径、文件模式或格式变化，没有逐行文字片段。'}</p>}
      </article>
    })}
  </section>
}
