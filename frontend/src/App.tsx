import { useEffect, useState } from 'react'

type Workspace = { workspace_id: string; name?: string; root_path?: string }
type ApiResult = { ok: boolean; data?: any; error?: { message?: string } | null }

async function api(path: string, options?: RequestInit): Promise<any> {
  const response = await fetch(`/api${path}`, { headers: { 'Content-Type': 'application/json' }, ...options })
  const result: ApiResult = await response.json()
  if (!response.ok || !result.ok) throw new Error(result.error?.message || `请求失败 (${response.status})`)
  return result.data
}

export default function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [selected, setSelected] = useState<Workspace | null>(null)
  const [path, setPath] = useState('')
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState<any>(null)
  const [history, setHistory] = useState<any[]>([])
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const refresh = async (workspace = selected) => {
    const list = await api('/workspaces'); setWorkspaces(list || [])
    const current = workspace || list?.[0]
    if (current) { setSelected(current); const [nextStatus, nextHistory] = await Promise.all([api(`/workspaces/${current.workspace_id}/status`), api(`/workspaces/${current.workspace_id}/revisions?limit=20`)]); setStatus(nextStatus); setHistory(nextHistory || []) }
  }
  useEffect(() => { refresh().catch((error) => setNotice(error.message)) }, [])
  useEffect(() => {
    const timer = window.setInterval(() => refresh().catch((error) => setNotice(error.message)), 2000)
    return () => window.clearInterval(timer)
  }, [selected?.workspace_id])
  const run = async (action: () => Promise<void>) => { setBusy(true); setNotice(''); try { await action() } catch (error) { setNotice(error instanceof Error ? error.message : '操作失败') } finally { setBusy(false) } }
  const addWorkspace = () => run(async () => { const created = await api('/workspaces', { method: 'POST', body: JSON.stringify({ path }) }); setPath(''); setNotice('工作区已纳管，首个快照已生成'); await refresh(created) })
  const snapshot = () => selected && run(async () => { await api(`/workspaces/${selected.workspace_id}/snapshots`, { method: 'POST', body: JSON.stringify({ message: message || null }) }); setMessage(''); setNotice('快照已完成'); await refresh(selected) })
  const tag = (name: string) => selected && run(async () => { await api(`/workspaces/${selected.workspace_id}/refs`, { method: 'POST', body: JSON.stringify({ name, rev: null }) }); setNotice(`已标记 ${name}`); await refresh(selected) })
  return <main><header><div><span className="eyebrow">LOCAL SKILL VERSION MANAGER</span><h1>SkillForge</h1><p>保存即快照，比较即结论</p></div><span className="live">● 本地服务在线</span></header><section className="grid"><aside className="panel"><h2>工作区</h2><p className="muted">绑定一个包含 Skill 文件的本地目录。</p><label>目录路径<input value={path} onChange={(event) => setPath(event.target.value)} placeholder={'例如 C:\\Skills\\my-skill'} /></label><button disabled={!path || busy} onClick={addWorkspace}>纳管目录</button><div className="workspace-list">{workspaces.map((workspace) => <button className={selected?.workspace_id === workspace.workspace_id ? 'workspace selected' : 'workspace'} key={workspace.workspace_id} onClick={() => run(() => refresh(workspace))}><strong>{workspace.name || workspace.workspace_id}</strong><small>{workspace.root_path || workspace.workspace_id}</small></button>)}{!workspaces.length && <p className="empty">还没有纳管工作区</p>}</div></aside><section className="panel content"><div className="content-head"><div><span className="eyebrow">WORKSPACE STATUS</span><h2>{selected?.name || '选择一个工作区'}</h2><p className="muted">{selected?.root_path || '纳管目录后，这里会显示快照状态。'}</p></div><span className="badge">{status?.has_pending_changes ? '有未保存变更' : '工作区已同步'}</span></div>{notice && <div className="notice">{notice}</div>}{selected && <><div className="actions"><button disabled={busy} onClick={snapshot}>立即生成快照</button><input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="快照备注（可选）" /><button className="secondary" disabled={busy} onClick={() => tag('stable')}>标记为 stable</button><button className="secondary" disabled={busy} onClick={() => tag('tested')}>标记为 tested</button></div><div className="stats"><div><small>当前 Skill</small><strong>{selected.name || '未命名'}</strong></div><div><small>当前状态</small><strong>{status?.has_pending_changes ? '有改动' : '无改动'}</strong></div><div><small>快照数量</small><strong>{history.length}</strong></div></div><h3>快照历史</h3><div className="history">{history.length ? history.map((revision: any) => <div className="revision" key={revision.revision_id || revision.id}><span className="dot" /><div><strong>{revision.revision_id || revision.id}</strong><small>{revision.message || '自动快照'}</small></div></div>) : <p className="empty">暂无快照记录</p>}</div><div className="limitation"><strong>当前版本说明</strong><span>页面每 2 秒自动刷新；快照、工作区管理和基线标记已可用。</span></div></>}</section></section></main>
}
