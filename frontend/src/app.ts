/**
 * 画面全体（アップロード・ステータス・属性パネル）
 *
 * 状態は state にまとめ、変更したら対応する render 関数を呼んで DOM に反映する。
 * 3D ビューア（IfcViewer）とはコールバックでつなぐ。
 */
import { ApiError, fetchElement, modelFileUrl, uploadModel } from './api'
import { append, el, replaceChildren } from './lib/dom'
import { classLabel, propLabel, psetLabel } from './lib/ifcLabels'
import { MODEL_NOT_FOUND_DETAIL } from './types'
import type { ElementDetail, ModelSummary, PropertySets } from './types'
import { IfcViewer } from './viewer/IfcViewer'

/** 形状はあるが属性表示の対象外のもの（IfcElement ではない空間など） */
interface NotFoundElement {
  notFound: true
  expressId: number
}

interface AppState {
  model: ModelSummary | null // POST /api/models のレスポンス
  element: ElementDetail | NotFoundElement | null // 選択中の部材の属性
  status: string
  error: string
  uploading: boolean
}

export function mountApp(root: HTMLElement): void {
  const state: AppState = {
    model: null,
    element: null,
    status: 'IFCファイルを選択してください',
    error: '',
    uploading: false,
  }
  // 選択のたびに増やす番号。応答が届いたとき最新の選択でなければ捨てる
  // （A→B と素早くクリックして A の応答が後から届くと、ハイライトとパネルが食い違うため）
  let selectSeq = 0

  // ---- 骨組み（一度だけ作る） ----
  const fileInput = el('input', { attrs: { type: 'file', accept: '.ifc' } })
  const uploadText = document.createTextNode('')
  const uploadLabel = el('label', { class: 'upload' }, fileInput, uploadText)
  const statusEl = el('p', { class: 'status' })
  const errorEl = el('p', { class: 'error' })
  const hintEl = el('p', { class: 'hint' }, 'ここに3Dモデルが表示されます')
  const viewerPane = el('section', { class: 'viewer-pane' }, hintEl)
  const side = el('aside', { class: 'side' })

  append(
    root,
    el(
      'div',
      { class: 'app' },
      el('header', {}, el('h1', {}, 'IFC Viewer ', el('span', {}, 'Pilot')), uploadLabel, statusEl),
      errorEl,
      el('main', {}, viewerPane, side),
    ),
  )

  const viewer = new IfcViewer(viewerPane, {
    onLoaded: ({ meshCount }) => {
      if (!state.model) return
      state.status = `${state.model.filename}：部材 ${state.model.elementCount} 件 / 3Dメッシュ ${meshCount} 件`
      renderHeader()
    },
    onSelect: (expressId) => void onSelect(expressId),
    onError: (message) => {
      // ビューアは失敗時に表示中のモデルを消すので、画面の状態もモデル無しに揃える
      state.model = null
      state.element = null
      selectSeq++
      state.error = message
      state.status = '3D表示に失敗しました'
      hintEl.hidden = false
      renderHeader()
      renderSide()
    },
  })

  fileInput.addEventListener('change', () => void onFileChange())

  // ---- イベント処理 ----
  async function onFileChange() {
    const file = fileInput.files?.[0]
    if (!file) return
    const previousStatus = state.status
    state.error = ''
    state.element = null
    selectSeq++ // 前のモデルへの属性取得の応答が遅れて届いても反映しない
    state.uploading = true
    state.status = '送信を準備中…'
    renderHeader()
    renderSide()
    try {
      const summary = await uploadModel(file, (p) => {
        state.status =
          p.phase === 'uploading'
            ? `送信中… ${percent(p.sentBytes, p.totalBytes)}%（${mb(p.sentBytes)} / ${mb(p.totalBytes)} MB）`
            : 'サーバーで解析中…（大きなファイルは数分かかることがあります）'
        renderHeader()
      })
      state.model = summary
      state.status = `${summary.filename}：3Dモデルを準備中…`
      hintEl.hidden = true
      void viewer.load(modelFileUrl(summary.modelId))
    } catch (err) {
      state.error = err instanceof Error ? err.message : String(err)
      // 前のモデルは画面に残って操作できるので、そのステータスに戻す
      state.status = state.model ? previousStatus : ''
    } finally {
      state.uploading = false
      fileInput.value = '' // 同じファイルを再選択できるように
      renderHeader()
      renderSide()
    }
  }

  async function onSelect(expressId: number | null) {
    const seq = ++selectSeq
    const model = state.model
    if (expressId === null || !model) {
      state.element = null
      renderSide()
      return
    }
    let element: AppState['element']
    let error = ''
    try {
      element = await fetchElement(model.modelId, expressId)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404 && err.message !== MODEL_NOT_FOUND_DETAIL) {
        // 形状はあるが IfcElement ではないもの（空間など）はAPI側で404になる。エラーではなく「対象外」として表示
        element = { notFound: true, expressId }
      } else {
        element = null
        error =
          err instanceof ApiError && err.message === MODEL_NOT_FOUND_DETAIL
            ? 'サーバー側でモデルが見つかりません（サーバーの再起動などで消えた可能性があります）。もう一度IFCファイルを開いてください。'
            : err instanceof Error
              ? err.message
              : String(err)
      }
    }
    if (seq !== selectSeq) return // より新しい選択が始まっていれば、この応答は捨てる
    if (error) viewer.highlight(null) // 属性が出せないのにハイライトだけ残ると、選択中に見えてしまうため
    state.element = element
    state.error = error
    renderHeader()
    renderSide()
  }

  // ---- 描画 ----
  function renderHeader() {
    fileInput.disabled = state.uploading
    uploadLabel.classList.toggle('disabled', state.uploading)
    uploadText.data = state.uploading ? '読み込み中…' : 'IFCファイルを開く'
    statusEl.textContent = state.status
    errorEl.textContent = state.error
    errorEl.hidden = !state.error
  }

  function renderSide() {
    const { model, element } = state
    let body: Node[]
    if (!model) body = [muted('モデルを読み込んでください。')]
    else if (!element) body = [muted('3D画面の部材をクリックすると、属性情報が表示されます。')]
    else if ('notFound' in element) body = [muted(`#${element.expressId} は属性表示の対象外です。`)]
    else body = elementDetail(element)
    replaceChildren(side, el('h2', {}, '部材の属性'), ...body)
  }

  renderHeader()
  renderSide()
}

