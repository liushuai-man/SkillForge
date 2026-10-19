import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import AddWorkspace from './components/AddWorkspace'
import WorkspaceTools from './components/WorkspaceTools'
import RestoreDialog from './components/RestoreDialog'
import type { RestorePlan } from './components/RestoreDialog'
import { api } from './lib/api'
import { useTheme } from './lib/theme'
import type { Theme } from './lib/theme'
import './styles.css'

const TextDiff = lazy(() => import('./components/TextDiff'))

type Workspace = { workspace_id: string; name: string; root_path: string }
type Revision = { rev_id: string; ws_id: string; seq: number; ts: string; trigger: string; source: string; parent_rev_id: string | null }
type Ref = { name: string; rev_id: string }
type Span = { path: string; start_byte: number; end_byte: number; text: string }
type Unit = { id: string; path: string; kind: string; op: string; before: Span | null; after: Span | null }
type Cluster = { id: string; label: string; units: string[] }
type Report = {
  report_id: string; layer: string; summary: string; base: { rev: string | null }; head: { rev: string }
  overview: { files: number; changes: number | null; clusters: number; risk: string; risk_counts: Record<string, number>; needs_review: number }
  clusters: Cluster[]
  risk: { items: Array<{ unit: string; level: string; reason: string }> }
  layers: { metadata: { files: Array<{ path: string; op: string; before_path?: string }> }; semantic: { status: string; units: Unit[] }; text: { status: string; hunks: Array<{ path: string; op: string; before: Span | null; after: Span | null }> } }
  needs_review: Array<{ path: string; reason_code: string }>
  degraded: Array<{ path: string; reason_code: string; available_layer: string }>
}

const labels: Record<string, string> = { add: '新增', delete: '删除', modify: '修改', move: '移动', high: '高', medium: '中', low: '低', unknown: '未知' }

