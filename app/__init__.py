import mimetypes
import os
import sys
from datetime import timedelta
from pathlib import Path

from dash import Dash
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.caching import stabilize_mtimes, use_version_only_fingerprint

# Python 3.12 の mimetypes は .webp を知らない環境があり（OS の mime.types 次第）、
# 生徒画像が application/octet-stream で配信されてしまうため登録しておく。
mimetypes.add_type("image/webp", ".webp")

# PyInstaller バンドル時は _MEIPASS、通常時はプロジェクトルート
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys._MEIPASS)
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent

# デプロイのたびに JS・CSS・画像の URL や ETag が変わり、再訪者が取り直すのを防ぐ
# （app/caching.py）。mtime の書き換えは本番（PORT がある gunicorn/Render）だけで行い、
# 手元の作業ツリーには触れない。
use_version_only_fingerprint()
if "PORT" in os.environ:
    stabilize_mtimes(_BASE_DIR / "assets")

# flask-compress の設定は Dash(compress=True) の初期化時に読まれるので、Flask を
# 先に作って設定しておく。
_server = Flask(__name__)
_server.config.update(
    # flask-compress は圧縮すると ETag に ":br" などを付け、条件付きリクエストを付け直した
    # ETag で判定し直すのは、ここに挙げたエンドポイントのストリーム応答だけ。Dash の
    # /assets を加えないと、再検証が 304 にならず毎回全量を送ってしまう。
    COMPRESS_STREAMING_ENDPOINT_CONDITIONAL=["static", "_dash_assets.static"],
    # リクエスト本文の上限。正規の最大はスクリーンショットの読み取り結果（1000 枚で
    # 約 0.9 MB）。
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
)

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
    server=_server,
    assets_folder=str(_BASE_DIR / "assets"),
    # 管理画面だけで使うスクリプト（admin_*.js）は公開ページで読み込まない
    # （/assets/ からの配信はされる）
    assets_ignore=r"^admin_",
    suppress_callback_exceptions=True,
    # JS・CSS・コールバック応答を gzip/brotli 圧縮して配信する（flask-compress）。
    # 転送量がおおむね 1/4〜1/10 になり、Render の帯域を節約できる。
    compress=True,
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
