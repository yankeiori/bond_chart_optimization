"""生徒・贈り物・リアクションのアイコン（assets/student, gift, reaction）の URL。

URL には ?v=<ファイル内容の SHA-1 の先頭 8 桁> を付ける。main.py の _cache_icons は
v 付きの URL を 1 年間 immutable でキャッシュさせるので、再訪問時は確認の通信も
起きない。画像を差し替えると v が変わって別の URL になるため、古い画像は出ない。
アイコンはデプロイでしか変わらないので、バージョンは起動時に 1 回だけ計算する。
"""

import hashlib
from pathlib import Path
from urllib.parse import quote

_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"

# フォルダ -> 画像の拡張子
ICON_EXTS = {"student": ".webp", "gift": ".webp", "reaction": ".webp"}


def file_versions(folder: Path, ext: str) -> dict[str, str]:
    """folder の *ext の {拡張子を除いたファイル名: 内容の SHA-1 の先頭 8 桁}。"""
    return {
        p.stem: hashlib.sha1(p.read_bytes()).hexdigest()[:8]
        for p in sorted(folder.glob(f"*{ext}"))
    }


# フォルダ -> {名前: バージョン}
ICON_VERSIONS = {
    folder: file_versions(_ASSETS_DIR / folder, ext)
    for folder, ext in ICON_EXTS.items()
}


def has_icon(folder: str, name: str) -> bool:
    """assets/<folder> に name の画像があるか。"""
    return name in ICON_VERSIONS[folder]


def icon_src(folder: str, name: str) -> str:
    """assets/<folder> の name の画像の URL（日本語名はパーセントエンコードする）。

    画像があれば ?v=<内容のハッシュ> を付ける。無い画像は v なしの URL（404 になる）。
    """
    url = f"/assets/{folder}/{quote(name)}{ICON_EXTS[folder]}"
    version = ICON_VERSIONS[folder].get(name)
    return f"{url}?v={version}" if version else url
