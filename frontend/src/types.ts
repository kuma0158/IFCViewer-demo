// FastAPI バックエンド（backend/ifc_service.py）が返す JSON の型
// バックエンドのキー名を変えたら、ここも合わせて変更する

/** 部材一覧の1行（summarize() の elements） */
export interface ElementRow {
  /** IFCファイル内の番号(#123)。web-ifc の expressID と共通 */
  expressId: number
  globalId: string
  ifcClass: string
  name: string | null
  storey: string
}

/** 階ごとの集計（summarize() の storeys） */
export interface StoreySummary {
  name: string
  total: number
  classCounts: Record<string, number>
}

/** POST /api/models ・ GET /api/models/{modelId} のレスポンス */
export interface ModelSummary {
  modelId: string
  filename: string
  schema: string
  project: string | null
  elementCount: number
  classCounts: Record<string, number>
  storeys: StoreySummary[]
  elements: ElementRow[]
}

/** プロパティセット名 → { プロパティ名: 値 }（値は真偽値・数値・文字列・入れ子のオブジェクト等） */
export type PropertySets = Record<string, Record<string, unknown>>

/** GET /api/models/{modelId}/elements/{expressId} のレスポンス */
export interface ElementDetail extends ElementRow {
  propertySets: PropertySets
}

/**
 * モデルが見つからないときの 404 の detail（backend/main.py の MODEL_NOT_FOUND_DETAIL と同じ文言）
 * 部材の 404（対象外）と、モデルの 404（サーバー再起動などで消えた）を区別するために使う
 */
export const MODEL_NOT_FOUND_DETAIL = 'モデルが見つかりません'

/** POST /api/uploads のレスポンス（分割アップロードの開始） */
export interface UploadSession {
  uploadId: string
  /** 1 チャンクのバイト数（最後のチャンクだけ端数） */
  chunkSize: number
  totalChunks: number
}

/** GET /api/uploads/{uploadId} のレスポンス（backend/upload_sessions.py の to_status()） */
export interface UploadStatus {
  uploadId: string
  status: 'uploading' | 'processing' | 'done' | 'error'
  receivedChunks: number
  totalChunks: number
  /** status が done のとき */
  modelId?: string
  /** status が error のとき（原因と対処の日本語メッセージ） */
  detail?: string
}
