# IFC Viewer Pilot

IFC（BIMの国際標準データ形式）をアップロードすると、3Dで表示し、
クリックした部材の属性情報を表示するパイロットアプリです。

## 概要

### 何ができるか

- ブラウザから IFC ファイル（最大 500MB）を開くと、建物が **3D で表示** される
- 部材（壁・床・柱・ドアなど）を **クリックすると、その属性**（種類・名前・階・GlobalId・プロパティセット）が右側に表示される
- 部材の種類やプロパティ名は **日本語で表示**（`IfcWall` → 壁、`IsExternal` → 外部に面する）し、元の英語名も併記する
- 開けないファイル（ZIP・HTML を保存したもの・壊れた IFC など）は、**原因と対処方法を日本語で** 案内する

### 位置づけ

本番システムではなく、「IFC を開いて、3D で見て、部材をクリックすると属性が分かる」ことを最小構成で確かめる **パイロット（技術検証）** です。
1 台の Windows PC で動かし、Cloudflare Tunnel 経由で公開しています（https://ifc.shinobuabe.com ）。

### 構成

```
[ブラウザ]  TypeScript（フレームワーク無し）+ Three.js + web-ifc（WebAssembly）
    │  http://localhost:5173（本番ビルドを配信 / /api はバックエンドへ転送）
    ▼
[バックエンド]  Python + FastAPI + ifcopenshell   http://127.0.0.1:8001
```

| 役割 | 担当 | 使っている技術 |
|---|---|---|
| 3D 形状の生成と表示・クリック判定 | ブラウザ | web-ifc（IFC → 三角形メッシュ）、Three.js（描画） |
| 集計・部材の属性（プロパティセット）取得 | サーバー | ifcopenshell |
| 画面（アップロード・属性パネル） | ブラウザ | TypeScript と DOM API のみ |

```
ifc-pilot/
├─ analyze_ifc.py      Step 1: IFC解析スクリプト（コマンドライン）
├─ backend/            Step 2: FastAPI（IFC解析API / ifcopenshell）
├─ frontend/           Step 5: TypeScript（フレームワーク無し）+ Three.js（3D表示 / web-ifc）
├─ scripts/            常駐起動スクリプト・E2E テスト
├─ docs/               設計・解説・レビュー・テスト記録
└─ samples/demo-house.ifc  動作確認用の小さなIFC（2階建て・壁8枚）
```

システムは段階的に作られています: Step 1（CLI で解析できるか）→ Step 2（Web API にできるか）→ Step 3〜4（Vue で 3D 表示と属性を結べるか）→ **Step 5（Vue を撤去し、純粋な TypeScript に）**。

## 設計思想

詳しくは [docs/design-philosophy.md](docs/design-philosophy.md)（全体）・[docs/design-backend.md](docs/design-backend.md)・[docs/design-frontend.md](docs/design-frontend.md)。ここでは要点だけをまとめます。

### 1. expressID を共通のキーにする（最も重要な判断）

IFC ファイル内の番号 `#123`（expressID）は、サーバーの ifcopenshell でもブラウザの web-ifc でも **同じ値** になります。
ブラウザは 3D の各部品にこの番号を記録しておき、クリックされたらその番号でサーバーに属性を問い合わせるだけです。
**独自の ID 対応表を一切作らずに、形状（ブラウザ）と属性（サーバー）を結び付けられる** ことが、この構成の土台です。

### 2. 得意なものに得意なことをさせる

- 属性・空間構造の扱いが成熟している **ifcopenshell（サーバー）** が集計と属性を担当
- 重い形状処理は **web-ifc（ブラウザ）** が担当し、サーバーから大量のメッシュを送らずに済ませる

同じ IFC を両側で 1 回ずつ解析することになりますが、それぞれのライブラリを標準的な使い方のまま使える単純さを優先しています。

### 3. 関心を分ける（層の分離）

| 層 | 知っていること | 知らないこと |
|---|---|---|
| `backend/main.py` | HTTP（URL・入力チェック・ステータスコード・保存・保持） | ifcopenshell の詳細 |
| `backend/ifc_service.py` | IFC の読み方（集計・属性） | HTTP（「無い」は `None` で返す） |
| `frontend/src/app.ts` | 画面の状態・API・ビューアの使い方 | 3D の詳細 |
| `frontend/src/viewer/IfcViewer.ts` | 3D の表示・操作・選択 | API（URL を受け取り、クリックを通知するだけ） |
| `frontend/src/lib/ifcLoader.ts` | web-ifc → Three.js の変換 | 画面（DOM） |

片方を差し替えても、もう片方を変えずに済むようにしています（例: 属性の取り方を変えてもビューアは変えない）。

### 4. 必要以上の道具を持たない

画面は小さい（ヘッダー・エラー帯・属性パネル）ため、Step 5 で Vue を撤去し、**フレームワーク無しの TypeScript** にしました。
複雑さの中心は Three.js / web-ifc 側にあり、フレームワークの恩恵が小さかったためです。依存は three / web-ifc の 2 つだけ、バックエンドも DB・キャッシュ・ジョブキュー無しで動きます。

### 5. 型と契約で前後をそろえる

`frontend/src/types.ts` は `backend/ifc_service.py` の戻り値と 1 対 1 の **API の契約書** です（キーは camelCase）。
TypeScript は `strict`、`npm run build` は型チェックが通らなければビルドしません。状態も型で表します（選択中の部材 = 未選択／対象外／属性あり）。

### 6. 利用者に寄り添う

