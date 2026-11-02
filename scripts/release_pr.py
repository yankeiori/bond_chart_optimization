#!/usr/bin/env python3
"""develop → main のリリースPRを作成・更新する。

develop にあって main にないコミットから含まれるPRを集め、リリースPRの
「含まれるPR」欄を書き直す。欄の外（本番への影響・確認事項など）は手書きを残す。
GitHub Actions（.github/workflows/release-pr.yml）から develop への push ごとに呼ばれる。

使い方:
    python scripts/release_pr.py            # PRを作成・更新する
    python scripts/release_pr.py --dry-run  # 本文を表示するだけ
"""

import argparse
import json
import re
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "main"
HEAD = "develop"
START = "<!-- release-notes:start -->"
END = "<!-- release-notes:end -->"

_MERGE_RE = re.compile(r"^Merge pull request #(\d+) from ")
_SQUASH_RE = re.compile(r"\(#(\d+)\)$")

_TEMPLATE = f"""develop の内容を本番（main）に反映するリリースPRです。
develop への push で「含まれるPR」欄が自動更新されます。マージすると Render がデプロイします。

{START}
{END}

## 本番への影響
- （画面・機能の変更、依存更新、render.yaml の変更などがあれば書く）

## マージ後に確認すること
- [ ] Render のデプロイが成功し、ヘルスチェックが通ること
- [ ] 本番サイトの表示・ログイン・管理画面が動くこと
"""


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def parse_commits(subjects: list[str]) -> tuple[list[int], list[str]]:
    """first-parent のコミット件名を、PR番号とPRを通さないコミットに分ける。"""
    prs: list[int] = []
    direct: list[str] = []
    for subject in subjects:
        m = _MERGE_RE.match(subject) or _SQUASH_RE.search(subject)
        if m:
            number = int(m.group(1))
            if number not in prs:
                prs.append(number)
        else:
            direct.append(subject)
    return prs, direct


def render_notes(prs: list[dict], direct: list[str]) -> str:
    """含まれるPR欄（マーカー間）の本文を作る。prs は number・title を持つ dict。"""
    lines = ["## 含まれるPR"]
    lines += [f"- #{pr['number']} {pr['title']}" for pr in prs] or ["- なし"]
    if direct:
        lines += ["", "## PRを通さないコミット"]
        lines += [f"- {subject}" for subject in direct]
    return "\n".join(lines)


def merge_body(existing: str | None, notes: str) -> str:
    """既存の本文のマーカー間だけを notes に差し替える。マーカーがなければ雛形から作る。"""
    body = existing if existing and START in existing and END in existing else _TEMPLATE
    before, rest = body.split(START, 1)
    _, after = rest.split(END, 1)
    return f"{before}{START}\n{notes}\n{END}{after}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="本文を表示するだけ")
    args = parser.parse_args()

    _run("git", "fetch", "--quiet", "origin", BASE, HEAD)
    revs = f"origin/{BASE}..origin/{HEAD}"
    subjects = _run(
        "git", "log", "--first-parent", "--reverse", "--format=%s", revs
    ).splitlines()
    if not subjects:
        print(f"{HEAD} は {BASE} に反映済みです")
        return

    numbers, direct = parse_commits(subjects)
    prs = []
    for number in numbers:
        pr = json.loads(
            _run("gh", "pr", "view", str(number), "--json", "number,title,headRefName")
        )
        # main → develop の取り込みPRはリリース内容ではないので除く
        if pr["headRefName"] != BASE:
            prs.append(pr)
    notes = render_notes(prs, direct)

    pr_list = ["gh", "pr", "list", "--base", BASE, "--head", HEAD, "--state", "open"]
    open_prs = json.loads(_run(*pr_list, "--json", "number,body"))
    existing = open_prs[0] if open_prs else None
    body = merge_body(existing["body"] if existing else None, notes)

    if args.dry_run:
        print(body)
        return
    if existing:
        _run("gh", "pr", "edit", str(existing["number"]), "--body", body)
        print(f"リリースPR #{existing['number']} を更新しました")
    else:
        today = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
        title = f"Release {today}"
        url = _run(
            "gh",
            "pr",
            "create",
            "--base",
            BASE,
            "--head",
            HEAD,
            "--title",
            title,
            "--body",
            body,
        )
        print(f"リリースPRを作成しました: {url.strip()}")


if __name__ == "__main__":
    main()
