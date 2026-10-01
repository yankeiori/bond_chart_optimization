"""製造の2次ノード対応表 (gift_craft) と逆引きページでの表示のテスト。"""

from pathlib import Path

import pytest

from dash import html

from app.backend.gift_craft import SECOND_NODES, compare_second_nodes, second_node
from app.frontend import callbacks
from app.frontend.callbacks import _gl_craft_section, _nc_weight
from app.frontend.layout import _gl_card_title, _gl_gift_card, gl_search_text

_GIFT_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "gift"
_ALL_NAMES = [name for _, _, names in SECOND_NODES for name in names]


def test_second_nodes_cover_35_unique_gifts():
    # Wiki の花弁ノード: 贈り物 35 種
    assert len(_ALL_NAMES) == 35
    assert len(set(_ALL_NAMES)) == 35


@pytest.mark.parametrize("name", _ALL_NAMES)
def test_gift_names_match_assets(name):
    # gift.name = アイコン画像のファイル名なので、表記ゆれがあれば検出できる
    assert (_GIFT_ASSETS / f"{name}.png").exists()


def test_second_node_lookup():
    node = second_node("お肌を透明にするBBクリーム")
    assert node["node"] == "桜"
    assert node["category"] == "化粧品"
    assert node["rate"] == pytest.approx(1 / 3)


def test_single_gift_node_rate():
    node = second_node("夏模様の浮き輪")
    assert node["node"] == "翡翠花"
    assert node["rate"] == 1.0


def test_high_gift_not_in_second_nodes():
    assert second_node("レースの枕") is None


def test_search_text_includes_node_and_category():
    text = gl_search_text({"name": "古典の詩集"})
    assert "古典の詩集" in text
    assert "チューリップ" in text
    assert "書籍" in text
    assert gl_search_text({"name": "レースの枕"}).startswith("レースの枕")


def test_card_title_mentions_node():
    title = _gl_card_title({"name": "天体望遠鏡"}, {"favorite": 2})
    assert "製造 2次ノード: 百日紅（おもちゃ）" in title
    assert "製造" not in _gl_card_title({"name": "レースの枕"}, {})


def _texts(component):
    out = []
    children = getattr(component, "children", None)
    if isinstance(children, str):
        out.append(children)
    elif isinstance(children, (list, tuple)):
        for c in children:
            out.extend(_texts(c) if not isinstance(c, str) else [c])
    elif children is not None:
        out.extend(_texts(children))
    return out


def test_craft_section_shows_node():
    texts = _texts(_gl_craft_section({"name": "エーポッドプロ"}))
    assert "薔薇" in texts
    assert "電子機器" in texts
    assert "ノード内 50.00%" in texts
    assert "ゲームガールカラー復刻版" not in texts


def test_craft_section_for_uncraftable_gift():
    texts = _texts(_gl_craft_section({"name": "レースの枕"}))
    assert any("出ません" in t for t in texts)


# ---------------------------------------------------------------------------
# 2次ノード比較
# ---------------------------------------------------------------------------

# DB の gift 相当。id は名前をそのまま使う（2次ノードの贈り物は全て normal）。
_GIFTS = [{"id": n, "name": n, "gift_type": "normal"} for n in _ALL_NAMES] + [
    {"id": "lace", "name": "レースの枕", "gift_type": "high"}
]


def _by_node(rows):
    return {r["node"]: r for r in rows}


def test_compare_without_members_is_base_exp():
    rows = compare_second_nodes(_GIFTS, [])
    # 14 ノード + 花弁
    assert len(rows) == 15
    assert all(r["ev"] == 20 for r in rows)


def test_compare_takes_max_over_members():
    members = [
        {
            "label": "A",
            "weight": 1.0,
            "present": {"エーポッドプロ": "ultraFavorite"},
        },
        {
            "label": "B",
            "weight": 1.0,
            "present": {
                "エーポッドプロ": "favorite",
                "ゲームガールカラー復刻版": "superFavorite",
            },
        },
    ]
    rows = compare_second_nodes(_GIFTS, members)
    rose = _by_node(rows)["薔薇"]
    # エーポッドプロ: max(80, 40)=80 / ゲームガール: max(20, 60)=60
    assert rose["ev"] == pytest.approx(70)
    assert rows[0]["node"] == "薔薇"
    detail = {g["name"]: g for g in rose["gifts"]}
    assert detail["エーポッドプロ"]["label"] == "A"
    assert detail["ゲームガールカラー復刻版"]["label"] == "B"
    # 花弁は 35 種の平均: (80 + 60 + 20*33) / 35
    assert _by_node(rows)["花弁"]["ev"] == pytest.approx((80 + 60 + 20 * 33) / 35)
    # 好物にしている衣装が無い贈り物は相手なし
    other = _by_node(rows)["翡翠花"]["gifts"][0]
    assert other["label"] is None and other["value"] == 20


