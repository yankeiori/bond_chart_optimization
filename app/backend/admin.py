"""管理画面（利用状況ダッシュボード・プリセット・好み/モーション家具）。

Flask の route として登録される。管理者の Google アカウント
（環境変数 ADMIN_GOOGLE_SUB）でログインしたときだけ使えるWebページで
新スキーマ (costume / bond_bonus / student_priority) を編集する。
"""

import json
from datetime import datetime, timezone
from functools import wraps
from html import escape
from urllib.parse import quote

from flask import abort, redirect, request, url_for

from app import app
from app.backend.accounts import (
    admin_google_sub,
    current_user,
    enabled_providers,
    is_admin,
    load_all_user_bond_ranks,
    pop_auth_error,
)
from app.backend.auth import same_origin
from app.backend.student import BOND_RANGES
from app.backend.usage_stats import JST, RECENT_DAYS, compute_usage_stats
from app.backend.user_presets import (
    VALID_PRESENT_TIERS,
    VALID_STATUS_NAMES,
    CostumeExistsError,
    admin_add_costume_furniture,
    admin_delete_preset,
    admin_delete_priority,
    admin_get_costume,
    admin_load_costume_furniture,
    admin_load_costumes,
    admin_load_furniture_catalog,
    admin_load_present,
    admin_load_presets,
    admin_load_priorities,
    admin_rebuild_preset,
    admin_register_costume,
    admin_remove_costume_furniture,
    admin_save_present,
    admin_set_preset_approved,
    admin_upsert_priority,
    gift_image_src,
    load_gifts,
)

# present.tier の日本語ラベル（管理画面の選択肢表示用）。
_TIER_LABELS = {
    "favorite": "好み (中)",
    "superFavorite": "とても好み (大)",
    "ultraFavorite": "最も好み (特大)",
}

# present.tier -> リアクションアイコン (assets/reaction/<name>.png)。
# gift_exp._TIER_TO_EFFECTIVITY と同じ対応。
_TIER_ICON = {
    "favorite": "favorite",
    "superFavorite": "super",
    "ultraFavorite": "ultra",
}

# present の対象になり得る贈り物タイプ。all 型・贈り物選択ボックスは
# tier (好み) を持たないため編集対象外。
_PRESENT_GIFT_TYPES = ("normal", "high")
_GIFT_SELECT_BOX_ID = "gift-select-box"

server = app.server

_RANGE_LABELS = [f"{lo}~{hi}" for lo, hi in BOND_RANGES]
_NUM_RANGES = len(_RANGE_LABELS)
# 衣装ごとに上がるステータスは2つ。新規追加フォームの初期選択。
_ADD_DEFAULT_STATUSES = ("攻撃", "HP")


def _require_login(f):
    """管理者の Google アカウントでログインしているときだけ通す。

    管理者の権限はサイト全体のログイン（180日保持）に乗るので、POST は
    本サイトのページから送られたものだけを受け付ける。
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_admin(current_user()):
            return redirect(url_for("admin_login"))
        if request.method == "POST" and not same_origin():
            abort(403)
        return f(*args, **kwargs)

    return wrapper


def _logout_form() -> str:
    return (
        '<form method="post" action="/auth/logout" class="logout">'
        '<button type="submit">ログアウト</button></form>'
    )


def _login_body() -> str:
    """ログインページの本文（ログイン状態に応じて変える）。"""
    if "google" not in enabled_providers():
        return "<p>Google ログインが設定されていません。</p>"
    user = current_user()
    error = pop_auth_error()
    error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
    if not admin_google_sub():
        # 未設定のときも、ログインして自分の値を確かめられるようにする
        error_html += (
            "<p class='hint'>管理者が設定されていません (ADMIN_GOOGLE_SUB)。</p>"
        )
    if user is None:
        return f"""{error_html}
  <a class="login-btn" href="/auth/login/google?next=admin">Google でログイン</a>"""
    # 管理者でないアカウント。自分の subject を出して ADMIN_GOOGLE_SUB の
    # 設定に使えるようにする（本人にしか見えない、本人の値）。
    subject = escape(user["subject"]) if user["provider"] == "google" else "－"
    return f"""{error_html}
  <p class="error">このアカウントには管理権限がありません。</p>
  <p class="hint">このアカウントの ADMIN_GOOGLE_SUB の値:<br><code>{subject}</code></p>
  {_logout_form()}"""


@server.route("/admin/login")
def admin_login():
    if is_admin(current_user()):
        return redirect(url_for("admin_dashboard"))
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>管理画面ログイン</title>
<style>
  body {{ font-family: sans-serif; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
  .login-box {{ background: #fff; padding: 32px; border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,.1); width: 320px; }}
  h1 {{ font-size: 1.3rem; margin: 0 0 20px; text-align: center; }}
  .login-btn {{ display: block; padding: 10px; background: #4a90d9; color: #fff;
                border-radius: 4px; font-size: 1rem; text-align: center;
                text-decoration: none; }}
  .login-btn:hover {{ background: #3a7bc8; }}
  .error {{ color: red; font-size: 0.9rem; margin-top: 8px; }}
  .hint {{ font-size: 0.85rem; color: #555; }}
  code {{ word-break: break-all; }}
  .logout button {{ width: 100%; padding: 10px; margin-top: 12px; background: #888;
                    color: #fff; border: none; border-radius: 4px; font-size: 1rem;
                    cursor: pointer; }}
</style>
</head>
<body>
<div class="login-box">
  <h1>管理画面</h1>
  {_login_body()}
</div>
</body>
</html>"""


# ----------------------------------------------------------------------
# 描画ヘルパー
# ----------------------------------------------------------------------

