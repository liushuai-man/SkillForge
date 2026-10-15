import { MergeView } from '@codemirror/merge'
import { useEffect, useRef } from 'react'

type Hunk = { path: string; before: { text: string } | null; after: { text: string } | null }

function Merge({ before, after }: { before: string; after: string }) {
  const host = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!host.current) return
    const view = new MergeView({ a: { doc: before }, b: { doc: after }, parent: host.current })
    return () => view.destroy()
  }, [after, before])
  return <div className="merge" ref={host} />
}

export default function TextDiff({ hunks }: { hunks: Hunk[] }) {
  if (!hunks.length) return <div className="empty">没有文字差异。</div>
  return <section className="text-diffs">{hunks.map((hunk, index) => <article key={`${hunk.path}-${index}`}><h3>{hunk.path}</h3><Merge before={hunk.before?.text ?? ''} after={hunk.after?.text ?? ''} /></article>)}</section>
}
