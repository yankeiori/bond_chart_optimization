"""アイコンの URL のバージョン (?v=) と、それに合わせたキャッシュのテスト。

アイコンの URL には内容のハッシュを付け（app/backend/icons.py）、v 付きの URL は
1 年間 immutable でキャッシュさせる（main.py の _cache_icons）。
"""

import hashlib
import re
from pathlib import Path
from urllib.parse import quote

import pytest

import app.backend.admin as admin
import app.frontend.callbacks as callbacks
import main  # noqa: F401 - after_request の登録
from app import app
from app.backend.icons import (
    ICON_EXTS,
    ICON_VERSIONS,
    file_versions,
    icon_src,
    version_for_path,
)
from app.backend.user_presets import gift_image_src

_ROOT = Path(__file__).resolve().parents[1]
_ASSETS = _ROOT / "assets"
_FOLDERS = ("student", "gift", "reaction")


@pytest.fixture
def client():
    return app.server.test_client()


def _first_name(folder: str) -> str:
    return sorted(ICON_VERSIONS[folder])[0]


def _sha1_8(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:8]


@pytest.mark.parametrize("folder", _FOLDERS)
def test_every_icon_has_content_version(folder):
    files = sorted((_ASSETS / folder).glob("*" + ICON_EXTS[folder]))
    assert files
    assert ICON_VERSIONS[folder] == {p.stem: _sha1_8(p) for p in files}


def test_version_changes_when_bytes_change(tmp_path):
    icon = tmp_path / "アイコン.webp"
    icon.write_bytes(b"first")
    (tmp_path / "other.png").write_bytes(b"ignored")  # 拡張子が違うものは数えない
    before = file_versions(tmp_path, ".webp")
    assert list(before) == ["アイコン"]
    assert re.fullmatch(r"[0-9a-f]{8}", before["アイコン"])

    icon.write_bytes(b"second")
    assert file_versions(tmp_path, ".webp")["アイコン"] != before["アイコン"]

    icon.write_bytes(b"first")  # 同じ内容なら同じバージョン
    assert file_versions(tmp_path, ".webp") == before


@pytest.mark.parametrize("folder", _FOLDERS)
def test_icon_src_carries_version(folder):
    name = _first_name(folder)
    path = _ASSETS / folder / f"{name}{ICON_EXTS[folder]}"
    assert icon_src(folder, name) == (
        f"/assets/{folder}/{quote(name)}{ICON_EXTS[folder]}?v={_sha1_8(path)}"
    )


def test_missing_icon_has_no_version():
    assert icon_src("gift", "存在しない贈り物") == (
        "/assets/gift/" + quote("存在しない贈り物") + ".webp"
    )


def test_gift_image_src_is_versioned():
    name = _first_name("gift")
    assert gift_image_src({"name": name}) == icon_src("gift", name)
    assert "?v=" in gift_image_src({"name": name})


def test_student_icon_src_is_versioned():
    name = _first_name("student")
    assert callbacks._student_icon_src(name) == icon_src("student", name)
    assert "?v=" in callbacks._student_icon_src(name)
    assert callbacks._student_icon_src("存在しない衣装") is None


def test_bond_rank_refs_carry_icon_src(monkeypatch):
    # bm-ocr-refs は [衣装ID, 表示名, 生徒画像の URL（無ければ None）]
    # （assets/bond_ocr.js と assets/bond_image.js がこの URL で画像を読む）
    name = _first_name("student")
    options = [{"value": 1, "label": name}, {"value": 2, "label": "存在しない衣装"}]
    monkeypatch.setattr(callbacks, "get_costume_options", lambda: options)
    _, refs = callbacks.bm_render(1, None)
    assert refs == [[1, name, icon_src("student", name)], [2, "存在しない衣装", None]]


def test_gift_ocr_panel_passes_versioned_icons(monkeypatch):
    name = _first_name("gift")
    gifts = [{"id": "g", "name": name, "gift_type": "normal"}]
    monkeypatch.setattr(admin, "load_gifts", lambda: gifts)
    html = admin._gift_ocr_panel()
    assert f'"src": "{icon_src("gift", name)}"' in html
    # 段の種類を決める顔アイコン（assets/admin_gift_ocr.js の _giftOcr_TIERS）
    for tier in ("ultra", "super", "favorite", "normal"):
        assert f'"{tier}": "{icon_src("reaction", tier)}"' in html


def test_icon_urls_are_built_by_the_helper():
    # アイコンの URL を直接組み立てると ?v= が付かず、長期キャッシュが効かない
    pattern = re.compile(r"/assets/(student|gift|reaction)/")
    sources = [*(_ROOT / "app").rglob("*.py"), *_ASSETS.glob("*.js")]
    offenders = [
        f"{p.relative_to(_ROOT)}:{i}"
        for p in sources
        if p.name != "icons.py"
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


@pytest.mark.parametrize("folder", _FOLDERS)
def test_versioned_icon_is_cached_immutably(client, folder):
    response = client.get(icon_src(folder, _first_name(folder)))
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/webp"
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize("folder", _FOLDERS)
@pytest.mark.parametrize("query", ["", "?v="])
def test_unversioned_icon_is_cached_for_a_week(client, folder, query):
    url = icon_src(folder, _first_name(folder)).split("?")[0] + query
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=604800"


@pytest.mark.parametrize("folder", _FOLDERS)
def test_mismatched_version_is_not_long_cached(client, folder):
    # 古いページの URL や、デプロイの切り替わりで古いサーバーに届いた新しい URL は、
    # 違う画像を 1 年残さないよう毎回確かめさせる
    url = icon_src(folder, _first_name(folder)).split("?")[0] + "?v=deadbeef"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-cache"


def test_version_for_path():
    name = _first_name("gift")
    assert version_for_path(f"/assets/gift/{name}.webp") == ICON_VERSIONS["gift"][name]
    assert version_for_path(f"/assets/gift/{name}.png") is None
    assert version_for_path("/assets/gift/存在しない.webp") is None
    assert version_for_path("/assets/style.css") is None
    assert version_for_path(f"/assets/gift/sub/{name}.webp") is None


def test_missing_versioned_icon_is_not_cached(client):
    response = client.get("/assets/gift/" + quote("存在しない贈り物") + ".webp?v=0")
    assert response.status_code == 404
    assert "immutable" not in response.headers.get("Cache-Control", "")


@pytest.mark.parametrize("folder", ["gift", "reaction"])
def test_icons_are_webp_only(folder):
    files = list((_ASSETS / folder).iterdir())
    assert files
    assert {p.suffix for p in files} == {".webp"}
