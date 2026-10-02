// FastAPI バックエンドの呼び出し
// 開発時は vite.config.ts のプロキシで /api → http://127.0.0.1:8001 に転送される
import type { ElementDetail, ModelSummary } from './types'

/** API がエラーを返したとき（status が 0 のときは通信そのものの失敗） */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(input, init)
  } catch {
    throw new ApiError('サーバーに接続できませんでした。ネットワークとサーバーの起動状態を確認してください。', 0)
  }
  const body: unknown = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(errorDetail(body) ?? `通信エラー (${res.status})`, res.status)
  return body as T
}

// FastAPI のエラーは {"detail": "..."}。検証エラー(422)では detail が配列になる
function errorDetail(body: unknown): string | null {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return null
  const { detail } = body
  return typeof detail === 'string' ? detail : null
}

export async function uploadModel(file: File): Promise<ModelSummary> {
  const form = new FormData()
  form.append('file', file)
  return request<ModelSummary>('/api/models', { method: 'POST', body: form })
}

export async function fetchElement(modelId: string, expressId: number): Promise<ElementDetail> {
  return request<ElementDetail>(`/api/models/${modelId}/elements/${expressId}`)
}

export function modelFileUrl(modelId: string): string {
  return `/api/models/${modelId}/file`
}
