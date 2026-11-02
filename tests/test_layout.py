"""レイアウト / UIコンポーネントのテスト。

ブラウザ不要でDashコンポーネントの構造・属性を検証する。
"""

import re
from pathlib import Path

import pytest

from app.backend.presets import PRESETS
from app.backend.student import BOND_RANGES
from app.frontend.layout import (
    create_layout,
    create_required_exp_layout,
    create_root_layout,
    make_student_card,
    _make_bond_rank_input,
    _default_costume_name,
    NAV_GROUPS,
    EXTRA_PAGES,
    PAGES,
)


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _find_by_id(component, target_id, *, results=None):
    """コンポーネントツリーからIDが一致する要素を再帰的に探す。"""
    if results is None:
        results = []
    props = getattr(component, "__dict__", {}) or {}
    if not props:
        return results
    cid = props.get("id")
    matched = False
    if cid == target_id:
        matched = True
    elif isinstance(cid, dict) and isinstance(target_id, dict):
        if all(cid.get(k) == v for k, v in target_id.items()):
            matched = True
    if matched:
        results.append(component)
        return results  # ID一致したらその下は探索しない（重複防止）
    for child in _iter_children(component):
        _find_by_id(child, target_id, results=results)
    return results


def _find_by_class(component, class_name, *, results=None):
    """コンポーネントツリーからclassNameが一致する要素を再帰的に探す。"""
    if results is None:
        results = []
    props = getattr(component, "__dict__", {}) or {}
    if class_name in (props.get("className") or "").split():
        results.append(component)
    for child in _iter_children(component):
        _find_by_class(child, class_name, results=results)
    return results


def _iter_children(component):
    """コンポーネントの子要素をイテレートする。"""
    props = getattr(component, "__dict__", {}) or {}
    children = props.get("children")
    if children is None:
        return
    if isinstance(children, (list, tuple)):
        for c in children:
            if hasattr(c, "__dict__"):
                yield c
    elif hasattr(children, "__dict__"):
        yield children


# ---------------------------------------------------------------------------
# create_layout
# ---------------------------------------------------------------------------


class TestCreateLayout:
    """create_layout() が必要な要素を含むことを検証する。"""

    @pytest.fixture()
    def layout(self):
        return create_layout()

    def test_page_container_class(self, layout):
        assert layout.className == "page-container"

    def test_has_page_intro(self, layout):
        found = _find_by_class(layout, "page-intro")
        assert len(found) == 1
        assert len(_find_by_id(found[0], "open-manual-btn")) == 1

    def test_has_preset_section(self, layout):
        found = _find_by_class(layout, "preset-section")
        assert len(found) == 1

    def test_has_preset_dropdown(self, layout):
        found = _find_by_id(layout, "preset-dropdown")
        assert len(found) == 1

    def test_has_calc_button(self, layout):
        found = _find_by_id(layout, "calc-chart-btn")
        assert len(found) == 1

    def test_calc_button_wrapper_class(self, layout):
        found = _find_by_class(layout, "calc-btn-wrapper")
        assert len(found) == 1

    def test_has_manual_modal(self, layout):
        found = _find_by_id(layout, "manual-modal")
        assert len(found) == 1
        modal = found[0]
        assert modal.style.get("display") == "none"

    def test_has_add_student_btn(self, layout):
        found = _find_by_id(layout, "add-student-btn")
        assert len(found) == 1
        assert "add-student-btn" in found[0].className

    def test_has_bond_rank_section(self, layout):
        found = _find_by_class(layout, "bond-rank-section")
        assert len(found) == 1

    def test_has_chart_result_area(self, layout):
        found = _find_by_class(layout, "chart-result-area")
        assert len(found) == 1

    def test_has_stores(self, layout):
        for store_id in ("student-indices", "next-student-index", "solver-inputs"):
            found = _find_by_id(layout, store_id)
            assert len(found) == 1, f"Store '{store_id}' が見つからない"

    def test_student_cards_in_manual_edit(self, layout):
        # 絆ボーナスの入力（衣装カード）は折りたたみの中に置く
        manual = _find_by_class(layout, "manual-edit")
        assert len(manual) == 1
        assert len(_find_by_id(manual[0], "students-container")) == 1
        assert len(_find_by_id(manual[0], "add-student-btn")) == 1

    def test_default_student_card_count(self, layout):
        found = _find_by_id(layout, "students-container")
        assert len(found) == 1
        container = found[0]
        assert len(container.children) == 1


# ---------------------------------------------------------------------------
# create_required_exp_layout
# ---------------------------------------------------------------------------


