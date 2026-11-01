"""サーバーサイドコールバック。"""

import logging
from pathlib import Path
from urllib.parse import quote

from dash import html, dcc, callback, Input, Output, State, ALL, ctx, no_update
from dash.exceptions import PreventUpdate

from app.backend.accounts import save_user_bond_ranks, session_user_id
from app.backend.student import BOND_RANGES
from app.backend.user_presets import (
    HAS_DB,
    get_all_presets_for_dropdown,
    get_costume_label,
    get_costume_options,
    get_costume_present_map,
    get_favorite_options,
    get_preset_data,
    get_status_options_for,
    get_student_options,
    make_preset_value,
    load_gifts,
    gift_image_src,
    get_preset_present,
    get_preset_furniture,
    get_gift_lovers,
    parse_preset_value,
    VALID_PRESENT_TIERS,
)
from app.backend.gift_craft import (
    OFFERED_NODES,
    compare_second_nodes,
    craft_expected_exp,
    second_node,
)
from app.backend.gift_exp import (
    get_effectivity,
    gift_exp,
    gift_select_box_exp,
    tier_to_effectivity,
    GIFT_SELECT_BOX_ID,
    TIER_ICON,
    TIER_LABEL,
)
from app.backend.gift_solver import (
    solve_gift_distribution,
    solve_required_boxes,
    exp_to_reach_rank,
)
from app.backend.bond_ranks import (
    MAX_RANK,
    apply_page_edits,
    merge_ocr_cards,
    normalize_bond_ranks,
    ranks_for_costumes,
    save_bond_ranks,
    valid_rank,
)
from app.frontend.layout import (
    BOND_RANKS_BTN_CLASS,
    make_student_card,
    _make_bond_rank_input,
    _default_costume_name,
    PAGES,
    EXTRA_PAGES,
    ROOT_REDIRECT,
    create_layout,
    build_gs_gift_list,
    gs_default_used,
    gl_gift_class,
    gl_lookup_gifts,
    GL_TIER_ORDER,
)


@callback(
    Output("url", "pathname"),
    Input("url", "pathname"),
)
def redirect_root(pathname):
    """ルート (/) を計算機ページへリダイレクトする。"""
    if pathname == "/":
        return ROOT_REDIRECT
    raise PreventUpdate


@callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
)
def display_page(pathname):
    """URL に応じてページを差し替える。未知のパスは計算機ページ。"""
    entry = PAGES.get(pathname) or EXTRA_PAGES.get(pathname)
    if entry is not None:
        _, builder = entry
        return builder()
    return create_layout()


# ----------------------------------------------------------------------
# プリセット選択（生徒ドロップダウン + ステータスラジオ）共通ヘルパー
# ----------------------------------------------------------------------


def _dropdown_student(dropdown_value):
    """ドロップダウン値から生徒名を取り出す。

    値は通常は生徒名のみだが、お気に入り経由では結合値
    (生徒名+ステータス名) が入る。
    """
    parsed = parse_preset_value(dropdown_value)
    return parsed[0] if parsed else dropdown_value


def _combined_preset_value(dropdown_value, status_value):
    """生徒選択とステータス選択からプリセット値（結合値）を作る。

    ステータス未選択時（DB未接続の旧形式キーなど）はドロップダウン値を
    そのまま返す。
    """
    if not dropdown_value:
        return None
    if status_value:
        return make_preset_value(_dropdown_student(dropdown_value), status_value)
    return dropdown_value


def _status_options_for_selection(dropdown_value, saved_value):
    """選択された生徒のステータス選択肢と初期選択を返す。

    初期選択の優先順: 結合値に含まれるステータス（お気に入り経由）
    → autosave に保存されたステータス（同一生徒の場合）→ 攻撃 → 先頭。
    """
    if not dropdown_value:
        return [], None
    parsed = parse_preset_value(dropdown_value)
    student = parsed[0] if parsed else dropdown_value
    options = get_status_options_for(student)
    if not options:
        return [], None
    valid = [o["value"] for o in options]
    if parsed and parsed[1] in valid:
        return options, parsed[1]
    saved = parse_preset_value(saved_value) if saved_value else None
    if saved and saved[0] == student and saved[1] in valid:
        return options, saved[1]
    if "攻撃" in valid:
        return options, "攻撃"
    return options, valid[0]


@callback(
    Output("preset-status-radio", "options"),
    Output("preset-status-radio", "value"),
    Input("preset-dropdown", "value"),
    State("autosave", "data"),
)
def update_status_radio(dropdown_value, autosave_data):
    saved = (autosave_data or {}).get("preset_value")
    return _status_options_for_selection(dropdown_value, saved)


@callback(
    Output("gs-status-radio", "options"),
    Output("gs-status-radio", "value"),
    Input("gs-preset-dropdown", "value"),
    State("gs-autosave", "data"),
)
def gs_update_status_radio(dropdown_value, autosave_data):
    saved = (autosave_data or {}).get("preset_value")
    return _status_options_for_selection(dropdown_value, saved)


# ----------------------------------------------------------------------
# 贈り物配分シミュレータ: プリセット読み込み
# ----------------------------------------------------------------------


# 並び替え（▲▼）ボタンの共通スタイル

# 生徒画像（scripts/fetch_student_icons.py で取得）。ファイル名は衣装の表示名
_STUDENT_ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "student"
_STUDENT_ICONS = {p.stem for p in _STUDENT_ICON_DIR.glob("*.png")}


def _student_icon_src(label: str) -> str | None:
    """衣装の表示名 label の生徒画像の URL。画像が無い衣装は None。"""
    if label not in _STUDENT_ICONS:
        return None
    return f"/assets/student/{quote(label)}.png"


def _student_icon(label: str, size: int = 32):
    """衣装の表示名 label の生徒画像。画像が無い衣装は None。"""
    src = _student_icon_src(label)
    if src is None:
        return None
    return html.Img(
        src=src,
        alt="",
        style={
            "width": f"{size}px",
            "height": f"{size}px",
            "objectFit": "cover",
            "objectPosition": "top",
            "borderRadius": "4px",
            "verticalAlign": "middle",
            "marginRight": "6px",
            "flexShrink": "0",
        },
    )


def _with_student_icon(label: str, text=None, size: int = 32) -> list:
    """衣装の表示名 label の生徒画像を text（既定は label）の前に付けた children。

    画像が無い衣装は text のみ。
    """
    text = label if text is None else text
    icon = _student_icon(label, size)
    return [text] if icon is None else [icon, text]


def _student_header(label: str, text=None):
    """結果表の列見出し。生徒画像があれば text（既定は label）の上に置く。"""
    text = label if text is None else text
    src = _student_icon_src(label)
    if src is None:
        return text
    return html.Div(
        [
            html.Img(
                src=src,
                alt="",
                style={
                    "width": "32px",
                    "height": "32px",
                    "objectFit": "cover",
                    "objectPosition": "top",
                    "borderRadius": "4px",
                },
            ),
            html.Div(text),
        ],
        style={"display": "flex", "flexDirection": "column", "alignItems": "center"},
    )


def _gs_normalize_order(order, n: int) -> list[int]:
    """優先順位（衣装 index の並び）を正規化する。

    不正値・重複を落とし、欠けている衣装は元の順序で末尾に足す。
    """
    seen = []
    for v in order or []:
        try:
            i = int(v)
        except (TypeError, ValueError):
            continue
        if 0 <= i < n and i not in seen:
            seen.append(i)
    seen.extend(i for i in range(n) if i not in seen)
    return seen


def _gs_costume_rows(
    costumes: list[dict],
    rank_by_index=None,
    remain_by_index=None,
    order=None,
) -> list:
    """衣装ごとに 優先順位(▲▼) / 衣装名 / 絆ボーナス(表示のみ) /
    現在の絆ランク入力 / 次の絆上昇までの残り経験値(任意) を生成。

    order は衣装 index の並び（先頭が最優先）。表示順がそのまま優先順位で、
    同点時のタイブレークに使う。rank_by_index / remain_by_index が与えられた
    場合は保存値で上書きする（キーは衣装 index で、並び替えても不変）。
    """
    rank_by_index = rank_by_index or {}
    remain_by_index = remain_by_index or {}
    order = _gs_normalize_order(order, len(costumes))
    labels = _nc_costume_labels()
    rows = []
    for pos, i in enumerate(order):
        c = costumes[i]
        rank_val = rank_by_index.get(i, rank_by_index.get(str(i), 20))
        remain_val = remain_by_index.get(i, remain_by_index.get(str(i), None))
        bonus_cells = [
            html.Span([html.Span(f"絆{lo}~{hi}", className="bonus-label"), str(v)])
            for (lo, hi), v in zip(BOND_RANGES, c["bond_bonuses"])
        ]
        rows.append(
            html.Div(
                [
                    html.Span(
                        f"{pos + 1}.",
                        title=(
                            "優先順位（絆ボーナス合計が同点のとき、"
                            "上の衣装ほど絆ランクが高くなる配分を選ぶ）"
                        ),
                        className="costume-pos",
                    ),
                    html.Button(
                        "▲",
                        id={"type": "gs-move-up", "index": i},
                        n_clicks=0,
                        disabled=pos == 0,
                        title="優先順位を上げる",
                        className="move-btn",
                    ),
                    html.Button(
                        "▼",
                        id={"type": "gs-move-down", "index": i},
                        n_clicks=0,
                        disabled=pos == len(order) - 1,
                        title="優先順位を下げる",
                        className="move-btn",
                    ),
                    html.Strong(
                        _with_student_icon(
                            labels.get(c.get("costume_id"), ""), c["costume_name"]
                        ),
                        className="costume-name",
                    ),
                    dcc.Input(
                        id={"type": "gs-bond-rank", "index": i},
                        type="number",
                        min=1,
                        max=MAX_RANK,
                        value=rank_val,
                        debounce=True,
                    ),
                    dcc.Input(
                        id={"type": "gs-bond-remain", "index": i},
                        type="number",
                        min=1,
                        value=remain_val,
                        debounce=True,
                        placeholder="任意",
                    ),
                    html.Div(bonus_cells, className="bonus-cells"),
                ],
                className="costume-row gs-grid",
            )
        )
    return rows


# present.tier -> リアクションアイコン / 効果ラベル（gift_exp の共有マップ）。
_GS_TIER_ICON = TIER_ICON
_GS_TIER_LABELS = TIER_LABEL


def _gs_furniture_cell(items: list[dict]):
    """モーション家具の欄。家具名と、同じ家具にモーションがある衣装。"""
    if not items:
        return "－"
    return [
        html.Div(
            [html.Span(f["name"])]
            + (
                [
                    html.Span(
                        "（共通: " + "、".join(f["partners"]) + "）",
                        style={"color": "#666", "fontSize": "0.75rem"},
                    )
                ]
                if f["partners"]
                else []
            )
        )
        for f in items
    ]


def _gs_present_table(
    costumes: list[dict],
    present: dict,
    gifts: list[dict],
    furniture: dict | None = None,
):
    """衣装ごとの好物（normal 以外）を 衣装(縦)×リアクション(横) の表にし、
    末尾にモーション家具の列を付ける。

    present: {衣装名: {gift_id: tier}}。
    furniture: {衣装名: [{name, partners}]}（get_preset_furniture）。
    データが無い場合はメッセージを返す。
    """
    furniture = furniture or {}
    if not any(
        present.get(c["costume_name"]) or furniture.get(c["costume_name"])
        for c in costumes
    ):
        return html.P(
            "好物データが登録されていません。",
            style={"color": "#888", "margin": "8px 0"},
        )
    header = html.Tr(
        [html.Th("衣装", style=_TH)]
        + [
            html.Th(
                html.Img(
                    src=f"/assets/reaction/{_GS_TIER_ICON[t]}.png",
                    alt=_GS_TIER_LABELS[t],
                    title=_GS_TIER_LABELS[t],
                    style={"height": "24px", "verticalAlign": "middle"},
                ),
                style=_TH,
            )
            for t in VALID_PRESENT_TIERS
        ]
        + [html.Th("モーション家具", style=_TH)]
    )
    rows = []
    for c in costumes:
        tier_by_gift = present.get(c["costume_name"], {})
        cells = []
        for t in VALID_PRESENT_TIERS:
            imgs = [
                html.Img(
                    src=gift_image_src(g),
                    title=g["name"],
                    style={
                        "width": "34px",
                        "height": "26px",
                        "objectFit": "contain",
                        "padding": "2px",
                        "borderRadius": "4px",
                        # 高級は淡い紫、通常は淡い黄色
                        "background": (
                            "#ede7f6"
                            if g["gift_type"] in ("high", "high-all")
                            else "#fff9c4"
                        ),
                    },
                )
                for g in gifts
                if tier_by_gift.get(g["id"]) == t
            ]
            cells.append(html.Td(imgs if imgs else "－", style=_TD))
        cells.append(
            html.Td(
                _gs_furniture_cell(furniture.get(c["costume_name"], [])),
                style={**_TD, "textAlign": "left"},
            )
        )
        rows.append(html.Tr([html.Td(c["costume_name"], style=_TD_LABEL)] + cells))
    # 家具列の分だけ幅が広がるので、狭い画面では横スクロールさせる
    return html.Div(
        html.Table(
            [html.Thead(header), html.Tbody(rows)],
            style={"borderCollapse": "collapse"},
        ),
        style={"overflowX": "auto"},
    )


def _preset_present_children(preset_value, costumes: list[dict]):
    """プリセット値から好物表を構築する（両ページ共通の入口）。"""
    parsed = parse_preset_value(preset_value)
    if not parsed:
        return html.P(
            "好物データが登録されていません。",
            style={"color": "#888", "margin": "8px 0"},
        )
    return _gs_present_table(
        costumes,
        get_preset_present(*parsed),
        load_gifts(),
        get_preset_furniture(*parsed),
    )


