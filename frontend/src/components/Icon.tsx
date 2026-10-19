import type { CSSProperties } from 'react'

export default function Icon({ name, className = '' }: { name: string; className?: string }) {
  return <span aria-hidden="true" className={`icon ${className}`} style={{ '--icon': `url(/icons/${name}.svg)` } as CSSProperties} />
}
