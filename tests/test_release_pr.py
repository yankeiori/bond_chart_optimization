"""リリースPR本文の生成のテスト。"""

from scripts.release_pr import END, START, merge_body, parse_commits, render_notes


def test_parse_commits_merge_and_squash():
    prs, direct = parse_commits(
        [
            "Merge pull request #51 from yankeiori/main",
            "Merge pull request #52 from yankeiori/feat/about-page",
            "Bump plotly (#53)",
            "Fix typo",
        ]
    )
    assert prs == [51, 52, 53]
    assert direct == ["Fix typo"]


def test_render_notes():
    notes = render_notes([{"number": 52, "title": "Add about page"}], ["Fix typo"])
    assert "- #52 Add about page" in notes
    assert "## PRを通さないコミット\n- Fix typo" in notes


def test_render_notes_empty():
    assert "- なし" in render_notes([], [])


def test_merge_body_new_uses_template():
    body = merge_body(None, "## 含まれるPR\n- #1 a")
    assert f"{START}\n## 含まれるPR\n- #1 a\n{END}" in body
    assert "## マージ後に確認すること" in body


def test_merge_body_keeps_handwritten_parts():
    existing = f"前書き\n{START}\n古い内容\n{END}\n## 本番への影響\n- 手書きのメモ"
    body = merge_body(existing, "新しい内容")
    assert (
        body == f"前書き\n{START}\n新しい内容\n{END}\n## 本番への影響\n- 手書きのメモ"
    )
