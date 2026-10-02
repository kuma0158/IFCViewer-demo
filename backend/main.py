"""
IFC解析API（パイロット Step 2）

エンドポイント
  POST /api/models                              IFCをアップロード → 集計結果を返す
  GET  /api/models/{model_id}                   集計結果を再取得
  GET  /api/models/{model_id}/elements/{id}     部材1件の属性情報
  GET  /api/models/{model_id}/file              元のIFCファイル（3D表示用）

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

from fastapi import FastAPI, File, HTTPException, Path, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import ifc_service

UPLOAD_DIR = FsPath(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_SIZE_MB = 100
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
# メモリに保持するモデルの上限。超えたら最後に使われたのが最も古いものから捨てる
MAX_MODELS = 20
CHUNK_SIZE = 1024 * 1024

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
    for old in UPLOAD_DIR.glob("*.ifc"):
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

# model_id → {"model", "summary", "path", "filename", "lock"}
# 並び順 = 最後に使われた順（古い順）。_models_lock で守る
_models: OrderedDict[str, dict] = OrderedDict()
_models_lock = threading.Lock()

# expressID は IFC ファイル内の #番号。ifcopenshell は C++ の int で受けるため、範囲外は 422 で弾く
ExpressId = Annotated[int, Path(ge=1, le=2**31 - 1)]


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
        while len(_models) > MAX_MODELS:
            evicted.append(_models.popitem(last=False)[1])
    for old in evicted:
        _remove_file(old["path"])


def _save_upload(file: UploadFile, path: FsPath) -> None:
    """アップロードを書き込みながらサイズを数え、上限を超えたらその場で打ち切る"""
    size = 0
    with path.open("wb") as f:
        while chunk := file.file.read(CHUNK_SIZE):
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
        model = ifc_service.open_model(str(path))
    except Exception as e:  # 壊れたファイル・IFC以外のファイル等
        detail = ifc_service.describe_open_error(str(path), e)
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=detail)

    try:
        summary = ifc_service.summarize(model)
    except Exception as e:  # 読み込めたが中身の構造がおかしい等
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"IFCを解析できませんでした: {e}")

    _register(
        model_id,
        {
            "model": model,
            "summary": summary,
            "path": path,
            "filename": file.filename,
            # ifcopenshell はスレッドセーフを保証していないので、同じモデルへのアクセスは1つずつにする
            "lock": threading.Lock(),
        },
    )
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
