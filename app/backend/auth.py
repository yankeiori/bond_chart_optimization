"""Google でのログイン。

/auth/login/<provider> → Google の同意画面 → /auth/callback/<provider> で
そのサービスのユーザーIDを受け取り、ユーザーを作ってセッションに入れる。
ログイン後・ログアウト後は絆ランク管理ページに戻る。
"""

import logging

from authlib.integrations.flask_client import OAuth
from flask import abort, redirect, session, url_for

from app import app
from app.backend.accounts import (
    delete_user,
    enabled_providers,
    login_user,
    provider_credentials,
    session_user_id,
)

_logger = logging.getLogger(__name__)

server = app.server
oauth = OAuth(server)

# ログイン・ログアウト後の戻り先
_RETURN_PATH = "/bond-ranks"

# OAuth 設定。ユーザーIDだけが取れる最小のスコープにする。
_REGISTER_KWARGS = {
    # OpenID Connect。ID トークンの sub がユーザーID。
    "google": dict(
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid"},
    ),
}


def _subject(provider: str, client, token) -> str:
    """アクセストークンから、そのサービスでの不変のユーザーIDを取り出す。"""
    if provider == "google":
        return str(token["userinfo"]["sub"])
    raise ValueError(provider)


for _provider in enabled_providers():
    _client_id, _client_secret = provider_credentials(_provider)
    oauth.register(
        _provider,
        client_id=_client_id,
        client_secret=_client_secret,
        **_REGISTER_KWARGS[_provider],
    )


def _client(provider: str):
    client = oauth.create_client(provider) if provider in _REGISTER_KWARGS else None
    if client is None:
        abort(404)
    return client


@server.route("/auth/login/<provider>")
def auth_login(provider):
    client = _client(provider)
    redirect_uri = url_for("auth_callback", provider=provider, _external=True)
    return client.authorize_redirect(redirect_uri)


@server.route("/auth/callback/<provider>")
def auth_callback(provider):
    client = _client(provider)
    try:
        token = client.authorize_access_token()
        subject = _subject(provider, client, token)
        user_id = login_user(provider, subject)
    except Exception:
        # 同意画面でキャンセルした場合もここに来る
        _logger.exception("login via %s failed", provider)
        session["auth_error"] = "ログインできませんでした。もう一度お試しください。"
        return redirect(_RETURN_PATH)
    session.clear()
    session["user_id"] = user_id
    session.permanent = True
    return redirect(_RETURN_PATH)


@server.route("/auth/logout")
def auth_logout():
    # セッションを空にすると Cookie ごと削除される
    session.clear()
    return redirect(_RETURN_PATH)


@server.route("/auth/delete", methods=["POST"])
def auth_delete():
    """ログイン中のユーザーと保存データを削除してログアウトする。

    セッション Cookie は SameSite=Lax なので、他サイトからの POST では
    Cookie が送られず削除されない。
    """
    user_id = session_user_id()
    if user_id is not None:
        delete_user(user_id)
    session.clear()
    return redirect(_RETURN_PATH)
