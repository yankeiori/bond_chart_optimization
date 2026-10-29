"""プリセットの管理。

DATABASE_URL が設定されている場合は PostgreSQL を使用し、
未設定の場合は JSON ファイルにフォールバックする（ローカル開発用）。
全プリセット（旧ビルトイン含む）を DB で一元管理する。
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import quote

_logger = logging.getLogger(__name__)

_DATABASE_URL = os.environ.get("DATABASE_URL")

# ======================================================================
# JSON ファイルバックエンド (ローカル開発用フォールバック)
# ======================================================================

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _BASE_DIR / "data"
_JSON_PATH = _DATA_DIR / "user_presets.json"
_lock = threading.Lock()


def _json_read() -> dict:
    if not _JSON_PATH.exists():
        return {}
    with open(_JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("presets", {})


def _json_write(presets: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump({"presets": presets}, f, ensure_ascii=False, indent=2)


# ======================================================================
# PostgreSQL バックエンド
# ======================================================================

_conn = None


def _get_conn():
    """PostgreSQL 接続を取得する（再接続対応）。"""
    global _conn
    import psycopg2

    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(_DATABASE_URL)
        _conn.autocommit = True
    return _conn


def _ensure_table() -> None:
    """テーブルが存在しなければ作成する。"""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_presets (
                key            TEXT PRIMARY KEY,
                character_name TEXT NOT NULL,
                costumes       JSONB NOT NULL,
                approved       BOOLEAN NOT NULL DEFAULT FALSE,
                submitted_at   TEXT NOT NULL
            )
        """)


def _ensure_preset_approval() -> None:
    """(生徒名, ステータス名) ごとの承認フラグ用テーブルを用意する。

    プリセット1件 = (生徒名, ステータス名) なので student_priority と
    同じ粒度で管理する。新規ユーザー投稿は未承認(FALSE)、それ以外の
    既存データはマイグレーション時に承認済み(TRUE)として埋める。
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preset_approval (
                student_name TEXT NOT NULL,
                status_name  TEXT NOT NULL,
                approved     BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (student_name, status_name)
            )
        """)
        # 既存プリセット(costume⨝bond_bonus に存在するが未登録の組)は
        # 承認済みとして埋める。ユーザー投稿で既に FALSE 登録済みの組は
        # ON CONFLICT DO NOTHING で保持される。
        try:
            cur.execute("""
                INSERT INTO preset_approval (student_name, status_name, approved)
                SELECT DISTINCT c.student_name, bb.status_name, TRUE
                FROM costume c
                JOIN bond_bonus bb ON bb.costume_id = c.id
                ON CONFLICT (student_name, status_name) DO NOTHING
            """)
        except Exception:
            # costume / bond_bonus 未作成の環境ではバックフィルをスキップ。
            _logger.exception("preset_approval backfill skipped")


def _ensure_present_table() -> None:
    """衣装ごとの好み贈り物テーブル (present) を用意する。

    本番では既存のため CREATE TABLE IF NOT EXISTS は no-op。ローカル
    開発で costume だけ作られている環境向けに冪等で作成する。
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS present (
                    id         SERIAL PRIMARY KEY,
                    costume_id INTEGER NOT NULL
                        REFERENCES costume(id) ON DELETE CASCADE,
                    gift_id    TEXT NOT NULL,
                    gift_name  TEXT NOT NULL,
                    gift_type  TEXT NOT NULL,
                    tier       TEXT NOT NULL,
                    UNIQUE (costume_id, gift_id)
                )
            """)
        except Exception:
            # costume 未作成の環境では作成をスキップ。
            _logger.exception("present table creation skipped")


def _ensure_furniture_tables() -> None:
    """モーション家具 (furniture / costume_furniture) テーブルを用意する。

    furniture.id は SchaleDB の家具 ID。データは
    scripts/import_furniture.py で SchaleDB から取り込む。
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS furniture (
                    id   INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS costume_furniture (
                    costume_id   INTEGER NOT NULL
                        REFERENCES costume(id) ON DELETE CASCADE,
                    furniture_id INTEGER NOT NULL
                        REFERENCES furniture(id) ON DELETE CASCADE,
                    PRIMARY KEY (costume_id, furniture_id)
                )
            """)
        except Exception:
            # costume 未作成の環境では作成をスキップ。
            _logger.exception("furniture table creation skipped")


if _DATABASE_URL:
    try:
        _ensure_table()
        _ensure_preset_approval()
        _ensure_present_table()
        _ensure_furniture_tables()
        _logger.info("PostgreSQL backend initialized")
    except Exception:
        _logger.exception("Failed to initialize user_presets table")


# ======================================================================
# 公開 API
# ======================================================================


def load_user_presets() -> dict:
    """全プリセットを返す。"""
    if _DATABASE_URL:
        try:
            conn = _get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT key, character_name, costumes, approved, submitted_at "
                    "FROM user_presets"
                )
                rows = cur.fetchall()
            return {
                row[0]: {
                    "character_name": row[1],
                    "costumes": row[2],
                    "approved": row[3],
                    "submitted_at": row[4],
                }
                for row in rows
            }
        except Exception:
            _logger.exception("DB read error")
            return {}
    else:
        with _lock:
            return _json_read()