class TestRequiredExpLayout:
    """create_required_exp_layout() が必要な要素を含むことを検証する。"""

    @pytest.fixture()
    def layout(self):
        return create_required_exp_layout()

    def test_page_container_class(self, layout):
        assert layout.className == "page-container"

    def test_registered_in_pages(self):
        assert "/required-exp" in PAGES
        label, builder = PAGES["/required-exp"]
        assert label == "必要絆経験値"
        assert builder is create_required_exp_layout

    @pytest.mark.parametrize(
        "component_id",
        [
            "rb-costume-dropdown",
            "rb-add-costume-btn",
            "rb-add-feedback",
            "rb-costume-container",
            "rb-gift-list",
            "rb-calc-btn",
            "rb-calc-result",
            "rb-costumes",
            "rb-autosave",
            "rb-autosave-ready",
            "rb-autosave-init",
        ],
    )
    def test_has_components(self, layout, component_id):
        found = _find_by_id(layout, component_id)
        assert len(found) == 1, f"'{component_id}' が見つからない"

    def test_costumes_store_default_empty(self, layout):
        store = _find_by_id(layout, "rb-costumes")[0]
        assert store.data == []


# ---------------------------------------------------------------------------
# 共通ヘッダー（タイトル・ログイン・カテゴリ付きタブ）
# ---------------------------------------------------------------------------


class TestSiteHeader:
    """ルートレイアウトの共通ヘッダーとタブを検証する。"""

    @pytest.fixture()
    def root(self):
        return create_root_layout()

    def test_has_site_header(self, root):
        assert len(_find_by_class(root, "site-header")) == 1
        assert len(_find_by_class(root, "site-title")) == 1

    def test_has_page_content(self, root):
        assert len(_find_by_id(root, "page-content")) == 1

    def test_tabs_cover_all_pages(self, root):
        assert len(_find_by_class(root, "page-tabs")) == 1
        tabs = _find_by_class(root, "page-tab")
        assert {t.href for t in tabs} == set(PAGES.keys())

    def test_tabs_grouped_by_category(self, root):
        groups = _find_by_class(root, "tab-group")
        assert len(groups) == len(NAV_GROUPS)
        paths = [p for _, group in NAV_GROUPS for p in group]
        assert sorted(paths) == sorted(PAGES.keys())

    def test_login_in_header(self, monkeypatch):
        monkeypatch.setattr("app.frontend.layout.enabled_providers", lambda: ["google"])
        header = _find_by_class(create_root_layout(), "site-header")[0]
        assert len(_find_by_class(header, "header-account")) == 1

    @pytest.mark.parametrize("path", list(PAGES.keys()))
    def test_pages_have_no_own_tabs(self, path):
        # タブは共通ヘッダーに1つだけ。各ページ側には持たせない。
        _, builder = PAGES[path]
        assert _find_by_class(builder(), "page-tabs") == []

    @pytest.mark.parametrize("path", list({**PAGES, **EXTRA_PAGES}.keys()))
    def test_pages_do_not_mention_schaledb(self, path):
        # データの取得元（SchaleDB）はページに出さない
        _, builder = {**PAGES, **EXTRA_PAGES}[path]
        assert "schaledb" not in str(builder()).lower()


# ---------------------------------------------------------------------------
# make_student_card
# ---------------------------------------------------------------------------


class TestMakeStudentCard:
    """make_student_card() の出力を検証する。"""

    def test_default_values(self):
        card = make_student_card(0)
        assert card.id == {"type": "student-card", "index": 0}
        assert card.className == "student-card"

    def test_custom_costume_name(self):
        card = make_student_card(2, costume_name="水着")
        inputs = _find_by_id(card, {"type": "costume", "index": 2})
        assert len(inputs) == 1
        assert inputs[0].value == "水着"

    def test_default_costume_name(self):
        card = make_student_card(3)
        inputs = _find_by_id(card, {"type": "costume", "index": 3})
        assert inputs[0].value == "衣装4"

    def test_bond_fields_count(self):
        card = make_student_card(0)
        bond_fields = _find_by_class(card, "bond-fields")
        assert len(bond_fields) == 1
        assert len(bond_fields[0].children) == len(BOND_RANGES)

    def test_bond_default_zero(self):
        card = make_student_card(0)
        for i in range(len(BOND_RANGES)):
            inputs = _find_by_id(card, {"type": "bond", "range_idx": i, "index": 0})
            assert len(inputs) == 1
            assert inputs[0].value == 0

    def test_bond_custom_values(self):
        bonuses = [1, 2, 3, 4, 5, 6, 7]
        card = make_student_card(1, bond_bonuses=bonuses)
        for i, expected in enumerate(bonuses):
            inputs = _find_by_id(card, {"type": "bond", "range_idx": i, "index": 1})
            assert inputs[0].value == expected

    def test_has_remove_button(self):
        card = make_student_card(0)
        btns = _find_by_class(card, "remove-student-btn")
        assert len(btns) == 1

    def test_has_student_card_header(self):
        card = make_student_card(0)
        headers = _find_by_class(card, "student-card-header")
        assert len(headers) == 1