_STYLE = """
<style>
  * { box-sizing: border-box; }
  body { font-family: sans-serif; max-width: 1280px; margin: 24px auto;
         padding: 0 20px; background: #f5f5f5; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  h2 { font-size: 1.15rem; color: #333; margin: 26px 0 8px; scroll-margin-top: 64px; }
  .topbar { position: sticky; top: 0; z-index: 10; display: flex; flex-wrap: wrap;
            align-items: center; gap: 4px 18px; background: #f5f5f5;
            border-bottom: 1px solid #ddd; padding: 10px 0; margin-bottom: 18px; }
  .brand { font-weight: bold; color: #333; }
  .tabs { display: flex; flex-wrap: wrap; gap: 4px; }
  .tabs a { padding: 6px 12px; border-radius: 6px; color: #2980b9;
            text-decoration: none; font-size: 0.9rem; }
  .tabs a:hover { background: #e8f1fa; }
  .tabs a.active { background: #2980b9; color: #fff; }
  .logout { margin-left: auto; }
  .logout button { background: none; border: none; padding: 0; cursor: pointer;
                   color: #888; font-size: 0.9rem; }
  .logout button:hover { color: #333; }
  .subnav { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 0.85rem;
            margin: 0 0 8px; }
  .subnav a { color: #2980b9; text-decoration: none; }
  .subnav a:hover { text-decoration: underline; }
  .table-wrap { overflow-x: auto; margin-bottom: 20px; }
  .table-wrap table { margin-bottom: 0; }
  .summary { color: #666; margin-bottom: 12px; font-size: 0.85rem; }
  .msg { padding: 10px; border-radius: 6px; margin: 12px 0; }
  .msg-ok { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
  .msg-err { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
  table { border-collapse: collapse; width: 100%; background: white;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }
  th, td { border: 1px solid #ddd; padding: 8px; text-align: left;
           font-size: 0.85rem; vertical-align: top; }
  th { background: #3498db; color: white; }
  tr:nth-child(even) { background: #f9f9f9; }
  button { cursor: pointer; border: none; padding: 6px 14px; border-radius: 4px;
           font-size: 0.85rem; color: white; white-space: nowrap; }
  .btn-save { background: #27ae60; }
  .btn-delete { background: #e74c3c; }
  .btn-add { background: #2980b9; padding: 8px 20px; font-size: 0.95rem;
             margin-top: 12px; }
  .btn-add-costume { background: #27ae60; font-size: 0.8rem; padding: 4px 10px; }
  .btn-remove-costume { background: #e74c3c; font-size: 0.75rem; padding: 3px 8px; }
  .btn-approve { background: #27ae60; }
  .btn-unapprove { background: #e67e22; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
           font-size: 0.75rem; font-weight: bold; }
  .badge-approved { background: #d4edda; color: #155724; }
  .badge-pending { background: #f8d7da; color: #721c24; }
  input[type=text], input[type=number], select {
    padding: 5px; border: 1px solid #ccc; border-radius: 4px;
    font-size: 0.85rem; }
  input[type=number] { width: 54px; text-align: center; }
  input[type=number]::-webkit-inner-spin-button,
  input[type=number]::-webkit-outer-spin-button {
    -webkit-appearance: none; margin: 0; }
  input[type=number] { -moz-appearance: textbox; appearance: textbox; }
  .costume-row { display: flex; gap: 4px; align-items: center;
                 margin-bottom: 4px; flex-wrap: wrap; }
  .costume-row input[type=text] { width: 100px; flex-shrink: 0; }
  form { margin: 0; }
  .add-form { background: white; padding: 16px; border-radius: 8px;
              box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .add-form label { display: block; font-weight: bold; margin-top: 10px;
                    margin-bottom: 4px; font-size: 0.85rem; }
  .range-labels { display: flex; gap: 4px; margin-bottom: 4px;
                  margin-left: 104px; }
  .range-labels span { font-size: 0.65rem; color: #888; width: 54px;
                       text-align: center; }
  .pri-row { display: flex; gap: 6px; align-items: center; }
  .empty { text-align: center; color: #888; padding: 24px; }
  .footer { text-align: center; color: #999; font-size: 0.8rem;
            margin-top: 28px; }
  .present-link { color: #2980b9; text-decoration: none; font-size: 0.8rem;
                  white-space: nowrap; }
  .present-link:hover { text-decoration: underline; }
  .char-info { display: flex; flex-wrap: wrap; gap: 18px; align-items: center;
               background: #eef6ff; border: 1px solid #cfe3f7;
               border-radius: 6px; padding: 10px 14px; margin: 8px 0 12px;
               font-size: 0.95rem; }
  .char-info b { color: #1565c0; }
  .char-info-id { margin-left: auto; color: #888; font-size: 0.75rem; }
  .gift-thumb { width: 30px; height: 30px; vertical-align: middle;
                margin-right: 8px; }
  .gift-name { vertical-align: middle; }
  .gift-type { color: #888; font-size: 0.75rem; margin-left: 6px; }
  .picker { background: white; padding: 16px; border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 16px; }
  .picker select { min-width: 320px; }
  .badge-present { background: #d4edda; color: #155724; }
  td.tier-cell { width: 250px; }
  tr.has-present { background: #fffceb; }
  .tier-group { display: flex; gap: 6px; align-items: stretch; }
  .tier-opt { display: inline-flex; align-items: center; justify-content: center;
              cursor: pointer; border: 2px solid transparent; border-radius: 6px;
              padding: 3px; min-width: 40px; }
  .tier-opt input { position: absolute; opacity: 0; pointer-events: none; }
  .tier-opt img { width: 30px; height: 30px; display: block;
                  filter: grayscale(1); opacity: 0.4; transition: 0.1s; }
  .tier-opt input:checked + img { filter: none; opacity: 1; }
  .tier-opt:has(input:checked) { border-color: #2980b9; background: #eaf3fb; }
  .tier-none { font-size: 0.8rem; color: #999; padding: 0 4px; }
  .tier-opt:has(input:checked) .tier-none { color: #2980b9; font-weight: bold; }
  .tier-opt:hover { background: #f0f0f0; }
  .furniture-partners { color: #666; font-size: 0.8rem; }
  .field-row { display: flex; flex-wrap: wrap; gap: 8px 20px; }
  .field-row label { margin: 0; font-weight: bold; font-size: 0.85rem; }
  .field-row input { display: block; margin-top: 4px; width: 200px; }
  .error-text { color: #c0392b; font-weight: bold; }
  .bonus-table { width: auto; }
  .bonus-table td, .bonus-table th { padding: 4px 6px; }
  .gift-grid { display: grid; gap: 8px;
               grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); }
  .gift-card { background: #fff; border-radius: 6px; padding: 8px 10px;
               box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex;
               flex-direction: column; gap: 6px; }
  .gift-card:has(.tier-opt:not(.tier-opt-none) input:checked) {
    background: #fffceb; }
  .gift-card-name { font-size: 0.85rem; display: flex; align-items: center; }
  .furn-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
  .furn-name { width: 280px; max-width: 100%; }
  .furn-id { width: 140px !important; text-align: left !important; }
  .submit-bar { position: sticky; bottom: 0; background: #f5f5f5;
                border-top: 1px solid #ddd; padding: 10px 0; margin-top: 20px;
                display: flex; align-items: center; gap: 12px; }
  .submit-bar .btn-add { margin-top: 0; }
  button:disabled { background: #aaa; cursor: not-allowed; }
  .tiles { display: grid; gap: 12px; margin: 8px 0 4px;
           grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); }
  .tile { background: #fff; border-radius: 8px; padding: 12px 14px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .tile-label { color: #666; font-size: 0.8rem; }
  .tile-value { font-size: 1.6rem; font-weight: bold; color: #222; margin-top: 2px; }
  .tile-sub { color: #888; font-size: 0.75rem; }
  .charts { display: grid; gap: 16px;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
  .chart { background: #fff; border-radius: 8px; padding: 12px 14px 8px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 0; }
  .chart h3 { font-size: 0.95rem; margin: 0 0 2px; color: #333; }
  .chart .summary { margin-bottom: 8px; }
  .bars { display: flex; align-items: flex-end; gap: 2px; height: 160px;
          border-bottom: 1px solid #ccc; }
  .bar-col { position: relative; flex: 1; height: 100%; display: flex;
             align-items: flex-end; outline: none; }
  .bar { width: 100%; background: #4a90d9; border-radius: 4px 4px 0 0;
         min-height: 0; }
  .bar-col:hover .bar, .bar-col:focus .bar { background: #2f6fb5; }
  .bar-col:hover::after, .bar-col:focus::after {
    content: attr(data-tip); position: absolute; bottom: 100%; left: 50%;
    transform: translateX(-50%); background: #333; color: #fff; padding: 3px 7px;
    border-radius: 4px; font-size: 0.75rem; white-space: nowrap; z-index: 2;
    pointer-events: none; }
  .bar-labels { display: flex; gap: 2px; margin-top: 3px; }
  .bar-labels span { flex: 1; font-size: 0.65rem; color: #888; text-align: center;
                     white-space: nowrap; overflow: visible; }
  .label-short { display: none; }
  .chart details { margin-top: 8px; font-size: 0.8rem; }
  .chart details table { margin: 6px 0 0; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
  th.sortable::after { content: " ↕"; opacity: 0.5; }
  th.sorted-asc::after { content: " ▲"; opacity: 1; }
  th.sorted-desc::after { content: " ▼"; opacity: 1; }
  .muted { color: #999; }
  .tag { display: inline-block; padding: 0 6px; border-radius: 8px;
         background: #eee; color: #555; font-size: 0.7rem; margin-left: 4px; }
  .toolbar { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
             margin: 4px 0 8px; font-size: 0.85rem; }
  @media (max-width: 600px) {
    body { padding: 0 12px; margin-top: 0; }
    .picker select { min-width: 0; width: 100%; }
    .label-full { display: none; }
    .label-short { display: inline; }
  }
</style>
"""

# 管理画面のタブ: (キー, URL, 表示名)
_NAV = [
    ("dashboard", "/admin", "ダッシュボード"),
    ("add", "/admin/add", "衣装を追加"),
    ("presets", "/admin/presets", "プリセット・表示優先度"),
    ("presents", "/admin/presents", "好み・モーション家具"),
]


def _msg_html(message: str, msg_type: str) -> str:
    if not message:
        return ""
    cls = "msg-ok" if msg_type == "ok" else "msg-err"
    return f'<div class="msg {cls}">{escape(message)}</div>'


