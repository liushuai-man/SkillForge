import { useId } from 'react'
import type { ReactNode } from 'react'
import Icon from './Icon'

export default function SidebarSection({ title, count, expanded, onToggle, action, children }: {
  title: string; count?: number; expanded: boolean; onToggle: () => void; action?: ReactNode; children: ReactNode
}) {
  const panelId = useId()
  return <section className="sidebar-section">
    <div className="sidebar-section-label">
      <button className="section-toggle" aria-expanded={expanded} aria-controls={panelId} aria-label={`${expanded ? '收起' : '展开'}${title}`} onClick={onToggle}>
        <Icon name={expanded ? 'chevron-down' : 'chevron-right'} /><strong>{title}</strong>
        {count !== undefined && <span className="count">{count}</span>}
      </button>{action}
    </div>
    <div id={panelId} hidden={!expanded}>{children}</div>
  </section>
}
