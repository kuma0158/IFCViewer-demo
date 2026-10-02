# フロントエンド解説（Vue 3 + TypeScript + Three.js + web-ifc）

`frontend/` は、IFC ファイルをサーバーにアップロードし、ブラウザ上で 3D 表示して、クリックした部材の属性を表示する画面です。

## 全体像

```
frontend/
├─ index.html                    エントリ HTML（#app に Vue をマウント）
├─ vite.config.ts                Vite 設定（/api を FastAPI へプロキシ）
├─ tsconfig.json                 TypeScript 設定（strict）
├─ package.json                  依存関係・npm スクリプト
├─ scripts/copy-wasm.mjs         web-ifc.wasm を public/ にコピー（npm install 時）
├─ public/web-ifc.wasm           web-ifc 本体（WebAssembly）
└─ src/
   ├─ main.ts                    Vue アプリの起動
   ├─ App.vue                    画面全体（アップロード・ステータス・属性パネル）
   ├─ api.ts                     バックエンド API の呼び出し
   ├─ types.ts                   API レスポンスの型定義
   ├─ components/IfcViewer.vue   3D ビューア（表示・視点操作・クリック選択・ハイライト）
   └─ lib/
      ├─ ifcLoader.ts            web-ifc の出力 → Three.js の Mesh 変換
      └─ ifcLabels.ts            IFC クラス名の日本語ラベル
```

## 使用ライブラリ

| ライブラリ | 用途 |
|---|---|
| vue 3 | 画面の構築（Composition API / `<script setup>`） |
| three | WebGL による 3D 描画 |
| web-ifc | IFC をブラウザ内で解析し、三角形メッシュを出力する WebAssembly ライブラリ |
| vite + @vitejs/plugin-vue | 開発サーバー・ビルド |
| typescript 5.9 + vue-tsc | 型チェック（`.vue` ファイルの中も含めてチェック） |
| @types/three | three の型定義（web-ifc は型定義を同梱） |

## TypeScript 化のポイント

- **設定**: `tsconfig.json` で `strict: true`。`npm run build` は `vue-tsc --noEmit`（型チェック）が通ってから `vite build` を実行します。型チェックだけなら `npm run typecheck`。
- **バージョン**: TypeScript は `~5.9.3` に固定しています。最新の TypeScript 7 はネイティブ（Go）実装で、vue-tsc が対応していないためです。
- **API の型（src/types.ts）**: `ModelSummary`（アップロード結果）、`ElementDetail`（部材の属性）などを、`backend/ifc_service.py` の戻り値に合わせて定義しています。バックエンドのキー名を変えたら、ここも合わせて変えます。キー名の書き間違い（例: `elementCnt`）はビルド時にエラーになります。
- **Vue コンポーネント**: `<script setup lang="ts">` を使い、props と emits を型で宣言しています（`defineProps<{...}>()` / `defineEmits<{...}>()`）。親の `App.vue` でイベントの引数の型が自動的に決まります。
- **未選択・対象外の表現**: `App.vue` の `element` は `ElementDetail | NotFoundElement | null` の型です。テンプレートの `v-else-if="'notFound' in element"` で絞り込むので、`v-else` の中では `ElementDetail` として扱えます。
- **three の型**: `modelGroup.children` は `Object3D[]` 型ですが、中身は `ifcLoader.ts` で作った `Mesh` だけなので、`modelMeshes()` で `Mesh[]` として扱っています。

## 処理の流れ

```
[App.vue] ファイル選択
   │  uploadModel(file)  ── POST /api/models ──▶ FastAPI（解析・modelId 発行）
   │  ◀── modelId・集計結果
   │  fileUrl = /api/models/{modelId}/file
   ▼
[IfcViewer.vue] fileUrl の変化を watch
   │  fetch(fileUrl) → Uint8Array
   │  buildIfcGroup(ifcApi, data)   ← lib/ifcLoader.ts
   │  scene に追加・カメラをフィット
   │  emit('loaded', { meshCount })
   ▼
部材クリック → Raycaster で Mesh 特定 → userData.expressID
   │  ハイライト + emit('select', expressID)
   ▼
[App.vue] fetchElement(modelId, expressID) ── GET /api/models/{id}/elements/{expressID}
   ◀── 属性情報 → 右パネルに表示
```

サーバー側（ifcopenshell）で集計・属性取得、ブラウザ側（web-ifc）で 3D 形状生成、と役割分担しています。
両者は IFC 内の番号 `#123`（**expressID**）が共通なので、これを使ってクリックした 3D 形状と属性データを結び付けます。

## 設定・起動まわり

### vite.config.ts

```js
server: { proxy: { '/api': 'http://127.0.0.1:8000' } }
```

