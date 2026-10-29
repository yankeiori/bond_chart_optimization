"""callbacks のヘルパー関数のテスト。

コールバック本体はDashサーバーが必要なため、純粋関数のみ検証する。
"""

from app.frontend.callbacks import (
    _gift_inputs_to_maps,
    _gs_costume_rows,
    _gs_furniture_cell,
    _gs_normalize_order,
    _rb_costume_rows,
    _rb_int_keys,
    _rb_merge_use_flags,
    _rb_shift_indices,
    _rb_swap_indices,
    _values_by_index,
)


class TestRbMergeUseFlags:
    CATALOG = [
        {"id": "gift-select-box", "gift_type": "normal"},
        {"id": "cake", "gift_type": "normal"},
        {"id": "doll", "gift_type": "high"},
        {"id": "flower-all", "gift_type": "high-all"},
    ]

    def test_new_favorite_turns_on(self):
        # 衣装追加で cake が好物になった → 既定値のままだった cake はONに
        out = _rb_merge_use_flags(self.CATALOG, {}, set(), {"cake"})
        assert out["cake"] is True
        assert out["doll"] is False
        assert out["gift-select-box"] is True  # 常時使用
        assert out["flower-all"] is True  # all 型

    def test_user_override_kept(self):
        # ユーザーが明示的にONにした doll は、好物でなくても保持
        use = {"doll": True}
        out = _rb_merge_use_flags(self.CATALOG, use, set(), {"cake"})
        assert out["doll"] is True

    def test_user_off_kept_when_still_favorite(self):
        # 好物だがユーザーがOFFにした cake は、衣装追加後もOFFのまま
        use = {"cake": False}
        out = _rb_merge_use_flags(self.CATALOG, use, {"cake"}, {"cake", "doll"})
        assert out["cake"] is False
        assert out["doll"] is True

    def test_removed_favorite_turns_off(self):
        # 衣装削除で doll が好物でなくなった → 既定値のままならOFFに
        use = {"doll": True}
        out = _rb_merge_use_flags(self.CATALOG, use, {"doll"}, set())
        assert out["doll"] is False


class TestGiftInputsToMaps:
    def test_maps(self):
        qty, use = _gift_inputs_to_maps(
            [3, None, "bad"],
            [{"gift": "a"}, {"gift": "b"}, {"gift": "c"}],
            [["use"], []],
            [{"gift": "a"}, {"gift": "b"}],
        )
        assert qty == {"a": 3, "b": 0, "c": 0}
        assert use == {"a": True, "b": False}


class TestRbIntKeys:
    def test_str_keys(self):
        assert _rb_int_keys({"0": 20, "2": 50}) == {0: 20, 2: 50}

    def test_none(self):
        assert _rb_int_keys(None) == {}


class TestRbValuesByIndex:
    def test_maps_by_index(self):
        values = [10, None, 30]
        ids = [{"index": 0}, {"index": 1}, {"index": 2}]
        assert _values_by_index(values, ids) == {0: 10, 2: 30}

    def test_empty(self):
        assert _values_by_index([], []) == {}


class TestRbShiftIndices:
    def test_remove_middle(self):
        # 行1を削除 → 行2以降が1つ繰り上がる
        assert _rb_shift_indices({0: "a", 1: "b", 2: "c"}, 1) == {0: "a", 1: "c"}

    def test_remove_first(self):
        assert _rb_shift_indices({0: "a", 1: "b"}, 0) == {0: "b"}

    def test_remove_last(self):
        assert _rb_shift_indices({0: "a", 1: "b"}, 1) == {0: "a"}

    def test_removed_index_absent(self):
        # 削除行に入力値が無くても他の行は正しく詰める
        assert _rb_shift_indices({0: "a", 2: "c"}, 1) == {0: "a", 1: "c"}


class TestRbCostumeRows:
    ENTRIES = [
        {"costume_id": 1, "label": "生徒A（通常）"},
        {"costume_id": 2, "label": "生徒A（水着）"},
    ]

    def test_empty_returns_message(self):
        rows = _rb_costume_rows([])
        assert getattr(rows, "children", None) == "生徒（衣装）を追加してください。"

    def test_row_count(self):
        rows = _rb_costume_rows(self.ENTRIES)
        assert len(rows) == 2

    def test_defaults(self):
        rows = _rb_costume_rows(self.ENTRIES)
        inputs = {
            (c.id["type"], c.id["index"]): c
            for row in rows
            for c in row.children
            if isinstance(getattr(c, "id", None), dict)
        }
        assert inputs[("rb-bond-rank", 0)].value == 20
        assert inputs[("rb-bond-target", 0)].value == 50
        assert inputs[("rb-bond-remain", 0)].value is None

    def test_value_carryover(self):
        rows = _rb_costume_rows(
            self.ENTRIES, ranks={1: 33}, remains={1: 100}, targets={1: 40}
        )
        inputs = {
            (c.id["type"], c.id["index"]): c
            for row in rows
            for c in row.children
            if isinstance(getattr(c, "id", None), dict)
        }
        assert inputs[("rb-bond-rank", 1)].value == 33
        assert inputs[("rb-bond-remain", 1)].value == 100
        assert inputs[("rb-bond-target", 1)].value == 40

    def test_move_buttons_disabled_at_ends(self):
        rows = _rb_costume_rows(self.ENTRIES)
        inputs = {
            (c.id["type"], c.id["index"]): c
            for row in rows
            for c in row.children
            if isinstance(getattr(c, "id", None), dict)
        }
        assert inputs[("rb-move-up", 0)].disabled is True
        assert inputs[("rb-move-down", 0)].disabled is False
        assert inputs[("rb-move-up", 1)].disabled is False
        assert inputs[("rb-move-down", 1)].disabled is True


