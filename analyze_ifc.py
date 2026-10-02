"""
IFCファイルを読み込み、以下を表示するスクリプト（パイロット Step 1）
  1. プロジェクト情報とIFCスキーマ
  2. 階（IfcBuildingStorey）ごとの部材数
  3. 部材の種類別の集計
  4. 最初の部材のプロパティセット（属性情報）の例

使い方:
    python analyze_ifc.py sample.ifc
"""
import sys
from collections import Counter, defaultdict

import ifcopenshell
import ifcopenshell.util.element as element_util


def main(path: str) -> None:
    model = ifcopenshell.open(path)

    # 1. プロジェクト情報
    project = model.by_type("IfcProject")[0]
    print(f"スキーマ : {model.schema}")
    print(f"プロジェクト : {project.Name}")
    print()

    # 部材（壁・床・柱・窓・扉など）は IfcElement のサブクラス
    elements = model.by_type("IfcElement")

    # 2. 階ごとの部材数
    by_storey = defaultdict(list)
    for el in elements:
        container = element_util.get_container(el)
        storey_name = container.Name if container else "(所属なし)"
        by_storey[storey_name].append(el)

    print("■ 階ごとの部材数")
    for storey, els in by_storey.items():
        print(f"  {storey}: {len(els)}")
    print()

    # 3. 種類別の集計
    print("■ 部材の種類別集計")
    counts = Counter(el.is_a() for el in elements)
    for ifc_class, n in counts.most_common():
        print(f"  {ifc_class:<25} {n}")
    print()

    # 4. プロパティセット（属性情報）の例
    # 属性情報を持つ最初の部材を探す
    sample = next((el for el in elements if element_util.get_psets(el)), None)
    if sample:
        el = sample
        print(f"■ 属性情報の例: {el.is_a()} / {el.Name} (GlobalId: {el.GlobalId})")
        psets = element_util.get_psets(el)
        for pset_name, props in psets.items():
            print(f"  [{pset_name}]")
            for key, value in props.items():
                if key != "id":
                    print(f"    {key}: {value}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python analyze_ifc.py <IFCファイルのパス>")
        sys.exit(1)
    main(sys.argv[1])
