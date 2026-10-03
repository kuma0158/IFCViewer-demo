# フロントエンド解説（TypeScript + Three.js + web-ifc／フレームワーク無し）

`frontend/` は、IFC ファイルをサーバーにアップロードし、ブラウザ上で 3D 表示して、クリックした部材の属性を表示する画面です。
Step 5 で Vue を撤去し、画面は **純粋な TypeScript（DOM API）** で組み立てています。Vite は開発サーバー・バンドラーとしてのみ使います。

## 全体像

```
frontend/
├─ index.html                    エントリ HTML（#app に画面を組み立てる）
├─ vite.config.ts                Vite 設定（/api を FastAPI へプロキシ）
├─ tsconfig.json                 TypeScript 設定（strict）
├─ package.json                  依存関係・npm スクリプト
├─ scripts/copy-wasm.mjs         web-ifc.wasm を public/ にコピー（npm install 時）
├─ public/web-ifc.wasm           web-ifc 本体（WebAssembly）
└─ src/
   ├─ main.ts                    起動（CSS 読み込み・mountApp）
   ├─ app.ts                     画面全体（状態・アップロード・ステータス・属性パネルの描画）
   ├─ style.css                  画面全体のスタイル
   ├─ api.ts                     バックエンド API の呼び出し
   ├─ types.ts                   API レスポンスの型定義
   ├─ viewer/IfcViewer.ts        3D ビューア（クラス。表示・視点操作・クリック選択・ハイライト）
   └─ lib/
      ├─ dom.ts                  DOM 生成ヘルパー（el / append / replaceChildren）
      ├─ ifcLoader.ts            web-ifc の出力 → Three.js の Mesh 変換
      └─ ifcLabels.ts            IFC クラス名などの日本語ラベル
```

## 動作環境

Node.js `^20.19.0 || >=22.12.0`（Vite 8 の要件）。`package.json` の `engines` にも記載しており、合わない Node.js で `npm install` すると警告が出ます。

## 使用ライブラリ

| ライブラリ | 用途 |
|---|---|
| three | WebGL による 3D 描画 |
| web-ifc | IFC をブラウザ内で解析し、三角形メッシュを出力する WebAssembly ライブラリ |
| vite | 開発サーバー・ビルド（TypeScript をそのまま扱える） |
| typescript 5.9 | 型チェック（`tsc --noEmit`） |
| @types/three | three の型定義（web-ifc は型定義を同梱） |

## TypeScript のポイント

- **設定**: `tsconfig.json` で `strict: true`。`npm run build` は `tsc --noEmit`（型チェック）が通ってから `vite build` を実行します。型チェックだけなら `npm run typecheck`。
- **バージョン**: TypeScript は動作確認済みの `~5.9.3` に固定しています（Step 4 では vue-tsc 対応のための固定でした。Vue 撤去により TypeScript 7 への更新も検討可能）。
- **API の型（src/types.ts）**: `ModelSummary`（アップロード結果）、`ElementDetail`（部材の属性）などを、`backend/ifc_service.py` の戻り値に合わせて定義しています。バックエンドのキー名を変えたら、ここも合わせて変えます。
- **未選択・対象外の表現**: `app.ts` の `state.element` は `ElementDetail | NotFoundElement | null` の型です。`renderSide()` で `'notFound' in element` により絞り込むので、それ以降は `ElementDetail` として扱えます。
- **three の型**: `modelGroup.children` は `Object3D[]` 型ですが、中身は `ifcLoader.ts` で作った `Mesh` だけなので、`modelMeshes()` で `Mesh[]` として扱っています。

## 処理の流れ

```
[app.ts] ファイル選択（change イベント）
   │  uploadModel(file)  ── 分割アップロード（/api/uploads）──▶ FastAPI（裏で解析・modelId 発行）
   │  ◀── modelId・集計結果
   │  viewer.load(`/api/models/{modelId}/file`)
   ▼
[viewer/IfcViewer.ts] load(url)
   │  fetch(url) → Uint8Array
   │  buildIfcGroup(ifcApi, data)   ← lib/ifcLoader.ts
   │  scene に追加・カメラをフィット
   │  onLoaded({ meshCount })
   ▼
部材クリック → Raycaster で Mesh 特定 → userData.expressID
   │  ハイライト + onSelect(expressID)
   ▼
[app.ts] fetchElement(modelId, expressID) ── GET /api/models/{id}/elements/{expressID}
   ◀── 属性情報 → renderSide() で右パネルに表示
```

