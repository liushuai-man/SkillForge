type Envelope<T> = { ok: boolean; data: T; error: { message: string; code: string } | null; request_id?: string }

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  // Reads are safe to retry; aborting a write cannot tell us whether it committed.
  const controller = new AbortController()
  const timer = (!init?.method || init.method.toUpperCase() === 'GET')
    ? setTimeout(() => controller.abort(), 20_000) : undefined
  try {
    const response = await fetch(`/api${path}`, { ...init, signal: init?.signal ?? controller.signal, headers: { 'Content-Type': 'application/json', ...init?.headers } })
    let body: Envelope<T>
    try { body = await response.json() as Envelope<T> }
    catch { throw new Error(`本机服务返回了无法读取的响应（HTTP ${response.status}），请检查服务后重试。`) }
    if (!response.ok || !body?.ok) throw new Error(body?.error?.message ?? `请求失败 ${response.status}`)
    return body.data
  } catch (reason) {
    if (controller.signal.aborted) throw new Error('读取超过 20 秒，请重试；已有历史仍保留。')
    if (reason instanceof TypeError) throw new Error('无法连接本机服务，请检查服务是否运行后重试。')
    throw reason
  } finally { clearTimeout(timer) }
}
