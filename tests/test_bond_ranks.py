"""絆ランク管理のデータ操作のテスト。"""

import pytest
from dash.exceptions import PreventUpdate

from app.backend.bond_ranks import (
    apply_page_edits,
    merge_ocr_cards,
    normalize_bond_ranks,
    ranks_for_costumes,
    save_bond_ranks,
)
from app.frontend.callbacks import (
    _bm_ocr_apply,
    _bm_ocr_preview,
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
            {"costume_id": "3", "rank": "30", "remain": 100},  # 旧形式の残りEXPは捨てる
            {"costume_id": 3, "rank": 40},  # 重複は先勝ち
            {"costume_id": None, "rank": 10},
            "bad",
            {"costume_id": 5, "rank": 101},  # 範囲外のランクは未設定扱い
            {"costume_id": 6, "rank": 100},
        )
        assert normalize_bond_ranks(data) == [
            {"costume_id": 3, "rank": 30},
            {"costume_id": 6, "rank": 100},
        ]


class TestSaveBondRanks:
    DATA = _data(
        {"costume_id": 1, "rank": 20},
        {"costume_id": 2, "rank": 30},
    )

    def test_upsert(self):
        new = save_bond_ranks(self.DATA, {1: 25, 3: 77})
        assert new["costumes"] == [
            {"costume_id": 1, "rank": 25},
            {"costume_id": 2, "rank": 30},
            {"costume_id": 3, "rank": 77},
        ]

    def test_invalid_rank_skipped(self):
        new = save_bond_ranks(self.DATA, {1: None, 2: 101, 3: "x"})
        assert new["costumes"] == self.DATA["costumes"]


class TestApplyPageEdits:
    DATA = _data(
        {"costume_id": 1, "rank": 20},
        {"costume_id": 2, "rank": 30},
    )

    def test_blank_rank_clears(self):
        new = apply_page_edits(self.DATA, {1: None, 2: 30, 3: None})
        assert [e["costume_id"] for e in new["costumes"]] == [2]

    def test_out_of_range_keeps_old(self):
        new = apply_page_edits(self.DATA, {1: 101, 3: 0})
        assert new["costumes"] == self.DATA["costumes"]

    def test_new_and_unlisted(self):
        # 入力欄に無い衣装 (2) はそのまま、新しく入力した衣装 (3) は追加
        new = apply_page_edits(self.DATA, {3: 12})
        assert [e["costume_id"] for e in new["costumes"]] == [1, 2, 3]
        assert new["costumes"][2] == {"costume_id": 3, "rank": 12}


class TestRanksForCostumes:
    def test_maps_by_position(self):
        data = _data(
            {"costume_id": 1, "rank": 25},
            {"costume_id": 3, "rank": 45},
        )
        assert ranks_for_costumes(data, [3, 2, 1, None]) == {0: 45, 2: 25}

    def test_empty(self):
        assert ranks_for_costumes(None, [1, 2]) == {}


class TestOverlayBondRanks:
    def test_saved_values_win_and_clear_stale_remain(self):
        data = _data(
            {"costume_id": 10, "rank": 40},
            {"costume_id": 11, "rank": 33},
        )
        ranks, remains, n = _overlay_bond_ranks(
            data, [10, 11, 12], {0: 20, 1: 33, 2: 15}, {0: 99, 1: 12, 2: 7}
        )
        assert n == 2
        assert ranks == {0: 40, 1: 33, 2: 15}
        # 絆ランクが変わった衣装の残りEXPは消し、それ以外の入力は保持
        assert remains == {1: 12, 2: 7}


class TestSaveInputsToBondRanks:
    def test_saves_by_costume_id(self):
        saved, n = _save_inputs_to_bond_ranks(
            None, [10, None, 12, 13], {0: 30, 1: 40, 2: 101, 3: 75}
        )
        # costume_id 無し (index 1) と範囲外 (index 2) は保存しない
        assert n == 2
        assert saved["costumes"] == [
            {"costume_id": 10, "rank": 30},
            {"costume_id": 13, "rank": 75},
        ]


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
        data = _data({"costume_id": 2, "rank": 30})
        options = [{"value": 1, "label": "ホシノ"}, {"value": 2, "label": "ノア"}]
        rows = _bm_rows(data, options)
        assert [r.children[0].children[-1] for r in rows] == ["ホシノ", "ノア"]
        assert [len(r.children) for r in rows] == [2, 2]  # 残りEXP欄は無い
        rank = [r.children[1] for r in rows]
        assert rank[0].value is None  # 未設定
        assert rank[1].id == {"type": "bm-rank", "costume": 2}
        assert rank[1].value == 30

    def test_no_options(self):
        assert "衣装データがありません" in _bm_rows(None, []).children


