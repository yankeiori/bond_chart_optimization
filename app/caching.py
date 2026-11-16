"""配信物の URL と検証子（ETag など）を、デプロイで変わらないようにする（Render の帯域対策）。

Render はデプロイのたびにリポジトリを取り直してパッケージを入れ直すので、
ファイルの更新時刻（mtime）がデプロイ時刻になる。Dash は mtime から
JS の URL（パッケージの指紋や /assets の ?m=）を作り、Flask は mtime から
ETag と Last-Modified を作る。そのままでは、デプロイのたびに再訪者が
JS・CSS・画像をすべて取り直してしまう。ここでは、中身やパッケージの版が
変わったときだけ URL と検証子が変わるようにする。
"""

import os
import zlib
from pathlib import Path

import dash.dash as _dash_module
from dash.fingerprint import build_fingerprint as _build_fingerprint

# 中身から決める mtime の範囲（2000-01-01 からの約 20 年）。
_MTIME_BASE = 946684800
_MTIME_SPAN = 631152000


def content_mtime(data: bytes) -> int:
    """ファイルの中身から決まる mtime（中身が同じなら常に同じ値）。"""
    return _MTIME_BASE + zlib.crc32(data) % _MTIME_SPAN


def stabilize_mtimes(folder: Path) -> int:
    """folder 以下のファイルの mtime を中身から決まる値にそろえる。

    Dash の ?m= と Flask の ETag・Last-Modified が、中身が変わったときだけ
    変わるようになる。書き換えられないファイルはそのままにする（配信には
    影響しない）。Returns mtime を変えたファイルの数。
    """
    changed = 0
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        try:
            mtime = content_mtime(path.read_bytes())
            if int(path.stat().st_mtime) != mtime:
                os.utime(path, (mtime, mtime))
                changed += 1
        except OSError:
            continue
    return changed


def version_only_fingerprint(path: str, version: str, _modified) -> str:
    """Dash の JS の URL の指紋（.v<版>m<mtime>.js）から mtime を外し、版だけで決める。"""
    return _build_fingerprint(path, version, 0)


def use_version_only_fingerprint() -> None:
    """Dash が JS の URL を作るときに version_only_fingerprint を使うようにする。

    dash.dash は build_fingerprint を呼ぶたびにモジュールの名前を引くので、
    差し替えれば以後の URL がすべて版だけで決まる（Dash を上げれば URL も変わる）。
    """
    _dash_module.build_fingerprint = version_only_fingerprint
