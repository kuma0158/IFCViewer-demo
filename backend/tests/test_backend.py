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


if __name__ == "__main__":
    unittest.main()
