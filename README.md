# IFC Viewer Pilot

IFC（BIMの国際標準データ形式）をアップロードすると、3Dで表示し、
クリックした部材の属性情報を表示するパイロットアプリです。

```
ifc-pilot/
├─ analyze_ifc.py      Step 1: IFC解析スクリプト（コマンドライン）
├─ backend/            Step 2: FastAPI（IFC解析API / ifcopenshell）
├─ frontend/           Step 5: TypeScript（フレームワーク無し）+ Three.js（3D表示 / web-ifc）
└─ samples/demo-house.ifc  動作確認用の小さなIFC（2階建て・壁8枚）
```

## 起動方法（Windows・ターミナルを2つ使います）

**ターミナル1：バックエンド**

```
cd ifc-pilot\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

**ターミナル2：フロントエンド**（Node.js 20.19 以上、または 22.12 以上。Vite 8 の要件）

```
cd ifc-pilot\frontend
npm install
npm run dev
```

ブラウザで http://localhost:5173 を開き、「IFCファイルを開く」から
`samples/demo-house.ifc` またはダウンロードしたサンプルIFCを選びます。

- 左ドラッグ：回転 / 右ドラッグ：平行移動 / ホイール：ズーム
- 部材をクリック：オレンジでハイライトされ、右側に属性情報を表示

### 本番モードで常駐させる（Cloudflare Tunnel 経由で公開する場合）

```
powershell -File ifc-pilot\scripts\start-servers.ps1
```

バックエンド（:8001）を起動し、フロントエンドは `npm run build` でビルドしてから `dist/` を `vite preview`（:5173）で配信します。
ソースコードは配信されず、圧縮済みのファイルだけが公開されます。トンネルの転送先は開発時と同じ 5173 番のままです。

- コードを変更したら、5173 番のプロセスを止めてからもう一度スクリプトを実行する（再ビルドされる）。
- 開発サーバーで常駐させるときは `-Dev` を付ける。モードを切り替えるときも、先に 5173 番のプロセスを止める。
- ビルドのログは `logs/frontend.build.log`。型エラーなどでビルドに失敗した場合、前回の `dist/` があればそれで起動する。
- 認証は無いので、公開する場合は Cloudflare Access などで利用者を絞ってください。

## 仕組み

```
[ブラウザ]                                   [FastAPI]
 ① IFCを選択 ──── POST /api/models ────────▶ ifcopenshellで解析・保持
                 ◀─── modelId・集計結果 ────
 ② GET /api/models/{id}/file でIFC取得
    → web-ifc（WebAssembly）で三角形メッシュに変換
    → Three.jsで表示（各メッシュに expressID を記録）
 ③ 部材クリック → expressID
    ──── GET /api/models/{id}/elements/{expressID} ──▶ プロパティセット取得
                 ◀─── 属性情報 ────
```

**ポイント：** IFCファイル内の番号（`#123` = expressID）は、サーバー側の
ifcopenshell とブラウザ側の web-ifc で共通です。これを両者をつなぐキーにしています。

## 主なファイル

設計・解説・レビュー記録は `docs/` にあります（`design-philosophy.md` / `design-backend.md` / `design-frontend.md` / `backend.md` / `frontend.md` / `review-2026-10-03.md` / `e2e-2026-10-03.md`）。

| ファイル | 内容 |
|---|---|
| backend/ifc_service.py | IFC解析（集計・部材の属性取得） |
| backend/main.py | APIエンドポイント |
| frontend/src/lib/ifcLoader.ts | web-ifc の出力を Three.js のメッシュに変換 |
| frontend/src/viewer/IfcViewer.ts | 3D表示・視点操作・クリック選択・ハイライト（クラス） |
| frontend/src/app.ts | 画面全体（アップロード・属性パネル）の状態と DOM 描画 |
| frontend/src/lib/dom.ts | DOM 生成ヘルパー（textContent のみ使用・innerHTML 不使用） |
| frontend/src/style.css | 画面全体のスタイル |
| frontend/src/lib/ifcLabels.ts | IFCクラス名・プロパティ名の日本語ラベル |
| frontend/src/types.ts | APIレスポンスの型（backend/ifc_service.py の戻り値と対応） |

## 型チェック（フロントエンド）

```
cd ifc-pilot\frontend
npm run typecheck   型チェックのみ
npm run build       型チェック → 本番ビルド（型エラーがあればビルドしない）
```

`npm run dev` は型チェックをしないので、エディタ（VS Code）の表示か `npm run typecheck` で確認します。

## E2E テスト（稼働中のシステムに対して）

```
cd ifc-pilot
backend\venv\Scripts\python.exe scripts\e2e_api.py
```

フロントエンド（:5173）の `/api` 転送を通して、配信・アップロード・属性取得・エラー処理を確認します（標準ライブラリのみ）。
公開ホスト名に対しては `--base https://ifc.shinobuabe.com --skip-heavy`。画面の確認手順と結果は `docs/e2e-2026-10-03.md`。

## 確認済みバージョン

ifcopenshell 0.9.0 / FastAPI / three 0.186 / web-ifc 0.0.78 / Vite 8 / TypeScript 5.9

Step 5 で Vue を撤去し、フロントエンドはフレームワーク無しの TypeScript になりました。
TypeScript は動作確認済みの `~5.9.3` に固定しています（vue-tsc が不要になったため、TypeScript 7 への更新も検討可能）。
