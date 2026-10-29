import { useState } from 'react'
import { api } from '../lib/api'
import Icon from './Icon'

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

  return <section className={`panel add-workspace ${compact ? 'start-workspace' : ''}`} aria-label="添加技能目录">
    {compact ? <><h3>打开本地技能</h3><p className="start-description">选择已有目录，自动开始记录文件变化。</p></> : <h2>{empty ? '添加第一个技能' : '添加技能目录'}</h2>}
    <button className={compact ? 'primary open-directory' : 'open-directory'} disabled={locked} onClick={() => void choose()}><Icon name="folder-opened" />{picking ? '请在系统窗口选择…' : '打开文件夹'}</button>
    {error && <p className="notice error" role="alert">{error}</p>}
    <button className="manual-path-toggle" disabled={locked} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起手动输入' : '手动输入路径'}<Icon name={open ? 'chevron-down' : 'chevron-right'} /></button>
    {open && <form className="form-grid" onSubmit={(event) => {
      event.preventDefault()
      if (!path.trim() || locked) return
      void onCreate(path.trim(), name.trim()).then((created) => { if (created) { setPath(''); setName(''); setOpen(false) } })
    }}>
      <label className="wide">技能目录路径<input required disabled={locked} value={path} onChange={(event) => setPath(event.target.value)} placeholder="例如 D:\skills\my-skill" /></label>
      <label>名称（可选）<input disabled={locked} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 写作助手" /></label>
      <button className="primary" disabled={locked || !path.trim()} type="submit">{locked ? '处理中…' : '纳管此目录'}</button>
    </form>}
    {compact && <p className="form-hint">文件保存在本机 · 压缩包请先解压</p>}
  </section>
}
