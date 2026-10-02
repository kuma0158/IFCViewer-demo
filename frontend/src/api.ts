// FastAPI バックエンドの呼び出し
// 開発時は vite.config.ts のプロキシで /api → http://127.0.0.1:8001 に転送される
import type { ElementDetail, ModelSummary } from './types'

async function handle<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail ?? `通信エラー (${res.status})`)
  return body as T
}

export async function uploadModel(file: File): Promise<ModelSummary> {
  const form = new FormData()
  form.append('file', file)
  return handle<ModelSummary>(await fetch('/api/models', { method: 'POST', body: form }))
}

export async function fetchElement(modelId: string, expressId: number): Promise<ElementDetail> {
  return handle<ElementDetail>(await fetch(`/api/models/${modelId}/elements/${expressId}`))
}

export function modelFileUrl(modelId: string): string {
  return `/api/models/${modelId}/file`
}
