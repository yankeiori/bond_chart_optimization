import os

from dotenv import load_dotenv

load_dotenv()

from dash import ALL, ClientsideFunction, Input, Output, State
from flask import request
from app import app as application
from app.frontend.layout import create_root_layout
import app.frontend.callbacks  # noqa: F401 - コールバック登録
import app.backend.api  # noqa: F401 - API エンドポイント登録
import app.backend.admin  # noqa: F401 - 管理画面登録

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
            return hit ? 'bm-row' : 'bm-row bm-hidden';
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

# --- 絆ランク管理: スクリーンショットの読み取り（画像はブラウザ内で処理） ---
application.clientside_callback(
    ClientsideFunction("bond_ocr", "read"),
    Output("bm-ocr-result", "data"),
    Input("bm-ocr-upload", "contents"),
    State("bm-ocr-refs", "data"),
    prevent_initial_call=True,
)

# --- 絆ランク管理: 範囲外の絆ランクを赤枠で示す ---
application.clientside_callback(
    """
    function(values) {
        const base = {width: '80px', textAlign: 'center'};
        return values.map(function (v) {
            const ok = v === null || v === undefined || v === ''
                || (Number.isInteger(v) && v >= 1 && v <= 50);
            return ok ? base : Object.assign({}, base, {border: '2px solid red', color: 'red'});
        });
    }
    """,
    Output({"type": "bm-rank", "costume": ALL}, "style"),
    Input({"type": "bm-rank", "costume": ALL}, "value"),
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
