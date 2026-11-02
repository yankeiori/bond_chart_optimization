"""管理画面のフォーム解析・認証のテスト。"""

from datetime import datetime, timedelta, timezone

import pytest

import app.backend.admin as admin
from app import app
from app.backend.accounts import is_admin
from app.backend.admin import _NUM_RANGES, _parse_costumes
from app.backend.usage_stats import JST, compute_usage_stats


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


# ----------------------------------------------------------------------
# 管理者の認証（Google アカウント）
# ----------------------------------------------------------------------

_ADMIN = {"id": 1, "provider": "google", "subject": "111"}
_OTHER = {"id": 2, "provider": "google", "subject": "222"}


class TestIsAdmin:
    def test_matches_subject(self, monkeypatch):
        monkeypatch.setenv("ADMIN_GOOGLE_SUB", "111")
        assert is_admin(_ADMIN)
        assert not is_admin(_OTHER)
        assert not is_admin(None)
        assert not is_admin({**_ADMIN, "provider": "other"})

    def test_unset_means_no_admin(self, monkeypatch):
        monkeypatch.delenv("ADMIN_GOOGLE_SUB", raising=False)
        assert not is_admin(_ADMIN)
        assert not is_admin({**_ADMIN, "subject": ""})


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_GOOGLE_SUB", "111")
    monkeypatch.setattr(admin, "enabled_providers", lambda: ["google"])
    monkeypatch.setattr(admin, "_render_admin_page", lambda *a: "admin page")
    return app.server.test_client()


def _login_as(monkeypatch, user):
    monkeypatch.setattr(admin, "current_user", lambda: user)