サーバー側（ifcopenshell）で集計・属性取得、ブラウザ側（web-ifc）で 3D 形状生成、と役割分担しています。
両者は IFC 内の番号 `#123`（**expressID**）が共通なので、これを使ってクリックした 3D 形状と属性データを結び付けます。

## 設定・起動まわり

### vite.config.ts

```js
const proxy = { '/api': 'http://127.0.0.1:8001' }
server:  { port: 5173, strictPort: true, allowedHosts, proxy },  // 開発: npm run dev
preview: { port: 5173, strictPort: true, allowedHosts, proxy },  // 本番: npm run build → npm run serve
```

`/api/...` へのリクエストを FastAPI に転送します。フロントのコードは相対パス `/api/...` で書けるため、CORS やホスト名を意識せずに済みます。
開発サーバー（`server`）と本番配信（`preview`）で **同じポート・同じ転送設定** にしているので、Cloudflare Tunnel の転送先（5173）を変えずにモードを切り替えられます。
Vue プラグインは不要になったので、`plugins` は指定していません。

### 開発モードと本番モード

| | 開発（`npm run dev`） | 本番（`npm run build` → `npm run serve`。Vite 標準名の `npm run preview` でも同じ） |
|---|---|---|
| 配信するもの | `src/` の TypeScript をその場で変換 | `dist/`（型チェック済み・圧縮済みのファイル） |
| ソースの公開 | `/src/...` が読める | 読めない（`dist/` だけを配信） |
| 変更の反映 | 保存すると即時 | 再ビルドが必要 |
| 常駐起動 | `start-servers.ps1 -Dev` | `start-servers.ps1`（既定） |

本番配信には `vite preview` を使っています。Vite の公式には「手元での確認用」とされていますが、
このシステムは 1 台の PC で少人数が使うパイロットであり、トンネルの転送先を変えずに済み、`/api` の転送もそのまま使えるため採用しました。
利用者が増える場合は、FastAPI の `StaticFiles` で `dist/` を配信する（画面と API を 1 つのポートにまとめる）か、静的ホスティングへの移行を検討します。

### scripts/copy-wasm.mjs

`npm install` の `postinstall` で実行され、`node_modules/web-ifc/web-ifc.wasm` を `public/` にコピーします。
`public/` のファイルはサイトのルート（`/web-ifc.wasm`）で配信されるので、web-ifc がそこから読み込めるようになります。

### main.ts / index.html

`style.css` を読み込み、`mountApp(document.getElementById('app')!)` で画面を組み立てるだけです。

## src/api.ts — API 呼び出し

| 関数 | 内容 |
|---|---|
| `uploadModel(file, onProgress)` | **分割アップロード**: `POST /api/uploads` → 16MB ずつ `PUT …/chunks/{i}` → `POST …/complete` → 1 秒ごとに `GET /api/uploads/{id}` で解析完了を待つ → `GET /api/models/{modelId}`。進み具合を `onProgress` で通知（送信中 n% / 解析中）。通信断や 5xx は 1 チャンクにつき 3 回までやり直す |
| `fetchElement(modelId, expressId)` | `GET /api/models/{modelId}/elements/{expressId}` |
| `modelFileUrl(modelId)` | IFC 本体の URL 文字列を返す（fetch はビューア側で行う） |

共通の `request()` で fetch と JSON の読み取りを行い、失敗時は **`ApiError`（HTTP ステータス付き）** を投げます。

- メッセージは FastAPI の `detail`（無ければ `通信エラー (ステータス)`）。
- サーバーに接続できないときは `status: 0` と「サーバーに接続できませんでした…」。
- ステータスが分かるので、呼び出し側で「部材が無い 404（対象外）」とそれ以外のエラーを区別できます。モデルが消えた 404 は、detail が `types.ts` の `MODEL_NOT_FOUND_DETAIL` と一致するかで見分けます。

## src/lib/dom.ts — DOM 生成ヘルパー

