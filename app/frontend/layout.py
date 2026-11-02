import sys
from pathlib import Path

from dash import html, dcc

from app import SITE_NAME
from app.backend.accounts import (
    current_user,
    enabled_providers,
    load_user_bond_ranks,
    pop_auth_error,
    provider_label,
)
from app.backend.student import BOND_RANGES
from app.backend.furniture_craft import GAUGE, furniture_node_ranking
from app.backend.gift_craft import second_node
from app.backend.gift_exp import (
    get_effectivity,
    tier_to_effectivity,
    GIFT_SELECT_BOX_ID,
    TIER_LABEL,
)
from app.backend.user_presets import (
    _search_text,
    get_costume_options,
    get_gift_lover_counts,
    get_student_options,
    gift_image_src,
    load_gifts,
)

# PyInstaller バンドル時は _MEIPASS、通常時はプロジェクトルート
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys._MEIPASS)
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent.parent

_MANUAL_MD = (_BASE_DIR / "docs" / "manual.md").read_text(encoding="utf-8")
_PRIVACY_MD = (_BASE_DIR / "docs" / "privacy.md").read_text(encoding="utf-8")

# 絆ランク管理との連携ボタン（反映 / 保存）を置く className
BOND_RANKS_BTN_CLASS = "btn btn-sm"


def bond_ranks_buttons(prefix: str, auto_note: str) -> list[html.Button]:
    """「絆ランク管理から反映」「絆ランク管理に保存」ボタンの組。

    id は {prefix}-apply-bond-ranks-btn / {prefix}-save-bond-ranks-btn。
    auto_note は自動反映されるタイミングの説明（反映ボタンの title）。
    """
    return [
        html.Button(
            "絆ランク管理から反映",
            id=f"{prefix}-apply-bond-ranks-btn",
            n_clicks=0,
            title=(
                f"絆ランク管理に保存した現在の絆ランクを入力欄に反映する（{auto_note}）"
            ),
            className=BOND_RANKS_BTN_CLASS,
        ),
        html.Button(
            "絆ランク管理に保存",
            id=f"{prefix}-save-bond-ranks-btn",
            n_clicks=0,
            title="入力中の現在の絆ランクを絆ランク管理に保存する",
            className=BOND_RANKS_BTN_CLASS,
        ),
    ]


def panel(
    children,
    *,
    title=None,
    actions=None,
    hint=None,
    className: str = "",
    **kwargs,
) -> html.Div:
    """見出し（title / 右寄せの actions）+ 補足（hint）+ 本体 のパネル。"""
    head = []
    if title is not None or actions:
        head.append(
            html.Div(
                [
                    html.Span(title, className="panel-title"),
                    actions and html.Div(actions, className="panel-actions"),
                ],
                className="panel-head",
            )
        )
    if hint:
        head.append(html.P(hint, className="hint"))
    if not isinstance(children, list):
        children = [children]
    return html.Div(
        [*head, html.Div(children, className="panel-body")],
        className=f"panel {className}".strip(),
        **kwargs,
    )


def bond_ranks_panel(
    children, *, title: str, prefix: str, auto_note: str, hint=None, **kwargs
) -> html.Div:
    """絆ランク管理と連携する衣装欄のパネル。見出しの右に反映/保存ボタン、
    その下にボタンの結果を表示する {prefix}-bond-ranks-feedback を置く。"""
    if not isinstance(children, list):
        children = [children]
    return panel(
        [
            html.Div(id=f"{prefix}-bond-ranks-feedback", className="feedback"),
            *children,
        ],
        title=title,
        actions=bond_ranks_buttons(prefix, auto_note),
        hint=hint,
        **kwargs,
    )


def page_intro(lead: str, details: str | None = None, actions=None) -> html.Div:
    """ページ冒頭の説明。要約1行を常に出し、詳しい説明は折りたたむ。"""
    return html.Div(
        [
            html.Div(
                [
                    html.P(lead, className="page-lead"),
                    actions and html.Div(actions, className="page-intro-actions"),
                ],
                className="page-intro-row",
            ),
            details
            and html.Details(
                [html.Summary("詳しい説明"), html.P(details)],
                className="page-details",
            ),
        ],
        className="page-intro",
    )


def page_container(children: list) -> html.Div:
    """各ページの外枠（幅・余白は style.css の .page-container）。"""
    return html.Div([*children, _footer()], className="page-container")


def calc_button(label: str, btn_id: str, result=None, **kwargs) -> html.Div:
    """計算実行ボタン（各ページ共通の見た目）と結果表示欄。"""
    return html.Div(
        [
            html.Button(
                label,
                id=btn_id,
                n_clicks=0,
                className="btn btn-primary btn-calc",
            ),
            *([result] if result is not None else []),
        ],
        **kwargs,
    )


def empty_note(text: str) -> html.P:
    """未入力・未選択のときの案内文。"""
    return html.P(text, className="empty-note")


def picker_row(children: list) -> html.Div:
    """選択欄（ドロップダウン）とボタンを1行に並べる行。"""
    return html.Div(children, className="picker-row")


def preset_panel(
    *,
    dropdown_id: str,
    radio_id: str,
    load_id: str,
    extra=None,
    feedback_id: str | None = None,
) -> html.Div:
    """プリセット（生徒）の選択パネル。ドロップダウン・ステータス・読み込みを
    1行に並べる。extra はドロップダウンの直後に置く要素（お気に入りボタン等）。"""
    row = [
        html.Div(
            dcc.Dropdown(
                id=dropdown_id,
                options=get_student_options(),
                placeholder="生徒を選択...",
            ),
            className="picker-dropdown",
        ),
        *(extra or []),
        dcc.RadioItems(id=radio_id, options=[], inline=True, className="picker-radio"),
        html.Button("読み込み", id=load_id, n_clicks=0, className="btn btn-primary"),
    ]
    children = [picker_row(row)]
    if feedback_id:
        children.append(html.Div(id=feedback_id, className="feedback"))
    return panel(children, title="プリセット", className="panel-soft preset-section")


def _default_costume_name(index: int) -> str:
    return f"衣装{index + 1}"


def make_student_card(
    index: int,
    *,
    costume_name: str = "",
    bond_bonuses: list[int] | None = None,
) -> html.Div:
    """生徒入力カードを1つ生成する。"""
    if bond_bonuses is None:
        bond_bonuses = [0] * len(BOND_RANGES)

    bond_fields = [
        html.Div(
            [
                html.Label(f"絆{lo}~{hi}"),
                dcc.Input(
                    id={"type": "bond", "range_idx": i, "index": index},
                    type="number",
                    value=bond_bonuses[i],
                    min=0,
                    debounce=True,
                    autoComplete="off",
                ),
            ],
            className="bond-field",
        )
        for i, (lo, hi) in enumerate(BOND_RANGES)
    ]

    return html.Div(
        [
            # ヘッダー行
            html.Div(
                [
                    html.Strong(f"衣装 {index + 1}"),
                    dcc.Input(
                        id={"type": "costume", "index": index},
                        type="text",
                        placeholder="衣装名",
                        value=costume_name or _default_costume_name(index),
                    ),
                    html.Button(
                        "✕",
                        id={"type": "remove-student", "index": index},
                        n_clicks=0,
                        title="この衣装を削除",
                        className="icon-btn remove-student-btn",
                    ),
                ],
                className="student-card-header",
            ),
            # 絆ボーナス入力行
            html.Div(bond_fields, className="bond-fields"),
        ],
        id={"type": "student-card", "index": index},
        className="student-card",
    )


