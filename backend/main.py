"""
IFC解析API（パイロット Step 2）

エンドポイント
  POST /api/models                              IFCをアップロード → 集計結果を返す（1 リクエストで送る。小さいファイル向け）
  GET  /api/models/{model_id}                   集計結果を再取得
  GET  /api/models/{model_id}/elements/{id}     部材1件の属性情報
  GET  /api/models/{model_id}/file              元のIFCファイル（3D表示用）

  分割アップロード（大きなファイル向け。Cloudflare の 1 リクエスト 100MB 制限と 100 秒の応答待ち制限を避ける）
  POST /api/uploads                             セッション作成 {filename, size} → {uploadId, chunkSize, totalChunks}
  PUT  /api/uploads/{upload_id}/chunks/{index}  チャンクを送る（本文はファイルの一部そのもの）
  POST /api/uploads/{upload_id}/complete        受信完了 → 裏で解析を始める（すぐ 202 を返す）
  GET  /api/uploads/{upload_id}                 進み具合 {status: uploading|processing|done|error, modelId?, detail?}

起動:
  uvicorn main:app --host 127.0.0.1 --port 8001 --reload
  → http://127.0.0.1:8001/docs で動作確認できる
"""
import threading
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path as FsPath
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Path, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import ifc_service
from upload_sessions import UploadSessionError, UploadSessions

UPLOAD_DIR = FsPath(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_SIZE_MB = 500
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
# メモリに保持するモデルの上限（件数と、元ファイルの合計サイズ）。
# ifcopenshell のモデルは元ファイルより大きなメモリを使うため、件数だけでなく合計サイズでも抑える。
# どちらかを超えたら、最後に使われたのが最も古いものから捨てる（直前に登録した 1 件は必ず残す）
MAX_MODELS = 20
MAX_TOTAL_MB = 1000
MAX_TOTAL_BYTES = MAX_TOTAL_MB * 1024 * 1024
# 1 リクエストで受け取る書き込み単位（POST /api/models）
WRITE_BUFFER = 1024 * 1024
# 分割アップロードの 1 チャンクの大きさ（Cloudflare の 100MB 制限より十分小さくする）
UPLOAD_CHUNK_SIZE = 16 * 1024 * 1024
# 同時に走らせる解析の数（大きな IFC の解析はメモリと CPU を多く使うため）
MAX_PARALLEL_ANALYSES = 2

# frontend/src/types.ts の MODEL_NOT_FOUND_DETAIL と同じ文言にする
# （フロントは「部材が無い 404」と「モデルが無い 404」をこの文言で区別する）
MODEL_NOT_FOUND_DETAIL = "モデルが見つかりません"


def _remove_file(path: FsPath) -> None:
    # Windows では配信中のファイルを消せない（PermissionError）ことがあるので、失敗しても止めない
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # パイロット版なので、読み込んだモデルはメモリに保持する（再起動で消える）。
    # 再起動するとファイルとモデルの対応が失われるため、起動時に前回のファイルを削除して揃える。
    # （import 時に消すと、`python -c "import main"` の確認だけで稼働中サーバーのファイルが消えるため起動時に行う）
    for pattern in ("*.ifc", "*.part"):
        for old in UPLOAD_DIR.glob(pattern):
            _remove_file(old)
    yield


app = FastAPI(title="IFC Pilot API", lifespan=lifespan)

# フロントエンドの開発サーバー（Vite: 5173番）からの呼び出しを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# model_id → {"model", "summary", "path", "filename", "size", "lock"}
# 並び順 = 最後に使われた順（古い順）。_models_lock で守る
_models: OrderedDict[str, dict] = OrderedDict()
_models_lock = threading.Lock()

_uploads = UploadSessions(UPLOAD_DIR, MAX_SIZE_BYTES, UPLOAD_CHUNK_SIZE)
_analysis_slots = threading.Semaphore(MAX_PARALLEL_ANALYSES)

# expressID は IFC ファイル内の #番号。ifcopenshell は C++ の int で受けるため、範囲外は 422 で弾く
ExpressId = Annotated[int, Path(ge=1, le=2**31 - 1)]
ChunkIndex = Annotated[int, Path(ge=0, le=100_000)]

_UPLOAD_ERROR_STATUS = {"not_found": 404, "too_large": 413, "bad_request": 400, "conflict": 409}


def _upload_http_error(e: UploadSessionError) -> HTTPException:
    return HTTPException(status_code=_UPLOAD_ERROR_STATUS[e.kind], detail=e.message)


class AnalyzeError(Exception):
    """IFC を開けない・集計できない（利用者向けの日本語メッセージを持つ）"""


def _get(model_id: str) -> dict:
    with _models_lock:
        entry = _models.get(model_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=MODEL_NOT_FOUND_DETAIL)
        _models.move_to_end(model_id)
        return entry


def _register(model_id: str, entry: dict) -> None:
    with _models_lock:
        _models[model_id] = entry
        evicted = []
        total = sum(e.get("size", 0) for e in _models.values())
        while len(_models) > 1 and (len(_models) > MAX_MODELS or total > MAX_TOTAL_BYTES):
            old = _models.popitem(last=False)[1]
            total -= old.get("size", 0)
            evicted.append(old)
    for old in evicted:
        _remove_file(old["path"])


def _analyze_and_register(model_id: str, path: FsPath, filename: str) -> dict:
    """保存済みの IFC を開いて集計し、保持する。失敗したらファイルを消して AnalyzeError"""
    with _analysis_slots:
        try:
            model = ifc_service.open_model(str(path))
        except Exception as e:  # 壊れたファイル・IFC以外のファイル等
            detail = ifc_service.describe_open_error(str(path), e)
            _remove_file(path)
            raise AnalyzeError(detail) from e
        try:
            summary = ifc_service.summarize(model)
        except Exception as e:  # 読み込めたが中身の構造がおかしい等
            _remove_file(path)
            raise AnalyzeError(f"IFCを解析できませんでした: {e}") from e

    _register(
        model_id,
        {
            "model": model,
            "summary": summary,
            "path": path,
            "filename": filename,
            "size": path.stat().st_size,
            # ifcopenshell はスレッドセーフを保証していないので、同じモデルへのアクセスは1つずつにする
            "lock": threading.Lock(),
        },
    )
    return summary


def _save_upload(file: UploadFile, path: FsPath) -> None:
    """アップロードを書き込みながらサイズを数え、上限を超えたらその場で打ち切る"""
    size = 0
    with path.open("wb") as f:
        while chunk := file.file.read(WRITE_BUFFER):
            size += len(chunk)
            if size > MAX_SIZE_BYTES:
                break
            f.write(chunk)
    if size > MAX_SIZE_BYTES:
        _remove_file(path)
        raise HTTPException(status_code=413, detail=f"{MAX_SIZE_MB}MB以下のファイルにしてください")


# async def にすると、同期処理（ファイル書き込み・ifcopenshell の解析）が
# イベントループを止めて他のリクエストまで待たせる。def にしてスレッドプールで実行させる
@app.post("/api/models")
def upload_model(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".ifc"):
        raise HTTPException(status_code=400, detail=".ifc ファイルを指定してください")

    model_id = uuid.uuid4().hex
    path = UPLOAD_DIR / f"{model_id}.ifc"
    _save_upload(file, path)
    try:
        summary = _analyze_and_register(model_id, path, file.filename)
    except AnalyzeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"modelId": model_id, "filename": file.filename, **summary}


