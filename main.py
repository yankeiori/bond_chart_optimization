import os

from dotenv import load_dotenv

load_dotenv()

from dash import ALL, MATCH, ClientsideFunction, Input, Output, State
from flask import redirect, request, send_from_directory
from app import app as application
from app.frontend.layout import ROOT_REDIRECT, create_root_layout
import app.frontend.callbacks  # noqa: F401 - コールバック登録
import app.backend.admin  # noqa: F401 - 管理画面登録
import app.backend.auth  # noqa: F401 - ログイン登録

application.layout = create_root_layout

# 中身が変わると URL も変わる配信物に付ける長期キャッシュ（再検証もさせない）。
LONG_CACHE_CONTROL = "public, max-age=31536000, immutable"


@application.server.before_request
def _guard_requests():
    path = request.path or ""
    # 正規の Dash の画面はコールバックの本文を圧縮して送らない。圧縮した本文は Dash が
    # 展開後 64 MB まで受け付けるため、小さなリクエストで巨大な応答を返させる悪用
    # （帯域の増幅）に使える。受け付けずに断る。
    if path == "/_dash-update-component" and request.headers.get("Content-Encoding"):
        return "Content-Encoding is not supported", 415
    # ルート (/) は計算機ページへ。ブラウザ側で書き換えるとページ全体を 2 回
    # 読み込むことになるので、サーバーで転送する。
    if path == "/":
        query = request.query_string.decode()
        return redirect(ROOT_REDIRECT + (f"?{query}" if query else ""), 302)
    return None


# URL に版が入っている配信物を長期キャッシュにする。
# - /assets の ?m= は Dash がファイルの mtime から付ける。本番では mtime を中身から
#   決めている（app/caching.py）ので、中身が変わったときだけ URL が変わる。
# - /_dash-component-suites/ は Dash が版入りの URL に 1 年のキャッシュを付ける。
#   immutable を足して、再読み込みでの再検証（Firefox・Safari）もさせない。
@application.server.after_request
def _cache_versioned_files(response):
    if response.status_code not in (200, 304):
        return response
    path = request.path or ""
    if request.endpoint == "_dash_assets.static" and "m" in request.args:
        response.headers["Cache-Control"] = LONG_CACHE_CONTROL
    elif (
        path.startswith("/_dash-component-suites/")
        and response.cache_control.max_age == 31536000
    ):
        response.headers["Cache-Control"] = LONG_CACHE_CONTROL
    return response


# クローラーが取りに来る /robots.txt と、<link rel="icon"> の無いページ（管理画面など）で
# ブラウザが取りに来る /favicon.ico。無いと Dash がページの HTML（約 14 KB）を返してしまう。
@application.server.route("/robots.txt")
def _robots_txt():
    body = "User-agent: *\nDisallow: /admin\nDisallow: /auth/\n"
    return (
        body,
        200,
        {
            "Content-Type": "text/plain; charset=utf-8",
            "Cache-Control": "public, max-age=86400",
        },
    )


@application.server.route("/favicon.ico")
def _favicon_ico():
    return send_from_directory(
        application.config.assets_folder, "favicon.ico", max_age=604800
    )


# Dash 内部エンドポイント (/_dash-layout 等) のキャッシュを無効化
# CDN/ブラウザが古いレイアウトを返すのを防ぐ。
# /_dash-component-suites/ (Dash の JS 本体) はバージョン入りの URL で Dash が
# 長期キャッシュを指定するため対象外にする（無効化すると訪問のたびに約 1MB を
# 再ダウンロードし、Render の帯域を圧迫する）。
@application.server.after_request
def _no_cache_dash_endpoints(response):
    path = request.path or ""
    if "/_dash-" in path and "/_dash-component-suites/" not in path:
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# 生徒・贈り物・リアクションのアイコンは URL にバージョンが入らないため、
# Dash の既定では no-cache（訪問のたびに数百枚分の確認通信）になる。
# 差し替えはまれなので 7 日間キャッシュさせる（差し替え後、最大 7 日は古い画像が出る）。
ICON_CACHE_PREFIXES = ("/assets/student/", "/assets/gift/", "/assets/reaction/")
ICON_CACHE_CONTROL = "public, max-age=604800"