def bond_view_cells(index: int, bond_bonuses: list[int] | None = None) -> html.Div:
    """絆ボーナスの表示欄（絆2~5 ... 絆41~50）。値は衣装カードの入力欄に
    追従する（callbacks.py の sync_bond_views）。"""
    if bond_bonuses is None:
        bond_bonuses = [0] * len(BOND_RANGES)
    return html.Div(
        [
            html.Span(
                [
                    html.Span(f"絆{lo}~{hi}", className="bonus-label"),
                    html.Span(
                        str(v),
                        id={"type": "bond-view", "range_idx": i, "index": index},
                    ),
                ]
            )
            for i, ((lo, hi), v) in enumerate(zip(BOND_RANGES, bond_bonuses))
        ],
        className="bonus-cells",
    )


def _make_bond_rank_input(
    index: int,
    *,
    costume_name: str = "",
    value: int = 20,
    bond_bonuses: list[int] | None = None,
) -> html.Div:
    """衣装1つ分の行（衣装名 / 現在の絆ランク入力 / 絆ボーナスの表示）。"""
    return html.Div(
        [
            html.Strong(
                costume_name or _default_costume_name(index),
                id={"type": "bond-rank-label", "index": index},
                className="costume-name",
            ),
            html.Div(
                [
                    dcc.Input(
                        id={"type": "bond-rank", "index": index},
                        type="number",
                        value=value,
                        debounce=True,
                    ),
                    html.Div(
                        [
                            html.Button(
                                "▲",
                                id={"type": "bond-rank-inc", "index": index},
                                n_clicks=0,
                            ),
                            html.Button(
                                "▼",
                                id={"type": "bond-rank-dec", "index": index},
                                n_clicks=0,
                            ),
                        ],
                        className="rank-stepper-btns",
                    ),
                ],
                className="rank-stepper",
            ),
            bond_view_cells(index, bond_bonuses),
        ],
        className="costume-row co-grid",
    )


def _footer() -> html.Div:
    """全ページ共通フッター。報告先とプライバシーポリシーへのリンクを置く。"""
    return html.Div(
        [
            html.Span(
                [
                    "不具合・要望報告は外部サービスの",
                    html.A(
                        "フォーム",
                        href="https://forms.gle/yxJYDAY55TPDkMr39",
                        target="_blank",
                        rel="noopener noreferrer",
                        className="link",
                    ),
                    "か",
                    html.A(
                        "Xアカウント",
                        href="https://x.com/yankeiori",
                        target="_blank",
                        rel="noopener noreferrer",
                        className="link",
                    ),
                    "まで",
                ]
            ),
            dcc.Link("プライバシーポリシー", href="/privacy", className="link"),
        ],
        className="site-footer",
    )


def create_privacy_layout() -> html.Div:
    """プライバシーポリシー表示ページ。"""
    return html.Div(
        [
            html.Div(
                [
                    dcc.Link(
                        "← 計算機に戻る",
                        href="/chart-opt",
                        style={
                            "color": "#4a90d9",
                            "textDecoration": "none",
                            "fontSize": "0.9rem",
                        },
                    ),
                ],
                style={"marginBottom": "16px"},
            ),
            dcc.Markdown(
                _PRIVACY_MD,
                style={
                    "background": "#fff",
                    "padding": "24px",
                    "borderRadius": "8px",
                    "boxShadow": "0 1px 3px rgba(0,0,0,0.08)",
                    "lineHeight": "1.7",
                },
            ),
            _footer(),
        ],
        style={
            "maxWidth": "820px",
            "margin": "24px auto",
            "padding": "0 20px",
        },
    )


# タブのカテゴリ（見出し, [パス, ...]）。ラベルは PAGES のもの。
NAV_GROUPS = [
    ("計算ツール", ["/chart-opt", "/gift-simulation", "/required-exp"]),
    ("調べる", ["/gift-lookup", "/node-compare", "/furniture-node"]),
    ("マイデータ", ["/bond-ranks"]),
]


