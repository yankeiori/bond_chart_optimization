"""絆ランク管理（ブラウザの localStorage に保存する）のデータ操作。

保存データは {"costumes": [{"costume_id", "rank"}, ...]} の形。
rank は現在の絆ランク (1〜100)。絆ボーナスは 50 までなので、計算では
51 以上を 50 として扱う（各計算ページ側で丸める）。絆ランクを
設定した衣装だけを保存し、それ以外は「未設定」とする。
以前の保存データにある "remain"（残りEXP）は読むときに捨てる。
localStorage の値は壊れている可能性があるため、読むときは必ず
normalize_bond_ranks を通す。
"""

MIN_RANK = 1
MAX_RANK = 100


def _to_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def valid_rank(value) -> int | None:
    """絆ランクとして有効なら int、無効（空欄・範囲外）なら None。"""
    rank = _to_int(value)
    if rank is None or not MIN_RANK <= rank <= MAX_RANK:
        return None
    return rank


def normalize_bond_ranks(data) -> list[dict]:
    """保存データを検証済みの [{costume_id, rank}, ...] にする。

    不正なエントリ（衣装IDや絆ランクが無効）は落とし、同じ衣装が
    重複していれば先勝ちとする。
    """
    if not isinstance(data, dict) or not isinstance(data.get("costumes"), list):
        return []
    out = []
    seen = set()
    for e in data["costumes"]:
        if not isinstance(e, dict):
            continue
        cid = _to_int(e.get("costume_id"))
        rank = valid_rank(e.get("rank"))
        if cid is None or rank is None or cid in seen:
            continue
        seen.add(cid)
        out.append({"costume_id": cid, "rank": rank})
    return out


def bond_ranks_data(entries: list[dict]) -> dict:
    """エントリのリストを localStorage 保存用の形にする。"""
    return {"costumes": entries}


def bond_ranks_by_costume(data) -> dict[int, dict]:
    """保存データを {costume_id: エントリ} で返す。"""
    return {e["costume_id"]: e for e in normalize_bond_ranks(data)}


def save_bond_ranks(data, rank_by_costume: dict) -> dict:
    """各ページの入力値を保存データへ書き込む（追加・上書き）。

    rank が無効（空欄・範囲外）な衣装は変更しない。
    """
    by_cid = bond_ranks_by_costume(data)
    for key, value in rank_by_costume.items():
        cid = _to_int(key)
        rank = valid_rank(value)
        if cid is None or rank is None:
            continue
        by_cid[cid] = {"costume_id": cid, "rank": rank}
    return bond_ranks_data(list(by_cid.values()))


def apply_page_edits(data, rank_by_costume: dict) -> dict:
    """絆ランク管理ページの入力欄の値を保存データへ反映する。

    絆ランクが空欄の衣装は未設定（保存データから削除）に、範囲外の値は
    保存済みの値のまま（未設定なら未設定のまま）にする。入力欄に無い
    衣装は変更しない。
    """
    cleared = {_to_int(k) for k, v in rank_by_costume.items() if v is None or v == ""}
    saved = save_bond_ranks(data, rank_by_costume)
    return bond_ranks_data(
        [e for e in saved["costumes"] if e["costume_id"] not in cleared]
    )


def merge_ocr_cards(cards) -> list[dict]:
    """スクリーンショットの読み取り結果（カードごと）を衣装ごとにまとめる。

    cards は assets/bond_ocr.js の出力 [{"costume_id", "rank", "uncertain"}, ...]
    （ブラウザからの値なので検証する）。スクロールして撮った画像の重なりで
    同じ衣装が複数回読まれたときは、確実に読めた値を優先して 1 つにまとめ、
    読んだ値が食い違えば要確認にする（別の衣装を取り違えた可能性がある）。MAX_RANK を超える絆ランクは
    MAX_RANK にする。Returns 読み取り順の
    [{"costume_id", "rank", "read": 読み取った値, "uncertain"}]
    （数字が読めなかった衣装は rank / read が None で要確認）。
    """
    if not isinstance(cards, list):
        return []
    readings: dict[int, list[tuple[int | None, bool]]] = {}
    for c in cards:
        if not isinstance(c, dict):
            continue
        cid = _to_int(c.get("costume_id"))
        if cid is None:
            continue
        read = _to_int(c.get("rank"))
        if read is not None and read < MIN_RANK:
            read = None
        uncertain = bool(c.get("uncertain")) or read is None
        readings.setdefault(cid, []).append((read, uncertain))
    out = []
    for cid, rs in readings.items():
        certain = [r for r, u in rs if not u]
        read = certain[0] if certain else rs[0][0]
        out.append(
            {
                "costume_id": cid,
                "rank": None if read is None else min(read, MAX_RANK),
                "read": read,
                "uncertain": not certain or len({r for r, _ in rs}) > 1,
            }
        )
    return out


def ranks_for_costumes(data, costume_ids) -> dict[int, int]:
    """costume_id の並びに対して、保存済みの衣装の絆ランクを
    {並びの index: 値} で返す（各ページの入力欄の初期値に使う）。
    """
    by_cid = bond_ranks_by_costume(data)
    ranks = {}
    for i, v in enumerate(costume_ids):
        e = by_cid.get(_to_int(v))
        if e is not None:
            ranks[i] = e["rank"]
    return ranks
