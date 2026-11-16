"""帯域対策（main.py の before/after_request、app/caching.py）と悪用対策のテスト。"""

import gzip
import json
import os
import re

import pytest

import main  # noqa: F401 - before/after_request とルートの登録
from app import app
from app.backend.bond_ranks import OCR_MAX_CARDS, OCR_MAX_NAMES, merge_ocr_cards
from app.caching import content_mtime, stabilize_mtimes, version_only_fingerprint
from app.frontend.callbacks import _bm_ocr_preview

LONG_CACHE = "public, max-age=31536000, immutable"


@pytest.fixture
def client():
    return app.server.test_client()


def _index_html(client) -> str:
    return client.get("/chart-opt").get_data(as_text=True)


# ---------------------------------------------------------------------------
# ルートの転送
# ---------------------------------------------------------------------------


def test_root_redirects_on_the_server(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"] == "/chart-opt"


def test_root_redirect_keeps_query(client):
    response = client.get("/?a=1&b=2")
    assert response.headers["Location"] == "/chart-opt?a=1&b=2"


def test_location_does_not_reload_on_callback_navigation():
    from app.frontend.layout import create_root_layout

    layout = create_root_layout()
    loc = next(c for c in layout.children if getattr(c, "id", None) == "url")
    assert loc.refresh == "callback-nav"


# ---------------------------------------------------------------------------
# 版入りの URL の長期キャッシュ
# ---------------------------------------------------------------------------


def test_dash_bundle_fingerprint_uses_version_only(client):
    html = _index_html(client)
    urls = re.findall(r'/_dash-component-suites/[^"]+', html)
    assert urls
    # .v<版>m0.js（デプロイ時刻の mtime が入らない）
    assert all(re.search(r"\.v[\w-]+m0\.", u) for u in urls), urls


def test_dash_bundles_are_immutable(client):
    html = _index_html(client)
    start = html.index("/_dash-component-suites/dash/dcc/dash_core_components.v")
    url = html[start : html.index('"', start)]
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == LONG_CACHE


def test_versioned_assets_are_immutable(client):
    html = _index_html(client)
    match = re.search(r'/assets/style\.css\?m=[^"]+', html)
    assert match
    response = client.get(match.group(0), headers={"Accept-Encoding": "br"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == LONG_CACHE


def test_compressed_asset_revalidates_to_304(client):
    """圧縮で ETag に ":br" が付いても、再検証は 304 になる（全量を送り直さない）。"""
    headers = {"Accept-Encoding": "br"}
    first = client.get("/assets/style.css", headers=headers)
    assert first.headers.get("Content-Encoding") == "br"
    etag = first.headers["ETag"]
    assert etag.endswith(':br"')
    second = client.get("/assets/style.css", headers={**headers, "If-None-Match": etag})
    assert second.status_code == 304
    assert second.get_data() == b""


def test_unversioned_assets_are_not_long_cached(client):
    response = client.get("/assets/style.css")
    assert "immutable" not in response.headers.get("Cache-Control", "")


# ---------------------------------------------------------------------------
# robots.txt と favicon.ico
# ---------------------------------------------------------------------------


def test_robots_txt(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    body = response.get_data(as_text=True)
    assert "Disallow: /admin" in body
    assert "max-age=86400" in response.headers["Cache-Control"]


def test_favicon_ico_is_the_icon(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.mimetype != "text/html"
    assert "max-age=604800" in response.headers["Cache-Control"]


# ---------------------------------------------------------------------------
# 悪用対策
# ---------------------------------------------------------------------------


def test_compressed_callback_body_is_rejected(client):
    body = gzip.compress(json.dumps({"output": "x"}).encode())
    response = client.post(
        "/_dash-update-component",
        data=body,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert response.status_code == 415


def test_oversized_request_is_rejected(client):
    response = client.post(
        "/_dash-update-component",
        data=b"x" * (4 * 1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_ocr_preview_ignores_non_integer_counts():
    options = [{"value": 1, "label": "アル"}]
    result = {
        "cards": [{"costume_id": 1, "rank": 5, "uncertain": False}],
        "failed": "あ" * 10_000,
        "partial": [0] * 10_000,
    }
    status, _ = _bm_ocr_preview(result, None, options)
    text = json.dumps(status.to_plotly_json(), ensure_ascii=False, default=str)
    assert "あああ" not in text
    assert "[0, 0" not in text


def test_ocr_preview_caps_counts():
    options = [{"value": 1, "label": "アル"}]
    result = {"cards": [], "failed": 10**12, "partial": -5}
    status, _ = _bm_ocr_preview(result, None, options)
    text = json.dumps(status.to_plotly_json(), ensure_ascii=False, default=str)
    assert "100000" in text
    assert "-5" not in text


def test_merge_ocr_cards_caps_names_and_cards():
    cards = [
        {"costume_id": 1, "rank": 5, "uncertain": False, "name": f"名前{i}"}
        for i in range(50)
    ]
    (entry,) = merge_ocr_cards(cards)
    assert len(entry["names"]) == OCR_MAX_NAMES
    many = [{"costume_id": i, "rank": 5} for i in range(OCR_MAX_CARDS + 10)]
    assert len(merge_ocr_cards(many)) == OCR_MAX_CARDS


def test_server_callbacks_never_receive_ocr_images(client):
    """スクリーンショットや切り抜き画像を運ぶ部品を、サーバーのコールバックに渡さない
    （画面の「画像はサーバーに送信しません」の約束）。"""
    forbidden_ids = {"bm-ocr-upload", "bm-ocr-crops"}
    forbidden_props = {
        ("bm-ocr-preview", "children"),
        ("page-content", "children"),
        ("bm-image", "src"),
    }
    deps = client.get("/_dash-dependencies").get_json()
    server_deps = [d for d in deps if not d.get("clientside_function")]
    assert server_deps
    for dep in server_deps:
        for item in dep["inputs"] + dep["state"]:
            raw = item["id"]
            cid = json.loads(raw).get("type") if raw.startswith("{") else raw
            assert cid not in forbidden_ids, dep["output"]
            assert (cid, item["property"]) not in forbidden_props, dep["output"]


# ---------------------------------------------------------------------------
# app/caching.py
# ---------------------------------------------------------------------------


def test_content_mtime_depends_only_on_content():
    assert content_mtime(b"abc") == content_mtime(b"abc")
    assert content_mtime(b"abc") != content_mtime(b"abd")
    # 2000〜2020 年の範囲（Last-Modified が未来や 1970 年にならない）
    assert 946684800 <= content_mtime(b"x") < 946684800 + 631152000


def test_stabilize_mtimes(tmp_path):
    (tmp_path / "sub").mkdir()
    a = tmp_path / "a.css"
    b = tmp_path / "sub" / "b.js"
    a.write_bytes(b"body{}")
    b.write_bytes(b"var x;")
    assert stabilize_mtimes(tmp_path) == 2
    assert int(os.stat(a).st_mtime) == content_mtime(b"body{}")
    assert int(os.stat(b).st_mtime) == content_mtime(b"var x;")
    # 2 回目は何も変えない（デプロイのたびに同じ値になる）
    assert stabilize_mtimes(tmp_path) == 0


def test_version_only_fingerprint():
    url = version_only_fingerprint("dcc/dash_core_components.js", "4.5.3", 1794771813)
    assert url == "dcc/dash_core_components.v4_5_3m0.js"
