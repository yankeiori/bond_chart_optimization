import sys
from pathlib import Path

from dash import html, dcc

from app.backend.student import BOND_RANGES
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

LABEL_STYLE = {"fontSize": "1rem", "whiteSpace": "nowrap"}


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

    bond_fields = []
    for i, (lo, hi) in enumerate(BOND_RANGES):
        bond_fields.append(
            html.Div(
                [
                    html.Label(f"絆{lo}~{hi}", style=LABEL_STYLE),
                    dcc.Input(
                        id={"type": "bond", "range_idx": i, "index": index},
                        type="number",
                        value=bond_bonuses[i],
                        min=0,
                        debounce=True,
                        autoComplete="off",
                        style={"width": "72px", "textAlign": "center"},
                    ),
                ],
                style={
                    "display": "flex",
                    "flexDirection": "column",
                    "alignItems": "center",
                },
            )
        )

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
                        style={"marginLeft": "8px", "flex": "1", "fontSize": "0.85rem"},
                    ),
                    html.Button(
                        "✕",
                        id={"type": "remove-student", "index": index},
                        n_clicks=0,
                        className="remove-student-btn",
                        style={
                            "marginLeft": "auto",
                            "background": "none",
                            "border": "none",
                            "cursor": "pointer",
                            "fontSize": "1.1rem",
                        },
                    ),
                ],
                className="student-card-header",
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "marginBottom": "8px",
                },
            ),
            # 絆ボーナス入力行
            html.Div(
                bond_fields,
                className="bond-fields",
                style={"display": "flex", "gap": "8px", "flexWrap": "wrap"},
            ),
        ],
        id={"type": "student-card", "index": index},
        className="student-card",
        style={
            "border": "1px solid #ccc",
            "borderRadius": "8px",
            "padding": "12px",
            "marginBottom": "10px",
            "background": "#fafafa",
        },
    )


