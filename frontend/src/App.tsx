import { useCallback, useEffect, useMemo, useState } from 'react'

import TextDiff from './components/TextDiff'
import './styles.css'

type Envelope<T> = { ok: boolean; data: T; error: { message: string } | null }
type Workspace = { workspace_id: string; name: string; root_path: string }
type Revision = { rev_id: string; seq: number; ts: string; trigger: string; source: string }
type Span = { path: string; start_byte: number; end_byte: number; text: string }
type Unit = { id: string; path: string; kind: string; op: string; before: Span | null; after: Span | null }
type Cluster = { id: string; label: string; units: string[] }
type Plan = { no_change: boolean; plan_id: string; changes: Array<{ action: string; path: string }> }
type Report = {
  report_id: string; summary: string; base: { rev: string | null }; head: { rev: string }
  overview: { files: number; changes: number | null; clusters: number; risk: string; risk_counts: Record<string, number>; needs_review: number }
  clusters: Cluster[]
  risk: { items: Array<{ unit: string; level: string; reason: string }> }
  layers: { semantic: { status: string; units: Unit[] }; text: { status: string; hunks: Array<{ path: string; op: string; before: Span | null; after: Span | null }> } }
  needs_review: Array<{ path: string; reason_code: string }>
  degraded: Array<{ path: string; reason_code: string; available_layer: string }>
}

const labels: Record<string, string> = { add: '新增', delete: '删除', modify: '修改', move: '移动', high: '高', medium: '中', low: '低', unknown: '未知' }

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  const body = (await response.json()) as Envelope<T>
  if (!response.ok || !body.ok) throw new Error(body.error?.message ?? `请求失败 ${response.status}`)
  return body.data
}