export default function App() {
  const { theme, setTheme, resolved, storageWarning } = useTheme()
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [workspaceId, setWorkspaceId] = useState('')
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState<'semantic' | 'text'>('semantic')
  const [selected, setSelected] = useState<string[]>([])
  const [anchor, setAnchor] = useState('')
  const [anchorRev, setAnchorRev] = useState('')
  const [baseSpec, setBaseSpec] = useState('')
  const [headSpec, setHeadSpec] = useState('')
  const [compareLayer, setCompareLayer] = useState('L3')
  const [notice, setNotice] = useState('')
  const [workspacesLoading, setWorkspacesLoading] = useState(true)
  const [refreshToken, setRefreshToken] = useState(0)
  const [pendingRestore, setPendingRestore] = useState<string | null>(null)
  const [plan, setPlan] = useState<RestorePlan | null>(null)
  const [streamError, setStreamError] = useState('')
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState(false)
  const [refs, setRefs] = useState<Ref[]>([])
  const [historyUpper, setHistoryUpper] = useState<number | null>(null)
  const [historyPage, setHistoryPage] = useState(0)
  const [summaries, setSummaries] = useState<Record<string, string>>({})
  const summaryCache = useRef<Record<string, string>>({})
  const activeWorkspace = useRef('')
  const reportRequest = useRef(0)
  const revisionRequest = useRef(0)
  const workspaceRequest = useRef(0)
  const actionInFlight = useRef(false)
  const comparison = useRef<{ base?: string; head?: string; layer: string }>({ layer: 'L3' })
  const locked = busy || plan !== null

  const loadRevisions = useCallback(async (ws: string) => {
    const request = ++revisionRequest.current
    try {
      const [rows, names] = await Promise.all([
        api<Revision[]>(`/workspaces/${ws}/revisions`), api<Ref[]>(`/workspaces/${ws}/refs`),
      ])
      if (activeWorkspace.current === ws && request === revisionRequest.current) {
        setRevisions(rows); setRefs(names)
        setHistoryUpper((current) => current ?? rows.at(-1)?.seq ?? null)
      }
    } catch (reason) {
      if (activeWorkspace.current === ws && request === revisionRequest.current) setError(reason instanceof Error ? reason.message : '历史读取失败')
    }
  }, [])
  const loadReport = useCallback(async (ws: string, base?: string, head?: string, layer = 'L3') => {
    comparison.current = { base, head, layer }
    const request = ++reportRequest.current
    const isCurrent = () => activeWorkspace.current === ws && request === reportRequest.current
    setLoading(true); setError(''); setStale(true)
    const query = new URLSearchParams({ layer })
    if (base) query.set('base', base); if (head) query.set('head', head)
    try {
      const next = await api<Report>(`/workspaces/${ws}/diff?${query}`)
      if (isCurrent()) { setReport(next); setStale(false) }
    }
    catch (reason) { if (isCurrent()) setError(reason instanceof Error ? reason.message : '报告生成失败') }
    finally { if (isCurrent()) setLoading(false) }
  }, [])

  const loadWorkspaces = useCallback(async () => {
    const request = ++workspaceRequest.current
    setWorkspacesLoading(true)
    try {
      const rows = await api<Workspace[]>('/workspaces')
      if (request !== workspaceRequest.current) return
      setWorkspaces(rows); setError('')
      setWorkspaceId((current) => rows.some((row) => row.workspace_id === current) ? current : rows[0]?.workspace_id ?? '')
    } catch (reason) { if (request === workspaceRequest.current) setError(reason instanceof Error ? reason.message : '工作区读取失败') }
    finally { if (request === workspaceRequest.current) setWorkspacesLoading(false) }
  }, [])
  useEffect(() => { void loadWorkspaces(); return () => { ++workspaceRequest.current } }, [loadWorkspaces])
  useEffect(() => {
    if (!workspaceId) return
    activeWorkspace.current = workspaceId
    comparison.current = { layer: 'L3' }
    summaryCache.current = {}
    setRevisions([]); setRefs([]); setSummaries({}); setHistoryUpper(null); setHistoryPage(0); setSelected([]); setReport(null); setAnchor(''); setAnchorRev(''); setBaseSpec(''); setHeadSpec(''); setCompareLayer('L3'); setPendingRestore(null); setNotice(''); setError(''); setStreamError('')
    const refresh = () => { const { base, head, layer } = comparison.current; void loadRevisions(workspaceId); void loadReport(workspaceId, base, head, layer); setRefreshToken((value) => value + 1) }
    refresh()
    const stream = new EventSource(`/api/workspaces/${workspaceId}/events`)
    stream.onopen = () => { if (activeWorkspace.current === workspaceId) { setStreamError(''); refresh() } }
    stream.onmessage = (message) => {
      if (activeWorkspace.current !== workspaceId) return
      try {
        const event = JSON.parse(message.data) as { type: string }
        if (event.type === 'snapshot/created') refresh()
      } catch { setStreamError('实时通知无法读取，请刷新当前对比。') }
    }
    stream.onerror = () => { if (activeWorkspace.current === workspaceId) setStreamError('实时连接已断开；重连后会读取最新状态。') }
    return () => { stream.close(); activeWorkspace.current = ''; ++reportRequest.current; ++revisionRequest.current }
  }, [loadReport, loadRevisions, workspaceId])

  const units = useMemo(() => new Map(report?.layers.semantic.units.map((unit) => [unit.id, unit]) ?? []), [report])
  const risks = useMemo(() => new Map(report?.risk.items.map((risk) => [risk.unit, risk]) ?? []), [report])
  const latest = revisions.at(-1)?.rev_id
  const workspace = workspaces.find((item) => item.workspace_id === workspaceId)
  const revisionLabel = (rev: string | null) => {
    if (rev === null) return '空基线'
    const row = revisions.find((item) => item.rev_id === rev)
    return row ? `版本 #${row.seq}` : rev.slice(0, 12)
  }
  const historyRows = revisions.filter((row) => historyUpper !== null && row.seq <= historyUpper).slice().reverse()
  const pageRows = useMemo(() => revisions.filter((row) => row.ws_id === workspaceId && historyUpper !== null && row.seq <= historyUpper).slice().reverse().slice(historyPage * 20, (historyPage + 1) * 20), [revisions, historyPage, historyUpper, workspaceId])
  useEffect(() => {
    let active = true
    void (async () => {
      for (const row of pageRows) {
        if (!active) break
        if (summaryCache.current[row.rev_id]) continue
        let summary = '首次纳管，保存目录的初始内容。'
        if (row.parent_rev_id) {
          try {
            const query = new URLSearchParams({ base: row.parent_rev_id, head: row.rev_id })
            summary = (await api<{ summary: string }>(`/workspaces/${workspaceId}/diff/summary?${query}`)).summary
          } catch { summary = '摘要暂不可用，可重载页面重试或打开版本比较。' }
        }
        if (active && activeWorkspace.current === workspaceId) {
          summaryCache.current[row.rev_id] = summary
          setSummaries((current) => ({ ...current, [row.rev_id]: summary }))
        }
      }
    })()
    return () => { active = false }
    // Each page reads immutable revision pairs once; summary updates must not restart it.
  }, [pageRows, workspaceId])
  const runAction = async (action: () => Promise<void>, refreshReport = true) => {
    if (actionInFlight.current) return
    actionInFlight.current = true
    setBusy(true); setError(''); setNotice('')
    try { await action(); await loadRevisions(workspaceId); if (refreshReport) { const { base, head, layer } = comparison.current; await loadReport(workspaceId, base, head, layer) } }
    catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败') }
    finally { setBusy(false); actionInFlight.current = false; setRefreshToken((value) => value + 1) }
  }

  const createWorkspace = async (path: string, name: string) => {
    if (actionInFlight.current || plan) return false
    actionInFlight.current = true; setBusy(true); setError(''); setNotice('')
    try {
      const result = await api<{ workspace: Workspace; file_count: number }>('/workspaces', { method: 'POST', body: JSON.stringify({ path, name: name || null }) })
      ++workspaceRequest.current
      setWorkspaces((current) => [...current.filter((row) => row.workspace_id !== result.workspace.workspace_id), result.workspace])
      activeWorkspace.current = result.workspace.workspace_id
      setWorkspaceId(result.workspace.workspace_id)
      setNotice(`已纳管 ${result.workspace.name}，初始快照包含 ${result.file_count} 个文件。`)
      return true
    } catch (reason) { setError(reason instanceof Error ? reason.message : '纳管失败'); return false }
    finally { setBusy(false); actionInFlight.current = false; setWorkspacesLoading(false) }
  }

  const compareSelected = () => {
    const rows = revisions.filter((row) => selected.includes(row.rev_id)).sort((a, b) => a.seq - b.seq)
    if (rows.length === 2) void loadReport(workspaceId, rows[0].rev_id, rows[1].rev_id)
  }
  const createAnchor = async () => {
    if (!anchor.trim()) return
    await runAction(async () => { await api(`/workspaces/${workspaceId}/refs`, { method: 'POST', body: JSON.stringify({ name: anchor.trim(), rev: anchorRev.trim() || null }) }); setNotice(`锚点 ${anchor.trim()} 已设为默认基线。`); setAnchor(''); setAnchorRev('') })
  }
  const previewPlan = (next: RestorePlan) => {
    if (next.no_change) setNotice('目标与当前内容一致，无需恢复。')
    else setPlan(next)
  }
  const restore = async (rev: string) => {
    await runAction(async () => { previewPlan(await api<RestorePlan>(`/workspaces/${workspaceId}/restore/preview`, { method: 'POST', body: JSON.stringify({ rev }) })) }, false)
  }
  const undo = async () => {
    await runAction(async () => { previewPlan(await api<RestorePlan>(`/workspaces/${workspaceId}/undo/preview`, { method: 'POST', body: '{}' })) }, false)
  }
  const resume = async (planId: string) => {
    await runAction(async () => { previewPlan(await api<RestorePlan>(`/workspaces/${workspaceId}/restore/plans/${encodeURIComponent(planId)}`)) }, false)
  }
  const applyPlan = async () => {
    if (!plan?.plan_id) return
    await runAction(async () => {
      const result = await api<{ created: boolean; revision: { seq: number } }>(`/workspaces/${workspaceId}/restore/plans/${encodeURIComponent(plan.plan_id!)}/apply`, { method: 'POST', body: JSON.stringify({ confirm: true }) })
      setPlan(null); setNotice(result.created ? `恢复完成，已记录版本 #${result.revision.seq}。` : '该计划此前已完成，本次未回写文件。')
    })
  }

  return <main>
    <header><div><span className="eyebrow">LOCAL SKILL HISTORY</span><h1>SkillForge VM</h1></div><div className="header-controls"><label>工作区<select disabled={locked || !workspaces.length} value={workspaceId} onChange={(event) => { activeWorkspace.current = event.target.value; setWorkspaceId(event.target.value) }}>{!workspaces.length && <option value="">尚未纳管目录</option>}{workspaces.map((workspace) => <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.name}</option>)}</select></label><label>界面主题<select value={theme} onChange={(event) => setTheme(event.target.value as Theme)}><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></label></div></header>
    {storageWarning && <p className="notice" role="status">{storageWarning}</p>}
    {error && <div className="notice error" role="alert">{error}</div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    <div className="connection-bar"><span>{workspacesLoading ? '正在连接本机服务…' : `${workspaces.length} 个已纳管目录`}</span><button disabled={locked || workspacesLoading} onClick={() => void loadWorkspaces()}>刷新工作区列表</button></div>
    {!workspacesLoading && <AddWorkspace busy={locked} empty={!workspaces.length} onCreate={createWorkspace} />}
    {workspace && <section className="workspace-info"><p>监听目录：<code>{workspace.root_path}</code></p><p>保存文件会自动记录快照；ZIP 需先解压。界面和终端共用同一份本机数据。</p><button disabled={locked || loading} onClick={() => { const { base, head, layer } = comparison.current; void loadRevisions(workspaceId); void loadReport(workspaceId, base, head, layer); setRefreshToken((value) => value + 1) }}>刷新当前对比</button></section>}
    {workspace && <WorkspaceTools key={workspaceId} workspaceId={workspaceId} busy={locked} refreshToken={refreshToken} onAction={runAction} onRestore={restore} onResume={resume} onPendingChange={setPendingRestore} />}
    {streamError && <div className="notice">{streamError}</div>}
    {stale && report && <div className="notice">旧结果 · {loading ? '正在更新…' : '更新失败，请刷新重试。'}</div>}
    {!report && loading && <div className="empty">正在生成第一份报告…</div>}
    {report && <>
      <p className="comparison">{revisionLabel(report.base.rev)} → {revisionLabel(report.head.rev)} · {report.layer} · {report.base.rev === null ? '尚未建立基线，比较全部已纳管内容。' : '下方结论与原文均对应这两个版本。'}</p>
      <section className="hero"><div><span className={`risk ${report.overview.risk}`}>{labels[report.overview.risk]}风险</span><h2>{report.summary}</h2></div><div className="metrics"><b>{report.overview.files}<small>文件</small></b><b>{report.overview.changes ?? '—'}<small>语义变化</small></b><b>{report.overview.clusters}<small>修改目的</small></b><b>{report.overview.needs_review}<small>待确认</small></b></div></section>
      <div className="risk-counts">{['high', 'medium', 'low', 'unknown'].map((level) => <span className={`risk ${level}`} key={level}>{labels[level]}风险 {report.overview.risk_counts[level] ?? 0}</span>)}<span>未接入行为对比</span></div>
      <nav className="tabs" aria-label="对比视图"><button aria-pressed={view === 'semantic'} className={view === 'semantic' ? 'active' : ''} onClick={() => setView('semantic')}>语义结论</button><button aria-pressed={view === 'text'} className={view === 'text' ? 'active' : ''} onClick={() => setView('text')}>原文差异</button></nav>
      {view === 'semantic' ? <section className="clusters">
        {report.clusters.map((cluster) => <article key={cluster.id}><h3>{cluster.label}<span>{cluster.units.length} 处</span></h3>{cluster.units.map((id) => { const unit = units.get(id); const risk = risks.get(id); if (!unit) return null; return <details key={id}><summary><em>{labels[unit.op] ?? unit.op}</em>{unit.path}<span className={`risk ${risk?.level ?? 'low'}`}>{labels[risk?.level ?? 'low']}</span></summary><div className="evidence">{unit.before && <pre><small>修改前</small>{unit.before.text}</pre>}{unit.after && <pre><small>修改后</small>{unit.after.text}</pre>}{risk && <p>{risk.reason}</p>}</div></details> })}</article>)}
        {report.needs_review.map((item, index) => <article className="review" key={`${item.path}-${index}`}><h3>待确认 · {item.path}</h3><p>系统不能可靠判断这是不是移动，请展开原文自行确认。</p></article>)}
        {report.degraded.map((item) => <article className="review" key={item.path}><h3>已降级 · {item.path}</h3><p>{item.reason_code}，当前可查看到 {item.available_layer}。</p></article>)}
        {!report.clusters.length && <article><h3>{report.layers.semantic.status === 'not_requested' ? '本次未计算语义层' : report.overview.files === 0 ? '没有文件变化' : '没有可展示的语义分组'}</h3><p className="empty">{report.layers.semantic.status === 'not_requested' ? '可以查看变更文件，或选择 L3 生成语义结论；未计算不等于无变化。' : report.overview.files === 0 ? '保存相同内容不会产生新版本。' : '请切换原文差异查看文件变化；降级或未识别不代表没有变化。'}</p></article>}
      </section> : <Suspense fallback={<p role="status">正在载入原文差异…</p>}><TextDiff files={report.layers.metadata.files} hunks={report.layers.text.hunks} degraded={report.degraded} dark={resolved === 'dark'} status={report.layers.text.status} /></Suspense>}
    </>}
    {workspace && <><section className="panel"><h2>指定版本比较</h2><form className="form-grid" onSubmit={(event) => { event.preventDefault(); if (!locked) void loadReport(workspaceId, baseSpec.trim() || undefined, headSpec.trim() || undefined, compareLayer) }}><label>比较基线<input disabled={locked} list="revision-options" value={baseSpec} onChange={(event) => setBaseSpec(event.target.value)} placeholder="默认基线，或选锚点/修订" /></label><label>目标版本<input disabled={locked} list="revision-options" value={headSpec} onChange={(event) => setHeadSpec(event.target.value)} placeholder="当前 @，或选修订" /></label><label>分析层级<select disabled={locked} value={compareLayer} onChange={(event) => setCompareLayer(event.target.value)}><option value="L3">L3 · 语义结论</option><option value="L2">L2 · 结构分析</option><option value="L1">L1 · 文字差异</option><option value="L0">L0 · 文件变化</option></select></label><button type="submit" disabled={locked}>比较指定版本</button></form><datalist id="revision-options"><option value="@">当前版本</option>{refs.filter((ref) => ref.name !== 'last').map((ref) => <option key={ref.name} value={ref.name} />)}{revisions.map((row) => <option key={row.rev_id} value={row.rev_id}>版本 #{row.seq}</option>)}</datalist></section>
    <section className="panel toolbar"><div><h2>建立基线</h2><p>为指定版本命名，并选为之后修改的默认比较基线。</p></div><form className="form-grid" onSubmit={(event) => { event.preventDefault(); if (!locked && !pendingRestore) void createAnchor() }}><label>锚点名称<input disabled={locked} value={anchor} onChange={(event) => setAnchor(event.target.value)} placeholder="例如 tested" /></label><label>锚点目标<input disabled={locked} list="revision-options" value={anchorRev} onChange={(event) => setAnchorRev(event.target.value)} placeholder="留空使用当前磁盘内容" /></label><button className="primary" type="submit" disabled={locked || Boolean(pendingRestore) || !anchor.trim()}>创建锚点</button></form></section>
    <section className="history"><div className="section-title"><div><h2>历史版本</h2><p>选择两个版本比较，或从任意版本与当前版本比较。</p></div><button disabled={locked || selected.length !== 2} onClick={compareSelected}>比较所选版本</button></div>
      {historyUpper !== null && (revisions.at(-1)?.seq ?? 0) > historyUpper && <div className="notice">有新版本。<button onClick={() => { setHistoryUpper(revisions.at(-1)?.seq ?? null); setHistoryPage(0) }}>查看最新历史</button></div>}
      {pageRows.map((revision) => <div className="revision" key={revision.rev_id}><input aria-label={`选择版本 ${revision.seq}`} type="checkbox" disabled={locked} checked={selected.includes(revision.rev_id)} onChange={() => setSelected((current) => current.includes(revision.rev_id) ? current.filter((id) => id !== revision.rev_id) : current.length < 2 ? [...current, revision.rev_id] : current)} /><b>#{revision.seq}</b><time>{new Date(revision.ts).toLocaleString()}</time><span>{({ init: '首次纳管', manual: '手动保存', watch: '自动保存' } as Record<string, string>)[revision.trigger] ?? revision.trigger}<small>{refs.filter((ref) => ref.rev_id === revision.rev_id).map((ref) => ref.name === 'last' ? '当前' : ref.name).join(' · ') || '未命名'}</small><small>{summaries[revision.rev_id] || '正在读取本次变化摘要…'}</small></span><button disabled={locked || revision.rev_id === latest} onClick={() => latest && void loadReport(workspaceId, revision.rev_id, latest)}>与当前比较</button><button disabled={locked || Boolean(pendingRestore)} onClick={() => void restore(revision.rev_id)}>恢复到这里</button></div>)}
      <div className="pagination"><button disabled={historyPage === 0} onClick={() => setHistoryPage((page) => page - 1)}>上一页</button><span>第 {historyPage + 1} 页 · 已载入 {historyRows.length} 个版本</span><button disabled={(historyPage + 1) * 20 >= historyRows.length} onClick={() => setHistoryPage((page) => page + 1)}>下一页</button></div>
      <button className="undo" disabled={locked || Boolean(pendingRestore)} onClick={() => void undo()}>撤销最近一次恢复</button>
    </section></>}
    {plan && <RestoreDialog key={plan.plan_id} plan={plan} busy={busy} error={error} onCancel={() => { setPlan(null); setNotice('已关闭确认窗口，不再继续回写；若恢复已开始，仍须续作原计划。'); const { base, head, layer } = comparison.current; void loadReport(workspaceId, base, head, layer) }} onConfirm={() => void applyPlan()} />}
  </main>
}