class TestAdminAccess:
    def test_logged_out_redirects_to_login(self, client, monkeypatch):
        _login_as(monkeypatch, None)
        res = client.get("/admin/presets")
        assert res.status_code == 302
        assert res.headers["Location"].endswith("/admin/login")
        page = client.get("/admin/login").get_data(as_text=True)
        assert "/auth/login/google?next=admin" in page

    def test_other_account_is_rejected(self, client, monkeypatch):
        _login_as(monkeypatch, _OTHER)
        assert client.get("/admin/presets").status_code == 302
        page = client.get("/admin/login").get_data(as_text=True)
        assert "管理権限がありません" in page
        assert "222" in page  # ADMIN_GOOGLE_SUB に設定する値を表示する

    def test_admin_can_open(self, client, monkeypatch):
        _login_as(monkeypatch, _ADMIN)
        assert client.get("/admin/presets").get_data(as_text=True) == "admin page"
        res = client.get("/admin/login")
        assert res.headers["Location"].endswith("/admin")

    def test_unset_admin_sub_locks_everyone_out(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_GOOGLE_SUB")
        _login_as(monkeypatch, _ADMIN)
        assert client.get("/admin/presets").status_code == 302
        page = client.get("/admin/login").get_data(as_text=True)
        assert "ADMIN_GOOGLE_SUB" in page
        assert "111" in page  # 未設定でも自分の値を確かめられる
        _login_as(monkeypatch, None)
        page = client.get("/admin/login").get_data(as_text=True)
        assert "/auth/login/google?next=admin" in page

    def test_post_requires_same_origin(self, client, monkeypatch):
        _login_as(monkeypatch, _ADMIN)
        deleted = []
        monkeypatch.setattr(admin, "admin_delete_preset", lambda *a: deleted.append(a))
        form = {"student": "アル", "status": "攻撃"}
        url = "/admin/presets/preset_delete"
        assert client.post(url, data=form).status_code == 403
        res = client.post(url, data=form, headers={"Origin": "https://evil.example"})
        assert res.status_code == 403
        assert deleted == []
        res = client.post(url, data=form, headers={"Origin": "http://localhost"})
        assert res.status_code == 302
        assert deleted == [("アル", "攻撃")]


# ----------------------------------------------------------------------
# ダッシュボード（絆ランク管理の利用状況）
# ----------------------------------------------------------------------

_NOW = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
_COSTUMES = [
    {"costume_id": 1, "student_name": "アル", "costume_name": "通常"},
    {"costume_id": 2, "student_name": "アル", "costume_name": "ドレス"},
    {"costume_id": 3, "student_name": "ムツキ", "costume_name": "通常"},
]


def _user(uid, created, entries, admin_flag=False, updated=None):
    return {
        "id": uid,
        "is_admin": admin_flag,
        "created_at": created,
        "last_login_at": created,
        "updated_at": updated
        if updated is not None
        else (created if entries else None),
        "entries": [{"costume_id": c, "rank": r} for c, r in entries],
    }


def _users():
    day = timedelta(days=1)
    return [
        _user(1, _NOW - 20 * day, [(1, 50), (2, 100)], admin_flag=True),
        _user(2, _NOW - 20 * day, [(1, 20), (3, 9), (99, 30)]),  # 99 は削除済みの衣装
        _user(3, _NOW - day, [(1, 40)]),
        _user(4, _NOW, []),
    ]


class TestUsageStats:
    def test_excludes_admin_by_default(self):
        stats = compute_usage_stats(_users(), _COSTUMES, _NOW)
        s = stats["summary"]
        assert s["users"] == 3
        assert s["savers"] == 2
        assert s["new_recent"] == 2
        assert s["saved_recent"] == 1
        assert s["entries"] == 3  # 削除済みの衣装は数えない
        assert s["avg_count"] == 1.5
        assert stats["admin_excluded"] == 1
        assert [u["id"] for u in stats["users"]] == [2, 3, 4]

    def test_include_admin(self):
        stats = compute_usage_stats(_users(), _COSTUMES, _NOW, include_admin=True)
        assert stats["summary"]["users"] == 4
        assert stats["admin_excluded"] == 0
        hist = {b["label"]: b["count"] for b in stats["rank_hist"]}
        assert hist["1〜9"] == 1
        assert hist["50〜59"] == 1
        assert hist["100"] == 1

    def test_by_costume(self):
        stats = compute_usage_stats(_users(), _COSTUMES, _NOW)
        by_id = {c["costume_id"]: c for c in stats["by_costume"]}
        assert by_id[1]["count"] == 2
        assert by_id[1]["avg"] == 30
        assert by_id[1]["max"] == 40
        assert by_id[2]["count"] == 0  # 管理者だけが登録した衣装
        assert by_id[2]["avg"] is None

    def test_daily_new_in_jst(self):
        stats = compute_usage_stats(_users(), _COSTUMES, _NOW)
        daily = stats["daily_new"]
        # 最初の利用者の日（日本時間）から今日まで、抜けなく並ぶ
        assert daily[0]["date"] == (_NOW - timedelta(days=20)).astimezone(JST).date()
        assert daily[-1]["date"] == _NOW.astimezone(JST).date()
        assert len(daily) == 21
        assert sum(d["count"] for d in daily) == 3

    def test_empty(self):
        stats = compute_usage_stats([], _COSTUMES, _NOW)
        assert stats["summary"]["avg_count"] is None
        assert stats["daily_new"] == []


class TestDashboard:
    @pytest.fixture
    def dash_client(self, client, monkeypatch):
        _login_as(monkeypatch, _ADMIN)
        monkeypatch.setattr(admin, "load_all_user_bond_ranks", _users)
        monkeypatch.setattr(admin, "admin_load_costumes", lambda: _COSTUMES)
        return client

    def test_renders(self, dash_client):
        page = dash_client.get("/admin").get_data(as_text=True)
        assert "ダッシュボード" in page
        assert "ムツキ" in page
        assert "管理者のアカウント 1 件を除いています" in page
        assert 'class="active">ダッシュボード' in page
        assert "schaledb" not in page.lower()

    def test_include_admin(self, dash_client):
        page = dash_client.get("/admin?include_admin=1").get_data(as_text=True)
        assert "除いています" not in page
        assert '<span class="tag">管理者</span>' in page

    def test_requires_admin(self, client, monkeypatch):
        _login_as(monkeypatch, _OTHER)
        assert client.get("/admin").status_code == 302

    def test_db_error_shows_message(self, dash_client, monkeypatch):
        def fail():
            raise RuntimeError("boom")

        monkeypatch.setattr(admin, "load_all_user_bond_ranks", fail)
        page = dash_client.get("/admin").get_data(as_text=True)
        assert "利用状況の取得に失敗しました" in page


# ----------------------------------------------------------------------
# 衣装を追加（まとめて登録）
# ----------------------------------------------------------------------

_GIFTS = [
    {"id": "gift-a", "name": "贈り物A", "gift_type": "normal"},
    {"id": "gift-b", "name": "贈り物B", "gift_type": "high"},
]


def _add_form(**extra):
    form = {
        "student_name": " アル ",
        "costume_name": "ドレス",
        "status_0": "攻撃",
        "status_1": "HP",
        "s0_b0": "3",
        "s1_b6": "40",
        "g_gift-a": "superFavorite",
        "g_gift-b": "",
        "furn_name_0": "ソファ",
        "furn_id_0": "",
        "furn_name_1": "",
        "furn_id_1": "",
    }
    form.update(extra)
    return form


class TestParseAddForm:
    @pytest.fixture(autouse=True)
    def gifts(self, monkeypatch):
        monkeypatch.setattr(admin, "load_gifts", lambda: _GIFTS)

    def test_parses_everything(self):
        data = admin._parse_add_form(_add_form(furn_name_1="棚", furn_id_1="12"))
        assert data["student_name"] == "アル"
        assert data["bonuses_by_status"]["攻撃"] == [3] + [0] * (_NUM_RANGES - 1)
        assert data["bonuses_by_status"]["HP"][6] == 40
        assert data["present"] == {"gift-a": "superFavorite"}
        assert data["furniture"] == [("ソファ", None), ("棚", 12)]
        assert data["priority"] is None

    @pytest.mark.parametrize(
        "extra, message",
        [
            ({"costume_name": ""}, "生徒名と衣装名"),
            ({"status_1": "攻撃"}, "重複"),
            ({"s0_b1": "x"}, "整数"),
            ({"s0_b1": "-1"}, "0以上"),
            ({"priority": "abc"}, "表示優先度"),
            ({"furn_id_1": "5"}, "家具名も"),
            ({"furn_id_0": "0"}, "正の整数"),
        ],
    )
    def test_errors(self, extra, message):
        with pytest.raises(admin._FormError, match=message):
            admin._parse_add_form(_add_form(**extra))


class TestAddPage:
    @pytest.fixture
    def add_client(self, client, monkeypatch):
        _login_as(monkeypatch, _ADMIN)
        monkeypatch.setattr(admin, "load_gifts", lambda: _GIFTS)
        monkeypatch.setattr(admin, "admin_load_costumes", lambda: _COSTUMES)
        monkeypatch.setattr(admin, "admin_load_presets", lambda: [])
        monkeypatch.setattr(admin, "admin_load_priorities", lambda: [])
        monkeypatch.setattr(admin, "admin_load_furniture_catalog", lambda: [])
        return client

    def test_renders(self, add_client):
        page = add_client.get("/admin/add").get_data(as_text=True)
        assert 'class="active">衣装を追加' in page
        assert 'name="g_gift-a"' in page
        assert "schaledb" not in page.lower()

    def test_registers_and_redirects(self, add_client, monkeypatch):
        calls = []
        monkeypatch.setattr(
            admin, "admin_register_costume", lambda **kw: calls.append(kw) or 42
        )
        res = add_client.post(
            "/admin/add", data=_add_form(), headers={"Origin": "http://localhost"}
        )
        assert res.status_code == 302
        assert "costume_id=42" in res.headers["Location"]
        assert calls[0]["costume_name"] == "ドレス"
        assert calls[0]["furniture"] == [("ソファ", None)]

    def test_error_keeps_input(self, add_client, monkeypatch):
        def exists(**kw):
            raise admin.CostumeExistsError("「アル／ドレス」は既に登録されています")

        monkeypatch.setattr(admin, "admin_register_costume", exists)
        res = add_client.post(
            "/admin/add",
            data=_add_form(furn_name_0="特製ソファ"),
            headers={"Origin": "http://localhost"},
        )
        page = res.get_data(as_text=True)
        assert res.status_code == 200
        assert "既に登録されています" in page
        assert 'value="特製ソファ"' in page  # 入力した値は消さない
        assert 'value="superFavorite" checked' in page

    def test_post_requires_same_origin(self, add_client, monkeypatch):
        monkeypatch.setattr(admin, "admin_register_costume", lambda **kw: 1)
        assert add_client.post("/admin/add", data=_add_form()).status_code == 403


# ----------------------------------------------------------------------
# 好みのスクリーンショット読み取り（assets/admin_gift_ocr.js）
# ----------------------------------------------------------------------

_OCR_GIFTS = _GIFTS + [
    {"id": "beautiful-bouquet", "name": "美しい花束", "gift_type": "high-all"},
    {"id": "gift-select-box", "name": "贈り物選択ボックス", "gift_type": "normal"},
]


class TestGiftOcr:
    @pytest.fixture
    def ocr_client(self, client, monkeypatch):
        _login_as(monkeypatch, _ADMIN)
        monkeypatch.setattr(admin, "load_gifts", lambda: _OCR_GIFTS)
        monkeypatch.setattr(admin, "admin_load_costumes", lambda: _COSTUMES)
        monkeypatch.setattr(admin, "admin_load_presets", lambda: [])
        monkeypatch.setattr(admin, "admin_load_priorities", lambda: [])
        monkeypatch.setattr(admin, "admin_load_furniture_catalog", lambda: [])
        return client

    def test_panel_gifts(self, monkeypatch):
        monkeypatch.setattr(admin, "load_gifts", lambda: _OCR_GIFTS)
        html = admin._gift_ocr_panel()
        assert '<script src="/assets/admin_gift_ocr.js"></script>' in html
        # 照合には好みのラジオが無い花束も要る。選択ボックスはパネルに出ない
        assert '"id": "beautiful-bouquet"' in html
        assert '"type": "high-all"' in html
        assert "gift-select-box" not in html
        assert "/assets/gift/%E8%B4%88%E3%82%8A%E7%89%A9A.png" in html

    def test_add_page_has_reader(self, ocr_client):
        page = ocr_client.get("/admin/add").get_data(as_text=True)
        assert 'id="gift-ocr-file"' in page
        # 好みのラジオは花束に作らない（読み取りは贈り物のラジオにだけ入れる）
        assert 'name="g_gift-a"' in page
        assert 'name="g_beautiful-bouquet"' not in page

    def test_presents_page_has_reader(self, ocr_client, monkeypatch):
        monkeypatch.setattr(
            admin,
            "admin_load_costumes",
            lambda: [{**c, "present_count": 0} for c in _COSTUMES],
        )
        monkeypatch.setattr(
            admin,
            "admin_get_costume",
            lambda cid: {"student_name": "アル", "costume_name": "ドレス"},
        )
        monkeypatch.setattr(admin, "admin_load_present", lambda cid: {})
        monkeypatch.setattr(admin, "admin_load_costume_furniture", lambda cid: [])
        page = ocr_client.get("/admin/presents?costume_id=2").get_data(as_text=True)
        assert 'id="gift-ocr-file"' in page
        assert "schaledb" not in page.lower()

    def test_not_loaded_on_public_pages(self, client):
        # 管理画面用のスクリプトは公開ページに読み込まないが、配信はする
        with app.server.test_request_context("/chart-opt"):
            app._walk_assets_directory()
            html = app.index()
        assert "bond_ocr.js" in html
        assert "admin_gift_ocr" not in html
        res = client.get("/assets/admin_gift_ocr.js")
        assert res.status_code == 200
        res.close()
