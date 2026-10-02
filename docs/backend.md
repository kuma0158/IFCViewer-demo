# バックエンド解説（FastAPI + ifcopenshell）

`backend/` は、アップロードされた IFC ファイルを **ifcopenshell** で解析し、集計結果と部材ごとの属性情報を JSON で返す API サーバーです。

## 全体像

```
backend/
├─ main.py            HTTP の窓口（エンドポイント・CORS・アップロード処理・モデル保持）
├─ ifc_service.py     IFC の解析ロジック（集計・部材詳細）
├─ requirements.txt   依存パッケージ
└─ uploads/           アップロードされた IFC の保存先（<modelId>.ifc）
```

役割を 2 ファイルに分けているのがポイントです。

- `main.py` … HTTP に関すること（リクエストの検証、ステータスコード、ファイル保存）だけを扱う
- `ifc_service.py` … IFC に関すること（ifcopenshell の呼び出し）だけを扱う

こうしておくと、`ifc_service.py` の関数を CLI（Step 1 の `analyze_ifc.py` のような用途）やテストからそのまま使い回せます。

## 依存パッケージ（requirements.txt）

| パッケージ | 用途 |
|---|---|
| fastapi | Web API フレームワーク |
| uvicorn[standard] | ASGI サーバー（`uvicorn main:app --host 127.0.0.1 --port 8001 --reload` で起動） |
| python-multipart | `multipart/form-data`（ファイルアップロード）の受信に必要 |
| ifcopenshell | IFC ファイルの読み込み・解析 |

## main.py

### 初期設定

```python
UPLOAD_DIR = FsPath(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_SIZE_MB = 100
MAX_MODELS = 20
MODEL_NOT_FOUND_DETAIL = "モデルが見つかりません"
```

- アップロード先は `main.py` と同じ階層の `uploads/`。無ければ作成します。
- 受け付けるファイルサイズの上限は 100MB。書き込み中に数え、超えた時点で打ち切ります。
- メモリに保持するモデルは最大 20 件。
- `MODEL_NOT_FOUND_DETAIL` は `frontend/src/types.ts` と同じ文言。フロントは「部材が無い 404（対象外）」と「モデルが無い 404（再起動などで消えた）」をこの文言で区別します。
- FastAPI の `lifespan` で、**起動時に `uploads/*.ifc` を削除** します（再起動でモデルが消える仕様と揃えるため。import 時ではなく起動時に行うので、`python -c "import main"` で確認しても稼働中サーバーのファイルは消えません）。

