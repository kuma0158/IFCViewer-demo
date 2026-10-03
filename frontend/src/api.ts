// FastAPI バックエンドの呼び出し
// 開発時は vite.config.ts のプロキシで /api → http://127.0.0.1:8001 に転送される
import type { ElementDetail, ModelSummary, UploadSession, UploadStatus } from './types'

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
  if (!res.ok) throw new ApiError(errorDetail(body) ?? fallbackMessage(res.status), res.status)
  return body as T
}

// FastAPI のエラーは {"detail": "..."}。検証エラー(422)では detail が配列になる
function errorDetail(body: unknown): string | null {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return null
  const { detail } = body
  return typeof detail === 'string' ? detail : null
}

// バックエンドより手前（Cloudflare など）が返したエラーには detail が無いので、ここで言葉を補う
function fallbackMessage(status: number): string {
  if (status === 413) return 'データが大きすぎて途中の経路で拒否されました (413)'
  if (status === 502 || status === 504 || status === 524) return `サーバーの応答がありませんでした (${status})。しばらくしてからやり直してください。`
  return `通信エラー (${status})`
}

/** アップロードの進み具合（画面表示用） */
export type UploadProgress =
  | { phase: 'uploading'; sentBytes: number; totalBytes: number }
  | { phase: 'processing' }

const RETRY_LIMIT = 3
const POLL_INTERVAL_MS = 1000

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// 一時的な失敗（通信断・サーバー側の一時エラー）だけをやり直す。入力の誤り（4xx）はやり直さない
function isRetryable(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 0 || e.status >= 500)
}

async function withRetry<T>(fn: () => Promise<T>): Promise<T> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await fn()
    } catch (e) {
      if (attempt >= RETRY_LIMIT || !isRetryable(e)) throw e
      await sleep(1000 * attempt)
    }
  }
}

/**
 * IFC をアップロードして解析結果を受け取る
 *
 * Cloudflare 経由では 1 リクエスト 100MB まで・応答待ち 100 秒までの制限があるため、
 *   ① ファイルをチャンク（サーバーが決めた大きさ）に分けて順に送り
 *   ② 送り終えたら解析を依頼し（サーバーは裏で解析してすぐ返す）
 *   ③ 解析が終わるまで進み具合を問い合わせる
 * という手順にしている。小さなファイルはチャンク 1 個で同じ手順をたどる。
 */
export async function uploadModel(file: File, onProgress?: (p: UploadProgress) => void): Promise<ModelSummary> {
  const session = await request<UploadSession>('/api/uploads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: file.name, size: file.size }),
  })
  const base = `/api/uploads/${session.uploadId}`

  let sent = 0
  onProgress?.({ phase: 'uploading', sentBytes: 0, totalBytes: file.size })
  for (let i = 0; i < session.totalChunks; i++) {
    const chunk = file.slice(i * session.chunkSize, (i + 1) * session.chunkSize)
    // 同じ番号の再送はサーバー側で上書きされるので、途中で失敗してもやり直せる
    await withRetry(() =>
      request(`${base}/chunks/${i}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: chunk,
      }),
    )
    sent += chunk.size
    onProgress?.({ phase: 'uploading', sentBytes: sent, totalBytes: file.size })
  }

  await withRetry(() => request<UploadStatus>(`${base}/complete`, { method: 'POST' }).catch(alreadyStarted))
  onProgress?.({ phase: 'processing' })

  for (;;) {
    const status = await withRetry(() => request<UploadStatus>(base))
    if (status.status === 'done' && status.modelId) {
      return withRetry(() => request<ModelSummary>(`/api/models/${status.modelId}`))
    }
    if (status.status === 'error') throw new ApiError(status.detail ?? 'IFCを解析できませんでした', 422)
    await sleep(POLL_INTERVAL_MS)
  }
}

// complete の応答が途中で失われて再送した場合、サーバーは「既に受付済み」(409) を返す。これは成功とみなす
function alreadyStarted(e: unknown): UploadStatus | Promise<never> {
  if (e instanceof ApiError && e.status === 409) return { status: 'processing' } as UploadStatus
  return Promise.reject(e)
}

export async function fetchElement(modelId: string, expressId: number): Promise<ElementDetail> {
  return request<ElementDetail>(`/api/models/${modelId}/elements/${expressId}`)
}

export function modelFileUrl(modelId: string): string {
  return `/api/models/${modelId}/file`
}
