/**
 * 画面全体（アップロード・ステータス・属性パネル）
 *
 * 状態は state にまとめ、変更したら対応する render 関数を呼んで DOM に反映する。
 * 3D ビューア（IfcViewer）とはコールバックでつなぐ。
 */
import { fetchElement, modelFileUrl, uploadModel } from './api'
import { append, el, replaceChildren } from './lib/dom'
import { classLabel, propLabel, psetLabel } from './lib/ifcLabels'
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
      state.error = message
      renderHeader()
    },
  })

  fileInput.addEventListener('change', () => void onFileChange())

  // ---- イベント処理 ----
  async function onFileChange() {
    const file = fileInput.files?.[0]
    if (!file) return
    state.error = ''
    state.element = null
    state.uploading = true
    state.status = 'サーバーで解析中…'
    renderHeader()
    renderSide()
    try {
      const summary = await uploadModel(file)
      state.model = summary
      hintEl.hidden = true
      void viewer.load(modelFileUrl(summary.modelId))
    } catch (err) {
      state.error = err instanceof Error ? err.message : String(err)
      state.status = ''
    } finally {
      state.uploading = false
      fileInput.value = '' // 同じファイルを再選択できるように
      renderHeader()
      renderSide()
    }
  }

  async function onSelect(expressId: number | null) {
    if (expressId === null || !state.model) {
      state.element = null
    } else {
      try {
        state.element = await fetchElement(state.model.modelId, expressId)
      } catch {
        // 形状はあるが IfcElement ではないもの（空間など）はAPI側で404になる
        state.element = { notFound: true, expressId }
      }
    }
    renderSide()
  }

  // ---- 描画 ----
  function renderHeader() {
    fileInput.disabled = state.uploading
    uploadLabel.classList.toggle('disabled', state.uploading)
    uploadText.data = state.uploading ? '解析中…' : 'IFCファイルを開く'
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

function muted(text: string): HTMLElement {
  return el('p', { class: 'muted' }, text)
}

function formatValue(v: unknown): string {
  if (v === true) return 'はい'
  if (v === false) return 'いいえ'
  if (v === null || v === undefined || v === '') return '—'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}
