# IFC Pilot — Step 2: FastAPI バックエンド

## セットアップ（Windows）

```
cd ifc-pilot\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

ブラウザで http://127.0.0.1:8000/docs を開くと、Swagger UI から各APIを試せます。

## API

| メソッド | パス | 内容 |
|---|---|---|
| POST | /api/models | IFCをアップロードし、集計結果と部材一覧を返す |
| GET | /api/models/{modelId} | 集計結果を再取得 |
| GET | /api/models/{modelId}/elements/{expressId} | 部材1件の属性情報（プロパティセット） |
| GET | /api/models/{modelId}/file | 元のIFCファイル（Step 3 の3D表示で使用） |

## 試し方（Swagger UI）

1. `POST /api/models` → Try it out → IFCファイルを選んで Execute
2. レスポンスの `modelId` と、`elements` の中の `expressId` を1つ控える
3. `GET /api/models/{modelId}/elements/{expressId}` に入れて Execute → 属性情報が返る

## 設計メモ

- **expressId** はIFCファイル内の `#123` の番号。ブラウザ側の 3D ライブラリ（web-ifc）でも同じ番号が使われるので、Step 3 で「クリックした部材 → このAPIで属性取得」とつなげるキーになります。
- 解析済みモデルはメモリ上に保持しています（パイロット用。サーバー再起動で消えます）。本番ならDBやキャッシュに置き換えるところです。
- IFC処理は `ifc_service.py`、HTTPの処理は `main.py` に分けています。
