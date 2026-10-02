#!/usr/bin/env python3
"""SchaleDB の製造データから app/backend/crafting_data.py を生成する。

1〜3次の各ノードについて、日本サーバーで実装済みのノードの重みと、
そのノードで出る贈り物（ノード内の出現率と個数）を取り出す。
贈り物が出ないノードも、ノード選択の確率計算に要るので重みだけ残す。

参照するデータ:
    https://schaledb.com/data/crafting.min.json   ノードの重み・報酬グループ
    https://schaledb.com/data/groups.min.json     グループ内のアイテムと確率・個数
    https://schaledb.com/data/jp/items.min.json   贈り物の判定・名前・レアリティ

使い方:
    uv run python scripts/fetch_crafting.py
"""

import json
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent
_OUT_PATH = _BASE_DIR / "app" / "backend" / "crafting_data.py"
_GIFT_ASSETS = _BASE_DIR / "assets" / "gift"

_URL = "https://schaledb.com/data/"
# SchaleDB のサーバー並び (Released / TotalProp): jp, global, cn
_SERVER = "jp"
_SERVER_INDEX = 0

# SchaleDB 表記 -> リポジトリ（DB の gift.name）表記
_NAME_FIXES: dict[str, str] = {}


def _fetch(path: str):
    req = urllib.request.Request(_URL + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def _gift_name(name: str) -> str:
    # 改行入りの名前があり、波ダッシュ (U+301C) はリポジトリでは全角チルダ
    name = name.replace("\n", "").replace("〜", "～")
    return _NAME_FIXES.get(name, name)


def _node_gifts(node: dict, groups: dict, items: dict) -> list[tuple]:
    """ノードで出る贈り物 [(名前, ノード内の出現率, 最小個数, 最大個数)]。"""
    total = sum(g["Weight"] for g in node["Groups"])
    gifts = []
    for group in node["Groups"]:
        entries = groups[str(group["GroupId"])]["Items"]
        # Chance は丸め値（例: 0.0286 × 35 = 1.001）なのでグループ内で正規化する
        chance_sum = sum(e["Chance"] for e in entries)
        for e in entries:
            item = items.get(str(e["Id"])) if e["Type"] == "Item" else None
            if item is None or item["Category"] != "Favor":
                continue
            rate = group["Weight"] / total * e["Chance"] / chance_sum
            gifts.append(
                (_gift_name(item["Name"]), rate, e["AmountMin"], e["AmountMax"])
            )
    return gifts


def build() -> list[list[tuple]]:
    crafting = _fetch("crafting.min.json")
    groups = _fetch("groups.min.json")
    items = _fetch(f"{_SERVER}/items.min.json")

    tiers = []
    for tier in (1, 2, 3):
        nodes = [
            n
            for n in crafting["Nodes"]
            if n["Tier"] == tier and n["Released"][_SERVER_INDEX]
        ]
        total = sum(n["Property"] for n in nodes)
        expected = crafting["TotalProp"][_SERVER][tier - 1]
        if total != expected:
            sys.exit(f"{tier}次: 重みの合計 {total} が TotalProp {expected} と違う")
        tiers.append(
            [
                (n["Id"], n["NameJp"], n["Property"], _node_gifts(n, groups, items))
                for n in nodes
            ]
        )

    missing = sorted(
        {
            name
            for nodes in tiers
            for *_, gifts in nodes
            for name, *_ in gifts
            if not (_GIFT_ASSETS / f"{name}.png").exists()
        }
    )
    if missing:
        sys.exit(f"assets/gift に無い贈り物名: {missing}（_NAME_FIXES に追加する）")
    return tiers


def render(tiers: list[list[tuple]]) -> str:
    lines = [
        '"""製造（クラフトチェンバー）のノードの重みと、ノードで出る贈り物。',
        "",
        "scripts/fetch_crafting.py が SchaleDB から生成する。手で編集しない。",
        f"出典: {_URL} (crafting / groups / {_SERVER}/items)",
        f"取得日: {date.today().isoformat()} / サーバー: {_SERVER}",
        '"""',
        "",
        "# TIERS[段 - 1] = ((ノードID, ノード名, 重み, 贈り物), ...)",
        "# 贈り物 = ((名前, ノード内の出現率, 最小個数, 最大個数), ...)",
        "TIERS = (",
    ]
    for nodes in tiers:
        lines.append("    (")
        for node_id, name, weight, gifts in nodes:
            if not gifts:
                lines.append(f"        ({node_id}, {name!r}, {weight}, ()),")
                continue
            lines.append(f"        ({node_id}, {name!r}, {weight}, (")
            for gift in gifts:
                lines.append(f"            {gift!r},")
            lines.append("        )),")
        lines.append("    ),")
    lines.append(")")
    return "\n".join(lines) + "\n"


def main() -> None:
    _OUT_PATH.write_text(render(build()), encoding="utf-8")
    subprocess.run(["ruff", "format", str(_OUT_PATH)], check=False)
    print(f"wrote {_OUT_PATH.relative_to(_BASE_DIR)}")


if __name__ == "__main__":
    main()
