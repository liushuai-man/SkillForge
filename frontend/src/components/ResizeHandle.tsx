import { useRef } from 'react'

export default function ResizeHandle({ axis, value, min, max, onChange }: {
  axis: 'sidebar' | 'panel'; value: number; min: number; max: number; onChange: (value: number) => void
}) {
  const drag = useRef<{ origin: number; value: number } | null>(null)
  return <div role="separator" tabIndex={0} aria-label={axis === 'sidebar' ? '调整侧栏宽度' : '调整底部面板高度'} aria-orientation={axis === 'sidebar' ? 'vertical' : 'horizontal'} aria-valuemin={min} aria-valuemax={max} aria-valuenow={value} className={`resize-handle ${axis}`}
    onPointerDown={(event) => { if (event.button !== 0) return; event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); drag.current = { origin: axis === 'sidebar' ? event.clientX : event.clientY, value } }}
    onPointerMove={(event) => { if (!drag.current) return; const delta = (axis === 'sidebar' ? event.clientX : -event.clientY) - (axis === 'sidebar' ? drag.current.origin : -drag.current.origin); onChange(Math.max(min, Math.min(max, drag.current.value + delta))) }}
    onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }}
    onKeyDown={(event) => { const negative = axis === 'sidebar' ? 'ArrowLeft' : 'ArrowDown'; const positive = axis === 'sidebar' ? 'ArrowRight' : 'ArrowUp'; if (![negative, positive].includes(event.key)) return; event.preventDefault(); onChange(Math.max(min, Math.min(max, value + (event.key === positive ? 16 : -16)))) }} />
}
