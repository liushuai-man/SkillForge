import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import AddWorkspace from './components/AddWorkspace'
import WorkspaceTools from './components/WorkspaceTools'
import RestoreDialog from './components/RestoreDialog'
import type { RestorePlan } from './components/RestoreDialog'
import { api } from './lib/api'
import { useTheme } from './lib/theme'
import type { Theme } from './lib/theme'
import Icon from './components/Icon'
import ResizeHandle from './components/ResizeHandle'
import SidebarSection from './components/SidebarSection'
import type { CSSProperties } from 'react'
import './styles.css'

const FileComparison = lazy(() => import('./components/FileComparison'))

type Workspace = { workspace_id: string; name: string; root_path: string }
type Revision = { rev_id: string; ws_id: string; seq: number; ts: string; trigger: string; source: string; parent_rev_id: string | null }
type Ref = { name: string; rev_id: string }
type Report = {
  base: { rev: string | null }; head: { rev: string }; added: number; removed: number
  files: Array<{ path: string; op: string; before_path?: string; added: number | null; removed: number | null }>
}

const labels: Record<string, string> = { add: '新增', delete: '删除', modify: '修改', move: '移动' }

export default function App() {
  const { theme, setTheme, resolved, storageWarning } = useTheme()
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [workspaceId, setWorkspaceId] = useState('')
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sidebarView, setSidebarView] = useState<'explorer' | 'history' | 'compare' | 'settings'>('explorer')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [sectionsOpen, setSectionsOpen] = useState({ workspace: true, files: true, history: true, anchors: true })
  const toggleSection = (key: keyof typeof sectionsOpen) => setSectionsOpen(current => ({ ...current, [key]: !current[key] }))
  const [sidebarWidth, setSidebarWidth] = useState(284)
  const [panelOpen, setPanelOpen] = useState(false)
  const [panelHeight, setPanelHeight] = useState(264)
  const [panelTab, setPanelTab] = useState<'snapshot' | 'revision' | 'ops' | 'anchor'>('snapshot')
  const [selectedFile, setSelectedFile] = useState('')
  const [fileFilter, setFileFilter] = useState('')
  const [workspaceStatusError, setWorkspaceStatusError] = useState('')
  const [viewport, setViewport] = useState(() => ({ width: window.innerWidth, height: window.innerHeight }))
  useEffect(() => {
    const resize = () => setViewport({ width: window.innerWidth, height: window.innerHeight })
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])
  const [selected, setSelected] = useState<string[]>([])
  const [anchor, setAnchor] = useState('')
  const [anchorRev, setAnchorRev] = useState('')
  const [baseSpec, setBaseSpec] = useState('')
  const [headSpec, setHeadSpec] = useState('')
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
  const activeWorkspace = useRef('')
  const selectionClosed = useRef(false)
  const reportRequest = useRef(0)
  const revisionRequest = useRef(0)
  const workspaceRequest = useRef(0)
  const actionInFlight = useRef(false)
  const comparison = useRef<{ base?: string; head?: string }>({})
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
  const loadReport = useCallback(async (ws: string, base?: string, head?: string) => {
    comparison.current = { base, head }
    const request = ++reportRequest.current
    const isCurrent = () => activeWorkspace.current === ws && request === reportRequest.current
    setLoading(true); setError(''); setStale(true)
    const query = new URLSearchParams()
    if (base) query.set('base', base); if (head) query.set('head', head)
    try {
      const next = await api<Report>(`/workspaces/${ws}/compare?${query}`)
      if (isCurrent()) { setReport(next); setStale(false) }
    }
    catch (reason) { if (isCurrent()) setError(reason instanceof Error ? reason.message : '文件比较失败') }
    finally { if (isCurrent()) setLoading(false) }
  }, [])

  const loadWorkspaces = useCallback(async () => {
    const request = ++workspaceRequest.current
    setWorkspacesLoading(true)
    try {
      const rows = await api<Workspace[]>('/workspaces')
      if (request !== workspaceRequest.current) return
      setWorkspaces(rows); setError('')
      setWorkspaceId((current) => rows.some((row) => row.workspace_id === current) ? current : selectionClosed.current ? '' : rows[0]?.workspace_id ?? '')
    } catch (reason) { if (request === workspaceRequest.current) setError(reason instanceof Error ? reason.message : '工作区读取失败') }
    finally { if (request === workspaceRequest.current) setWorkspacesLoading(false) }
  }, [])
  useEffect(() => { void loadWorkspaces(); return () => { ++workspaceRequest.current } }, [loadWorkspaces])
  useEffect(() => {
    activeWorkspace.current = workspaceId
    if (window.innerWidth <= 700) setSidebarOpen(false)
    comparison.current = {}
    setSelectedFile(''); setFileFilter(''); setWorkspaceStatusError('')
    setRevisions([]); setRefs([]); setHistoryUpper(null); setHistoryPage(0); setSelected([]); setReport(null); setAnchor(''); setAnchorRev(''); setBaseSpec(''); setHeadSpec(''); setPendingRestore(null); setNotice(''); setError(''); setStreamError('')
    setPlan(null)
    if (!workspaceId) { setLoading(false); return }
    const refresh = () => { const { base, head } = comparison.current; void loadRevisions(workspaceId); void loadReport(workspaceId, base, head); setRefreshToken((value) => value + 1) }
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

  const latest = revisions.at(-1)?.rev_id
  const workspace = workspaces.find((item) => item.workspace_id === workspaceId)
  const revisionLabel = (rev: string | null) => {
    if (rev === null) return '空内容'
    const row = revisions.find((item) => item.rev_id === rev)
    return row ? `版本 #${row.seq}` : rev.slice(0, 12)
  }
  const historyRows = revisions.filter((row) => historyUpper !== null && row.seq <= historyUpper).slice().reverse()
  const pageRows = useMemo(() => revisions.filter((row) => row.ws_id === workspaceId && historyUpper !== null && row.seq <= historyUpper).slice().reverse().slice(historyPage * 20, (historyPage + 1) * 20), [revisions, historyPage, historyUpper, workspaceId])
  const runAction = async (action: () => Promise<void>, refreshReport = true) => {
    if (actionInFlight.current) return
    actionInFlight.current = true
    setBusy(true); setError(''); setNotice('')
    try { await action(); await loadRevisions(workspaceId); if (refreshReport) { const { base, head } = comparison.current; await loadReport(workspaceId, base, head) } }
    catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败') }
    finally { setBusy(false); actionInFlight.current = false; setRefreshToken((value) => value + 1) }
  }

  const createWorkspace = async (path: string, name: string) => {
    if (actionInFlight.current || plan) return false
    const normalized = (value: string) => {
      const cleaned = value.trim().replace(/\\/g, '/').replace(/\/+$/, '')
      return /^[a-z]:\//i.test(cleaned) || cleaned.startsWith('//') ? cleaned.toLowerCase() : cleaned
    }
    const existing = workspaces.find((row) => normalized(row.root_path) === normalized(path))
    if (existing) {
      selectionClosed.current = false
      activeWorkspace.current = existing.workspace_id
      setWorkspaceId(existing.workspace_id); setError(''); setNotice('')
      return true
    }
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

  const closeWorkspace = () => {
    if (locked) return
    selectionClosed.current = true
    activeWorkspace.current = ''
    ++reportRequest.current; ++revisionRequest.current
    setWorkspaceId(''); setPanelOpen(false); setSidebarView('explorer'); setSidebarOpen(true)
  }

  const compareSelected = () => {
    const rows = revisions.filter((row) => selected.includes(row.rev_id)).sort((a, b) => a.seq - b.seq)
    if (rows.length === 2) compare(rows[0].rev_id, rows[1].rev_id)
  }
  const createAnchor = async () => {
    if (!anchor.trim()) return
    await runAction(async () => { await api(`/workspaces/${workspaceId}/refs`, { method: 'POST', body: JSON.stringify({ name: anchor.trim(), rev: anchorRev.trim() || null }) }); setNotice(`锚点 ${anchor.trim()} 已保存。`); setAnchor(''); setAnchorRev('') })
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

  const openSidebar = (next: typeof sidebarView) => { if (sidebarView === next) setSidebarOpen(!sidebarOpen); else { setSidebarView(next); setSidebarOpen(true) } }
  const openPanel = (next: typeof panelTab) => { setPanelTab(next); setPanelOpen(true) }
  const refreshCurrent = () => { const { base, head } = comparison.current; void loadRevisions(workspaceId); void loadReport(workspaceId, base, head); setRefreshToken((value) => value + 1) }
  const title = { explorer: '资源管理器', history: '版本历史', compare: '版本比较', settings: '设置' }[sidebarView]
  const files = report?.files ?? []
  const visibleFiles = files.filter((file) => file.path.toLocaleLowerCase().includes(fileFilter.toLocaleLowerCase()))
  const activeFile = files.some((file) => file.path === selectedFile) ? selectedFile : files[0]?.path ?? ''
  const compare = (base?: string, head?: string) => { setBaseSpec(base ?? ''); setHeadSpec(head ?? ''); if (viewport.width <= 700) setSidebarOpen(false); void loadReport(workspaceId, base, head) }
  const fileName = (path: string) => path.split('/').at(-1) ?? path
  const maxSidebarWidth = Math.max(220, Math.min(460, viewport.width - (viewport.width <= 700 ? 80 : 368)))
  const maxPanelHeight = Math.max(180, Math.min(520, Math.floor(viewport.height * (viewport.width <= 700 ? .48 : .5))))
  const actualSidebarWidth = Math.min(sidebarWidth, maxSidebarWidth)
  const actualPanelHeight = Math.min(panelHeight, maxPanelHeight)

  return <div className="app-shell" style={{ '--sidebar-width': `${actualSidebarWidth}px`, '--panel-height': `${actualPanelHeight}px` } as CSSProperties}>
    <header className="titlebar">
      <div className="titlebar-brand"><button className="icon-button" title="切换侧栏" aria-label="切换侧栏" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(!sidebarOpen)}><Icon name="layout-sidebar-left" /></button><strong>SkillForge</strong><span className="app-edition">版本管理器</span></div>
      <div className="workspace-picker"><Icon name="folder-opened" /><select aria-label="工作区" disabled={locked || !workspaces.length} value={workspaceId} onChange={(event) => { selectionClosed.current = !event.target.value; activeWorkspace.current = event.target.value; setWorkspaceId(event.target.value) }}><option value="">未打开文件夹</option>{workspaces.map((item) => <option key={item.workspace_id} value={item.workspace_id}>{item.name}</option>)}</select>{workspace && <button className="icon-button" title="关闭视图，后台继续记录" aria-label="关闭文件夹" disabled={locked} onClick={closeWorkspace}><Icon name="close" /></button>}</div>
      <div className="titlebar-actions"><label className="theme-picker"><span className="sr-only">界面主题</span><select value={theme} onChange={(event) => setTheme(event.target.value as Theme)}><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></label><button className="icon-button" title="切换底部面板" aria-label="切换底部面板" aria-expanded={panelOpen} disabled={!workspace} onClick={() => setPanelOpen(!panelOpen)}><Icon name="layout-panel" /></button></div>
    </header>
    <div className={`workbench ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
      <nav className="activity-bar" aria-label="主导航">
        {([['explorer', 'files', '资源管理器'], ['history', 'history', '版本历史'], ['compare', 'source-control', '版本比较']] as const).map(([key, icon, label]) => <button key={key} className={`activity-button ${sidebarView === key && sidebarOpen ? 'active' : ''}`} title={label} aria-label={label} aria-pressed={sidebarView === key && sidebarOpen} onClick={() => openSidebar(key)}><Icon name={icon} />{key === 'compare' && files.length > 0 && <span className="activity-count">{files.length}</span>}</button>)}
        <div className="activity-spacer" /><button className={`activity-button ${sidebarView === 'settings' && sidebarOpen ? 'active' : ''}`} title="设置" aria-label="设置" aria-pressed={sidebarView === 'settings' && sidebarOpen} onClick={() => openSidebar('settings')}><Icon name="settings-gear" /></button>
      </nav>
      <aside className="sidebar" hidden={!sidebarOpen} aria-label={title}>
        <div className="sidebar-heading"><h1>{title}</h1><div className="sidebar-heading-actions"><button className="icon-button" title="刷新工作区列表" aria-label="刷新工作区列表" disabled={locked || workspacesLoading} onClick={() => void loadWorkspaces()}><Icon name="refresh" /></button><button className="icon-button" title="收起侧栏" aria-label="收起侧栏" onClick={() => setSidebarOpen(false)}><Icon name="arrow-left" /></button></div></div>
        <div className="sidebar-scroll">
          {sidebarView === 'explorer' && <>
            <SidebarSection title="工作区" count={workspaces.length} expanded={sectionsOpen.workspace} onToggle={() => toggleSection('workspace')}>
            {workspace && <div className="workspace-root"><Icon name="folder-opened" /><strong>{workspace.name}</strong><span className="muted">已纳管</span></div>}
            {workspace && <p className="workspace-path" title={workspace.root_path}>{workspace.root_path}</p>}
            {!workspacesLoading && <AddWorkspace busy={locked} empty={!workspaces.length} onCreate={createWorkspace} />}
            </SidebarSection><SidebarSection title="变更文件" count={files.length} expanded={sectionsOpen.files} onToggle={() => toggleSection('files')}>
            <label className="file-filter"><Icon name="search" /><span className="sr-only">筛选变更文件</span><input value={fileFilter} onChange={(event) => setFileFilter(event.target.value)} placeholder="筛选变更文件" /></label>
            <div className="file-list" aria-label="变更文件列表">{visibleFiles.map((file) => <button key={file.path} title={file.path} aria-current={activeFile === file.path ? 'true' : undefined} className={`file-row ${activeFile === file.path ? 'active' : ''}`} onClick={() => { setSelectedFile(file.path); if (viewport.width <= 700) setSidebarOpen(false) }}><Icon name="file-code" /><span className="file-name">{fileName(file.path)}<small>{file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/')) : ''}</small></span><span className={`file-operation ${file.op}`} aria-label={labels[file.op] ?? file.op}>{({ add: 'A', delete: 'D', modify: 'M', move: 'R' } as Record<string, string>)[file.op] ?? file.op}</span></button>)}{!visibleFiles.length && <p className="sidebar-hint">{fileFilter ? '没有匹配的变更文件。' : !workspace ? '未打开文件夹。' : loading ? '正在读取变化…' : '没有变更文件。'}</p>}</div>
            {workspace && <button className="sidebar-link" onClick={() => { setSidebarView('history'); setSidebarOpen(true) }}><Icon name="history" />浏览历史版本<span>{revisions.length}</span></button>}
          </SidebarSection></>}
          {(sidebarView === 'history' || sidebarView === 'explorer') && <>
            <SidebarSection title="版本列表" count={revisions.length} expanded={sectionsOpen.history} onToggle={() => toggleSection('history')}>
            {workspace && <><div className="history-actions"><button disabled={locked || selected.length !== 2} onClick={compareSelected}><Icon name="diff" />比较所选 {selected.length}/2</button><button className="icon-button" aria-label="刷新历史" title="刷新历史" disabled={locked} onClick={() => void loadRevisions(workspaceId)}><Icon name="refresh" /></button></div>
              {historyUpper !== null && (revisions.at(-1)?.seq ?? 0) > historyUpper && <button className="new-revisions" onClick={() => { setHistoryUpper(revisions.at(-1)?.seq ?? null); setHistoryPage(0) }}>有新版本 · 查看最新历史</button>}
              <div className="revision-list">{pageRows.map((revision) => <article className="revision" key={revision.rev_id}><div className="revision-heading"><input aria-label={`选择版本 ${revision.seq}`} type="checkbox" disabled={locked} checked={selected.includes(revision.rev_id)} onChange={() => setSelected((current) => current.includes(revision.rev_id) ? current.filter((id) => id !== revision.rev_id) : current.length < 2 ? [...current, revision.rev_id] : current)} /><b>#{revision.seq}</b>{revision.rev_id === latest && <span className="ref-label">当前</span>}<time title={`${new Date(revision.ts).toLocaleString()} · ${({ init: '首次纳管', manual: '手动保存', watch: '自动保存' } as Record<string, string>)[revision.trigger] ?? revision.trigger}`}>{new Date(revision.ts).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</time></div><button className="revision-open" disabled={locked} onClick={() => compare(undefined, revision.rev_id)}>查看此版改动</button><div className="revision-meta">{refs.filter((ref) => ref.rev_id === revision.rev_id && ref.name !== 'last').map((ref) => <span className="ref-label" key={ref.name}>{ref.name}</span>)}</div><div className="revision-actions"><button title="与当前版本比较" aria-label={`比较版本 ${revision.seq} 与当前版本`} disabled={locked || revision.rev_id === latest} onClick={() => latest && compare(revision.rev_id, latest)}><Icon name="diff" />与最新比较</button><button title="恢复到此版本" aria-label={`恢复到版本 ${revision.seq}`} disabled={locked || Boolean(pendingRestore) || Boolean(workspaceStatusError)} onClick={() => void restore(revision.rev_id)}><Icon name="discard" />恢复此版本</button></div></article>)}</div>
              <div className="pagination"><button className="icon-button" title="上一页" aria-label="上一页" disabled={historyPage === 0} onClick={() => setHistoryPage((page) => page - 1)}><Icon name="arrow-left" /></button><span>{historyPage + 1} / {Math.max(1, Math.ceil(historyRows.length / 20))} · {historyRows.length} 个版本</span><button className="icon-button" title="下一页" aria-label="下一页" disabled={(historyPage + 1) * 20 >= historyRows.length} onClick={() => setHistoryPage((page) => page + 1)}><Icon name="arrow-right" /></button></div>
              </>}</SidebarSection>{workspace && <SidebarSection title="命名锚点" count={refs.filter(ref => ref.name !== 'last').length} expanded={sectionsOpen.anchors} onToggle={() => toggleSection('anchors')} action={<button className="icon-button" title="创建锚点" aria-label="打开创建锚点面板" onClick={() => openPanel('anchor')}><Icon name="add" /></button>}>{refs.filter((ref) => ref.name !== 'last').map((ref) => <button className="sidebar-link" key={ref.name} disabled={locked} onClick={() => compare(ref.name, '@')}><Icon name="bookmark" />{ref.name}<small>{revisionLabel(ref.rev_id)}</small></button>)}
            </SidebarSection>}{!workspace && <p className="sidebar-hint">先在资源管理器中添加 Skill 目录。</p>}
          </>}
          {sidebarView === 'compare' && <div className="sidebar-form"><h2>比较任意两个版本</h2><p className="section-description">使用顶部的旧版和新版下拉框；也可以输入锚点或 @~1。</p><form onSubmit={(event) => { event.preventDefault(); if (!locked && workspace) compare(baseSpec.trim() || undefined, headSpec.trim() || undefined) }}><label>旧版本<input disabled={locked || !workspace} list="revision-options" value={baseSpec} onChange={(event) => setBaseSpec(event.target.value)} placeholder="上一个版本 / tested / @~1" /></label><label>新版本<input disabled={locked || !workspace} list="revision-options" value={headSpec} onChange={(event) => setHeadSpec(event.target.value)} placeholder="最新版本 / @" /></label><button type="submit" className="primary" disabled={locked || !workspace || loading}>比较这两版</button><button type="button" disabled={locked || !workspace || loading} onClick={() => compare()}>比较最新两版</button></form></div>}
          {sidebarView === 'settings' && <div className="sidebar-form"><h2>颜色主题</h2><div className="theme-options" aria-label="颜色主题">{([['light', '浅色'], ['dark', '深色'], ['system', '跟随系统']] as const).map(([key, label]) => <button key={key} aria-pressed={theme === key} onClick={() => setTheme(key)}><span className={`theme-preview ${key}`} /><span>{label}</span>{theme === key && <Icon name="check" />}</button>)}</div><h2>关于工作区</h2><p className="sidebar-hint">保存文件自动记录版本。文件在本机分析，纳管不会改写原文件。恢复和撤销需预览并确认。</p></div>}
        </div>
      </aside>
      {sidebarOpen && <ResizeHandle axis="sidebar" value={actualSidebarWidth} min={220} max={maxSidebarWidth} onChange={setSidebarWidth} />}
      <main className="editor-group">
        <div className="comparison-toolbar">
          <label>旧版<select aria-label="旧版本" value={baseSpec} disabled={locked || !workspace} onChange={event => compare(event.target.value || undefined, headSpec || undefined)}><option value="">上一个版本</option>{revisions.slice().reverse().map(row => <option key={row.rev_id} value={row.rev_id}>#{row.seq} · {new Date(row.ts).toLocaleString()}</option>)}{refs.filter(ref => ref.name !== 'last').map(ref => <option key={ref.name} value={ref.name}>{ref.name}</option>)}</select></label>
          <button disabled={locked || loading || stale || !report?.base.rev} title="交换旧版和新版" aria-label="交换旧版和新版" onClick={() => report && compare(report.head.rev, report.base.rev ?? undefined)}>⇄</button>
          <label>新版<select aria-label="新版本" value={headSpec} disabled={locked || !workspace} onChange={event => compare(baseSpec || undefined, event.target.value || undefined)}><option value="">最新版本</option>{revisions.slice().reverse().map(row => <option key={row.rev_id} value={row.rev_id}>#{row.seq} · {new Date(row.ts).toLocaleString()}</option>)}{refs.filter(ref => ref.name !== 'last').map(ref => <option key={ref.name} value={ref.name}>{ref.name}</option>)}</select></label>
          <button disabled={locked || !workspace || loading} onClick={() => compare()}>最新两版</button><button aria-label="刷新当前对比" disabled={locked || !workspace || loading} onClick={refreshCurrent}><Icon name="refresh" />刷新</button>
        </div>
        <div className="breadcrumbs"><span>{workspace?.name ?? '未打开工作区'}</span><Icon name="chevron-right" /><span>{activeFile || '文件比较'}</span>{report && <><span className="breadcrumb-spacer" /><span>{revisionLabel(report.base.rev)} → {revisionLabel(report.head.rev)}</span><span>{files.length} 文件 <b className="added">+{report.added}</b> <b className="removed">−{report.removed}</b></span></>}</div>
        {workspace && <div className="editor-commandbar"><button title="文件保存后会自动记录版本" disabled={locked || Boolean(pendingRestore) || Boolean(workspaceStatusError)} onClick={() => openPanel('snapshot')}><Icon name="save" />手动快照</button><button disabled={locked || loading || stale || !report || Boolean(pendingRestore) || Boolean(workspaceStatusError)} onClick={() => { setAnchorRev(report?.head.rev ?? ''); openPanel('anchor') }}><Icon name="bookmark" />标记版本</button><button disabled={locked || Boolean(pendingRestore) || Boolean(workspaceStatusError)} onClick={() => void undo()}><Icon name="discard" />撤销恢复</button><button disabled={locked || loading || stale || !report || Boolean(pendingRestore) || Boolean(workspaceStatusError)} onClick={() => report && void restore(report.head.rev)}>恢复右侧版本…</button><span className="breadcrumb-spacer" /><button onClick={() => openPanel('ops')}><Icon name="history" />操作记录</button></div>}
        <div className="editor-notifications" aria-live="polite">{storageWarning && <p className="notice">{storageWarning}</p>}{error && <p className="notice error" role="alert"><Icon name="warning" />{error}</p>}{notice && <p className="notice success" role="status"><Icon name="check" />{notice}<button className="icon-button" aria-label="关闭提示" onClick={() => setNotice('')}><Icon name="close" /></button></p>}{workspaceStatusError && <p className="notice error" role="alert">工作区状态读取失败：{workspaceStatusError}；恢复状态尚未确认。<button onClick={() => openPanel('snapshot')}>打开状态面板</button></p>}{streamError && <p className="notice"><Icon name="warning" />{streamError}</p>}{stale && report && <p className="notice">旧结果 · {loading ? '正在更新…' : '更新失败，请刷新重试。'}</p>}{pendingRestore && <p className="notice"><Icon name="warning" />恢复未完成，普通写入已暂停。<button disabled={locked} onClick={() => void resume(pendingRestore)}>查看并继续恢复</button></p>}</div>
        <div className="editor-scroll">
          {!workspace && !workspacesLoading && <section className="welcome"><Icon name="files" /><h2>打开一个 Skill，开始记录变化</h2><AddWorkspace compact busy={locked} empty onCreate={createWorkspace} /><small>选择文件夹开始。ZIP 请先解压。</small></section>}
          {workspacesLoading && <div className="empty" role="status">正在连接本机服务…</div>}
          {workspace && !report && loading && <div className="empty" role="status">正在读取文件差异…</div>}
          {report && (files.length === 0 ? <div className="empty"><Icon name="check" /><h2>这两个版本没有文件变化</h2><p>保存后自动记录。可从上方选择其他版本比较。</p></div> : <Suspense fallback={<p className="empty" role="status">正在载入文件差异…</p>}><FileComparison workspaceId={workspaceId} base={report.base.rev} head={report.head.rev} file={files.find(file => file.path === activeFile)!} dark={resolved === 'dark'} baseLabel={revisionLabel(report.base.rev)} headLabel={revisionLabel(report.head.rev)} /></Suspense>)}
        </div>
        {workspace && <><div hidden={!panelOpen}><ResizeHandle axis="panel" value={actualPanelHeight} min={180} max={maxPanelHeight} onChange={setPanelHeight} /></div><section className="bottom-panel" hidden={!panelOpen} aria-label="工作区操作面板"><div className="panel-tabbar"><nav aria-label="工作区管理功能">{([['snapshot', '手动快照'], ['revision', '修订与续作'], ['ops', '操作日志'], ['anchor', '锚点']] as const).map(([key, label]) => <button key={key} aria-pressed={panelTab === key} className={panelTab === key ? 'active' : ''} onClick={() => setPanelTab(key)}>{label}</button>)}</nav><button className="icon-button" aria-label="关闭底部面板" title="关闭底部面板" onClick={() => setPanelOpen(false)}><Icon name="close" /></button></div><div className="panel-scroll"><div hidden={panelTab === 'anchor'}><WorkspaceTools key={workspaceId} workspaceId={workspaceId} busy={locked} refreshToken={refreshToken} onAction={runAction} onRestore={restore} onResume={resume} onPendingChange={setPendingRestore} onStatusError={setWorkspaceStatusError} tab={panelTab === 'anchor' ? 'snapshot' : panelTab} /></div><section className="anchor-panel" hidden={panelTab !== 'anchor'}><h2>创建锚点</h2><p>命名指定版本；目标留空时先捕获当前磁盘内容。</p><form className="form-grid" onSubmit={(event) => { event.preventDefault(); if (!locked && !pendingRestore && !workspaceStatusError) void createAnchor() }}><label>锚点名称<input disabled={locked} value={anchor} onChange={(event) => setAnchor(event.target.value)} placeholder="例如 tested" /></label><label>锚点目标<input disabled={locked} list="revision-options" value={anchorRev} onChange={(event) => setAnchorRev(event.target.value)} placeholder="当前磁盘内容 / 历史修订" /></label><button className="primary" type="submit" disabled={locked || Boolean(pendingRestore) || Boolean(workspaceStatusError) || !anchor.trim()}>创建锚点</button></form></section></div></section></>}
      </main>
    </div>
    <footer className="statusbar"><span className="status-brand"><Icon name="source-control" />本机</span><span><Icon name={(streamError || workspaceStatusError) ? 'warning' : 'check'} />{workspacesLoading ? '正在连接' : streamError ? '实时连接中断' : workspaceStatusError ? '状态读取失败' : workspace ? '自动快照已启用' : '未打开目录'}</span>{workspace && <><span className="status-workspace" title={workspace.root_path}>{workspace.name}</span><span>{pendingRestore ? '恢复待续作' : busy ? '正在处理…' : `当前 #${revisions.at(-1)?.seq ?? '—'}`}</span></>}<span className="status-spacer" />{report && <span>{stale ? '旧结果' : '对比已更新'}</span>}<button disabled={!workspace} onClick={() => openPanel('revision')}>修订与续作</button><button onClick={() => { setSidebarView('settings'); setSidebarOpen(true) }}>{theme === 'system' ? '跟随系统' : resolved === 'dark' ? '深色' : '浅色'}</button></footer>
    <datalist id="revision-options"><option value="@">当前版本</option>{refs.filter((ref) => ref.name !== 'last').map((ref) => <option key={ref.name} value={ref.name} />)}{revisions.map((row) => <option key={row.rev_id} value={row.rev_id}>版本 #{row.seq}</option>)}</datalist>
    {plan && <RestoreDialog key={plan.plan_id} plan={plan} busy={busy} error={error} onCancel={() => { setPlan(null); setNotice('已关闭恢复预览。'); const { base, head } = comparison.current; void loadReport(workspaceId, base, head) }} onConfirm={() => void applyPlan()} />}
  </div>
}