def save_user_preset(character_name: str, costumes: list[dict]) -> str:
    """プリセットを保存する。生成されたキーを返す。"""
    key = f"{character_name}_{int(time.time())}"
    submitted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if _DATABASE_URL:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_presets (key, character_name, costumes, approved, submitted_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (key, character_name, json.dumps(costumes), False, submitted_at),
            )
    else:
        with _lock:
            presets = _json_read()
            presets[key] = {
                "character_name": character_name,
                "costumes": costumes,
                "approved": False,
                "submitted_at": submitted_at,
            }
            _json_write(presets)
    return key


def approve_preset(key: str) -> bool:
    """プリセットを承認する。"""
    if _DATABASE_URL:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_presets SET approved = TRUE WHERE key = %s", (key,)
            )
            return cur.rowcount > 0
    else:
        with _lock:
            presets = _json_read()
            if key not in presets:
                return False
            presets[key]["approved"] = True
            _json_write(presets)
        return True


def delete_preset(key: str) -> bool:
    """プリセットを削除する。"""
    if _DATABASE_URL:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_presets WHERE key = %s", (key,))
            return cur.rowcount > 0
    else:
        with _lock:
            presets = _json_read()
            if key not in presets:
                return False
            del presets[key]
            _json_write(presets)
        return True


# ======================================================================
# ドロップダウン用ヘルパー
# ======================================================================


# ドロップダウン選択肢はページ表示のたびに DB へ往復しないよう
# 短時間キャッシュする。プリセット投稿・管理画面での編集時は
# _invalidate_options_cache() で即時反映させる（別プロセスの
# キャッシュは TTL まで古いままになり得る）。
_OPTIONS_CACHE_TTL = 300.0  # 秒
_options_cache: dict[str, tuple[float, object]] = {}


def _cached_options(key: str, loader):
    now = time.time()
    hit = _options_cache.get(key)
    if hit is not None and now - hit[0] < _OPTIONS_CACHE_TTL:
        return hit[1]
    options = loader()
    if options:  # 空（DBエラー等）はキャッシュしない
        _options_cache[key] = (now, options)
    return options


def _invalidate_options_cache() -> None:
    _options_cache.clear()


def _kata_to_hira(text: str) -> str:
    """カタカナをひらがなに変換する。"""
    return "".join(chr(ord(c) - 0x60) if "\u30a1" <= c <= "\u30f6" else c for c in text)


def _search_text(name: str) -> str:
    """検索用テキスト（カタカナ + ひらがな）を生成する。"""
    hira = _kata_to_hira(name)
    return f"{name} {hira}" if hira != name else name


# --- 新スキーマ (costume ⨝ bond_bonus) からの読み込み ---

# ドロップダウン値の区切り文字（生徒名・ステータス名には出現しない）。
_PRESET_VALUE_SEP = "\x1f"

# ステータス名の選択肢。
VALID_STATUS_NAMES = ("攻撃", "HP", "治癒力", "防御")


def preset_exists(student_name: str, status_name: str) -> bool:
    """(生徒名, ステータス名) が登録済みかを返す。"""
    if not _DATABASE_URL:
        return False
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM costume c "
                "JOIN bond_bonus bb ON bb.costume_id = c.id "
                "WHERE c.student_name = %s AND bb.status_name = %s LIMIT 1",
                (student_name, status_name),
            )
            return cur.fetchone() is not None
    except Exception:
        _logger.exception("DB read error")
        return False


