import { useEffect, useRef } from 'react'

export type RestorePlan = { no_change: boolean; plan_id: string | null; before_rev?: string; target_rev?: string; changes: Array<{ action: string; path: string }> }
const labels: Record<string, string> = { add: '新增', modify: '修改', delete: '删除', mkdir: '创建目录', rmdir: '删除目录' }

export default function RestoreDialog({ plan, busy, error, onCancel, onConfirm }: {
  plan: RestorePlan; busy: boolean; error: string; onCancel: () => void; onConfirm: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])
  return <dialog ref={dialog} aria-labelledby="restore-title" onCancel={(event) => { event.preventDefault(); if (!busy) onCancel() }}>
    <h2 id="restore-title">确认回写整个技能</h2>
    <p>请先保存编辑器缓冲区并暂停编辑。确认后将按下列清单恢复；已有历史保留。</p>
    <dl className="plan-info"><dt>计划</dt><dd>{plan.plan_id}</dd><dt>当前修订</dt><dd>{plan.before_rev}</dd><dt>目标修订</dt><dd>{plan.target_rev}</dd></dl>
    <ul className="plan-changes">{plan.changes.map((change) => <li key={`${change.action}-${change.path}`}><b>{labels[change.action] ?? change.action}</b><code>{change.path}</code></li>)}</ul>
    <p className="form-hint">预览可能已保护当前磁盘内容为快照；取消不会执行文件回写。已开始的中断恢复不会因关闭本窗口自动回滚。</p>
    {error && <p className="notice error" role="alert">{error}</p>}
    <div className="dialog-actions"><button disabled={busy} onClick={onCancel}>取消</button><button className="primary" disabled={busy} onClick={onConfirm}>{busy ? '正在恢复…' : '确认恢复并回写'}</button></div>
  </dialog>
}
