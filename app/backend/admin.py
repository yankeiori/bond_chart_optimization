"""プリセット管理画面。

Flask の route として登録される。パスワード保護されたWebページで
新スキーマ (costume / bond_bonus / student_priority) を編集する。
"""

import os
from functools import wraps
from html import escape
from urllib.parse import quote

from flask import redirect, request, session, url_for

from app import app
from app.backend.student import BOND_RANGES
from app.backend.user_presets import (
    VALID_PRESENT_TIERS,
    VALID_STATUS_NAMES,
    admin_add_costume,
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

# FLASK_SECRET_KEY が未設定でも、毎起動でランダム生成して既知キーでの
# セッション偽造を防ぐ（再起動で管理者は再ログインになる副作用あり）。
server.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32).hex()

# 管理者セッション Cookie の保護設定。PORT 環境変数は gunicorn/Render など
# 本番ホスティング下でセットされる想定で、その場合のみ Secure を強制する
# （ローカル HTTP 開発では Secure を切らないと Cookie が送信されない）。
server.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE="PORT" in os.environ,
)

_ADMIN_PASSWORD = os.environ.get("PRESET_ADMIN_TOKEN", "")

_RANGE_LABELS = [f"{lo}~{hi}" for lo, hi in BOND_RANGES]
_NUM_RANGES = len(_RANGE_LABELS)


def _require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _ADMIN_PASSWORD:
            return "管理パスワードが設定されていません (PRESET_ADMIN_TOKEN)", 503
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)

    return wrapper


@server.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not _ADMIN_PASSWORD:
        return "管理パスワードが設定されていません (PRESET_ADMIN_TOKEN)", 503
    error = ""
    if request.method == "POST":
        if request.form.get("password") == _ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_presets"))
        error = "パスワードが正しくありません"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>管理ログイン</title>