def register_costume_preset(
    student_name: str, status_name: str, costumes: list[dict]
) -> None:
    """新スキーマ (costume + bond_bonus) へプリセットを登録する。

    既存の (生徒名, 衣装名) は再利用し、(衣装, ステータス名) の
    bond_bonuses を追加する。
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        for sort_order, c in enumerate(costumes):
            cur.execute(
                "INSERT INTO costume (student_name, costume_name, sort_order) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (student_name, costume_name) "
                "DO UPDATE SET costume_name = EXCLUDED.costume_name "
                "RETURNING id",
                (student_name, c["costume_name"], sort_order),
            )
            costume_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO bond_bonus (costume_id, status_name, bond_bonuses) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (costume_id, status_name) DO NOTHING",
                (costume_id, status_name, list(c["bond_bonuses"])),
            )
        # ユーザー投稿は未承認(FALSE)。既存登録があれば現状の承認状態を保持。
        cur.execute(
            "INSERT INTO preset_approval (student_name, status_name, approved) "
            "VALUES (%s, %s, FALSE) "
            "ON CONFLICT (student_name, status_name) DO NOTHING",
            (student_name, status_name),
        )
    _invalidate_options_cache()


# DB接続の有無（UI側でフォールバック時の挙動を切り替える用）。
HAS_DB = bool(_DATABASE_URL)


def _preset_label(student_name: str, status_name: str) -> str:
    """表示名。ステータスが既定の「攻撃」なら生徒名のみ、それ以外は括弧付き。"""
    if status_name == "攻撃":
        return student_name
    return f"{student_name}({status_name})"


def make_preset_value(student_name: str, status_name: str) -> str:
    """(生徒名, ステータス名) をドロップダウン値に結合する。"""
    return f"{student_name}{_PRESET_VALUE_SEP}{status_name}"


def preset_label_for_value(dropdown_value: str) -> str:
    """結合値の表示名を返す。分解できない値はそのまま返す。"""
    parsed = parse_preset_value(dropdown_value)
    if not parsed:
        return dropdown_value
    return _preset_label(*parsed)


def parse_preset_value(dropdown_value: str) -> tuple[str, str] | None:
    """ドロップダウン値を (生徒名, ステータス名) に分解する。"""
    if not dropdown_value or _PRESET_VALUE_SEP not in dropdown_value:
        return None
    student_name, status_name = dropdown_value.split(_PRESET_VALUE_SEP, 1)
    return student_name, status_name


def _load_costume_grouped() -> dict[tuple[str, str], list[dict]]:
    """costume と bond_bonus を結合し、(生徒名, ステータス名) ごとに
    [{costume_name, bond_bonuses}, ...] へまとめて返す。"""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.student_name, bb.status_name, c.costume_name, bb.bond_bonuses "
            "FROM costume c "
            "JOIN bond_bonus bb ON bb.costume_id = c.id "
            "LEFT JOIN student_priority sp ON sp.student_name = c.student_name "
            "ORDER BY COALESCE(sp.priority, 1000000), c.student_name, "
            "bb.status_name, c.sort_order, c.id"
        )
        rows = cur.fetchall()
    grouped: dict[tuple[str, str], list[dict]] = {}
    for student_name, status_name, costume_name, bond_bonuses in rows:
        grouped.setdefault((student_name, status_name), []).append(
            {
                "costume_name": costume_name,
                "bond_bonuses": list(bond_bonuses),
            }
        )
    return grouped


def _load_approval_map() -> dict[tuple[str, str], bool]:
    """(生徒名, ステータス名) -> 承認済みか の辞書を返す。

    未登録の組はテーブル作成時のバックフィルで承認済みになる想定だが、
    取得失敗時も安全側（承認済み扱い）に倒すため呼び出し側で
    dict.get(..., True) する。
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT student_name, status_name, approved FROM preset_approval")
        return {(r[0], r[1]): r[2] for r in cur.fetchall()}


def get_all_presets_for_dropdown() -> list[dict]:
    """全プリセットをドロップダウン用に返す。

    プリセット1件 = (生徒名, ステータス名) の組。
    """
    if not _DATABASE_URL:
        # JSON フォールバック (旧形式)
        options = []
        for key, entry in load_user_presets().items():
            char_name = entry["character_name"]
            label = (
                char_name if entry.get("approved") else f"{char_name} [ユーザー投稿]"
            )
            options.append(
                {"label": label, "value": key, "search": _search_text(char_name)}
            )
        return options

    try:
        grouped = _load_costume_grouped()
    except Exception:
        _logger.exception("DB read error")
        return []
    try:
        approval = _load_approval_map()
    except Exception:
        _logger.exception("DB read error (approval)")
        approval = {}
    options = []
    for student_name, status_name in grouped:
        base_label = _preset_label(student_name, status_name)
        approved = approval.get((student_name, status_name), True)
        label = base_label if approved else f"{base_label} [未承認]"
        options.append(
            {
                "label": label,
                "value": f"{student_name}{_PRESET_VALUE_SEP}{status_name}",
                "search": _search_text(base_label),
            }
        )
    return options


def _load_student_options() -> list[dict]:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT c.student_name, COALESCE(sp.priority, 1000000) "
                "FROM costume c "
                "JOIN bond_bonus bb ON bb.costume_id = c.id "
                "LEFT JOIN student_priority sp ON sp.student_name = c.student_name "
                "ORDER BY COALESCE(sp.priority, 1000000), c.student_name"
            )
            rows = cur.fetchall()
    except Exception:
        _logger.exception("DB read error")
        return []
    return [{"label": r[0], "value": r[0], "search": _search_text(r[0])} for r in rows]


def get_student_options() -> list[dict]:
    """生徒選択ドロップダウン用のオプションを返す（短時間キャッシュ）。

    値は生徒名。表示は優先度 (student_priority) 順 → 生徒名順。
    DB未接続時は旧形式（キー単位）のオプションを返す。
    """
    if not _DATABASE_URL:
        return get_all_presets_for_dropdown()
    return _cached_options("students", _load_student_options)


def _costume_label(student_name: str, costume_name: str) -> str:
    """生徒（衣装）の表示名。既定の「通常」衣装は生徒名のみ。"""
    if costume_name == "通常":
        return student_name
    return f"{student_name}（{costume_name}）"