### CORS

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    ...
)
```

Vite 開発サーバー（5173 番ポート）からのブラウザ直接アクセスを許可しています。
なお、実際にはフロントエンドは Vite のプロキシ経由（`/api` → `127.0.0.1:8001`）で呼び出すため同一オリジン扱いとなり、CORS は保険的な設定です。

### モデルの保持

```python
_models: OrderedDict[str, dict] = OrderedDict()
_models_lock = threading.Lock()
```

解析済みモデルを **プロセスのメモリ上の辞書** に保持します。キーは `modelId`（UUID の hex 文字列）、値は次の内容です。
並び順は「最後に使われた順」で、`_get()` で使うたびに末尾へ移動し、`_register()` で 20 件を超えたら先頭（最も使われていないもの）からファイルごと捨てます。

| キー | 内容 |
|---|---|
| model | `ifcopenshell.file`（解析済みの IFC オブジェクト） |
| summary | `ifc_service.summarize()` の結果 |
| path | 保存した IFC ファイルのパス |
| filename | アップロード時の元ファイル名 |
| lock | モデルごとの `threading.Lock`。ifcopenshell はスレッドセーフを保証していないので、同じモデルへの属性取得を 1 つずつにする |

パイロット用の簡易実装のため、サーバーを再起動すると消えます（`uploads/` のファイルも起動時に削除します）。

`_get(model_id)` は辞書から取り出し、無ければ 404（`MODEL_NOT_FOUND_DETAIL`）を返す共通ヘルパーです。
ファイル削除は `_remove_file()` 経由で行い、Windows で配信中のファイルが消せない場合（`PermissionError`）でも処理を止めません。

### エンドポイント

#### `POST /api/models` — アップロード・解析

`async def` ではなく **`def`** で定義しています。ファイル書き込みと ifcopenshell の解析は同期処理なので、
`async def` の中で行うとイベントループが止まり、解析中は他の利用者のリクエストまで待たされるためです（`def` なら FastAPI がスレッドプールで実行します）。

処理の流れ:

1. 拡張子が `.ifc` でなければ **400**
2. `uuid4().hex` で `modelId` を発行し、`_save_upload()` で `uploads/<modelId>.ifc` に 1MB ずつ書き込む
3. 書き込み中に累計が 100MB を超えたら、その時点で打ち切ってファイルを削除し **413**
4. `ifc_service.open_model()` で読み込み。失敗したら `describe_open_error()` で原因別の日本語メッセージを作り、ファイルを削除して **422**
5. `summarize()` で集計。例外が出たらファイルを削除して **422**
6. `_register()` で `_models` に登録し（上限を超えたら古いものを破棄）、`{"modelId", "filename", ...summary}` を返す

レスポンス例:

```json
{
  "modelId": "96779cd09de7444f80dad7cf7593d209",
  "filename": "demo-house.ifc",
  "schema": "IFC4",
  "project": "Demo House",
  "elementCount": 12,
  "classCounts": { "IfcWall": 8, "IfcSlab": 2, ... },
  "storeys": [ { "name": "1F", "total": 6, "classCounts": { ... } }, ... ],
  "elements": [ { "expressId": 123, "globalId": "...", "ifcClass": "IfcWall", "name": "...", "storey": "1F" }, ... ]
}
```

#### `GET /api/models/{model_id}` — 集計結果の再取得

アップロード時と同じ形のレスポンスを、保持している `summary` から返します。

#### `GET /api/models/{model_id}/elements/{express_id}` — 部材 1 件の属性

`ifc_service.element_detail()` の結果を返します。該当なし（存在しない ID、または `IfcElement` ではないもの）は **404**。
`express_id` は `int` 型で宣言しているので、数値以外が来ると FastAPI が自動で 422 を返します。

#### `GET /api/models/{model_id}/file` — 元の IFC ファイル

保存した IFC を `FileResponse` でそのまま返します。フロントエンドはこれを取得して web-ifc で 3D 化します。

## ifc_service.py

### `open_model(path)`

`ifcopenshell.open(path)` を呼ぶだけの薄いラッパーです。

### `describe_open_error(path, error)`

`open_model()` が失敗したときだけ呼ばれ、ファイルの先頭 1024 バイトを見て原因別の日本語メッセージを返します。

| 先頭の内容 | メッセージの趣旨 |
|---|---|
| 空 | ファイルが空 |
| `PK\x03\x04` | ZIP（IFC-ZIP）は未対応。解凍して選ぶ |
| UTF-16 の BOM | 文字コードが UTF-16。保存し直す |
| `<!DOCTYPE html` / `<html` | Web ページを保存している。ダウンロードし直す |
| その他の `<` | XML（ifcXML）は未対応 |
| `ISO-10303-21;` 以外 | IFC（テキスト形式）ではない |
| エラー文に `header` を含む | ヘッダーが規格に沿っていない |
| 上記以外 | 壊れている可能性（元のエラー文を併記） |

先に ifcopenshell で開き、失敗したときだけこの判定を行う順番にしています。こうすると、ifcopenshell が読めるファイルをこのチェックで誤って弾くことがありません。

### `_storey_name(el)`

```python
container = element_util.get_container(el)
return container.Name if container and container.Name else "(所属なし)"
```

部材が属する空間構造（通常は `IfcBuildingStorey` = 階）を `get_container` で取得し、その名前を返します。所属が無い場合は `"(所属なし)"`。

### `summarize(model)`

モデル全体の集計を作ります。

- `model.by_type("IfcElement")` で **物理的な部材（壁・床・ドア等）をすべて** 取得
  （`IfcElement` のサブクラスもまとめて取れる）
- `by_storey`: `defaultdict(Counter)` で「階 → {IFC クラス: 個数}」を集計
- `element_rows`: 部材ごとに `expressId / globalId / ifcClass / name / storey` を 1 行ずつ作成
- `classCounts`: 種類別の個数を多い順（`most_common()`）で返す

返り値:

| キー | 内容 |
|---|---|
| schema | IFC スキーマ（`IFC2X3` / `IFC4` など） |
| project | `IfcProject` の名前（無ければ `null`） |
| elementCount | 部材の総数 |
| classCounts | 種類ごとの個数 |
| storeys | 階ごとの合計と種類別内訳 |
| elements | 部材一覧 |

### `element_detail(model, express_id)`

1 つの部材の詳細を返します。

1. `model.by_id(express_id)` で取得。存在しない ID（`RuntimeError`）や C++ の int に収まらない ID（`OverflowError`）は `None` を返す
   （API 側でもパスパラメータを `1〜2147483647` に制限しており、範囲外は 422 になる）
2. `IfcElement` でなければ `None`（例: `IfcSpace` や `IfcSite` など、形状はあっても部材ではないもの）
3. `element_util.get_psets(el)` でプロパティセット（Pset / 数量セット）を辞書で取得
4. ifcopenshell が各セットに付与する内部用の `"id"` キーを除去
5. 基本情報 + `propertySets` を返す

```json
{
  "expressId": 123,
  "globalId": "2O2Fr$t4X7Zf8NOew3FLOH",
  "ifcClass": "IfcWall",
  "name": "外壁-01",
  "storey": "1F",
  "propertySets": {
    "Pset_WallCommon": { "IsExternal": true, "LoadBearing": false }
  }
}
```

## 設計上のキー：expressId

`expressId` は IFC ファイル内の行番号 `#123` のことです。
サーバー側の ifcopenshell（`el.id()`）とブラウザ側の web-ifc（`flatMesh.expressID`）で **同じ番号** になるため、
「3D 画面でクリックした部材 → この API で属性を取得」という連携のキーとして使っています。

## 注意点・今後の改善候補

> 2026-10-03 のコードレビュー結果（B-1〜B-7）は [review-2026-10-03.md](review-2026-10-03.md#バックエンド) を参照。

- **永続化なし**: モデルはメモリ保持のみ（最大 20 件）。本番では DB やキャッシュ（Redis 等）、オブジェクトストレージへの置き換えが必要です。
- **件数でしか上限を設けていない**: 20 件でも、大きな IFC ばかりならメモリを多く使います。必要ならサイズの合計や有効期限での破棄を加えます。
- **解析はリクエストの中で行う**: スレッドプールで実行するので他のリクエストは止まりませんが、アップロードした本人は解析が終わるまで待ちます。巨大なファイルを扱うならバックグラウンドジョブ化が考えられます。
- **認証なし**: `modelId` を知っていれば誰でもアクセスできます。公開する場合は Cloudflare Access などで利用者を絞ってください。