開発時、`/api/...` へのリクエストを FastAPI に転送します。フロントのコードは相対パス `/api/...` で書けるため、CORS やホスト名を意識せずに済みます。

### scripts/copy-wasm.mjs

`npm install` の `postinstall` で実行され、`node_modules/web-ifc/web-ifc.wasm` を `public/` にコピーします。
`public/` のファイルはサイトのルート（`/web-ifc.wasm`）で配信されるので、web-ifc がそこから読み込めるようになります。

### main.ts / index.html

`createApp(App).mount('#app')` で `App.vue` を起動するだけです。

## src/api.ts — API 呼び出し

| 関数 | 内容 |
|---|---|
| `uploadModel(file)` | `FormData` に `file` を入れて `POST /api/models` |
| `fetchElement(modelId, expressId)` | `GET /api/models/{modelId}/elements/{expressId}` |
| `modelFileUrl(modelId)` | IFC 本体の URL 文字列を返す（fetch はビューア側で行う） |

共通の `handle(res)` で JSON を読み、エラー時は FastAPI の `detail` メッセージ（無ければ `通信エラー (ステータス)`）で `Error` を投げます。

## src/App.vue — 画面全体

### 状態（ref）

| 変数 | 内容 |
|---|---|
| `model` | `POST /api/models` のレスポンス（modelId・集計結果） |
| `fileUrl` | ビューアに渡す IFC の URL |
| `element` | 選択中の部材の属性（未選択は `null`） |
| `status` | ヘッダーに出すメッセージ |
| `error` | エラーメッセージ（赤帯で表示） |
| `uploading` | アップロード中フラグ（ボタンを無効化） |

### 主な関数

- **`onFileChange(e)`**
  ファイル選択時に呼ばれ、`uploadModel` → 成功したら `fileUrl` をセット。
  `fileUrl` が変わると `IfcViewer` が自動で 3D 読み込みを始めます。
  最後に `e.target.value = ''` として、同じファイルを再選択しても `change` が発火するようにしています。
- **`onLoaded({ meshCount })`**
  3D 読み込み完了時にステータス（ファイル名・部材数・メッシュ数）を更新。
- **`onSelect(expressId)`**
  `null`（何もない所をクリック）なら選択解除。それ以外は属性を取得。
  API が 404 を返すもの（`IfcSpace` など、形状はあるが `IfcElement` ではないもの）は `{ notFound: true }` として「対象外」と表示します。
- **`formatValue(v)`**
  真偽値を「はい／いいえ」、空値を「—」、オブジェクトを JSON 文字列に変換して表示用に整形。

### テンプレート構成

- **header**: タイトル、ファイル選択ボタン（`<input type="file">` を非表示にして `<label>` をボタン化）、ステータス
- **main**
  - 左 `.viewer-pane`: `<IfcViewer>`。未読み込み時はヒント文を重ねて表示
  - 右 `.side`: 属性パネル。基本情報（種類・名前・階・GlobalId）を `<dl>` で、プロパティセットごとに見出し＋`<table>` で表示
- 幅 760px 以下では縦並び（ビューア上・パネル下）になるレスポンシブ対応

## src/components/IfcViewer.vue — 3D ビューア

### インターフェース

- props: `fileUrl`（IFC の URL）
- emits:
  - `loaded` … 読み込み完了（`{ meshCount }`）
  - `select` … クリックされた部材の expressID（空クリックは `null`）
  - `error` … エラーメッセージ
- expose: `highlight(expressID)`（親から任意の部材をハイライトできる）

### 初期化（onMounted）

1. `Scene`（背景色 `#eef1f5`）、`PerspectiveCamera`、`WebGLRenderer` を作成し、canvas をコンテナに追加
2. `OrbitControls` でマウス操作（左ドラッグ回転・右ドラッグ平行移動・ホイールズーム）。`enableDamping` で慣性あり
3. 環境光 + 平行光源、グリッドを配置
4. `ResizeObserver` でコンテナのサイズ変化に追従（`resize()` でレンダラーとカメラのアスペクト比を更新）
5. `setAnimationLoop` で毎フレーム `controls.update()` と描画
6. pointerdown / pointerup のイベントを登録

`onBeforeUnmount` ではループ停止・監視解除・モデル破棄・レンダラー破棄を行います。

### web-ifc の初期化（getIfcApi）

```js
ifcApi = new IfcAPI()
ifcApi.SetWasmPath('/', true)
await ifcApi.Init()
```

`/web-ifc.wasm` を読み込んで初期化します。初期化は重いので、最初の 1 回だけ行いインスタンスを使い回します。

### 読み込み（load）

