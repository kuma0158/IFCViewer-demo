# IFC Pilot — Step 2: FastAPI バックエンド

## セットアップ（Windows）

```
cd ifc-pilot\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

ブラウザで http://127.0.0.1:8001/docs（8000 は別プロジェクトが使用しているため 8001） を開くと、Swagger UI から各APIを試せます。

## API

| メソッド | パス | 内容 |
|---|---|---|
| POST | /api/models | IFCをアップロードし、集計結果と部材一覧を返す |
| GET | /api/models/{modelId} | 集計結果を再取得 |
| GET | /api/models/{modelId}/elements/{expressId} | 部材1件の属性情報（プロパティセット） |
| GET | /api/models/{modelId}/file | 元のIFCファイル（Step 3 の3D表示で使用） |
| POST | /api/uploads | 分割アップロードの開始 `{filename, size}` → `{uploadId, chunkSize, totalChunks}` |
| PUT | /api/uploads/{uploadId}/chunks/{index} | チャンク（ファイルの一部）を送る。同じ番号の再送は上書き |
| POST | /api/uploads/{uploadId}/complete | 受信完了 → 裏で解析開始（すぐ 202） |
| GET | /api/uploads/{uploadId} | 進み具合 `{status: uploading/processing/done/error, modelId?, detail?}` |

画面は分割アップロードを使います（Cloudflare 経由では 1 リクエスト 100MB まで・応答待ち 100 秒までの制限があるため）。
`POST /api/models` は 1 リクエストで送る簡易版で、Swagger UI や小さなファイルの確認用に残しています。

## 試し方（Swagger UI）

1. `POST /api/models` → Try it out → IFCファイルを選んで Execute
2. レスポンスの `modelId` と、`elements` の中の `expressId` を1つ控える
3. `GET /api/models/{modelId}/elements/{expressId}` に入れて Execute → 属性情報が返る

## 設計メモ

- **expressId** はIFCファイル内の `#123` の番号。ブラウザ側の 3D ライブラリ（web-ifc）でも同じ番号が使われるので、Step 3 で「クリックした部材 → このAPIで属性取得」とつなげるキーになります。
- 解析済みモデルはメモリ上に保持しています（パイロット用。サーバー再起動で消えます）。本番ならDBやキャッシュに置き換えるところです。
- IFC処理は `ifc_service.py`、HTTPの処理は `main.py` に分けています。
- 受け付けるファイルは最大 500MB（`MAX_SIZE_MB`）。分割アップロードの 1 チャンクは 16MB。
- メモリに保持するモデルは最大 20 件（`MAX_MODELS`）かつ元ファイルの合計 1000MB（`MAX_TOTAL_MB`）。超えると最後に使われたのが最も古いものから、ファイルごと捨てます（直前に登録した 1 件は残す）。
- 解析は同時に 2 件まで（`MAX_PARALLEL_ANALYSES`）。
- 起動時に `uploads/` の前回のファイルを削除します（再起動でモデルが消える仕様と揃えるため）。

## テスト

```
cd ifc-pilot\backend
venv\Scripts\python.exe -m unittest discover -s tests -v
```

追加の依存は不要です（標準の unittest）。`samples/demo-house.ifc` を使って `ifc_service.py` と `main.py` の補助関数を確認します。