def _page(
    active: str,
    body: str,
    message: str = "",
    msg_type: str = "ok",
    footer: str = "",
) -> str:
    """管理画面の共通の枠（タブ・ログアウト・メッセージ）で本文を包む。"""
    title = next(label for key, _, label in _NAV if key == active)
    tabs = "".join(
        f'<a href="{url}" class="active">{label}</a>'
        if key == active
        else f'<a href="{url}">{label}</a>'
        for key, url, label in _NAV
    )
    footer_html = f'<div class="footer">{footer}</div>' if footer else ""
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} - 管理画面</title>{_STYLE}</head><body>
    <div class="topbar">
      <span class="brand">管理画面</span>
      <nav class="tabs">{tabs}</nav>
      {_logout_form()}
    </div>
    <h1>{title}</h1>
    {_msg_html(message, msg_type)}
    {body}
    {footer_html}
    </body></html>"""


def _status_select(name: str, selected: str) -> str:
    opts = "".join(
        f'<option value="{escape(s)}"'
        f"{' selected' if s == selected else ''}>{escape(s)}</option>"
        for s in VALID_STATUS_NAMES
    )
    return f'<select name="{name}">{opts}</select>'


def _range_header() -> str:
    labels = "".join(f"<span>{escape(lbl)}</span>" for lbl in _RANGE_LABELS)
    return f'<div class="range-labels"><span style="width:100px"></span>{labels}</div>'


def _costume_row(prefix: str, idx: int, costume: dict | None = None) -> str:
    cname = escape(costume["costume_name"]) if costume else ""
    bonuses = costume["bond_bonuses"] if costume else [0] * _NUM_RANGES
    inp = (
        f'<input type="text" name="{prefix}_cname_{idx}" '
        f'value="{cname}" placeholder="衣装名">'
    )
    for j in range(_NUM_RANGES):
        v = bonuses[j] if j < len(bonuses) else 0
        inp += f'<input type="number" name="{prefix}_b{j}_{idx}" value="{v}" min="0">'
    inp += (
        ' <button type="button" class="btn-remove-costume" '
        'onclick="this.parentElement.remove()">✕</button>'
    )
    cid = costume.get("costume_id") if costume else None
    if cid:
        # 既存衣装は ID を送り、改名しても同じ costume 行を更新する
        # （行を作り直すと present / costume_furniture が CASCADE で消える）
        inp += f'<input type="hidden" name="{prefix}_cid_{idx}" value="{cid}">'
        inp += (
            f' <a class="present-link" href="/admin/presents?costume_id={cid}" '
            'target="_blank" title="この衣装の好み(present)を編集">好み ↗</a>'
        )
    return f'<div class="costume-row">{inp}</div>'


def _render_admin_page(message: str = "", msg_type: str = "ok") -> str:
    presets = admin_load_presets()
    priorities = admin_load_priorities()

    # --- 表示優先度 ---
    pri_rows = ""
    for p in priorities:
        sn = escape(p["student_name"])
        pri_rows += f"""<tr>
          <td>
            <form method="post" action="/admin/presets/priority_save"
                  class="pri-row">
              <input type="hidden" name="orig_student" value="{sn}">
              <input type="text" name="student_name" value="{sn}"
                     style="width:160px">
              <input type="number" name="priority" value="{p["priority"]}"
                     style="width:80px">
              <button type="submit" class="btn-save">保存</button>
            </form>
          </td>
          <td>
            <form method="post" action="/admin/presets/priority_delete"
              onsubmit="return confirm('「{sn}」の優先度を削除しますか？')">
              <input type="hidden" name="student_name" value="{sn}">
              <button type="submit" class="btn-delete">削除</button>
            </form>
          </td>
        </tr>"""
    if not pri_rows:
        pri_rows = '<tr><td colspan="2" class="empty">優先度の設定なし</td></tr>'

    priority_section = f"""
    <h2 id="priority">表示優先度 (student_priority)</h2>
    <div class="summary">数値が小さいほど先頭に表示。空き番号を残すと後から挿入しやすい。</div>
    <table>
      <thead><tr><th>生徒名 / 優先度</th><th style="width:90px">操作</th></tr></thead>
      <tbody>{pri_rows}</tbody>
    </table>
    <div class="add-form">
      <form method="post" action="/admin/presets/priority_save" class="pri-row">
        <input type="text" name="student_name" placeholder="生徒名" required
               style="width:160px">
        <input type="number" name="priority" placeholder="優先度" required
               style="width:80px">
        <button type="submit" class="btn-add">優先度を追加/更新</button>
      </form>
    </div>"""

    # --- プリセット ---
    if not presets:
        preset_rows = '<div class="empty">レコードがありません。</div>'
    else:
        rows = ""
        pending_count = 0
        for pi, p in enumerate(presets):
            sn = escape(p["student_name"])
            st = p["status_name"]
            approved = p.get("approved", True)
            if not approved:
                pending_count += 1
            prefix = f"p{pi}"
            costume_html = _range_header()
            for ci, c in enumerate(p["costumes"]):
                costume_html += _costume_row(prefix, ci, c)
            add_js = (
                f"addCostume(this.parentElement.querySelector('.costumes'),'{prefix}')"
            )
            if approved:
                badge = '<span class="badge badge-approved">承認済み</span>'
                appr_btn = (
                    '<input type="hidden" name="approved" value="0">'
                    '<button type="submit" class="btn-unapprove">承認解除</button>'
                )
            else:
                badge = '<span class="badge badge-pending">未承認</span>'
                appr_btn = (
                    '<input type="hidden" name="approved" value="1">'
                    '<button type="submit" class="btn-approve">承認</button>'
                )
            search = " ".join(
                [sn, escape(st)] + [escape(c["costume_name"]) for c in p["costumes"]]
            )
            rows += f"""<tr data-search="{search}">
              <td>
                <div style="margin-bottom:6px">{badge}</div>
                <form method="post" action="/admin/presets/preset_save"
                      id="form_{prefix}">
                  <input type="hidden" name="old_student" value="{sn}">
                  <input type="hidden" name="old_status"
                         value="{escape(st)}">
                  生徒名:
                  <input type="text" name="student_name" value="{sn}"
                         style="width:150px">
                  ステータス: {_status_select("status_name", st)}
                  <div class="costumes" style="margin-top:8px">
                    {costume_html}
                  </div>
                  <button type="button" class="btn-add-costume"
                          onclick="{add_js}">+ 衣装</button>
                </form>
              </td>
              <td>
                <div style="display:flex;flex-direction:column;gap:8px">
                  <button type="submit" form="form_{prefix}"
                          class="btn-save">保存</button>
                  <form method="post"
                        action="/admin/presets/preset_set_approval">
                    <input type="hidden" name="student" value="{sn}">
                    <input type="hidden" name="status" value="{escape(st)}">
                    {appr_btn}
                  </form>
                  <form method="post" action="/admin/presets/preset_delete"
                    onsubmit="return confirm('「{sn}({escape(st)})」を削除しますか？')">
                    <input type="hidden" name="student" value="{sn}">
                    <input type="hidden" name="status" value="{escape(st)}">
                    <button type="submit" class="btn-delete">削除</button>
                  </form>
                </div>
              </td>
            </tr>"""
        preset_rows = f"""
        <div class="toolbar">
          <label>絞り込み: <input type="text" placeholder="生徒名・ステータス・衣装名"
                 oninput="filterRows(this, 'preset-table')"></label>
        </div>
        <div class="table-wrap"><table id="preset-table"><thead><tr>
          <th>生徒 / ステータス / 衣装（ボーナス: {", ".join(_RANGE_LABELS)}）</th>
          <th style="width:100px">操作</th>
        </tr></thead><tbody>{rows}</tbody></table></div>"""
        if pending_count:
            preset_rows = (
                f'<div class="summary">未承認: {pending_count} 件 '
                "（公開側では「[未承認]」表示）</div>" + preset_rows
            )

    nranges = _NUM_RANGES
    script = f"""
    <script>
    var counters = {{}};
    function addCostume(container, prefix) {{
      if (!(prefix in counters)) {{
        counters[prefix] = container.querySelectorAll('.costume-row').length;
      }}
      var idx = counters[prefix];
      var row = document.createElement('div');
      row.className = 'costume-row';
      var html = '<input type="text" name="' + prefix + '_cname_' + idx
        + '" placeholder="衣装名">';
      for (var j = 0; j < {nranges}; j++) {{
        html += '<input type="number" name="' + prefix + '_b' + j + '_' + idx
          + '" value="0" min="0">';
      }}
      html += ' <button type="button" class="btn-remove-costume"'
        + ' onclick="this.parentElement.remove()">✕</button>';
      row.innerHTML = html;
      container.appendChild(row);
      counters[prefix] = idx + 1;
    }}
    </script>"""

    subnav = (
        '<nav class="subnav">'
        '<a href="#presets">プリセット一覧</a>'
        '<a href="#priority">表示優先度</a>'
        "</nav>"
    )
    body = f"""{subnav}
    <div class="summary">新しい衣装・生徒は「<a href="/admin/add">衣装を追加</a>」から登録します。</div>
    <h2 id="presets">プリセット (costume + bond_bonus) — 全 {len(presets)} 件</h2>
    {preset_rows}
    {priority_section}
    {script}
    {_TABLE_SCRIPT}"""
    return _page(
        "presets",
        body,
        message,
        msg_type,
        footer=f"絆ボーナスは7区分 ({', '.join(_RANGE_LABELS)})",
    )


def _parse_costumes(form, prefix: str) -> list[dict]:
    """フォームから衣装行を番号順に読み出す。

    途中の行を ✕ で削除すると番号が飛ぶため、連番を前提にせず
    送られてきた番号をすべて拾う。既存衣装は costume_id も返す。
    """
    head = f"{prefix}_cname_"
    indices = sorted(
        int(k[len(head) :])
        for k in form.keys()
        if k.startswith(head) and k[len(head) :].isdigit()
    )
    costumes = []
    for idx in indices:
        cname = form.get(f"{head}{idx}", "").strip()
        if not cname:
            continue
        bonuses = []
        for j in range(_NUM_RANGES):
            raw = form.get(f"{prefix}_b{j}_{idx}", "0")
            try:
                bonuses.append(int(raw) if raw else 0)
            except ValueError:
                bonuses.append(0)
        raw_cid = form.get(f"{prefix}_cid_{idx}", "")
        costumes.append(
            {
                "costume_name": cname,
                "bond_bonuses": bonuses,
                "costume_id": int(raw_cid) if raw_cid.isdigit() else None,
            }
        )
    return costumes


def _parse_costumes_any(form) -> list[dict]:
    """フォーム単位送信のため、送られてきた prefix を検出して解析する。"""
    prefixes = set()
    for k in form.keys():
        if "_cname_" in k:
            prefixes.add(k.split("_cname_")[0])
    for pref in prefixes:
        costumes = _parse_costumes(form, pref)
        if costumes:
            return costumes
    return []


# ----------------------------------------------------------------------
# ルート
# ----------------------------------------------------------------------


@server.route("/admin/presets")
@_require_login
def admin_presets():
    msg = request.args.get("msg", "")
    msg_type = request.args.get("type", "ok")
    return _render_admin_page(msg, msg_type)


def _redirect_msg(msg: str, msg_type: str = "ok"):
    return redirect(f"/admin/presets?msg={quote(msg)}&type={msg_type}")


@server.route("/admin/presets/preset_save", methods=["POST"])
@_require_login
def admin_preset_save():
    f = request.form
    old_s = f.get("old_student", "")
    old_st = f.get("old_status", "")
    new_s = f.get("student_name", "").strip()
    new_st = f.get("status_name", "").strip()
    if not new_s:
        return _redirect_msg("生徒名が空です", "err")
    if new_st not in VALID_STATUS_NAMES:
        return _redirect_msg("ステータス名が不正です", "err")
    costumes = _parse_costumes_any(f)
    if not costumes:
        return _redirect_msg("衣装が1つもありません", "err")
    try:
        admin_rebuild_preset(old_s, old_st, new_s, new_st, costumes)
    except Exception as e:
        return _redirect_msg(f"エラー: {e}", "err")
    return _redirect_msg(f"「{new_s}({new_st})」を更新しました")


@server.route("/admin/presets/preset_delete", methods=["POST"])
@_require_login
def admin_preset_delete():
    f = request.form
    s = f.get("student", "")
    st = f.get("status", "")
    if not s or not st:
        return _redirect_msg("対象が指定されていません", "err")
    try:
        admin_delete_preset(s, st)
    except Exception as e:
        return _redirect_msg(f"エラー: {e}", "err")
    return _redirect_msg(f"「{s}({st})」を削除しました")


@server.route("/admin/presets/preset_set_approval", methods=["POST"])
@_require_login
def admin_preset_set_approval():
    f = request.form
    s = f.get("student", "")
    st = f.get("status", "")
    approved = f.get("approved") == "1"
    if not s or not st:
        return _redirect_msg("対象が指定されていません", "err")
    try:
        admin_set_preset_approved(s, st, approved)
    except Exception as e:
        return _redirect_msg(f"エラー: {e}", "err")
    verb = "承認" if approved else "承認解除"
    return _redirect_msg(f"「{s}({st})」を{verb}しました")


@server.route("/admin/presets/priority_save", methods=["POST"])
@_require_login
def admin_priority_save():
    f = request.form
    s = f.get("student_name", "").strip()
    orig = f.get("orig_student", "").strip()
    pri_raw = f.get("priority", "").strip()
    if not s or not pri_raw:
        return _redirect_msg("生徒名と優先度を入力してください", "err")
    try:
        pri = int(pri_raw)
    except ValueError:
        return _redirect_msg("優先度は整数で入力してください", "err")
    try:
        if orig and orig != s:
            admin_delete_priority(orig)
        admin_upsert_priority(s, pri)
    except Exception as e:
        return _redirect_msg(f"エラー: {e}", "err")
    return _redirect_msg(f"優先度を保存しました（{s} = {pri}）")


@server.route("/admin/presets/priority_delete", methods=["POST"])
@_require_login
def admin_priority_delete():
    s = request.form.get("student_name", "")
    if not s:
        return _redirect_msg("生徒名が指定されていません", "err")
    try:
        admin_delete_priority(s)
    except Exception as e:
        return _redirect_msg(f"エラー: {e}", "err")
    return _redirect_msg(f"優先度を削除しました（{s}）")


# ======================================================================
# 好み (present) 管理ページ
# ======================================================================


def _present_gifts() -> list[dict]:
    """present 編集対象の贈り物（normal / high のみ、選択ボックス除く）。"""
    return [
        g
        for g in load_gifts()
        if g["gift_type"] in _PRESENT_GIFT_TYPES and g["id"] != _GIFT_SELECT_BOX_ID
    ]


def _costume_label(c: dict) -> str:
    name = c["costume_name"] or "（標準）"
    star = f" ★{c['present_count']}" if c["present_count"] else ""
    return f"{name}{star}"


def _costume_picker(costumes: list[dict], selected_id: int | None) -> str:
    """生徒ごとに optgroup でまとめた衣装セレクタ。"""
    groups: dict[str, list[dict]] = {}
    for c in costumes:
        groups.setdefault(c["student_name"], []).append(c)
    opts = ['<option value="">― 衣装を選択 ―</option>']
    for student, items in groups.items():
        opts.append(f'<optgroup label="{escape(student)}">')
        for c in items:
            sel = " selected" if c["costume_id"] == selected_id else ""
            # optgroup ラベル(生徒名)は選択後の折り畳み表示に出ないため、
            # option 自体に生徒名を含めて自己説明的にする。
            label = f"{c['student_name']} / {_costume_label(c)}"
            opts.append(
                f'<option value="{c["costume_id"]}"{sel}>{escape(label)}</option>'
            )
        opts.append("</optgroup>")
    return (
        '<div class="picker">'
        '<form method="get" action="/admin/presents">'
        "衣装: "
        '<select name="costume_id" onchange="this.form.submit()">'
        f"{''.join(opts)}</select> "
        '<noscript><button type="submit" class="btn-save">表示</button></noscript>'
        "</form>"
        '<div class="summary" style="margin:8px 0 0">'
        "★ は登録済みの好み件数。生徒の並びは表示優先度に従う。"
        '新しい衣装・生徒は「<a href="/admin/add">衣装を追加</a>」から登録します。</div>'
        "</div>"
    )


def _tier_select(gift_id: str, current: str) -> str:
    """好み(tier)選択。リアクションアイコンのラジオで表示する。

    <select>/<option> は画像を表示できないため、アイコン付きラジオ
    ボタングループにする。各 gift で 1 つだけ選択（同 name のラジオ）。
    """
    name = f"g_{escape(gift_id)}"
    none_chk = "" if current else " checked"
    parts = [
        f'<label class="tier-opt tier-opt-none" title="好みなし">'
        f'<input type="radio" name="{name}" value=""{none_chk}>'
        f'<span class="tier-none">なし</span></label>'
    ]
    for t in VALID_PRESENT_TIERS:
        chk = " checked" if current == t else ""
        lbl = escape(_TIER_LABELS[t])
        parts.append(
            f'<label class="tier-opt" title="{lbl}">'
            f'<input type="radio" name="{name}" value="{t}"{chk}>'
            f'<img src="/assets/reaction/{_TIER_ICON[t]}.png" alt="{lbl}">'
            f"</label>"
        )
    return f'<div class="tier-group">{"".join(parts)}</div>'


def _parse_present(form) -> dict[str, str]:
    """_tier_select の入力を {gift_id: tier} にする（「なし」は含めない）。"""
    mapping: dict[str, str] = {}
    for g in _present_gifts():
        tier = form.get(f"g_{g['id']}", "").strip()
        if tier in VALID_PRESENT_TIERS:
            mapping[g["id"]] = tier
    return mapping


def _present_editor(costume_id: int) -> str:
    costume = admin_get_costume(costume_id)
    if costume is None:
        return '<div class="msg msg-err">指定された衣装が見つかりません。</div>'
    present = admin_load_present(costume_id)
    gifts = _present_gifts()
    title = escape(costume["student_name"])
    cname = escape(costume["costume_name"] or "（標準）")

    rows = ""
    for g in gifts:
        gid = g["id"]
        cur = present.get(gid, "")
        cls = ' class="has-present"' if cur else ""
        rows += f"""<tr{cls}>
          <td>
            <img class="gift-thumb" src="{gift_image_src(g)}"
                 alt="" onerror="this.style.display='none'">
            <span class="gift-name">{escape(g["name"])}</span>
            <span class="gift-type">[{escape(g["gift_type"])}]</span>
          </td>
          <td class="tier-cell">{_tier_select(gid, cur)}</td>
        </tr>"""

    set_count = sum(1 for g in gifts if present.get(g["id"]))
    return f"""
    <h2>好みを編集</h2>
    <div class="char-info">
      <span>生徒: <b>{title}</b></span>
      <span>衣装: <b>{cname}</b></span>
      <span>登録済みの好み: <b>{set_count}</b> 件</span>
      <span class="char-info-id">costume_id={costume_id}</span>
    </div>
    <div class="summary">「なし」のままの贈り物は present から削除されます。
      tier は EXP 計算に影響します（中=favorite / 大=superFavorite /
      特大=ultraFavorite）。</div>
    <form method="post" action="/admin/presents/save">
      <input type="hidden" name="costume_id" value="{costume_id}">
      <table>
        <thead><tr>
          <th>贈り物</th><th class="tier-cell">好み (tier)</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <button type="button" class="btn-delete"
              onclick="document.querySelectorAll(
                       'table input[type=radio][value=&quot;&quot;]')
                       .forEach(function(r){{r.checked=true;}})">
        全て「なし」に</button>
      <button type="submit" class="btn-add">この衣装の好みを保存</button>
    </form>
    {_furniture_editor(costume_id)}"""


def _furniture_editor(costume_id: int) -> str:
    """モーション家具の一覧（削除ボタン付き）と追加フォーム。"""
    items = admin_load_costume_furniture(costume_id)
    rows = ""
    for f in items:
        partners = "、".join(f["partners"]) or "－"
        fid = "手動登録" if f["id"] < 0 else f["id"]
        rows += f"""<tr>
          <td>{escape(f["name"])}</td>
          <td class="furniture-partners">{escape(partners)}</td>
          <td class="furniture-partners">{fid}</td>
          <td>
            <form method="post" action="/admin/presents/furniture/remove">
              <input type="hidden" name="costume_id" value="{costume_id}">
              <input type="hidden" name="furniture_id" value="{f["id"]}">
              <button type="submit" class="btn-delete">削除</button>
            </form>
          </td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="4" class="empty">未登録</td></tr>'
    options = "".join(
        f'<option value="{escape(f["name"])}">' for f in admin_load_furniture_catalog()
    )
    return f"""
    <h2>モーション家具</h2>
    <table>
      <thead><tr>
        <th>家具</th><th>共通の衣装</th><th>家具ID</th><th></th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <form method="post" action="/admin/presents/furniture/add" class="add-form"
          style="margin-top:12px">
      <input type="hidden" name="costume_id" value="{costume_id}">
      家具名:
      <input type="text" name="name" list="furniture-catalog" required
             style="width:260px">
      <datalist id="furniture-catalog">{options}</datalist>
      家具ID (任意):
      <input type="number" name="furniture_id" min="1" style="width:90px">
      <button type="submit" class="btn-add" style="margin-top:0">追加</button>
      <div class="summary" style="margin:6px 0 0">
        登録済みの家具は名前で選べます。新しい家具は取り込み元の家具IDを
        入れておくと、取り込みスクリプト (scripts/import_furniture.py)
        のデータとそのまま揃います。IDなしで登録した家具も、取り込み時に
        同名の家具があれば統合されます。</div>
    </form>"""


