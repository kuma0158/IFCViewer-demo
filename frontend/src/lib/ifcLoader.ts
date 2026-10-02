/**
 * IFC → Three.js 変換
 *
 * web-ifc（IFCをブラウザで解析するWebAssemblyライブラリ）が出力する
 * 三角形メッシュを、Three.js の Mesh に変換する。
 *
 * 各 Mesh の userData.expressID に部材の番号(#123)を持たせるのがポイント。
 * クリックした Mesh からこの番号を取り出し、FastAPI の
 *   GET /api/models/{modelId}/elements/{expressId}
 * に渡すことで属性情報を取得できる。
 */
import * as THREE from 'three'
import type { Color, IfcAPI } from 'web-ifc'

export interface IfcGroupResult {
  group: THREE.Group
  meshCount: number
}

/**
 * @param ifcApi 初期化済みの IfcAPI
 * @param data IFCファイルのバイト列
 */
export function buildIfcGroup(ifcApi: IfcAPI, data: Uint8Array): IfcGroupResult {
  const modelID = ifcApi.OpenModel(data)
  const group = new THREE.Group()
  const materials = new Map<string, THREE.MeshLambertMaterial>() // 同じ色のマテリアルは使い回す
  let meshCount = 0

  try {
    ifcApi.StreamAllMeshes(modelID, (flatMesh) => {
      const placed = flatMesh.geometries
      for (let i = 0; i < placed.size(); i++) {
        const pg = placed.get(i)
        const geometry = toBufferGeometry(ifcApi, modelID, pg.geometryExpressID)
        const mesh = new THREE.Mesh(geometry, getMaterial(materials, pg.color))

        // IFC内の配置（位置・回転）を反映
        const matrix = new THREE.Matrix4().fromArray(pg.flatTransformation)
        mesh.applyMatrix4(matrix)

        mesh.userData.expressID = flatMesh.expressID
        group.add(mesh)
        meshCount++
      }
    })
  } finally {
    ifcApi.CloseModel(modelID)
  }

  return { group, meshCount }
}

function toBufferGeometry(ifcApi: IfcAPI, modelID: number, geometryExpressID: number): THREE.BufferGeometry {
  const g = ifcApi.GetGeometry(modelID, geometryExpressID)
  // 頂点データは [x, y, z, nx, ny, nz] の6要素で1頂点
  const verts = ifcApi.GetVertexArray(g.GetVertexData(), g.GetVertexDataSize())
  const indices = ifcApi.GetIndexArray(g.GetIndexData(), g.GetIndexDataSize())

  const count = verts.length / 6
  const positions = new Float32Array(count * 3)
  const normals = new Float32Array(count * 3)
  for (let i = 0; i < count; i++) {
    positions.set(verts.subarray(i * 6, i * 6 + 3), i * 3)
    normals.set(verts.subarray(i * 6 + 3, i * 6 + 6), i * 3)
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3))
  geometry.setIndex(new THREE.BufferAttribute(indices.slice(), 1))
  g.delete() // WebAssembly側のメモリを解放
  return geometry
}

function getMaterial(cache: Map<string, THREE.MeshLambertMaterial>, color: Color): THREE.MeshLambertMaterial {
  const key = `${color.x},${color.y},${color.z},${color.w}`
  let material = cache.get(key)
  if (!material) {
    material = new THREE.MeshLambertMaterial({
      color: new THREE.Color(color.x, color.y, color.z),
      transparent: color.w < 1,
      opacity: color.w,
      side: THREE.DoubleSide,
    })
    cache.set(key, material)
  }
  return material
}