def _make_bond_rank_input(
    index: int, *, costume_name: str = "", value: int = 20
) -> html.Div:
    """衣装ごとの現在の絆ランク入力欄を1つ生成する。"""
    btn_style = {
        "width": "24px",
        "height": "14px",
        "border": "1px solid #ccc",
        "background": "#f5f5f5",
        "cursor": "pointer",
        "fontSize": "0.65rem",
        "lineHeight": "1",
        "padding": "0",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "center",
    }
    return html.Div(
        [
            html.Label(
                costume_name or _default_costume_name(index),
                id={"type": "bond-rank-label", "index": index},
                style={**LABEL_STYLE, "textAlign": "center"},
            ),
            html.Div(
                [
                    dcc.Input(
                        id={"type": "bond-rank", "index": index},
                        type="number",
                        value=value,
                        debounce=True,
                        style={"width": "50px", "textAlign": "center"},
                    ),
                    html.Div(
                        [
                            html.Button(
                                "▲",
                                id={"type": "bond-rank-inc", "index": index},
                                n_clicks=0,
                                style={**btn_style, "borderRadius": "3px 3px 0 0"},
                            ),
                            html.Button(
                                "▼",
                                id={"type": "bond-rank-dec", "index": index},
                                n_clicks=0,
                                style={**btn_style, "borderRadius": "0 0 3px 3px"},
                            ),
                        ],
                        style={
                            "display": "flex",
                            "flexDirection": "column",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "1px"},
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "alignItems": "center",
            "gap": "4px",
        },
    )


def _contact_span(nowrap: bool = True) -> html.Span:
    """不具合・要望報告の連絡先（フォーム / X アカウント）。"""
    link_style = {"color": "#4a90d9", "textDecoration": "underline"}
    style = {"fontSize": "0.85rem"}
    if nowrap:
        style["whiteSpace"] = "nowrap"
    return html.Span(
        [
            "不具合・要望報告は外部サービスの",
            html.A(
                "フォーム",
                href="https://forms.gle/yxJYDAY55TPDkMr39",
                target="_blank",
                rel="noopener noreferrer",
                style=link_style,
            ),
            "か",
            html.A(
                "Xアカウント",
                href="https://x.com/yankeiori",
                target="_blank",
                rel="noopener noreferrer",
                style=link_style,
            ),
            "まで",
        ],
        style=style,
    )


def _footer() -> html.Div:
    """全ページ共通フッター。プライバシーポリシーへのリンクを置く。"""
    return html.Div(
        [
            dcc.Link(
                "プライバシーポリシー",
                href="/privacy",
                style={"color": "#4a90d9", "textDecoration": "underline"},
            ),
        ],
        style={
            "marginTop": "32px",
            "paddingTop": "12px",
            "borderTop": "1px solid #ddd",
            "textAlign": "center",
            "fontSize": "0.8rem",
            "color": "#888",
        },
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


def _page_tabs_bar() -> html.Div:
    """ページ切り替えタブバー（共通ヘッダー内に1つだけ配置）。

    アクティブ表示は URL に応じてクライアントサイドで className を
    切り替える（main.py のコールバック参照）。見た目は style.css の
    .page-tab / .page-tab-active で定義する。
    """
    return html.Div(
        [
            dcc.Link(
                label,
                href=path,
                id={"type": "page-tab", "path": path},
                className="page-tab",
            )
            for path, (label, _) in PAGES.items()
        ],
        className="page-tabs",
    )


def create_layout() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Button(
                                "📖 マニュアル",
                                id="open-manual-btn",
                                n_clicks=0,
                                style={
                                    "background": "#4a90d9",
                                    "color": "white",
                                    "border": "none",
                                    "borderRadius": "4px",
                                    "padding": "6px 16px",
                                    "cursor": "pointer",
                                    "fontSize": "0.9rem",
                                    "whiteSpace": "nowrap",
                                },
                            ),
                        ],
                        className="page-header-right",
                        style={
                            "marginLeft": "auto",
                            "display": "flex",
                            "alignItems": "center",
                            "gap": "12px",
                        },
                    ),
                ],
                className="page-header",
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "marginBottom": "16px",
                },
            ),
            # マニュアルモーダル
            html.Div(
                html.Div(
                    [
                        html.Div(
                            [
                                html.Strong("マニュアル", style={"fontSize": "1.2rem"}),
                                html.Button(
                                    "✕",
                                    id="close-manual-btn",
                                    n_clicks=0,
                                    style={
                                        "marginLeft": "auto",
                                        "background": "none",
                                        "border": "none",
                                        "cursor": "pointer",
                                        "fontSize": "1.3rem",
                                    },
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
                        dcc.Markdown(
                            _MANUAL_MD, style={"overflowY": "auto", "flex": "1"}
                        ),
                    ],
                    className="manual-modal-content",
                ),
                id="manual-modal",
                className="manual-modal-overlay",
                style={"display": "none"},
            ),
            html.Div(
                [
                    # サイドバー
                    html.Div(
                        [
                            # プリセット読み込み
                            html.Div(
                                [
                                    html.Strong("プリセット"),
                                    html.Div(
                                        [
                                            html.Div(
                                                dcc.Dropdown(
                                                    id="preset-dropdown",
                                                    options=get_student_options(),
                                                    placeholder="生徒を選択...",
                                                ),
                                                style={"flex": "1", "minWidth": "0"},
                                            ),
                                            html.Button(
                                                "☆",
                                                id="fav-toggle-btn",
                                                n_clicks=0,
                                                title="お気に入りに追加/解除",
                                                style={
                                                    "flexShrink": "0",
                                                    "background": "none",
                                                    "border": "1px solid #ccc",
                                                    "borderRadius": "4px",
                                                    "cursor": "pointer",
                                                    "fontSize": "1.1rem",
                                                    "padding": "4px 10px",
                                                    "lineHeight": "1",
                                                },
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "gap": "6px",
                                            "alignItems": "stretch",
                                            "marginTop": "6px",
                                        },
                                    ),
                                    dcc.RadioItems(
                                        id="preset-status-radio",
                                        options=[],
                                        inline=True,
                                        style={
                                            "marginTop": "6px",
                                            "fontSize": "0.85rem",
                                        },
                                        labelStyle={
                                            "marginRight": "10px",
                                            "cursor": "pointer",
                                        },
                                    ),
                                    html.Button(
                                        "読み込み",
                                        id="load-preset-btn",
                                        n_clicks=0,
                                        style={
                                            "marginTop": "8px",
                                            "width": "100%",
                                            "background": "#27ae60",
                                            "color": "white",
                                            "border": "none",
                                            "borderRadius": "4px",
                                            "padding": "6px 16px",
                                            "cursor": "pointer",
                                        },
                                    ),
                                ],
                                className="preset-section",
                                style={
                                    "padding": "10px",
                                    "border": "1px solid #ddd",
                                    "borderRadius": "8px",
                                    "background": "#f5f5ff",
                                },
                            ),
                            # プリセット投稿
                            html.Details(
                                [
                                    html.Summary(
                                        "プリセット投稿",
                                        style={
                                            "cursor": "pointer",
                                            "fontWeight": "bold",
                                        },
                                    ),
                                    html.Div(
                                        [
                                            html.P(
                                                "現在の絆ボーナスの入力内容を、全ユーザーが利用できるプリセットとして共有します。"
                                                "保存機能ではありません。",
                                                style={
                                                    "fontSize": "0.8rem",
                                                    "color": "#666",
                                                    "margin": "0 0 8px 0",
                                                },
                                            ),
                                            dcc.Input(
                                                id="submit-character-name",
                                                type="text",
                                                placeholder="生徒名を入力...",
                                                style={
                                                    "width": "100%",
                                                    "marginTop": "6px",
                                                    "fontSize": "0.85rem",
                                                },
                                            ),
                                            dcc.Dropdown(
                                                id="submit-status-name",
                                                options=[
                                                    {"label": s, "value": s}
                                                    for s in (
                                                        "攻撃",
                                                        "HP",
                                                        "治癒力",
                                                        "防御",
                                                    )
                                                ],
                                                placeholder="ステータス名を選択...",
                                                style={
                                                    "marginTop": "6px",
                                                    "fontSize": "0.85rem",
                                                },
                                            ),
                                            dcc.ConfirmDialogProvider(
                                                html.Button(
                                                    "投稿",
                                                    style={
                                                        "marginTop": "8px",
                                                        "width": "100%",
                                                        "background": "#e67e22",
                                                        "color": "white",
                                                        "border": "none",
                                                        "borderRadius": "4px",
                                                        "padding": "6px 16px",
                                                        "cursor": "pointer",
                                                    },
                                                ),
                                                id="submit-preset-btn",
                                                message="プリセットを投稿しますか？",
                                            ),
                                            html.Div(
                                                id="submit-feedback",
                                                style={
                                                    "marginTop": "6px",
                                                    "fontSize": "0.8rem",
                                                },
                                            ),
                                        ],
                                        style={"marginTop": "8px"},
                                    ),
                                ],
                                className="submit-section",
                                style={
                                    "padding": "10px",
                                    "border": "1px solid #ddd",
                                    "borderRadius": "8px",
                                    "background": "#fff8f0",
                                    "marginTop": "12px",
                                },
                            ),
                        ],
                        className="sidebar",
                        style={
                            "width": "220px",
                            "flexShrink": "0",
                            "position": "sticky",
                            "top": "20px",
                            "alignSelf": "flex-start",
                            "zIndex": "10",
                        },
                    ),
                    # メインコンテンツ
                    html.Div(
                        [
                            html.Div(
                                id="students-container",
                                children=[make_student_card(0)],
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "+ 衣装追加",
                                        id="add-student-btn",
                                        className="add-student-btn",
                                        n_clicks=0,
                                        style={
                                            "padding": "8px 16px",
                                            "cursor": "pointer",
                                            "borderRadius": "6px",
                                            "border": "1px solid #ccc",
                                            "background": "#fff",
                                            "fontSize": "0.95rem",
                                        },
                                    ),
                                ],
                                style={"marginBottom": "16px"},
                            ),
                            # 現在の絆ランク入力
                            html.Div(
                                [
                                    html.Strong(
                                        "現在の絆ランク",
                                        style={
                                            "marginBottom": "8px",
                                            "display": "block",
                                        },
                                    ),
                                    html.Div(
                                        id="bond-rank-container",
                                        children=[_make_bond_rank_input(0)],
                                        className="bond-rank-row",
                                        style={
                                            "display": "flex",
                                            "gap": "8px",
                                            "flexWrap": "wrap",
                                        },
                                    ),
                                ],
                                className="bond-rank-section",
                                style={
                                    "padding": "12px",
                                    "border": "1px solid #ccc",
                                    "borderRadius": "8px",
                                    "background": "#f0f8f0",
                                    "marginBottom": "16px",
                                },
                            ),
                            # 衣装ごとの好物（normal 以外を 衣装×リアクション の表で表示）
                            html.Div(
                                [
                                    html.Strong(
                                        "衣装ごとの好物",
                                        style={
                                            "marginBottom": "8px",
                                            "display": "block",
                                        },
                                    ),
                                    html.Div(
                                        id="present-display",
                                        children=html.P(
                                            "プリセットを読み込むと表示されます。",
                                            style={"color": "#888", "margin": "8px 0"},
                                        ),
                                    ),
                                ],
                                style={
                                    "padding": "12px",
                                    "border": "1px solid #ccc",
                                    "borderRadius": "8px",
                                    "marginBottom": "16px",
                                },
                            ),
                            # 高度な設定（折りたたみ）
                            html.Details(
                                [
                                    html.Summary(
                                        "高度な設定",
                                        style={
                                            "cursor": "pointer",
                                            "fontWeight": "bold",
                                            "marginBottom": "8px",
                                        },
                                    ),
                                    html.Div(
                                        [
                                            # 衣装優先度
                                            html.Div(
                                                [
                                                    html.Strong(
                                                        "衣装優先度（タイブレーク）",
                                                        style={
                                                            "display": "block",
                                                            "marginBottom": "6px",
                                                        },
                                                    ),
                                                    html.P(
                                                        "上が高優先。同スコア時に優先度が高い衣装を先にします。",
                                                        style={
                                                            "fontSize": "0.8rem",
                                                            "color": "#666",
                                                            "margin": "0 0 8px 0",
                                                        },
                                                    ),
                                                    html.Div(
                                                        id="costume-priority-container",
                                                        style={
                                                            "display": "flex",
                                                            "flexDirection": "column",
                                                            "gap": "4px",
                                                        },
                                                    ),
                                                ],
                                                style={"marginBottom": "16px"},
                                            ),
                                            # 絆50ペナルティ
                                            html.Div(
                                                [
                                                    html.Strong(
                                                        "絆50到達ペナルティ",
                                                        style={
                                                            "display": "block",
                                                            "marginBottom": "6px",
                                                        },
                                                    ),
                                                    html.P(
                                                        "絆50到達時のボーナス減衰率。1に近いほど50到達を後回しにします。",
                                                        style={
                                                            "fontSize": "0.8rem",
                                                            "color": "#666",
                                                            "margin": "0 0 8px 0",
                                                        },
                                                    ),
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
                                                ],
                                            ),
                                        ],
                                        style={
                                            "padding": "12px",
                                            "border": "1px solid #ddd",
                                            "borderRadius": "8px",
                                            "background": "#f9f9ff",
                                        },
                                    ),
                                ],
                                style={"marginBottom": "16px"},
                            ),
                            # チャート計算ボタン
                            html.Div(
                                html.Button(
                                    "チャート計算",
                                    id="calc-chart-btn",
                                    n_clicks=0,
                                    style={
                                        "width": "100%",
                                        "padding": "12px 24px",
                                        "fontSize": "1.1rem",
                                        "fontWeight": "bold",
                                        "background": "#4a90d9",
                                        "color": "white",
                                        "border": "none",
                                        "borderRadius": "6px",
                                        "cursor": "pointer",
                                    },
                                ),
                                className="calc-btn-wrapper",
                            ),
                            # 計算結果表示エリア
                            html.Div(
                                id="chart-result",
                                className="chart-result-area",
                                style={"marginTop": "16px"},
                            ),
                        ],
                        style={"flex": "1", "minWidth": "0"},
                    ),
                ],
                className="main-columns",
                style={"display": "flex", "gap": "20px", "alignItems": "flex-start"},
            ),
            # 非表示 Store 群
            dcc.Store(id="student-indices", data=[0]),
            dcc.Store(id="next-student-index", data=1),
            dcc.Store(id="solver-inputs"),
            dcc.Store(id="submit-preset-status"),
            dcc.Store(id="costume-priority-order", data=[{"idx": 0, "name": "衣装1"}]),
            dcc.Store(id="autosave", storage_type="local"),
            # 復元完了フラグ: False の間は autosave への保存をブロックする
            # （動的レイアウト挿入時の初期発火で保存データが潰れるのを防ぐ）
            dcc.Store(id="autosave-ready", data=False),
            dcc.Store(id="favorites", storage_type="local", data=[]),
            dcc.Interval(id="autosave-init", max_intervals=1, interval=200),
            _footer(),
        ],
        className="page-container",
        style={
            "maxWidth": "1200px",
            "margin": "0 auto",
            "padding": "20px",
            "fontFamily": "sans-serif",
        },
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


def create_gift_simulator_layout() -> html.Div:
    """贈り物配分シミュレータページ（入力部）。"""
    gifts = load_gifts()
    # プリセット未読込時は好み無し（all 型・常時使用対象のみ可）
    gift_list_children = build_gs_gift_list(gifts, lambda g: gs_default_used(g))
    return html.Div(
        [
            # プリセット読み込み
            html.Div(
                [
                    html.Strong("プリセット"),
                    html.P(
                        [
                            "プリセットの追加は",
                            dcc.Link(
                                "絆上げ優先度計算機",
                                href="/chart-opt",
                                style={
                                    "color": "#4a90d9",
                                    "textDecoration": "underline",
                                },
                            ),
                            "から行ってください。",
                        ],
                        style={
                            "fontSize": "0.8rem",
                            "color": "#666",
                            "margin": "6px 0 0 0",
                        },
                    ),
                    html.Div(
                        dcc.Dropdown(
                            id="gs-preset-dropdown",
                            options=get_student_options(),
                            placeholder="生徒を選択...",
                        ),
                        style={"marginTop": "6px"},
                    ),
                    dcc.RadioItems(
                        id="gs-status-radio",
                        options=[],
                        inline=True,
                        style={"marginTop": "6px", "fontSize": "0.85rem"},
                        labelStyle={"marginRight": "10px", "cursor": "pointer"},
                    ),
                    html.Button(
                        "読み込み",
                        id="gs-load-preset-btn",
                        n_clicks=0,
                        style={
                            "marginTop": "8px",
                            "background": "#27ae60",
                            "color": "white",
                            "border": "none",
                            "borderRadius": "4px",
                            "padding": "6px 16px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Div(
                        id="gs-load-feedback",
                        style={"marginTop": "6px", "fontSize": "0.85rem"},
                    ),
                ],
                style={
                    "padding": "12px",
                    "border": "1px solid #ccc",
                    "borderRadius": "8px",
                    "background": "#f5f5ff",
                    "marginBottom": "16px",
                    "maxWidth": "420px",
                },
            ),
            # 衣装・上昇量（表示のみ）＋ 現在の絆ランク入力
            html.Div(
                [
                    html.Strong("衣装 / 優先順位 / 現在の絆ランク / 絆ボーナス"),
                    html.P(
                        "▲▼ の並び順が優先順位です（上が最優先）。"
                        "絆ボーナス合計・使用個数が同点のとき、"
                        "上の衣装ほど絆ランクが高くなる配分を選びます"
                        "（もらえる絆ボーナスや使う贈り物の数は変わりません）。",
                        style={
                            "color": "#888",
                            "fontSize": "0.8rem",
                            "margin": "4px 0 0",
                        },
                    ),
                    html.Div(
                        id="gs-costume-display",
                        children=html.P(
                            "プリセットを読み込んでください。",
                            style={"color": "#888", "margin": "8px 0"},
                        ),
                        style={"marginTop": "8px"},
                    ),
                ],
                style={
                    "padding": "12px",
                    "border": "1px solid #ccc",
                    "borderRadius": "8px",
                    "marginBottom": "16px",
                },
            ),
            # 衣装ごとの好物（normal 以外を 衣装×リアクション の表で表示）
            html.Div(
                [
                    html.Strong("衣装ごとの好物"),
                    html.Div(
                        id="gs-present-display",
                        children=html.P(
                            "プリセットを読み込んでください。",
                            style={"color": "#888", "margin": "8px 0"},
                        ),
                        style={"marginTop": "8px"},
                    ),
                ],
                style={
                    "padding": "12px",
                    "border": "1px solid #ccc",
                    "borderRadius": "8px",
                    "marginBottom": "16px",
                },
            ),
            # 贈り物リスト
            html.Div(
                [
                    html.Strong("贈り物（所持数・使用可否）"),
                    html.Div(
                        gift_list_children,
                        id="gs-gift-list",
                        style={"marginTop": "8px"},
                    ),
                ],
                style={
                    "padding": "12px",
                    "border": "1px solid #ccc",
                    "borderRadius": "8px",
                },
            ),
            # 計算開始
            html.Div(
                [
                    html.Button(
                        "計算開始",
                        id="gs-calc-btn",
                        n_clicks=0,
                        style={
                            "background": "#4a90d9",
                            "color": "white",
                            "border": "none",
                            "borderRadius": "4px",
                            "padding": "10px 32px",
                            "fontSize": "1rem",
                            "cursor": "pointer",
                        },
                    ),
                    dcc.Loading(
                        type="circle",
                        children=html.Div(
                            id="gs-calc-result",
                            style={"marginTop": "12px", "minHeight": "24px"},
                        ),
                    ),
                ],
                style={"marginTop": "16px"},
            ),
            dcc.Store(id="gs-loaded-preset"),
            # 衣装の優先順位（衣装 index の並び。先頭が最優先）
            dcc.Store(id="gs-costume-order", data=[]),
            dcc.Store(id="gs-autosave", storage_type="local"),
            # 復元完了フラグ: False の間は gs-autosave への保存をブロックする
            dcc.Store(id="gs-autosave-ready", data=False),
            dcc.Interval(id="gs-autosave-init", max_intervals=1, interval=300),
            _footer(),
        ],
        className="page-container",
        style={
            "maxWidth": "1200px",
            "margin": "0 auto",
            "padding": "20px",
            "fontFamily": "sans-serif",
        },
    )


# ======================================================================
# 必要絆経験値（ページ）
# ======================================================================


def create_required_exp_layout() -> html.Div:
    """必要絆経験値 計算ページ。

    生徒（衣装）ごとに、現在の絆ランクから目標絆ランクまでに必要な
    絆経験値と、その贈り物選択ボックス換算個数を計算する。
    """
    return html.Div(
        [
            html.P(
                "追加した生徒（衣装）ごとに、現在の絆ランク（既定 20）から"
                "目標絆ランク（既定 50）まで上げるのに必要な絆経験値を計算します。"
                "所持している贈り物を入力すると、最適に充当した上で"
                "それでも不足する絆経験値と、その贈り物選択ボックス換算の"
                "個数を表示します（ボックス1個あたりの獲得EXPは衣装の好物"
                "（通常タイプの最高効果）で決まります）。"
                "衣装は ▲▼ ボタンで並び替えでき、上の衣装ほど優先されます"
                "（不足ボックスの総数を増やさない範囲で、順位が上の衣装から"
                "不足が出ないように所持贈り物を充当します）。",
                style={"fontSize": "0.85rem", "color": "#666", "margin": "0 0 16px"},
            ),
            # 生徒（衣装）の追加
            html.Div(
                [
                    html.Strong("衣装の追加"),
                    html.Div(
                        [
                            html.Div(
                                dcc.Dropdown(
                                    id="rb-costume-dropdown",
                                    options=get_costume_options(),
                                    placeholder="生徒（衣装）を選択...",
                                ),
                                style={"flex": "1", "minWidth": "0"},
                            ),
                            html.Button(
                                "＋ 追加",
                                id="rb-add-costume-btn",
                                n_clicks=0,
                                style={
                                    "flexShrink": "0",
                                    "background": "#27ae60",
                                    "color": "white",
                                    "border": "none",
                                    "borderRadius": "4px",
                                    "padding": "6px 16px",
                                    "cursor": "pointer",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "gap": "6px",
                            "alignItems": "stretch",
                            "marginTop": "6px",
                        },
                    ),
                    html.Div(
                        id="rb-add-feedback",
                        style={"marginTop": "6px", "fontSize": "0.85rem"},
                    ),
                ],
                style={
                    "padding": "12px",
                    "border": "1px solid #ccc",
                    "borderRadius": "8px",
                    "background": "#f5f5ff",
                    "marginBottom": "16px",
                    "maxWidth": "480px",
                },
            ),
            # 追加済み衣装の 現在絆ランク / 目標絆ランク 入力
            html.Div(
                [
                    html.Strong("衣装（上ほど優先） / 現在の絆ランク / 目標絆ランク"),
                    html.Div(
                        id="rb-costume-container",
                        children=html.P(
                            "生徒（衣装）を追加してください。",
                            style={"color": "#888", "margin": "8px 0"},
                        ),
                        style={"marginTop": "8px"},
                    ),
                ],
                style={
                    "padding": "12px",
                    "border": "1px solid #ccc",
                    "borderRadius": "8px",
                    "marginBottom": "16px",
                },
            ),
            # 贈り物リスト（所持数・使用可否）
            html.Div(
                [
                    html.Strong("所持贈り物（所持数・使用可否）"),
                    html.P(
                        "所持数を入力すると、追加した衣装へ最適に充当した上で"
                        "不足分を計算します。すべて 0 のままでも計算できます"
                        "（純粋な必要絆経験値のみ）。追加した衣装の好物・"
                        "全生徒対象・選択ボックス以外は効率が悪いため"
                        "デフォルトで使用OFF（折りたたみ内）です。",
                        style={
                            "fontSize": "0.8rem",
                            "color": "#666",
                            "margin": "6px 0 0",
                        },
                    ),
                    html.Div(
                        build_gs_gift_list(
                            load_gifts(),
                            lambda g: gs_default_used(g),
                            id_prefix="rb",
                        ),
                        id="rb-gift-list",
                        style={"marginTop": "8px"},
                    ),
                ],
                style={
                    "padding": "12px",
                    "border": "1px solid #ccc",
                    "borderRadius": "8px",
                    "marginBottom": "16px",
                },
            ),
            # 計算
            html.Div(
                [
                    html.Button(
                        "必要絆経験値を計算",
                        id="rb-calc-btn",
                        n_clicks=0,
                        style={
                            "background": "#8e44ad",
                            "color": "white",
                            "border": "none",
                            "borderRadius": "4px",
                            "padding": "10px 32px",
                            "fontSize": "1rem",
                            "cursor": "pointer",
                        },
                    ),
                    dcc.Loading(
                        type="circle",
                        children=html.Div(
                            id="rb-calc-result",
                            style={"marginTop": "12px", "minHeight": "24px"},
                        ),
                    ),
                ],
            ),
            # 追加済みの生徒（衣装）リスト [{costume_id, label}, ...]
            dcc.Store(id="rb-costumes", data=[]),
            dcc.Store(id="rb-autosave", storage_type="local"),
            # 復元完了フラグ: False の間は rb-autosave への保存をブロックする
            dcc.Store(id="rb-autosave-ready", data=False),
            dcc.Interval(id="rb-autosave-init", max_intervals=1, interval=300),
            _footer(),
        ],
        className="page-container",
        style={
            "maxWidth": "1200px",
            "margin": "0 auto",
            "padding": "20px",
            "fontFamily": "sans-serif",
        },
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
        return html.Div(
            [
                html.P(
                    "贈り物データを読み込めませんでした。",
                    style={"color": "#888"},
                ),
                _footer(),
            ],
            className="page-container",
            style={"maxWidth": "1200px", "margin": "0 auto", "padding": "20px"},
        )
    counts = get_gift_lover_counts()
    panel_style = {
        "padding": "12px",
        "border": "1px solid #ccc",
        "borderRadius": "8px",
    }
    return html.Div(
        [
            html.P(
                "贈り物を選ぶと、それを好物にしている生徒（衣装）を"
                "効果（特大 / 大 / 中）別に一覧します。好物は衣装ごとに"
                "異なるため、同じ生徒でも衣装によって効果が変わります。"
                "カード下部の数字は、その贈り物を好物にしている生徒（衣装）の"
                "人数を効果別に示したものです。"
                "贈り物名のほか、製造の2次ノード名（桜 など）やカテゴリ"
                "（化粧品 など）でも絞り込めます。",
                style={"fontSize": "0.85rem", "color": "#666", "margin": "0 0 12px"},
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
                            style=panel_style,
                        ),
                        className="gl-select-col",
                    ),
                    # 右カラム: 逆引き結果（スクロール追従）
                    html.Div(
                        html.Div(
                            id="gl-result",
                            children=html.P(
                                "贈り物を選んでください。",
                                style={"color": "#888", "margin": "8px 0"},
                            ),
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
            _footer(),
        ],
        className="page-container",
        style={
            "maxWidth": "1200px",
            "margin": "0 auto",
            "padding": "20px",
            "fontFamily": "sans-serif",
        },
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
    panel_style = {
        "padding": "12px",
        "border": "1px solid #ccc",
        "borderRadius": "8px",
        "marginBottom": "16px",
    }
    return html.Div(
        [
            html.P(
                [
                    "製造で「素材の追加投入」をしたときの2次ノード（花弁系）を、"
                    "出る贈り物の絆経験値の期待値で比較します。贈り物1つの値は、"
                    "選んだ衣装の中で最も効果が高い衣装に贈ったときの獲得EXPです。"
                    "ノード内の贈り物は等確率で出るため、その平均を期待値とします。"
                    "重みを設定すると 重み × EXP の最大値で比較します"
                    "（優先して上げたい衣装の重みを大きくする、など）。",
                ],
                style={"fontSize": "0.85rem", "color": "#666", "margin": "0 0 16px"},
            ),
            html.Div(
                [
                    html.Strong("絆上げ対象の衣装"),
                    dcc.Dropdown(
                        id="nc-costume-dropdown",
                        options=get_costume_options(),
                        multi=True,
                        placeholder="生徒（衣装）を選択...（複数可）",
                        persistence=True,
                        persistence_type="local",
                        style={"marginTop": "6px"},
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
                style={**panel_style, "background": "#f5f5ff"},
            ),
            html.Div(
                html.Div(
                    id="nc-result",
                    children=html.P(
                        "衣装を選んでください。",
                        style={"color": "#888", "margin": "8px 0"},
                    ),
                ),
                style=panel_style,
            ),
            _footer(),
        ],
        className="page-container",
        style={
            "maxWidth": "1200px",
            "margin": "0 auto",
            "padding": "20px",
            "fontFamily": "sans-serif",
        },
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
}

# 主要ページ以外のページ（フッター等からのみアクセス）。
EXTRA_PAGES = {
    "/privacy": ("プライバシーポリシー", create_privacy_layout),
}

# 旧ルート互換 / ルートからのリダイレクト先。
ROOT_REDIRECT = "/chart-opt"


def create_root_layout() -> html.Div:
    """共通ヘッダー（タイトル・報告先・タブ）+ ページ切り替えのルートシェル。

    ヘッダーとタブはページ遷移で再描画されず、page-content のみ差し替わる。
    """
    return html.Div(
        [
            dcc.Location(id="url"),
            html.Div(
                [
                    html.Div(
                        [
                            html.H1(
                                "絆上げ優先度計算機",
                                className="site-title",
                                style={"margin": "0", "fontSize": "1.5rem"},
                            ),
                            html.Div(
                                _contact_span(nowrap=False),
                                style={"marginLeft": "auto"},
                            ),
                        ],
                        className="site-header",
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "gap": "16px",
                            "flexWrap": "wrap",
                            "marginBottom": "10px",
                        },
                    ),
                    _page_tabs_bar(),
                ],
                className="site-header-wrap",
                style={
                    "maxWidth": "1200px",
                    "margin": "0 auto",
                    "padding": "16px 20px 0",
                    "fontFamily": "sans-serif",
                },
            ),
            html.Div(id="page-content"),
        ]
    )
