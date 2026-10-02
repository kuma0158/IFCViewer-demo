"""
E2E テスト（API・配信）— 稼働中のシステムに対して、利用者と同じ入口（フロントエンド :5173 → /api 転送 → FastAPI :8001）から確認する

実行（サーバーが起動している状態で）:
  cd ifc-pilot
  backend\\venv\\Scripts\\python.exe scripts\\e2e_api.py                 # http://localhost:5173 を対象
  backend\\venv\\Scripts\\python.exe scripts\\e2e_api.py --base https://ifc.shinobuabe.com --skip-heavy

標準ライブラリのみ使用（追加の依存なし）。テストでアップロードしたファイルは最後に削除する。
--skip-heavy を付けると、100MB 超のアップロード（サイズ上限・同時アクセス）の確認を省く。
"""
import argparse
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "demo-house.ifc"
UPLOAD_DIR = ROOT / "backend" / "uploads"

results: list[tuple[str, bool, str]] = []
created_models: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# Cloudflare は Python 標準の User-Agent（Python-urllib）を 403 で弾くため、独自の名前を付ける
USER_AGENT = "ifc-pilot-e2e/1.0"


def parse_json(raw: bytes):
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        return {"detail": f"(JSON ではない応答: {raw[:60]!r})"}


def request(base: str, method: str, path: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 60):
    req = urllib.request.Request(base + path, data=body, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.headers.get("Content-Type", ""), res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def multipart(filename: str, data: bytes) -> tuple[bytes, dict]:
    boundary = uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + data + tail, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def upload(base: str, filename: str, data: bytes, timeout: float = 120):
    body, headers = multipart(filename, data)
    status, _, raw = request(base, "POST", "/api/models", body, headers, timeout)
    payload = parse_json(raw)
    if status == 200:
        created_models.append(payload["modelId"])
    return status, payload


def detail_of(payload) -> str:
    return payload.get("detail", "") if isinstance(payload, dict) else ""


def run(base: str, skip_heavy: bool) -> None:
    sample = SAMPLE.read_bytes()

    # ---- 配信（本番ビルド） ----
    status, ctype, html = request(base, "GET", "/")
    check("S1 トップページが表示できる", status == 200 and b'id="app"' in html, f"{status}")
    check("S2 ビルド済みの JS を読み込んでいる（/assets/…）", b"/assets/index-" in html)
    status, ctype, body = request(base, "GET", "/src/main.ts")
    check("S3 ソースコード（/src/main.ts）が配信されない", b"mountApp" not in body, f"{status} {ctype}")
    status, _, wasm = request(base, "GET", "/web-ifc.wasm")
    check("S4 web-ifc.wasm が配信される", status == 200 and wasm[:4] == b"\0asm", f"{status} {len(wasm)}B")

    # ---- 正常系 ----
    status, model = upload(base, "demo-house.ifc", sample)
    check("A1 IFC をアップロードできる", status == 200, f"{status}")
    if status != 200:
        return
    mid = model["modelId"]
    check(
        "A2 集計結果が正しい（IFC4・壁8枚・1F/2F 各4）",
        model["schema"] == "IFC4"
        and model["elementCount"] == 8
        and model["classCounts"] == {"IfcWall": 8}
        and {s["name"]: s["total"] for s in model["storeys"]} == {"1F": 4, "2F": 4},
    )
    status, _, raw = request(base, "GET", f"/api/models/{mid}")
    check("A3 集計結果を再取得できる", status == 200 and parse_json(raw)["elementCount"] == 8, f"{status}")

    ok_all, bad = True, []
    for row in model["elements"]:
        status, _, raw = request(base, "GET", f"/api/models/{mid}/elements/{row['expressId']}")
        d = parse_json(raw)
        good = (
            status == 200
            and d["expressId"] == row["expressId"]
            and d["globalId"] == row["globalId"]
            and isinstance(d["propertySets"], dict)
            and all("id" not in props for props in d["propertySets"].values())
        )
        if not good:
            ok_all = False
            bad.append(row["expressId"])
    check("A4 全部材（8件）の属性が取れ、一覧と一致する", ok_all, f"NG: {bad}" if bad else "")

    status, _, raw = request(base, "GET", f"/api/models/{mid}/file")
    check("A5 元の IFC をダウンロードでき、中身が一致する", status == 200 and raw == sample, f"{status} {len(raw)}B")

    # ---- 異常系（部材・モデル） ----
    status, _, raw = request(base, "GET", f"/api/models/{mid}/elements/99999")
    check("B1 存在しない部材は 404（部材が見つかりません）", status == 404 and "部材" in detail_of(parse_json(raw)), f"{status}")
    status, _, raw = request(base, "GET", f"/api/models/{mid}/elements/99999999999")
    check("B2 範囲外の expressID は 422（500 にならない）", status == 422, f"{status}")
    status, _, raw = request(base, "GET", f"/api/models/{mid}/elements/0")
    check("B3 expressID 0 は 422", status == 422, f"{status}")
    status, _, raw = request(base, "GET", "/api/models/does-not-exist/elements/1")
    check(
        "B4 存在しないモデルは 404（モデルが見つかりません）",
        status == 404 and detail_of(parse_json(raw)) == "モデルが見つかりません",
        f"{status}",
    )

    # ---- 異常系（アップロード） ----
    status, p = upload(base, "readme.txt", b"hello")
    check("C1 拡張子が .ifc でなければ 400", status == 400, f"{status} {detail_of(p)}")
    cases = [
        ("C2 空のファイルは 422（空です）", b"", "空"),
        ("C3 HTML を保存したファイルは 422（Webページ）", b"<!DOCTYPE html><html></html>", "Webページ"),
        ("C4 ZIP は 422（ZIP形式）", b"PK\x03\x04" + b"\0" * 100, "ZIP"),
        ("C5 IFC 以外のテキストは 422（ISO-10303-21）", b"hello world", "ISO-10303-21"),
    ]
    for name, data, keyword in cases:
        status, p = upload(base, "bad.ifc", data)
        check(name, status == 422 and keyword in detail_of(p), f"{status} {detail_of(p)[:40]}")

    if skip_heavy:
        return

    # ---- サイズ上限と同時アクセス ----
    with tempfile.TemporaryDirectory() as tmp:
        big = Path(tmp) / "big.ifc"
        with big.open("wb") as f:
            f.write(b"ISO-10303-21;\n")
            f.write(b"x" * (101 * 1024 * 1024))
        data = big.read_bytes()

    result: dict = {}

    def do_big():
        t = time.perf_counter()
        result["status"], result["payload"] = upload(base, "big.ifc", data, timeout=300)
        result["sec"] = time.perf_counter() - t

    th = threading.Thread(target=do_big)
    th.start()
    time.sleep(0.3)
    t = time.perf_counter()
    status, _, _ = request(base, "GET", f"/api/models/{mid}")
    elapsed = time.perf_counter() - t
    th.join()
    check("D1 101MB のアップロードは 413", result.get("status") == 413, f"{result.get('status')} {result.get('sec', 0):.1f}s")
    check("D2 大きなアップロード中も他のリクエストがすぐ返る（1秒未満）", status == 200 and elapsed < 1.0, f"{elapsed * 1000:.0f}ms")


def cleanup() -> None:
    # テストで作ったモデルのファイルだけを消す（他の利用者のファイルには触らない）
    for mid in created_models:
        try:
            (UPLOAD_DIR / f"{mid}.ifc").unlink(missing_ok=True)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--skip-heavy", action="store_true")
    args = ap.parse_args()
    print(f"対象: {args.base}\n")
    try:
        run(args.base.rstrip("/"), args.skip_heavy)
    finally:
        cleanup()
    failed = [r for r in results if not r[1]]
    print(f"\n結果: {len(results) - len(failed)}/{len(results)} 成功")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
