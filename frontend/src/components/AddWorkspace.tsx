import { useState } from 'react'

export default function AddWorkspace({ busy, empty, onCreate }: {
  busy: boolean; empty: boolean; onCreate: (path: string, name: string) => Promise<boolean>
}) {
  const [open, setOpen] = useState(false)
  const [path, setPath] = useState('')
  const [name, setName] = useState('')

  return <section className="panel add-workspace">
    <div className="section-title"><div><h2>{empty ? '添加第一个 Skill' : '添加 Skill 目录'}</h2><p>输入本机的绝对路径，纳管后自动记录保存内容。</p></div>
      {!empty && <button disabled={busy} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起' : '添加目录'}</button>}
    </div>
    {(empty || open) && <form className="form-grid" onSubmit={(event) => {
      event.preventDefault()
      if (!path.trim() || busy) return
      void onCreate(path.trim(), name.trim()).then((created) => { if (created) { setPath(''); setName(''); setOpen(false) } })
    }}>
      <label className="wide">Skill 目录路径<input required disabled={busy} value={path} onChange={(event) => setPath(event.target.value)} placeholder="例如 D:\skills\my-skill" /></label>
      <label>名称（可选）<input disabled={busy} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 写作助手" /></label>
      <button className="primary" disabled={busy || !path.trim()} type="submit">{busy ? '处理中…' : '纳管此目录'}</button>
      <p className="form-hint wide">可从文件管理器地址栏复制路径。目录应已存在；ZIP 请先解压。纳管只读取文件，不改写 Skill。</p>
    </form>}
  </section>
}
