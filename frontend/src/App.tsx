import { useEffect, useRef, useState } from 'react'
import { MergeView } from '@codemirror/merge'
import { EditorView, lineNumbers } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import './styles/workbench.css'

type Workspace = { workspace_id: string; name: string; root_path: string }
type Revision = { rev_id: string; seq: number; ts: string; trigger: string; parent_rev_id: string | null }
type FileEntry = { path: string; oid: string }
type Preview = { content: string | null; reason: string | null; size: number }
async function api<T>(path: string, body?: object): Promise<T> {
  const r = await fetch('/api' + path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined)
  const result = await r.json()
  if (!r.ok || !result.ok) throw new Error(result.error?.message || '请求失败')
  return result.data as T
}
const date = (s: string) => new Date(s).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
const trigger: Record<string, string> = { init: '首次记录', watch: '自动记录', manual: '手动快照', restore: '恢复' }
function Comparison({ before, after }: { before: string; after: string }) {
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!root.current) return
    const extensions = [EditorState.readOnly.of(true), EditorView.editable.of(false), lineNumbers(), EditorView.lineWrapping]
    const view = new MergeView({ parent: root.current, a: { doc: before, extensions }, b: { doc: after, extensions }, highlightChanges: true, gutter: true })
    return () => view.destroy()
  }, [before, after])
  return <div ref={root} className="comparison" />
}
export default function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [ws, setWs] = useState('')
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [rev, setRev] = useState('')
  const [base, setBase] = useState('')
  const [files, setFiles] = useState<FileEntry[]>([])
  const [oldFiles, setOldFiles] = useState<FileEntry[]>([])
  const [path, setPath] = useState('')
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState('read')
  const [current, setCurrent] = useState<Preview | null>(null)
  const [previous, setPrevious] = useState<Preview | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [online, setOnline] = useState(false)
  const [busy, setBusy] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [tick, setTick] = useState(0)
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const list = await api<Workspace[]>('/workspaces')
        if (!alive) return
        setWorkspaces(list); setOnline(true)
        setWs(id => list.some(w => w.workspace_id === id) ? id : list.find(w => w.name.includes('ZIP'))?.workspace_id || list[0]?.workspace_id || '')
      } catch (e) { if (alive) { setOnline(false); setError(String(e)) } }
    }
    void load()
    const timer = window.setInterval(() => { void load(); setTick(t => t + 1) }, 5000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [])
  useEffect(() => {
    if (!ws) return
    let alive = true
    api<Revision[]>('/workspaces/' + ws + '/revisions').then(list => {
      if (!alive) return
      list.sort((a, b) => b.seq - a.seq); setRevisions(list)
      setRev(id => list.some(r => r.rev_id === id) ? id : list[0]?.rev_id || '')
    }).catch(e => { if (alive) setError(String(e)) })
    return () => { alive = false }
  }, [ws, tick])
  const revision = revisions.find(r => r.rev_id === rev)
  useEffect(() => { setBase(revision?.parent_rev_id || '') }, [rev, revision?.parent_rev_id])
  useEffect(() => {
    setFiles([]); setOldFiles([]); setCurrent(null); setPrevious(null)
    if (!ws || !rev) return
    let alive = true
    const prefix = '/workspaces/' + ws + '/revisions/'
    Promise.all([api<{ files: FileEntry[] }>(prefix + rev + '/files'), base ? api<{ files: FileEntry[] }>(prefix + base + '/files') : Promise.resolve({ files: [] })]).then(([a, b]) => {
      if (!alive) return
      setFiles(a.files); setOldFiles(b.files)
      const paths = [...a.files, ...b.files]
      setPath(p => paths.some(f => f.path === p) ? p : paths.find(f => f.path === 'SKILL.md')?.path || paths[0]?.path || '')
      setError('')
    }).catch(e => { if (alive) setError(String(e)) })
    return () => { alive = false }
  }, [ws, rev, base])
  useEffect(() => {
    setCurrent(null); setPrevious(null)
    if (!path || !rev || (!files.length && !oldFiles.length)) return
    let alive = true
    setLoading(true)
    const read = (id: string, entries: FileEntry[]) => id && entries.some(f => f.path === path)
      ? api<Preview>('/workspaces/' + ws + '/revisions/' + id + '/file?path=' + encodeURIComponent(path))
      : Promise.resolve({ content: '', reason: null, size: 0 })
    Promise.all([read(rev, files), read(base, oldFiles)]).then(([a, b]) => {
      if (alive) { setCurrent(a); setPrevious(b); setError('') }
    }).catch(e => { if (alive) setError(String(e)) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [ws, rev, base, path, files, oldFiles])
  const workspace = workspaces.find(w => w.workspace_id === ws)
  const paths = [...new Set([...files, ...oldFiles].map(f => f.path))].sort()
  const state = (p: string) => {
    const a = files.find(f => f.path === p), b = oldFiles.find(f => f.path === p)
    return !base ? '已存档' : !a ? '删除' : !b ? '新增' : a.oid !== b.oid ? '修改' : '未变'
  }
  const changed = paths.filter(p => !['未变', '已存档'].includes(state(p))).length
  const action = async (fn: () => Promise<void>) => {
    setBusy(true); setError(''); setNotice('')
    try { await fn(); setTick(t => t + 1) } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  const selectWorkspace = (id: string) => { setWs(id); setRev(''); setBase(''); setPath(''); setRevisions([]); setFiles([]); setOldFiles([]); setNotice('') }
  return <div className="app">
    <header className="top"><div className="brand"><span className="brand-icon">S</span><strong>SkillForge</strong><span className="subtitle">Skill 版本工作台</span></div><span className={online ? 'connection on' : 'connection'}>{online ? '本地服务在线' : '服务未连接'}</span></header>
    <div className="layout">
      <aside className="sidebar"><div className="section-label">工作区 <span>{workspaces.length}</span></div>
        <nav>{workspaces.map(w => <button className={'workspace ' + (ws === w.workspace_id ? 'active' : '')} key={w.workspace_id} onClick={() => selectWorkspace(w.workspace_id)}><span className="folder">▣</span><span>{w.name}<small title={w.root_path}>{w.root_path}</small></span></button>)}</nav>
        <button className="add" onClick={() => setShowAdd(!showAdd)}>＋ 添加目录</button>
        {showAdd && <form onSubmit={e => { e.preventDefault(); void action(async () => { const result = await api<{ workspace: Workspace }>('/workspaces', { path: newPath }); setWorkspaces(w => [...w, result.workspace]); selectWorkspace(result.workspace.workspace_id); setNewPath(''); setShowAdd(false) }) }}><label>本地目录<input required value={newPath} onChange={e => setNewPath(e.target.value)} placeholder="C:\Skills\my-skill" /></label><button disabled={busy}>添加</button></form>}
        <div className="sidebar-foot">本地存储 · 历史快照<br/><span>ZIP 来源需先同步到监听目录</span></div>
      </aside>
      <main><div className="workspace-header"><div><div className="section-label">正在查看</div><h1>{workspace?.name || '选择工作区'}</h1><p className="root-path">{workspace?.root_path || '暂无工作区'}</p></div><button className="primary" disabled={!ws || busy || !online} onClick={() => void action(async () => { const result = await api<{ created: boolean }>('/workspaces/' + ws + '/snapshots', {}); setNotice(result.created ? '已记录新快照' : '内容未变化，没有新增快照') })}>记录当前内容</button></div>
        {error && <div role="alert" className="error">{error}</div>}{notice && <div role="status" className="notice">{notice}</div>}
        <div className="summary"><span><b>{revisions.length}</b> 次记录</span><span><b>{files.length}</b> 个文件</span><span>{base ? <><b>{changed}</b> 个文件变化</> : '首次记录 · 暂无前版'}</span><span className="summary-time">最近记录 {revisions[0] ? date(revisions[0].ts) : '—'}</span></div>
        <div className="reader-layout"><section className="navigator"><div className="section-label">版本历史</div><div className="revision-list">{revisions.map(r => <button key={r.rev_id} className={'revision ' + (rev === r.rev_id ? 'active' : '')} onClick={() => setRev(r.rev_id)}><span className="revision-top"><b>版本 {r.seq}</b><small>{trigger[r.trigger] || r.trigger}</small></span><time>{date(r.ts)}</time><small>{r.rev_id.slice(0, 10)}</small></button>)}</div>
          <div className="section-label file-title">文件 <span>{paths.length}</span></div><input className="search" aria-label="搜索文件" placeholder="搜索文件…" value={query} onChange={e => setQuery(e.target.value)} /><div className="file-list">{paths.filter(p => p.toLowerCase().includes(query.toLowerCase())).map(p => <button key={p} title={p} className={'file ' + (path === p ? 'active' : '')} onClick={() => setPath(p)}><span>{p}</span><small className={'file-state state-' + state(p)}>{state(p)}</small></button>)}</div>
        </section><section className="document"><div className="document-toolbar"><div className="filename">{path || '选择文件'}<small>版本 {revision?.seq || '—'} · {current ? current.size.toLocaleString() + ' bytes' : '只读快照'}</small></div><div className="tabs"><button className={mode === 'read' ? 'selected' : ''} onClick={() => setMode('read')}>正文</button><button className={mode === 'diff' ? 'selected' : ''} onClick={() => setMode('diff')}>版本对比</button></div></div>
          {mode === 'diff' && <div className="compare-toolbar"><label>对比基准 <select aria-label="对比基准" value={base} onChange={e => setBase(e.target.value)}><option value="">无基准</option>{revisions.filter(r => r.rev_id !== rev).map(r => <option value={r.rev_id} key={r.rev_id}>版本 {r.seq} · {date(r.ts)}</option>)}</select></label><span>左：基准版本　右：所选版本</span></div>}
          {loading ? <div className="empty">正在读取快照…</div> : current ? mode === 'read' ? current.reason ? <div className="empty">{current.reason}</div> : <pre className="source">{files.some(f => f.path === path) ? current.content || '（空文件）' : '此版本已删除该文件；切换版本对比可查看删除内容。'}</pre> : !base ? <div className="empty">选择一个基准版本查看差异</div> : current.reason || previous?.reason ? <div className="empty">{current.reason || previous?.reason}</div> : <Comparison before={previous?.content || ''} after={current.content || ''} /> : <div className="empty">选择一个版本和文件</div>}
        </section></div>
      </main>
    </div>
  </div>
}