def test_compare_weight_changes_best_member():
    members = [
        {"label": "A", "weight": 1.0, "present": {"夏模様の浮き輪": "favorite"}},
        {"label": "B", "weight": 3.0, "present": {}},
    ]
    gift = _by_node(compare_second_nodes(_GIFTS, members))["翡翠花"]["gifts"][0]
    # A: 1*40=40 < B: 3*20=60 → 好物でなくても重みの大きい B に贈る方が高い
    assert gift["value"] == 60
    assert gift["tier"] is None


def test_compare_zero_weight_excludes_member():
    members = [
        {"label": "A", "weight": 0.0, "present": {"夏模様の浮き輪": "ultraFavorite"}},
        {"label": "B", "weight": 1.0, "present": {}},
    ]
    gift = _by_node(compare_second_nodes(_GIFTS, members))["翡翠花"]["gifts"][0]
    assert gift["value"] == 20


def test_compare_skips_gifts_missing_from_db():
    gifts = [g for g in _GIFTS if g["name"] != "O-フィット"]
    members = [
        {"label": "A", "weight": 1.0, "present": {"ペロロの腹筋ローラー": "favorite"}}
    ]
    node = _by_node(compare_second_nodes(gifts, members))["アサガオ"]
    assert len(node["gifts"]) == 1
    assert node["ev"] == 40


def test_nc_weight_normalization():
    assert _nc_weight(None) == 1.0
    assert _nc_weight("abc") == 1.0
    assert _nc_weight(-2) == 0.0
    assert _nc_weight(2.5) == 2.5


@pytest.fixture
def _nc_db(monkeypatch):
    monkeypatch.setattr(callbacks, "load_gifts", lambda: _GIFTS)
    monkeypatch.setattr(
        callbacks,
        "get_costume_options",
        lambda: [{"label": "A", "value": 1}, {"label": "B（水着）", "value": 2}],
    )
    presents = {1: {"百科事典": "ultraFavorite"}, 2: {"古典の詩集": "superFavorite"}}
    monkeypatch.setattr(
        callbacks, "get_costume_present_map", lambda cid: presents.get(cid, {})
    )


def test_nc_compare_ranks_nodes(_nc_db):
    result = callbacks.nc_compare([1, 2], [], [], [])
    texts = _texts(html.Div(result))
    # チューリップ: (80 + 60 + 20*4) / 6 = 36.7 が1位
    assert texts.index("チューリップ") < texts.index("花弁")
    assert "36.7 EXP" in texts
    assert "B（水着）" in texts


def test_nc_compare_uses_weights_only_when_enabled(_nc_db):
    ids = [{"type": "nc-weight", "costume": 1}, {"type": "nc-weight", "costume": 2}]
    off = _texts(html.Div(callbacks.nc_compare([1, 2], [], [0, 0], ids)))
    assert "36.7 EXP" in off
    on = _texts(html.Div(callbacks.nc_compare([1, 2], ["on"], [0, 2], ids)))
    # A は重み0で除外。B: 古典の詩集 2*60=120、他 2*20=40 → (120+40*5)/6
    assert f"{(120 + 40 * 5) / 6:.1f}" in on


def test_nc_compare_requires_selection(_nc_db):
    assert "衣装を選んでください" in _texts(callbacks.nc_compare([], [], [], []))[0]


def test_nc_render_weights_keeps_previous_values(_nc_db):
    prev_ids = [{"type": "nc-weight", "costume": 1}]
    out = callbacks.nc_render_weights([1, 2], ["on"], [3], prev_ids)
    inputs = [c.children[1] for c in out[1].children]  # nc-weight-row: [label, input]
    assert [i.value for i in inputs] == [3, 1.0]
    assert callbacks.nc_render_weights([1, 2], [], [3], prev_ids) == []


def _find_class(component, cls):
    out = []
    if cls in (getattr(component, "className", None) or "").split():
        out.append(component)
    children = getattr(component, "children", None)
    if not isinstance(children, (list, tuple)):
        children = [children]
    for c in children:
        if c is not None and not isinstance(c, str):
            out.extend(_find_class(c, cls))
    return out


def test_lookup_card_shows_node_badge():
    card = _gl_gift_card({"id": "x", "name": "百科事典", "gift_type": "normal"}, {})
    badges = _find_class(card, "gl-node-badge")
    assert [b.children for b in badges] == ["チューリップ"]


def test_lookup_card_without_node_has_no_badge():
    card = _gl_gift_card({"id": "lace", "name": "レースの枕", "gift_type": "high"}, {})
    assert _find_class(card, "gl-node-badge") == []
