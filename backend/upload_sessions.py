"""
分割アップロード（チャンク）の受付状態を管理する

Cloudflare 経由では 1 リクエストの本文が 100MB までに制限されるため、
大きな IFC はブラウザ側で一定サイズ（CHUNK_SIZE）に分けて送り、ここで 1 つのファイルに組み立てる。

  create()        セッション作成（ファイル名・合計サイズを受け取り、受け皿のファイルを用意）
  write_chunk()   i 番目のチャンクを所定の位置に書き込む（同じ番号の再送は上書き = やり直し可能）
  start_processing()  全チャンクが揃ったか確認して「解析中」にする
  finish() / fail()   解析の結果を記録する

HTTP（FastAPI）は知らない。エラーは UploadSessionError（kind で種類を表す）で返し、
ステータスコードへの変換は main.py が行う。
"""
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


class UploadSessionError(Exception):
    """kind: "not_found" | "too_large" | "bad_request" | "conflict" """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class UploadSession:
    id: str
    filename: str
    size: int
    chunk_size: int
    path: Path  # 受信中のファイル（<id>.part）
    received: set[int] = field(default_factory=set)
    status: str = "uploading"  # uploading → processing → done / error
    model_id: str | None = None
    detail: str | None = None
    updated: float = field(default_factory=time.monotonic)

    @property
    def total_chunks(self) -> int:
        return -(-self.size // self.chunk_size)  # 切り上げ

    def expected_length(self, index: int) -> int:
        """index 番目のチャンクのバイト数（最後だけ端数）"""
        return min(self.chunk_size, self.size - index * self.chunk_size)

    def to_status(self) -> dict:
        status = {
            "uploadId": self.id,
            "status": self.status,
            "receivedChunks": len(self.received),
            "totalChunks": self.total_chunks,
        }
        if self.model_id:
            status["modelId"] = self.model_id
        if self.detail:
            status["detail"] = self.detail
        return status


class UploadSessions:
    def __init__(self, directory: Path, max_size: int, chunk_size: int, ttl_seconds: float = 3600):
        self.directory = directory
        self.max_size = max_size
        self.chunk_size = chunk_size
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, UploadSession] = {}
        self._lock = threading.Lock()

    def create(self, filename: str, size: int) -> UploadSession:
        if not filename.lower().endswith(".ifc"):
            raise UploadSessionError("bad_request", ".ifc ファイルを指定してください")
        if size < 0:
            raise UploadSessionError("bad_request", "ファイルサイズが不正です")
        if size > self.max_size:
            raise UploadSessionError(
                "too_large", f"{self.max_size // (1024 * 1024)}MB以下のファイルにしてください"
            )
        self.cleanup_expired()
        session_id = uuid.uuid4().hex
        session = UploadSession(
            id=session_id,
            filename=filename,
            size=size,
            chunk_size=self.chunk_size,
            path=self.directory / f"{session_id}.part",
        )
        session.path.write_bytes(b"")  # 受け皿。チャンクは位置を指定して書き込む
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> UploadSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise UploadSessionError(
                "not_found", "アップロードが見つかりません（期限切れの可能性があります）。もう一度ファイルを開いてください。"
            )
        return session

    def write_chunk(self, session_id: str, index: int, data: bytes) -> UploadSession:
        session = self.get(session_id)
        if session.status != "uploading":
            raise UploadSessionError("conflict", "このアップロードは既に受付を終えています")
        if not 0 <= index < session.total_chunks:
            raise UploadSessionError("bad_request", f"チャンク番号が範囲外です（0〜{session.total_chunks - 1}）")
        if len(data) != session.expected_length(index):
            raise UploadSessionError(
                "bad_request",
                f"チャンク {index} の大きさが違います（期待 {session.expected_length(index)} バイト、受信 {len(data)} バイト）",
            )
        # 同じセッションの別チャンクが同時に届いても、ファイルごとに別ハンドルで位置指定して書くので壊れない
        with session.path.open("r+b") as f:
            f.seek(index * session.chunk_size)
            f.write(data)
        with self._lock:
            session.received.add(index)
            session.updated = time.monotonic()
        return session

    def start_processing(self, session_id: str) -> UploadSession:
        session = self.get(session_id)
        with self._lock:
            if session.status != "uploading":
                raise UploadSessionError("conflict", "このアップロードは既に受付を終えています")
            missing = session.total_chunks - len(session.received)
            if missing:
                raise UploadSessionError("conflict", f"まだ届いていないチャンクがあります（残り {missing} 個）")
            session.status = "processing"
            session.updated = time.monotonic()
        return session

    def finish(self, session_id: str, model_id: str) -> None:
        session = self.get(session_id)
        with self._lock:
            session.status = "done"
            session.model_id = model_id
            session.updated = time.monotonic()

    def fail(self, session_id: str, detail: str) -> None:
        session = self.get(session_id)
        with self._lock:
            session.status = "error"
            session.detail = detail
            session.updated = time.monotonic()

    def cleanup_expired(self) -> None:
        """しばらく動きのないセッションを捨てる（途中で閉じられたアップロードのファイルも消す）。解析中のものは残す"""
        now = time.monotonic()
        with self._lock:
            expired = [
                s for s in self._sessions.values()
                if s.status != "processing" and now - s.updated > self.ttl_seconds
            ]
            for s in expired:
                del self._sessions[s.id]
        for s in expired:
            if s.status == "uploading":
                try:
                    s.path.unlink(missing_ok=True)
                except OSError:
                    pass
