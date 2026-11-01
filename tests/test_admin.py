"""管理画面のフォーム解析のテスト。"""

from app.backend.admin import _NUM_RANGES, _parse_costumes


def _row(form, idx, name, cid=None, b0="1"):
    form[f"p_cname_{idx}"] = name
    for j in range(_NUM_RANGES):
        form[f"p_b{j}_{idx}"] = b0 if j == 0 else "0"
    if cid is not None:
        form[f"p_cid_{idx}"] = str(cid)


class TestParseCostumes:
    def test_gap_in_indices(self):
        # 途中の行 (1) を削除して番号が飛んでも、後ろの行を読み落とさない
        form = {}
        _row(form, 0, "通常", cid=10)
        _row(form, 2, "水着", cid=11)
        _row(form, 10, "新衣装", b0="5")
        out = _parse_costumes(form, "p")
        assert [c["costume_name"] for c in out] == ["通常", "水着", "新衣装"]
        assert [c["costume_id"] for c in out] == [10, 11, None]
        assert out[2]["bond_bonuses"][0] == 5

    def test_blank_name_skipped_and_bad_values(self):
        form = {}
        _row(form, 0, "  ")
        _row(form, 1, "通常", b0="x")
        form["p_cid_1"] = "abc"
        out = _parse_costumes(form, "p")
        assert out == [
            {
                "costume_name": "通常",
                "bond_bonuses": [0] * _NUM_RANGES,
                "costume_id": None,
            }
        ]