- エラーは **原因 ＋ 対処方法** を日本語で（例: 「中身がWebページ（HTML）になっています。…元のIFCファイルをダウンロードし直してください」）
- 日本語ラベルは辞書に無ければ英語のまま（表示が欠けない）
- ドラッグ（視点操作）とクリック（選択）を 4px の移動量で区別
- 部屋など「部材ではないもの」はエラーではなく「対象外です」という正常な状態として表示
- 大きなファイルは進み具合を表示（送信中 n% → サーバーで解析中）

### 7. 割り切りを隠さない

パイロットとして **意図的にやっていないこと** を明記し、本番化するときの差し替え先を残しています。

| 割り切り | 現状 |
|---|---|
| 永続化 | モデルはメモリだけに保持（最大 20 件・合計 1000MB）。再起動で消える |
| 認証 | 無し。公開する場合は Cloudflare Access などで利用者を絞る |
| 配信 | `vite preview` で本番ビルドを配信（少人数のパイロット向け） |
| 大規模モデル | 1 部材 1〜複数メッシュのまま（マージ・インスタンシングはしていない） |

### 8. 実際の公開経路に合わせる

Cloudflare 経由では **1 リクエスト 100MB まで・応答待ち約 100 秒まで** の制限があります。
そのため画面からのアップロードは **16MB ずつの分割アップロード** にし、解析はサーバーの裏で行って進み具合を問い合わせる形にしています。

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
[ブラウザ]                                          [FastAPI]
 ① IFCを選択
    POST /api/uploads ──────────────────────────────▶ 受付開始（uploadId）
    PUT  /api/uploads/{id}/chunks/{i} × n（16MBずつ）─▶ 1 つのファイルに組み立て
    POST /api/uploads/{id}/complete ────────────────▶ 裏で ifcopenshell が解析・保持
    GET  /api/uploads/{id}（1秒ごと）◀── 進み具合 / 完了したら modelId
    GET  /api/models/{modelId}       ◀── 集計結果
 ② GET /api/models/{modelId}/file でIFC取得
    → web-ifc（WebAssembly）で三角形メッシュに変換
    → Three.jsで表示（各メッシュに expressID を記録）
 ③ 部材クリック → expressID
    GET /api/models/{modelId}/elements/{expressID} ──▶ プロパティセット取得
                                    ◀── 属性情報 ──
```

`POST /api/models`（1 リクエストで送る簡易版）も残しており、Swagger UI（http://127.0.0.1:8001/docs ）や小さなファイルの確認に使えます。

## 主なファイル

設計・解説・レビュー記録は `docs/` にあります（`design-philosophy.md` / `design-backend.md` / `design-frontend.md` / `backend.md` / `frontend.md` / `review-2026-10-03.md` / `e2e-2026-10-03.md`）。

| ファイル | 内容 |
|---|---|
| backend/main.py | APIエンドポイント（一括・分割アップロード、集計、属性、ファイル） |
| backend/ifc_service.py | IFC解析（集計・部材の属性取得・開けない原因の判定） |
| backend/upload_sessions.py | 分割アップロードの受付と組み立て |
| frontend/src/app.ts | 画面全体（アップロード・属性パネル）の状態と DOM 描画 |
| frontend/src/api.ts | バックエンドの呼び出し（分割アップロード・やり直し・進み具合） |
| frontend/src/types.ts | APIレスポンスの型（backend/ifc_service.py の戻り値と対応） |
| frontend/src/viewer/IfcViewer.ts | 3D表示・視点操作・クリック選択・ハイライト（クラス） |
| frontend/src/lib/ifcLoader.ts | web-ifc の出力を Three.js のメッシュに変換 |
| frontend/src/lib/ifcLabels.ts | IFCクラス名・プロパティ名の日本語ラベル |
| frontend/src/lib/dom.ts | DOM 生成ヘルパー（textContent のみ使用・innerHTML 不使用） |
| frontend/src/style.css | 画面全体のスタイル |
| scripts/start-servers.ps1 | バックエンドとフロントエンドの常駐起動（本番 / `-Dev`） |
| scripts/e2e_api.py | 稼働中のシステムに対する E2E テスト |

## 型チェック（フロントエンド）

```
cd ifc-pilot\frontend
npm run typecheck   型チェックのみ
npm run build       型チェック → 本番ビルド（型エラーがあればビルドしない）
```

`npm run dev` は型チェックをしないので、エディタ（VS Code）の表示か `npm run typecheck` で確認します。

## テスト

```
cd ifc-pilot\backend
venv\Scripts\python.exe -m unittest discover -s tests -v       バックエンドの単体テスト（15 件）
```

### E2E テスト（稼働中のシステムに対して）

```
cd ifc-pilot
backend\venv\Scripts\python.exe scripts\e2e_api.py
```

フロントエンド（:5173）の `/api` 転送を通して、配信・アップロード（一括・分割・120MB）・属性取得・エラー処理を確認します（標準ライブラリのみ）。
公開ホスト名に対しては `--base https://ifc.shinobuabe.com --skip-heavy`。画面の確認手順と結果は `docs/e2e-2026-10-03.md`。

## 確認済みバージョン

ifcopenshell 0.9.0 / FastAPI 0.142 / Python 3.14 / three 0.186 / web-ifc 0.0.78 / Vite 8 / TypeScript 5.9 / Node.js 24

Step 5 で Vue を撤去し、フロントエンドはフレームワーク無しの TypeScript になりました。
TypeScript は動作確認済みの `~5.9.3` に固定しています（vue-tsc が不要になったため、TypeScript 7 への更新も検討可能）。
