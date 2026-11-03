"""絆ランク管理（ブラウザの localStorage に保存する）のデータ操作。

保存データは {"costumes": [{"costume_id", "rank"}, ...]} の形。
rank は現在の絆ランク (1〜100)。絆ボーナスは 50 までなので、計算では
51 以上を 50 として扱う（各計算ページ側で丸める）。絆ランクを
設定した衣装だけを保存し、それ以外は「未設定」とする。
以前の保存データにある "remain"（残りEXP）は読むときに捨てる。
localStorage の値は壊れている可能性があるため、読むときは必ず
normalize_bond_ranks を通す。
"""

from statistics import median

from app.backend.bond_exp import BOND_EXP_PER_LEVEL

MIN_RANK = 1
MAX_RANK = 100
# 絆ボーナスが上限になる絆ランク
BONUS_MAX_RANK = 50


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

    cards は assets/bond_ocr.js の出力 [{"costume_id", "rank", "uncertain", "name"}, ...]
    （ブラウザからの値なので検証する。name は名前が衣装と食い違ったときの、最も近い名前）。
    スクロールして撮った画像の重なりで同じ衣装が複数回読まれたときは、確実に読めた値を
    優先して 1 つにまとめ、読んだ値が食い違えば要確認にする（別の衣装を取り違えた可能性が
    ある）。名前が食い違ったカードは別の生徒（候補に無い衣装など）なので、名前の合う
    カードがある衣装では使わない。MAX_RANK を超える絆ランクは MAX_RANK にする。
    Returns 読み取り順の [{"costume_id", "rank", "read": 読み取った値, "uncertain",
    "names": 食い違った名前（名前の合うカードが無い衣装だけ）, "dropped": 使わなかったカード数}]
    （数字が読めなかった衣装は rank / read が None で要確認）。
    """
    if not isinstance(cards, list):
        return []
    readings: dict[int, list[tuple[int | None, bool, str | None]]] = {}
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
        name = c.get("name")
        name = name[:40] if isinstance(name, str) and name else None
        readings.setdefault(cid, []).append((read, uncertain or name is not None, name))
    out = []
    for cid, all_rs in readings.items():
        rs = [r for r in all_rs if r[2] is None] or all_rs
        certain = [r for r, u, _ in rs if not u]
        read = certain[0] if certain else rs[0][0]
        out.append(
            {
                "costume_id": cid,
                "rank": None if read is None else min(read, MAX_RANK),
                "read": read,
                "uncertain": not certain or len({r for r, _, _ in rs}) > 1,
                "names": list(dict.fromkeys(n for _, _, n in rs if n)),
                "dropped": len(all_rs) - len(rs),
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


# 「あと少し」に出す範囲: 目標の絆ランクの何ランク手前から出すか
NEAR_RANKS = 5
# 「絆ランクが高い衣装」に出す数
TOP_COUNT = 10


def _exp_to(rank: int) -> int:
    """絆ランク 1 から rank までに必要な累計の絆経験値。"""
    return sum(BOND_EXP_PER_LEVEL[: rank - 1])


def bond_rank_stats(data, options: list[dict]) -> dict:
    """絆ランク統計ページに出す、自分の絆ランクの統計。

    options は衣装ドロップダウンのオプション [{value, label, student}, ...]
    （表示順）。ここに無い衣装（削除済み）の保存値は数えない。
    ranks は分布（ヒストグラム）用の設定済みの絆ランク（昇順）。
    """
    by_cid = bond_ranks_by_costume(data)
    rows = [
        {
            "label": o["label"],
            "student": o.get("student"),
            "rank": by_cid[o["value"]]["rank"],
        }
        for o in options
        if o["value"] in by_cid
    ]
    ranks = [r["rank"] for r in rows]

    near = []
    for r in rows:
        target = next(
            (t for t in (BONUS_MAX_RANK, MAX_RANK) if t - NEAR_RANKS <= r["rank"] < t),
            None,
        )
        if target is not None:
            near.append(
                {
                    **r,
                    "target": target,
                    "exp": _exp_to(target) - _exp_to(r["rank"]),
                }
            )
    near.sort(key=lambda r: r["exp"])

    return {
        "count": len(ranks),
        "costume_total": len(options),
        "students": len({r["student"] for r in rows}),
        "student_total": len({o.get("student") for o in options}),
        "total": sum(ranks),
        "avg": sum(ranks) / len(ranks) if ranks else None,
        "median": median(ranks) if ranks else None,
        "bonus_max": sum(1 for r in ranks if r >= BONUS_MAX_RANK),
        "max_rank": sum(1 for r in ranks if r == MAX_RANK),
        "exp_total": sum(_exp_to(r) for r in ranks),
        "exp_to_bonus_max": sum(
            _exp_to(BONUS_MAX_RANK) - _exp_to(r) for r in ranks if r < BONUS_MAX_RANK
        ),
        "exp_to_max": sum(_exp_to(MAX_RANK) - _exp_to(r) for r in ranks),
        "ranks": sorted(ranks),
        "near": near,
        "top": sorted(rows, key=lambda r: -r["rank"])[:TOP_COUNT],
    }