| 関数 | 内容 |
|---|---|
| `el(tag, options, ...children)` | 要素を作る。`options` は `class` / `title` / `attrs`。子は Node か文字列 |
| `append(parent, ...children)` | 子を追加。`null` / `undefined` / `false` は無視（条件付き表示を `cond && el(...)` で書ける） |
| `replaceChildren(parent, ...children)` | 中身を差し替える（再描画用） |

**文字列は必ず textContent（テキストノード）として入れ、innerHTML は使いません。**
部材名やプロパティ値は IFC の作成者が自由に書ける値なので、HTML として解釈させると XSS の原因になるためです。

## src/app.ts — 画面全体

### 状態（state）

Vue の `ref` の代わりに、1 つのオブジェクト `state` に状態をまとめます。変更したら対応する `render*()` を呼んで DOM に反映します（自動追跡はしない）。

| 変数 | 内容 |
|---|---|
| `model` | `POST /api/models` のレスポンス（modelId・集計結果） |
| `element` | 選択中の部材の属性（未選択は `null`） |
| `status` | ヘッダーに出すメッセージ |
| `error` | エラーメッセージ（赤帯で表示。空なら `hidden`） |
| `uploading` | アップロード中フラグ（ボタンを無効化） |

### 構成

- **骨組み**: `mountApp()` の最初に header / エラー帯 / main（`.viewer-pane` と `.side`）を一度だけ作り、`new IfcViewer(viewerPane, { onLoaded, onSelect, onError })` でビューアを差し込みます。
- **`onFileChange()`**: `uploadModel`（進み具合をステータスに「送信中… 45%（54.0 / 120.0 MB）」「サーバーで解析中…」と表示。失敗したら前のモデルのステータスに戻す）→ 成功したら `viewer.load(modelFileUrl(...))`。最後に `fileInput.value = ''` として、同じファイルを再選択しても `change` が発火するようにしています。
- **`onSelect(expressId)`**: `null`（何もない所をクリック）なら選択解除。それ以外は属性を取得。
  - 部材の 404（`IfcSpace` など）は `{ notFound: true }` として「対象外」と表示。
  - モデルの 404（サーバー再起動などで消えた）は「もう一度IFCファイルを開いてください」、通信失敗などはそのメッセージを赤帯に出し、ハイライトも外す。
  - 呼び出しごとに番号（`selectSeq`）を振り、応答が届いた時点で最新の選択でなければ捨てる。素早く A→B とクリックしても、B のハイライトに A の属性が出ることはない。アップロード開始時にも番号を進め、前のモデルへの応答を無視する。
- **`onError`（ビューアからの通知）**: 3D 表示に失敗したら、ステータスを「3D表示に失敗しました」にし、モデル・選択を空に戻す（ビューア側も表示中のモデルを消している）。
- **`renderHeader()`**: ボタンの文言・無効化、ステータス、エラー帯を更新（既存要素の中身だけ書き換える）。
- **`renderSide()`**: 属性パネルを丸ごと作り直す。基本情報（種類・名前・階・GlobalId）を `<dl>` で、プロパティセットごとに見出し＋`<table>` で表示（`elementDetail()` / `psetBlock()`）。
- **`formatValue(v)`**: 真偽値を「はい／いいえ」、空値を「—」、オブジェクトを JSON 文字列に変換。
- 幅 760px 以下では縦並び（ビューア上・パネル下）になるレスポンシブ対応（`style.css`）。

## src/viewer/IfcViewer.ts — 3D ビューア

### インターフェース

```ts
const viewer = new IfcViewer(container, {
  onLoaded: ({ meshCount }) => { ... },  // 読み込み完了
  onSelect: (expressID) => { ... },      // クリックされた部材（空クリックは null）
  onError: (message) => { ... },         // エラーメッセージ
})
await viewer.load(url)       // IFC を読み込んで表示
viewer.highlight(expressID)  // 任意の部材をハイライト（null で解除）
viewer.dispose()             // 取り外し（GPU リソース・監視・イベントを解放）
```

API（`api.ts`）は知りません。URL を受け取って表示し、結果をコールバックで返すだけです。

### 初期化（constructor）

