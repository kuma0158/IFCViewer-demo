<script setup lang="ts">
import { ref } from 'vue'
import IfcViewer from './components/IfcViewer.vue'
import { fetchElement, modelFileUrl, uploadModel } from './api'
import { classLabel, propLabel, psetLabel } from './lib/ifcLabels'
import type { ElementDetail, ModelSummary } from './types'

/** 形状はあるが属性表示の対象外のもの（IfcElement ではない空間など） */
interface NotFoundElement {
  notFound: true
  expressId: number
}

const model = ref<ModelSummary | null>(null) // POST /api/models のレスポンス
const fileUrl = ref<string | null>(null)
const element = ref<ElementDetail | NotFoundElement | null>(null) // 選択中の部材の属性
const status = ref('IFCファイルを選択してください')
const error = ref('')
const uploading = ref(false)

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  error.value = ''
  element.value = null
  uploading.value = true
  status.value = 'サーバーで解析中…'
  try {
    const summary = await uploadModel(file)
    model.value = summary
    fileUrl.value = modelFileUrl(summary.modelId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = ''
  } finally {
    uploading.value = false
    input.value = '' // 同じファイルを再選択できるように
  }
}

function onLoaded({ meshCount }: { meshCount: number }) {
  if (!model.value) return
  status.value = `${model.value.filename}：部材 ${model.value.elementCount} 件 / 3Dメッシュ ${meshCount} 件`
}

async function onSelect(expressId: number | null) {
  if (expressId === null || !model.value) {
    element.value = null
    return
  }
  try {
    element.value = await fetchElement(model.value.modelId, expressId)
  } catch {
    // 形状はあるが IfcElement ではないもの（空間など）はAPI側で404になる
    element.value = { notFound: true, expressId }
  }
}

function formatValue(v: unknown): string {
  if (v === true) return 'はい'
  if (v === false) return 'いいえ'
  if (v === null || v === undefined || v === '') return '—'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}
</script>

<template>
  <div class="app">
    <header>
      <h1>IFC Viewer <span>Pilot</span></h1>
      <label class="upload" :class="{ disabled: uploading }">
        <input type="file" accept=".ifc" :disabled="uploading" @change="onFileChange" />
        {{ uploading ? '解析中…' : 'IFCファイルを開く' }}
      </label>
      <p class="status">{{ status }}</p>
    </header>

    <p v-if="error" class="error">{{ error }}</p>

    <main>
      <section class="viewer-pane">
        <IfcViewer :file-url="fileUrl" @loaded="onLoaded" @select="onSelect" @error="(m) => (error = m)" />
        <p v-if="!fileUrl" class="hint">ここに3Dモデルが表示されます</p>
      </section>

      <aside class="side">
        <h2>部材の属性</h2>
        <p v-if="!model" class="muted">モデルを読み込んでください。</p>
        <p v-else-if="!element" class="muted">3D画面の部材をクリックすると、属性情報が表示されます。</p>
        <p v-else-if="'notFound' in element" class="muted">#{{ element.expressId }} は属性表示の対象外です。</p>
        <template v-else>
          <dl class="basic">
            <dt>種類</dt>
            <dd>{{ classLabel(element.ifcClass) }} <small>{{ element.ifcClass }}</small></dd>
            <dt>名前</dt>
            <dd>{{ formatValue(element.name) }}</dd>
            <dt>階</dt>
            <dd>{{ element.storey }}</dd>
            <dt>GlobalId</dt>
            <dd class="mono">{{ element.globalId }}</dd>
          </dl>
          <p v-if="!Object.keys(element.propertySets).length" class="muted">プロパティセットはありません。</p>
          <div v-for="(props, psetName) in element.propertySets" :key="psetName" class="pset">
            <h3>
              {{ psetLabel(psetName) }}
              <small v-if="psetLabel(psetName) !== psetName">{{ psetName }}</small>
            </h3>
            <table>
              <tr v-for="(value, key) in props" :key="key">
                <th :title="key">{{ propLabel(key) }}</th>
                <td>{{ formatValue(value) }}</td>
              </tr>
            </table>
          </div>
        </template>
      </aside>
    </main>
  </div>
</template>

<style>
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  font-family: system-ui, -apple-system, 'Segoe UI', 'Hiragino Sans', 'Meiryo', sans-serif;
  color: #1f2933;
  background: #f7f8fa;
}
</style>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  background: #1f2933;
  color: #fff;
  flex-wrap: wrap;
}
h1 {
  font-size: 18px;
  margin: 0;
}
h1 span {
  font-weight: 400;
  opacity: 0.6;
}
.upload input {
  display: none;
}
.upload {
  background: #ff7a1a;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}
.upload.disabled {
  opacity: 0.6;
  cursor: wait;
}
.status {
  margin: 0;
  font-size: 13px;
  opacity: 0.8;
}
.error {
  margin: 0;
  padding: 8px 16px;
  background: #fde8e8;
  color: #9b1c1c;
  font-size: 14px;
}
main {
  flex: 1;
  display: flex;
  min-height: 0;
}
.viewer-pane {
  flex: 1;
  position: relative;
  min-width: 0;
}
.hint {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  margin: 0;
  color: #7b8794;
  pointer-events: none;
}
.side {
  width: 340px;
  overflow-y: auto;
  padding: 16px;
  background: #fff;
  border-left: 1px solid #e4e7eb;
}
h2 {
  font-size: 15px;
  margin: 0 0 12px;
}
.muted {
  color: #7b8794;
  font-size: 14px;
}
.basic {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 6px 8px;
  margin: 0 0 16px;
  font-size: 14px;
}
.basic dt {
  color: #7b8794;
}
.basic dd {
  margin: 0;
  word-break: break-all;
}
.basic small {
  color: #7b8794;
}
.mono {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
.pset h3 {
  font-size: 13px;
  margin: 12px 0 4px;
  color: #3e4c59;
}
.pset h3 small {
  font-weight: 400;
  color: #7b8794;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  text-align: left;
  padding: 4px 6px;
  border-bottom: 1px solid #f0f2f4;
  vertical-align: top;
  word-break: break-all;
}
th {
  color: #616e7c;
  font-weight: 500;
  width: 45%;
}

/* スマホ幅では縦並び */
@media (max-width: 760px) {
  main {
    flex-direction: column;
  }
  .viewer-pane {
    min-height: 55vh;
  }
  .side {
    width: 100%;
    border-left: none;
    border-top: 1px solid #e4e7eb;
  }
}
</style>
