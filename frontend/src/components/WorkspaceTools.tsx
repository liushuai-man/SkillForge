import { useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import { triggerLabel } from '../lib/display'

type Status = { head_revision: string | null; head_seq: number | null; baseline_revision: string | null; has_pending_changes: boolean; pending_restore: string | null }
type Op = { op_id: string; kind: string; payload_json: string; ts: string }
const opLabels: Record<string, string> = { 'workspace.init': '纳管目录', snapshot: '记录快照', 'ref.set': '设置锚点', 'restore.plan': '预览恢复', 'restore.begin': '开始恢复', 'restore.done': '完成恢复' }

function formatPayload(value: string) {
  try { return JSON.stringify(JSON.parse(value), null, 2) }
  catch { return value }
}

export default function WorkspaceTools({ workspaceId, busy, refreshToken, onAction, onRestore, onResume, onPendingChange, onStatusError, tab }: {
  workspaceId: string; busy: boolean; refreshToken: number
  onAction: (action: () => Promise<void>) => Promise<void>
  onRestore: (rev: string) => Promise<void>; onResume: (planId: string) => Promise<void>
  onPendingChange: (planId: string | null) => void
  onStatusError: (message: string) => void
  tab: 'snapshot' | 'revision' | 'ops'
}) {
  const [status, setStatus] = useState<Status | null>(null)
  const [statusError, setStatusError] = useState('')
  const [statusTick, setStatusTick] = useState(0)
  const [message, setMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [rev, setRev] = useState('@')
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [detailError, setDetailError] = useState('')
  const [detailLoading, setDetailLoading] = useState(false)
  const detailRequest = useRef(0)
  const [ops, setOps] = useState<Op[]>([])
  const [opsError, setOpsError] = useState('')
  const [opsLoading, setOpsLoading] = useState(false)
  const [opsPage, setOpsPage] = useState(0)
  const [opsTick, setOpsTick] = useState(0)
  const [resumeId, setResumeId] = useState('')

  useEffect(() => {
    let active = true
    api<Status>(`/workspaces/${workspaceId}/status`).then((next) => {
      if (active) { setStatus(next); setStatusError(''); onStatusError(''); onPendingChange(next.pending_restore) }
    }).catch((reason: Error) => { if (active) { setStatusError(reason.message); onStatusError(reason.message) } })
    return () => { active = false }
  }, [workspaceId, refreshToken, statusTick, onPendingChange, onStatusError])

  useEffect(() => () => { ++detailRequest.current }, [])

  useEffect(() => {
    if (tab !== 'ops') return
    let active = true
    setOpsLoading(true)
    api<Op[]>(`/workspaces/${workspaceId}/ops`).then((rows) => {
      if (active) { setOps(rows.slice().reverse()); setOpsPage(0); setOpsError('') }
    }).catch((reason: Error) => { if (active) setOpsError(reason.message) })
      .finally(() => { if (active) setOpsLoading(false) })
    return () => { active = false }
  }, [workspaceId, tab, opsTick])

  const lookup = async () => {
    if (!rev.trim()) return
    const request = ++detailRequest.current
    setDetailLoading(true); setDetailError(''); setDetail(null)
    try {
      const next = await api<Record<string, unknown>>(`/workspaces/${workspaceId}/revisions/${encodeURIComponent(rev.trim())}`)
      if (request === detailRequest.current) setDetail(next)
    } catch (reason) { if (request === detailRequest.current) setDetailError(reason instanceof Error ? reason.message : '修订读取失败') }
    finally { if (request === detailRequest.current) setDetailLoading(false) }
  }

  return <section className="panel workspace-tools">
    <div className="section-title"><h2>工作区状态</h2><button disabled={busy} onClick={() => setStatusTick((value) => value + 1)}>刷新状态</button></div>
    {statusError && <p role="alert" className="notice error">状态读取失败：{statusError}{status && '；下方保留上次读取的状态。'}</p>}
    {status ? <div className="status-grid">
      <div><small>当前版本</small><strong>{status.head_seq === null ? '尚无版本' : `#${status.head_seq}`}</strong></div>
      <div><small>磁盘状态</small><strong>{status.pending_restore ? '恢复未完成' : status.has_pending_changes ? '有待捕获改动' : '内容已捕获'}</strong></div>
      <div className="wide"><small>最近锚点</small><code>{status.baseline_revision ?? '尚未设置'}</code></div>
    </div> : !statusError && <p role="status">正在读取状态…</p>}
    {status?.pending_restore && <div className="notice"><strong>有未完成的恢复</strong><p>普通快照和锚点操作暂不可用。继续前仍会展示原计划并要求确认。</p><code>{status.pending_restore}</code><button disabled={busy} onClick={() => void onResume(status.pending_restore!)}>查看并继续恢复</button></div>}
    {tab === 'snapshot' && <form className="form-grid" onSubmit={(event) => {
      event.preventDefault(); if (busy || statusError || status?.pending_restore) return
      setNotice('')
      void onAction(async () => {
        const result = await api<{ created: boolean; revision: { seq: number } }>(`/workspaces/${workspaceId}/snapshots`, { method: 'POST', body: JSON.stringify({ message: message.trim() || null }) })
        setMessage(''); setNotice(result.created ? `已记录版本 #${result.revision.seq}` : `内容未变化，仍为版本 #${result.revision.seq}，未创建空快照。`)
      })
    }}><label className="wide">快照说明（可选）<input disabled={busy} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="例如 调整输出格式" /></label><button className="primary" disabled={busy || Boolean(statusError) || Boolean(status?.pending_restore)} type="submit">记录快照</button>{notice && <p role="status" className="wide">{notice}</p>}</form>}
    {tab === 'revision' && <div className="tool-content">
      <form className="form-grid" onSubmit={(event) => { event.preventDefault(); void lookup() }}><label className="wide">修订或锚点<input value={rev} onChange={(event) => setRev(event.target.value)} placeholder="当前 @、已验证、@~1 或修订编号" /></label><button disabled={detailLoading || !rev.trim()} type="submit">查看修订详情</button><button type="button" disabled={busy || Boolean(statusError) || !rev.trim() || Boolean(status?.pending_restore)} onClick={() => void onRestore(rev.trim())}>预览恢复此版本</button></form>
      {detailError && <p className="notice error" role="alert">{detailError}</p>}
      {detail && <div className="revision-detail"><h3>版本 #{String(detail.seq)}</h3><p>{new Date(String(detail.ts)).toLocaleString('zh-CN')} · {triggerLabel(String(detail.trigger))}</p><p>修订编号：<code>{String(detail.rev_id)}</code></p><details><summary>原始修订数据（技术字段）</summary><pre>{JSON.stringify(detail, null, 2)}</pre></details><p className="form-hint">这是修订元数据，不是快照文件正文。</p></div>}
      <form className="form-grid" onSubmit={(event) => { event.preventDefault(); if (resumeId.trim()) void onResume(resumeId.trim()) }}><label className="wide">恢复计划编号<input value={resumeId} onChange={(event) => setResumeId(event.target.value)} placeholder="OP-…" /></label><button disabled={busy || !resumeId.trim()} type="submit">读取计划并预览续作</button></form>
    </div>}
    {tab === 'ops' && <div className="tool-content"><div className="section-title"><button disabled={opsLoading} onClick={() => setOpsTick((value) => value + 1)}>刷新日志</button></div>
      {opsError && <p className="notice error" role="alert">日志读取失败：{opsError}；已有记录可能已过时。</p>}
      {opsLoading && <p role="status">正在读取操作日志…</p>}
      {!ops.length && !opsLoading && !opsError && <p>暂无操作记录。</p>}
      {ops.slice(opsPage * 20, (opsPage + 1) * 20).map((op) => <details key={op.op_id}><summary><strong>{opLabels[op.kind] ?? op.kind}</strong><time>{new Date(op.ts).toLocaleString('zh-CN')}</time></summary><div className="op-detail"><code>{op.op_id}</code><pre>{formatPayload(op.payload_json)}</pre></div></details>)}
      <div className="pagination"><button disabled={opsPage === 0} onClick={() => setOpsPage((page) => page - 1)}>上一页日志</button><span>第 {opsPage + 1} 页 · {ops.length} 条</span><button disabled={(opsPage + 1) * 20 >= ops.length} onClick={() => setOpsPage((page) => page + 1)}>下一页日志</button></div>
    </div>}
  </section>
}