1. コンテナ内に `.viewer` 要素（読み込み中オーバーレイ付き）を作り、`WebGLRenderer` の canvas を追加
2. `Scene`（背景色 `#eef1f5`）、`PerspectiveCamera`、`OrbitControls`（`enableDamping` で慣性あり）
3. 環境光 + 平行光源、グリッドを配置
4. `ResizeObserver` でサイズ変化に追従（`resize()` でレンダラーとカメラのアスペクト比を更新）
5. `setAnimationLoop` で毎フレーム `controls.update()` と描画
6. pointerdown / pointerup を登録（`removeEventListener` できるよう、アロー関数のプロパティとして定義）

`dispose()` ではループ停止・監視解除・イベント解除・モデル破棄・レンダラー破棄を行います。読み込み中のものがあれば、完了しても反映しません。

### web-ifc の初期化（getIfcApi）

`new IfcAPI()` → `SetWasmPath('/', true)` → `Init()` で `/web-ifc.wasm` を読み込みます。初期化は重いので、最初の 1 回だけ行いインスタンスを使い回します。
初期化中の **Promise ごと** 保持するので、初期化が終わる前に `load` が 2 回呼ばれても初期化は 1 回だけです。失敗したら保持を解除し、次の `load` でやり直します。

### 読み込み（load）

1. オーバーレイを表示し、`fetch(url)` で IFC を取得して `Uint8Array` に
2. `buildIfcGroup()` で Three.js の `Group` に変換
3. 既存モデルを `clearModel()` で破棄してから新しい Group をシーンに追加
4. `fitCamera()` でモデル全体が収まるようカメラを移動
5. `onLoaded` を呼ぶ。失敗時は表示中のモデルも消してから `onError`（画面のモデルとアップロードしたモデルが食い違わないように）

`load` のたびに番号（`loadSeq`）を振り、完了時に最新でなければ結果もエラーも捨てます。読み込み中に別のファイルを選んでも、最後に選んだものだけが表示されます。

`clearModel()` はハイライトを戻したうえで、ジオメトリと、Mesh 間で共有しているマテリアルを重複なく集めて `dispose()` します。

### カメラ合わせ（fitCamera）

モデルのバウンディングボックスから対角長 `size` と中心 `center` を求め、注視点を `center` に、カメラを斜め上 `(1, 0.8, 1)` 方向・距離 `size × 1.2` に配置。`near = size / 1000`、`far = size × 20` としてクリッピングされにくくします。

### クリック選択

**ドラッグとクリックの区別**: pointerdown の位置を記録し、pointerup で移動距離が 4px 未満かつ左ボタンのときだけ「クリック」とみなします（視点操作のドラッグで誤選択しないため）。

**ピック（pick）**: マウス座標を正規化デバイス座標に変換 → `Raycaster` で `modelGroup.children` と交差判定 → 最も手前のヒットの `userData.expressID` を取得 → `highlight()` して `onSelect` を呼ぶ。

**ハイライト（highlight）**: 1 つの部材が複数の Mesh で構成される場合があるため、**同じ expressID を持つ Mesh をすべて** オレンジ（`#ff7a1a`）に差し替えます。元のマテリアルは `userData.originalMaterial` に退避し、次の選択時に戻します。

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

> 2026-10-03 のコードレビュー結果（F-1〜F-7）は [review-2026-10-03.md](review-2026-10-03.md#フロントエンド) を参照。

- **読み込み中の別ファイル**: 最後に選んだファイルだけを表示します（`load` の番号で古い結果を捨てる）。ただし古い方の変換処理そのものは止められず、終わるまで CPU を使います。
- **本番配信は `vite preview`**: 少人数のパイロットとしては十分だが、本格運用なら専用の配信方法に移す（上記「開発モードと本番モード」参照）。
- **バンドルが大きい**: three と web-ifc で約 4MB（gzip 約 0.5MB）。`IfcViewer` を `import()` で遅延読み込みにすると初回表示が速くなる。
- **大規模モデル**: 1 部材 1〜複数 Mesh のため、大きな IFC では描画コールが多くなります。ジオメトリのマージやインスタンシングで改善できます。
- **二重の解析**: 同じ IFC をサーバー（ifcopenshell）とブラウザ（web-ifc）の両方で解析しています。パイロットとしては単純で分かりやすい構成ですが、大きなファイルでは待ち時間が増えます。