1. `fetch(url)` で IFC を取得し `Uint8Array` に
2. `buildIfcGroup()` で Three.js の `Group` に変換
3. 既存モデルを `clearModel()` で破棄してから新しい Group をシーンに追加
4. `fitCamera()` でモデル全体が収まるようカメラを移動
5. `loaded` を emit。失敗時は `error` を emit

`watch(() => props.fileUrl, ...)` により、`fileUrl` が変わるたびに自動で読み込み直します。

### カメラ合わせ（fitCamera）

モデルのバウンディングボックスから対角長 `size` と中心 `center` を求め、

- 注視点を `center` に
- カメラを斜め上 `(1, 0.8, 1)` 方向、距離 `size × 1.2` に配置
- `near = size / 1000`、`far = size × 20` として、モデルの大きさに関係なくクリッピングされにくくする

### クリック選択

**ドラッグとクリックの区別**: pointerdown の位置を記録し、pointerup で移動距離が 4px 未満かつ左ボタンのときだけ「クリック」とみなします（視点操作のドラッグで誤選択しないため）。

**ピック（pick）**:

1. マウス座標を正規化デバイス座標（-1〜1）に変換
2. `Raycaster` でカメラからレイを飛ばし、`modelGroup.children` と交差判定
3. 最も手前のヒットの `userData.expressID` を取得
4. `highlight()` で色替えし、`select` を emit

**ハイライト（highlight）**:

1 つの部材が複数の Mesh で構成される場合があるため、**同じ expressID を持つ Mesh をすべて** オレンジ（`#ff7a1a`）に差し替えます。
元のマテリアルは `userData.originalMaterial` に退避し、次の選択時に戻します。

## src/lib/ifcLoader.ts — IFC → Three.js 変換

### buildIfcGroup(ifcApi, data)

1. `ifcApi.OpenModel(data)` でモデルを開く
2. `StreamAllMeshes` で部材ごとの `flatMesh` を順に受け取る
3. 各 `flatMesh.geometries`（配置済みジオメトリの配列）について
   - `toBufferGeometry()` で `BufferGeometry` を作成
   - 色から `MeshLambertMaterial` を取得（同じ色はキャッシュして共有）
   - `flatTransformation`（4×4 行列）を `applyMatrix4` で適用し、IFC 内の位置・回転を反映
   - **`mesh.userData.expressID = flatMesh.expressID`** を設定（クリック選択のキー）
4. 最後に必ず `CloseModel` で web-ifc 側のモデルを閉じる（`try/finally`）

### toBufferGeometry

web-ifc の頂点データは 1 頂点 6 要素 `[x, y, z, nx, ny, nz]` が並んだ配列なので、
位置（position）と法線（normal）の 2 つの `Float32Array` に分けて `BufferGeometry` に設定します。
インデックスは `slice()` でコピーしてから設定し、`g.delete()` で WebAssembly 側のメモリを解放します（コピーしないと解放後に参照が壊れるため）。

### getMaterial

色 `(x, y, z, w)` = RGBA をキーにマテリアルをキャッシュします。
`w < 1` なら半透明（窓ガラス等）として `transparent` / `opacity` を設定。`side: DoubleSide` で裏面も描画します。

## src/lib/ifcLabels.ts — 日本語ラベル

画面に出す英語名を日本語に置き換える対応表です。どの関数も、表に無い名前は英語のまま返します。

| 関数 | 対象 | 例 |
|---|---|---|
| `classLabel(ifcClass)` | IFC クラス名 | `IfcWall → 壁` |
| `psetLabel(psetName)` | プロパティセット名 | `Pset_WallCommon → 壁の共通プロパティ` |
| `propLabel(propName)` | プロパティ名 | `IsExternal → 外部に面する` |

属性パネルでは、プロパティセットの見出しに日本語名と元の英語名（小さい文字）を並べて表示します。プロパティ名は日本語で表示し、マウスを乗せると元の英語名がツールチップで出ます。

## 注意点・今後の改善候補

- **マテリアルの破棄漏れ**: `clearModel()` はジオメトリのみ `dispose()` しており、マテリアルは破棄していません。モデルを何度も読み替えると GPU メモリが少しずつ残ります。
- **読み込みの競合**: 読み込み中に別ファイルを選ぶと、2 つの `load` が並行し、後から終わった方が表示されます。
- **大規模モデル**: 1 部材 1〜複数 Mesh のため、大きな IFC では描画コールが多くなります。ジオメトリのマージやインスタンシングで改善できます。
- **二重の解析**: 同じ IFC をサーバー（ifcopenshell）とブラウザ（web-ifc）の両方で解析しています。パイロットとしては単純で分かりやすい構成ですが、大きなファイルでは待ち時間が増えます。
