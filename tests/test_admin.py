"""管理画面のフォーム解析・認証のテスト。"""

import pytest

import app.backend.admin as admin
from app import app
from app.backend.accounts import is_admin
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
        assert res.headers["Location"].endswith("/admin/presets")

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