def _render_presents_page(
    costume_id: int | None, message: str = "", msg_type: str = "ok"
) -> str:
    try:
        costumes = admin_load_costumes()
    except Exception as e:
        costumes = []
        if not message:
            message, msg_type = f"衣装一覧の取得に失敗しました: {e}", "err"

    picker = _costume_picker(costumes, costume_id)
    if costume_id is None:
        body = '<div class="empty">編集する衣装を選択してください。</div>'
    else:
        try:
            body = _present_editor(costume_id)
        except Exception as e:
            body = f'<div class="msg msg-err">エラー: {escape(str(e))}</div>'

    return _page(
        "presents",
        picker + body,
        message,
        msg_type,
        footer="present = 衣装ごとの好み贈り物。gift カタログは固定。",
    )


def _parse_costume_id(raw: str) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@server.route("/admin/presents")
@_require_login
def admin_presents():
    costume_id = _parse_costume_id(request.args.get("costume_id", ""))
    msg = request.args.get("msg", "")
    msg_type = request.args.get("type", "ok")
    return _render_presents_page(costume_id, msg, msg_type)


def _redirect_presents(costume_id: int | None, msg: str, msg_type: str = "ok"):
    cid = f"costume_id={costume_id}&" if costume_id is not None else ""
    return redirect(f"/admin/presents?{cid}msg={quote(msg)}&type={msg_type}")


