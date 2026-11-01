"""ログイン（サーバー保存）まわりのテスト。DB は差し替えて使う。"""

import pytest
from dash.exceptions import PreventUpdate

import app.backend.accounts as accounts
import app.frontend.callbacks as callbacks
import app.frontend.layout as layout
from app import app

from tests.test_layout import _find_by_id


def _store(root, store_id):
    found = _find_by_id(root, store_id)
    assert len(found) == 1
    return found[0]


class TestEnabledProviders:
    def test_requires_db_and_both_credentials(self, monkeypatch):
        monkeypatch.setattr(accounts, "_DATABASE_URL", "postgres://x")
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
        assert accounts.enabled_providers() == ["google"]
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
        assert accounts.enabled_providers() == []
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
        monkeypatch.setattr(accounts, "_DATABASE_URL", None)
        assert accounts.enabled_providers() == []


class TestBondRanksStores:
    def test_logged_out_uses_local_storage(self, monkeypatch):
        monkeypatch.setattr(layout, "current_user", lambda: None)
        stores = layout._bond_ranks_stores()
        assert _store(stores[0], "bond-ranks").storage_type == "local"
        assert _store(stores[1], "account-state").data == {"user_id": None}

    def test_logged_in_uses_server_data(self, monkeypatch):
        data = {"costumes": [{"costume_id": 1, "rank": 20, "remain": None}]}
        monkeypatch.setattr(
            layout, "current_user", lambda: {"id": 7, "provider": "google"}
        )
        monkeypatch.setattr(layout, "load_user_bond_ranks", lambda uid: data)
        stores = layout._bond_ranks_stores()
        store = _store(stores[0], "bond-ranks")
        assert store.storage_type == "memory"
        assert store.data == data
        assert stores[1].data == {"user_id": 7, "needs_import": False}

    def test_first_login_imports_local(self, monkeypatch):
        monkeypatch.setattr(
            layout, "current_user", lambda: {"id": 7, "provider": "google"}
        )
        monkeypatch.setattr(layout, "load_user_bond_ranks", lambda uid: None)
        stores = layout._bond_ranks_stores()
        assert stores[1].data == {"user_id": 7, "needs_import": True}

    def test_db_error_falls_back_to_local(self, monkeypatch):
        def boom(uid):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            layout, "current_user", lambda: {"id": 7, "provider": "google"}
        )
        monkeypatch.setattr(layout, "load_user_bond_ranks", boom)
        stores = layout._bond_ranks_stores()
        assert stores[0].storage_type == "local"
        assert stores[1].data == {"user_id": None}


class TestAccountSaveBondRanks:
    DATA = {"costumes": [{"costume_id": 1, "rank": 20, "remain": None}]}

    @pytest.fixture
    def saved(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            callbacks, "save_user_bond_ranks", lambda uid, d: calls.append((uid, d))
        )
        return calls

    def test_not_logged_in_page_does_nothing(self, saved):
        with pytest.raises(PreventUpdate):
            callbacks.account_save_bond_ranks(self.DATA, 0, {"user_id": None})
        assert saved == []

    def test_saves_for_logged_in_user(self, monkeypatch, saved):
        monkeypatch.setattr(callbacks, "session_user_id", lambda: 7)
        assert callbacks.account_save_bond_ranks(self.DATA, 0, {"user_id": 7}) == (
            "",
            True,
        )
        assert saved == [(7, self.DATA)]

    def test_session_changed_is_not_saved(self, monkeypatch, saved):
        monkeypatch.setattr(callbacks, "session_user_id", lambda: 8)
        msg, stop_retry = callbacks.account_save_bond_ranks(
            self.DATA, 0, {"user_id": 7}
        )
        assert "再読み込み" in msg
        assert stop_retry
        assert saved == []

    def test_save_failure_is_reported(self, monkeypatch):
        def boom(uid, d):
            raise RuntimeError("db down")

        monkeypatch.setattr(callbacks, "session_user_id", lambda: 7)
        monkeypatch.setattr(callbacks, "save_user_bond_ranks", boom)
        msg, stop_retry = callbacks.account_save_bond_ranks(
            self.DATA, 0, {"user_id": 7}
        )
        assert "再試行" in msg
        assert not stop_retry  # 少し待って再試行する


class TestSessionUserId:
    def test_reads_int_only(self):
        with app.server.test_request_context():
            from flask import session

            assert accounts.session_user_id() is None
            session["user_id"] = "7"
            assert accounts.session_user_id() is None
            session["user_id"] = 7
            assert accounts.session_user_id() == 7

    def test_outside_request(self):
        assert accounts.session_user_id() is None
        assert accounts.pop_auth_error() is None


class TestLogoutAndDelete:
    """ログアウト・アカウント削除は POST のみで、本サイトから送られたものだけ受け付ける。"""

    ORIGIN = {"Origin": "http://localhost"}

    @pytest.fixture
    def client(self, monkeypatch):
        import app.backend.auth as auth

        deleted = []
        monkeypatch.setattr(auth, "delete_user", deleted.append)
        client = app.server.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = 7
        client.deleted = deleted
        return client

    def _logged_in(self, client):
        with client.session_transaction() as sess:
            return "user_id" in sess

    def test_logout_requires_post(self, client):
        # GET は Dash のページ表示に回り、ログアウトはしない
        client.get("/auth/logout", headers=self.ORIGIN)
        assert self._logged_in(client)

    def test_logout_rejects_other_origin(self, client):
        for headers in (
            {},
            {"Origin": "https://evil.example"},
            {"Origin": "https://localhost.evil.example"},
            {"Origin": "null"},
        ):
            assert client.post("/auth/logout", headers=headers).status_code == 403
        assert self._logged_in(client)

    def test_logout(self, client):
        # プロキシの設定でスキームが食い違っても、同じホストなら受け付ける
        res = client.post("/auth/logout", headers={"Origin": "https://localhost"})
        assert res.status_code == 302
        assert not self._logged_in(client)

    def test_delete_rejects_other_origin(self, client):
        res = client.post("/auth/delete", headers={"Origin": "https://evil.example"})
        assert res.status_code == 403
        assert client.deleted == []
        assert self._logged_in(client)

    def test_delete(self, client):
        res = client.post("/auth/delete", headers=self.ORIGIN)
        assert res.status_code == 302
        assert client.deleted == [7]
        assert not self._logged_in(client)
