<!--
  3Dビューア
  - props.fileUrl の IFC を読み込んで表示
  - マウス: 左ドラッグ=回転 / 右ドラッグ=平行移動 / ホイール=ズーム
  - 部材をクリックすると 'select' イベントで expressID を通知（空クリックは null）
-->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { IfcAPI } from 'web-ifc'
import { buildIfcGroup } from '../lib/ifcLoader'

const props = withDefaults(defineProps<{ fileUrl?: string | null }>(), { fileUrl: null })
const emit = defineEmits<{
  select: [expressID: number | null]
  loaded: [payload: { meshCount: number }]
  error: [message: string]
}>()

const container = ref<HTMLDivElement | null>(null)
const loading = ref(false)

// onMounted で必ず作成されるもの
let renderer!: THREE.WebGLRenderer
let scene!: THREE.Scene
let camera!: THREE.PerspectiveCamera
let controls!: OrbitControls
let resizeObserver!: ResizeObserver

let ifcApi: IfcAPI | null = null
let modelGroup: THREE.Group | null = null
let selected: number | null = null
const highlightMaterial = new THREE.MeshLambertMaterial({
  color: 0xff7a1a,
  side: THREE.DoubleSide,
  // 壁の角など隣の部材と面が重なる箇所で、ハイライト側を常に手前に描く（Zファイティング対策）
  polygonOffset: true,
  polygonOffsetFactor: -1,
  polygonOffsetUnits: -1,
})

onMounted(() => {
  const el = container.value!
  scene = new THREE.Scene()
  scene.background = new THREE.Color(0xeef1f5)

  camera = new THREE.PerspectiveCamera(50, 1, 0.1, 5000)
  camera.position.set(15, 12, 15)

  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(window.devicePixelRatio)
  el.appendChild(renderer.domElement)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true

  scene.add(new THREE.AmbientLight(0xffffff, 1.2))
  const sun = new THREE.DirectionalLight(0xffffff, 1.5)
  sun.position.set(20, 40, 25)
  scene.add(sun)
  scene.add(new THREE.GridHelper(100, 100, 0xc5cbd3, 0xdde1e6))

  resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(el)
  resize()

  renderer.domElement.addEventListener('pointerdown', onPointerDown)
  renderer.domElement.addEventListener('pointerup', onPointerUp)
  renderer.setAnimationLoop(() => {
    controls.update()
    renderer.render(scene, camera)
  })

  if (props.fileUrl) load(props.fileUrl)
})

onBeforeUnmount(() => {
  renderer.setAnimationLoop(null)
  resizeObserver.disconnect()
  clearModel()
  renderer.dispose()
})

watch(() => props.fileUrl, (url) => url && load(url))

function resize() {
  if (!container.value) return
  const { clientWidth: w, clientHeight: h } = container.value
  if (!w || !h) return
  renderer.setSize(w, h)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}

async function getIfcApi(): Promise<IfcAPI> {
  if (!ifcApi) {
    const api = new IfcAPI()
    // public/ に置いた web-ifc.wasm を読む（npm install 時に自動コピー）
    api.SetWasmPath('/', true)
    await api.Init()
    ifcApi = api
  }
  return ifcApi
}

async function load(url: string) {
  loading.value = true
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`IFCファイルを取得できませんでした (${res.status})`)
    const data = new Uint8Array(await res.arrayBuffer())

    const { group, meshCount } = buildIfcGroup(await getIfcApi(), data)
    clearModel()
    modelGroup = group
    scene.add(group)
    fitCamera(group)
    emit('loaded', { meshCount })
  } catch (e) {
    emit('error', e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

function clearModel() {
  selected = null
  if (!modelGroup) return
  scene.remove(modelGroup)
  modelGroup.traverse((o) => {
    if (o instanceof THREE.Mesh) o.geometry.dispose()
  })
  modelGroup = null
}

// モデル全体が画面に収まるようにカメラを移動
function fitCamera(object: THREE.Object3D) {
  const box = new THREE.Box3().setFromObject(object)
  const size = box.getSize(new THREE.Vector3()).length()
  const center = box.getCenter(new THREE.Vector3())
  controls.target.copy(center)
  camera.position.copy(center).add(new THREE.Vector3(1, 0.8, 1).normalize().multiplyScalar(size * 1.2))
  camera.near = size / 1000
  camera.far = size * 20
  camera.updateProjectionMatrix()
}

// ---- クリック選択 ----
// ドラッグ（視点操作）とクリックを区別するため、押した位置と離した位置を比べる
let downPos: { x: number; y: number } | null = null
function onPointerDown(e: PointerEvent) {
  downPos = { x: e.clientX, y: e.clientY }
}
function onPointerUp(e: PointerEvent) {
  if (e.button !== 0 || !downPos) return
  const moved = Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y)
  if (moved < 4) pick(e)
}

const raycaster = new THREE.Raycaster()
function pick(e: PointerEvent) {
  if (!modelGroup) return
  const rect = renderer.domElement.getBoundingClientRect()
  const pointer = new THREE.Vector2(
    ((e.clientX - rect.left) / rect.width) * 2 - 1,
    -((e.clientY - rect.top) / rect.height) * 2 + 1,
  )
  raycaster.setFromCamera(pointer, camera)
  const hit = raycaster.intersectObjects(modelGroup.children, false)[0]
  const expressID: number | null = hit ? hit.object.userData.expressID : null
  highlight(expressID)
  emit('select', expressID)
}

// modelGroup の子は ifcLoader.ts で作った Mesh のみ
function modelMeshes(): THREE.Mesh[] {
  return modelGroup ? (modelGroup.children as THREE.Mesh[]) : []
}

// 同じ expressID を持つ Mesh（1部材が複数Meshの場合あり）をまとめて色替え
function highlight(expressID: number | null) {
  if (selected !== null) {
    modelMeshes().forEach((m) => {
      if (m.userData.originalMaterial) {
        m.material = m.userData.originalMaterial
        delete m.userData.originalMaterial
      }
    })
  }
  selected = expressID
  if (expressID === null) return
  modelMeshes()
    .filter((m) => m.userData.expressID === expressID)
    .forEach((m) => {
      m.userData.originalMaterial = m.material
      m.material = highlightMaterial
    })
}

defineExpose({ highlight })
</script>

<template>
  <div class="viewer" ref="container">
    <div v-if="loading" class="overlay">3Dモデルを読み込み中…</div>
  </div>
</template>

<style scoped>
.viewer {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 300px;
  overflow: hidden;
}
.viewer :deep(canvas) {
  display: block;
}
.overlay {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.6);
  font-weight: 600;
}
</style>
