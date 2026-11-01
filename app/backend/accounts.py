"""ログインユーザーと、ユーザーごとの絆ランク管理データの保存。

ログインは Google の OAuth (OpenID Connect) で行い、
保存するのは「どのサービスの、どのアカウントか」（provider と、そのサービスの
不変のユーザーID = subject）だけ。メールアドレスや表示名は受け取っても保存しない。
ログイン中のユーザーは Flask セッションの user_id で識別する。

各サービスは CLIENT_ID / CLIENT_SECRET の環境変数が両方あるときだけ有効になる
（PROVIDERS 参照）。DATABASE_URL が無いとログイン機能は使えない。
"""

import logging
import os
import threading
from contextlib import contextmanager

from flask import has_request_context, session

from app.backend.bond_ranks import bond_ranks_data, normalize_bond_ranks

_logger = logging.getLogger(__name__)

_DATABASE_URL = os.environ.get("DATABASE_URL")

# 1ユーザーが保存できる衣装数の上限（衣装は数百件なので十分な余裕を持たせる）。
MAX_ENTRIES = 2000

# provider 名 → (表示名, 環境変数の接頭辞)。ボタンはこの順に並べる。
PROVIDERS = {
    "google": ("Google", "GOOGLE"),
}


def provider_credentials(provider: str) -> tuple[str, str] | None:
    """provider の (client_id, client_secret)。未設定なら None。"""
    if provider not in PROVIDERS:
        return None
    prefix = PROVIDERS[provider][1]
    client_id = os.environ.get(f"{prefix}_CLIENT_ID", "")
    client_secret = os.environ.get(f"{prefix}_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


def enabled_providers() -> list[str]:
    """ログインに使えるサービス（DB 未設定なら空）。"""
    if not _DATABASE_URL:
        return []
    return [p for p in PROVIDERS if provider_credentials(p) is not None]


def provider_label(provider: str) -> str:
    return PROVIDERS.get(provider, (provider, ""))[0]


# ======================================================================
# PostgreSQL（スレッドごとに接続を使い分けるため接続プールを使う）
# ======================================================================

_pool = None
_pool_lock = threading.Lock()
_tables_ready = False


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            from psycopg2.pool import ThreadedConnectionPool

            _pool = ThreadedConnectionPool(1, 4, _DATABASE_URL)
        return _pool


@contextmanager
def _cursor():
    """プールの接続でトランザクションを1つ実行するカーソル。

    切れた接続（DB 側のアイドル切断など）はプールに戻さず捨てる。
    """
    import psycopg2

    pool = _get_pool()
    conn = pool.getconn()
    broken = False
    try:
        with conn:
            with conn.cursor() as cur:
                yield cur
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        broken = True
        raise
    finally:
        pool.putconn(conn, close=broken or bool(conn.closed))


def _ensure_tables() -> None:
    global _tables_ready
    if _tables_ready:
        return
    with _cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_users (
                id            BIGSERIAL PRIMARY KEY,
                provider      TEXT NOT NULL,
                subject       TEXT NOT NULL,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_login_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (provider, subject)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_bond_ranks (
                user_id    BIGINT PRIMARY KEY
                           REFERENCES app_users (id) ON DELETE CASCADE,
                data       JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
    _tables_ready = True


def login_user(provider: str, subject: str) -> int:
    """(provider, subject) のユーザーを（無ければ作って）返す。Returns user_id。"""
    _ensure_tables()
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_users (provider, subject) VALUES (%s, %s)
            ON CONFLICT (provider, subject) DO UPDATE SET last_login_at = now()
            RETURNING id
            """,
            (provider, subject),
        )
        return cur.fetchone()[0]


def get_user(user_id: int) -> dict | None:
    """{"id", "provider", "subject"}。削除済みなら None。"""
    _ensure_tables()
    with _cursor() as cur:
        cur.execute(
            "SELECT id, provider, subject FROM app_users WHERE id = %s", (user_id,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"id": row[0], "provider": row[1], "subject": row[2]}


def delete_user(user_id: int) -> None:
    """ユーザーと保存データを削除する。"""
    _ensure_tables()
    with _cursor() as cur:
        cur.execute("DELETE FROM app_users WHERE id = %s", (user_id,))


def load_user_bond_ranks(user_id: int) -> dict | None:
    """保存済みの絆ランク管理データ。まだ一度も保存していなければ None。"""
    _ensure_tables()
    with _cursor() as cur:
        cur.execute("SELECT data FROM user_bond_ranks WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return bond_ranks_data(normalize_bond_ranks(row[0]))


def save_user_bond_ranks(user_id: int, data) -> dict:
    """絆ランク管理データを検証して保存する。Returns 保存した値。"""
    import psycopg2.extras

    saved = bond_ranks_data(normalize_bond_ranks(data)[:MAX_ENTRIES])
    _ensure_tables()
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_bond_ranks (user_id, data) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET data = EXCLUDED.data, updated_at = now()
            """,
            (user_id, psycopg2.extras.Json(saved)),
        )
    return saved


def load_all_user_bond_ranks() -> list[dict]:
    """全ユーザーと保存データ（管理画面の利用状況の集計用）。

    Returns [{"id", "is_admin", "created_at", "last_login_at", "updated_at",
    "entries"}, ...]。保存したことが無ければ updated_at は None・entries は空。
    subject は返さず、管理者のアカウントかどうかだけを is_admin で返す。
    """
    _ensure_tables()
    with _cursor() as cur:
        cur.execute(
            """
            SELECT u.id, u.provider, u.subject, u.created_at, u.last_login_at,
                   b.updated_at, b.data
            FROM app_users u LEFT JOIN user_bond_ranks b ON b.user_id = u.id
            ORDER BY u.id
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": uid,
            "is_admin": is_admin({"provider": provider, "subject": subject}),
            "created_at": created_at,
            "last_login_at": last_login_at,
            "updated_at": updated_at,
            "entries": normalize_bond_ranks(data),
        }
        for uid, provider, subject, created_at, last_login_at, updated_at, data in rows
    ]


# ======================================================================
# セッション
# ======================================================================


def session_user_id() -> int | None:
    """セッションのログインユーザーID（DB は見ない）。"""
    if not has_request_context():
        return None
    uid = session.get("user_id")
    return uid if isinstance(uid, int) else None


def pop_auth_error() -> str | None:
    """ログイン失敗のメッセージ（auth.py が入れる）を1回だけ取り出す。"""
    if not has_request_context():
        return None
    return session.pop("auth_error", None)


def current_user() -> dict | None:
    """ログイン中のユーザー {"id", "provider", "subject"}。

    未ログイン・削除済み・DB に接続できないときは None（削除済みなら
    セッションからも消す）。
    """
    uid = session_user_id()
    if uid is None or not _DATABASE_URL:
        return None
    try:
        user = get_user(uid)
    except Exception:
        _logger.exception("failed to load user %s", uid)
        return None
    if user is None:
        session.pop("user_id", None)
    return user


# ======================================================================
# 管理者
# ======================================================================


def admin_google_sub() -> str:
    """管理者の Google アカウントの subject（ADMIN_GOOGLE_SUB）。未設定なら空。"""
    return os.environ.get("ADMIN_GOOGLE_SUB", "").strip()


def is_admin(user: dict | None) -> bool:
    """user（current_user の値）が管理者の Google アカウントか。"""
    admin_sub = admin_google_sub()
    return (
        bool(admin_sub)
        and user is not None
        and user.get("provider") == "google"
        and user.get("subject") == admin_sub
    )
