"""Render の Health Check Path 用エンドポイントのテスト。"""

from app import app


def test_healthz_returns_ok_without_cache():
    response = app.server.test_client().get("/healthz")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"
    assert response.headers["Cache-Control"] == "no-store"