@application.server.after_request
def _cache_icons(response):
    if response.status_code in (200, 304) and (request.path or "").startswith(
        ICON_CACHE_PREFIXES
    ):
        response.headers["Cache-Control"] = ICON_CACHE_CONTROL
    return response


# ===========================================================================
# クライアントサイドコールバック
# ===========================================================================


# --- アプリ内で / に来たときは計算機ページへ（サーバーへの往復なし） ---
# 直接 / を開いた場合は _guard_requests が 302 で転送する。dcc.Location は
# refresh="callback-nav" なので、ここで書き換えてもページ全体は読み直さない。
application.clientside_callback(
    f"""
    function(pathname) {{
        return pathname === "/" ? "{ROOT_REDIRECT}" : window.dash_clientside.no_update;
    }}
    """,
    Output("url", "pathname"),
    Input("url", "pathname"),
)


# --- 絆ランク増減ボタン ---
application.clientside_callback(
    ClientsideFunction("solver", "bond_rank_inc_dec"),
    Output({"type": "bond-rank", "index": ALL}, "value", allow_duplicate=True),
    Input({"type": "bond-rank-inc", "index": ALL}, "n_clicks"),
    Input({"type": "bond-rank-dec", "index": ALL}, "n_clicks"),
    State({"type": "bond-rank", "index": ALL}, "value"),
    State({"type": "bond-rank", "index": ALL}, "id"),
    State({"type": "bond-rank-inc", "index": ALL}, "id"),
    State({"type": "bond-rank-dec", "index": ALL}, "id"),
    prevent_initial_call=True,
)

# --- チャート計算: ステップ1 スピナー表示 + 入力データ収集 ---
application.clientside_callback(
    ClientsideFunction("solver", "collect_inputs"),
    Output("chart-result", "children"),
    Output("solver-inputs", "data"),
    Input("calc-chart-btn", "n_clicks"),
    State({"type": "bond-rank", "index": ALL}, "value"),
    State({"type": "bond-rank", "index": ALL}, "id"),
    State({"type": "bond", "range_idx": ALL, "index": ALL}, "value"),
    State({"type": "bond", "range_idx": ALL, "index": ALL}, "id"),
    State({"type": "costume", "index": ALL}, "value"),
    State({"type": "costume", "index": ALL}, "id"),
    State("costume-priority-order", "data"),
    State("bond50-penalty", "value"),
    State("co-costume-icons", "data"),
    prevent_initial_call=True,
)

# --- チャート計算: ステップ2 DP 実行 + 結果表示 ---
application.clientside_callback(
    ClientsideFunction("solver", "calc_chart"),
    Output("chart-result", "children", allow_duplicate=True),
    Input("solver-inputs", "data"),
    prevent_initial_call=True,
)

# --- ページタブ: アクティブ表示の切り替え（サーバー往復なし） ---
application.clientside_callback(
    """
    function(pathname, ids) {
        return ids.map(
            id => 'page-tab' + (id.path === pathname ? ' page-tab-active' : '')
        );
    }
    """,
    Output({"type": "page-tab", "path": ALL}, "className"),
    Input("url", "pathname"),
    State({"type": "page-tab", "path": ALL}, "id"),
)

# --- 贈り物逆引き: 名前による絞り込み ---
application.clientside_callback(
    """
    function(query, index, ids) {
        const q = (query || '').trim().toLowerCase();
        if (!q) return ids.map(() => ({}));
        return ids.map(function (id) {
            const s = ((index && index[id.gift]) || '').toLowerCase();
            return s.indexOf(q) >= 0 ? {} : {display: 'none'};
        });
    }
    """,
    Output({"type": "gl-gift", "gift": ALL}, "style"),
    Input("gl-search", "value"),
    State("gl-search-index", "data"),
    State({"type": "gl-gift", "gift": ALL}, "id"),
)

