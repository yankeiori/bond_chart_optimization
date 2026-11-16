"""配信量を抑えるためのキャッシュ・圧縮・アイコン形式のテスト（main.py の after_request）。"""

from pathlib import Path
from urllib.parse import quote

import pytest

import main  # noqa: F401 - after_request の登録
from app import app

_ASSETS = Path(__file__).resolve().parents[1] / "assets"


@pytest.fixture
def client():
    return app.server.test_client()


def _first(subdir: str, pattern: str) -> str:
    name = sorted((_ASSETS / subdir).glob(pattern))[0].name
    return f"/assets/{subdir}/{quote(name)}"


@pytest.mark.parametrize(
    "url",
    [
        _first("student", "*.webp"),
        _first("gift", "*.webp"),
        _first("reaction", "*.webp"),
    ],
)
def test_icons_are_cached_for_a_week(client, url):
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=604800"


def test_student_icon_is_served_as_webp(client):
    response = client.get(_first("student", "*.webp"))
    assert response.headers["Content-Type"] == "image/webp"


def test_missing_icon_is_not_cached(client):
    response = client.get("/assets/student/" + quote("存在しない生徒") + ".webp")
    assert response.status_code == 404
    assert "max-age=604800" not in response.headers.get("Cache-Control", "")


def test_dash_layout_is_not_cached(client):
    response = client.get("/_dash-layout")
    assert "no-store" in response.headers["Cache-Control"]


def test_dash_bundles_keep_long_cache(client):
    html = client.get("/chart-opt").get_data(as_text=True)
    start = html.index("/_dash-component-suites/dash/dcc/dash_core_components.v")
    url = html[start : html.index('"', start)]
    response = client.get(url)
    assert response.status_code == 200
    assert "no-store" not in response.headers.get("Cache-Control", "")


def test_responses_are_compressed(client):
    response = client.get("/_dash-layout", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("Content-Encoding") == "gzip"


def test_student_icons_are_webp_only():
    files = list((_ASSETS / "student").iterdir())
    assert files
    assert {p.suffix for p in files} == {".webp"}
