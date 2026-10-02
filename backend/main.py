"""
IFC解析API（パイロット Step 2）

エンドポイント
  POST /api/models                              IFCをアップロード → 集計結果を返す
  GET  /api/models/{model_id}                   集計結果を再取得
  GET  /api/models/{model_id}/elements/{id}     部材1件の属性情報
  GET  /api/models/{model_id}/file              元のIFCファイル（3D表示用）

起動:
  uvicorn main:app --reload
  → http://127.0.0.1:8000/docs で動作確認できる
"""
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import ifc_service

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_SIZE_MB = 100

app = FastAPI(title="IFC Pilot API")

# Step 3 の Vue 開発サーバー（Vite: 5173番）からの呼び出しを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# パイロット版なので、読み込んだモデルはメモリに保持する（再起動で消える）
_models: dict[str, dict] = {}


def _get(model_id: str) -> dict:
    entry = _models.get(model_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="モデルが見つかりません")
    return entry


@app.post("/api/models")
async def upload_model(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".ifc"):
        raise HTTPException(status_code=400, detail=".ifc ファイルを指定してください")

    model_id = uuid.uuid4().hex
    path = UPLOAD_DIR / f"{model_id}.ifc"
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    if path.stat().st_size > MAX_SIZE_MB * 1024 * 1024:
        path.unlink()
        raise HTTPException(status_code=413, detail=f"{MAX_SIZE_MB}MB以下のファイルにしてください")

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

    _models[model_id] = {"model": model, "summary": summary, "path": path, "filename": file.filename}
    return {"modelId": model_id, "filename": file.filename, **summary}


@app.get("/api/models/{model_id}")
def get_summary(model_id: str):
    entry = _get(model_id)
    return {"modelId": model_id, "filename": entry["filename"], **entry["summary"]}


@app.get("/api/models/{model_id}/elements/{express_id}")
def get_element(model_id: str, express_id: int):
    entry = _get(model_id)
    detail = ifc_service.element_detail(entry["model"], express_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="部材が見つかりません")
    return detail


@app.get("/api/models/{model_id}/file")
def get_file(model_id: str):
    entry = _get(model_id)
    return FileResponse(entry["path"], media_type="application/octet-stream", filename=entry["filename"])