@server.route("/admin/presents/save", methods=["POST"])
@_require_login
def admin_present_save():
    f = request.form
    costume_id = _parse_costume_id(f.get("costume_id", ""))
    if costume_id is None:
        return _redirect_presents(None, "衣装が指定されていません", "err")
    mapping = _parse_present(f)
    try:
        admin_save_present(costume_id, mapping)
    except Exception as e:
        return _redirect_presents(costume_id, f"エラー: {e}", "err")
    return _redirect_presents(costume_id, f"好みを保存しました（{len(mapping)} 件）")


@server.route("/admin/presents/furniture/add", methods=["POST"])
@_require_login
def admin_furniture_add():
    f = request.form
    costume_id = _parse_costume_id(f.get("costume_id", ""))
    if costume_id is None:
        return _redirect_presents(None, "衣装が指定されていません", "err")
    name = f.get("name", "").strip()
    if not name:
        return _redirect_presents(costume_id, "家具名を入力してください", "err")
    raw_id = f.get("furniture_id", "").strip()
    furniture_id = _parse_costume_id(raw_id) if raw_id else None
    if raw_id and (furniture_id is None or furniture_id <= 0):
        return _redirect_presents(
            costume_id, "家具IDは正の整数で入力してください", "err"
        )
    try:
        admin_add_costume_furniture(costume_id, name, furniture_id)
    except Exception as e:
        return _redirect_presents(costume_id, f"エラー: {e}", "err")
    return _redirect_presents(costume_id, f"モーション家具「{name}」を追加しました")


@server.route("/admin/presents/furniture/remove", methods=["POST"])
@_require_login
def admin_furniture_remove():
    f = request.form
    costume_id = _parse_costume_id(f.get("costume_id", ""))
    furniture_id = _parse_costume_id(f.get("furniture_id", ""))
    if costume_id is None or furniture_id is None:
        return _redirect_presents(costume_id, "家具が指定されていません", "err")
    try:
        admin_remove_costume_furniture(costume_id, furniture_id)
    except Exception as e:
        return _redirect_presents(costume_id, f"エラー: {e}", "err")
    return _redirect_presents(costume_id, "モーション家具を削除しました")