export default function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [workspaceId, setWorkspaceId] = useState('')
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState<'semantic' | 'text'>('semantic')
  const [selected, setSelected] = useState<string[]>([])
  const [anchor, setAnchor] = useState('')

  const loadRevisions = useCallback(async (ws: string) => setRevisions(await api<Revision[]>(`/workspaces/${ws}/revisions`)), [])
  const loadReport = useCallback(async (ws: string, base?: string, head?: string) => {
    setLoading(true); setError('')
    const query = new URLSearchParams({ layer: 'L3' })
    if (base) query.set('base', base); if (head) query.set('head', head)
    try { setReport(await api<Report>(`/workspaces/${ws}/diff?${query}`)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '报告生成失败') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { api<Workspace[]>('/workspaces').then((rows) => { setWorkspaces(rows); if (rows[0]) setWorkspaceId(rows[0].workspace_id) }).catch((reason: Error) => setError(reason.message)) }, [])
  useEffect(() => {
    if (!workspaceId) return
    void loadRevisions(workspaceId); void loadReport(workspaceId)
    const stream = new EventSource(`/api/workspaces/${workspaceId}/events`)
    stream.onmessage = (message) => {
      const event = JSON.parse(message.data) as { type: string }
      if (event.type === 'snapshot/created') { void loadRevisions(workspaceId); void loadReport(workspaceId) }
    }
    stream.onerror = () => setError('实时连接已断开；重连后会读取最新状态。')
    return () => stream.close()
  }, [loadReport, loadRevisions, workspaceId])

  const units = useMemo(() => new Map(report?.layers.semantic.units.map((unit) => [unit.id, unit]) ?? []), [report])
  const risks = useMemo(() => new Map(report?.risk.items.map((risk) => [risk.unit, risk]) ?? []), [report])
  const latest = revisions.at(-1)?.rev_id

  const compareSelected = () => {
    const rows = revisions.filter((row) => selected.includes(row.rev_id)).sort((a, b) => a.seq - b.seq)
    if (rows.length === 2) void loadReport(workspaceId, rows[0].rev_id, rows[1].rev_id)
  }
  const createAnchor = async () => {
    if (!anchor.trim()) return
    try { await api(`/workspaces/${workspaceId}/refs`, { method: 'POST', body: JSON.stringify({ name: anchor.trim() }) }); setAnchor(''); await loadReport(workspaceId) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '锚点创建失败') }
  }
  const confirmPlan = async (plan: Plan) => {
    if (plan.no_change) return
    const list = plan.changes.map((item) => `${labels[item.action] ?? item.action} ${item.path}`).join('\n')
    if (!window.confirm(`将回写整个 Skill：\n${list}\n\n确认继续？`)) return
    await api(`/workspaces/${workspaceId}/restore/plans/${plan.plan_id}/apply`, { method: 'POST', body: JSON.stringify({ confirm: true }) })
  }
  const restore = async (rev: string) => {
    try { await confirmPlan(await api<Plan>(`/workspaces/${workspaceId}/restore/preview`, { method: 'POST', body: JSON.stringify({ rev }) })) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '恢复失败') }
  }
  const undo = async () => {
    try { await confirmPlan(await api<Plan>(`/workspaces/${workspaceId}/undo/preview`, { method: 'POST', body: '{}' })) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '撤销失败') }
  }

  return <main>
    <header><div><span className="eyebrow">LOCAL SKILL HISTORY</span><h1>SkillForge VM</h1></div><select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>{workspaces.map((workspace) => <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.name}</option>)}</select></header>
    {error && <div className="notice error">{error}</div>}
    {loading && report && <div className="notice">旧结果 · 正在更新…</div>}
    {!report && loading && <div className="empty">正在生成第一份报告…</div>}
    {report && <>
      <section className="hero"><div><span className={`risk ${report.overview.risk}`}>{labels[report.overview.risk]}风险</span><h2>{report.summary}</h2></div><div className="metrics"><b>{report.overview.files}<small>文件</small></b><b>{report.overview.changes ?? '—'}<small>语义变化</small></b><b>{report.overview.clusters}<small>修改目的</small></b><b>{report.overview.needs_review}<small>待确认</small></b></div></section>
      <nav className="tabs"><button className={view === 'semantic' ? 'active' : ''} onClick={() => setView('semantic')}>语义结论</button><button className={view === 'text' ? 'active' : ''} onClick={() => setView('text')}>原文差异</button></nav>
      {view === 'semantic' ? <section className="clusters">
        {report.clusters.map((cluster) => <article key={cluster.id}><h3>{cluster.label}<span>{cluster.units.length} 处</span></h3>{cluster.units.map((id) => { const unit = units.get(id); const risk = risks.get(id); if (!unit) return null; return <details key={id}><summary><em>{labels[unit.op] ?? unit.op}</em>{unit.path}<span className={`risk ${risk?.level ?? 'low'}`}>{labels[risk?.level ?? 'low']}</span></summary><div className="evidence">{unit.before && <pre><small>修改前</small>{unit.before.text}</pre>}{unit.after && <pre><small>修改后</small>{unit.after.text}</pre>}{risk && <p>{risk.reason}</p>}</div></details> })}</article>)}
        {report.needs_review.map((item, index) => <article className="review" key={`${item.path}-${index}`}><h3>待确认 · {item.path}</h3><p>系统不能可靠判断这是不是移动，请展开原文自行确认。</p></article>)}
        {report.degraded.map((item) => <article className="review" key={item.path}><h3>已降级 · {item.path}</h3><p>{item.reason_code}，当前可查看到 {item.available_layer}。</p></article>)}
      </section> : <TextDiff hunks={report.layers.text.hunks} />}
    </>}
    <section className="toolbar"><div><h2>建立基线</h2><p>为当前版本命名，之后的修改都会与它比较。</p></div><div className="inline"><input value={anchor} onChange={(event) => setAnchor(event.target.value)} placeholder="例如 tested" /><button onClick={() => void createAnchor()}>创建锚点</button></div></section>
    <section className="history"><div className="section-title"><div><h2>历史版本</h2><p>选择两个版本比较，或从任意版本与当前版本比较。</p></div><button disabled={selected.length !== 2} onClick={compareSelected}>比较所选版本</button></div>
      {revisions.map((revision) => <div className="revision" key={revision.rev_id}><input type="checkbox" checked={selected.includes(revision.rev_id)} onChange={() => setSelected((current) => current.includes(revision.rev_id) ? current.filter((id) => id !== revision.rev_id) : current.length < 2 ? [...current, revision.rev_id] : current)} /><b>#{revision.seq}</b><time>{new Date(revision.ts).toLocaleString()}</time><span>{revision.trigger}/{revision.source}</span><button disabled={revision.rev_id === latest} onClick={() => latest && void loadReport(workspaceId, revision.rev_id, latest)}>与当前比较</button><button onClick={() => void restore(revision.rev_id)}>恢复到这里</button></div>)}
      <button className="undo" onClick={() => void undo()}>撤销最近一次恢复</button>
    </section>
  </main>
}
