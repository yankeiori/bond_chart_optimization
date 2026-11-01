import os
import sys
from datetime import timedelta
from pathlib import Path

from dash import Dash
from werkzeug.middleware.proxy_fix import ProxyFix

# PyInstaller バンドル時は _MEIPASS、通常時はプロジェクトルート
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys._MEIPASS)
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent

app = Dash(
    __name__,
    assets_folder=str(_BASE_DIR / "assets"),
    suppress_callback_exceptions=True,
    title="絆上げ優先度計算機",
    update_title=None,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

server = app.server

# FLASK_SECRET_KEY が未設定でも、毎起動でランダム生成して既知キーでの
# セッション偽造を防ぐ（再起動で管理者・ユーザーとも再ログインになる副作用が
# あるため、本番では固定値を設定する）。
server.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32).hex()

# セッション Cookie の保護設定。PORT 環境変数は gunicorn/Render など
# 本番ホスティング下でセットされる想定で、その場合のみ Secure を強制する
# （ローカル HTTP 開発では Secure を切らないと Cookie が送信されない）。
# ユーザーのログインは permanent セッションにして 180 日保持する。
server.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE="PORT" in os.environ,
    PERMANENT_SESSION_LIFETIME=timedelta(days=180),
)

# Render のリバースプロキシ配下で、OAuth のリダイレクト先 URL を
# https・公開ホスト名で組み立てるため X-Forwarded-Proto / Host を信頼する。
if "PORT" in os.environ:
    server.wsgi_app = ProxyFix(server.wsgi_app, x_proto=1, x_host=1)