def _page_tabs_bar() -> html.Div:
    """ページ切り替えタブバー（共通ヘッダー内に1つだけ配置）。

    NAV_GROUPS のカテゴリごとに、見出しの下にタブを並べる。
    アクティブ表示は URL に応じてクライアントサイドで className を
    切り替える（main.py のコールバック参照）。見た目は style.css の
    .page-tab / .page-tab-active で定義する。
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Div(title, className="tab-group-label"),
                    html.Div(
                        [
                            dcc.Link(
                                PAGES[path][0],
                                href=path,
                                id={"type": "page-tab", "path": path},
                                className="page-tab",
                            )
                            for path in paths
                        ],
                        className="tab-group-tabs",
                    ),
                ],
                className="tab-group",
            )
            for title, paths in NAV_GROUPS
        ],
        className="page-tabs",
    )


def _header_account() -> html.Div:
    """ヘッダー右上のログイン / ログイン中の表示。

    ログイン中は「〇〇 でログイン中」を開くとログアウト・アカウント削除。
    """
    user = current_user()
    if user is not None:
        return html.Details(
            [
                html.Summary(
                    f"{provider_label(user['provider'])} でログイン中",
                    className="account-summary",
                ),
                html.Div(
                    [
                        html.Form(
                            html.Button(
                                "ログアウト", type="submit", className="btn btn-sm"
                            ),
                            action="/auth/logout",
                            method="POST",
                        ),
                        html.Details(
                            [
                                html.Summary("アカウントを削除"),
                                html.Form(
                                    [
                                        html.P(
                                            "サーバーに保存した絆ランク管理の内容と"
                                            "ログイン情報を削除します（元に戻せません）。"
                                            "このブラウザに保存した内容は残ります。",
                                            className="hint",
                                            style={"marginBottom": "8px"},
                                        ),
                                        html.Button(
                                            "削除する",
                                            type="submit",
                                            className="btn btn-sm btn-danger",
                                        ),
                                    ],
                                    action="/auth/delete",
                                    method="POST",
                                ),
                            ],
                            className="account-delete",
                        ),
                    ],
                    className="account-menu",
                ),
            ],
            className="header-account",
        )
    if "google" in enabled_providers():
        return html.Div(_google_login_button(), className="header-account")
    return html.Div()


def _manual_modal() -> html.Div:
    """絆上げ優先度計算機のマニュアル（モーダル）。"""
    return html.Div(
        html.Div(
            [
                html.Div(
                    [
                        html.Strong("マニュアル", style={"fontSize": "1.2rem"}),
                        html.Button(
                            "✕",
                            id="close-manual-btn",
                            n_clicks=0,
                            className="icon-btn",
                            style={"marginLeft": "auto"},
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "borderBottom": "1px solid #ddd",
                        "paddingBottom": "8px",
                        "marginBottom": "12px",
                    },
                ),
                dcc.Markdown(_MANUAL_MD, style={"overflowY": "auto", "flex": "1"}),
            ],
            className="manual-modal-content",
        ),
        id="manual-modal",
        className="manual-modal-overlay",
        style={"display": "none"},
    )


def create_layout() -> html.Div:
    return page_container(
        [
            page_intro(
                "衣装ごとの絆ボーナスと現在の絆ランクから、"
                "ステータスが効率よく上がる絆上げの順番を計算します。",
                actions=[
                    html.Button(
                        "📖 マニュアル",
                        id="open-manual-btn",
                        n_clicks=0,
                        className="btn btn-sm",
                    )
                ],
            ),
            _manual_modal(),
            preset_panel(
                dropdown_id="preset-dropdown",
                radio_id="preset-status-radio",
                load_id="load-preset-btn",
                extra=[
                    html.Button(
                        "☆",
                        id="fav-toggle-btn",
                        n_clicks=0,
                        title="お気に入りに追加/解除",
                        className="btn fav-btn",
                    )
                ],
            ),
            # 衣装ごとの 現在の絆ランク入力 + 絆ボーナス（表示のみ）。
            # 絆ボーナスの入力（衣装カード）はプリセットで自動入力されるため
            # 折りたたみに置く。
            bond_ranks_panel(
                [
                    costume_table(
                        html.Div(
                            id="bond-rank-container",
                            children=[_make_bond_rank_input(0)],
                        ),
                        [html.Span("衣装"), html.Span("絆ランク"), _bonus_head()],
                        "co-grid",
                    ),
                    html.Details(
                        [
                            html.Summary(
                                "絆ボーナスを手動で編集"
                                "（プリセットに無い衣装・値の修正）"
                            ),
                            html.Div(
                                id="students-container",
                                children=[make_student_card(0)],
                            ),
                            html.Button(
                                "+ 衣装追加",
                                id="add-student-btn",
                                className="btn add-row-btn add-student-btn",
                                n_clicks=0,
                            ),
                        ],
                        className="manual-edit",
                    ),
                ],
                title="衣装と現在の絆ランク",
                prefix="co",
                auto_note="プリセット読み込み時は自動で反映",
                hint="プリセットを読み込むと絆ボーナスが自動で入力されます。",
                className="bond-rank-section",
            ),
            # 衣装ごとの好物（normal 以外を 衣装×リアクション の表で表示）
            panel(
                html.Div(
                    id="present-display",
                    children=empty_note("プリセットを読み込むと表示されます。"),
                ),
                title="衣装ごとの好物",
            ),
            # 高度な設定（折りたたみ）
            html.Details(
                [
                    html.Summary("高度な設定"),
                    html.Div(
                        [
                            html.Div(
                                "衣装優先度（タイブレーク）", className="panel-title"
                            ),
                            html.P(
                                "上が高優先。同スコア時に優先度が高い衣装を先にします。",
                                className="hint",
                            ),
                            html.Div(
                                id="costume-priority-container",
                                className="priority-list panel-body",
                            ),
                        ],
                        style={"marginBottom": "16px"},
                    ),
                    html.Div(
                        [
                            html.Div("絆50到達ペナルティ", className="panel-title"),
                            html.P(
                                "絆50到達時のボーナス減衰率。1に近いほど50到達を後回しにします。",
                                className="hint",
                            ),
                            html.Div(
                                dcc.Slider(
                                    id="bond50-penalty",
                                    min=0,
                                    max=1,
                                    step=0.05,
                                    value=0,
                                    marks={
                                        0: "0",
                                        0.25: "0.25",
                                        0.5: "0.5",
                                        0.75: "0.75",
                                        1: "1",
                                    },
                                    tooltip={
                                        "placement": "bottom",
                                        "always_visible": True,
                                    },
                                ),
                                className="panel-body",
                            ),
                        ],
                    ),
                ],
                className="panel",
            ),
            # チャート計算ボタン
            calc_button("チャート計算", "calc-chart-btn", className="calc-btn-wrapper"),
            # 計算結果表示エリア
            html.Div(id="chart-result", className="chart-result-area"),
            # 非表示 Store 群
            dcc.Store(id="student-indices", data=[0]),
            dcc.Store(id="next-student-index", data=1),
            dcc.Store(id="solver-inputs"),
            dcc.Store(id="costume-priority-order", data=[{"idx": 0, "name": "衣装1"}]),
            dcc.Store(id="autosave", storage_type="local"),
            # 復元完了フラグ: False の間は autosave への保存をブロックする
            # （動的レイアウト挿入時の初期発火で保存データが潰れるのを防ぐ）
            dcc.Store(id="autosave-ready", data=False),
            dcc.Store(id="favorites", storage_type="local", data=[]),
            # 読み込んだプリセットの衣装 [{costume_name, costume_id}, ...]。
            # 衣装カードと絆ランク管理の衣装を衣装名で対応付けるのに使う。
            dcc.Store(id="co-loaded-costumes", data=[]),
            # 結果表の列見出しに出す生徒画像 {衣装 index: URL}
            dcc.Store(id="co-costume-icons", data={}),
            dcc.Interval(id="autosave-init", max_intervals=1, interval=200),
        ]
    )


# ======================================================================
# 贈り物配分シミュレータ（ページ）
# ======================================================================

# プリセットの好み/all 型に関わらず、常にデフォルト使用可とする贈り物。
_GS_ALWAYS_USED = {"gift-select-box"}


def gs_default_used(gift: dict, preferred: set | frozenset = frozenset()) -> bool:
    """贈り物の使用フラグ既定値。

    好み(preferred) に入る / type に all を含む / 常時使用対象 のとき可。
    """
    return (
        gift["id"] in _GS_ALWAYS_USED
        or gift["id"] in preferred
        or "all" in gift["gift_type"]
    )


def _gs_gift_card(
    gift: dict, default_use: bool, qty: int = 0, id_prefix: str = "gs"
) -> html.Div:
    """贈り物1件のコンパクトカード（アイコン・所持数・使用可否）。

    名前は非表示で、マウスオーバー時に title で表示する。
    id_prefix でページごとのコンポーネントID型 (<prefix>-gift-use /
    <prefix>-gift-qty) を切り替える。
    """
    gid = gift["id"]
    is_high = gift["gift_type"] in ("high", "high-all")
    return html.Div(
        [
            html.Img(
                src=gift_image_src(gift),
                style={"width": "34px", "height": "26px", "objectFit": "contain"},
            ),
            html.Div(
                [
                    dcc.Checklist(
                        id={"type": f"{id_prefix}-gift-use", "gift": gid},
                        options=[{"label": "", "value": "use"}],
                        value=["use"] if default_use else [],
                        style={"margin": "0"},
                    ),
                    dcc.Input(
                        id={"type": f"{id_prefix}-gift-qty", "gift": gid},
                        type="number",
                        min=0,
                        value=qty,
                        debounce=True,
                        style={
                            "width": "38px",
                            "textAlign": "center",
                            "fontSize": "0.7rem",
                            "padding": "1px",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "2px"},
            ),
        ],
        className="gs-gift-card",
        title=gift["name"],
        style={
            "display": "flex",
            "flexDirection": "column",
            "alignItems": "center",
            "gap": "2px",
            "padding": "3px",
            "border": "1px solid #ccc",
            "borderRadius": "4px",
            "background": "#ede7f6" if is_high else "#fafafa",
        },
    )


def _gs_gift_grid(cards: list) -> html.Div:
    return html.Div(
        cards,
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fill, minmax(56px, 1fr))",
            "gap": "4px",
        },
    )


def build_gs_gift_list(
    gifts: list[dict],
    is_used,
    qty_by_gift: dict | None = None,
    use_by_gift: dict | None = None,
    id_prefix: str = "gs",
) -> list:
    """使用フラグONの贈り物のみ表示し、残りは折りたたみに格納する。

    qty_by_gift / use_by_gift が与えられた場合は所持数・使用フラグの
    保存値で上書きする（入力復元用）。

    贈り物リスト表示の children として使う要素リストを返す。
    """
    qty_by_gift = qty_by_gift or {}
    use_by_gift = use_by_gift or {}
    used, unused = [], []
    for g in gifts:
        gid = g["id"]
        if gid in use_by_gift:
            u = bool(use_by_gift[gid])
        else:
            u = bool(is_used(g))
        qty = qty_by_gift.get(gid, 0)
        (used if u else unused).append(_gs_gift_card(g, u, qty, id_prefix))
    children = []
    if used:
        children.append(_gs_gift_grid(used))
    else:
        children.append(
            html.P(
                "使用する贈り物がありません。",
                style={"color": "#888", "fontSize": "0.8rem", "margin": "4px 0"},
            )
        )
    if unused:
        children.append(
            html.Details(
                [
                    html.Summary(
                        f"使用しない贈り物 ({len(unused)})",
                        style={
                            "cursor": "pointer",
                            "fontSize": "0.85rem",
                            "margin": "10px 0 4px",
                            "color": "#666",
                        },
                    ),
                    html.P(
                        "使用する場合はチェックを付けて所持数を入力してください。",
                        style={
                            "fontSize": "0.78rem",
                            "color": "#888",
                            "margin": "4px 0 8px",
                        },
                    ),
                    _gs_gift_grid(unused),
                ]
            )
        )
    return children


def costume_table(
    container, head: list, grid_class: str, *, fit: bool = False
) -> html.Div:
    """衣装ごとの入力表。見出し行（head）の下に container（行は callbacks.py
    で描画）を置く。行が無いうちは見出しを出さない（style.css）。

    fit=True なら表の幅を列の合計までに縮める（PC 幅のみ。列が固定幅の表用）。
    """
    return html.Div(
        [html.Div(head, className=f"costume-head {grid_class}"), container],
        className="costume-table costume-table-fit" if fit else "costume-table",
    )


def _bonus_head() -> html.Div:
    """絆ボーナス列の見出し（絆2~5 ... 絆41~50）。"""
    return html.Div(
        [html.Span(f"絆{lo}~{hi}") for lo, hi in BOND_RANGES],
        className="bonus-cells",
    )


_REMAIN_EXP_TITLE = (
    "次の絆ランクまでの残り経験値（任意）。"
    "空欄なら現在ランクの開始（経験値0）として計算。"
)


def create_gift_simulator_layout() -> html.Div:
    """贈り物配分シミュレータページ（入力部）。"""
    gifts = load_gifts()
    # プリセット未読込時は好み無し（all 型・常時使用対象のみ可）
    gift_list_children = build_gs_gift_list(gifts, lambda g: gs_default_used(g))
    return page_container(
        [
            page_intro(
                "所持している贈り物をどの衣装に何個贈ると、"
                "絆ボーナスの合計が最も大きくなるかを計算します。",
            ),
            preset_panel(
                dropdown_id="gs-preset-dropdown",
                radio_id="gs-status-radio",
                load_id="gs-load-preset-btn",
                feedback_id="gs-load-feedback",
            ),
            # 衣装（優先順位）・現在の絆ランク入力・絆ボーナス（表示のみ）
            bond_ranks_panel(
                costume_table(
                    html.Div(
                        id="gs-costume-display",
                        children=empty_note("プリセットを読み込んでください。"),
                    ),
                    [
                        html.Span(className="costume-pos"),
                        html.Span("優先", className="span-2"),
                        html.Span("衣装"),
                        html.Span("絆ランク"),
                        html.Span("残りEXP", title=_REMAIN_EXP_TITLE),
                        _bonus_head(),
                    ],
                    "gs-grid",
                ),
                title="衣装と現在の絆ランク",
                prefix="gs",
                auto_note="読み込み時は自動で反映",
                hint=(
                    "▲▼ の並び順が優先順位です（上が最優先）。"
                    "絆ボーナス合計・使用個数が同点のとき、"
                    "上の衣装ほど絆ランクが高くなる配分を選びます。"
                ),
            ),
            # 衣装ごとの好物（normal 以外を 衣装×リアクション の表で表示）
            panel(
                html.Div(
                    id="gs-present-display",
                    children=empty_note("プリセットを読み込んでください。"),
                ),
                title="衣装ごとの好物",
            ),
            # 贈り物リスト
            panel(
                html.Div(gift_list_children, id="gs-gift-list"),
                title="所持している贈り物",
                hint="チェックを付けた贈り物だけを配分に使います。",
            ),
            # 計算開始
            calc_button(
                "計算開始",
                "gs-calc-btn",
                dcc.Loading(
                    type="circle",
                    children=html.Div(
                        id="gs-calc-result",
                        style={"marginTop": "12px", "minHeight": "24px"},
                    ),
                ),
            ),
            dcc.Store(id="gs-loaded-preset"),
            # 衣装の優先順位（衣装 index の並び。先頭が最優先）
            dcc.Store(id="gs-costume-order", data=[]),
            dcc.Store(id="gs-autosave", storage_type="local"),
            # 復元完了フラグ: False の間は gs-autosave への保存をブロックする
            dcc.Store(id="gs-autosave-ready", data=False),
            dcc.Interval(id="gs-autosave-init", max_intervals=1, interval=300),
        ]
    )


# ======================================================================
# 必要絆経験値（ページ）
# ======================================================================


def create_required_exp_layout() -> html.Div:
    """必要絆経験値 計算ページ。

    生徒（衣装）ごとに、現在の絆ランクから目標絆ランクまでに必要な
    絆経験値と、その贈り物選択ボックス換算個数を計算する。
    """
    return page_container(
        [
            page_intro(
                "目標の絆ランクまでに必要な絆経験値と、所持している贈り物で"
                "足りない分の贈り物選択ボックス換算の個数を計算します。",
                "現在の絆ランクの既定は 20、目標絆ランクの既定は 50 です。"
                "所持している贈り物を入力すると、最適に充当した上で"
                "それでも不足する絆経験値と、その贈り物選択ボックス換算の"
                "個数を表示します（ボックス1個あたりの獲得EXPは衣装の好物"
                "（通常タイプの最高効果）で決まります）。"
                "衣装は ▲▼ ボタンで並び替えでき、上の衣装ほど優先されます"
                "（不足ボックスの総数を増やさない範囲で、順位が上の衣装から"
                "不足が出ないように所持贈り物を充当します）。",
            ),
            # 生徒（衣装）の追加と、追加済み衣装の 現在絆ランク / 目標絆ランク 入力
            bond_ranks_panel(
                [
                    picker_row(
                        [
                            html.Div(
                                dcc.Dropdown(
                                    id="rb-costume-dropdown",
                                    options=get_costume_options(),
                                    placeholder="追加する生徒（衣装）を選択...",
                                ),
                                className="picker-dropdown",
                            ),
                            html.Button(
                                "＋ 追加",
                                id="rb-add-costume-btn",
                                n_clicks=0,
                                className="btn btn-primary",
                            ),
                        ]
                    ),
                    html.Div(id="rb-add-feedback", className="feedback"),
                    costume_table(
                        html.Div(
                            id="rb-costume-container",
                            children=empty_note("生徒（衣装）を追加してください。"),
                        ),
                        [
                            html.Span(className="costume-pos"),
                            html.Span("優先", className="span-2"),
                            html.Span("衣装"),
                            html.Span("絆ランク"),
                            html.Span("残りEXP", title=_REMAIN_EXP_TITLE),
                            html.Span("目標"),
                            html.Span(""),
                        ],
                        "rb-grid",
                        fit=True,
                    ),
                ],
                title="衣装と目標絆ランク",
                prefix="rb",
                auto_note="衣装の追加時は自動で反映",
                hint="上の衣装ほど優先して所持贈り物を充当します。",
            ),
            # 贈り物リスト（所持数・使用可否）
            panel(
                html.Div(
                    build_gs_gift_list(
                        load_gifts(),
                        lambda g: gs_default_used(g),
                        id_prefix="rb",
                    ),
                    id="rb-gift-list",
                ),
                title="所持している贈り物",
                hint=(
                    "所持数を入力すると、追加した衣装へ最適に充当した上で"
                    "不足分を計算します（すべて 0 なら必要絆経験値のみ）。"
                    "追加した衣装の好物・全生徒対象・選択ボックス以外は"
                    "効率が悪いため、既定で使用しない側に入れています。"
                ),
            ),
            # 計算
            calc_button(
                "必要絆経験値を計算",
                "rb-calc-btn",
                dcc.Loading(
                    type="circle",
                    children=html.Div(
                        id="rb-calc-result",
                        style={"marginTop": "12px", "minHeight": "24px"},
                    ),
                ),
            ),
            # 追加済みの生徒（衣装）リスト [{costume_id, label}, ...]
            dcc.Store(id="rb-costumes", data=[]),
            dcc.Store(id="rb-autosave", storage_type="local"),
            # 復元完了フラグ: False の間は rb-autosave への保存をブロックする
            dcc.Store(id="rb-autosave-ready", data=False),
            dcc.Interval(id="rb-autosave-init", max_intervals=1, interval=300),
        ]
    )


# ======================================================================
# 贈り物逆引きページ
# ======================================================================

# 効果の高い順。結果の表示順に使う。
GL_TIER_ORDER = ("ultraFavorite", "superFavorite", "favorite")


def gl_lookup_gifts() -> list[dict]:
    """逆引き対象の贈り物を返す。

    全生徒対象タイプ (*-all) と贈り物選択ボックスは衣装ごとの好みを
    持たない（誰に贈っても効果が同じ / 中身を選べる）ため除外する。
    """
    return [
        g
        for g in load_gifts()
        if not g["gift_type"].endswith("-all") and g["id"] != GIFT_SELECT_BOX_ID
    ]


def gl_gift_class(gift: dict, selected: bool = False) -> str:
    """贈り物カードの className。高級/通常で背景色、選択中で枠を変える。"""
    base = "gl-gift-card "
    base += "gl-high" if gift["gift_type"] in ("high", "high-all") else "gl-normal"
    return base + " gl-selected" if selected else base


def _gl_tier_counts(gift: dict, counts: dict[str, int]) -> html.Div:
    """効果別の人数表示（特大x人/大x人/中x人）。0 人の効果は表示しない。"""
    badges = []
    for tier in GL_TIER_ORDER:
        n = counts.get(tier, 0)
        if not n:
            continue
        label, exp = get_effectivity(gift["gift_type"], tier_to_effectivity(tier))
        if badges:
            badges.append(html.Span("/", className="gl-tier-sep"))
        badges.append(
            html.Span(
                f"{label}{n}人",
                className="gl-tier-count",
                title=f"{label}（{exp} EXP）{n}人",
            )
        )
    if not badges:
        badges = [html.Span("－", className="gl-tier-count")]
    return html.Div(badges, className="gl-tier-counts")


def _gl_card_title(gift: dict, counts: dict[str, int]) -> str:
    """カードのツールチップ。贈り物名と効果別の内訳、製造の2次ノードを出す。"""
    total = sum(counts.values())
    if not total:
        title = f"{gift['name']}（好物にしている生徒なし）"
    else:
        parts = [
            f"{TIER_LABEL[t]} {counts[t]}人" for t in GL_TIER_ORDER if counts.get(t)
        ]
        title = f"{gift['name']}（計 {total}人: {' / '.join(parts)}）"
    node = second_node(gift["name"])
    if node:
        title += f"\n製造 2次ノード: {node['node']}（{node['category']}）"
    return title


def gl_search_text(gift: dict) -> str:
    """絞り込み用の検索文字列。贈り物名に加えて2次ノード名・カテゴリでも引ける。"""
    text = gift["name"]
    node = second_node(gift["name"])
    if node:
        text += f" {node['node']} {node['category']}"
    return _search_text(text)


def _gl_gift_card(gift: dict, counts: dict[str, int]) -> html.Button:
    """贈り物1件のカード（アイコン・名前・効果別の人数）。

    製造の2次ノードで出る贈り物は、アイコンにノード名のバッジを重ねる。
    """
    node = second_node(gift["name"])
    return html.Button(
        [
            html.Div(
                [
                    html.Img(
                        src=gift_image_src(gift),
                        style={
                            "width": "44px",
                            "height": "34px",
                            "objectFit": "contain",
                        },
                    ),
                    node
                    and html.Span(
                        node["node"],
                        className="gl-node-badge",
                        title=f"製造 2次ノード: {node['node']}（{node['category']}）",
                    ),
                ],
                className="gl-icon-wrap",
            ),
            html.Div(gift["name"], className="gl-gift-name"),
            _gl_tier_counts(gift, counts),
        ],
        id={"type": "gl-gift", "gift": gift["id"]},
        n_clicks=0,
        className=gl_gift_class(gift),
        title=_gl_card_title(gift, counts),
    )


def create_gift_lookup_layout() -> html.Div:
    """贈り物逆引きページ。

    左に贈り物リスト、右にその贈り物を好物にしている生徒（衣装）を
    効果別に表示する2カラム構成。結果カラムはスクロールに追従する。
    """
    gifts = gl_lookup_gifts()
    if not gifts:
        return page_container([empty_note("贈り物データを読み込めませんでした。")])
    counts = get_gift_lover_counts()
    panel_style = {"marginBottom": "0"}
    return page_container(
        [
            page_intro(
                "贈り物を選ぶと、それを好物にしている生徒（衣装）を"
                "効果（特大 / 大 / 中）別に一覧します。",
                "好物は衣装ごとに異なるため、同じ生徒でも衣装によって効果が"
                "変わります。カード下部の数字は、その贈り物を好物にしている"
                "生徒（衣装）の人数を効果別に示したものです。"
                "贈り物名のほか、製造の2次ノード名（桜 など）やカテゴリ"
                "（化粧品 など）でも絞り込めます。",
            ),
            html.Div(
                [
                    # 左カラム: 贈り物の選択
                    html.Div(
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Strong("贈り物を選択"),
                                        html.Span(
                                            "高級", className="gl-legend gl-high"
                                        ),
                                        html.Span(
                                            "通常", className="gl-legend gl-normal"
                                        ),
                                        dcc.Input(
                                            id="gl-search",
                                            type="text",
                                            placeholder="贈り物名・2次ノード名で絞り込み...",
                                            value="",
                                            style={
                                                "marginLeft": "auto",
                                                "width": "200px",
                                                "maxWidth": "45%",
                                                "padding": "4px 8px",
                                            },
                                        ),
                                    ],
                                    style={
                                        "display": "flex",
                                        "alignItems": "center",
                                        "gap": "6px",
                                        "flexWrap": "wrap",
                                        "marginBottom": "8px",
                                        "fontSize": "0.75rem",
                                        "color": "#666",
                                    },
                                ),
                                html.Div(
                                    [
                                        _gl_gift_card(g, counts.get(g["id"], {}))
                                        for g in gifts
                                    ],
                                    id="gl-gift-grid",
                                    className="gl-gift-grid",
                                ),
                            ],
                            className="panel",
                            style=panel_style,
                        ),
                        className="gl-select-col",
                    ),
                    # 右カラム: 逆引き結果（スクロール追従）
                    html.Div(
                        html.Div(
                            id="gl-result",
                            children=empty_note("贈り物を選んでください。"),
                            className="panel",
                            style=panel_style,
                        ),
                        className="gl-result-col",
                    ),
                ],
                className="gl-columns",
            ),
            # 絞り込み用の検索テキスト {gift_id: 検索文字列}
            dcc.Store(
                id="gl-search-index",
                data={g["id"]: gl_search_text(g) for g in gifts},
            ),
        ]
    )


# ======================================================================
# 2次ノード比較ページ
# ======================================================================


def create_node_compare_layout() -> html.Div:
    """製造の2次ノード比較ページ。

    絆上げ対象の衣装を選ぶと、2次ノードごとに出る贈り物の絆EXP期待値を
    計算して降順に並べる。贈り物1つの価値は対象の中で最も効果の高い
    衣装に贈ったときの値（重みを設定した場合は 重み × EXP）。
    """
    return page_container(
        [
            page_intro(
                "製造で「素材の追加投入」をしたときの2次ノード（花弁系）を、"
                "出る贈り物の絆経験値の期待値で比較します。",
                "贈り物1つの値は、選んだ衣装の中で最も効果が高い衣装に"
                "贈ったときの獲得EXPです。ノード内の贈り物は等確率で出るため、"
                "その平均を期待値とします。重みを設定すると 重み × EXP の"
                "最大値で比較します（優先して上げたい衣装の重みを大きくする、"
                "など）。あわせて、1〜3次ノードまで含めた製造1回あたりの"
                "期待値も表示します。",
            ),
            panel(
                [
                    dcc.Dropdown(
                        id="nc-costume-dropdown",
                        options=get_costume_options(),
                        multi=True,
                        placeholder="生徒（衣装）を選択...（複数可）",
                        persistence=True,
                        persistence_type="local",
                    ),
                    dcc.Checklist(
                        id="nc-use-weight",
                        options=[{"label": " 重みを設定する", "value": "on"}],
                        value=[],
                        persistence=True,
                        persistence_type="local",
                        style={"marginTop": "8px", "fontSize": "0.85rem"},
                    ),
                    html.Div(id="nc-weight-container", style={"marginTop": "6px"}),
                ],
                title="絆上げ対象の衣装",
                className="panel-soft",
            ),
            html.Div(id="nc-craft-result", className="nc-craft-panel"),
            panel(
                html.Div(
                    id="nc-result",
                    children=empty_note("衣装を選んでください。"),
                ),
            ),
        ]
    )


# ======================================================================
# 家具ノード比較ページ
# ======================================================================


def _fn_star_row(star: dict) -> html.Div:
    """家具ノードの内訳: ★1行（★・ノード内の出現率・個数・1個のゲージ）。"""
    label = f"★{star['star']}" if star["star"] else "★1ノーマル"
    count = (
        f"{star['min']}個"
        if star["min"] == star["max"]
        else f"{star['min']}〜{star['max']}個"
    )
    return html.Div(
        [
            html.Span(label, className="fn-star"),
            html.Span(f"{star['rate'] * 100:.1f}%", className="nc-craft-rate"),
            html.Span(count, className="nc-craft-rate"),
            html.Span(f"1個 {GAUGE[star['star']]}%", className="nc-gift-name fn-gauge"),
        ],
        className="nc-gift-row",
    )


def fn_ranking(tier: int) -> list:
    """tier 次の家具ノードのランキング。各ノードは★別の内訳を折りたたみで持つ。"""
    rows = furniture_node_ranking(tier)
    top = rows[0]["ev"] if rows else 0
    items = []
    for rank, row in enumerate(rows, start=1):
        pct = row["ev"] / top * 100 if top else 0
        items.append(
            html.Details(
                [
                    html.Summary(
                        [
                            html.Span(f"{rank}", className="nc-rank"),
                            html.Span(row["node"], className="gl-node fn-node-name"),
                            html.Span(row["category"], className="nc-category"),
                            html.Span(
                                html.Span(
                                    className="nc-bar-fill",
                                    style={"width": f"{pct:.1f}%"},
                                ),
                                className="nc-bar",
                            ),
                            html.Strong(f"{row['ev']:.1f}%", className="nc-ev"),
                        ],
                        className="nc-summary",
                    ),
                    html.Div(
                        [
                            *[_fn_star_row(s) for s in row["stars"]],
                            html.P(
                                f"このノードの出現率 {row['appear'] * 100:.2f}%",
                                className="hint",
                            ),
                        ],
                        className="nc-gifts",
                    ),
                ],
                className="nc-node" + (" nc-top" if rank == 1 else ""),
            )
        )
    return items


def create_furniture_node_layout() -> html.Div:
    """製造の家具ノード比較ページ。

    2次の家具だけが出るノード（色彩・シリーズ・各色）を、出る家具を素材として
    追加投入したときのゲージ増加量の期待値で並べる。
    """
    return page_container(
        [
            page_intro(
                "製造の2次の家具ノードを、出る家具を素材として追加投入したときの"
                "ゲージ増加量の期待値で比較します。",
                f"追加投入したときのゲージ増加量は ★1家具 {GAUGE[1]}%・"
                f"★2家具 {GAUGE[2]}%・★3家具 {GAUGE[3]}% です（攻略 Wiki"
                "「製造」の表より）。ノードごとの★の出現率から期待値を計算"
                "します。家具以外も出るノード（明かり・輝き・煌めき）は"
                "含めません。",
            ),
            panel(
                fn_ranking(2),
                title="2次ノード",
                hint="行をクリックすると、★ごとの出現率と個数を表示します。",
            ),
        ]
    )


# ======================================================================
# 絆ランク管理ページ
# ======================================================================


def bm_search_index(options: list[dict]) -> dict[str, str]:
    """衣装ID -> 絞り込み用の検索文字列（小文字化済み）。"""
    return {
        str(o["value"]): f"{o['label']} {o.get('search', '')}".lower() for o in options
    }


def _google_login_button() -> html.A:
    """「Google でログイン」ボタン（Google のブランドガイドラインの
    ライトテーマ: 白地・灰色の枠・G ロゴ）。"""
    return html.A(
        [
            html.Img(
                src="/assets/google_g.svg",
                alt="",
                style={"width": "18px", "height": "18px"},
            ),
            html.Span("Google でログイン"),
        ],
        href="/auth/login/google",
        style={
            "display": "inline-flex",
            "alignItems": "center",
            "gap": "10px",
            "height": "40px",
            "padding": "0 12px",
            "boxSizing": "border-box",
            "background": "#fff",
            "border": "1px solid #747775",
            "borderRadius": "4px",
            "color": "#1f1f1f",
            "fontFamily": "Roboto, Arial, sans-serif",
            "fontSize": "14px",
            "fontWeight": 500,
            "textDecoration": "none",
        },
    )


# 絆ランク管理の一覧の列数の上限（見出しをこの数だけ用意する。style.css）
_BM_MAX_COLUMNS = 6


def _bm_ocr_panel() -> html.Div:
    """スクリーンショットからの読み取り。見出しの右に画像の選択ボタンを置き、
    撮り方・サンプル画像は折りたたむ。確認表（bm-ocr-preview）は読み取り後に出る。"""
    return panel(
        [
            html.Details(
                [
                    html.Summary("撮り方・サンプル画像"),
                    html.P(
                        "ゲームの「生徒リスト」画面を、並び替えを「絆ランク」に"
                        "してから撮影してください。スクロールしながら撮った複数枚を"
                        "まとめて選べます（画面の端で切れているカードは読み取りません）。",
                        className="hint",
                    ),
                    html.A(
                        html.Img(
                            src="/assets/ocr_example.jpg",
                            alt="生徒リスト画面のスクリーンショット例",
                            className="bm-ocr-example",
                        ),
                        href="/assets/ocr_example.jpg",
                        target="_blank",
                    ),
                ],
                className="bm-ocr-help",
            ),
            html.Div(id="bm-ocr-status", className="feedback"),
            html.Div(id="bm-ocr-preview"),
            dcc.Store(id="bm-ocr-refs"),
            dcc.Store(id="bm-ocr-result"),
            # カードの切り抜き画像。ブラウザ内（クライアントサイドのコールバック）
            # だけで使い、サーバーのコールバックの State にはしないこと。
            dcc.Store(id="bm-ocr-crops"),
        ],
        title="スクリーンショットから読み取り",
        actions=[
            dcc.Upload(
                id="bm-ocr-upload",
                multiple=True,
                accept="image/*",
                children=html.Span("画像を選択（ドロップも可）", className="btn"),
                className="bm-ocr-upload",
            )
        ],
        hint="生徒リスト画面の画像から絆ランクを読み取ります。"
        "画像はこのブラウザ内で処理し、サーバーには送信しません。",
        className="bm-ocr-panel",
    )


def _bm_image_modal() -> html.Div:
    """絆ランクの一覧の画像を表示するモーダル（assets/bond_image.js が描く）。
    スマホでも保存できるよう、ダウンロードではなく表示して長押しで保存してもらう。"""
    return html.Div(
        html.Div(
            [
                html.Div(
                    [
                        html.Strong("絆ランクの画像", style={"fontSize": "1.2rem"}),
                        html.Button(
                            "✕",
                            id="close-bm-image-btn",
                            n_clicks=0,
                            className="icon-btn",
                            style={"marginLeft": "auto"},
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "borderBottom": "1px solid #ddd",
                        "paddingBottom": "8px",
                        "marginBottom": "8px",
                    },
                ),
                html.P(
                    "画像を長押し（PC は右クリック）して保存できます。",
                    style={"color": "#888", "fontSize": "0.85rem", "margin": "0 0 8px"},
                ),
                # 画像だけをスクロールさせ、✕ボタンのある見出しは常に見えるようにする
                html.Div(
                    html.Img(
                        id="bm-image",
                        alt="絆ランクの一覧",
                        style={"maxWidth": "100%", "height": "auto"},
                    ),
                    style={"flex": "1", "minHeight": "0", "overflowY": "auto"},
                ),
            ],
            className="manual-modal-content",
        ),
        id="bm-image-modal",
        className="manual-modal-overlay",
        style={"display": "none"},
    )


def create_bond_ranks_layout() -> html.Div:
    """絆ランク管理ページ。

    全衣装の現在の絆ランクをブラウザ
    (localStorage) か、ログイン中ならサーバーに保存し、各計算ページの
    初期値として使う。
    行の描画は保存データを読む復元コールバックで行う。
    """
    auth_error = pop_auth_error()
    return page_container(
        [
            page_intro(
                "全生徒（衣装）の現在の絆ランクを管理します。"
                "入力した絆ランクは各計算ページで衣装を読み込んだときに自動で入力されます。",
                "対象は絆上げ優先度計算機・贈り物配分シミュレータ・必要絆経験値です"
                "（空欄の衣装は未設定として扱います）。各ページの"
                "「絆ランク管理に保存」ボタンで、そのページの入力値を保存することもできます。"
                "ログインしていないときはこのブラウザに保存します（他の端末・ブラウザとは"
                "共有されず、サイトデータを削除すると消えます）。右上の"
                "「Google でログイン」からログインするとサーバーに保存され、他の端末・"
                "ブラウザでも使えます（初回ログイン時はこのブラウザの内容を引き継ぎます）。"
                "保存するのは Google のユーザーIDのみで、メールアドレスや名前は保存しません。",
            ),
            # ログイン失敗などの通知（あるときだけ）
            auth_error and html.P(auth_error, className="auth-error"),
            _bm_ocr_panel(),
            panel(
                [
                    html.Div(
                        [
                            dcc.Input(
                                id="bm-search",
                                type="text",
                                value="",
                                placeholder="生徒名・衣装名で絞り込み...",
                                style={
                                    "flex": "1 1 220px",
                                    "maxWidth": "320px",
                                    "padding": "6px 8px",
                                },
                            ),
                            dcc.Checklist(
                                id="bm-only-set",
                                options=[{"label": " 設定済みのみ", "value": "on"}],
                                value=[],
                                style={"fontSize": "0.85rem"},
                            ),
                            dcc.Dropdown(
                                id="bm-sort",
                                options=[
                                    {"label": "標準の並び", "value": "default"},
                                    {"label": "絆ランクが高い順", "value": "desc"},
                                    {"label": "絆ランクが低い順", "value": "asc"},
                                ],
                                value="default",
                                clearable=False,
                                searchable=False,
                                style={"width": "180px", "fontSize": "0.85rem"},
                            ),
                            html.Span(
                                id="bm-count",
                                style={"color": "#888", "fontSize": "0.8rem"},
                            ),
                        ],
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "gap": "12px",
                            "flexWrap": "wrap",
                        },
                    ),
                    html.Div(id="bm-image-feedback", className="feedback"),
                    # 一覧は幅に応じて複数列に分け、上から下へ流す。見出しは
                    # 列ごとに出すため上限の列数ぶん用意し、余りは隠す（style.css）
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        [html.Span("衣装"), html.Span("絆ランク")],
                                        className="costume-head bm-grid",
                                    )
                                    for _ in range(_BM_MAX_COLUMNS)
                                ],
                                className="bm-heads",
                            ),
                            html.Div(
                                id="bm-container",
                                children=empty_note("読み込み中..."),
                                className="bm-rows",
                            ),
                        ],
                        className="costume-table",
                    ),
                ],
                title="衣装ごとの絆ランク",
                actions=[
                    html.Button(
                        "画像で保存",
                        id="bm-save-image-btn",
                        className="btn",
                        title="絆ランクを設定済みの衣装を、絆ランクの高い順に"
                        "1行10人ずつ並べた画像（PNG）を表示する",
                    )
                ],
                className="bm-list-panel",
            ),
            dcc.Store(
                id="bm-search-index", data=bm_search_index(get_costume_options())
            ),
            dcc.Interval(id="bm-init", max_intervals=1, interval=200),
            _bm_image_modal(),
        ]
    )


# ======================================================================
# ルートレイアウト（URL ルーティング）
# ======================================================================

# ページ切り替えタブに出す主要ページ。
PAGES = {
    "/chart-opt": ("絆上げ優先度計算機", create_layout),
    "/gift-simulation": ("贈り物配分シミュレータ", create_gift_simulator_layout),
    "/required-exp": ("必要絆経験値", create_required_exp_layout),
    "/gift-lookup": ("贈り物逆引き", create_gift_lookup_layout),
    "/node-compare": ("2次ノード比較", create_node_compare_layout),
    "/furniture-node": ("家具ノード比較", create_furniture_node_layout),
    "/bond-ranks": ("絆ランク管理", create_bond_ranks_layout),
}

# 主要ページ以外のページ（フッター等からのみアクセス）。
EXTRA_PAGES = {
    "/privacy": ("プライバシーポリシー", create_privacy_layout),
}

# 旧ルート互換 / ルートからのリダイレクト先。
ROOT_REDIRECT = "/chart-opt"


def create_root_layout() -> html.Div:
    """共通ヘッダー（タイトル・ログイン・タブ）+ ページ切り替えのルートシェル。

    ヘッダーとタブはページ遷移で再描画されず、page-content のみ差し替わる。
    タイトルとログインの行はスクロールしても画面上部に残す（style.css）。
    """
    return html.Div(
        [
            dcc.Location(id="url"),
            # タイトル + ログイン（スクロールしても画面上部に残す。style.css）
            html.Div(
                html.Div(
                    [
                        html.H1(SITE_NAME, className="site-title"),
                        _header_account(),
                    ],
                    className="site-header",
                ),
                className="site-header-bar",
            ),
            html.Div(_page_tabs_bar(), className="site-header-wrap"),
            html.Div(id="page-content"),
            *_bond_ranks_stores(),
        ]
    )


# サーバーへの保存に失敗したとき、再試行するまでの待ち時間（ミリ秒）
SYNC_RETRY_MS = 5000


def _bond_ranks_stores() -> list:
    """絆ランク管理の保存データ。全ページから参照するためルートに置く。

    未ログインならこのブラウザの localStorage に保存する。ログイン中は
    サーバーの保存値を初期値にしたメモリ上の Store にし、変更のたびに
    サーバーへ保存する（account-state 参照、コールバックは callbacks.py）。
    ログイン後に初めて開いたとき（サーバーに保存値が無いとき）は、
    このブラウザの localStorage の値を取り込む。ログイン中の値は localStorage
    にも書き写し、ログアウト後もログアウト直前の内容を使えるようにする。
    """
    user = current_user()
    data = None
    if user is not None:
        try:
            data = load_user_bond_ranks(user["id"])
        except Exception:
            # サーバーに保存できない状態ではこのブラウザへの保存にする
            user = None
    # サーバーへの保存に失敗したときの再試行タイマー（失敗したときだけ動かす）
    retry = dcc.Interval(
        id="account-retry", interval=SYNC_RETRY_MS, disabled=True, n_intervals=0
    )
    sync_error = html.Div(id="account-sync-error", className="account-sync-error")
    # localStorage への書き写し（main.py）の出力先。値は使わない。
    mirror = dcc.Store(id="bond-ranks-mirror")
    if user is None:
        return [
            dcc.Store(id="bond-ranks", storage_type="local"),
            dcc.Store(id="account-state", data={"user_id": None}),
            sync_error,
            retry,
            mirror,
        ]
    return [
        dcc.Store(id="bond-ranks", storage_type="memory", data=data),
        dcc.Store(
            id="account-state",
            data={"user_id": user["id"], "needs_import": data is None},
        ),
        sync_error,
        retry,
        mirror,
    ]