def _load_costume_options() -> list[dict]:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.id, c.student_name, c.costume_name FROM costume c "
                "LEFT JOIN student_priority sp ON sp.student_name = c.student_name "
                "ORDER BY COALESCE(sp.priority, 1000000), c.student_name, "
                "c.sort_order, c.id"
            )
            rows = cur.fetchall()
    except Exception:
        _logger.exception("DB read error")
        return []
    return [
        {
            "label": _costume_label(r[1], r[2]),
            "value": r[0],
            "search": _search_text(f"{r[1]} {r[2]}"),
        }
        for r in rows
    ]


def get_costume_options() -> list[dict]:
    """生徒（衣装）選択ドロップダウン用のオプションを返す（短時間キャッシュ）。

    値は costume.id。表示は優先度 (student_priority) 順 → 生徒名順 →
    衣装の定義順。DB未接続時は空リスト。
    """
    if not _DATABASE_URL:
        return []
    return _cached_options("costumes", _load_costume_options)


def get_costume_label(costume_id) -> str | None:
    """costume.id から 生徒（衣装） の表示名を返す。見つからなければ None。"""
    if not _DATABASE_URL or costume_id is None:
        return None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT student_name, costume_name FROM costume WHERE id = %s",
                (int(costume_id),),
            )
            row = cur.fetchone()
    except Exception:
        _logger.exception("DB read error")
        return None
    if not row:
        return None
    return _costume_label(row[0], row[1])


def _load_costume_present_map(costume_id) -> dict[str, str]:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT gift_id, tier FROM present WHERE costume_id = %s",
                (int(costume_id),),
            )
            return {r[0]: r[1] for r in cur.fetchall()}
    except Exception:
        _logger.exception("DB read error")
        return {}


def get_costume_present_map(costume_id) -> dict[str, str]:
    """衣装の present を {gift_id: tier} で返す（短時間キャッシュ）。

    get_preset_present の1衣装分と同形式。DB未接続・未登録時は空辞書
    （= 好み無し。選択ボックスは通常 normal の 20 EXP 扱い）。
    """
    if not _DATABASE_URL or costume_id is None:
        return {}
    return _cached_options(
        f"present:{int(costume_id)}",
        lambda: _load_costume_present_map(costume_id),
    )


def get_status_options_for(student_name: str) -> list[dict]:
    """指定生徒が持つステータスの選択肢を返す。

    表示順は VALID_STATUS_NAMES。未承認プリセットには [未承認] を付ける。
    """
    if not _DATABASE_URL or not student_name:
        return []
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT bb.status_name FROM costume c "
                "JOIN bond_bonus bb ON bb.costume_id = c.id "
                "WHERE c.student_name = %s",
                (student_name,),
            )
            statuses = {r[0] for r in cur.fetchall()}
            cur.execute(
                "SELECT status_name, approved FROM preset_approval "
                "WHERE student_name = %s",
                (student_name,),
            )
            approval = {r[0]: r[1] for r in cur.fetchall()}
    except Exception:
        _logger.exception("DB read error")
        return []
    options = []
    for status in VALID_STATUS_NAMES:
        if status not in statuses:
            continue
        label = status if approval.get(status, True) else f"{status} [未承認]"
        options.append({"label": label, "value": status})
    return options


def get_favorite_options(favorites: list[str]) -> list[dict]:
    """お気に入り（結合値）をドロップダウンの先頭に出すオプションを返す。"""
    options = []
    for value in favorites:
        label = preset_label_for_value(value)
        options.append(
            {"label": f"★ {label}", "value": value, "search": _search_text(label)}
        )
    return options


def get_preset_data(dropdown_value: str) -> tuple[str, list[dict]] | None:
    """ドロップダウン値からプリセットデータを取得する。

    Returns
    -------
    tuple[str, list[dict]] | None
        (表示名, [{costume_name, bond_bonuses}, ...]) のタプル。
        見つからなければ None。
    """
    if not _DATABASE_URL:
        presets = load_user_presets()
        entry = presets.get(dropdown_value)
        if entry:
            return (entry["character_name"], entry["costumes"])
        return None

    if _PRESET_VALUE_SEP not in dropdown_value:
        return None
    student_name, status_name = dropdown_value.split(_PRESET_VALUE_SEP, 1)
    try:
        grouped = _load_costume_grouped()
    except Exception:
        _logger.exception("DB read error")
        return None
    costumes = grouped.get((student_name, status_name))
    if not costumes:
        return None
    return (_preset_label(student_name, status_name), costumes)


# ======================================================================
# 管理画面用 (costume / bond_bonus / student_priority の編集)
# ======================================================================