# --- 絆ランク管理: 生徒名・衣装名 / 設定済み による絞り込み ---
application.clientside_callback(
    """
    function(query, onlySet, index, ids, rankIds, rankValues) {
        const q = (query || '').trim().toLowerCase();
        const only = (onlySet || []).indexOf('on') >= 0;
        const rankByCostume = {};
        rankIds.forEach(function (id, i) { rankByCostume[id.costume] = rankValues[i]; });
        return ids.map(function (id) {
            const s = (index && index[id.costume]) || '';
            const r = rankByCostume[id.costume];
            const hit = (!q || s.indexOf(q) >= 0) && (!only || (r !== null && r !== undefined && r !== ''));
            const base = 'costume-row bm-grid bm-row';  // _bm_rows の className
            return hit ? base : base + ' bm-hidden';
        });
    }
    """,
    Output({"type": "bm-row", "costume": ALL}, "className"),
    Input("bm-search", "value"),
    Input("bm-only-set", "value"),
    State("bm-search-index", "data"),
    State({"type": "bm-row", "costume": ALL}, "id"),
    State({"type": "bm-rank", "costume": ALL}, "id"),
    State({"type": "bm-rank", "costume": ALL}, "value"),
)

# --- 絆ランク管理: 並び替え ---
# 行を作り直すと入力中のフォーカスが外れるため、グリッドの order で並べ替える。
# 絆ランク順では未設定の衣装を昇順・降順どちらでも末尾に置く。同じ絆ランクや
# 同じ生徒の衣装どうしは標準の並び（生徒の優先度順）のまま。50音順は ja ロケールの
# 比較に任せる（漢字の名前はカタカナの後ろに並ぶ）。
application.clientside_callback(
    """
    function(sort, dir, rankValues, names, rankIds, ids) {
        const rankByCostume = {};
        rankIds.forEach(function (id, i) {
            const v = rankValues[i];
            if (typeof v === 'number') rankByCostume[id.costume] = v;
        });
        const sign = dir === 'desc' ? -1 : 1;
        const collator = new Intl.Collator('ja');
        const compare = {
            default: function (a, b) { return sign * (a - b); },
            rank: function (a, b) {
                const ra = rankByCostume[ids[a].costume];
                const rb = rankByCostume[ids[b].costume];
                const ua = ra === undefined, ub = rb === undefined;
                if (ua !== ub) return ua ? 1 : -1;
                return ua ? 0 : sign * (ra - rb);
            },
            kana: function (a, b) {
                return sign * collator.compare(
                    names[ids[a].costume] || '', names[ids[b].costume] || ''
                );
            },
        }[sort];
        const order = ids.map((id, i) => i).sort(function (a, b) {
            return compare(a, b) || a - b;
        });
        const pos = [];
        order.forEach(function (i, k) { pos[i] = k; });
        return ids.map((id, i) => ({order: pos[i]}));
    }
    """,
    Output({"type": "bm-row", "costume": ALL}, "style"),
    Input("bm-sort", "value"),
    Input("bm-sort-dir", "value"),
    Input({"type": "bm-rank", "costume": ALL}, "value"),
    State("bm-student-names", "data"),
    State({"type": "bm-rank", "costume": ALL}, "id"),
    State({"type": "bm-row", "costume": ALL}, "id"),
)

# 並び替えの種類を変えたら、その種類でよく使う向きに合わせる（絆ランクは高い順から）
application.clientside_callback(
    "function(sort) { return sort === 'rank' ? 'desc' : 'asc'; }",
    Output("bm-sort-dir", "value"),
    Input("bm-sort", "value"),
    prevent_initial_call=True,
)

# --- 絆ランク管理: スクリーンショットの読み取り（画像はブラウザ内で処理） ---
application.clientside_callback(
    ClientsideFunction("bond_ocr", "read"),
    Output("bm-ocr-result", "data"),
    Input("bm-ocr-upload", "contents"),
    State("bm-ocr-refs", "data"),
    prevent_initial_call=True,
)
application.clientside_callback(
    ClientsideFunction("bond_ocr", "crops"),
    Output({"type": "bm-ocr-crops", "costume": MATCH}, "children"),
    Input({"type": "bm-ocr-crops", "costume": MATCH}, "id"),
    State("bm-ocr-crops", "data"),
)

# --- 絆ランク管理: 絆ランクの一覧を画像にして表示（assets/bond_image.js） ---
application.clientside_callback(
    ClientsideFunction("bond_image", "save"),
    Output("bm-image", "src"),
    Output("bm-image-modal", "style", allow_duplicate=True),
    Output("bm-image-feedback", "children"),
    Input("bm-save-image-btn", "n_clicks"),
    State("bond-ranks", "data"),
    State("bm-ocr-refs", "data"),
    prevent_initial_call=True,
)
application.clientside_callback(
    "function(n) { return {display: 'none'}; }",
    Output("bm-image-modal", "style"),
    Input("close-bm-image-btn", "n_clicks"),
    prevent_initial_call=True,
)