function elementDetail(element: ElementDetail): Node[] {
  const basic = el(
    'dl',
    { class: 'basic' },
    el('dt', {}, '種類'),
    el('dd', {}, `${classLabel(element.ifcClass)} `, el('small', {}, element.ifcClass)),
    el('dt', {}, '名前'),
    el('dd', {}, formatValue(element.name)),
    el('dt', {}, '階'),
    el('dd', {}, element.storey),
    el('dt', {}, 'GlobalId'),
    el('dd', { class: 'mono' }, element.globalId),
  )
  const psetNames = Object.keys(element.propertySets)
  if (!psetNames.length) return [basic, muted('プロパティセットはありません。')]
  return [basic, ...psetNames.map((name) => psetBlock(name, element.propertySets[name]))]
}

function psetBlock(psetName: string, props: PropertySets[string]): HTMLElement {
  const label = psetLabel(psetName)
  return el(
    'div',
    { class: 'pset' },
    el('h3', {}, `${label} `, label !== psetName && el('small', {}, psetName)),
    el(
      'table',
      {},
      el(
        'tbody',
        {},
        ...Object.entries(props).map(([key, value]) =>
          el('tr', {}, el('th', { title: key }, propLabel(key)), el('td', {}, formatValue(value))),
        ),
      ),
    ),
  )
}

function percent(part: number, total: number): number {
  return total ? Math.floor((part / total) * 100) : 100
}

function mb(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(1)
}

function muted(text: string): HTMLElement {
  return el('p', { class: 'muted' }, text)
}

function formatValue(v: unknown): string {
  if (v === true) return 'はい'
  if (v === false) return 'いいえ'
  if (v === null || v === undefined || v === '') return '—'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}