# ----------------------------------------------------------------------
# 衣装を追加（衣装・絆ボーナス・好み・モーション家具をまとめて登録）
# ----------------------------------------------------------------------

# モーション家具の入力欄の初期行数（「+ 家具」で増やせる）
_ADD_FURNITURE_ROWS = 2


class _FormError(ValueError):
    pass


def _parse_add_form(form) -> dict:
    """衣装追加フォームを検証して admin_register_costume の引数にする。

    不正な入力は _FormError（メッセージは画面にそのまま出す）。
    """
    student = form.get("student_name", "").strip()
    costume = form.get("costume_name", "").strip()
    if not student or not costume:
        raise _FormError("生徒名と衣装名を入力してください")

    bonuses_by_status: dict[str, list[int]] = {}
    for k in range(len(_ADD_DEFAULT_STATUSES)):
        status = form.get(f"status_{k}", "").strip()
        if status not in VALID_STATUS_NAMES:
            raise _FormError("ステータス名が不正です")
        if status in bonuses_by_status:
            raise _FormError("上がるステータスが重複しています")
        try:
            bonuses = [
                int(form.get(f"s{k}_b{j}", "").strip() or 0) for j in range(_NUM_RANGES)
            ]
        except ValueError:
            raise _FormError("絆ボーナスは整数で入力してください") from None
        if any(b < 0 for b in bonuses):
            raise _FormError("絆ボーナスは0以上で入力してください")
        bonuses_by_status[status] = bonuses

    raw_priority = form.get("priority", "").strip()
    priority = None
    if raw_priority:
        try:
            priority = int(raw_priority)
        except ValueError:
            raise _FormError("表示優先度は整数で入力してください") from None

    furniture: list[tuple[str, int | None]] = []
    i = 0
    while f"furn_name_{i}" in form or f"furn_id_{i}" in form:
        name = form.get(f"furn_name_{i}", "").strip()
        raw_id = form.get(f"furn_id_{i}", "").strip()
        i += 1
        if not name:
            if raw_id:
                raise _FormError("家具IDだけの行があります。家具名も入力してください")
            continue
        furniture_id = _parse_costume_id(raw_id) if raw_id else None
        if raw_id and (furniture_id is None or furniture_id <= 0):
            raise _FormError("家具IDは正の整数で入力してください")
        furniture.append((name, furniture_id))

    return {
        "student_name": student,
        "costume_name": costume,
        "bonuses_by_status": bonuses_by_status,
        "present": _parse_present(form),
        "furniture": furniture,
        "priority": priority,
    }


def _add_bonus_table(form) -> str:
    head = "".join(f'<th class="num">{escape(lbl)}</th>' for lbl in _RANGE_LABELS)
    rows = ""
    for k, default_status in enumerate(_ADD_DEFAULT_STATUSES):
        status = form.get(f"status_{k}", default_status)
        cells = "".join(
            f'<td><input type="number" name="s{k}_b{j}" min="0" '
            f'value="{escape(form.get(f"s{k}_b{j}", ""))}" placeholder="0" '
            f'data-row="{k}" data-col="{j}"></td>'
            for j in range(_NUM_RANGES)
        )
        rows += f"<tr><td>{_status_select(f'status_{k}', status)}</td>{cells}</tr>"
    return f"""<div class="table-wrap"><table class="bonus-table">
      <thead><tr><th>ステータス</th>{head}</tr></thead>
      <tbody>{rows}</tbody></table></div>"""


def _add_gift_grid(form) -> str:
    cards = ""
    for g in _present_gifts():
        cur = form.get(f"g_{g['id']}", "")
        cards += f"""<div class="gift-card">
          <div class="gift-card-name">
            <img class="gift-thumb" src="{gift_image_src(g)}" alt=""
                 onerror="this.style.display='none'">
            <span>{escape(g["name"])}</span>
            <span class="gift-type">[{escape(g["gift_type"])}]</span>
          </div>
          {_tier_select(g["id"], cur)}
        </div>"""
    return f'<div class="gift-grid">{cards}</div>'


def _furniture_row(i: int, name: str = "", fid: str = "") -> str:
    return (
        '<div class="furn-row">'
        f'<input type="text" name="furn_name_{i}" value="{escape(name)}" '
        'list="furniture-catalog" placeholder="家具名" class="furn-name">'
        f'<input type="number" name="furn_id_{i}" value="{escape(fid)}" min="1" '
        'placeholder="家具ID（任意）" class="furn-id">'
        "</div>"
    )


def _add_furniture_rows(form) -> str:
    rows = []
    i = 0
    while f"furn_name_{i}" in form or f"furn_id_{i}" in form:
        rows.append(
            _furniture_row(
                i, form.get(f"furn_name_{i}", ""), form.get(f"furn_id_{i}", "")
            )
        )
        i += 1
    while len(rows) < _ADD_FURNITURE_ROWS:
        rows.append(_furniture_row(len(rows)))
    return "".join(rows)