<style>
  body {{ font-family: sans-serif; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
  .login-box {{ background: #fff; padding: 32px; border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,.1); width: 320px; }}
  h1 {{ font-size: 1.3rem; margin: 0 0 20px; text-align: center; }}
  input[type=password] {{ width: 100%; padding: 10px; border: 1px solid #ccc;
                          border-radius: 4px; font-size: 1rem; box-sizing: border-box; }}
  button {{ width: 100%; padding: 10px; margin-top: 12px; background: #4a90d9;
            color: #fff; border: none; border-radius: 4px; font-size: 1rem;
            cursor: pointer; }}
  button:hover {{ background: #3a7bc8; }}
  .error {{ color: red; font-size: 0.9rem; margin-top: 8px; }}
</style>
</head>
<body>
<div class="login-box">
  <h1>プリセット管理</h1>
  <form method="post">
    <input type="password" name="password" placeholder="パスワード" autofocus>
    <button type="submit">ログイン</button>
  </form>
  {"<p class='error'>" + escape(error) + "</p>" if error else ""}
</div>
</body>
</html>"""


@server.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


# ----------------------------------------------------------------------
# 描画ヘルパー
# ----------------------------------------------------------------------

_STYLE = """
<style>
  * { box-sizing: border-box; }
  body { font-family: sans-serif; max-width: 1280px; margin: 24px auto;
         padding: 0 20px; background: #f5f5f5; }
  .header { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; }
  h1 { font-size: 1.4rem; margin: 0; }
  h2 { font-size: 1.15rem; color: #333; margin: 26px 0 8px; }
  .logout { color: #888; text-decoration: none; font-size: 0.9rem;
            margin-left: auto; }
  .logout:hover { color: #333; }
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
           font-size: 0.85rem; color: white; }
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
  .navlink { margin-left: auto; color: #2980b9; text-decoration: none;
             font-size: 0.9rem; }
  .navlink + .logout { margin-left: 14px; }
  .navlink:hover { text-decoration: underline; }
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
</style>
"""


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
        inp += (
            f' <a class="present-link" href="/admin/presents?costume_id={cid}" '
            'target="_blank" title="この衣装の好み(present)を編集">好み ↗</a>'
        )
    return f'<div class="costume-row">{inp}</div>'


def _render_admin_page(message: str = "", msg_type: str = "ok") -> str:
    presets = admin_load_presets()
    priorities = admin_load_priorities()

    msg_html = ""
    if message:
        cls = "msg-ok" if msg_type == "ok" else "msg-err"
        msg_html = f'<div class="msg {cls}">{escape(message)}</div>'

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
    <h2>表示優先度 (student_priority)</h2>
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
            rows += f"""<tr>
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
        preset_rows = f"""<table><thead><tr>
          <th>生徒 / ステータス / 衣装（ボーナス: {", ".join(_RANGE_LABELS)}）</th>
          <th style="width:90px">操作</th>
        </tr></thead><tbody>{rows}</tbody></table>"""
        if pending_count:
            preset_rows = (
                f'<div class="summary">未承認: {pending_count} 件 '
                "（公開側では「[未承認]」表示）</div>" + preset_rows
            )

    add_preset = f"""
    <h2>新規プリセット追加</h2>
    <div class="add-form">
      <form method="post" action="/admin/presets/preset_add" id="add-form">
        <label>生徒名</label>
        <input type="text" name="student_name" required style="width:200px">
        <label>ステータス名</label>
        {_status_select("status_name", "攻撃")}
        <label>衣装</label>
        {_range_header()}
        <div id="add-costumes" class="costumes">
          {_costume_row("add", 0)}
        </div>
        <button type="button" class="btn-add-costume"
                onclick="addCostume(document.getElementById('add-costumes'),'add')">
          + 衣装追加</button>
        <br>
        <button type="submit" class="btn-add">追加</button>
      </form>
    </div>"""

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

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>プリセット管理</title>{_STYLE}</head><body>
    <div class="header">
      <h1>プリセット管理</h1>
      <a href="/admin/presents" class="navlink">好み(present)管理 →</a>
      <a href="/admin/logout" class="logout">ログアウト</a>
    </div>
    {msg_html}
    {priority_section}
    <h2>プリセット (costume + bond_bonus) — 全 {len(presets)} 件</h2>
    {preset_rows}
    {add_preset}
    {script}
    <div class="footer">絆ボーナスは7区分 ({", ".join(_RANGE_LABELS)})</div>
    </body></html>"""


def _parse_costumes(form, prefix: str) -> list[dict]:
    costumes = []
    idx = 0
    while True:
        cname_key = f"{prefix}_cname_{idx}"
        if cname_key not in form:
            break
        cname = form.get(cname_key, "").strip()
        if cname:
            bonuses = []
            for j in range(_NUM_RANGES):
                raw = form.get(f"{prefix}_b{j}_{idx}", "0")
                try:
                    bonuses.append(int(raw) if raw else 0)
                except ValueError:
                    bonuses.append(0)
            costumes.append({"costume_name": cname, "bond_bonuses": bonuses})
        idx += 1
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


@server.route("/admin/presets/preset_add", methods=["POST"])
@_require_login
def admin_preset_add():
    f = request.form
    new_s = f.get("student_name", "").strip()
    new_st = f.get("status_name", "").strip()
    if not new_s:
        return _redirect_msg("生徒名を入力してください", "err")
    if new_st not in VALID_STATUS_NAMES:
        return _redirect_msg("ステータス名が不正です", "err")
    costumes = _parse_costumes(f, "add")
    if not costumes:
        return _redirect_msg("衣装を1つ以上入力してください", "err")
    try:
        admin_rebuild_preset(new_s, new_st, new_s, new_st, costumes)
    except Exception as e:
        return _redirect_msg(f"エラー: {e}", "err")
    return _redirect_msg(f"「{new_s}({new_st})」を追加しました")


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
        "★ は登録済みの好み件数。生徒の並びは表示優先度に従う。</div>"
        '<form method="post" action="/admin/presents/add_costume" '
        'style="margin-top:12px;border-top:1px solid #eee;padding-top:12px">'
        "新規 生徒/衣装 を追加: "
        '<input type="text" name="student_name" placeholder="生徒名" '
        'required style="width:160px"> '
        '<input type="text" name="costume_name" placeholder="衣装名" '
        'required style="width:160px"> '
        '<button type="submit" class="btn-add" '
        'style="margin-top:0">追加して編集</button>'
        '<div class="summary" style="margin:6px 0 0">'
        "既存の (生徒名, 衣装名) があればそれを再利用します。"
        "衣装名は空欄不可（標準衣装は「通常」等で登録）。</div>"
        "</form>"
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
        登録済みの家具は名前で選べます。新しい家具は SchaleDB の家具IDを
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

    msg_html = ""
    if message:
        cls = "msg-ok" if msg_type == "ok" else "msg-err"
        msg_html = f'<div class="msg {cls}">{escape(message)}</div>'

    picker = _costume_picker(costumes, costume_id)
    if costume_id is None:
        body = '<div class="empty">編集する衣装を選択してください。</div>'
    else:
        try:
            body = _present_editor(costume_id)
        except Exception as e:
            body = f'<div class="msg msg-err">エラー: {escape(str(e))}</div>'

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>好み(present)管理</title>{_STYLE}</head><body>
    <div class="header">
      <h1>好み(present)管理</h1>
      <a href="/admin/presets" class="navlink">← プリセット管理</a>
      <a href="/admin/logout" class="logout">ログアウト</a>
    </div>
    {msg_html}
    {picker}
    {body}
    <div class="footer">present = 衣装ごとの好み贈り物。gift カタログは固定。</div>
    </body></html>"""


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
    mapping: dict[str, str] = {}
    for g in _present_gifts():
        tier = f.get(f"g_{g['id']}", "").strip()
        if tier in VALID_PRESENT_TIERS:
            mapping[g["id"]] = tier
    try:
        admin_save_present(costume_id, mapping)
    except Exception as e:
        return _redirect_presents(costume_id, f"エラー: {e}", "err")
    return _redirect_presents(costume_id, f"好みを保存しました（{len(mapping)} 件）")


@server.route("/admin/presents/add_costume", methods=["POST"])
@_require_login
def admin_present_add_costume():
    f = request.form
    student = f.get("student_name", "").strip()
    costume = f.get("costume_name", "").strip()
    if not student or not costume:
        return _redirect_presents(None, "生徒名と衣装名を入力してください", "err")
    try:
        costume_id = admin_add_costume(student, costume)
    except Exception as e:
        return _redirect_presents(None, f"エラー: {e}", "err")
    return _redirect_presents(
        costume_id, f"「{student} / {costume}」を追加しました。好みを編集できます。"
    )


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