@app.get("/api/models/{model_id}")
def get_summary(model_id: str):
    entry = _get(model_id)
    return {"modelId": model_id, "filename": entry["filename"], **entry["summary"]}


@app.get("/api/models/{model_id}/elements/{express_id}")
def get_element(model_id: str, express_id: ExpressId):
    entry = _get(model_id)
    with entry["lock"]:
        detail = ifc_service.element_detail(entry["model"], express_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="部材が見つかりません")
    return detail


@app.get("/api/models/{model_id}/file")
def get_file(model_id: str):
    entry = _get(model_id)
    if not entry["path"].exists():
        raise HTTPException(status_code=404, detail=MODEL_NOT_FOUND_DETAIL)
    return FileResponse(entry["path"], media_type="application/octet-stream", filename=entry["filename"])


# ---- 分割アップロード ----


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0)


@app.post("/api/uploads", status_code=201)
def create_upload(body: UploadCreate):
    try:
        session = _uploads.create(body.filename, body.size)
    except UploadSessionError as e:
        raise _upload_http_error(e)
    return {
        "uploadId": session.id,
        "chunkSize": session.chunk_size,
        "totalChunks": session.total_chunks,
    }


# 本文（チャンク）を読む必要があるので async def。書き込みはスレッドプールに回してイベントループを止めない
@app.put("/api/uploads/{upload_id}/chunks/{index}")
async def put_chunk(upload_id: str, index: ChunkIndex, request: Request):
    # 想定より大きな本文は読み切る前に打ち切る（メモリを守るため）
    data = bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data) > UPLOAD_CHUNK_SIZE:
            raise HTTPException(status_code=413, detail=f"1 チャンクは {UPLOAD_CHUNK_SIZE} バイト以下にしてください")
    try:
        session = await run_in_threadpool(_uploads.write_chunk, upload_id, index, bytes(data))
    except UploadSessionError as e:
        raise _upload_http_error(e)
    return session.to_status()


def _process_upload(upload_id: str) -> None:
    """裏のスレッドで実行: 組み立て済みファイルを解析して登録し、結果をセッションに記録する"""
    session = _uploads.get(upload_id)
    model_id = upload_id
    path = UPLOAD_DIR / f"{model_id}.ifc"
    try:
        session.path.replace(path)
        _analyze_and_register(model_id, path, session.filename)
    except AnalyzeError as e:
        _uploads.fail(upload_id, str(e))
        return
    except Exception as e:  # 想定外の失敗も「解析中」のまま放置しない
        _remove_file(path)
        _remove_file(session.path)
        _uploads.fail(upload_id, f"IFCを解析できませんでした: {e}")
        return
    _uploads.finish(upload_id, model_id)


@app.post("/api/uploads/{upload_id}/complete", status_code=202)
def complete_upload(upload_id: str):
    # 解析は時間がかかる（Cloudflare は 100 秒で応答待ちを打ち切る）ので、裏で走らせてすぐ返す
    try:
        session = _uploads.start_processing(upload_id)
    except UploadSessionError as e:
        raise _upload_http_error(e)
    threading.Thread(target=_process_upload, args=(upload_id,), daemon=True).start()
    return session.to_status()


@app.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str):
    try:
        return _uploads.get(upload_id).to_status()
    except UploadSessionError as e:
        raise _upload_http_error(e)