def admin_load_presets() -> list[dict]:
    """(生徒名, ステータス名) ごとに編集用データを返す。"""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.student_name, bb.status_name, c.id, c.costume_name, "
            "c.sort_order, bb.bond_bonuses, COALESCE(pa.approved, TRUE) "
            "FROM costume c "
            "JOIN bond_bonus bb ON bb.costume_id = c.id "
            "LEFT JOIN student_priority sp ON sp.student_name = c.student_name "
            "LEFT JOIN preset_approval pa "
            "ON pa.student_name = c.student_name "
            "AND pa.status_name = bb.status_name "
            "ORDER BY COALESCE(sp.priority, 1000000), c.student_name, "
            "bb.status_name, c.sort_order, c.id"
        )
        rows = cur.fetchall()
    grouped: dict[tuple[str, str], dict] = {}
    for sn, st, cid, cname, so, bb, approved in rows:
        g = grouped.setdefault(
            (sn, st),
            {
                "student_name": sn,
                "status_name": st,
                "approved": approved,
                "costumes": [],
            },
        )
        g["costumes"].append(
            {
                "costume_id": cid,
                "costume_name": cname,
                "sort_order": so,
                "bond_bonuses": list(bb),
            }
        )
    return list(grouped.values())


def admin_load_priorities() -> list[dict]:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT student_name, priority FROM student_priority ORDER BY priority"
        )
        return [{"student_name": r[0], "priority": r[1]} for r in cur.fetchall()]


def admin_rebuild_preset(
    old_student: str,
    old_status: str,
    new_student: str,
    new_status: str,
    costumes: list[dict],
) -> None:
    """(生徒, ステータス) プリセットをフォーム内容で再構築する。

    共有 costume 行は再利用し、対象ステータスの bond_bonus のみ入れ替える。
    どのステータスからも参照されない costume 行は削除する。
    """
    conn = _get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM bond_bonus bb USING costume c "
                "WHERE bb.costume_id = c.id "
                "AND c.student_name = %s AND bb.status_name = %s",
                (old_student, old_status),
            )
            for i, c in enumerate(costumes):
                cur.execute(
                    "INSERT INTO costume (student_name, costume_name, sort_order) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (student_name, costume_name) "
                    "DO UPDATE SET sort_order = EXCLUDED.sort_order "
                    "RETURNING id",
                    (new_student, c["costume_name"], i),
                )
                costume_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO bond_bonus "
                    "(costume_id, status_name, bond_bonuses) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (costume_id, status_name) "
                    "DO UPDATE SET bond_bonuses = EXCLUDED.bond_bonuses",
                    (costume_id, new_status, list(c["bond_bonuses"])),
                )
            cur.execute(
                "DELETE FROM costume c "
                "WHERE c.student_name IN (%s, %s) "
                "AND NOT EXISTS "
                "(SELECT 1 FROM bond_bonus bb WHERE bb.costume_id = c.id)",
                (old_student, new_student),
            )
            if old_student != new_student:
                cur.execute(
                    "UPDATE student_priority SET student_name = %s "
                    "WHERE student_name = %s "
                    "AND NOT EXISTS "
                    "(SELECT 1 FROM student_priority WHERE student_name = %s)",
                    (new_student, old_student, new_student),
                )
            # 承認状態を引き継ぐ。既存登録があればその値を保持し
            # (管理者の編集・保存では承認状態を変えない)、
            # 未登録(=管理者の新規追加・既存マイグレ漏れ)は承認済み扱い。
            cur.execute(
                "SELECT approved FROM preset_approval "
                "WHERE student_name = %s AND status_name = %s",
                (old_student, old_status),
            )
            row = cur.fetchone()
            approved = row[0] if row else True
            if (old_student, old_status) != (new_student, new_status):
                cur.execute(
                    "DELETE FROM preset_approval "
                    "WHERE student_name = %s AND status_name = %s",
                    (old_student, old_status),
                )
            cur.execute(
                "INSERT INTO preset_approval "
                "(student_name, status_name, approved) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (student_name, status_name) "
                "DO UPDATE SET approved = EXCLUDED.approved",
                (new_student, new_status, approved),
            )
        conn.commit()
        _invalidate_options_cache()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def admin_add_costume_preset(
    student_name: str, costume_name: str, bonuses_by_status: dict[str, list[int]]
) -> None:
    """1衣装分の bond_bonus をステータスごとに登録する（既存なら上書き）。

    新規衣装はその生徒の末尾に並べ、既存衣装は sort_order を保持する。
    承認状態は既存登録があれば保持し、未登録なら承認済みで作成する。
    """
    conn = _get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO costume (student_name, costume_name, sort_order) "
                "SELECT %s, %s, COALESCE(MAX(sort_order) + 1, 0) "
                "FROM costume WHERE student_name = %s "
                "ON CONFLICT (student_name, costume_name) "
                "DO UPDATE SET costume_name = EXCLUDED.costume_name "
                "RETURNING id",
                (student_name, costume_name, student_name),
            )
            costume_id = cur.fetchone()[0]
            for status_name, bonuses in bonuses_by_status.items():
                cur.execute(
                    "INSERT INTO bond_bonus "
                    "(costume_id, status_name, bond_bonuses) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (costume_id, status_name) "
                    "DO UPDATE SET bond_bonuses = EXCLUDED.bond_bonuses",
                    (costume_id, status_name, list(bonuses)),
                )
                cur.execute(
                    "INSERT INTO preset_approval "
                    "(student_name, status_name, approved) "
                    "VALUES (%s, %s, TRUE) "
                    "ON CONFLICT (student_name, status_name) DO NOTHING",
                    (student_name, status_name),
                )
        conn.commit()
        _invalidate_options_cache()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def admin_delete_preset(student: str, status: str) -> None:
    conn = _get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM bond_bonus bb USING costume c "
                "WHERE bb.costume_id = c.id "
                "AND c.student_name = %s AND bb.status_name = %s",
                (student, status),
            )
            cur.execute(
                "DELETE FROM costume c "
                "WHERE c.student_name = %s "
                "AND NOT EXISTS "
                "(SELECT 1 FROM bond_bonus bb WHERE bb.costume_id = c.id)",
                (student,),
            )
            cur.execute(
                "DELETE FROM preset_approval "
                "WHERE student_name = %s AND status_name = %s",
                (student, status),
            )
        conn.commit()
        _invalidate_options_cache()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def admin_set_preset_approved(student: str, status: str, approved: bool) -> None:
    """(生徒名, ステータス名) プリセットの承認状態を設定する。"""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO preset_approval (student_name, status_name, approved) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (student_name, status_name) "
            "DO UPDATE SET approved = EXCLUDED.approved",
            (student, status, approved),
        )


