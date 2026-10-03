"""
E2E テスト（API・配信）— 稼働中のシステムに対して、利用者と同じ入口（フロントエンド :5173 → /api 転送 → FastAPI :8001）から確認する

実行（サーバーが起動している状態で）:
  cd ifc-pilot
  backend\\venv\\Scripts\\python.exe scripts\\e2e_api.py                 # http://localhost:5173 を対象
  backend\\venv\\Scripts\\python.exe scripts\\e2e_api.py --base https://ifc.shinobuabe.com --skip-heavy

標準ライブラリのみ使用（追加の依存なし）。テストでアップロードしたファイルは最後に削除する。
--skip-heavy を付けると、100MB 超のアップロード（サイズ上限・同時アクセス・大きなファイルの分割アップロード）の確認を省く。
--big-mb N で、分割アップロードで送る大きな IFC（合成データ）のサイズを指定する（既定 120MB）。
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
created_uploads: list[str] = []  # 分割アップロードのセッション（途中で止めたものの .part を消すため）


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


def chunked_upload(base: str, filename: str, data: bytes, timeout: float = 600):
    """分割アップロード（POST /api/uploads → PUT chunks → complete → 状態の問い合わせ）。(最終状態, 秒) を返す"""
    t0 = time.perf_counter()
    body = json.dumps({"filename": filename, "size": len(data)}).encode()
    status, _, raw = request(base, "POST", "/api/uploads", body, {"Content-Type": "application/json"})
    if status != 201:
        return {"status": "http", "code": status, "detail": detail_of(parse_json(raw))}, 0.0
    session = parse_json(raw)
    uid, size = session["uploadId"], session["chunkSize"]
    for i in range(session["totalChunks"]):
        status, _, raw = request(
            base, "PUT", f"/api/uploads/{uid}/chunks/{i}", data[i * size : (i + 1) * size],
            {"Content-Type": "application/octet-stream"}, timeout=300,
        )
        if status != 200:
            return {"status": "http", "code": status, "detail": detail_of(parse_json(raw))}, 0.0
    request(base, "POST", f"/api/uploads/{uid}/complete")
    while time.perf_counter() - t0 < timeout:
        _, _, raw = request(base, "GET", f"/api/uploads/{uid}")
        st = parse_json(raw)
        if st.get("status") in ("done", "error"):
            if st.get("modelId"):
                created_models.append(st["modelId"])
            return st, time.perf_counter() - t0
        time.sleep(1)
    return {"status": "timeout"}, time.perf_counter() - t0


def synthetic_ifc(target_mb: int) -> bytes:
    """サンプル IFC の DATA 部に、参照されないプロパティ値を詰めて大きくした IFC（形状と部材数は元のまま）"""
    text = SAMPLE.read_bytes()
    head, sep, tail = text.rpartition(b"ENDSEC;")
    # DATA の ENDSEC は最後から 1 つ目（その後ろは END-ISO-10303-21 のみ）
    line = b"='" + b"x" * 900 + b"';"
    filler = bytearray()
    n = 900000
    while len(filler) < target_mb * 1024 * 1024:
        filler += b"#%d=IFCPROPERTYSINGLEVALUE('Filler',$,IFCLABEL(" % n + line[1:-1] + b"),$);\n"
        n += 1
    return head + bytes(filler) + sep + tail


def detail_of(payload) -> str:
    return payload.get("detail", "") if isinstance(payload, dict) else ""


def run(base: str, skip_heavy: bool, big_mb: int) -> None:
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

    # ---- 分割アップロード ----
    st, sec = chunked_upload(base, "demo-house.ifc", sample)
    ok = st.get("status") == "done"
    if ok:
        _, _, raw = request(base, "GET", f"/api/models/{st['modelId']}")
        ok = parse_json(raw).get("elementCount") == 8
    check("E1 分割アップロード（小さいファイル）→ 解析 → モデル取得", ok, f"{st.get('status')} {sec:.1f}s")
    st, _ = chunked_upload(base, "bad.ifc", b"<!DOCTYPE html><html></html>")
    check("E2 分割アップロードで壊れたファイルは status=error と原因", st.get("status") == "error" and "Webページ" in st.get("detail", ""), st.get("detail", "")[:30])
    body = json.dumps({"filename": "huge.ifc", "size": 501 * 1024 * 1024}).encode()
    status, _, raw = request(base, "POST", "/api/uploads", body, {"Content-Type": "application/json"})
    check("E3 500MB 超は開始時点で 413", status == 413 and "500MB" in detail_of(parse_json(raw)), f"{status}")
    body = json.dumps({"filename": "a.txt", "size": 10}).encode()
    status, _, _ = request(base, "POST", "/api/uploads", body, {"Content-Type": "application/json"})
    check("E4 拡張子が .ifc でなければ 400", status == 400, f"{status}")
    body = json.dumps({"filename": "a.ifc", "size": 10}).encode()
    _, _, raw = request(base, "POST", "/api/uploads", body, {"Content-Type": "application/json"})
    uid = parse_json(raw).get("uploadId", "")
    created_uploads.append(uid)
    status, _, _ = request(base, "PUT", f"/api/uploads/{uid}/chunks/0", b"x" * 5)
    check("E5 チャンクの大きさが違えば 400", status == 400, f"{status}")
    status, _, _ = request(base, "POST", f"/api/uploads/{uid}/complete")
    check("E6 全チャンクが揃う前の完了通知は 409", status == 409, f"{status}")
    status, _, _ = request(base, "GET", "/api/uploads/does-not-exist")
    check("E7 存在しないアップロードは 404", status == 404, f"{status}")

    if skip_heavy:
        return

    # ---- サイズ上限と同時アクセス ----
    with tempfile.TemporaryDirectory() as tmp:
        big = Path(tmp) / "big.ifc"
        with big.open("wb") as f:
            f.write(b"ISO-10303-21;\n")
            f.write(b"x" * (501 * 1024 * 1024))
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
    check("D1 500MB 超（501MB）の一括アップロードは 413", result.get("status") == 413, f"{result.get('status')} {result.get('sec', 0):.1f}s")
    check("D2 大きなアップロード中も他のリクエストがすぐ返る（1秒未満）", status == 200 and elapsed < 1.0, f"{elapsed * 1000:.0f}ms")

    big = synthetic_ifc(big_mb)
    st, sec = chunked_upload(base, "big.ifc", big)
    ok = st.get("status") == "done"
    if ok:
        _, _, raw = request(base, "GET", f"/api/models/{st['modelId']}")
        ok = parse_json(raw).get("elementCount") == 8
        status, _, raw = request(base, "GET", f"/api/models/{st['modelId']}/file", timeout=600)
        ok = ok and status == 200 and len(raw) == len(big)
    check(
        f"F1 {len(big) / 1024 / 1024:.0f}MB の IFC を分割アップロード → 解析 → ダウンロード",
        ok, f"{st.get('status')} {st.get('detail', '')[:40]} {sec:.0f}s",
    )


def cleanup() -> None:
    # テストで作ったモデルのファイルだけを消す（他の利用者のファイルには触らない）
    targets = [UPLOAD_DIR / f"{mid}.ifc" for mid in created_models]
    targets += [UPLOAD_DIR / f"{uid}.part" for uid in created_uploads if uid]
    for path in targets:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--skip-heavy", action="store_true")
    ap.add_argument("--big-mb", type=int, default=120)
    args = ap.parse_args()
    print(f"対象: {args.base}\n")
    try:
        run(args.base.rstrip("/"), args.skip_heavy, args.big_mb)
    finally:
        cleanup()
    failed = [r for r in results if not r[1]]
    print(f"\n結果: {len(results) - len(failed)}/{len(results)} 成功")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
