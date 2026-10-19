type Envelope<T> = { ok: boolean; data: T; error: { message: string; code: string } | null; request_id?: string }

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  const body = (await response.json()) as Envelope<T>
  if (!response.ok || !body.ok) throw new Error(body.error?.message ?? `请求失败 ${response.status}`)
  return body.data
}