class TestMergeOcrCards:
    def test_garbage(self):
        assert merge_ocr_cards(None) == []
        assert merge_ocr_cards(["x", {"costume_id": None, "rank": 3}]) == []

    def test_dedupe_prefers_certain_and_caps_rank(self):
        cards = [
            {"costume_id": 1, "rank": 31, "uncertain": True},
            {"costume_id": 2, "rank": 186, "uncertain": False},
            {"costume_id": 1, "rank": 31, "uncertain": False},  # 重なりで再読
            {"costume_id": 3, "rank": None, "uncertain": False},
            {"costume_id": "4", "rank": "0"},
        ]
        assert merge_ocr_cards(cards) == [
            {"costume_id": 1, "rank": 31, "read": 31, "uncertain": False},
            # 100 を超える値は 100 にする
            {"costume_id": 2, "rank": 100, "read": 186, "uncertain": False},
            # 読めなかった数字は要確認
            {"costume_id": 3, "rank": None, "read": None, "uncertain": True},
            {"costume_id": 4, "rank": None, "read": None, "uncertain": True},
        ]

    def test_conflicting_uncertain_reading(self):
        # 取り違えの可能性があるので、確実な値を使いつつ要確認にする
        cards = [
            {"costume_id": 1, "rank": 30, "uncertain": False},
            {"costume_id": 1, "rank": 1, "uncertain": True},
        ]
        assert merge_ocr_cards(cards) == [
            {"costume_id": 1, "rank": 30, "read": 30, "uncertain": True}
        ]

    def test_conflicting_certain_readings(self):
        cards = [
            {"costume_id": 1, "rank": 30, "uncertain": False},
            {"costume_id": 1, "rank": 38, "uncertain": False},
        ]
        assert merge_ocr_cards(cards) == [
            {"costume_id": 1, "rank": 30, "read": 30, "uncertain": True}
        ]


class TestBmOcrPreview:
    OPTIONS = [{"value": 1, "label": "ホシノ"}, {"value": 2, "label": "ノア"}]

    def test_rows_uncertain_first_and_unknown_dropped(self):
        result = {
            "cards": [
                {"costume_id": 1, "rank": 40, "uncertain": False},
                {"costume_id": 2, "rank": 20, "uncertain": True},
                {"costume_id": 99, "rank": 20, "uncertain": False},  # 衣装に無い
            ],
            "partial": 2,
        }
        data = _data({"costume_id": 1, "rank": 35})
        status, preview = _bm_ocr_preview(result, data, self.OPTIONS)
        assert "2 衣装を読み取りました" in status.children
        assert "（要確認 1）" in status.children
        assert any("切れていたカード 2 枚" in c for c in status.children)
        rows = preview[0].children
        inputs = [r.children[1].children[1] for r in rows]
        assert [i.id["costume"] for i in inputs] == [2, 1]
        assert [i.value for i in inputs] == [20, 40]
        assert [r.children[2].children for r in rows] == ["現在: 未設定", "現在: 35"]
        assert preview[1].id == "bm-ocr-apply-btn"

    def test_nothing_read(self):
        status, preview = _bm_ocr_preview(
            {"cards": [], "failed": 1}, None, self.OPTIONS
        )
        assert status.style == {"color": "red"}
        assert preview == []

    def test_error_and_invalid(self):
        status, _ = _bm_ocr_preview({"error": True}, None, self.OPTIONS)
        assert "失敗" in status.children
        with pytest.raises(PreventUpdate):
            _bm_ocr_preview(None, None, self.OPTIONS)


class TestBmOcrApply:
    def test_sets_ranks(self):
        ids = [{"type": "bm-rank", "costume": c} for c in (1, 2, 3)]
        ranks, n = _bm_ocr_apply(
            [30, None, 72, 99],
            [{"costume": c} for c in (1, 2, 3, 4)],  # 4 は一覧に無い
            [30, 20, 10],
            ids,
        )
        assert ranks == [30, 20, 72]
        assert n == 2
