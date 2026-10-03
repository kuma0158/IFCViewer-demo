"""
バックエンドの回帰テスト（追加の依存なし。標準の unittest で動く）

実行:
  cd ifc-pilot\\backend
  venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import io
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi import HTTPException, UploadFile  # noqa: E402

import ifc_service  # noqa: E402
import main  # noqa: E402
from upload_sessions import UploadSessionError, UploadSessions  # noqa: E402

SAMPLE = BACKEND_DIR.parent / "samples" / "demo-house.ifc"


class IfcServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ifc_service.open_model(str(SAMPLE))

    def test_summarize(self):
        s = ifc_service.summarize(self.model)
        self.assertEqual(s["schema"], "IFC4")
        self.assertEqual(s["project"], "Demo House")
        self.assertEqual(s["elementCount"], 8)
        self.assertEqual(s["classCounts"], {"IfcWall": 8})
        self.assertEqual({st["name"]: st["total"] for st in s["storeys"]}, {"1F": 4, "2F": 4})
        # 部材一覧のキーは frontend/src/types.ts の ElementRow と一致させる
        self.assertEqual(set(s["elements"][0]), {"expressId", "globalId", "ifcClass", "name", "storey"})

    def test_element_detail(self):
        express_id = self.model.by_type("IfcWall")[0].id()
        d = ifc_service.element_detail(self.model, express_id)
        self.assertIsNotNone(d)
        self.assertEqual(d["expressId"], express_id)
        self.assertEqual(d["ifcClass"], "IfcWall")
        # ifcopenshell の内部キー "id" はレスポンスから除く
        for props in d["propertySets"].values():
            self.assertNotIn("id", props)

    def test_element_detail_not_element(self):
        # IfcProject は IfcElement ではないので対象外
        project_id = self.model.by_type("IfcProject")[0].id()
        self.assertIsNone(ifc_service.element_detail(self.model, project_id))

    def test_element_detail_missing_or_out_of_range(self):
        self.assertIsNone(ifc_service.element_detail(self.model, 99999))
        # C++ の int に収まらない番号でも例外にせず None（以前は OverflowError で 500 になっていた）
        self.assertIsNone(ifc_service.element_detail(self.model, 99999999999))

    def test_describe_open_error(self):
        cases = {
            b"": "空",
            b"PK\x03\x04rest": "ZIP",
            b"\xff\xfeI\x00S\x00O\x00": "UTF-16",
            b"<!DOCTYPE html><html>": "HTML",
            b"<?xml version='1.0'?>": "XML",
            b"hello": "ISO-10303-21",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for head, expected in cases.items():
                path = Path(tmp) / "x.ifc"
                path.write_bytes(head)
                msg = ifc_service.describe_open_error(str(path), RuntimeError("x"))
                self.assertIn(expected, msg, head)


class UploadHelperTest(unittest.TestCase):
    def test_save_upload_within_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.ifc"
            main._save_upload(UploadFile(io.BytesIO(b"x" * 10), filename="a.ifc"), path)
            self.assertEqual(path.stat().st_size, 10)

    def test_save_upload_over_limit_is_aborted(self):
        original = main.MAX_SIZE_BYTES
        main.MAX_SIZE_BYTES = 100
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "a.ifc"
                with self.assertRaises(HTTPException) as cm:
                    main._save_upload(UploadFile(io.BytesIO(b"x" * 1000), filename="a.ifc"), path)
                self.assertEqual(cm.exception.status_code, 413)
                self.assertFalse(path.exists())
        finally:
            main.MAX_SIZE_BYTES = original


class ModelRegistryTest(unittest.TestCase):
    def setUp(self):
        self.saved = main._models.copy()
        main._models.clear()

    def tearDown(self):
        main._models.clear()
        main._models.update(self.saved)

    def test_evicts_least_recently_used_and_deletes_file(self):
        original = main.MAX_MODELS
        main.MAX_MODELS = 2
        try:
            with tempfile.TemporaryDirectory() as tmp:
                paths = {}
                for name in ("a", "b"):
                    paths[name] = Path(tmp) / f"{name}.ifc"
                    paths[name].write_bytes(b"x")
                    main._register(name, {"path": paths[name]})
                main._get("a")  # a を最近使ったことにする → 次に捨てられるのは b
                paths["c"] = Path(tmp) / "c.ifc"
                paths["c"].write_bytes(b"x")
                main._register("c", {"path": paths["c"]})

                self.assertEqual(list(main._models), ["a", "c"])
                self.assertFalse(paths["b"].exists())
                with self.assertRaises(HTTPException) as cm:
                    main._get("b")
                self.assertEqual(cm.exception.status_code, 404)
                self.assertEqual(cm.exception.detail, main.MODEL_NOT_FOUND_DETAIL)
        finally:
            main.MAX_MODELS = original


    def test_evicts_by_total_size_but_keeps_newest(self):
        original = main.MAX_TOTAL_BYTES
        main.MAX_TOTAL_BYTES = 100
        try:
            with tempfile.TemporaryDirectory() as tmp:
                for name, size in (("a", 60), ("b", 60)):
                    path = Path(tmp) / f"{name}.ifc"
                    path.write_bytes(b"x")
                    main._register(name, {"path": path, "size": size})
                # 合計 120 > 100 なので古い a が捨てられる
                self.assertEqual(list(main._models), ["b"])
                # 1 件で上限を超えていても、直前に登録したものは残す
                big = Path(tmp) / "big.ifc"
                big.write_bytes(b"x")
                main._register("big", {"path": big, "size": 500})
                self.assertEqual(list(main._models), ["big"])
        finally:
            main.MAX_TOTAL_BYTES = original


class UploadSessionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.sessions = UploadSessions(self.dir, max_size=1000, chunk_size=10)

    def tearDown(self):
        self.tmp.cleanup()

    def test_assembles_chunks_in_any_order_and_accepts_resend(self):
        data = bytes(range(25))
        s = self.sessions.create("a.ifc", len(data))
        self.assertEqual(s.total_chunks, 3)
        for i in (2, 0, 1, 1):  # 順不同・同じチャンクの再送も可
            self.sessions.write_chunk(s.id, i, data[i * 10 : i * 10 + 10])
        self.sessions.start_processing(s.id)
        self.assertEqual(s.path.read_bytes(), data)
        self.assertEqual(s.status, "processing")

    def test_rejects_invalid_requests(self):
        cases = [
            (lambda: self.sessions.create("a.txt", 10), "bad_request"),
            (lambda: self.sessions.create("a.ifc", 1001), "too_large"),
            (lambda: self.sessions.get("nope"), "not_found"),
        ]
        s = self.sessions.create("a.ifc", 25)
        cases += [
            (lambda: self.sessions.write_chunk(s.id, 3, b"x" * 10), "bad_request"),  # 範囲外
            (lambda: self.sessions.write_chunk(s.id, 0, b"x" * 9), "bad_request"),  # 大きさ違い
            (lambda: self.sessions.write_chunk(s.id, 2, b"x" * 10), "bad_request"),  # 最後は 5 バイトのはず
            (lambda: self.sessions.start_processing(s.id), "conflict"),  # 未受信あり
        ]
        for fn, kind in cases:
            with self.assertRaises(UploadSessionError) as cm:
                fn()
            self.assertEqual(cm.exception.kind, kind)

    def test_empty_file_has_no_chunks(self):
        s = self.sessions.create("empty.ifc", 0)
        self.assertEqual(s.total_chunks, 0)
        self.sessions.start_processing(s.id)

    def test_cleanup_removes_idle_uploads_but_keeps_processing(self):
        idle = self.sessions.create("a.ifc", 10)
        busy = self.sessions.create("b.ifc", 0)
        self.sessions.start_processing(busy.id)
        idle.updated -= 10_000
        busy.updated -= 10_000
        self.sessions.cleanup_expired()
        self.assertFalse(idle.path.exists())
        with self.assertRaises(UploadSessionError):
            self.sessions.get(idle.id)
        self.assertEqual(self.sessions.get(busy.id).status, "processing")


class ChunkedUploadFlowTest(unittest.TestCase):
    """分割アップロード → 裏の解析 → モデル登録 までを、HTTP を通さずに確認する"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (main.UPLOAD_DIR, main._uploads, main._models.copy())
        main.UPLOAD_DIR = Path(self.tmp.name)
        main._uploads = UploadSessions(main.UPLOAD_DIR, max_size=10**8, chunk_size=4096)

    def tearDown(self):
        main.UPLOAD_DIR, main._uploads, models = self.saved
        main._models.clear()
        main._models.update(models)
        self.tmp.cleanup()

    def _upload(self, filename: str, data: bytes) -> str:
        s = main._uploads.create(filename, len(data))
        for i in range(s.total_chunks):
            main._uploads.write_chunk(s.id, i, data[i * 4096 : (i + 1) * 4096])
        main._uploads.start_processing(s.id)
        main._process_upload(s.id)  # 本番では裏のスレッドで動く
        return s.id

    def test_valid_ifc_becomes_model(self):
        upload_id = self._upload("demo-house.ifc", SAMPLE.read_bytes())
        status = main._uploads.get(upload_id).to_status()
        self.assertEqual(status["status"], "done")
        entry = main._get(status["modelId"])
        self.assertEqual(entry["summary"]["elementCount"], 8)
        self.assertEqual(entry["path"].read_bytes(), SAMPLE.read_bytes())
        self.assertFalse((main.UPLOAD_DIR / f"{upload_id}.part").exists())

    def test_broken_ifc_reports_error_and_removes_file(self):
        upload_id = self._upload("bad.ifc", b"<!DOCTYPE html><html></html>")
        status = main._uploads.get(upload_id).to_status()
        self.assertEqual(status["status"], "error")
        self.assertIn("Webページ", status["detail"])
        self.assertEqual(list(main.UPLOAD_DIR.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
