/**
 * 3Dビューア
 * - load(url) で IFC を読み込んで表示
 * - マウス: 左ドラッグ=回転 / 右ドラッグ=平行移動 / ホイール=ズーム
 * - 部材をクリックすると onSelect で expressID を通知（空クリックは null）
 *
 * API（api.ts）は知らない。入力はメソッド呼び出し、出力はコンストラクタで受け取るコールバック。
 */
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { IfcAPI } from 'web-ifc'
import { buildIfcGroup } from '../lib/ifcLoader'
import { el } from '../lib/dom'

export interface IfcViewerEvents {
  onSelect?: (expressID: number | null) => void
  onLoaded?: (payload: { meshCount: number }) => void
  onError?: (message: string) => void
}

export class IfcViewer {
  private readonly root: HTMLDivElement
  private readonly overlay: HTMLDivElement
  private readonly renderer: THREE.WebGLRenderer
  private readonly scene = new THREE.Scene()
  private readonly camera = new THREE.PerspectiveCamera(50, 1, 0.1, 5000)
  private readonly controls: OrbitControls
  private readonly resizeObserver: ResizeObserver
  private readonly raycaster = new THREE.Raycaster()

  private ifcApi: IfcAPI | null = null
  private modelGroup: THREE.Group | null = null
  private selected: number | null = null
  // ドラッグ（視点操作）とクリックを区別するため、押した位置と離した位置を比べる
  private downPos: { x: number; y: number } | null = null

  private readonly highlightMaterial = new THREE.MeshLambertMaterial({
    color: 0xff7a1a,
    side: THREE.DoubleSide,
    // 壁の角など隣の部材と面が重なる箇所で、ハイライト側を常に手前に描く（Zファイティング対策）
    polygonOffset: true,
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
  })

  constructor(
    container: HTMLElement,
    private readonly events: IfcViewerEvents = {},
  ) {
    this.overlay = el('div', { class: 'viewer-overlay' }, '3Dモデルを読み込み中…')
    this.overlay.hidden = true
    this.root = el('div', { class: 'viewer' }, this.overlay)
    container.appendChild(this.root)

    this.scene.background = new THREE.Color(0xeef1f5)
    this.camera.position.set(15, 12, 15)

    this.renderer = new THREE.WebGLRenderer({ antialias: true })
    this.renderer.setPixelRatio(window.devicePixelRatio)
    this.root.prepend(this.renderer.domElement)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true

    this.scene.add(new THREE.AmbientLight(0xffffff, 1.2))
    const sun = new THREE.DirectionalLight(0xffffff, 1.5)
    sun.position.set(20, 40, 25)
    this.scene.add(sun)
    this.scene.add(new THREE.GridHelper(100, 100, 0xc5cbd3, 0xdde1e6))

    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(this.root)
    this.resize()

    // removeEventListener できるようにアロー関数のプロパティで登録する
    this.renderer.domElement.addEventListener('pointerdown', this.onPointerDown)
    this.renderer.domElement.addEventListener('pointerup', this.onPointerUp)
    this.renderer.setAnimationLoop(() => {
      this.controls.update()
      this.renderer.render(this.scene, this.camera)
    })
  }

  /** 画面から取り外すときに呼ぶ（GPU リソース・監視・イベントを解放） */
  dispose(): void {
    this.renderer.setAnimationLoop(null)
    this.resizeObserver.disconnect()
    this.renderer.domElement.removeEventListener('pointerdown', this.onPointerDown)
    this.renderer.domElement.removeEventListener('pointerup', this.onPointerUp)
    this.clearModel()
    this.controls.dispose()
    this.highlightMaterial.dispose()
    this.renderer.dispose()
    this.root.remove()
  }

  async load(url: string): Promise<void> {
    this.overlay.hidden = false
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error(`IFCファイルを取得できませんでした (${res.status})`)
      const data = new Uint8Array(await res.arrayBuffer())

      const { group, meshCount } = buildIfcGroup(await this.getIfcApi(), data)
      this.clearModel()
      this.modelGroup = group
      this.scene.add(group)
      this.fitCamera(group)
      this.events.onLoaded?.({ meshCount })
    } catch (e) {
      this.events.onError?.(e instanceof Error ? e.message : String(e))
    } finally {
      this.overlay.hidden = true
    }
  }

  // 同じ expressID を持つ Mesh（1部材が複数Meshの場合あり）をまとめて色替え
  highlight(expressID: number | null): void {
    if (this.selected !== null) {
      this.modelMeshes().forEach((m) => {
        if (m.userData.originalMaterial) {
          m.material = m.userData.originalMaterial
          delete m.userData.originalMaterial
        }
      })
    }
    this.selected = expressID
    if (expressID === null) return
    this.modelMeshes()
      .filter((m) => m.userData.expressID === expressID)
      .forEach((m) => {
        m.userData.originalMaterial = m.material
        m.material = this.highlightMaterial
      })
  }

  private resize(): void {
    const { clientWidth: w, clientHeight: h } = this.root
    if (!w || !h) return
    this.renderer.setSize(w, h)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  private async getIfcApi(): Promise<IfcAPI> {
    if (!this.ifcApi) {
      const api = new IfcAPI()
      // public/ に置いた web-ifc.wasm を読む（npm install 時に自動コピー）
      api.SetWasmPath('/', true)
      await api.Init()
      this.ifcApi = api
    }
    return this.ifcApi
  }

  private clearModel(): void {
    this.selected = null
    if (!this.modelGroup) return
    this.scene.remove(this.modelGroup)
    this.modelGroup.traverse((o) => {
      if (o instanceof THREE.Mesh) o.geometry.dispose()
    })
    this.modelGroup = null
  }

  // モデル全体が画面に収まるようにカメラを移動
  private fitCamera(object: THREE.Object3D): void {
    const box = new THREE.Box3().setFromObject(object)
    const size = box.getSize(new THREE.Vector3()).length()
    const center = box.getCenter(new THREE.Vector3())
    this.controls.target.copy(center)
    this.camera.position.copy(center).add(new THREE.Vector3(1, 0.8, 1).normalize().multiplyScalar(size * 1.2))
    this.camera.near = size / 1000
    this.camera.far = size * 20
    this.camera.updateProjectionMatrix()
  }

  // ---- クリック選択 ----
  private readonly onPointerDown = (e: PointerEvent): void => {
    this.downPos = { x: e.clientX, y: e.clientY }
  }

  private readonly onPointerUp = (e: PointerEvent): void => {
    if (e.button !== 0 || !this.downPos) return
    const moved = Math.hypot(e.clientX - this.downPos.x, e.clientY - this.downPos.y)
    if (moved < 4) this.pick(e)
  }

  private pick(e: PointerEvent): void {
    if (!this.modelGroup) return
    const rect = this.renderer.domElement.getBoundingClientRect()
    const pointer = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    )
    this.raycaster.setFromCamera(pointer, this.camera)
    const hit = this.raycaster.intersectObjects(this.modelGroup.children, false)[0]
    const expressID: number | null = hit ? hit.object.userData.expressID : null
    this.highlight(expressID)
    this.events.onSelect?.(expressID)
  }

  // modelGroup の子は ifcLoader.ts で作った Mesh のみ
  private modelMeshes(): THREE.Mesh[] {
    return this.modelGroup ? (this.modelGroup.children as THREE.Mesh[]) : []
  }
}