def _gs_build_view(
    preset_value,
    ranks=None,
    qty=None,
    use=None,
    remain=None,
    order=None,
    bond_ranks=None,
):
    """プリセットから 衣装表示 / 好物表 / フィードバック / loaded-store /
    贈り物リスト / 優先順位 を構築する。ranks/qty/use/remain/order は
    保存値の上書き（復元用）。bond_ranks を渡すと、絆ランク管理で
    設定済みの衣装の絆ランクを初期値に使う（新規読み込み用）。

    Returns (costume_children, present_children, feedback, store_data,
    gift_list_children, order) または失敗時
    (None, None, error_span, None, None, None)。
    """
    result = get_preset_data(preset_value)
    parsed = parse_preset_value(preset_value)
    if not result or not parsed:
        return (
            None,
            None,
            html.Span("プリセットが見つかりません。", style={"color": "red"}),
            None,
            None,
            None,
        )
    display_name, costumes = result
    student_name, status_name = parsed
    if bond_ranks is not None:
        ranks = ranks_for_costumes(bond_ranks, [c.get("costume_id") for c in costumes])
    present = get_preset_present(student_name, status_name)
    preferred = {gid for tiers in present.values() for gid in tiers}

    gifts = load_gifts()
    gift_list_children = build_gs_gift_list(
        gifts,
        lambda g: gs_default_used(g, preferred),
        qty_by_gift=qty,
        use_by_gift=use,
    )
    present_children = _gs_present_table(
        costumes, present, gifts, get_preset_furniture(student_name, status_name)
    )
    feedback = html.Span(
        f"「{display_name}」を読み込みました。", style={"color": "#27ae60"}
    )
    order = _gs_normalize_order(order, len(costumes))
    return (
        _gs_costume_rows(
            costumes, rank_by_index=ranks, remain_by_index=remain, order=order
        ),
        present_children,
        feedback,
        {
            "student_name": student_name,
            "status_name": status_name,
            "costumes": costumes,
        },
        gift_list_children,
        order,
    )


@callback(
    Output("gs-costume-display", "children"),
    Output("gs-present-display", "children"),
    Output("gs-load-feedback", "children"),
    Output("gs-loaded-preset", "data"),
    Output("gs-gift-list", "children"),
    Output("gs-costume-order", "data"),
    Input("gs-load-preset-btn", "n_clicks"),
    State("gs-preset-dropdown", "value"),
    State("gs-status-radio", "value"),
    State("bond-ranks", "data"),
    prevent_initial_call=True,
)
def gs_load_preset(n_clicks, dropdown_value, status_value, bond_ranks):
    preset_value = _combined_preset_value(dropdown_value, status_value)
    if not preset_value:
        return (
            no_update,
            no_update,
            html.Span("プリセットを選択してください。", style={"color": "red"}),
            no_update,
            no_update,
            no_update,
        )
    (
        costume_children,
        present_children,
        feedback,
        store,
        gift_list,
        order,
    ) = _gs_build_view(preset_value, bond_ranks=bond_ranks or {})
    if store is None:
        return (no_update, no_update, feedback, no_update, no_update, no_update)
    return (costume_children, present_children, feedback, store, gift_list, order)


def _overlay_bond_ranks(bond_ranks, costume_ids, rank_by_index, remain_by_index):
    """入力欄の値 ({index: 値}) を、絆ランク管理で設定済みの衣装だけ
    保存値で上書きする。

    絆ランクが変わる衣装の残りEXPは空欄にする（古い入力値を残さない）。
    Returns (ranks, remains, 反映した衣装数)。
    """
    saved_ranks = ranks_for_costumes(bond_ranks, costume_ids)
    ranks = {**rank_by_index, **saved_ranks}
    remains = {
        i: v
        for i, v in remain_by_index.items()
        if i not in saved_ranks or saved_ranks[i] == rank_by_index.get(i)
    }
    return ranks, remains, len(saved_ranks)


def _save_inputs_to_bond_ranks(bond_ranks, costume_ids, rank_by_index):
    """入力欄の値 ({index: 値}) を costume_id 単位で絆ランク管理へ保存する。

    costume_id の無い衣装（手入力など）と、絆ランクが無効な衣装は保存しない。
    Returns (新しい保存データ, 保存した衣装数)。
    """
    rank_by_cid = {}
    for i, cid in enumerate(costume_ids):
        if cid is None or valid_rank(rank_by_index.get(i)) is None:
            continue
        rank_by_cid[cid] = rank_by_index[i]
    return save_bond_ranks(bond_ranks, rank_by_cid), len(rank_by_cid)


_BOND_RANKS_LINK = dcc.Link(
    "絆ランク管理", href="/bond-ranks", style={"color": "#4a90d9"}
)


def _bond_ranks_applied_feedback(n: int):
    """「絆ランク管理から反映」の結果メッセージ。"""
    if n == 0:
        return html.Span(
            [
                "絆ランクを設定済みの衣装がありません（",
                _BOND_RANKS_LINK,
                "で設定できます）。",
            ],
            style={"color": "#888"},
        )
    return html.Span(
        f"保存済みの絆ランクを {n} 衣装に反映しました。", style={"color": "#27ae60"}
    )


def _bond_ranks_saved_feedback(n: int):
    """「絆ランク管理に保存」の結果メッセージ。"""
    if n == 0:
        return html.Span(
            "保存できる衣装がありません（絆ランクが空欄・範囲外の衣装は保存しません）。",
            style={"color": "red"},
        )
    return html.Span(
        [f"{n} 衣装の絆ランクを", _BOND_RANKS_LINK, "に保存しました。"],
        style={"color": "#27ae60"},
    )


