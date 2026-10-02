"""製造の2次ノード対応表 (gift_craft) と逆引きページでの表示のテスト。"""

from pathlib import Path

import numpy as np
import pytest

from dash import html

from app.backend.crafting_data import TIERS
from app.backend.gift_craft import (
    OFFERED_NODES,
    SECOND_NODES,
    compare_second_nodes,
    craft_expected_exp,
    second_node,
)
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


# ---------------------------------------------------------------------------
# 製造1回あたりの期待値（1〜3次）
# ---------------------------------------------------------------------------

_CRAFT_NAMES = {name for nodes in TIERS for *_, gifts in nodes for name, *_ in gifts}
# 3次の煌めきは高級贈り物（SSR）だけが出る
_HIGH_NAMES = {
    gift[0] for _, node, _, gifts in TIERS[2] if node == "煌めき" for gift in gifts
}
_CRAFT_GIFTS = [
    {"id": n, "name": n, "gift_type": "high" if n in _HIGH_NAMES else "normal"}
    for n in sorted(_CRAFT_NAMES)
]


def _craft_node(tier, name):
    result = craft_expected_exp(_CRAFT_GIFTS, [])
    return {n["name"]: n for n in result["tiers"][tier - 1]["nodes"]}[name]


def test_crafting_data_gift_names_match_assets():
    # 通常 35 種 + 高級 13 種
    assert len(_CRAFT_NAMES) == 48
    assert len(_HIGH_NAMES) == 13
    missing = [n for n in _CRAFT_NAMES if not (_GIFT_ASSETS / f"{n}.png").exists()]
    assert missing == []


def test_crafting_data_matches_second_node_table():
    # Wiki 由来の 2次ノード対応表と SchaleDB のデータが一致する
    nodes = {name: gifts for _, name, _, gifts in TIERS[1]}
    for node, _, names in SECOND_NODES:
        assert {g[0] for g in nodes[node]} == set(names)
        assert all(g[1] == pytest.approx(1 / len(names)) for g in nodes[node])


@pytest.mark.parametrize(
    "tier, name, chance",
    [
        # SchaleDB の ChanceJp（5つの提示に入る確率）
        (1, "花弁", 0.5257963479898812),
        (2, "花弁", 0.29914822370359295),
        (2, "牡丹", 0.024240005437418465),
        (3, "煌めき", 0.5858488105294458),
        (3, "花弁", 0.5590322781802878),
    ],
)
def test_offered_probability_matches_schaledb(tier, name, chance):
    assert _craft_node(tier, name)["offered"] == pytest.approx(chance, abs=1e-9)


def test_craft_expected_exp_without_members():
    result = craft_expected_exp(_CRAFT_GIFTS, [])
    by_tier = [t["ev"] for t in result["tiers"]]
    assert by_tier == pytest.approx([14.9391, 13.0893, 59.5496], abs=1e-4)
    assert result["ev"] == pytest.approx(sum(by_tier))
    # 3次の花弁: SR 2〜3個 (75%) と SSR 1〜2個 (25%)
    assert _craft_node(3, "花弁")["ev"] == pytest.approx(
        0.75 * 2.5 * 20 + 0.25 * 1.5 * 120
    )


def test_craft_picks_are_probabilities():
    for tier in craft_expected_exp(_CRAFT_GIFTS, [])["tiers"]:
        picks = [n["pick"] for n in tier["nodes"]]
        assert all(0 <= p <= n["offered"] + 1e-12 for p, n in zip(picks, tier["nodes"]))
        assert sum(picks) <= 1


def _simulate_tier(tier, gifts, members, samples=100_000):
    """モンテカルロ: 5つ提示して期待値最大のノードを選んだときの平均。"""
    result = craft_expected_exp(gifts, members)
    ev = {n["id"]: n["ev"] for n in result["tiers"][tier - 1]["nodes"]}
    nodes = TIERS[tier - 1]
    weights = np.array([n[2] for n in nodes], dtype=float)
    values = np.array([ev.get(n[0], 0.0) for n in nodes])
    rng = np.random.default_rng(0)
    arrival = rng.exponential(1 / weights, size=(samples, len(nodes)))
    offered = np.argpartition(arrival, OFFERED_NODES, axis=1)[:, :OFFERED_NODES]
    return values[offered].max(axis=1).mean(), result["tiers"][tier - 1]["ev"]


@pytest.mark.parametrize("tier", [1, 2, 3])
def test_craft_expected_exp_matches_simulation(tier):
    members = [
        {"label": "A", "weight": 1.0, "present": {"夏模様の浮き輪": "ultraFavorite"}},
        {"label": "B", "weight": 1.0, "present": {"レースの枕": "ultraFavorite"}},
    ]
    simulated, exact = _simulate_tier(tier, _CRAFT_GIFTS, members)
    assert simulated == pytest.approx(exact, rel=0.01)


def test_craft_picks_highest_expected_node():
    members = [
        {"label": "A", "weight": 1.0, "present": {"夏模様の浮き輪": "ultraFavorite"}}
    ]
    nodes = craft_expected_exp(_CRAFT_GIFTS, members)["tiers"][1]["nodes"]
    # 翡翠花（浮き輪のみ）は 80 で、花弁 (80 + 20*34) / 35 より上に来る
    assert nodes[0]["name"] == "翡翠花"
    assert nodes[0]["ev"] == 80
    # 翡翠花が提示されれば必ず選ぶ
    assert nodes[0]["pick"] == pytest.approx(nodes[0]["offered"])
    gift = nodes[0]["gifts"][0]
    assert gift["label"] == "A" and gift["amount"] == 1


def test_craft_zero_weight_gives_zero():
    members = [{"label": "A", "weight": 0.0, "present": {}}]
    assert craft_expected_exp(_CRAFT_GIFTS, members)["ev"] == 0


def test_nc_craft_exp_shows_total(_nc_db):
    assert callbacks.nc_craft_exp([], [], [], []) == []
    texts = _texts(html.Div(callbacks.nc_craft_exp([1, 2], [], [], [])))
    assert "製造1回あたりの期待値" in texts
    assert any(t.endswith(" EXP") for t in texts)
    assert "3次" in texts
