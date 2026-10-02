"""
IFC解析ロジック（Step 1 の analyze_ifc.py をAPI向けに整理したもの）

APIの処理（main.py）とIFCの処理をこのファイルに分けておくことで、
後からCLIやテストでも同じ関数を使い回せるようにしている。
"""
from collections import Counter, defaultdict

import ifcopenshell
import ifcopenshell.util.element as element_util


def open_model(path: str) -> ifcopenshell.file:
    return ifcopenshell.open(path)


def describe_open_error(path: str, error: Exception) -> str:
    """open_model が失敗したとき、ファイル先頭を見て原因別の日本語メッセージを返す

    先に ifcopenshell で開き、失敗した場合だけ呼ぶ。こうすることで、
    ifcopenshell が読めるファイルをこのチェックで弾いてしまうことがない。
    """
    with open(path, "rb") as f:
        head = f.read(1024)

    if not head:
        return "ファイルが空です。"
    if head.startswith(b"PK\x03\x04"):
        return "ZIP形式のファイルです。IFC-ZIP（.ifczip）には未対応のため、解凍した .ifc を選んでください。"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "文字コードが UTF-16 で保存されています。IFC は ASCII（または UTF-8）のテキストで保存し直してください。"

    text = head.removeprefix(b"\xef\xbb\xbf").lstrip().lower()
    if text.startswith((b"<!doctype html", b"<html")):
        return (
            "中身がWebページ（HTML）になっています。ブラウザの「名前を付けて保存」ではなく、"
            "元のIFCファイルをダウンロードし直してください（GitHub なら Raw / Download から）。"
        )
    if text.startswith(b"<"):
        return "XML形式のファイルです。ifcXML には未対応のため、テキスト形式（STEP）の .ifc を選んでください。"
    if not text.startswith(b"iso-10303-21;"):
        return "IFC（テキスト形式）のファイルではありません。先頭が「ISO-10303-21;」で始まるファイルを選んでください。"
    if "header" in str(error).lower():
        return (
            "IFCのヘッダー部分が規格に沿っていないため読み込めません。"
            "ファイルが途中で欠けているか、作成したソフトの出力に問題がある可能性があります。"
        )
    return f"IFCを解析できませんでした。ファイルが壊れている可能性があります（{error}）"


def _storey_name(el) -> str:
    container = element_util.get_container(el)
    return container.Name if container and container.Name else "(所属なし)"


def summarize(model: ifcopenshell.file) -> dict:
    """プロジェクト情報・階ごと・種類ごとの集計と部材一覧を返す"""
    projects = model.by_type("IfcProject")
    elements = model.by_type("IfcElement")

    by_storey = defaultdict(Counter)  # 階 → {種類: 数}
    element_rows = []
    for el in elements:
        storey = _storey_name(el)
        by_storey[storey][el.is_a()] += 1
        element_rows.append(
            {
                # expressId はIFCファイル内の行番号(#123)。
                # ブラウザ側の web-ifc でも同じ番号が使われるため、
                # 3D画面でクリックした部材とAPIのデータを結びつけるキーになる。
                "expressId": el.id(),
                "globalId": el.GlobalId,
                "ifcClass": el.is_a(),
                "name": el.Name,
                "storey": storey,
            }
        )

    return {
        "schema": model.schema,
        "project": projects[0].Name if projects else None,
        "elementCount": len(elements),
        "classCounts": dict(Counter(el.is_a() for el in elements).most_common()),
        "storeys": [
            {"name": name, "total": sum(c.values()), "classCounts": dict(c)}
            for name, c in by_storey.items()
        ],
        "elements": element_rows,
    }


def element_detail(model: ifcopenshell.file, express_id: int) -> dict | None:
    """1つの部材の基本情報とプロパティセットを返す"""
    try:
        el = model.by_id(express_id)
    except RuntimeError:
        return None
    if not el.is_a("IfcElement"):
        return None

    psets = element_util.get_psets(el)
    # ifcopenshell が付与する内部用の "id" キーは不要なので除く
    cleaned = {
        name: {k: v for k, v in props.items() if k != "id"}
        for name, props in psets.items()
    }
    return {
        "expressId": el.id(),
        "globalId": el.GlobalId,
        "ifcClass": el.is_a(),
        "name": el.Name,
        "storey": _storey_name(el),
        "propertySets": cleaned,
    }