def _render_add_page(
    form=None, message: str = "", msg_type: str = "ok", done_id: int | None = None
) -> str:
    form = form or {}
    try:
        costumes = admin_load_costumes()
        presets = admin_load_presets()
        priorities = admin_load_priorities()
        catalog = admin_load_furniture_catalog()
    except Exception as e:
        return _page("add", "", f"データの取得に失敗しました: {e}", "err")

    # 生徒名の入力に合わせて「新しい生徒か・登録済みの衣装・上がるステータス」を
    # 出すための既存データ（JS で使う）
    students: dict[str, dict] = {}
    for c in costumes:
        students.setdefault(c["student_name"], {"costumes": [], "statuses": []})
        students[c["student_name"]]["costumes"].append(c["costume_name"])
    for p in presets:
        statuses = students.setdefault(
            p["student_name"], {"costumes": [], "statuses": []}
        )["statuses"]
        if p["status_name"] not in statuses:
            statuses.append(p["status_name"])
    max_priority = max((p["priority"] for p in priorities), default=0)

    done_html = ""
    if done_id is not None:
        done_html = (
            '<div class="msg msg-ok">確認・修正: '
            f'<a href="/admin/presents?costume_id={done_id}">好み・モーション家具</a>'
            ' ／ <a href="/admin/presets">プリセット</a></div>'
        )
    student_opts = "".join(f'<option value="{escape(n)}">' for n in students)
    catalog_opts = "".join(f'<option value="{escape(f["name"])}">' for f in catalog)
    student_json = json.dumps(students, ensure_ascii=False).replace("<", "\\u003c")

    body = f"""{done_html}
    <div class="summary">衣装（新しい生徒も可）・絆ボーナス・好み・モーション家具を
      まとめて登録します。途中で失敗したときは何も登録されません。</div>
    <nav class="subnav">
      <a href="#sec-costume">1. 生徒・衣装</a><a href="#sec-bonus">2. 絆ボーナス</a>
      <a href="#sec-gift">3. 好み</a><a href="#sec-furniture">4. モーション家具</a>
    </nav>
    <form method="post" action="/admin/add" id="add-costume-form" autocomplete="off">
      <h2 id="sec-costume">1. 生徒・衣装</h2>
      <div class="add-form">
        <div class="field-row">
          <label>生徒名
            <input type="text" name="student_name" id="add-student" required
                   list="student-names" value="{escape(form.get("student_name", ""))}">
          </label>
          <label>衣装名
            <input type="text" name="costume_name" id="add-costume" required
                   value="{escape(form.get("costume_name", ""))}"
                   placeholder="通常・水着 など">
          </label>
          <label id="priority-field">表示優先度（任意）
            <input type="number" name="priority" style="width:110px"
                   value="{escape(form.get("priority", ""))}"
                   placeholder="{max_priority + 10}">
          </label>
        </div>
        <datalist id="student-names">{student_opts}</datalist>
        <div class="summary" id="student-status" style="margin:8px 0 0"></div>
      </div>

      <h2 id="sec-bonus">2. 絆ボーナス</h2>
      <div class="summary">空欄は 0 です。7つの値をまとめて貼り付けると横に並べて入ります。</div>
      {_add_bonus_table(form)}

      <h2 id="sec-gift">3. 好み</h2>
      <div class="summary">好みの贈り物だけ選んでください（<span id="gift-count">0</span> 件選択中）。</div>
      {_add_gift_grid(form)}

      <h2 id="sec-furniture">4. モーション家具（あれば）</h2>
      <div class="add-form">
        <div id="furn-rows">{_add_furniture_rows(form)}</div>
        <datalist id="furniture-catalog">{catalog_opts}</datalist>
        <button type="button" class="btn-add-costume" onclick="addFurnitureRow()">+ 家具</button>
        <div class="summary" style="margin:6px 0 0">
          登録済みの家具は名前で選べます（家具IDは不要）。新しい家具は取り込み元の
          家具IDを入れておくと、取り込みスクリプトのデータとそのまま揃います。
          家具名が空の行は無視します。</div>
      </div>

      <div class="submit-bar">
        <button type="submit" class="btn-add" id="add-submit">まとめて登録</button>
        <span class="summary" id="submit-note"></span>
      </div>
    </form>
    <script>
    var STUDENTS = {student_json};
    var studentInput = document.getElementById('add-student');
    var costumeInput = document.getElementById('add-costume');
    var lastAutoStudent = null;
    function esc(s) {{
      var d = document.createElement('div'); d.textContent = s; return d.innerHTML;
    }}
    function updateStudentStatus() {{
      var name = studentInput.value.trim();
      var costume = costumeInput.value.trim();
      var info = STUDENTS[name];
      var box = document.getElementById('student-status');
      var exists = !!(info && costume && info.costumes.indexOf(costume) >= 0);
      document.getElementById('priority-field').style.display = info ? 'none' : '';
      if (!name) {{
        box.innerHTML = '';
      }} else if (!info) {{
        box.innerHTML = '<b>新しい生徒</b>として登録します。表示優先度を入れると'
          + '一覧での並び位置を指定できます（空欄なら末尾）。';
      }} else {{
        box.innerHTML = '登録済みの生徒です。登録済みの衣装: '
          + esc(info.costumes.join('、'));
        // 既存の生徒は、上がるステータスを既存の衣装に合わせる（生徒を選んだときだけ）
        if (lastAutoStudent !== name && info.statuses.length === 2) {{
          document.querySelector('[name=status_0]').value = info.statuses[0];
          document.querySelector('[name=status_1]').value = info.statuses[1];
        }}
      }}
      lastAutoStudent = name;
      if (exists) {{
        box.innerHTML += '<br><span class="error-text">この衣装は登録済みです。'
          + '編集はプリセット／好み・モーション家具のページで行います。</span>';
      }}
      document.getElementById('add-submit').disabled = exists;
    }}
    studentInput.addEventListener('input', updateStudentStatus);
    costumeInput.addEventListener('input', updateStudentStatus);
    lastAutoStudent = studentInput.value.trim();
    updateStudentStatus();

    // 絆ボーナス: 複数の値の貼り付けを右のマスへ順に入れる
    document.querySelectorAll('.bonus-table input').forEach(function (input) {{
      input.addEventListener('paste', function (e) {{
        var text = (e.clipboardData || window.clipboardData).getData('text');
        var values = text.trim().split(/[\\s,]+/);
        if (values.length < 2) return;
        e.preventDefault();
        var row = input.getAttribute('data-row');
        var col = parseInt(input.getAttribute('data-col'), 10);
        values.forEach(function (v, i) {{
          var target = document.querySelector(
            '.bonus-table input[data-row="' + row + '"][data-col="' + (col + i) + '"]');
          if (target) target.value = v;
        }});
      }});
    }});

    function updateGiftCount() {{
      var n = document.querySelectorAll(
        '.gift-grid input[type=radio]:checked:not([value=""])').length;
      document.getElementById('gift-count').textContent = n;
    }}
    document.querySelector('.gift-grid').addEventListener('change', updateGiftCount);
    updateGiftCount();

    function addFurnitureRow() {{
      var box = document.getElementById('furn-rows');
      var i = box.querySelectorAll('.furn-row').length;
      box.insertAdjacentHTML('beforeend',
        '<div class="furn-row"><input type="text" name="furn_name_' + i + '"'
        + ' list="furniture-catalog" placeholder="家具名" class="furn-name">'
        + '<input type="number" name="furn_id_' + i + '" min="1"'
        + ' placeholder="家具ID（任意）" class="furn-id"></div>');
    }}
    </script>"""
    return _page("add", body, message, msg_type)


@server.route("/admin/add")
@_require_login
def admin_add():
    done_id = _parse_costume_id(request.args.get("costume_id", ""))
    return _render_add_page(
        None, request.args.get("msg", ""), request.args.get("type", "ok"), done_id
    )


@server.route("/admin/add", methods=["POST"])
@_require_login
def admin_add_submit():
    form = request.form
    try:
        data = _parse_add_form(form)
        costume_id = admin_register_costume(**data)
    except (_FormError, CostumeExistsError) as e:
        return _render_add_page(form, str(e), "err")
    except Exception as e:
        return _render_add_page(form, f"エラー: {e}", "err")
    msg = (
        f"「{data['student_name']}／{data['costume_name']}」を登録しました"
        f"（好み {len(data['present'])} 件・モーション家具 {len(data['furniture'])} 件）"
    )
    return redirect(f"/admin/add?msg={quote(msg)}&costume_id={costume_id}")


# ----------------------------------------------------------------------
# ダッシュボード（絆ランク管理の利用状況）
# ----------------------------------------------------------------------


def _fmt_num(value, digits: int = 1) -> str:
    """平均・中央値の表示（整数ならそのまま、無ければ「－」）。"""
    if value is None:
        return '<span class="muted">－</span>'
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.{digits}f}"


def _fmt_time(value) -> str:
    if value is None:
        return '<span class="muted">－</span>'
    return value.astimezone(JST).strftime("%Y-%m-%d %H:%M")


