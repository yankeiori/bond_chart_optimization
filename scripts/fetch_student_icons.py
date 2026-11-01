#!/usr/bin/env python3
"""Blue Archive Wiki の生徒画像を assets/student/<表示名>.png に保存する。

画像は https://bluearchive.wiki/wiki/Characters の一覧表にある生徒画像
（コレクション画像）の縮小版。衣装は DB の表示名「生徒名（衣装名）」
（通常衣装は生徒名のみ）で SchaleDB の日本語名と照合し、同じ Id の
英語名を Wiki の表記に直して一覧表の行を引く。costume.id はローカルと
本番で違うので、ファイル名には表示名を使う。

既に画像がある衣装は取得しない（--force で取り直す）。
デフォルトはドライラン（照合結果の表示のみ）。--apply を付けると保存する。

参照するデータ:
    https://bluearchive.wiki/wiki/Characters        生徒画像
    https://schaledb.com/data/jp/students.min.json  日本語名
    https://schaledb.com/data/en/students.min.json  英語名

使い方:
    python scripts/fetch_student_icons.py                    # ドライラン
    python scripts/fetch_student_icons.py --apply            # ローカルDBの衣装を保存
    python scripts/fetch_student_icons.py --env-var PROD_DATABASE_URL --apply
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent
_ENV_PATH = _BASE_DIR / ".env"
_OUT_DIR = _BASE_DIR / "assets" / "student"

_WIKI_URL = "https://bluearchive.wiki/wiki/Characters"
_SCHALE_URL = "https://schaledb.com/data/"
_USER_AGENT = "Mozilla/5.0 (bond-chart-optimization student icon fetcher)"
# 保存する画像の幅（元画像は 404x456）。表示 32px の 2 倍
_WIDTH = 64

_DEFAULT_COSTUME = "通常"

# SchaleDB の英語名 -> Wiki の表記（生徒名部分）
_EN_NAME_FIXES = {
    "Aris": "Arisu",
    "Shiroko*Terror": "Shiroko＊Terror",
}
# SchaleDB の英語名 -> Wiki の表記（括弧内の衣装名）
_EN_COSTUME_FIXES = {
    "Armed": "Battle",
    "Bunny": "Bunny Girl",
    "Camp": "Camping",
    "Cheer Squad": "Cheerleader",
    "Cycling": "Riding",
    "Pajamas": "Pajama",
    "Pop Idol": "Idol",
    "School": "School Uniform",
    "Small": "Kid",
    "Track": "Sportswear",
}
# 上の規則で引けない衣装の Wiki 表記（DB の表示名 -> Wiki の行の名前）
_WIKI_NAMES: dict[str, str] = {}


def _load_env():
    if _ENV_PATH.exists():
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def _label(student: str, costume: str) -> str:
    return student if costume == _DEFAULT_COSTUME else f"{student}（{costume}）"


def fetch_wiki_images() -> dict[str, str]:
    """Wiki の一覧表から {行の名前: 縮小画像の URL} を作る。"""
    page = _get(_WIKI_URL).decode("utf-8")
    images = {}
    # 各行の先頭セルが画像。src は 40px 幅のサムネイル
    for m in re.finditer(
        r'<td style="padding:0"><span typeof="mw:File"><a href="[^"]*" '
        r'title="([^"]*)"><img [^>]*?src="([^"]*)"',
        page,
    ):
        src = html.unescape(m.group(2))
        src = re.sub(r"/\d+px-([^/]+)$", rf"/{_WIDTH}px-\1", src)
        images[html.unescape(m.group(1))] = urllib.parse.urljoin(_WIKI_URL, src)
    return images


def _wiki_name(en_name: str) -> str:
    m = re.fullmatch(r"(.+?) \((.+)\)", en_name)
    if not m:
        return _EN_NAME_FIXES.get(en_name, en_name)
    name, costume = m.groups()
    name = _EN_NAME_FIXES.get(name, name)
    return f"{name} ({_EN_COSTUME_FIXES.get(costume, costume)})"


def build_wiki_names() -> dict[str, str]:
    """SchaleDB から {日本語の表示名: Wiki の行の名前} を作る。

    同じ表示名に Id が2つある衣装（ホシノ（臨戦）など形態違い）は
    小さい方の Id の名前を使う。
    """
    jp = json.loads(_get(_SCHALE_URL + "jp/students.min.json"))
    en = json.loads(_get(_SCHALE_URL + "en/students.min.json"))
    names = {}
    for sid in sorted(jp, key=int):
        label = jp[sid]["Name"]
        if label not in names and sid in en:
            names[label] = _wiki_name(en[sid]["Name"])
    names.update(_WIKI_NAMES)
    return names


def load_labels(db_url: str) -> list[str]:
    import psycopg2

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT student_name, costume_name FROM costume ORDER BY id")
            return [_label(s, c) for s, c in cur.fetchall()]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Blue Archive Wiki の生徒画像を assets/student に保存する"
    )
    parser.add_argument(
        "--apply", action="store_true", help="実際に保存する（既定はドライラン）"
    )
    parser.add_argument("--force", action="store_true", help="既にある画像も取り直す")
    parser.add_argument(
        "--env-var",
        default="DATABASE_URL",
        help="衣装一覧を読む DB の URL を持つ環境変数名（既定: DATABASE_URL）",
    )
    args = parser.parse_args()

    _load_env()
    db_url = os.environ.get(args.env_var)
    if not db_url:
        print(f"エラー: {args.env_var} が設定されていません")
        return 1

    labels = load_labels(db_url)
    images = fetch_wiki_images()
    wiki_names = build_wiki_names()
    print(f"DB の衣装 {len(labels)} 件 / Wiki の生徒 {len(images)} 件\n")

    todo, missing = [], []
    for label in labels:
        path = _OUT_DIR / f"{label}.png"
        if path.exists() and not args.force:
            continue
        name = wiki_names.get(label)
        if name not in images:
            missing.append((label, name))
            continue
        todo.append((label, name, images[name], path))

    print(f"取得する画像: {len(todo)} 件")
    for label, name, _, _ in todo:
        print(f"  {label} <- {name}")
    if missing:
        print(f"\nWiki で見つからない衣装: {len(missing)} 件（_WIKI_NAMES に追加する）")
        for label, name in missing:
            print(f"  {label}" + (f"（{name}）" if name else "（SchaleDB に無い）"))

    if not args.apply:
        print("\nドライランです。保存するには --apply を付けてください。")
        return 0
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    for label, _, url, path in todo:
        path.write_bytes(_get(url))
        time.sleep(0.2)
    print(f"\n保存しました: {len(todo)} 件 -> {_OUT_DIR.relative_to(_BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