def admin_upsert_priority(student: str, priority: int) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO student_priority (student_name, priority) "
            "VALUES (%s, %s) "
            "ON CONFLICT (student_name) DO UPDATE SET priority = EXCLUDED.priority",
            (student, priority),
        )
    _invalidate_options_cache()


def admin_delete_priority(student: str) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM student_priority WHERE student_name = %s", (student,))
    _invalidate_options_cache()


# ======================================================================
# 贈り物 (gift / present) — 贈り物配分シミュレータ用
# ======================================================================


# 贈り物カタログはほぼ不変のため短時間キャッシュし、ページ表示・
# プリセット読み込みのたびに DB へ往復しないようにする。
_gifts_cache: list[dict] | None = None
_gifts_cache_at = 0.0
_GIFTS_CACHE_TTL = 300.0  # 秒。DB 直編集の反映はこの時間まで遅延し得る。


def load_gifts() -> list[dict]:
    """全贈り物を定義順で返す。[{id, name, gift_type}, ...]"""
    global _gifts_cache, _gifts_cache_at
    if not _DATABASE_URL:
        return []
    now = time.time()
    if _gifts_cache is not None and now - _gifts_cache_at < _GIFTS_CACHE_TTL:
        return _gifts_cache
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, gift_type FROM gift ORDER BY sort_order")
            gifts = [
                {"id": r[0], "name": r[1], "gift_type": r[2]} for r in cur.fetchall()
            ]
        _gifts_cache, _gifts_cache_at = gifts, now
        return gifts
    except Exception:
        _logger.exception("DB read error")
        return []


def gift_image_src(gift: dict) -> str:
    """贈り物アイコンの URL。ファイル名は gift.name（日本語可）。

    日本語名を URL に含めるためパーセントエンコードする。画像ファイル
    (assets/gift/<name>.png) のファイル名は DB の gift.name と一致させる。
    """
    return f"/assets/gift/{quote(gift['name'])}.png"


# ----------------------------------------------------------------------
# 贈り物 → 好物にしている衣装 の逆引き
# ----------------------------------------------------------------------


def _load_gift_lovers(gift_id: str) -> list[dict]:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.student_name, c.costume_name, p.tier "
                "FROM present p "
                "JOIN costume c ON c.id = p.costume_id "
                "LEFT JOIN student_priority sp "
                "  ON sp.student_name = c.student_name "
                "WHERE p.gift_id = %s "
                "ORDER BY COALESCE(sp.priority, 1000000), c.student_name, "
                "c.sort_order, c.id",
                (gift_id,),
            )
            rows = cur.fetchall()
    except Exception:
        _logger.exception("DB read error")
        return []
    return [
        {
            "student_name": r[0],
            "costume_name": r[1],
            "label": _costume_label(r[0], r[1]),
            "tier": r[2],
        }
        for r in rows
    ]


def get_gift_lovers(gift_id: str) -> list[dict]:
    """指定の贈り物を好物にしている衣装を返す（短時間キャッシュ）。

    [{student_name, costume_name, label, tier}, ...] を
    優先度 (student_priority) 順 → 生徒名順 → 衣装の定義順で返す。
    全生徒対象タイプ (*-all) は present に行を持たないため空リスト。
    """
    if not _DATABASE_URL or not gift_id:
        return []
    return _cached_options(f"gift_lovers:{gift_id}", lambda: _load_gift_lovers(gift_id))


def _load_gift_lover_counts() -> dict[str, dict[str, int]]:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT gift_id, tier, COUNT(*) FROM present GROUP BY gift_id, tier"
            )
            out: dict[str, dict[str, int]] = {}
            for gift_id, tier, n in cur.fetchall():
                out.setdefault(gift_id, {})[tier] = n
            return out
    except Exception:
        _logger.exception("DB read error")
        return {}


