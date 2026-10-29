import { useState } from 'react'
import { api } from '../lib/api'

export default function AddWorkspace({ busy, empty, onCreate, compact = false }: {
  busy: boolean; empty: boolean; onCreate: (path: string, name: string) => Promise<boolean>; compact?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [path, setPath] = useState('')
  const [name, setName] = useState('')
  const [picking, setPicking] = useState(false)
  const [error, setError] = useState('')
  const locked = busy || picking

  const choose = async () => {
    if (locked) return
    setOpen(true); setPicking(true); setError('')
    try {
      const result = await api<{ path: string | null }>('/local/select-directory', { method: 'POST', body: '{}' })
      if (result.path) {
        setPath(result.path)
        const created = await onCreate(result.path, name.trim())
        if (created) { setPath(''); setName(''); setOpen(false) }
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法打开目录选择窗口，请手动输入路径。')
    } finally { setPicking(false) }
  }

  if (compact) return <>
    <button className="primary" disabled={locked} onClick={() => void choose()}>{picking ? '请在系统窗口选择…' : '添加技能目录'}</button>
    {error && <p className="notice error" role="alert">{error}可在左侧手动输入路径。</p>}
  </>

  return <section className="panel add-workspace">
    <div className="section-title"><div><h2>{empty ? '添加第一个技能' : '添加技能目录'}</h2></div>
      <button disabled={locked} onClick={() => void choose()}>{picking ? '请在系统窗口选择…' : '打开文件夹'}</button>
    </div>
    {error && <p className="notice error" role="alert">{error}</p>}
    {!empty && <button disabled={locked} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起手动输入' : '手动输入路径'}</button>}
    {(empty || open) && <form className="form-grid" onSubmit={(event) => {
      event.preventDefault()
      if (!path.trim() || locked) return
      void onCreate(path.trim(), name.trim()).then((created) => { if (created) { setPath(''); setName(''); setOpen(false) } })
    }}>
      <label className="wide">技能目录路径<input required disabled={locked} value={path} onChange={(event) => setPath(event.target.value)} placeholder="例如 D:\skills\my-skill" /></label>
      <label>名称（可选）<input disabled={locked} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 写作助手" /></label>
      <button className="primary" disabled={locked || !path.trim()} type="submit">{locked ? '处理中…' : '纳管此目录'}</button>
      <p className="form-hint wide">压缩包请先解压。</p>
    </form>}
  </section>
}