def _tile(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div class="tile-sub">{sub}</div>' if sub else ""
    return (
        f'<div class="tile"><div class="tile-label">{label}</div>'
        f'<div class="tile-value">{value}</div>{sub_html}</div>'
    )


def _bar_chart(
    title: str, note: str, items: list[tuple[str, str | None, int]], unit: str
) -> str:
    """縦棒グラフ（件数）。値はホバー/フォーカスで出し、表でも見られるようにする。

    items は [(ラベル, 狭い画面用の短いラベル（None ならラベルのまま）, 件数), ...]。
    """
    peak = max((n for _, _, n in items), default=0) or 1
    # 棒が多いときは x 軸のラベルを間引く
    step = 1 if len(items) <= 12 else (len(items) + 9) // 10
    cols, labels, rows = "", "", ""
    for i, (label, short, n) in enumerate(items):
        short = label if short is None else short
        tip = escape(f"{label}: {n}{unit}")
        cols += (
            f'<div class="bar-col" tabindex="0" data-tip="{tip}" aria-label="{tip}">'
            f'<div class="bar" style="height:{n / peak * 100:.1f}%"></div></div>'
        )
        # 最後（最新）の棒には必ずラベルを付け、そこから step 本ごとに付ける
        shown = (len(items) - 1 - i) % step == 0
        labels += (
            f'<span><span class="label-full">{escape(label) if shown else ""}</span>'
            f'<span class="label-short">{escape(short) if shown else ""}</span></span>'
        )
        rows += f'<tr><td>{escape(label)}</td><td class="num">{n}</td></tr>'
    if not items:
        return (
            f'<div class="chart"><h3>{title}</h3>'
            '<div class="empty">データがありません。</div></div>'
        )
    return f"""<div class="chart">
      <h3>{title}</h3>
      <div class="summary">{note}（最大 {peak if peak else 0}{unit}）</div>
      <div class="bars">{cols}</div>
      <div class="bar-labels">{labels}</div>
      <details><summary>表で見る</summary>
        <table><thead><tr><th>区分</th><th class="num">{unit}</th></tr></thead>
        <tbody>{rows}</tbody></table>
      </details>
    </div>"""


def _sortable_th(label: str, kind: str = "num") -> str:
    return f'<th class="sortable" data-kind="{kind}">{label}</th>'


def _sort_value(value) -> str:
    return "" if value is None else str(value)


def _costume_table(by_costume: list[dict]) -> str:
    # 既定は「登録人数が多い順 → 平均絆ランクが高い順」
    ordered = sorted(by_costume, key=lambda c: (-c["count"], -(c["avg"] or 0)))
    rows = ""
    for c in ordered:
        name = escape(c["student_name"])
        cname = escape(c["costume_name"] or "（標準）")
        rows += f"""<tr data-search="{name} {cname}">
          <td data-v="{name}">{name}</td>
          <td data-v="{cname}">{cname}</td>
          <td class="num" data-v="{c["count"]}">{c["count"]}</td>
          <td class="num" data-v="{_sort_value(c["avg"])}">{_fmt_num(c["avg"])}</td>
          <td class="num" data-v="{_sort_value(c["median"])}">{_fmt_num(c["median"])}</td>
          <td class="num" data-v="{_sort_value(c["max"])}">{_fmt_num(c["max"])}</td>
          <td class="num" data-v="{c["over50"]}">{c["over50"]}</td>
        </tr>"""
    return f"""
    <div class="toolbar">
      <label>絞り込み: <input type="text" id="costume-filter"
             placeholder="生徒名・衣装名" oninput="filterRows(this, 'costume-table')"></label>
      <span class="muted">見出しをクリックすると並び替えます。</span>
    </div>
    <div class="table-wrap">
    <table id="costume-table" class="sort-table">
      <thead><tr>
        {_sortable_th("生徒", "text")}{_sortable_th("衣装", "text")}
        {_sortable_th("登録人数")}{_sortable_th("平均")}{_sortable_th("中央値")}
        {_sortable_th("最高")}{_sortable_th("50以上の人数")}
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    </div>"""


def _user_table(users: list[dict]) -> str:
    rows = ""
    for u in users:
        tag = '<span class="tag">管理者</span>' if u["is_admin"] else ""
        rows += f"""<tr>
          <td class="num" data-v="{u["id"]}">{u["id"]}{tag}</td>
          <td data-v="{_sort_value(u["created_at"])}">{_fmt_time(u["created_at"])}</td>
          <td data-v="{_sort_value(u["last_login_at"])}">{_fmt_time(u["last_login_at"])}</td>
          <td data-v="{_sort_value(u["updated_at"])}">{_fmt_time(u["updated_at"])}</td>
          <td class="num" data-v="{u["count"]}">{u["count"]}</td>
          <td class="num" data-v="{_sort_value(u["avg"])}">{_fmt_num(u["avg"])}</td>
          <td class="num" data-v="{_sort_value(u["median"])}">{_fmt_num(u["median"])}</td>
          <td class="num" data-v="{_sort_value(u["max"])}">{_fmt_num(u["max"])}</td>
          <td class="num" data-v="{u["total"]}">{u["total"]}</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="9" class="empty">利用者はいません。</td></tr>'
    return f"""
    <div class="table-wrap">
    <table id="user-table" class="sort-table">
      <thead><tr>
        {_sortable_th("ID")}{_sortable_th("初回ログイン", "text")}
        {_sortable_th("最終ログイン", "text")}{_sortable_th("最終保存", "text")}
        {_sortable_th("登録数")}{_sortable_th("平均")}{_sortable_th("中央値")}
        {_sortable_th("最高")}{_sortable_th("合計")}
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    </div>"""


# 表の絞り込み（data-search の文字列で照合）と、th.sortable の見出しでの
# 並び替え。並び替えでは空の値を常に末尾に置く。
_TABLE_SCRIPT = """
<script>
function filterRows(input, tableId) {
  var q = input.value.trim().toLowerCase();
  document.querySelectorAll('#' + tableId + ' tbody tr').forEach(function (tr) {
    var text = (tr.getAttribute('data-search') || '').toLowerCase();
    tr.style.display = !q || text.indexOf(q) >= 0 ? '' : 'none';
  });
}
document.querySelectorAll('table.sort-table').forEach(function (table) {
  var ths = table.querySelectorAll('th.sortable');
  ths.forEach(function (th, col) {
    th.addEventListener('click', function () {
      var desc = !th.classList.contains('sorted-desc');
      ths.forEach(function (h) { h.classList.remove('sorted-asc', 'sorted-desc'); });
      th.classList.add(desc ? 'sorted-desc' : 'sorted-asc');
      var num = th.getAttribute('data-kind') === 'num';
      var body = table.tBodies[0];
      var rows = Array.prototype.slice.call(body.rows);
      rows.sort(function (a, b) {
        var x = a.cells[col].getAttribute('data-v') || '';
        var y = b.cells[col].getAttribute('data-v') || '';
        if (x === '' || y === '') return (x === '') - (y === '');
        var c = num ? parseFloat(x) - parseFloat(y) : x.localeCompare(y, 'ja');
        return desc ? -c : c;
      });
      rows.forEach(function (r) { body.appendChild(r); });
    });
  });
});
</script>"""


def _render_dashboard(include_admin: bool) -> str:
    try:
        users = load_all_user_bond_ranks()
        costumes = admin_load_costumes()
    except Exception as e:
        body = f'<div class="msg msg-err">利用状況の取得に失敗しました: {escape(str(e))}</div>'
        return _page("dashboard", body)
    stats = compute_usage_stats(
        users, costumes, datetime.now(timezone.utc), include_admin
    )
    s = stats["summary"]

    checked = " checked" if include_admin else ""
    excluded = (
        f"（管理者のアカウント {stats['admin_excluded']} 件を除いています）"
        if stats["admin_excluded"]
        else ""
    )
    toolbar = f"""
    <form method="get" action="/admin" class="toolbar">
      <label><input type="checkbox" name="include_admin" value="1"{checked}
             onchange="this.form.submit()"> 管理者のアカウントも数える</label>
      <noscript><button type="submit" class="btn-save">更新</button></noscript>
      <span class="muted">{excluded}</span>
    </form>"""

    avg_count = (
        f"{_fmt_num(s['avg_count'])} / {s['costume_total']}"
        if s["avg_count"] is not None
        else _fmt_num(None)
    )
    tiles = f"""<div class="tiles">
      {
        _tile(
            "ログインした人",
            str(s["users"]),
            f"直近{RECENT_DAYS}日の新規 {s['new_recent']} 人",
        )
    }
      {
        _tile(
            "絆ランクを保存している人",
            str(s["savers"]),
            f"直近{RECENT_DAYS}日に保存 {s['saved_recent']} 人",
        )
    }
      {
        _tile(
            "1人あたりの登録数（平均）",
            avg_count,
            f"中央値 {_fmt_num(s['median_count'])}",
        )
    }
      {
        _tile(
            "登録された絆ランク",
            str(s["entries"]),
            f"平均絆ランク {_fmt_num(s['avg_rank'])}",
        )
    }
    </div>"""

    rank_chart = _bar_chart(
        "絆ランクの分布",
        "全利用者が登録した絆ランクの件数",
        [(b["label"], str(b["low"]), b["count"]) for b in stats["rank_hist"]],
        "件",
    )
    daily_chart = _bar_chart(
        "新規利用者（日別）",
        "初回ログインした人数・日本時間",
        [
            (f"{d['date'].month}/{d['date'].day}", None, d["count"])
            for d in stats["daily_new"]
        ],
        "人",
    )

    body = f"""
    <div class="summary">ログインして絆ランクをサーバーに保存した人だけを数えます。
      ログインせずに使っている人のデータはブラウザにしか無いため含まれません。</div>
    {toolbar}
    {tiles}
    <nav class="subnav" style="margin-top:14px">
      <a href="#charts">グラフ</a><a href="#costumes">生徒（衣装）別</a>
      <a href="#users">利用者別</a>
    </nav>
    <h2 id="charts">グラフ</h2>
    <div class="charts">{rank_chart}{daily_chart}</div>
    <h2 id="costumes">生徒（衣装）別 — 全 {len(stats["by_costume"])} 件</h2>
    {_costume_table(stats["by_costume"])}
    <h2 id="users">利用者別 — 全 {len(stats["users"])} 人</h2>
    <div class="summary">ID は内部の番号です（Google アカウントの情報は表示しません）。</div>
    {_user_table(stats["users"])}
    {_TABLE_SCRIPT}"""
    return _page("dashboard", body, footer="時刻はすべて日本時間")


@server.route("/admin")
@_require_login
def admin_dashboard():
    return _render_dashboard(request.args.get("include_admin") == "1")