# --- 絆ランク管理: +1 ボタン（未設定なら 1、上限 100） ---
application.clientside_callback(
    """
    function(n, v) {
        if (!n) return window.dash_clientside.no_update;
        const cur = Number.isInteger(v) ? v : 0;
        return Math.max(1, Math.min(100, cur + 1));  // MAX_RANK
    }
    """,
    Output({"type": "bm-rank", "costume": MATCH}, "value", allow_duplicate=True),
    Input({"type": "bm-rank-inc", "costume": MATCH}, "n_clicks"),
    State({"type": "bm-rank", "costume": MATCH}, "value"),
    prevent_initial_call=True,
)

# --- 絆ランク管理: -1 ボタン（未設定ならそのまま、1 より下げない） ---
application.clientside_callback(
    """
    function(n, v) {
        if (!n || !Number.isInteger(v)) return window.dash_clientside.no_update;
        return Math.max(1, Math.min(100, v - 1));  // MAX_RANK
    }
    """,
    Output({"type": "bm-rank", "costume": MATCH}, "value", allow_duplicate=True),
    Input({"type": "bm-rank-dec", "costume": MATCH}, "n_clicks"),
    State({"type": "bm-rank", "costume": MATCH}, "value"),
    prevent_initial_call=True,
)

# --- 絆ランク管理: 範囲外の絆ランクを赤枠で示す ---
application.clientside_callback(
    """
    function(values) {
        const base = {width: '100%', textAlign: 'center'};  // BM_ROW_RANK_STYLE
        return values.map(function (v) {
            const ok = v === null || v === undefined || v === ''
                || (Number.isInteger(v) && v >= 1 && v <= 100);  // MAX_RANK
            return ok ? base : Object.assign({}, base, {border: '2px solid red', color: 'red'});
        });
    }
    """,
    Output({"type": "bm-rank", "costume": ALL}, "style"),
    Input({"type": "bm-rank", "costume": ALL}, "value"),
)

# --- 絆ランク管理: 初めてログインしたとき、このブラウザの保存値を取り込む ---
# （取り込んだ値は bond-ranks の変更としてサーバーに保存される。
#   dcc.Store は localStorage に id をキーとした JSON で保存している）
application.clientside_callback(
    """
    function(state) {
        if (!state || !state.needs_import) return window.dash_clientside.no_update;
        let local = null;
        try { local = JSON.parse(window.localStorage.getItem('bond-ranks')); } catch (e) {}
        return (local && Array.isArray(local.costumes)) ? local : {costumes: []};
    }
    """,
    Output("bond-ranks", "data", allow_duplicate=True),
    Input("account-state", "data"),
    prevent_initial_call="initial_duplicate",
)

# --- 絆ランク管理: ログイン中の値をこのブラウザ（localStorage）にも書き写す ---
# （ログアウト後もログアウト直前の内容を使えるようにする。ページを開いたときの
#   サーバーの値も書き写すため初回呼び出しも行う）
application.clientside_callback(
    """
    function(data, state) {
        if (state && state.user_id !== null && state.user_id !== undefined
                && data !== null && data !== undefined) {
            try { window.localStorage.setItem('bond-ranks', JSON.stringify(data)); } catch (e) {}
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("bond-ranks-mirror", "data"),
    Input("bond-ranks", "data"),
    State("account-state", "data"),
)

# --- マニュアルモーダル開閉 ---
application.clientside_callback(
    """
    function(openClicks, closeClicks) {
        const triggered = dash_clientside.callback_context.triggered;
        if (!triggered || triggered.length === 0) return window.dash_clientside.no_update;
        const id = triggered[0].prop_id.split('.')[0];
        if (id === 'open-manual-btn') return {display: 'flex'};
        return {display: 'none'};
    }
    """,
    Output("manual-modal", "style"),
    Input("open-manual-btn", "n_clicks"),
    Input("close-manual-btn", "n_clicks"),
    prevent_initial_call=True,
)

# gunicorn から参照される WSGI サーバー (gunicorn main:server)
server = application.server

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    debug = "PORT" not in os.environ
    application.run(host="0.0.0.0", port=port, debug=debug)
