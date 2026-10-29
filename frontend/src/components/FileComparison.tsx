import { goToNextChunk, goToPreviousChunk, MergeView } from '@codemirror/merge'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

type Content = { status: 'text' | 'absent' | 'binary' | 'too_large'; text: string | null; size: number; mode?: string | null }
type FileChange = { path: string; before_path?: string; op: string }
const statuses = { text: '', absent: '此版本不存在', binary: '二进制或非 UTF-8 文件，无法显示文本', too_large: '超过文本展示上限，未截断内容' }
const textFormat = (side: Content) => {
  if (side.status !== 'text') return statuses[side.status]
  const text = side.text ?? ''
  const endings = [...text.matchAll(/\r\n|\r|\n/g)].map(match => match[0])
  const formats = [...new Set(endings)].map(ending => ending === '\r\n' ? 'CRLF' : ending === '\n' ? 'LF' : 'CR')
  return `${side.size} 字节 · ${formats.join('/') || '无换行'}${side.mode != null ? ` · 模式 ${side.mode}` : ''}${text.startsWith('\ufeff') ? ' · BOM' : ''}${text && !/[\r\n]$/.test(text) ? ' · 末尾无换行' : ''}`
}

export default function FileComparison({ workspaceId, base, head, file, dark, baseLabel, headLabel }: {
  workspaceId: string; base: string | null; head: string; file: FileChange
  dark: boolean; baseLabel: string; headLabel: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const merge = useRef<MergeView | null>(null)
  const [content, setContent] = useState<{ key: string; before: Content; after: Content } | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [collapse, setCollapse] = useState(false)
  const [count, setCount] = useState(0)
  const oldPath = file.before_path ?? file.path
  const key = JSON.stringify([workspaceId, base, head, oldPath, file.path])
  const current = content?.key === key ? content : null
  const readable = current && [current.before, current.after].every(side => side.status === 'text' || side.status === 'absent')

  useEffect(() => {
    let active = true
    setError(''); setCount(0)
    const read = (rev: string, path: string) => api<Content>(`/workspaces/${workspaceId}/revisions/${encodeURIComponent(rev)}/content?${new URLSearchParams({ path })}`)
    void Promise.all([
      base ? read(base, oldPath) : Promise.resolve<Content>({ status: 'absent', text: null, size: 0 }), read(head, file.path),
    ]).then(([before, after]) => { if (active) setContent({ key, before, after }) })
      .catch((reason: Error) => { if (active) { setContent(null); setError(reason.message) } })
    return () => { active = false }
  }, [workspaceId, base, head, oldPath, file.path, key, retry])

  useEffect(() => {
    if (!host.current || !readable || !current) return
    const extensions = [lineNumbers(), EditorState.phrases.of({ '$ unchanged lines': '$ 行未修改' }), EditorState.readOnly.of(true), EditorView.editable.of(false),
      EditorView.contentAttributes.of({ tabindex: '0', 'aria-label': '只读文件正文' }),
      keymap.of([{ key: 'F7', run: goToNextChunk }, { key: 'Shift-F7', run: goToPreviousChunk }]),
      EditorView.theme({
        '&': { backgroundColor: 'var(--surface)', color: 'var(--text)' },
        '.cm-scroller': { fontFamily: 'var(--font-mono)', lineHeight: '1.8' },
        '.cm-gutters': { backgroundColor: 'var(--subtle)', color: 'var(--muted)', borderColor: 'var(--border)' },
      }, { dark })]
    const view = new MergeView({
      a: { doc: current.before.text ?? '', extensions }, b: { doc: current.after.text ?? '', extensions },
      parent: host.current, highlightChanges: true, gutter: true,
      collapseUnchanged: collapse ? { margin: 3, minSize: 8 } : undefined,
    })
    merge.current = view; setCount(view.chunks.length)
    return () => { merge.current = null; view.destroy() }
  }, [current, readable, dark, collapse])

  const navigate = (next: boolean) => {
    const view = merge.current
    if (!view?.chunks.length) return
    const editor = view.b
    editor.focus()
    ;(next ? goToNextChunk : goToPreviousChunk)(editor)
  }
  return <section className="full-file-diff" aria-label={`文件差异 ${file.path}`}>
    <div className="file-diff-toolbar"><strong title={file.path}>{file.path}</strong><span>{readable ? `${count} 处差异` : error ? '读取失败' : current ? '无法显示文字差异' : '正在读取…'}</span>
      <button disabled={!readable || !count} onClick={() => navigate(false)} title="Shift+F7">↑ 上一处</button>
      <button disabled={!readable || !count} onClick={() => navigate(true)} title="F7">↓ 下一处</button>
      <label><input type="checkbox" checked={collapse} onChange={event => setCollapse(event.target.checked)} />折叠未修改区域</label>
    </div>
    <div className="full-diff-labels"><span>修改前 · {baseLabel}<small>{oldPath}</small>{current && <small>{textFormat(current.before)}</small>}</span><span>修改后 · {headLabel}<small>{file.path}</small>{current && <small>{textFormat(current.after)}</small>}</span></div>
    {error ? <p className="notice error" role="alert">{error}<button onClick={() => setRetry(value => value + 1)}>重试全文读取</button></p>
      : !current ? <p className="empty" role="status">正在读取两个版本的完整文件…</p>
      : readable ? <><div className="full-merge" ref={host} />{!count && <p className="file-note">没有可见文字变化；请核对路径、文件模式、换行符或末尾换行。</p>}</>
      : <p className="empty">{[...new Set([statuses[current.before.status], statuses[current.after.status]].filter(Boolean))].join('；')}。历史文件仍已保存。</p>}
  </section>
}
