"""絆ランク管理のデータ操作のテスト。"""

from app.backend.bond_ranks import (
    apply_page_edits,
    normalize_bond_ranks,
    ranks_for_costumes,
    save_bond_ranks,
)
from app.frontend.callbacks import (
    _bm_rows,
    _co_costume_ids,
    _overlay_bond_ranks,
    _save_inputs_to_bond_ranks,
)


def _data(*entries):
    return {"costumes": list(entries)}


class TestNormalizeBondRanks:
    def test_none_and_garbage(self):
        assert normalize_bond_ranks(None) == []
        assert normalize_bond_ranks({"costumes": "x"}) == []
        assert normalize_bond_ranks([1, 2]) == []

    def test_drops_invalid_and_duplicates(self):
        data = _data(
            {"costume_id": "3", "rank": "30", "remain": 100},
            {"costume_id": 3, "rank": 40},  # 重複は先勝ち
            {"costume_id": None, "rank": 10},
            "bad",
            {"costume_id": 5, "rank": 99},  # 範囲外のランクは未設定扱い
            {"costume_id": 6, "rank": 50, "remain": 0},
        )
        assert normalize_bond_ranks(data) == [
            {"costume_id": 3, "rank": 30, "remain": 100},
            # 0 以下の残りEXPは未入力扱い
            {"costume_id": 6, "rank": 50, "remain": None},
        ]


class TestSaveBondRanks:
    DATA = _data(
        {"costume_id": 1, "rank": 20, "remain": 50},
        {"costume_id": 2, "rank": 30, "remain": 9},
    )

    def test_upsert_with_remain(self):
        new = save_bond_ranks(self.DATA, {1: 25, 3: 40}, {1: None, 3: 7})
        assert new["costumes"] == [
            {"costume_id": 1, "rank": 25, "remain": None},
            {"costume_id": 2, "rank": 30, "remain": 9},
            {"costume_id": 3, "rank": 40, "remain": 7},
        ]

    def test_invalid_rank_skipped(self):
        new = save_bond_ranks(self.DATA, {1: None, 2: 51, 3: "x"}, {})
        assert new["costumes"] == self.DATA["costumes"]

    def test_without_remain_inputs(self):
        # 残りEXP欄の無いページ: 同じランクなら残りEXPを保持、変われば未入力
        new = save_bond_ranks(self.DATA, {1: 20, 2: 31})
        assert new["costumes"] == [
            {"costume_id": 1, "rank": 20, "remain": 50},
            {"costume_id": 2, "rank": 31, "remain": None},
        ]


class TestApplyPageEdits:
    DATA = _data(
        {"costume_id": 1, "rank": 20, "remain": 50},
        {"costume_id": 2, "rank": 30, "remain": None},
    )

    def test_blank_rank_clears(self):
        new = apply_page_edits(self.DATA, {1: None, 2: 30, 3: None}, {})
        assert [e["costume_id"] for e in new["costumes"]] == [2]

    def test_out_of_range_keeps_old(self):
        new = apply_page_edits(self.DATA, {1: 60, 3: 0}, {1: 50, 3: None})
        assert new["costumes"] == self.DATA["costumes"]

    def test_new_and_unlisted(self):
        # 入力欄に無い衣装 (2) はそのまま、新しく入力した衣装 (3) は追加
        new = apply_page_edits(self.DATA, {3: 12}, {3: 5})
        assert [e["costume_id"] for e in new["costumes"]] == [1, 2, 3]
        assert new["costumes"][2] == {"costume_id": 3, "rank": 12, "remain": 5}


class TestRanksForCostumes:
    def test_maps_by_position(self):
        data = _data(
            {"costume_id": 1, "rank": 25, "remain": 40},
            {"costume_id": 3, "rank": 45, "remain": None},
        )
        ranks, remains = ranks_for_costumes(data, [3, 2, 1, None])
        assert ranks == {0: 45, 2: 25}
        assert remains == {2: 40}

    def test_empty(self):
        assert ranks_for_costumes(None, [1, 2]) == ({}, {})


class TestOverlayBondRanks:
    def test_saved_values_win_and_clear_stale_remain(self):
        data = _data(
            {"costume_id": 10, "rank": 40, "remain": None},
            {"costume_id": 11, "rank": 33, "remain": 12},
        )
        ranks, remains, n = _overlay_bond_ranks(
            data, [10, 11, 12], {0: 20, 1: 20, 2: 15}, {0: 99, 2: 7}
        )
        assert n == 2
        assert ranks == {0: 40, 1: 33, 2: 15}
        # 保存値で未入力の残りEXPは消し、未設定の衣装の入力は保持
        assert remains == {1: 12, 2: 7}


class TestSaveInputsToBondRanks:
    def test_saves_by_costume_id(self):
        saved, n = _save_inputs_to_bond_ranks(
            None, [10, None, 12, 13], {0: 30, 1: 40, 2: 99, 3: 45}, {0: 5}
        )
        # costume_id 無し (index 1) と範囲外 (index 2) は保存しない
        assert n == 2
        assert saved["costumes"] == [
            {"costume_id": 10, "rank": 30, "remain": 5},
            {"costume_id": 13, "rank": 45, "remain": None},
        ]

    def test_without_remain_keeps_same_rank_remain(self):
        data = _data({"costume_id": 10, "rank": 30, "remain": 5})
        saved, n = _save_inputs_to_bond_ranks(data, [10], {0: 30})
        assert n == 1
        assert saved["costumes"] == [{"costume_id": 10, "rank": 30, "remain": 5}]


class TestCoCostumeIds:
    def test_match_by_costume_name(self):
        loaded = [
            {"costume_name": "通常", "costume_id": 1},
            {"costume_name": "水着", "costume_id": 2},
        ]
        costume_values = ["水着", "手入力", "通常"]
        costume_ids = [{"index": 0}, {"index": 3}, {"index": 5}]
        rank_ids = [{"index": 5}, {"index": 0}, {"index": 3}]
        assert _co_costume_ids(loaded, costume_values, costume_ids, rank_ids) == [
            1,
            2,
            None,
        ]

    def test_nothing_loaded(self):
        assert _co_costume_ids([], ["通常"], [{"index": 0}], [{"index": 0}]) == [None]


class TestBmRows:
    def test_lists_all_options_with_saved_values(self):
        data = _data({"costume_id": 2, "rank": 30, "remain": 4})
        options = [{"value": 1, "label": "ホシノ"}, {"value": 2, "label": "ノア"}]
        rows = _bm_rows(data, options)
        assert [r.children[0].children for r in rows] == ["ホシノ", "ノア"]
        assert rows[0].children[2].value is None  # 未設定
        assert rows[1].children[2].id == {"type": "bm-rank", "costume": 2}
        assert rows[1].children[2].value == 30
        assert rows[1].children[4].value == 4

    def test_no_options(self):
        assert "衣装データがありません" in _bm_rows(None, []).children
