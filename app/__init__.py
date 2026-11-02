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

SITE_NAME = "絆上げ計算機"
SITE_URL = "https://bond-chart-optimization.onrender.com/"
SITE_DESCRIPTION = (
    "ブルーアーカイブの絆上げを支援する無料ツール集。複数衣装の絆上げ優先度計算、"
    "贈り物の配分シミュレーション、必要絆経験値、贈り物逆引き、製造ノード比較、"
    "絆ランク管理を提供します。"
)

# リンク共有時のプレビュー（X 等のクローラーは JavaScript を実行しない）と
# 検索結果の説明文のため、description と OGP は HTML に直接埋め込む。
app = Dash(
    __name__,
    assets_folder=str(_BASE_DIR / "assets"),
    # 管理画面だけで使うスクリプト（admin_*.js）は公開ページで読み込まない
    # （/assets/ からの配信はされる）
    assets_ignore=r"^admin_",
    suppress_callback_exceptions=True,
    title=SITE_NAME,
    update_title=None,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "description", "content": SITE_DESCRIPTION},
        {"property": "og:type", "content": "website"},
        {"property": "og:url", "content": SITE_URL},
        {"property": "og:site_name", "content": SITE_NAME},
        {"property": "og:title", "content": SITE_NAME},
        {"property": "og:description", "content": SITE_DESCRIPTION},
        {"property": "og:image", "content": SITE_URL + "assets/og-image.png"},
        {"property": "og:image:width", "content": "1200"},
        {"property": "og:image:height", "content": "630"},
        {"property": "og:image:alt", "content": SITE_NAME},
        {"property": "og:locale", "content": "ja_JP"},
        {"name": "twitter:card", "content": "summary_large_image"},
    ],
)

# Dash 既定のテンプレートに lang="ja" と、JavaScript 無効時の案内を足したもの。
app.index_string = """<!DOCTYPE html>
<html lang="ja">
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        <noscript>このサイトの利用には JavaScript を有効にしてください。</noscript>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""

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


# Render の Health Check Path 用。DB が一時的に落ちてもアプリの再起動や
# デプロイ失敗につながらないよう、DB には触れずにプロセスの応答だけを返す。
@server.route("/healthz")
def healthz():
    return "ok", 200, {"Cache-Control": "no-store"}
