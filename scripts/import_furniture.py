#!/usr/bin/env python3
"""SchaleDB のモーション家具データをプリセットDBへ取り込む。

生徒（衣装）ごとにカフェでモーションがある家具を furniture /
costume_furniture テーブルへ書き込む。衣装は表示名「生徒名（衣装名）」
（通常衣装は生徒名のみ）で SchaleDB の生徒名と照合する。SchaleDB に
無い衣装の登録内容は変更しない。

デフォルトはドライラン（差分の表示のみ）。--apply を付けると書き込む。

参照するデータ:
    https://schaledb.com/data/jp/students.min.json   FurnitureInteraction
    https://schaledb.com/data/jp/furniture.min.json  家具名

使い方:
    python scripts/import_furniture.py                    # ドライラン
    python scripts/import_furniture.py --apply            # ローカルDBへ書き込み
    python scripts/import_furniture.py --env-var PROD_DATABASE_URL --apply
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent
_ENV_PATH = _BASE_DIR / ".env"

_URL = "https://schaledb.com/data/"
# SchaleDB のサーバー並び (FurnitureInteraction): jp, global, cn
_SERVER = "jp"
_SERVER_INDEX = 0

_DEFAULT_COSTUME = "通常"


def _load_env():
    if _ENV_PATH.exists():
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def _fetch(path: str):
    req = urllib.request.Request(_URL + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def _label(student: str, costume: str) -> str:
    return student if costume == _DEFAULT_COSTUME else f"{student}（{costume}）"


def build_interactions() -> tuple[dict[str, list[int]], dict[int, str]]:
    """SchaleDB から ({生徒表示名: [家具ID]}, {家具ID: 家具名}) を作る。

    FurnitureInteraction の要素は [家具ID, モーション種別]。同じ家具に
    複数種別のモーションがある場合は1つにまとめる。
    """
    students = _fetch(f"{_SERVER}/students.min.json")
    furniture = _fetch(f"{_SERVER}/furniture.min.json")
    by_student: dict[str, list[int]] = {}
    names: dict[int, str] = {}
    for s in students.values():
        ids: list[int] = []
        for fid, _kind in s["FurnitureInteraction"][_SERVER_INDEX]:
            if fid not in ids:
                ids.append(fid)
        if not ids:
            continue
        by_student[s["Name"]] = ids
        for fid in ids:
            names[fid] = furniture[str(fid)]["Name"]
    return by_student, names


def _ensure_tables(cur) -> None:
    """app/backend/user_presets._ensure_furniture_tables と同じスキーマ。"""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS furniture (
            id   INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS costume_furniture (
            costume_id   INTEGER NOT NULL
                REFERENCES costume(id) ON DELETE CASCADE,
            furniture_id INTEGER NOT NULL
                REFERENCES furniture(id) ON DELETE CASCADE,
            PRIMARY KEY (costume_id, furniture_id)
        )
    """)


def _build_plan(cur, by_student, names):
    """SchaleDB と DB 現状の差分から実行計画を作る。"""
    cur.execute("SELECT id, student_name, costume_name FROM costume")
    costumes = {_label(r[1], r[2]): r[0] for r in cur.fetchall()}
    cur.execute("SELECT id, name FROM furniture")
    db_names = dict(cur.fetchall())
    cur.execute("SELECT costume_id, furniture_id FROM costume_furniture")
    current = set(cur.fetchall())

    # SchaleDB にある衣装は SchaleDB の内容に揃える
    matched = {cid for label, cid in costumes.items() if label in by_student}
    desired = {
        (costumes[label], fid)
        for label, fids in by_student.items()
        if label in costumes
        for fid in fids
    }
    used = {fid for _, fid in desired}
    id_to_label = {cid: label for label, cid in costumes.items()}
    return {
        "furniture": sorted(
            (fid, names[fid]) for fid in used if db_names.get(fid) != names[fid]
        ),
        "add": sorted(desired - current),
        "remove": sorted(p for p in current - desired if p[0] in matched),
        "unmatched_db": sorted(label for label in costumes if label not in by_student),
        "id_to_label": id_to_label,
        "names": {**db_names, **names},
    }


def _print_plan(plan) -> None:
    label, names = plan["id_to_label"], plan["names"]
    print(f"家具の追加・名前更新: {len(plan['furniture'])} 件")
    for fid, name in plan["furniture"]:
        print(f"  {fid}: {name}")
    print(f"モーション家具の追加: {len(plan['add'])} 件")
    for cid, fid in plan["add"]:
        print(f"  {label[cid]}: {names[fid]}")
    print(f"モーション家具の削除: {len(plan['remove'])} 件")
    for cid, fid in plan["remove"]:
        print(f"  {label[cid]}: {names.get(fid, fid)}")
    if plan["unmatched_db"]:
        print(
            "SchaleDB にモーション家具が無い衣装（変更なし）: "
            f"{len(plan['unmatched_db'])} 件"
        )
        print("  " + "、".join(plan["unmatched_db"]))


def _apply_plan(cur, plan) -> None:
    for fid, name in plan["furniture"]:
        cur.execute(
            "INSERT INTO furniture (id, name) VALUES (%s, %s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
            (fid, name),
        )
    for cid, fid in plan["remove"]:
        cur.execute(
            "DELETE FROM costume_furniture WHERE costume_id = %s AND furniture_id = %s",
            (cid, fid),
        )
    for cid, fid in plan["add"]:
        cur.execute(
            "INSERT INTO costume_furniture (costume_id, furniture_id) VALUES (%s, %s)",
            (cid, fid),
        )


def main():
    parser = argparse.ArgumentParser(
        description="SchaleDB のモーション家具データをプリセットDBへ取り込む"
    )
    parser.add_argument(
        "--apply", action="store_true", help="実際にDBへ書き込む（既定はドライラン）"
    )
    parser.add_argument(
        "--env-var",
        default="DATABASE_URL",
        help="接続先URLを持つ環境変数名（既定: DATABASE_URL）",
    )
    args = parser.parse_args()

    _load_env()
    db_url = os.environ.get(args.env_var)
    if not db_url:
        print(f"エラー: {args.env_var} が設定されていません")
        return 1

    by_student, names = build_interactions()
    print(
        f"SchaleDB: モーション家具のある生徒 {len(by_student)} 人 / "
        f"家具 {len(names)} 種\n"
    )

    import psycopg2

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            # テーブル作成もトランザクション内なので、ドライランでは残らない
            _ensure_tables(cur)
            plan = _build_plan(cur, by_student, names)
        _print_plan(plan)
        if not args.apply:
            conn.rollback()
            print("\nドライランです。書き込むには --apply を付けてください。")
            return 0
        with conn.cursor() as cur:
            _apply_plan(cur, plan)
        conn.commit()
        target = db_url.split("@")[-1] if "@" in db_url else "(unknown)"
        print(f"\n書き込み完了: {target}")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
