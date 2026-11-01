"""絆ランク管理（ブラウザの localStorage に保存する）のデータ操作。

保存データは {"costumes": [{"costume_id", "rank", "remain"}, ...]} の形。
rank は現在の絆ランク (1〜50)、remain は次の絆ランクまでの残り経験値
（任意。None なら現在ランクの開始＝経験値0 として扱う）。絆ランクを
設定した衣装だけを保存し、それ以外は「未設定」とする。
localStorage の値は壊れている可能性があるため、読むときは必ず
normalize_bond_ranks を通す。
"""

MIN_RANK = 1
MAX_RANK = 50


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


def _valid_remain(value) -> int | None:
    remain = _to_int(value)
    if remain is None or remain < 1:
        return None
    return remain


def normalize_bond_ranks(data) -> list[dict]:
    """保存データを検証済みの [{costume_id, rank, remain}, ...] にする。

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
        out.append(
            {"costume_id": cid, "rank": rank, "remain": _valid_remain(e.get("remain"))}
        )
    return out


def bond_ranks_data(entries: list[dict]) -> dict:
    """エントリのリストを localStorage 保存用の形にする。"""
    return {"costumes": entries}


def bond_ranks_by_costume(data) -> dict[int, dict]:
    """保存データを {costume_id: エントリ} で返す。"""
    return {e["costume_id"]: e for e in normalize_bond_ranks(data)}


def save_bond_ranks(data, rank_by_costume: dict, remain_by_costume=None) -> dict:
    """各ページの入力値を保存データへ書き込む（追加・上書き）。

    rank が無効（空欄・範囲外）な衣装は変更しない。remain_by_costume が
    None（残りEXPの入力欄が無いページ）のときは、絆ランクが変わらなければ
    保存済みの残りEXPを保持し、変わったら未入力に戻す。
    """
    by_cid = bond_ranks_by_costume(data)
    for key, value in rank_by_costume.items():
        cid = _to_int(key)
        rank = valid_rank(value)
        if cid is None or rank is None:
            continue
        old = by_cid.get(cid)
        if remain_by_costume is not None:
            remain = _valid_remain(remain_by_costume.get(key))
        elif old is not None and old["rank"] == rank:
            remain = old["remain"]
        else:
            remain = None
        by_cid[cid] = {"costume_id": cid, "rank": rank, "remain": remain}
    return bond_ranks_data(list(by_cid.values()))


def apply_page_edits(data, rank_by_costume: dict, remain_by_costume: dict) -> dict:
    """絆ランク管理ページの入力欄の値を保存データへ反映する。

    絆ランクが空欄の衣装は未設定（保存データから削除）に、範囲外の値は
    保存済みの値のまま（未設定なら未設定のまま）にする。入力欄に無い
    衣装は変更しない。
    """
    cleared = {_to_int(k) for k, v in rank_by_costume.items() if v is None or v == ""}
    saved = save_bond_ranks(data, rank_by_costume, remain_by_costume)
    return bond_ranks_data(
        [e for e in saved["costumes"] if e["costume_id"] not in cleared]
    )


def ranks_for_costumes(data, costume_ids) -> tuple[dict[int, int], dict[int, int]]:
    """costume_id の並びに対して、保存済みの衣装の 絆ランク / 残りEXP を
    {並びの index: 値} で返す（各ページの入力欄の初期値に使う）。
    """
    by_cid = bond_ranks_by_costume(data)
    ranks = {}
    remains = {}
    for i, v in enumerate(costume_ids):
        e = by_cid.get(_to_int(v))
        if e is None:
            continue
        ranks[i] = e["rank"]
        if e["remain"] is not None:
            remains[i] = e["remain"]
    return ranks, remains
