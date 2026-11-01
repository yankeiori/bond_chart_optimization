"""製造の家具ノード比較 (furniture_craft) と家具ノード比較ページのテスト。"""

import pytest

from app.backend.crafting_data import FURNITURE, TIERS
from app.backend.furniture_craft import COLOR_CATEGORIES, furniture_node_ranking
from app.frontend.layout import create_furniture_node_layout, fn_ranking


def _by_name(tier):
    return {r["node"]: r for r in furniture_node_ranking(tier)}


@pytest.mark.parametrize("tier", [1, 2, 3])
def test_star_rates_sum_to_one(tier):
    for row in furniture_node_ranking(tier):
        assert sum(s["rate"] for s in row["stars"]) == pytest.approx(1)


def test_furniture_nodes_exclude_mixed_nodes():
    # 明かり・輝き・煌めきは家具以外も出るので対象外
    for tier in (1, 2, 3):
        names = set(_by_name(tier))
        assert names.isdisjoint({"明かり", "輝き", "煌めき"})
        assert "色彩" in names
    ids = {node_id for nodes in TIERS for node_id, *_ in nodes}
    assert set(FURNITURE) <= ids


def test_second_tier_colors_have_categories():
    colors = set(_by_name(2)) & set(COLOR_CATEGORIES)
    assert colors == set(COLOR_CATEGORIES)


def test_third_tier_matches_wiki():
    # Wiki: 3次「★2以上の家具」は ★2 81.48%・★3 18.52%、出現率 12.53%
    row = _by_name(3)["色彩"]
    rates = {s["star"]: s["rate"] for s in row["stars"]}
    assert rates == pytest.approx({2: 0.8148, 3: 0.1852}, abs=1e-4)
    assert row["appear"] == pytest.approx(0.1253, abs=1e-4)
    # ★2 2〜3個 × 20%、★3 1〜2個 × 50%
    assert row["ev"] == pytest.approx(rates[2] * 2.5 * 20 + rates[3] * 1.5 * 50)


def test_second_tier_ranking():
    rows = furniture_node_ranking(2)
    assert [r["ev"] for r in rows] == sorted((r["ev"] for r in rows), reverse=True)
    # ★2以上しか出ない壁紙・背景・床が上位3つ
    assert {r["node"] for r in rows[:3]} == {"ブルー", "ホワイト", "ブラウン"}
    assert _by_name(2)["ブラウン"]["ev"] == pytest.approx(20)


def test_page_lists_every_node():
    assert len(fn_ranking(2)) == len(furniture_node_ranking(2))


def test_page_shows_only_second_tier():
    text = str(create_furniture_node_layout())
    assert "2次ノード" in text
    assert "1次ノード" not in text
    assert "3次ノード" not in text