class TestRbSwapIndices:
    def test_swap_both_present(self):
        assert _rb_swap_indices({0: "a", 1: "b", 2: "c"}, 0, 1) == {
            0: "b",
            1: "a",
            2: "c",
        }

    def test_swap_with_missing_key(self):
        # 未入力（キーなし）側も入れ替わる: 値が移動し、元は未入力になる
        assert _rb_swap_indices({0: "a"}, 0, 1) == {1: "a"}
        assert _rb_swap_indices({1: "b"}, 0, 1) == {0: "b"}

    def test_swap_both_missing(self):
        assert _rb_swap_indices({2: "c"}, 0, 1) == {2: "c"}


class TestGsNormalizeOrder:
    def test_default_is_original_order(self):
        assert _gs_normalize_order(None, 3) == [0, 1, 2]
        assert _gs_normalize_order([], 3) == [0, 1, 2]

    def test_keeps_given_order(self):
        assert _gs_normalize_order([2, 0, 1], 3) == [2, 0, 1]

    def test_missing_indices_appended(self):
        assert _gs_normalize_order([2], 3) == [2, 0, 1]

    def test_drops_duplicates_and_out_of_range(self):
        assert _gs_normalize_order([1, 1, 9, -1, "x", None], 2) == [1, 0]

    def test_str_values(self):
        # localStorage 経由で文字列になっていても解釈する
        assert _gs_normalize_order(["1", "0"], 2) == [1, 0]

    def test_shrunk_costume_list(self):
        # 衣装数が減ったプリセットに保存済みの並びを当てても壊れない
        assert _gs_normalize_order([0, 1, 2], 2) == [0, 1]


class TestGsCostumeRows:
    COSTUMES = [
        {"costume_name": "通常", "bond_bonuses": [1, 0, 0, 0, 0, 0, 0]},
        {"costume_name": "水着", "bond_bonuses": [2, 0, 0, 0, 0, 0, 0]},
    ]

    @staticmethod
    def _components(rows):
        """行（入れ子あり）から id 付きコンポーネントを集める。"""
        found = {}

        def walk(node):
            if isinstance(node, (list, tuple)):
                for c in node:
                    walk(c)
                return
            cid = getattr(node, "id", None)
            if isinstance(cid, dict):
                found[(cid["type"], cid["index"])] = node
            walk(getattr(node, "children", None) or [])

        walk(rows)
        return found

    def test_row_count(self):
        assert len(_gs_costume_rows(self.COSTUMES)) == 2

    def test_move_buttons_disabled_at_ends(self):
        comps = self._components(_gs_costume_rows(self.COSTUMES))
        assert comps[("gs-move-up", 0)].disabled is True
        assert comps[("gs-move-down", 0)].disabled is False
        assert comps[("gs-move-up", 1)].disabled is False
        assert comps[("gs-move-down", 1)].disabled is True

    def test_order_changes_display_not_indices(self):
        rows = _gs_costume_rows(self.COSTUMES, order=[1, 0])
        # 表示順は order どおり
        assert rows[0].children[3].children == "水着"
        assert rows[1].children[3].children == "通常"
        # 入力の index は衣装 index のまま。端のボタンだけが無効になる
        comps = self._components(rows)
        assert comps[("gs-move-up", 1)].disabled is True
        assert comps[("gs-move-down", 0)].disabled is True

    def test_value_carryover_follows_costume_index(self):
        rows = _gs_costume_rows(
            self.COSTUMES,
            rank_by_index={1: 33},
            remain_by_index={"1": 100},
            order=[1, 0],
        )
        comps = self._components(rows)
        assert comps[("gs-bond-rank", 1)].value == 33
        assert comps[("gs-bond-remain", 1)].value == 100
        assert comps[("gs-bond-rank", 0)].value == 20


class TestGsFurnitureCell:
    def test_empty(self):
        assert _gs_furniture_cell([]) == "－"

    def test_partners_listed(self):
        items = [
            {"name": "格闘ゲーム機", "partners": ["アリス"]},
            {"name": "レースゲーム機", "partners": ["トキ", "アリス（メイド）"]},
            {"name": "植物棚", "partners": []},
        ]
        divs = _gs_furniture_cell(items)
        assert [d.children[0].children for d in divs] == [
            "格闘ゲーム機",
            "レースゲーム機",
            "植物棚",
        ]
        assert divs[1].children[1].children == "（共通: トキ、アリス（メイド））"
        assert len(divs[2].children) == 1  # 共通キャラなしは注記を出さない
