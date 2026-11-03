"""絆ランク管理のデータ操作のテスト。"""

import pytest
from dash.exceptions import PreventUpdate

from app.backend.bond_exp import BOND_EXP_PER_LEVEL
from app.backend.bond_ranks import (
    apply_page_edits,
    bond_rank_stats,
    merge_ocr_cards,
    normalize_bond_ranks,
    ranks_for_costumes,
    save_bond_ranks,
)
from app.frontend.callbacks import (
    _bm_ocr_apply,
    _bm_ocr_preview,
    _bm_rows,
    _bs_hist_bins,
    _bs_render,
    bs_bin_size,
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
        assert [len(r.children) for r in rows] == [4, 4]  # 衣装 / 絆ランク / -1 / +1
        rank = [r.children[1] for r in rows]
        assert rows[1].children[2].id == {"type": "bm-rank-dec", "costume": 2}
        assert rows[1].children[3].id == {"type": "bm-rank-inc", "costume": 2}
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
            {
                "costume_id": 1,
                "rank": 31,
                "read": 31,
                "uncertain": False,
                "names": [],
                "dropped": 0,
            },
            # 100 を超える値は 100 にする
            {
                "costume_id": 2,
                "rank": 100,
                "read": 186,
                "uncertain": False,
                "names": [],
                "dropped": 0,
            },
            # 読めなかった数字は要確認
            {
                "costume_id": 3,
                "rank": None,
                "read": None,
                "uncertain": True,
                "names": [],
                "dropped": 0,
            },
            {
                "costume_id": 4,
                "rank": None,
                "read": None,
                "uncertain": True,
                "names": [],
                "dropped": 0,
            },
        ]

    def test_conflicting_uncertain_reading(self):
        # 取り違えの可能性があるので、確実な値を使いつつ要確認にする
        cards = [
            {"costume_id": 1, "rank": 30, "uncertain": False},
            {"costume_id": 1, "rank": 1, "uncertain": True},
        ]
        assert merge_ocr_cards(cards) == [
            {
                "costume_id": 1,
                "rank": 30,
                "read": 30,
                "uncertain": True,
                "names": [],
                "dropped": 0,
            }
        ]

    def test_conflicting_certain_readings(self):
        cards = [
            {"costume_id": 1, "rank": 30, "uncertain": False},
            {"costume_id": 1, "rank": 38, "uncertain": False},
        ]
        assert merge_ocr_cards(cards) == [
            {
                "costume_id": 1,
                "rank": 30,
                "read": 30,
                "uncertain": True,
                "names": [],
                "dropped": 0,
            }
        ]

    def test_name_mismatch(self):
        # 食い違った名前は重複なくまとめる。名前の合うカードがある衣装では、
        # 食い違ったカード（別の生徒）は使わない
        cards = [
            {"costume_id": 1, "rank": 12, "uncertain": True, "name": "ツルギ"},
            {"costume_id": 1, "rank": 12, "uncertain": True, "name": "ツルギ"},
            {"costume_id": 2, "rank": 5, "uncertain": False, "name": 3},
            {"costume_id": 3, "rank": 51, "uncertain": False},
            {"costume_id": 3, "rank": 21, "uncertain": False, "name": "フブキ"},
        ]
        assert merge_ocr_cards(cards) == [
            {
                "costume_id": 1,
                "rank": 12,
                "read": 12,
                "uncertain": True,
                "names": ["ツルギ"],
                "dropped": 0,
            },
            {
                "costume_id": 2,
                "rank": 5,
                "read": 5,
                "uncertain": False,
                "names": [],
                "dropped": 0,
            },
            {
                "costume_id": 3,
                "rank": 51,
                "read": 51,
                "uncertain": False,
                "names": [],
                "dropped": 1,
            },
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
        rows = preview[1].children
        inputs = [r.children[1].children[1] for r in rows]
        assert [i.id["costume"] for i in inputs] == [2, 1]
        assert [i.value for i in inputs] == [20, 40]
        assert [r.children[2].children for r in rows] == ["現在: 未設定", "現在: 35"]
        assert preview[0].id == "bm-ocr-apply-btn"
        # 要確認の行にだけカードの切り抜きの置き場所がある
        assert rows[0].children[-1].id == {"type": "bm-ocr-crops", "costume": 2}
        assert not any(
            isinstance(c.id, dict) and c.id["type"] == "bm-ocr-crops"
            for c in rows[1].children
            if hasattr(c, "id")
        )

    def test_name_mismatch_not_applied_by_default(self):
        result = {
            "cards": [
                {"costume_id": 1, "rank": 12, "uncertain": True, "name": "ツルギ"}
            ]
        }
        status, preview = _bm_ocr_preview(result, None, self.OPTIONS)
        assert not any("名前が一致しなかったカード" in c for c in status.children)
        row = preview[1].children[0]
        assert row.children[1].children[1].value is None
        notes = [c for c in row.children if isinstance(c, str)]
        assert "（読み取り値 12）" in notes
        assert "（名前が一致しません。近い名前: ツルギ）" in notes

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


class TestBondRankStats:
    _OPTIONS = [
        {"value": 1, "label": "アル", "student": "アル"},
        {"value": 2, "label": "アル（ドレス）", "student": "アル"},
        {"value": 3, "label": "ムツキ", "student": "ムツキ"},
        {"value": 4, "label": "カヨコ", "student": "カヨコ"},
    ]

    def test_counts_known_costumes_only(self):
        data = _data(
            {"costume_id": 1, "rank": 100},
            {"costume_id": 2, "rank": 47},
            {"costume_id": 3, "rank": 9},
            {"costume_id": 99, "rank": 80},  # 削除済みの衣装
        )
        st = bond_rank_stats(data, self._OPTIONS)
        assert st["count"] == 3
        assert st["costume_total"] == 4
        assert st["students"] == 2
        assert st["student_total"] == 3
        assert st["total"] == 156
        assert st["avg"] == 52
        assert st["median"] == 47
        assert st["bonus_max"] == 1
        assert st["max_rank"] == 1
        assert st["ranks"] == [9, 47, 100]
        assert [r["label"] for r in st["top"]] == ["アル", "アル（ドレス）", "ムツキ"]

    def test_exp(self):
        exp_to = lambda r: sum(BOND_EXP_PER_LEVEL[: r - 1])  # noqa: E731
        data = _data({"costume_id": 1, "rank": 100}, {"costume_id": 3, "rank": 20})
        st = bond_rank_stats(data, self._OPTIONS)
        assert st["exp_total"] == exp_to(100) + exp_to(20)
        assert st["exp_to_bonus_max"] == exp_to(50) - exp_to(20)
        assert st["exp_to_max"] == exp_to(100) - exp_to(20)

    def test_near(self):
        data = _data(
            {"costume_id": 1, "rank": 99},
            {"costume_id": 2, "rank": 45},
            {"costume_id": 3, "rank": 44},  # 5ランクより手前
            {"costume_id": 4, "rank": 49},
        )
        near = bond_rank_stats(data, self._OPTIONS)["near"]
        # 必要な絆経験値の少ない順（99→100 は 45→50 より少ない）
        assert [(r["label"], r["target"]) for r in near] == [
            ("カヨコ", 50),
            ("アル", 100),
            ("アル（ドレス）", 50),
        ]
        assert near[0]["exp"] == BOND_EXP_PER_LEVEL[48]
        assert near[1]["exp"] == BOND_EXP_PER_LEVEL[98]

    def test_empty(self):
        st = bond_rank_stats(None, self._OPTIONS)
        assert st["count"] == 0
        assert st["avg"] is None
        assert st["near"] == []

    def test_students_without_name(self):
        options = [*self._OPTIONS, {"value": 5, "label": "不明"}]
        data = _data({"costume_id": 1, "rank": 10}, {"costume_id": 5, "rank": 10})
        st = bond_rank_stats(data, options)
        assert st["count"] == 2
        assert st["students"] == 1
        assert st["student_total"] == 3


class TestBsRender:
    _OPTIONS = [
        {"value": 1, "label": "アル", "student": "アル"},
        {"value": 2, "label": "ムツキ", "student": "ムツキ"},
    ]

    def test_renders_sections(self):
        out = str(_bs_render(_data({"costume_id": 1, "rank": 48}), self._OPTIONS))
        assert "1 / 2" in out
        assert "あと少しの衣装" in out
        assert "48 → 50" in out
        assert "bs-hist-graph" in out

    def test_no_ranks(self):
        out = str(_bs_render(None, self._OPTIONS))
        assert "まだ設定されていません" in out
        assert "/bond-ranks" in out


class TestBsBinSize:
    def test_bins_10(self):
        bins = _bs_hist_bins([1, 9, 10, 99, 100], 10)
        assert [b["label"] for b in bins][:2] == ["1〜9", "10〜19"]
        assert [b["label"] for b in bins][-2:] == ["90〜99", "100"]
        assert [b["count"] for b in bins] == [2, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1]

    def test_bins_1_and_5(self):
        assert len(_bs_hist_bins([], 1)) == 100
        assert [b["label"] for b in _bs_hist_bins([], 5)][:2] == ["1〜4", "5〜9"]

    def test_figure(self):
        fig = bs_bin_size(5, [3, 48])
        assert fig.data[0].customdata[0] == "1〜4"
        assert fig.data[0].y[0] == 1

    def test_invalid(self):
        for v in (None, 0, 2, 7):
            with pytest.raises(PreventUpdate):
                bs_bin_size(v, [1])
        with pytest.raises(PreventUpdate):
            bs_bin_size(10, None)
