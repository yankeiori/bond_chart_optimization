import os

from dotenv import load_dotenv

load_dotenv()

from dash import ALL, MATCH, ClientsideFunction, Input, Output, State
from flask import request
from app import app as application
from app.frontend.layout import create_root_layout
import app.frontend.callbacks  # noqa: F401 - コールバック登録
import app.backend.admin  # noqa: F401 - 管理画面登録
import app.backend.auth  # noqa: F401 - ログイン登録

application.layout = create_root_layout


# Dash 内部エンドポイント (/_dash-layout 等) のキャッシュを無効化
# CDN/ブラウザが古いレイアウトを返すのを防ぐ
@application.server.after_request
def _no_cache_dash_endpoints(response):
    if "/_dash-" in (request.path or ""):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ===========================================================================
# クライアントサイドコールバック
# ===========================================================================


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

# --- 絆ランク管理: 絆ランク順の並び替え ---
# 行を作り直すと入力中のフォーカスが外れるため、グリッドの order で並べ替える。
# 未設定の衣装は常に末尾、同じ絆ランクは標準の並び（生徒の優先度順）のまま。
application.clientside_callback(
    """
    function(sort, rankValues, rankIds, ids) {
        if (sort !== 'desc' && sort !== 'asc') return ids.map(() => ({}));
        const rankByCostume = {};
        rankIds.forEach(function (id, i) {
            const v = rankValues[i];
            if (typeof v === 'number') rankByCostume[id.costume] = v;
        });
        const sign = sort === 'desc' ? -1 : 1;
        const order = ids.map((id, i) => i).sort(function (a, b) {
            const ra = rankByCostume[ids[a].costume];
            const rb = rankByCostume[ids[b].costume];
            const ua = ra === undefined, ub = rb === undefined;
            if (ua !== ub) return ua ? 1 : -1;
            if (!ua && ra !== rb) return sign * (ra - rb);
            return a - b;
        });
        const pos = [];
        order.forEach(function (i, k) { pos[i] = k; });
        return ids.map((id, i) => ({order: pos[i]}));
    }
    """,
    Output({"type": "bm-row", "costume": ALL}, "style"),
    Input("bm-sort", "value"),
    Input({"type": "bm-rank", "costume": ALL}, "value"),
    State({"type": "bm-rank", "costume": ALL}, "id"),
    State({"type": "bm-row", "costume": ALL}, "id"),
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