@callback(
    Output("gs-costume-display", "children", allow_duplicate=True),
    Output("gs-bond-ranks-feedback", "children"),
    Input("gs-apply-bond-ranks-btn", "n_clicks"),
    State("bond-ranks", "data"),
    State("gs-loaded-preset", "data"),
    State("gs-costume-order", "data"),
    State({"type": "gs-bond-rank", "index": ALL}, "value"),
    State({"type": "gs-bond-rank", "index": ALL}, "id"),
    State({"type": "gs-bond-remain", "index": ALL}, "value"),
    State({"type": "gs-bond-remain", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def gs_apply_bond_ranks(
    n_clicks,
    bond_ranks,
    loaded,
    order,
    rank_values,
    rank_ids,
    remain_values,
    remain_ids,
):
    """絆ランク管理で設定済みの衣装の絆ランクで入力欄を上書きする。"""
    if not n_clicks:
        raise PreventUpdate
    costumes = (loaded or {}).get("costumes") or []
    if not costumes:
        return no_update, html.Span(
            "プリセットを読み込んでください。", style={"color": "red"}
        )
    ranks, remains, n = _overlay_bond_ranks(
        bond_ranks,
        [c.get("costume_id") for c in costumes],
        _values_by_index(rank_values, rank_ids),
        _values_by_index(remain_values, remain_ids),
    )
    return (
        _gs_costume_rows(
            costumes, rank_by_index=ranks, remain_by_index=remains, order=order
        ),
        _bond_ranks_applied_feedback(n),
    )


@callback(
    Output("bond-ranks", "data", allow_duplicate=True),
    Output("gs-bond-ranks-feedback", "children", allow_duplicate=True),
    Input("gs-save-bond-ranks-btn", "n_clicks"),
    State("bond-ranks", "data"),
    State("gs-loaded-preset", "data"),
    State({"type": "gs-bond-rank", "index": ALL}, "value"),
    State({"type": "gs-bond-rank", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def gs_save_bond_ranks(n_clicks, bond_ranks, loaded, rank_values, rank_ids):
    """入力中の絆ランクを絆ランク管理に保存する。"""
    if not n_clicks:
        raise PreventUpdate
    costumes = (loaded or {}).get("costumes") or []
    if not costumes:
        return no_update, html.Span(
            "プリセットを読み込んでください。", style={"color": "red"}
        )
    saved, n = _save_inputs_to_bond_ranks(
        bond_ranks,
        [c.get("costume_id") for c in costumes],
        _values_by_index(rank_values, rank_ids),
    )
    return (saved if n else no_update), _bond_ranks_saved_feedback(n)


# ----------------------------------------------------------------------
# 贈り物配分シミュレータ: 入力保存（localStorage autosave）
# ----------------------------------------------------------------------


def _gift_inputs_to_maps(qty_values, qty_ids, use_values, use_ids):
    """贈り物の所持数・使用フラグ入力を {gift_id: 値} にまとめる。"""
    qty = {}
    for qv, qid in zip(qty_values, qty_ids):
        try:
            qty[qid["gift"]] = max(0, int(qv))
        except (TypeError, ValueError):
            qty[qid["gift"]] = 0
    use = {
        uid["gift"]: bool(uv and "use" in uv) for uv, uid in zip(use_values, use_ids)
    }
    return qty, use


@callback(
    Output("gs-autosave", "data"),
    Input("gs-preset-dropdown", "value"),
    Input("gs-status-radio", "value"),
    Input({"type": "gs-bond-rank", "index": ALL}, "value"),
    Input({"type": "gs-bond-remain", "index": ALL}, "value"),
    Input({"type": "gs-gift-qty", "gift": ALL}, "value"),
    Input({"type": "gs-gift-use", "gift": ALL}, "value"),
    Input("gs-costume-order", "data"),
    State({"type": "gs-bond-rank", "index": ALL}, "id"),
    State({"type": "gs-bond-remain", "index": ALL}, "id"),
    State({"type": "gs-gift-qty", "gift": ALL}, "id"),
    State({"type": "gs-gift-use", "gift": ALL}, "id"),
    State("gs-autosave-ready", "data"),
    prevent_initial_call=True,
)
def gs_save_autosave(
    dropdown_value,
    status_value,
    rank_values,
    remain_values,
    qty_values,
    use_values,
    order,
    rank_ids,
    remain_ids,
    qty_ids,
    use_ids,
    ready,
):
    # 復元前の保存は禁止。動的レイアウト挿入直後は prevent_initial_call が
    # 効かず初期値で発火するため、そのまま保存すると復元前のデータが潰れる。
    if not ready:
        raise PreventUpdate
    ranks = {
        str(rid["index"]): rv
        for rv, rid in zip(rank_values, rank_ids)
        if rv is not None
    }
    remain = {
        str(rid["index"]): rv
        for rv, rid in zip(remain_values, remain_ids)
        if rv is not None
    }
    qty, use = _gift_inputs_to_maps(qty_values, qty_ids, use_values, use_ids)
    return {
        "preset_value": _combined_preset_value(dropdown_value, status_value),
        "ranks": ranks,
        "remain": remain,
        "qty": qty,
        "use": use,
        "order": list(order or []),
    }


@callback(
    Output("gs-preset-dropdown", "value"),
    Output("gs-costume-display", "children", allow_duplicate=True),
    Output("gs-present-display", "children", allow_duplicate=True),
    Output("gs-load-feedback", "children", allow_duplicate=True),
    Output("gs-loaded-preset", "data", allow_duplicate=True),
    Output("gs-gift-list", "children", allow_duplicate=True),
    Output("gs-costume-order", "data", allow_duplicate=True),
    Output("gs-autosave-ready", "data"),
    Input("gs-autosave-init", "n_intervals"),
    State("gs-autosave", "data"),
    prevent_initial_call=True,
)
def gs_restore_autosave(_n, data):
    # 復元するものがなくても ready フラグは立てる（以降の保存を許可）
    if not data:
        return (no_update,) * 7 + (True,)
    preset_value = data.get("preset_value")
    qty = data.get("qty") or {}
    use = data.get("use") or {}
    ranks = data.get("ranks") or {}
    remain = data.get("remain") or {}
    saved_order = data.get("order") or []

    if not preset_value:
        # プリセット未選択でも所持数・使用フラグは復元する
        gifts = load_gifts()
        gift_list = build_gs_gift_list(
            gifts,
            lambda g: gs_default_used(g),
            qty_by_gift=qty,
            use_by_gift=use,
        )
        return (
            None,
            no_update,
            no_update,
            no_update,
            no_update,
            gift_list,
            no_update,
            True,
        )

    (
        costume_children,
        present_children,
        feedback,
        store,
        gift_list,
        order,
    ) = _gs_build_view(
        preset_value,
        ranks=ranks,
        qty=qty,
        use=use,
        remain=remain,
        order=saved_order,
    )
    if store is None:
        return (no_update,) * 7 + (True,)
    return (
        _dropdown_student(preset_value),
        costume_children,
        present_children,
        feedback,
        store,
        gift_list,
        order,
        True,
    )


@callback(
    Output("gs-costume-display", "children", allow_duplicate=True),
    Output("gs-costume-order", "data", allow_duplicate=True),
    Input({"type": "gs-move-up", "index": ALL}, "n_clicks"),
    Input({"type": "gs-move-down", "index": ALL}, "n_clicks"),
    State("gs-loaded-preset", "data"),
    State("gs-costume-order", "data"),
    State({"type": "gs-bond-rank", "index": ALL}, "value"),
    State({"type": "gs-bond-rank", "index": ALL}, "id"),
    State({"type": "gs-bond-remain", "index": ALL}, "value"),
    State({"type": "gs-bond-remain", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def gs_reorder_costumes(
    up_clicks,
    down_clicks,
    loaded,
    order,
    rank_values,
    rank_ids,
    remain_values,
    remain_ids,
):
    """▲▼ で衣装の優先順位（同点時のタイブレーク順）を入れ替える。

    入力値は衣装 index をキーに引き継ぐので、並び替えても入力は動かない。
    """
    trigger = ctx.triggered_id
    if not isinstance(trigger, dict) or not loaded:
        raise PreventUpdate
    # 行の再生成直後にもボタン追加で発火するため、実クリックのみ処理
    if not (ctx.triggered and ctx.triggered[0]["value"]):
        raise PreventUpdate
    costumes = loaded.get("costumes") or []
    order = _gs_normalize_order(order, len(costumes))
    ci = trigger["index"]
    if ci not in order:
        raise PreventUpdate
    pos = order.index(ci)
    new_pos = pos - 1 if trigger["type"] == "gs-move-up" else pos + 1
    if not 0 <= new_pos < len(order):
        raise PreventUpdate
    order[pos], order[new_pos] = order[new_pos], order[pos]
    return (
        _gs_costume_rows(
            costumes,
            rank_by_index=_values_by_index(rank_values, rank_ids),
            remain_by_index=_values_by_index(remain_values, remain_ids),
            order=order,
        ),
        order,
    )


def _rank_bg(rank: int) -> str:
    """最終絆ランクの色分け。"""
    if rank >= 50:
        return "#ffd54f"
    if rank >= 40:
        return "#aed581"
    if rank >= 30:
        return "#dce775"
    if rank >= 20:
        return "#fff59d"
    if rank >= 10:
        return "#ffcc80"
    return "#ef9a9a"


_TH = {
    "border": "1px solid #ccc",
    "padding": "4px 8px",
    "background": "#3498db",
    "color": "white",
    "fontSize": "0.8rem",
    "whiteSpace": "nowrap",
}
_TD = {
    "border": "1px solid #ddd",
    "padding": "4px 8px",
    "textAlign": "center",
    "fontSize": "0.82rem",
}
_TD_LABEL = {**_TD, "textAlign": "left", "whiteSpace": "nowrap"}


def _gs_result_table(
    col_names: list,
    used_gifts: list,
    allocation: list,
    final_ranks: list,
    other_normal_alloc=None,
    other_high_alloc=None,
    extra_rows: list | None = None,
) -> html.Table:
    """贈り物×衣装の配分マトリクス（MILP 解）。

    other_normal_alloc / other_high_alloc が list（衣装ごとの配分数）なら
    その他(通常)/その他(高級) の集約行として表示する。None なら非表示。
    extra_rows は (ラベル, 衣装ごとの個数リスト) の列で、最終絆ランク行の
    直前に強調表示で追加する（不足ボックス数など）。
    """
    ncol = len(col_names)

    header = html.Tr(
        [html.Th("贈り物 ＼ 衣装", style=_TH)]
        + [html.Th(n, style={**_TH, "verticalAlign": "bottom"}) for n in col_names]
    )

    body = []
    for gi, g in enumerate(used_gifts):
        label = html.Td(
            html.Div(
                [
                    html.Img(
                        src=gift_image_src(g),
                        title=g["name"],
                        style={
                            "width": "28px",
                            "height": "22px",
                            "objectFit": "contain",
                        },
                    ),
                    html.Span(
                        g["name"],
                        style={"fontSize": "0.78rem", "marginLeft": "6px"},
                    ),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            style=_TD_LABEL,
        )
        body.append(
            html.Tr(
                [label]
                + [html.Td(str(allocation[gi][ci]), style=_TD) for ci in range(ncol)]
            )
        )

    # その他(通常)/その他(高級) 集約行（使用ON・非好み・非all・非boxを集約）
    if other_normal_alloc is not None:
        body.append(
            html.Tr(
                [html.Td("その他(通常)", style=_TD_LABEL)]
                + [
                    html.Td(str(other_normal_alloc[ci]), style=_TD)
                    for ci in range(ncol)
                ]
            )
        )
    if other_high_alloc is not None:
        body.append(
            html.Tr(
                [html.Td("その他(高級)", style=_TD_LABEL)]
                + [html.Td(str(other_high_alloc[ci]), style=_TD) for ci in range(ncol)]
            )
        )

    for label_text, counts in extra_rows or []:
        body.append(
            html.Tr(
                [html.Td(label_text, style={**_TD_LABEL, "fontWeight": "bold"})]
                + [
                    html.Td(
                        str(counts[ci]),
                        style={**_TD, "fontWeight": "bold", "background": "#f3e5f5"},
                    )
                    for ci in range(ncol)
                ]
            )
        )

    # 最終絆ランク行（色分け）
    rank_cells = [
        html.Td(
            str(final_ranks[ci]),
            style={
                **_TD,
                "fontWeight": "bold",
                "background": _rank_bg(final_ranks[ci]),
            },
        )
        for ci in range(ncol)
    ]
    body.append(
        html.Tr(
            [html.Td("最終絆ランク", style={**_TD_LABEL, "fontWeight": "bold"})]
            + rank_cells
        )
    )

    return html.Table(
        [html.Thead(header), html.Tbody(body)],
        style={"borderCollapse": "collapse", "marginTop": "8px"},
    )


def _gs_parse_current_ranks(
    rank_values, rank_ids, n: int, default: int = 20
) -> list[int]:
    """現在の絆ランク入力を衣装 index 順のリストにする（不正値は default）。

    絆ボーナスは 50 までなので、51 以上は 50 として扱う。
    """
    rank_by_idx = {rid["index"]: rv for rv, rid in zip(rank_values, rank_ids)}
    current_ranks = []
    for i in range(n):
        v = rank_by_idx.get(i)
        try:
            v = int(v)
        except (TypeError, ValueError):
            v = default
        current_ranks.append(min(50, max(1, v)))
    return current_ranks


def _gs_parse_remaining_exp(remain_values, remain_ids, n: int) -> list[int | None]:
    """次の絆上昇までの残り経験値入力を衣装 index 順のリストにする。

    未入力/不正/0以下は None（= 通常どおりレベル満額を要求）。
    """
    remain_by_idx = {rid["index"]: rv for rv, rid in zip(remain_values, remain_ids)}
    remaining_exp: list[int | None] = []
    for i in range(n):
        rv = remain_by_idx.get(i)
        try:
            rv = int(rv)
        except (TypeError, ValueError):
            rv = None
        if rv is not None and rv <= 0:
            rv = None
        remaining_exp.append(rv)
    return remaining_exp


def _gs_box_values(costumes: list[dict], present: dict, type_by_id: dict) -> list[int]:
    """衣装ごとの 贈り物選択ボックス1個あたり獲得EXP。"""
    values = []
    for c in costumes:
        tiers = present.get(c["costume_name"], {})
        rows = [(type_by_id.get(gid, ""), tier) for gid, tier in tiers.items()]
        values.append(gift_select_box_exp(rows))
    return values


def _gs_build_gift_inputs(
    costumes: list[dict],
    present: dict,
    catalog: list[dict],
    use_values,
    use_ids,
    qty_values,
    qty_ids,
):
    """使用ON贈り物を MILP 入力（個別 + プール集約）へ変換する。

    使用ON贈り物を「個別」と「その他(集約)」に振り分ける。
     個別     : 好み(present) / all型 / 贈り物選択ボックス
     その他通常: 上記以外の素 normal（非好み=一律20EXP相当）
     その他高級: 上記以外の素 high （非好み=一律120EXP相当）

    Returns
    -------
    (individual_gifts, value, gift_qty, pool_idx_normal, pool_idx_high)
        individual_gifts : 個別扱いの贈り物（カタログ行）
        value / gift_qty : プール擬似贈り物 2 行を含む MILP 入力
        pool_idx_normal / pool_idx_high : プール行の index（無ければ None）
    """
    used_ids = {
        uid["gift"] for uid, val in zip(use_ids, use_values) if val and "use" in val
    }
    qty_by_gift = {}
    for qid, qv in zip(qty_ids, qty_values):
        try:
            qty_by_gift[qid["gift"]] = max(0, int(qv))
        except (TypeError, ValueError):
            qty_by_gift[qid["gift"]] = 0

    type_by_id = {g["id"]: g["gift_type"] for g in catalog}
    preferred = {gid for tiers in present.values() for gid in tiers}
    ncol = len(costumes)

    individual_gifts = []
    pool_normal_qty = 0
    pool_high_qty = 0
    has_pool_normal = False
    has_pool_high = False
    for g in catalog:
        if g["id"] not in used_ids:
            continue
        gtype = g["gift_type"]
        is_individual = (
            g["id"] == GIFT_SELECT_BOX_ID or "all" in gtype or g["id"] in preferred
        )
        if is_individual:
            individual_gifts.append(g)
        elif gtype == "normal":
            has_pool_normal = True
            pool_normal_qty += qty_by_gift.get(g["id"], 0)
        elif gtype == "high":
            has_pool_high = True
            pool_high_qty += qty_by_gift.get(g["id"], 0)

    # 価値行列 value[g][c]（個別贈り物）
    value = []
    for g in individual_gifts:
        row = []
        for c in costumes:
            tiers = present.get(c["costume_name"], {})
            if g["id"] == GIFT_SELECT_BOX_ID:
                rows = [(type_by_id.get(gid, ""), tier) for gid, tier in tiers.items()]
                row.append(gift_select_box_exp(rows))
            else:
                row.append(gift_exp(g["gift_type"], tiers.get(g["id"])))
        value.append(row)
    gift_qty = [qty_by_gift.get(g["id"], 0) for g in individual_gifts]

    # その他 集約の擬似贈り物（全衣装一律 EXP）。
    other_normal_exp = gift_exp("normal", None)  # 20
    other_high_exp = gift_exp("high", None)  # 120
    pool_idx_normal = pool_idx_high = None
    if has_pool_normal:
        pool_idx_normal = len(value)
        value.append([other_normal_exp] * ncol)
        gift_qty.append(pool_normal_qty)
    if has_pool_high:
        pool_idx_high = len(value)
        value.append([other_high_exp] * ncol)
        gift_qty.append(pool_high_qty)

    return individual_gifts, value, gift_qty, pool_idx_normal, pool_idx_high


@callback(
    Output("gs-calc-result", "children"),
    Input("gs-calc-btn", "n_clicks"),
    State("gs-loaded-preset", "data"),
    State({"type": "gs-gift-use", "gift": ALL}, "value"),
    State({"type": "gs-gift-use", "gift": ALL}, "id"),
    State({"type": "gs-gift-qty", "gift": ALL}, "value"),
    State({"type": "gs-gift-qty", "gift": ALL}, "id"),
    State({"type": "gs-bond-rank", "index": ALL}, "value"),
    State({"type": "gs-bond-rank", "index": ALL}, "id"),
    State({"type": "gs-bond-remain", "index": ALL}, "value"),
    State({"type": "gs-bond-remain", "index": ALL}, "id"),
    State("gs-costume-order", "data"),
    prevent_initial_call=True,
)
def gs_calculate(
    n_clicks,
    loaded,
    use_values,
    use_ids,
    qty_values,
    qty_ids,
    rank_values,
    rank_ids,
    remain_values,
    remain_ids,
    order,
):
    """MILP(SCIP) で贈り物配分を最適化し、マトリクスを表示する。

    衣装の表示順がそのまま優先順位で、絆ボーナス合計・使用個数が同点なら
    順位が上の衣装の絆ランクが高くなる配分を選ぶ（タイブレーク）。
    """
    if not loaded:
        return html.Span("先にプリセットを読み込んでください。", style={"color": "red"})

    costumes = loaded.get("costumes", [])
    if not costumes:
        return html.Span("衣装がありません。", style={"color": "red"})

    # 現在の絆ランク / 次の絆上昇までの残り経験値（衣装index順）
    current_ranks = _gs_parse_current_ranks(rank_values, rank_ids, len(costumes))
    remaining_exp = _gs_parse_remaining_exp(remain_values, remain_ids, len(costumes))

    student = loaded["student_name"]
    status_name = loaded["status_name"]
    present = get_preset_present(student, status_name)  # 衣装名->{gift:tier}
    (
        individual_gifts,
        value,
        gift_qty,
        pool_idx_normal,
        pool_idx_high,
    ) = _gs_build_gift_inputs(
        costumes, present, load_gifts(), use_values, use_ids, qty_values, qty_ids
    )

    bond_bonuses = [c["bond_bonuses"] for c in costumes]

    # 表示順（上が最優先）を 1 始まりの優先順位に変換する
    order = _gs_normalize_order(order, len(costumes))
    priorities = [0] * len(costumes)
    for pos, ci in enumerate(order):
        priorities[ci] = pos + 1

    try:
        result = solve_gift_distribution(
            current_ranks,
            bond_bonuses,
            gift_qty,
            value,
            remaining_exp=remaining_exp,
            costume_priorities=priorities,
        )
    except Exception as e:
        return html.Span(f"計算エラー: {e}", style={"color": "red"})

    status = result["status"]
    if status not in ("optimal", "timelimit"):
        return html.Span(
            f"解を得られませんでした（SCIP: {status}）。",
            style={"color": "red"},
        )

    alloc = result["allocation"]
    n_ind = len(individual_gifts)

    # 列は入力と同じ優先順位（上の行 = 左の列）で並べる
    def _cols(row):
        return [row[ci] for ci in order]

    other_normal_alloc = (
        _cols(alloc[pool_idx_normal]) if pool_idx_normal is not None else None
    )
    other_high_alloc = (
        _cols(alloc[pool_idx_high]) if pool_idx_high is not None else None
    )

    labels = _nc_costume_labels()
    col_names = [
        _student_header(
            labels.get(costumes[ci].get("costume_id"), ""),
            costumes[ci]["costume_name"],
        )
        for ci in order
    ]
    table = _gs_result_table(
        col_names,
        individual_gifts,
        [_cols(row) for row in alloc[:n_ind]],
        _cols(result["final_ranks"]),
        other_normal_alloc,
        other_high_alloc,
    )
    status_note = []
    if status == "optimal":
        status_note.append(
            html.Span(
                "（SCIP: 最適）",
                style={"color": "#888", "fontSize": "0.8rem"},
            )
        )
    elif status == "timelimit":
        status_note.append(
            html.Span(
                "（時間制限到達: 暫定解。最適とは限りません）",
                style={"color": "#e67e22", "fontSize": "0.8rem"},
            )
        )
    else:
        status_note.append(
            html.Span(
                f"（SCIP: {status}）",
                style={"color": "#888", "fontSize": "0.8rem"},
            )
        )
    summary = html.Div(
        [
            html.Span(
                f"絆ボーナス上昇量 合計: +{result['total_gain']}",
                style={"fontWeight": "bold", "marginRight": "12px"},
            ),
            *status_note,
        ],
        style={"margin": "4px 0"},
    )
    return html.Div([summary, table])


# ----------------------------------------------------------------------
# 必要絆経験値ページ
# ----------------------------------------------------------------------

# ボックス1個あたり獲得EXP -> 効果ラベル（gift_exp の normal タイプ対応）
_RB_BOX_EXP_LABEL = {20: "小", 40: "中", 60: "大", 80: "特大"}

_RB_DEFAULT_CURRENT_RANK = 20
_RB_DEFAULT_TARGET_RANK = 50

_RB_EMPTY_MSG = html.P(
    "生徒（衣装）を追加してください。",
    style={"color": "#888", "margin": "8px 0"},
)


def _rb_costume_rows(entries: list[dict], ranks=None, remains=None, targets=None):
    """追加済み生徒（衣装）ごとの 現在絆ランク / 残りEXP / 目標絆ランク /
    並び替え・削除ボタン の入力行を生成。並び順がそのまま優先順位
    （上が最優先）。ranks/remains/targets は入力値の引き継ぎ用
    （index -> 値）。空なら案内メッセージを返す。
    """
    if not entries:
        return _RB_EMPTY_MSG
    ranks = ranks or {}
    remains = remains or {}
    targets = targets or {}
    n = len(entries)
    rows = []
    for i, e in enumerate(entries):
        rows.append(
            html.Div(
                [
                    html.Span(
                        f"{i + 1}.",
                        title="優先順位（上の衣装ほど所持贈り物を優先的に充当）",
                        className="costume-pos",
                    ),
                    html.Button(
                        "▲",
                        id={"type": "rb-move-up", "index": i},
                        n_clicks=0,
                        disabled=i == 0,
                        title="優先順位を上げる",
                        className="move-btn",
                    ),
                    html.Button(
                        "▼",
                        id={"type": "rb-move-down", "index": i},
                        n_clicks=0,
                        disabled=i == n - 1,
                        title="優先順位を下げる",
                        className="move-btn",
                    ),
                    html.Strong(
                        _with_student_icon(e["label"]), className="costume-name"
                    ),
                    dcc.Input(
                        id={"type": "rb-bond-rank", "index": i},
                        type="number",
                        min=1,
                        max=MAX_RANK,
                        value=ranks.get(i, _RB_DEFAULT_CURRENT_RANK),
                        debounce=True,
                    ),
                    dcc.Input(
                        id={"type": "rb-bond-remain", "index": i},
                        type="number",
                        min=1,
                        value=remains.get(i),
                        debounce=True,
                        placeholder="任意",
                    ),
                    dcc.Input(
                        id={"type": "rb-bond-target", "index": i},
                        type="number",
                        min=1,
                        max=50,
                        value=targets.get(i, _RB_DEFAULT_TARGET_RANK),
                        debounce=True,
                    ),
                    html.Button(
                        "✕",
                        id={"type": "rb-remove-costume", "index": i},
                        n_clicks=0,
                        title="この衣装を削除",
                        className="icon-btn",
                    ),
                ],
                className="costume-row rb-grid",
            )
        )
    return rows


def _rb_swap_indices(by_index: dict[int, object], i: int, j: int) -> dict[int, object]:
    """index i と j の値を入れ替える（未入力 = キーなし も入れ替える）。"""
    out = {k: v for k, v in by_index.items() if k not in (i, j)}
    if j in by_index:
        out[i] = by_index[j]
    if i in by_index:
        out[j] = by_index[i]
    return out


def _values_by_index(values, ids) -> dict[int, object]:
    """パターンマッチ入力を {index: 値} にまとめる（None は除外）。"""
    return {vid["index"]: v for v, vid in zip(values, ids) if v is not None}


def _rb_preferred(entries: list[dict]) -> set[str]:
    """追加済み衣装の好物 gift_id の和集合。"""
    return {gid for e in entries for gid in get_costume_present_map(e["costume_id"])}


def _rb_merge_use_flags(catalog, use_by_gift, old_pref, new_pref) -> dict[str, bool]:
    """衣装の増減で変わる使用フラグ既定値を反映する。

    ユーザーが旧既定値から明示的に変更したフラグはそのまま保持し、
    既定値のままだった贈り物のみ新しい既定値（新しい好物の和集合に
    基づく）へ更新する。
    """
    out = {}
    for g in catalog:
        gid = g["id"]
        old_def = gs_default_used(g, old_pref)
        cur = use_by_gift.get(gid, old_def)
        out[gid] = cur if cur != old_def else gs_default_used(g, new_pref)
    return out


def _rb_shift_indices(by_index: dict[int, object], removed: int) -> dict[int, object]:
    """removed 番目の行を除いた後の index 詰め替えを行う。"""
    out = {}
    for idx, v in by_index.items():
        if idx == removed:
            continue
        out[idx - 1 if idx > removed else idx] = v
    return out


@callback(
    Output("rb-costume-container", "children"),
    Output("rb-costumes", "data"),
    Output("rb-add-feedback", "children"),
    Output("rb-gift-list", "children", allow_duplicate=True),
    Input("rb-add-costume-btn", "n_clicks"),
    Input({"type": "rb-remove-costume", "index": ALL}, "n_clicks"),
    Input({"type": "rb-move-up", "index": ALL}, "n_clicks"),
    Input({"type": "rb-move-down", "index": ALL}, "n_clicks"),
    State("rb-costume-dropdown", "value"),
    State("rb-costumes", "data"),
    State({"type": "rb-bond-rank", "index": ALL}, "value"),
    State({"type": "rb-bond-rank", "index": ALL}, "id"),
    State({"type": "rb-bond-remain", "index": ALL}, "value"),
    State({"type": "rb-bond-remain", "index": ALL}, "id"),
    State({"type": "rb-bond-target", "index": ALL}, "value"),
    State({"type": "rb-bond-target", "index": ALL}, "id"),
    State({"type": "rb-gift-qty", "gift": ALL}, "value"),
    State({"type": "rb-gift-qty", "gift": ALL}, "id"),
    State({"type": "rb-gift-use", "gift": ALL}, "value"),
    State({"type": "rb-gift-use", "gift": ALL}, "id"),
    State("bond-ranks", "data"),
    prevent_initial_call=True,
)
def rb_update_costumes(
    add_clicks,
    remove_clicks,
    move_up_clicks,
    move_down_clicks,
    dropdown_value,
    entries,
    rank_values,
    rank_ids,
    remain_values,
    remain_ids,
    target_values,
    target_ids,
    qty_values,
    qty_ids,
    use_values,
    use_ids,
    bond_ranks,
):
    """生徒（衣装）の追加・削除・並び替え（▲▼）。既存行の入力値は引き継ぐ。
    追加した衣装の絆ランクが絆ランク管理で設定済みなら、その値を初期値にする。

    並び順がそのまま優先順位（上が最優先）。贈り物リストは新しい
    衣装構成の好物に合わせて使用フラグの既定値を更新して再構築する
    （所持数と、ユーザーが明示変更したフラグは保持）。
    """
    trigger = ctx.triggered_id
    entries = list(entries or [])
    ranks = _values_by_index(rank_values, rank_ids)
    remains = _values_by_index(remain_values, remain_ids)
    targets = _values_by_index(target_values, target_ids)

    def _rebuild_gift_list(old_entries):
        catalog = load_gifts()
        qty, use = _gift_inputs_to_maps(qty_values, qty_ids, use_values, use_ids)
        old_pref = _rb_preferred(old_entries)
        new_pref = _rb_preferred(entries)
        return build_gs_gift_list(
            catalog,
            lambda g: gs_default_used(g, new_pref),
            qty_by_gift=qty,
            use_by_gift=_rb_merge_use_flags(catalog, use, old_pref, new_pref),
            id_prefix="rb",
        )

    if trigger == "rb-add-costume-btn":
        if dropdown_value is None:
            return (
                no_update,
                no_update,
                html.Span("生徒（衣装）を選択してください。", style={"color": "red"}),
                no_update,
            )
        if any(e["costume_id"] == dropdown_value for e in entries):
            return (
                no_update,
                no_update,
                html.Span("既に追加されています。", style={"color": "red"}),
                no_update,
            )
        label = get_costume_label(dropdown_value)
        if not label:
            return (
                no_update,
                no_update,
                html.Span("衣装が見つかりません。", style={"color": "red"}),
                no_update,
            )
        old_entries = list(entries)
        entries.append({"costume_id": dropdown_value, "label": label})
        ranks, remains, _ = _overlay_bond_ranks(
            bond_ranks,
            [None] * (len(entries) - 1) + [dropdown_value],
            ranks,
            remains,
        )
        return (
            _rb_costume_rows(entries, ranks, remains, targets),
            entries,
            "",
            _rebuild_gift_list(old_entries),
        )

    if isinstance(trigger, dict) and trigger.get("type") == "rb-remove-costume":
        # 行の再生成直後にもボタン追加で発火するため、実クリックのみ処理
        triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None
        if not triggered_value:
            raise PreventUpdate
        removed = trigger["index"]
        if removed >= len(entries):
            raise PreventUpdate
        old_entries = list(entries)
        entries.pop(removed)
        return (
            _rb_costume_rows(
                entries,
                _rb_shift_indices(ranks, removed),
                _rb_shift_indices(remains, removed),
                _rb_shift_indices(targets, removed),
            ),
            entries,
            "",
            _rebuild_gift_list(old_entries),
        )

    if isinstance(trigger, dict) and trigger.get("type") in (
        "rb-move-up",
        "rb-move-down",
    ):
        # 行の再生成直後にもボタン追加で発火するため、実クリックのみ処理
        triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None
        if not triggered_value:
            raise PreventUpdate
        i = trigger["index"]
        j = i - 1 if trigger["type"] == "rb-move-up" else i + 1
        if not (0 <= i < len(entries) and 0 <= j < len(entries)):
            raise PreventUpdate
        entries[i], entries[j] = entries[j], entries[i]
        return (
            _rb_costume_rows(
                entries,
                _rb_swap_indices(ranks, i, j),
                _rb_swap_indices(remains, i, j),
                _rb_swap_indices(targets, i, j),
            ),
            entries,
            "",
            no_update,
        )

    raise PreventUpdate


@callback(
    Output("rb-costume-container", "children", allow_duplicate=True),
    Output("rb-bond-ranks-feedback", "children"),
    Input("rb-apply-bond-ranks-btn", "n_clicks"),
    State("bond-ranks", "data"),
    State("rb-costumes", "data"),
    State({"type": "rb-bond-rank", "index": ALL}, "value"),
    State({"type": "rb-bond-rank", "index": ALL}, "id"),
    State({"type": "rb-bond-remain", "index": ALL}, "value"),
    State({"type": "rb-bond-remain", "index": ALL}, "id"),
    State({"type": "rb-bond-target", "index": ALL}, "value"),
    State({"type": "rb-bond-target", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def rb_apply_bond_ranks(
    n_clicks,
    bond_ranks,
    entries,
    rank_values,
    rank_ids,
    remain_values,
    remain_ids,
    target_values,
    target_ids,
):
    """絆ランク管理で設定済みの衣装の絆ランクで入力欄を
    上書きする（目標は保持）。"""
    if not n_clicks:
        raise PreventUpdate
    entries = list(entries or [])
    if not entries:
        return no_update, html.Span(
            "生徒（衣装）を追加してください。", style={"color": "red"}
        )
    ranks, remains, n = _overlay_bond_ranks(
        bond_ranks,
        [e["costume_id"] for e in entries],
        _values_by_index(rank_values, rank_ids),
        _values_by_index(remain_values, remain_ids),
    )
    return (
        _rb_costume_rows(
            entries, ranks, remains, _values_by_index(target_values, target_ids)
        ),
        _bond_ranks_applied_feedback(n),
    )


@callback(
    Output("bond-ranks", "data", allow_duplicate=True),
    Output("rb-bond-ranks-feedback", "children", allow_duplicate=True),
    Input("rb-save-bond-ranks-btn", "n_clicks"),
    State("bond-ranks", "data"),
    State("rb-costumes", "data"),
    State({"type": "rb-bond-rank", "index": ALL}, "value"),
    State({"type": "rb-bond-rank", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def rb_save_bond_ranks(n_clicks, bond_ranks, entries, rank_values, rank_ids):
    """入力中の絆ランクを絆ランク管理に保存する。"""
    if not n_clicks:
        raise PreventUpdate
    entries = list(entries or [])
    if not entries:
        return no_update, html.Span(
            "生徒（衣装）を追加してください。", style={"color": "red"}
        )
    saved, n = _save_inputs_to_bond_ranks(
        bond_ranks,
        [e["costume_id"] for e in entries],
        _values_by_index(rank_values, rank_ids),
    )
    return (saved if n else no_update), _bond_ranks_saved_feedback(n)


@callback(
    Output("rb-calc-result", "children"),
    Input("rb-calc-btn", "n_clicks"),
    State("rb-costumes", "data"),
    State({"type": "rb-bond-rank", "index": ALL}, "value"),
    State({"type": "rb-bond-rank", "index": ALL}, "id"),
    State({"type": "rb-bond-remain", "index": ALL}, "value"),
    State({"type": "rb-bond-remain", "index": ALL}, "id"),
    State({"type": "rb-bond-target", "index": ALL}, "value"),
    State({"type": "rb-bond-target", "index": ALL}, "id"),
    State({"type": "rb-gift-use", "gift": ALL}, "value"),
    State({"type": "rb-gift-use", "gift": ALL}, "id"),
    State({"type": "rb-gift-qty", "gift": ALL}, "value"),
    State({"type": "rb-gift-qty", "gift": ALL}, "id"),
    prevent_initial_call=True,
)
def rb_calculate(
    n_clicks,
    entries,
    rank_values,
    rank_ids,
    remain_values,
    remain_ids,
    target_values,
    target_ids,
    use_values,
    use_ids,
    qty_values,
    qty_ids,
):
    """生徒（衣装）ごとに目標絆ランクまでの必要絆経験値を計算する。

    使用ONの所持贈り物（選択ボックス含む）を MILP で最適に充当した上で、
    不足する絆経験値と、その贈り物選択ボックス換算の個数（最小）を表示する。
    """
    entries = entries or []
    if not entries:
        return html.Span("先に生徒（衣装）を追加してください。", style={"color": "red"})

    n = len(entries)
    current_ranks = _gs_parse_current_ranks(
        rank_values, rank_ids, n, default=_RB_DEFAULT_CURRENT_RANK
    )
    remaining_exp = _gs_parse_remaining_exp(remain_values, remain_ids, n)
    target_ranks = _gs_parse_current_ranks(
        target_values, target_ids, n, default=_RB_DEFAULT_TARGET_RANK
    )
    # 並び順がそのまま優先順位（上の行 = 順位1 が最優先）
    priorities = list(range(1, n + 1))

    # _gs_build_gift_inputs / _gs_box_values を流用するため、
    # 衣装リストと present を {表示名: {gift_id: tier}} 形式に揃える
    costumes = [{"costume_name": e["label"]} for e in entries]
    present = {e["label"]: get_costume_present_map(e["costume_id"]) for e in entries}
    catalog = load_gifts()
    type_by_id = {g["id"]: g["gift_type"] for g in catalog}
    box_values = _gs_box_values(costumes, present, type_by_id)
    (
        individual_gifts,
        value,
        gift_qty,
        pool_idx_normal,
        pool_idx_high,
    ) = _gs_build_gift_inputs(
        costumes, present, catalog, use_values, use_ids, qty_values, qty_ids
    )

    try:
        result = solve_required_boxes(
            current_ranks,
            [[0] * len(BOND_RANGES) for _ in range(n)],  # 絆ボーナスは不使用
            gift_qty,
            value,
            box_values,
            target_ranks=target_ranks,
            remaining_exp=remaining_exp,
            box_priorities=priorities,
        )
    except Exception as e:
        return html.Span(f"計算エラー: {e}", style={"color": "red"})

    status = result["status"]
    if status not in ("optimal", "timelimit"):
        return html.Span(
            f"解を得られませんでした（SCIP: {status}）。",
            style={"color": "red"},
        )

    alloc = result["allocation"]
    boxes = result["boxes"]
    # 衣装ごとの所持贈り物からの獲得EXP
    covered = [
        sum(value[g][c] * alloc[g][c] for g in range(len(gift_qty))) for c in range(n)
    ]

    header = html.Tr(
        [
            html.Th("生徒（衣装）", style=_TH),
            html.Th("現在 → 目標", style=_TH),
            html.Th("必要絆経験値", style=_TH),
            html.Th("所持贈り物で獲得", style=_TH),
            html.Th("不足絆経験値", style=_TH),
            html.Th("不足分ボックス換算", style=_TH),
        ]
    )
    body = []
    total_exp = 0
    total_covered = 0
    total_short = 0
    total_boxes = sum(boxes)
    for i, e in enumerate(entries):
        cur, tgt = current_ranks[i], target_ranks[i]
        need_exp = exp_to_reach_rank(cur, tgt, remaining_exp[i])
        short = max(0, need_exp - covered[i])
        total_exp += need_exp
        total_covered += covered[i]
        total_short += short
        box_exp = box_values[i]
        label = _RB_BOX_EXP_LABEL.get(box_exp)
        box_text = f"{boxes[i]:,} 個（1個={box_exp}" + (
            f" {label}）" if label else "）"
        )
        body.append(
            html.Tr(
                [
                    html.Td(
                        html.Div(
                            _with_student_icon(e["label"], size=24),
                            style={"display": "flex", "alignItems": "center"},
                        ),
                        style=_TD_LABEL,
                    ),
                    html.Td(f"絆{cur} → 絆{tgt}", style=_TD),
                    html.Td(
                        f"{need_exp:,}",
                        style={
                            **_TD,
                            "fontWeight": "bold",
                            "background": "#e3f2fd",
                        },
                    ),
                    html.Td(f"{covered[i]:,}", style=_TD),
                    html.Td(f"{short:,}", style=_TD),
                    html.Td(
                        box_text,
                        style={**_TD, "fontWeight": "bold", "background": "#f3e5f5"},
                    ),
                ]
            )
        )
    body.append(
        html.Tr(
            [
                html.Td("合計", style={**_TD_LABEL, "fontWeight": "bold"}),
                html.Td("－", style=_TD),
                html.Td(
                    f"{total_exp:,}",
                    style={**_TD, "fontWeight": "bold", "background": "#e3f2fd"},
                ),
                html.Td(f"{total_covered:,}", style={**_TD, "fontWeight": "bold"}),
                html.Td(f"{total_short:,}", style={**_TD, "fontWeight": "bold"}),
                html.Td(
                    f"{total_boxes:,} 個",
                    style={**_TD, "fontWeight": "bold", "background": "#f3e5f5"},
                ),
            ]
        )
    )
    note = []
    if status == "timelimit":
        note.append(
            html.Span(
                "（時間制限到達: 暫定解。最小とは限りません）",
                style={"color": "#e67e22", "fontSize": "0.8rem"},
            )
        )
    summary = html.Div(
        [
            html.Span(
                f"必要絆経験値: 合計 {total_exp:,} ／ "
                f"所持贈り物充当後の不足: {total_short:,}"
                f"（選択ボックス換算 {total_boxes:,} 個）",
                style={"fontWeight": "bold", "marginRight": "12px"},
            ),
            *note,
        ],
        style={"margin": "4px 0"},
    )
    table = html.Table(
        [html.Thead(header), html.Tbody(body)],
        style={"borderCollapse": "collapse", "marginTop": "8px"},
    )

    # 所持贈り物の配分内訳（折りたたみ）
    n_ind = len(individual_gifts)
    other_normal_alloc = (
        list(alloc[pool_idx_normal]) if pool_idx_normal is not None else None
    )
    other_high_alloc = list(alloc[pool_idx_high]) if pool_idx_high is not None else None
    detail = html.Details(
        [
            html.Summary(
                "所持贈り物の配分内訳",
                style={
                    "cursor": "pointer",
                    "fontSize": "0.9rem",
                    "margin": "12px 0 4px",
                },
            ),
            _gs_result_table(
                [_student_header(e["label"]) for e in entries],
                individual_gifts,
                alloc[:n_ind],
                result["final_ranks"],
                other_normal_alloc,
                other_high_alloc,
                extra_rows=[("追加ボックス（不足分）", boxes)],
            ),
        ]
    )
    return html.Div([summary, table, detail])


# ----------------------------------------------------------------------
# 必要絆経験値ページ: 入力保存（localStorage autosave）
# ----------------------------------------------------------------------


@callback(
    Output("rb-autosave", "data"),
    Input("rb-costumes", "data"),
    Input({"type": "rb-bond-rank", "index": ALL}, "value"),
    Input({"type": "rb-bond-remain", "index": ALL}, "value"),
    Input({"type": "rb-bond-target", "index": ALL}, "value"),
    Input({"type": "rb-gift-qty", "gift": ALL}, "value"),
    Input({"type": "rb-gift-use", "gift": ALL}, "value"),
    State({"type": "rb-bond-rank", "index": ALL}, "id"),
    State({"type": "rb-bond-remain", "index": ALL}, "id"),
    State({"type": "rb-bond-target", "index": ALL}, "id"),
    State({"type": "rb-gift-qty", "gift": ALL}, "id"),
    State({"type": "rb-gift-use", "gift": ALL}, "id"),
    State("rb-autosave-ready", "data"),
    prevent_initial_call=True,
)
def rb_save_autosave(
    entries,
    rank_values,
    remain_values,
    target_values,
    qty_values,
    use_values,
    rank_ids,
    remain_ids,
    target_ids,
    qty_ids,
    use_ids,
    ready,
):
    # 復元前の保存は禁止。動的レイアウト挿入直後は prevent_initial_call が
    # 効かず初期値で発火するため、そのまま保存すると復元前のデータが潰れる。
    if not ready:
        raise PreventUpdate
    qty, use = _gift_inputs_to_maps(qty_values, qty_ids, use_values, use_ids)
    return {
        "entries": entries or [],
        "ranks": {
            str(k): v for k, v in _values_by_index(rank_values, rank_ids).items()
        },
        "remain": {
            str(k): v for k, v in _values_by_index(remain_values, remain_ids).items()
        },
        "targets": {
            str(k): v for k, v in _values_by_index(target_values, target_ids).items()
        },
        "qty": qty,
        "use": use,
    }


def _rb_int_keys(by_index) -> dict[int, object]:
    """JSON化で文字列になった index キーを int に戻す。"""
    out = {}
    for k, v in (by_index or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            continue
    return out


@callback(
    Output("rb-costume-container", "children", allow_duplicate=True),
    Output("rb-costumes", "data", allow_duplicate=True),
    Output("rb-gift-list", "children"),
    Output("rb-autosave-ready", "data"),
    Input("rb-autosave-init", "n_intervals"),
    State("rb-autosave", "data"),
    prevent_initial_call=True,
)
def rb_restore_autosave(_n, data):
    # 復元するものがなくても ready フラグは立てる（以降の保存を許可）
    if not data:
        return no_update, no_update, no_update, True
    entries = data.get("entries") or []
    # 保存済みフラグを最優先で復元。保存に無い贈り物（後からカタログに
    # 追加された等）のみ好物ベースの既定値を使う。
    preferred = _rb_preferred(entries)
    gift_list = build_gs_gift_list(
        load_gifts(),
        lambda g: gs_default_used(g, preferred),
        qty_by_gift=data.get("qty") or {},
        use_by_gift=data.get("use") or {},
        id_prefix="rb",
    )
    if not entries:
        return no_update, no_update, gift_list, True
    rows = _rb_costume_rows(
        entries,
        _rb_int_keys(data.get("ranks")),
        _rb_int_keys(data.get("remain")),
        _rb_int_keys(data.get("targets")),
    )
    return rows, entries, gift_list, True


def _sort_options_with_favorites(options, favorites):
    """★付きお気に入りを先頭に固定したオプションリストを返す。"""
    fav_set = set(favorites or [])
    favs, others = [], []
    for opt in options:
        value = opt["value"]
        label = opt["label"]
        if value in fav_set:
            new_label = label if label.startswith("★") else f"★ {label}"
            favs.append({**opt, "label": new_label})
        else:
            others.append(opt)
    fav_order = {v: i for i, v in enumerate(favorites or [])}
    favs.sort(key=lambda o: fav_order.get(o["value"], 0))
    return favs + others


def _build_priority_data(order, costume_map):
    """Store に保存する優先度データを構築する。"""
    return [
        {"idx": idx, "name": costume_map.get(idx) or _default_costume_name(idx)}
        for idx in order
    ]


def _make_priority_cards(priority_data):
    """上下ボタン付き優先度カードリストを生成する。"""
    n = len(priority_data)
    btn_style = {
        "background": "none",
        "border": "1px solid #ccc",
        "borderRadius": "4px",
        "cursor": "pointer",
        "padding": "2px 8px",
        "fontSize": "0.8rem",
        "lineHeight": "1",
    }
    items = []
    for pos, entry in enumerate(priority_data):
        idx = entry["idx"] if isinstance(entry, dict) else entry
        name = entry["name"] if isinstance(entry, dict) else _default_costume_name(idx)
        items.append(
            html.Div(
                [
                    html.Span(
                        f"{pos + 1}.",
                        style={
                            "fontWeight": "bold",
                            "color": "#888",
                            "marginRight": "6px",
                            "minWidth": "20px",
                        },
                    ),
                    html.Span(name, style={"flex": "1"}),
                    html.Button(
                        "▲",
                        id={"type": "priority-up", "index": idx},
                        n_clicks=0,
                        disabled=pos == 0,
                        style=btn_style,
                    ),
                    html.Button(
                        "▼",
                        id={"type": "priority-down", "index": idx},
                        n_clicks=0,
                        disabled=pos == n - 1,
                        style=btn_style,
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "6px",
                    "padding": "6px 12px",
                    "background": "#e8f5e9",
                    "border": "1px solid #a5d6a7",
                    "borderRadius": "6px",
                    "fontSize": "0.85rem",
                },
            )
        )
    return items


@callback(
    Output("students-container", "children"),
    Output("student-indices", "data"),
    Output("next-student-index", "data"),
    Output("bond-rank-container", "children"),
    Output("costume-priority-order", "data"),
    Output("chart-result", "children", allow_duplicate=True),
    Output("present-display", "children"),
    Input("add-student-btn", "n_clicks"),
    Input({"type": "remove-student", "index": ALL}, "n_clicks"),
    Input("load-preset-btn", "n_clicks"),
    State("student-indices", "data"),
    State("next-student-index", "data"),
    State("students-container", "children"),
    State("preset-dropdown", "value"),
    State("preset-status-radio", "value"),
    State({"type": "bond-rank", "index": ALL}, "value"),
    State({"type": "bond-rank", "index": ALL}, "id"),
    State({"type": "costume", "index": ALL}, "value"),
    State({"type": "costume", "index": ALL}, "id"),
    State("costume-priority-order", "data"),
    State("bond-ranks", "data"),
    prevent_initial_call=True,
)
def update_students(
    add_clicks,
    remove_clicks,
    load_preset_clicks,
    indices,
    next_idx,
    children,
    preset_dropdown_value,
    preset_status_value,
    rank_values,
    rank_ids,
    costume_values,
    costume_ids,
    priority_order,
    bond_ranks,
):
    trigger = ctx.triggered_id

    # 現在のユーザー入力値をマップに保持
    rank_map = {rid["index"]: rv for rv, rid in zip(rank_values, rank_ids)}
    costume_map = {cid["index"]: cv for cv, cid in zip(costume_values, costume_ids)}

    # priority_order から idx リストを取得
    old_idx_order = [e["idx"] if isinstance(e, dict) else e for e in priority_order]

    if trigger == "add-student-btn":
        indices.append(next_idx)
        children.append(make_student_card(next_idx))
        rank_children = [
            _make_bond_rank_input(
                idx,
                costume_name=costume_map.get(idx, ""),
                value=rank_map.get(idx, 20),
            )
            for idx in indices
        ]
        new_order = [i for i in old_idx_order if i in indices] + [next_idx]
        priority_data = _build_priority_data(new_order, costume_map)
        return (
            children,
            indices,
            next_idx + 1,
            rank_children,
            priority_data,
            no_update,
            no_update,
        )

    if isinstance(trigger, dict) and trigger.get("type") == "remove-student":
        triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None
        if not triggered_value:
            raise PreventUpdate
        if len(indices) <= 1:
            raise PreventUpdate
        remove_idx = trigger["index"]
        indices = [i for i in indices if i != remove_idx]
        children = [
            c
            for c in children
            if not (
                c["props"]["id"].get("type") == "student-card"
                and c["props"]["id"].get("index") == remove_idx
            )
        ]
        rank_children = [
            _make_bond_rank_input(
                idx,
                costume_name=costume_map.get(idx, ""),
                value=rank_map.get(idx, 20),
            )
            for idx in indices
        ]
        new_order = [i for i in old_idx_order if i != remove_idx]
        priority_data = _build_priority_data(new_order, costume_map)
        return (
            children,
            indices,
            next_idx,
            rank_children,
            priority_data,
            no_update,
            no_update,
        )

    if trigger == "load-preset-btn":
        preset_name = _combined_preset_value(preset_dropdown_value, preset_status_value)
        if not preset_name:
            raise PreventUpdate
        result = get_preset_data(preset_name)
        if not result:
            raise PreventUpdate
        display_name, students = result
        # 絆ランク管理で設定済みの衣装は保存値を初期値にする
        saved_ranks = ranks_for_costumes(
            bond_ranks, [s.get("costume_id") for s in students]
        )
        new_children = []
        new_indices = []
        new_rank_children = []
        preset_costume_map = {}
        for i, s in enumerate(students):
            new_children.append(
                make_student_card(
                    i,
                    costume_name=s["costume_name"],
                    bond_bonuses=s["bond_bonuses"],
                )
            )
            new_indices.append(i)
            new_rank_children.append(
                _make_bond_rank_input(
                    i,
                    costume_name=s["costume_name"],
                    value=saved_ranks.get(i, 20),
                    bond_bonuses=s["bond_bonuses"],
                )
            )
            preset_costume_map[i] = s["costume_name"]
        new_order = list(range(len(students)))
        priority_data = _build_priority_data(new_order, preset_costume_map)
        msg = html.P(
            f"プリセット「{display_name}」を読み込みました。",
            style={
                "color": "#27ae60",
                "fontWeight": "bold",
                "margin": "8px 0",
            },
        )
        return (
            new_children,
            new_indices,
            len(students),
            new_rank_children,
            priority_data,
            msg,
            _preset_present_children(preset_name, students),
        )

    raise PreventUpdate


@callback(
    Output({"type": "bond-rank-label", "index": ALL}, "children"),
    Output("co-costume-icons", "data"),
    Input({"type": "costume", "index": ALL}, "value"),
    Input("co-loaded-costumes", "data"),
    State({"type": "costume", "index": ALL}, "id"),
)
def sync_bond_rank_labels(costume_values, loaded, costume_ids):
    """絆ランク欄のラベルと結果表の生徒画像 {衣装 index: URL} を衣装名に合わせる。

    生徒画像はプリセットから読み込んだ衣装（衣装名が一致するもの）のみ。
    """
    cids = _co_costume_ids(loaded, costume_values, costume_ids, costume_ids)
    labels = _nc_costume_labels() if any(c is not None for c in cids) else {}
    student_labels = [labels.get(c, "") for c in cids]
    names = [
        v or _default_costume_name(cid["index"])
        for v, cid in zip(costume_values, costume_ids)
    ]
    icons = {
        cid["index"]: src
        for sl, cid in zip(student_labels, costume_ids)
        if (src := _student_icon_src(sl))
    }
    return (
        [_with_student_icon(sl, n) for sl, n in zip(student_labels, names)],
        icons,
    )


def _bond_view_texts(values, ids, view_ids) -> list[str]:
    """衣装カードの絆ボーナス入力値を、表の表示欄（view_ids の順）の文字列にする。

    表示欄と入力欄は {index, range_idx} で対応付ける（並び順に依存しない）。
    """
    by_key = {(i["index"], i["range_idx"]): v for v, i in zip(values, ids)}
    texts = []
    for vid in view_ids:
        v = by_key.get((vid["index"], vid["range_idx"]))
        if v is None or v == "":
            texts.append("－")
        elif isinstance(v, float) and v.is_integer():
            texts.append(str(int(v)))
        else:
            texts.append(str(v))
    return texts


@callback(
    Output({"type": "bond-view", "range_idx": ALL, "index": ALL}, "children"),
    Input({"type": "bond", "range_idx": ALL, "index": ALL}, "value"),
    State({"type": "bond", "range_idx": ALL, "index": ALL}, "id"),
)
def sync_bond_views(values, ids):
    """衣装カードで編集した絆ボーナスを、衣装と現在の絆ランクの表に反映する。"""
    view_ids = [o["id"] for o in ctx.outputs_list]
    return _bond_view_texts(values, ids, view_ids)


_BOND_RANK_BASE_STYLE = {"width": "50px", "textAlign": "center"}
_BOND_RANK_ERROR_STYLE = {
    **_BOND_RANK_BASE_STYLE,
    "border": "2px solid red",
    "color": "red",
}


@callback(
    Output({"type": "bond-rank", "index": ALL}, "style"),
    Input({"type": "bond-rank", "index": ALL}, "value"),
)
def validate_bond_rank_style(values):
    return [
        _BOND_RANK_ERROR_STYLE
        if v is None or not isinstance(v, (int, float)) or v < 1 or v > MAX_RANK
        else _BOND_RANK_BASE_STYLE
        for v in values
    ]


@callback(
    Output("costume-priority-container", "children"),
    Output("costume-priority-order", "data", allow_duplicate=True),
    Input("costume-priority-order", "data"),
    Input({"type": "priority-up", "index": ALL}, "n_clicks"),
    Input({"type": "priority-down", "index": ALL}, "n_clicks"),
    State({"type": "priority-up", "index": ALL}, "id"),
    State({"type": "priority-down", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def render_and_reorder_priority(
    priority_data, up_clicks, down_clicks, up_ids, down_ids
):
    trigger = ctx.triggered_id

    # 上下ボタンによる並べ替え
    if isinstance(trigger, dict):
        data = list(priority_data)
        move_idx = trigger["index"]
        pos = next(
            i
            for i, e in enumerate(data)
            if (e["idx"] if isinstance(e, dict) else e) == move_idx
        )
        if trigger["type"] == "priority-up" and pos > 0:
            data[pos], data[pos - 1] = data[pos - 1], data[pos]
        elif trigger["type"] == "priority-down" and pos < len(data) - 1:
            data[pos], data[pos + 1] = data[pos + 1], data[pos]
        return _make_priority_cards(data), data

    # Store 変更によるレンダリング
    return _make_priority_cards(priority_data), no_update


@callback(
    Output("autosave", "data"),
    Input({"type": "costume", "index": ALL}, "value"),
    Input({"type": "bond-rank", "index": ALL}, "value"),
    Input("costume-priority-order", "data"),
    Input("bond50-penalty", "value"),
    Input("preset-dropdown", "value"),
    Input("preset-status-radio", "value"),
    State("student-indices", "data"),
    State("next-student-index", "data"),
    State({"type": "costume", "index": ALL}, "id"),
    State({"type": "bond-rank", "index": ALL}, "id"),
    State("autosave-ready", "data"),
    prevent_initial_call=True,
)
def save_autosave(
    costume_values,
    rank_values,
    priority_data,
    penalty,
    dropdown_value,
    status_value,
    indices,
    next_index,
    costume_ids,
    rank_ids,
    ready,
):
    # 復元前の保存は禁止。動的レイアウト挿入直後は prevent_initial_call が
    # 効かず初期値で発火するため、そのまま保存すると復元前のデータが潰れる。
    if not ready:
        raise PreventUpdate
    if not indices:
        raise PreventUpdate
    costumes = {str(cid["index"]): cv for cv, cid in zip(costume_values, costume_ids)}
    ranks = {str(rid["index"]): rv for rv, rid in zip(rank_values, rank_ids)}
    return {
        "indices": indices,
        "next_index": next_index,
        "costumes": costumes,
        "ranks": ranks,
        "priority": priority_data,
        "penalty": penalty,
        "preset_value": _combined_preset_value(dropdown_value, status_value),
    }


@callback(
    Output("students-container", "children", allow_duplicate=True),
    Output("student-indices", "data", allow_duplicate=True),
    Output("next-student-index", "data", allow_duplicate=True),
    Output("bond-rank-container", "children", allow_duplicate=True),
    Output("costume-priority-order", "data", allow_duplicate=True),
    Output("bond50-penalty", "value", allow_duplicate=True),
    Output("preset-dropdown", "value"),
    Output("present-display", "children", allow_duplicate=True),
    Output("autosave-ready", "data"),
    Input("autosave-init", "n_intervals"),
    State("autosave", "data"),
    prevent_initial_call=True,
)
def restore_autosave(_n, data):
    # 復元するものがなくても ready フラグは立てる（以降の保存を許可）
    if not data or not data.get("indices"):
        return (no_update,) * 8 + (True,)

    penalty = data.get("penalty", 0)
    preset_value = data.get("preset_value")

    # プリセットが選択されていればプリセットから復元
    if preset_value:
        result = get_preset_data(preset_value)
        if result:
            _, students = result
            indices = list(range(len(students)))
            next_index = len(students)
            ranks = data.get("ranks") or {}
            student_children = [
                make_student_card(
                    i,
                    costume_name=s["costume_name"],
                    bond_bonuses=s["bond_bonuses"],
                )
                for i, s in enumerate(students)
            ]
            rank_children = [
                _make_bond_rank_input(
                    i,
                    costume_name=s["costume_name"],
                    value=ranks.get(str(i)) or 20,
                    bond_bonuses=s["bond_bonuses"],
                )
                for i, s in enumerate(students)
            ]
            priority = [
                {"idx": i, "name": s["costume_name"]} for i, s in enumerate(students)
            ]
            return (
                student_children,
                indices,
                next_index,
                rank_children,
                priority,
                penalty if penalty is not None else 0,
                _dropdown_student(preset_value),
                _preset_present_children(preset_value, students),
                True,
            )

    # プリセット未選択: デフォルト状態（衣装1つ）
    return (no_update,) * 8 + (True,)


@callback(
    Output("co-loaded-costumes", "data"),
    Input("load-preset-btn", "n_clicks"),
    Input("autosave-init", "n_intervals"),
    State("preset-dropdown", "value"),
    State("preset-status-radio", "value"),
    State("autosave", "data"),
    prevent_initial_call=True,
)
def co_track_loaded_costumes(_clicks, _n, dropdown_value, status_value, autosave):
    """読み込んだ（自動保存から復元した）プリセットの衣装名と衣装IDを保持する。

    update_students / restore_autosave と同じプリセット値から求める。
    """
    if ctx.triggered_id == "autosave-init":
        preset_value = (autosave or {}).get("preset_value")
    else:
        preset_value = _combined_preset_value(dropdown_value, status_value)
    result = get_preset_data(preset_value) if preset_value else None
    if not result:
        raise PreventUpdate
    return [
        {"costume_name": c["costume_name"], "costume_id": c.get("costume_id")}
        for c in result[1]
    ]


def _co_costume_ids(loaded, costume_values, costume_ids, rank_ids) -> list:
    """絆ランク入力欄の並びに対応する costume_id（不明なら None）を返す。

    衣装カードの衣装名が、読み込んだプリセットの衣装名と一致するものだけ
    対応付ける（手入力・改名した衣装は None）。
    """
    cid_by_name = {
        c["costume_name"]: c["costume_id"]
        for c in loaded or []
        if c.get("costume_id") is not None
    }
    name_by_index = {cid["index"]: v for v, cid in zip(costume_values, costume_ids)}
    return [cid_by_name.get(name_by_index.get(rid["index"])) for rid in rank_ids]


@callback(
    Output({"type": "bond-rank", "index": ALL}, "value", allow_duplicate=True),
    Output("co-bond-ranks-feedback", "children"),
    Input("co-apply-bond-ranks-btn", "n_clicks"),
    State("bond-ranks", "data"),
    State("co-loaded-costumes", "data"),
    State({"type": "costume", "index": ALL}, "value"),
    State({"type": "costume", "index": ALL}, "id"),
    State({"type": "bond-rank", "index": ALL}, "value"),
    State({"type": "bond-rank", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def co_apply_bond_ranks(
    n_clicks, bond_ranks, loaded, costume_values, costume_ids, rank_values, rank_ids
):
    """絆ランク管理で設定済みの衣装の絆ランクで入力欄を上書きする。"""
    if not n_clicks:
        raise PreventUpdate
    saved_ranks = ranks_for_costumes(
        bond_ranks, _co_costume_ids(loaded, costume_values, costume_ids, rank_ids)
    )
    values = [saved_ranks.get(i, v) for i, v in enumerate(rank_values)]
    return values, _bond_ranks_applied_feedback(len(saved_ranks))


@callback(
    Output("bond-ranks", "data", allow_duplicate=True),
    Output("co-bond-ranks-feedback", "children", allow_duplicate=True),
    Input("co-save-bond-ranks-btn", "n_clicks"),
    State("bond-ranks", "data"),
    State("co-loaded-costumes", "data"),
    State({"type": "costume", "index": ALL}, "value"),
    State({"type": "costume", "index": ALL}, "id"),
    State({"type": "bond-rank", "index": ALL}, "value"),
    State({"type": "bond-rank", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def co_save_bond_ranks(
    n_clicks, bond_ranks, loaded, costume_values, costume_ids, rank_values, rank_ids
):
    """入力中の絆ランクを絆ランク管理に保存する（プリセットの衣装のみ）。"""
    if not n_clicks:
        raise PreventUpdate
    saved, n = _save_inputs_to_bond_ranks(
        bond_ranks,
        _co_costume_ids(loaded, costume_values, costume_ids, rank_ids),
        dict(enumerate(rank_values)),
    )
    if n == 0:
        return no_update, html.Span(
            "保存できる衣装がありません（プリセットを読み込んだ衣装のみ保存できます）。",
            style={"color": "red"},
        )
    return saved, _bond_ranks_saved_feedback(n)


@callback(
    Output("favorites", "data"),
    Output("fav-toggle-btn", "children"),
    Input("fav-toggle-btn", "n_clicks"),
    Input("preset-dropdown", "value"),
    Input("preset-status-radio", "value"),
    State("favorites", "data"),
    prevent_initial_call=False,
)
def toggle_favorite(n_clicks, dropdown_value, status_value, favorites):
    favorites = list(favorites or [])
    preset_value = _combined_preset_value(dropdown_value, status_value)
    trigger = ctx.triggered_id
    if trigger == "fav-toggle-btn":
        if not preset_value:
            raise PreventUpdate
        if preset_value in favorites:
            favorites.remove(preset_value)
        else:
            favorites.append(preset_value)
    star = "★" if preset_value and preset_value in favorites else "☆"
    return favorites, star


@callback(
    Output("preset-dropdown", "options"),
    Input("favorites", "data"),
)
def render_preset_options(favorites):
    if not HAS_DB:
        # JSON フォールバック (旧形式キー)
        return _sort_options_with_favorites(
            get_all_presets_for_dropdown(), favorites or []
        )
    return get_favorite_options(favorites or []) + get_student_options()


# ======================================================================
# 贈り物逆引きページ
# ======================================================================


def _gl_header(gift: dict) -> html.Div:
    """結果先頭の「選択中の贈り物」行。"""
    is_high = gift["gift_type"] in ("high", "high-all")
    return html.Div(
        [
            html.Img(
                src=gift_image_src(gift),
                style={"width": "44px", "height": "34px", "objectFit": "contain"},
            ),
            html.Strong(gift["name"], style={"fontSize": "1.05rem"}),
            html.Span(
                "高級" if is_high else "通常",
                style={
                    "fontSize": "0.75rem",
                    "color": "#666",
                    "border": "1px solid #ccc",
                    "borderRadius": "10px",
                    "padding": "1px 8px",
                    "background": "#ede7f6" if is_high else "#fafafa",
                },
            ),
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "gap": "8px",
            "flexWrap": "wrap",
            "paddingBottom": "8px",
            "borderBottom": "1px solid #eee",
        },
    )


def _gl_note(text: str) -> html.P:
    return html.P(
        text, style={"color": "#666", "fontSize": "0.9rem", "margin": "10px 0 0"}
    )


def _gl_craft_section(gift: dict) -> html.Div:
    """製造（クラフトチェンバー）でこの贈り物が出る2次ノード。"""
    node = second_node(gift["name"])
    if node is None:
        body = [
            html.Div(
                "製造の2次ノード（花弁系）では出ません。",
                style={"fontSize": "0.85rem", "color": "#666"},
            )
        ]
    else:
        body = [
            html.Div(
                [
                    html.Span(node["node"], className="gl-node"),
                    html.Span(node["category"], style={"color": "#555"}),
                    html.Span(
                        f"ノード内 {node['rate'] * 100:.2f}%",
                        style={"fontSize": "0.8rem", "color": "#888"},
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "8px",
                    "flexWrap": "wrap",
                },
            ),
        ]
    return html.Div(
        [
            html.Div(html.Strong("製造（2次ノード）"), style={"marginBottom": "6px"}),
            *body,
        ],
        style={
            "marginTop": "10px",
            "paddingBottom": "10px",
            "borderBottom": "1px solid #eee",
        },
    )


def _gl_tier_section(gift: dict, tier: str, members: list[dict]) -> html.Div:
    """効果ごとの生徒（衣装）一覧。"""
    label, exp = get_effectivity(gift["gift_type"], tier_to_effectivity(tier))
    return html.Div(
        [
            html.Div(
                [
                    html.Img(
                        src=f"/assets/reaction/{_GS_TIER_ICON[tier]}.png",
                        alt=label,
                        title=label,
                        style={"height": "24px", "verticalAlign": "middle"},
                    ),
                    html.Strong(f"{label}（{exp} EXP）"),
                    html.Span(
                        f"{len(members)}人",
                        style={"fontSize": "0.8rem", "color": "#888"},
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "8px"},
            ),
            html.Div(
                [html.Span(m["label"], className="gl-chip") for m in members],
                className="gl-chips",
            ),
        ],
        style={"marginTop": "14px"},
    )


def _gl_result(gift: dict | None) -> list:
    """選択された贈り物の逆引き結果を組み立てる。"""
    if gift is None:
        return [
            html.P(
                "贈り物が見つかりませんでした。",
                style={"color": "#888", "margin": "8px 0"},
            )
        ]
    children = [_gl_header(gift), _gl_craft_section(gift)]
    lovers = get_gift_lovers(gift["id"])
    if not lovers:
        children.append(
            _gl_note("この贈り物を好物にしている生徒（衣装）は登録されていません。")
        )
        return children
    by_tier: dict[str, list[dict]] = {}
    for lover in lovers:
        by_tier.setdefault(lover["tier"], []).append(lover)
    children.append(_gl_note(f"好物にしている生徒（衣装）: {len(lovers)}人"))
    for tier in GL_TIER_ORDER:
        members = by_tier.get(tier)
        if members:
            children.append(_gl_tier_section(gift, tier, members))
    return children


@callback(
    Output("gl-result", "children"),
    Output({"type": "gl-gift", "gift": ALL}, "className"),
    Input({"type": "gl-gift", "gift": ALL}, "n_clicks"),
    State({"type": "gl-gift", "gift": ALL}, "id"),
    prevent_initial_call=True,
)
def gl_select_gift(_clicks, ids):
    """贈り物カードのクリックで逆引き結果を表示し、選択中カードを強調する。"""
    triggered = ctx.triggered_id
    if not triggered:
        raise PreventUpdate
    selected_id = triggered["gift"]
    gifts = {g["id"]: g for g in gl_lookup_gifts()}
    classes = [
        gl_gift_class(
            gifts.get(i["gift"], {"gift_type": "normal"}),
            i["gift"] == selected_id,
        )
        for i in ids
    ]
    return _gl_result(gifts.get(selected_id)), classes


# ======================================================================
# 2次ノード比較ページ
# ======================================================================

_NC_DEFAULT_WEIGHT = 1.0


def _nc_weight(value) -> float:
    """重み入力の値を正規化する。未入力・不正値は既定値、負値は 0。"""
    try:
        w = float(value)
    except (TypeError, ValueError):
        return _NC_DEFAULT_WEIGHT
    return max(w, 0.0)


def _nc_costume_labels() -> dict:
    return {o["value"]: o["label"] for o in get_costume_options()}


@callback(
    Output("nc-weight-container", "children"),
    Input("nc-costume-dropdown", "value"),
    Input("nc-use-weight", "value"),
    State({"type": "nc-weight", "costume": ALL}, "value"),
    State({"type": "nc-weight", "costume": ALL}, "id"),
)
def nc_render_weights(costume_ids, use_weight, values, ids):
    """選択中の衣装ごとの重み入力欄。入力済みの重みは選択を変えても引き継ぐ。"""
    if not use_weight or not costume_ids:
        return []
    prev = {i["costume"]: v for i, v in zip(ids, values)}
    labels = _nc_costume_labels()
    rows = [
        html.Div(
            [
                html.Span(labels.get(cid, str(cid)), className="nc-weight-label"),
                dcc.Input(
                    id={"type": "nc-weight", "costume": cid},
                    type="number",
                    min=0,
                    step=0.1,
                    value=prev.get(cid, _NC_DEFAULT_WEIGHT),
                    debounce=True,
                    persistence=True,
                    persistence_type="local",
                    style={"width": "70px", "padding": "2px 4px"},
                ),
            ],
            className="nc-weight-row",
        )
        for cid in costume_ids
    ]
    return [
        html.P(
            "重みは 0 以上（既定 1）。0 にした衣装は比較から外れます。",
            style={"fontSize": "0.8rem", "color": "#888", "margin": "0 0 4px"},
        ),
        html.Div(rows, className="nc-weight-grid"),
    ]


def _nc_gift_row(gift: dict, gifts_by_id: dict, weighted: bool) -> html.Div:
    """ノード内訳の贈り物1行（アイコン・名前・値・贈る相手）。"""
    if gift["tier"]:
        target = [
            html.Img(
                src=f"/assets/reaction/{TIER_ICON[gift['tier']]}.png",
                title=TIER_LABEL[gift["tier"]],
                style={"height": "18px", "verticalAlign": "middle"},
            ),
            html.Span(gift["label"]),
        ]
    else:
        target = [html.Span("好物なし", style={"color": "#aaa"})]
    value = f"{gift['value']:.1f}" if weighted else f"{gift['exp']} EXP"
    return html.Div(
        [
            html.Img(
                src=gift_image_src(gifts_by_id[gift["id"]]),
                style={"width": "32px", "height": "24px", "objectFit": "contain"},
            ),
            html.Span(gift["name"], className="nc-gift-name"),
            html.Span(value, className="nc-gift-value"),
            html.Span(target, className="nc-gift-target"),
        ],
        className="nc-gift-row",
    )


def _nc_result(rows: list[dict], gifts: list[dict], weighted: bool) -> list:
    """ノードの期待値ランキング。各ノードは内訳を折りたたみで持つ。"""
    gifts_by_id = {g["id"]: g for g in gifts}
    top = rows[0]["ev"] if rows else 0
    unit = "" if weighted else " EXP"
    items = []
    for rank, row in enumerate(rows, start=1):
        pct = row["ev"] / top * 100 if top else 0
        n = len(row["gifts"])
        summary = html.Summary(
            [
                html.Span(f"{rank}", className="nc-rank"),
                html.Span(row["node"], className="gl-node nc-node-name"),
                html.Span(row["category"], className="nc-category"),
                html.Span(
                    html.Span(className="nc-bar-fill", style={"width": f"{pct:.1f}%"}),
                    className="nc-bar",
                ),
                html.Strong(f"{row['ev']:.1f}{unit}", className="nc-ev"),
            ],
            className="nc-summary",
            title=f"{n}種から等確率（各 {100 / n:.2f}%）",
        )
        items.append(
            html.Details(
                [
                    summary,
                    html.Div(
                        [_nc_gift_row(g, gifts_by_id, weighted) for g in row["gifts"]],
                        className="nc-gifts",
                    ),
                ],
                className="nc-node" + (" nc-top" if rank == 1 else ""),
            )
        )
    return [
        html.P(
            ("期待値（重み × EXP）" if weighted else "期待値（EXP）")
            + "の高い順。行をクリックすると、出る贈り物とそれを贈る衣装を"
            "表示します。",
            style={"fontSize": "0.8rem", "color": "#888", "margin": "0 0 8px"},
        ),
        *items,
    ]


@callback(
    Output("nc-result", "children"),
    Input("nc-costume-dropdown", "value"),
    Input("nc-use-weight", "value"),
    Input({"type": "nc-weight", "costume": ALL}, "value"),
    State({"type": "nc-weight", "costume": ALL}, "id"),
)
def nc_compare(costume_ids, use_weight, weight_values, weight_ids):
    """選択中の衣装で2次ノードの期待値を計算して並べる。"""
    if not costume_ids:
        return html.P(
            "衣装を選んでください。", style={"color": "#888", "margin": "8px 0"}
        )
    gifts = load_gifts()
    if not gifts:
        return html.P(
            "贈り物データを読み込めませんでした。",
            style={"color": "#888", "margin": "8px 0"},
        )
    weighted = bool(use_weight)
    members = _nc_members(costume_ids, weighted, weight_values, weight_ids)
    return _nc_result(compare_second_nodes(gifts, members), gifts, weighted)


def _nc_members(costume_ids, weighted: bool, weight_values, weight_ids) -> list:
    """選択中の衣装を compare_second_nodes / craft_expected_exp の members にする。"""
    weights = {i["costume"]: _nc_weight(v) for i, v in zip(weight_ids, weight_values)}
    labels = _nc_costume_labels()
    return [
        {
            "label": labels.get(cid, str(cid)),
            "weight": weights.get(cid, _NC_DEFAULT_WEIGHT) if weighted else 1.0,
            "present": get_costume_present_map(cid),
        }
        for cid in costume_ids
    ]


def _nc_craft_node_row(node: dict, unit: str) -> html.Div:
    """製造期待値の内訳: ノード1行（名前・出現率・採用率・期待値）。"""
    return html.Div(
        [
            html.Span(node["name"], className="gl-node nc-node-name"),
            html.Span(
                f"出現率 {node['offered'] * 100:.1f}%", className="nc-craft-rate"
            ),
            html.Span(f"採用率 {node['pick'] * 100:.1f}%", className="nc-craft-rate"),
            html.Span(f"{node['ev']:.1f}{unit}", className="nc-gift-value"),
        ],
        className="nc-gift-row",
    )


def _nc_craft_result(result: dict, weighted: bool) -> list:
    """製造1回あたりの期待値。段ごとの内訳を折りたたみで持つ。"""
    unit = "" if weighted else " EXP"
    top = max((t["ev"] for t in result["tiers"]), default=0)
    tiers = []
    for t in result["tiers"]:
        pct = t["ev"] / top * 100 if top else 0
        tiers.append(
            html.Details(
                [
                    html.Summary(
                        [
                            html.Span(f"{t['tier']}次", className="nc-node-name"),
                            html.Span(
                                html.Span(
                                    className="nc-bar-fill",
                                    style={"width": f"{pct:.1f}%"},
                                ),
                                className="nc-bar",
                            ),
                            html.Strong(f"{t['ev']:.1f}{unit}", className="nc-ev"),
                        ],
                        className="nc-summary",
                    ),
                    html.Div(
                        [_nc_craft_node_row(n, unit) for n in t["nodes"]],
                        className="nc-gifts",
                    ),
                ],
                className="nc-node",
            )
        )
    return [
        html.Div(
            [
                html.Strong("製造1回あたりの期待値"),
                html.Strong(f"{result['ev']:.1f}{unit}", className="nc-craft-total"),
            ],
            className="nc-craft-head",
        ),
        html.P(
            f"1〜3次の各段で候補のノードが{OFFERED_NODES}つ出て、その中から"
            "期待値が最も高いノードを選んだときの、3段分の贈り物の"
            + ("期待値（重み × EXP）" if weighted else "絆EXP期待値")
            + "です。段をクリックすると、贈り物が出るノードごとに、候補に出る確率"
            "（出現率）、実際に選ばれる確率（採用率）、期待値を表示します。",
            style={"fontSize": "0.8rem", "color": "#888", "margin": "4px 0 8px"},
        ),
        *tiers,
    ]


@callback(
    Output("nc-craft-result", "children"),
    Input("nc-costume-dropdown", "value"),
    Input("nc-use-weight", "value"),
    Input({"type": "nc-weight", "costume": ALL}, "value"),
    State({"type": "nc-weight", "costume": ALL}, "id"),
)
def nc_craft_exp(costume_ids, use_weight, weight_values, weight_ids):
    """選択中の衣装で、製造1回あたりの期待値（1〜3次の合計）を計算する。"""
    if not costume_ids:
        return []
    gifts = load_gifts()
    if not gifts:
        return []
    weighted = bool(use_weight)
    members = _nc_members(costume_ids, weighted, weight_values, weight_ids)
    return _nc_craft_result(craft_expected_exp(gifts, members), weighted)


# ======================================================================
# 絆ランク管理ページ
# ======================================================================

# 絆ランク欄は min/max を付けない（範囲外の値が None になり「空欄 =
# 未設定に戻す」と区別できなくなるため）。範囲外は保存せず赤枠で示す。
BM_RANK_STYLE = {"width": "80px", "textAlign": "center"}
# 一覧の行の絆ランク欄（幅は表の列に合わせる）。赤枠の切り替えは main.py
BM_ROW_RANK_STYLE = {"width": "100%", "textAlign": "center"}
# ラベルと入力欄の組。狭い画面では組ごとに折り返す。
_BM_FIELD_STYLE = {
    "display": "inline-flex",
    "alignItems": "center",
    "gap": "4px",
    "whiteSpace": "nowrap",
    "marginRight": "8px",
}


def _bm_rows(bond_ranks, options: list[dict]) -> list:
    """全衣装の現在絆ランク入力行を生成する。

    並びは衣装ドロップダウンの表示順（生徒の優先度順）。未設定の衣装は空欄。
    """
    by_cid = {e["costume_id"]: e for e in normalize_bond_ranks(bond_ranks)}
    rows = []
    for o in options:
        cid = o["value"]
        e = by_cid.get(cid) or {}
        rows.append(
            html.Div(
                [
                    html.Strong(
                        _with_student_icon(o["label"]), className="costume-name"
                    ),
                    dcc.Input(
                        id={"type": "bm-rank", "costume": cid},
                        type="number",
                        value=e.get("rank"),
                        debounce=True,
                        placeholder="未設定",
                        style=BM_ROW_RANK_STYLE,
                    ),
                ],
                id={"type": "bm-row", "costume": cid},
                className="costume-row bm-grid bm-row",
            )
        )
    if not rows:
        return html.P(
            "衣装データがありません。", style={"color": "#888", "margin": "8px 0"}
        )
    return rows


@callback(
    Output("account-sync-error", "children"),
    Output("account-retry", "disabled"),
    Input("bond-ranks", "data"),
    Input("account-retry", "n_intervals"),
    State("account-state", "data"),
    prevent_initial_call=True,
)
def account_save_bond_ranks(bond_ranks, _retry, account_state):
    """ログイン中は、絆ランク管理の保存データが変わるたびにサーバーへ保存する。

    失敗したら再試行タイマー（account-retry）を動かし、少し待ってから
    その時点の保存データで保存し直す（成功するまで繰り返す）。
    ページを開いた時点でログインしていなかった（localStorage に保存している）
    ときは何もしない。開いた後に別のタブでログアウト・別アカウントでログイン
    したときは、別アカウントへ書き込まないよう保存せずに知らせる。
    Returns (通知メッセージ, 再試行タイマーを止めるか)。
    """
    user_id = (account_state or {}).get("user_id")
    if user_id is None:
        raise PreventUpdate
    if session_user_id() != user_id:
        return (
            "ログイン状態が変わったため、サーバーに保存できませんでした。"
            "ページを再読み込みしてください。"
        ), True
    try:
        save_user_bond_ranks(user_id, bond_ranks)
    except Exception:
        logging.getLogger(__name__).exception("failed to save bond ranks")
        return (
            "サーバーへの保存に失敗しました。自動で再試行しています…"
            "（このページを閉じたり再読み込みしたりすると、変更が失われます）"
        ), False
    return "", True


@callback(
    Output("bm-container", "children"),
    Output("bm-ocr-refs", "data"),
    Input("bm-init", "n_intervals"),
    State("bond-ranks", "data"),
    prevent_initial_call=True,
)
def bm_render(_n, bond_ranks):
    """保存データを読んで全衣装の行を描画する（ページ表示時に1回）。

    入力値の保存は bm_save_edits が行う。入力のたびに行を再生成すると
    フォーカスを失うため、描画はここだけで行う。あわせて、スクリーンショット
    読み取りで照合する衣装の [[衣装ID, 表示名, 生徒画像があるか], ...] を返す
    （生徒画像の無い衣装は名前だけで照合する）。
    """
    options = get_costume_options()
    refs = [[o["value"], o["label"], o["label"] in _STUDENT_ICONS] for o in options]
    return _bm_rows(bond_ranks, options), refs


@callback(
    Output("bond-ranks", "data", allow_duplicate=True),
    Output("bm-count", "children"),
    Input({"type": "bm-rank", "costume": ALL}, "value"),
    State({"type": "bm-rank", "costume": ALL}, "id"),
    State("bond-ranks", "data"),
    prevent_initial_call=True,
)
def bm_save_edits(rank_values, rank_ids, bond_ranks):
    """入力欄の値を保存する。絆ランクを空欄にした衣装は未設定に戻す。

    行が無い（描画前）ときは何もしない。入力欄に無い衣装は変更しない。
    """
    if not rank_ids:
        raise PreventUpdate
    saved = apply_page_edits(
        bond_ranks,
        {rid["costume"]: v for v, rid in zip(rank_values, rank_ids)},
    )
    count = f"設定済み {len(saved['costumes'])} / {len(rank_ids)} 衣装"
    if saved["costumes"] == normalize_bond_ranks(bond_ranks):
        return no_update, count
    return saved, count


def _bm_ocr_preview(result, bond_ranks, options: list[dict]):
    """スクリーンショットの読み取り結果（assets/bond_ocr.js）の
    状態メッセージと確認表。Returns (状態メッセージ, 確認表)。

    確認表の絆ランク欄は修正でき、空欄にした衣装は反映しない（名前が衣装と
    食い違った衣装は最初から空欄）。要確認の衣装を先に並べ、画像と見比べられるようカードの切り抜きの
    置き場所を付ける（切り抜きはブラウザ内で入れる。assets/bond_ocr.js の crops）。
    """
    if not isinstance(result, dict):
        raise PreventUpdate
    if result.get("error"):
        return (
            html.Span("画像の読み取りに失敗しました。", style={"color": "red"}),
            [],
        )
    labels = {o["value"]: o["label"] for o in options}
    entries = [
        e for e in merge_ocr_cards(result.get("cards")) if e["costume_id"] in labels
    ]
    notes = []
    if result.get("failed"):
        notes.append(
            f"生徒のカードが見つからなかった画像が {result['failed']} 枚あります。"
        )
    if result.get("partial"):
        notes.append(
            f"画面の端で切れていたカード {result['partial']} 枚は読み取っていません。"
        )
    if not entries:
        return (
            html.Span(
                ["絆ランクを読み取れませんでした。", *notes], style={"color": "red"}
            ),
            [],
        )
    n_uncertain = sum(e["uncertain"] for e in entries)
    n_dropped = sum(e["dropped"] for e in entries)
    if n_dropped:
        notes.append(
            f"名前が一致しなかったカード {n_dropped} 枚は読み取っていません"
            "（まだ登録されていない生徒の可能性があります）。"
        )
    status = html.Span(
        [
            f"{len(entries)} 衣装を読み取りました",
            f"（要確認 {n_uncertain}）" if n_uncertain else "",
            "。内容を確認して「絆ランク管理に反映」を押してください。",
            *notes,
        ]
    )
    saved = {e["costume_id"]: e["rank"] for e in normalize_bond_ranks(bond_ranks)}
    rows = []
    for e in sorted(entries, key=lambda e: not e["uncertain"]):
        cid = e["costume_id"]
        note = []
        if e["uncertain"]:
            note.append(
                html.Span("要確認", style={"color": "#c0392b", "fontWeight": "bold"})
            )
        # 名前が衣装と食い違ったカードは別の生徒の可能性があるので、既定では反映しない
        value = None if e["names"] else e["rank"]
        if e["read"] is not None and e["read"] != value:
            note.append(f"（読み取り値 {e['read']}）")
        if e["names"]:
            note.append(f"（名前が一致しません。近い名前: {'・'.join(e['names'])}）")
        rows.append(
            html.Div(
                [
                    html.Strong(
                        _with_student_icon(labels[cid]),
                        style={"minWidth": "210px", "display": "inline-block"},
                    ),
                    html.Span(
                        [
                            html.Span("絆ランク:", style={"fontSize": "0.8rem"}),
                            dcc.Input(
                                id={"type": "bm-ocr-rank", "costume": cid},
                                type="number",
                                value=value,
                                placeholder="反映しない",
                                style=BM_RANK_STYLE,
                            ),
                        ],
                        style=_BM_FIELD_STYLE,
                    ),
                    html.Span(
                        f"現在: {saved.get(cid, '未設定')}",
                        style={
                            "fontSize": "0.8rem",
                            "color": "#888",
                            "marginRight": "8px",
                        },
                    ),
                    *note,
                    *(
                        [
                            html.Div(
                                id={"type": "bm-ocr-crops", "costume": cid},
                                className="bm-ocr-crops",
                            )
                        ]
                        if e["uncertain"]
                        else []
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "4px",
                    "flexWrap": "wrap",
                    "padding": "6px 4px",
                    "borderBottom": "1px solid #eee",
                    "background": "#fff3f3" if e["uncertain"] else None,
                },
            )
        )
    preview = [
        html.Div(rows, className="bm-rows bm-ocr-rows", style={"margin": "8px 0"}),
        html.Button(
            "絆ランク管理に反映",
            id="bm-ocr-apply-btn",
            n_clicks=0,
            title="確認表の絆ランクを下の一覧に反映して保存する（空欄の衣装は反映しない）",
            className=BOND_RANKS_BTN_CLASS,
        ),
    ]
    return status, preview


@callback(
    Output("bm-ocr-status", "children"),
    Output("bm-ocr-preview", "children"),
    Input("bm-ocr-result", "data"),
    State("bond-ranks", "data"),
    prevent_initial_call=True,
)
def bm_ocr_preview(result, bond_ranks):
    """スクリーンショットの読み取り結果を確認表にする。"""
    return _bm_ocr_preview(result, bond_ranks, get_costume_options())


def _bm_ocr_apply(ocr_values, ocr_ids, rank_values, rank_ids):
    """確認表の絆ランクを一覧の入力欄の値にする。

    Returns (絆ランク欄の値, 反映した衣装数)。確認表で空欄・
    範囲外の衣装は変えない。
    """
    new = {}
    for v, oid in zip(ocr_values, ocr_ids):
        rank = valid_rank(v)
        if rank is not None:
            new[oid["costume"]] = rank
    old = {rid["costume"]: v for v, rid in zip(rank_values, rank_ids)}
    ranks = [new.get(rid["costume"], v) for v, rid in zip(rank_values, rank_ids)]
    return ranks, sum(cid in old for cid in new)


@callback(
    Output({"type": "bm-rank", "costume": ALL}, "value"),
    Output("bm-ocr-status", "children", allow_duplicate=True),
    Output("bm-ocr-preview", "children", allow_duplicate=True),
    Input("bm-ocr-apply-btn", "n_clicks"),
    State({"type": "bm-ocr-rank", "costume": ALL}, "value"),
    State({"type": "bm-ocr-rank", "costume": ALL}, "id"),
    State({"type": "bm-rank", "costume": ALL}, "value"),
    State({"type": "bm-rank", "costume": ALL}, "id"),
    prevent_initial_call=True,
)
def bm_ocr_apply(n_clicks, ocr_values, ocr_ids, rank_values, rank_ids):
    """確認表の絆ランクを一覧に反映する（保存は bm_save_edits が行う）。"""
    if not n_clicks or not rank_ids:
        raise PreventUpdate
    ranks, n = _bm_ocr_apply(ocr_values, ocr_ids, rank_values, rank_ids)
    if n == 0:
        return (
            no_update,
            html.Span(
                "反映できる衣装がありません（絆ランクが空欄・範囲外の衣装は反映しません）。",
                style={"color": "red"},
            ),
            no_update,
        )
    return (
        ranks,
        html.Span(f"{n} 衣装の絆ランクを反映しました。", style={"color": "#27ae60"}),
        [],
    )