def get_gift_lover_counts() -> dict[str, dict[str, int]]:
    """{gift_id: {tier: 好物にしている衣装数}} を返す（短時間キャッシュ）。

    present に行が無い贈り物（全生徒対象タイプ等）はキーを持たない。
    0 件の tier もキーを持たないため、参照側は .get(tier, 0) を使う。
    """
    if not _DATABASE_URL:
        return {}
    return _cached_options("gift_lover_counts", _load_gift_lover_counts)


def get_preset_present(
    student_name: str, status_name: str
) -> dict[str, dict[str, str]]:
    """(生徒名, ステータス名) プリセットの present を
    {衣装名: {gift_id: tier}} で返す。"""
    if not _DATABASE_URL:
        return {}
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.costume_name, p.gift_id, p.tier "
                "FROM present p "
                "JOIN costume c ON c.id = p.costume_id "
                "JOIN bond_bonus bb ON bb.costume_id = c.id "
                "WHERE c.student_name = %s AND bb.status_name = %s",
                (student_name, status_name),
            )
            out: dict[str, dict[str, str]] = {}
            for costume_name, gift_id, tier in cur.fetchall():
                out.setdefault(costume_name, {})[gift_id] = tier
            return out
    except Exception:
        _logger.exception("DB read error")
        return {}


def get_preset_furniture(student_name: str, status_name: str) -> dict[str, list[dict]]:
    """(生徒名, ステータス名) プリセットのモーション家具を
    {衣装名: [{name, partners}, ...]} で返す。

    partners は同じ家具にモーションがある他の衣装の表示名
    （優先度 → 生徒名 → 衣装の定義順）。
    """
    if not _DATABASE_URL:
        return {}
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.costume_name, f.id, f.name, "
                "oc.student_name, oc.costume_name "
                "FROM costume c "
                "JOIN bond_bonus bb ON bb.costume_id = c.id "
                "JOIN costume_furniture cf ON cf.costume_id = c.id "
                "JOIN furniture f ON f.id = cf.furniture_id "
                "LEFT JOIN costume_furniture ocf "
                "  ON ocf.furniture_id = f.id AND ocf.costume_id <> c.id "
                "LEFT JOIN costume oc ON oc.id = ocf.costume_id "
                "LEFT JOIN student_priority sp "
                "  ON sp.student_name = oc.student_name "
                "WHERE c.student_name = %s AND bb.status_name = %s "
                "ORDER BY f.id, COALESCE(sp.priority, 1000000), "
                "oc.student_name, oc.sort_order, oc.id",
                (student_name, status_name),
            )
            rows = cur.fetchall()
    except Exception:
        _logger.exception("DB read error")
        return {}
    by_costume: dict[str, dict[int, dict]] = {}
    for costume_name, fid, fname, o_student, o_costume in rows:
        item = by_costume.setdefault(costume_name, {}).setdefault(
            fid, {"name": fname, "partners": []}
        )
        if o_student is not None:
            item["partners"].append(_costume_label(o_student, o_costume))
    return {c: list(items.values()) for c, items in by_costume.items()}


# ----------------------------------------------------------------------
# 管理画面用 (present = 衣装ごとの好み贈り物 の編集)
# ----------------------------------------------------------------------

# present.tier の選択肢（gift_exp._TIER_TO_EFFECTIVITY のキーと一致）。
VALID_PRESENT_TIERS = ("favorite", "superFavorite", "ultraFavorite")


def admin_load_costumes() -> list[dict]:
    """全衣装を表示優先度順で返す。

    present は (生徒, ステータス) ではなく costume 単位。bond_bonus を
    持たない衣装（present のみ／新規挿入した衣装）も含めて列挙する。

    Returns
    -------
    list[dict]
        [{costume_id, student_name, costume_name, present_count}, ...]
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.student_name, c.costume_name, "
            "COUNT(p.gift_id) AS present_count "
            "FROM costume c "
            "LEFT JOIN student_priority sp ON sp.student_name = c.student_name "
            "LEFT JOIN present p ON p.costume_id = c.id "
            "GROUP BY c.id, c.student_name, c.costume_name, c.sort_order, "
            "sp.priority "
            "ORDER BY COALESCE(sp.priority, 1000000), c.student_name, "
            "c.sort_order, c.id"
        )
        return [
            {
                "costume_id": r[0],
                "student_name": r[1],
                "costume_name": r[2],
                "present_count": r[3],
            }
            for r in cur.fetchall()
        ]


def admin_add_costume(student_name: str, costume_name: str) -> int:
    """衣装を新規挿入（既存なら再利用）し、その costume_id を返す。

    present 編集用に、bond_bonus を持たない衣装も作成できる。
    既存の (生徒名, 衣装名) があればその id をそのまま返す。
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO costume (student_name, costume_name, sort_order) "
            "VALUES (%s, %s, 0) "
            "ON CONFLICT (student_name, costume_name) "
            "DO UPDATE SET costume_name = EXCLUDED.costume_name "
            "RETURNING id",
            (student_name, costume_name),
        )
        costume_id = cur.fetchone()[0]
    _invalidate_options_cache()
    return costume_id