# ---------------------------------------------------------------------------
# _make_bond_rank_input
# ---------------------------------------------------------------------------


class TestMakeBondRankInput:
    """_make_bond_rank_input() の出力を検証する。"""

    def test_default_value(self):
        inp = _make_bond_rank_input(0)
        rank_inputs = _find_by_id(inp, {"type": "bond-rank", "index": 0})
        assert len(rank_inputs) == 1
        assert rank_inputs[0].value == 20

    def test_custom_value(self):
        inp = _make_bond_rank_input(1, value=35)
        rank_inputs = _find_by_id(inp, {"type": "bond-rank", "index": 1})
        assert rank_inputs[0].value == 35

    def test_has_inc_dec_buttons(self):
        inp = _make_bond_rank_input(0)
        dec_btns = _find_by_id(inp, {"type": "bond-rank-dec", "index": 0})
        inc_btns = _find_by_id(inp, {"type": "bond-rank-inc", "index": 0})
        assert len(dec_btns) == 1
        assert len(inc_btns) == 1

    def test_label_default(self):
        inp = _make_bond_rank_input(2)
        labels = _find_by_id(inp, {"type": "bond-rank-label", "index": 2})
        assert len(labels) == 1
        assert labels[0].children == "衣装3"

    def test_label_custom(self):
        inp = _make_bond_rank_input(0, costume_name="通常")
        labels = _find_by_id(inp, {"type": "bond-rank-label", "index": 0})
        assert labels[0].children == "通常"

    def test_bond_views(self):
        inp = _make_bond_rank_input(1, bond_bonuses=[1, 2, 3, 4, 5, 6, 7])
        views = [
            _find_by_id(inp, {"type": "bond-view", "range_idx": i, "index": 1})[0]
            for i in range(len(BOND_RANGES))
        ]
        assert [v.children for v in views] == ["1", "2", "3", "4", "5", "6", "7"]

    def test_bond_views_default_zero(self):
        inp = _make_bond_rank_input(0)
        view = _find_by_id(inp, {"type": "bond-view", "range_idx": 0, "index": 0})
        assert view[0].children == "0"


# ---------------------------------------------------------------------------
# _default_costume_name
# ---------------------------------------------------------------------------


class TestDefaultCostumeName:
    @pytest.mark.parametrize(
        "index, expected", [(0, "衣装1"), (1, "衣装2"), (9, "衣装10")]
    )
    def test_names(self, index, expected):
        assert _default_costume_name(index) == expected


# ---------------------------------------------------------------------------
# プリセット連携
# ---------------------------------------------------------------------------


class TestPresetsIntegration:
    """全プリセットで make_student_card が正しく生成されることを検証する。"""

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_preset_cards(self, name):
        students = PRESETS[name]
        for i, s in enumerate(students):
            card = make_student_card(
                i,
                costume_name=s["costume_name"],
                bond_bonuses=s["bond_bonuses"],
            )
            # 衣装名が正しい
            inputs = _find_by_id(card, {"type": "costume", "index": i})
            assert inputs[0].value == s["costume_name"]
            # 絆ボーナスが正しい
            for ri, val in enumerate(s["bond_bonuses"]):
                bond = _find_by_id(card, {"type": "bond", "range_idx": ri, "index": i})
                assert bond[0].value == val

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_preset_bond_rank_inputs(self, name):
        students = PRESETS[name]
        for i, s in enumerate(students):
            inp = _make_bond_rank_input(i, costume_name=s["costume_name"])
            labels = _find_by_id(inp, {"type": "bond-rank-label", "index": i})
            assert labels[0].children == s["costume_name"]


# ---------------------------------------------------------------------------
# HTML の雛形（index_string）
# ---------------------------------------------------------------------------


class TestIndexHtml:
    """JavaScript を実行しないクローラーや読み上げソフト向けの HTML を検証する。"""

    @pytest.fixture(scope="class")
    def html(self):
        from app import app

        with app.server.test_request_context("/chart-opt"):
            return app.index()

    def test_lang_is_japanese(self, html):
        assert '<html lang="ja">' in html

    def test_has_description(self, html):
        assert '<meta name="description"' in html

    @pytest.mark.parametrize(
        "prop", ["og:type", "og:url", "og:site_name", "og:title", "og:description"]
    )
    def test_has_ogp(self, html, prop):
        assert f'property="{prop}"' in html

    def test_og_image_exists(self, html):
        from app import SITE_URL

        m = re.search(r'property="og:image" content="([^"]+)"', html)
        assert m and m.group(1).startswith(SITE_URL)
        assert (
            Path(__file__).parent.parent
            / "assets"
            / m.group(1).removeprefix(SITE_URL + "assets/")
        ).is_file()

    def test_has_noscript_notice(self, html):
        assert "<noscript>" in html

    def test_does_not_mention_schaledb(self, html):
        assert "schaledb" not in html.lower()