def admin_load_present(costume_id: int) -> dict[str, str]:
    """指定衣装の present を {gift_id: tier} で返す。"""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT gift_id, tier FROM present WHERE costume_id = %s",
            (costume_id,),
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def admin_get_costume(costume_id: int) -> dict | None:
    """衣装の (生徒名, 衣装名) を返す。存在しなければ None。"""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT student_name, costume_name FROM costume WHERE id = %s",
            (costume_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"student_name": row[0], "costume_name": row[1]}


def admin_save_present(costume_id: int, mapping: dict[str, str]) -> None:
    """衣装の present をフォーム内容で総入れ替えする。

    mapping: {gift_id: tier}。tier が VALID_PRESENT_TIERS 外の
    エントリは無視する。present.gift_name / gift_type は gift カタログ
    を単一の真実として SELECT で埋める（カタログに無い gift_id は
    挿入されない）。
    """
    conn = _get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM present WHERE costume_id = %s", (costume_id,))
            for gift_id, tier in mapping.items():
                if tier not in VALID_PRESENT_TIERS:
                    continue
                cur.execute(
                    "INSERT INTO present "
                    "(costume_id, gift_id, gift_name, gift_type, tier) "
                    "SELECT %s, g.id, g.name, g.gift_type, %s "
                    "FROM gift g WHERE g.id = %s",
                    (costume_id, tier, gift_id),
                )
        conn.commit()
        _invalidate_options_cache()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


# ----------------------------------------------------------------------
# 管理画面用 (costume_furniture = 衣装ごとのモーション家具 の編集)
# ----------------------------------------------------------------------


def admin_load_furniture_catalog() -> list[dict]:
    """登録済みの家具を名前順で返す。[{id, name}, ...]"""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM furniture ORDER BY name, id")
        return [{"id": r[0], "name": r[1]} for r in cur.fetchall()]


def admin_load_costume_furniture(costume_id: int) -> list[dict]:
    """指定衣装のモーション家具を返す。

    [{id, name, partners}, ...]。partners は同じ家具にモーションがある
    他の衣装の表示名。
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT f.id, f.name, oc.student_name, oc.costume_name "
            "FROM costume_furniture cf "
            "JOIN furniture f ON f.id = cf.furniture_id "
            "LEFT JOIN costume_furniture ocf "
            "  ON ocf.furniture_id = f.id AND ocf.costume_id <> cf.costume_id "
            "LEFT JOIN costume oc ON oc.id = ocf.costume_id "
            "LEFT JOIN student_priority sp "
            "  ON sp.student_name = oc.student_name "
            "WHERE cf.costume_id = %s "
            "ORDER BY f.id, COALESCE(sp.priority, 1000000), "
            "oc.student_name, oc.sort_order, oc.id",
            (costume_id,),
        )
        rows = cur.fetchall()
    items: dict[int, dict] = {}
    for fid, fname, o_student, o_costume in rows:
        item = items.setdefault(fid, {"id": fid, "name": fname, "partners": []})
        if o_student is not None:
            item["partners"].append(_costume_label(o_student, o_costume))
    return list(items.values())


def admin_add_costume_furniture(
    costume_id: int, name: str, furniture_id: int | None = None
) -> int:
    """衣装にモーション家具を追加し、その家具 ID を返す。

    furniture_id（SchaleDB の家具 ID）を指定した場合はその ID で家具を
    登録（既存なら名前を更新）する。省略時は同名の家具があればそれを
    使い、無ければ負の ID で新規登録する（SchaleDB の ID と衝突させない
    ため。scripts/import_furniture.py が同名の家具を SchaleDB の ID へ
    統合する）。
    """
    conn = _get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            if furniture_id is None:
                cur.execute(
                    "SELECT id FROM furniture WHERE name = %s ORDER BY id DESC",
                    (name,),
                )
                row = cur.fetchone()
                if row:
                    furniture_id = row[0]
                else:
                    cur.execute(
                        "SELECT LEAST(COALESCE(MIN(id), 0), 0) - 1 FROM furniture"
                    )
                    furniture_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO furniture (id, name) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
                (furniture_id, name),
            )
            cur.execute(
                "INSERT INTO costume_furniture (costume_id, furniture_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (costume_id, furniture_id),
            )
        conn.commit()
        return furniture_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def admin_remove_costume_furniture(costume_id: int, furniture_id: int) -> None:
    """衣装からモーション家具を外す。どの衣装も使わなくなった手動登録
    （負の ID）の家具はカタログからも削除する。"""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM costume_furniture WHERE costume_id = %s AND furniture_id = %s",
            (costume_id, furniture_id),
        )
        cur.execute(
            "DELETE FROM furniture f WHERE f.id = %s AND f.id < 0 "
            "AND NOT EXISTS "
            "(SELECT 1 FROM costume_furniture cf WHERE cf.furniture_id = f.id)",
            (furniture_id,),
        )
