"""贈り物配分の最適化（MILP / SCIP）。

各衣装の現在絆ランクから、使用可能な贈り物を配分して
全衣装の絆ボーナス上昇量の合計を最大化する。

定式化:
  x[g][c] >= 0 整数      … 贈り物 g を衣装 c に配る個数
  delta[c][r] in {0,1}   … 衣装 c が r-1 -> r のランクアップを達成
  s.t.
    sum_c x[g][c] <= qty[g]                          (所持数)
    delta[c][r] <= delta[c][r-1]                     (連続性)
    sum_r e(r) delta[c][r] <= sum_g v[g][c] x[g][c]  (消費EXP <= 獲得EXP)
  max sum_c sum_r b_c(r) delta[c][r]
"""

from time import monotonic

from app.backend.bond_exp import BOND_EXP_PER_LEVEL
from app.backend.student import BOND_RANGES

_MAX_RANK = 50
# 必要EXPテーブルの上限（絆100）。絆51以降は絆ボーナスがなく、目標絆ランク
# までの必要EXPを求めるとき（exp_to_reach_rank / solve_required_boxes）だけ使う。
_MAX_EXP_RANK = len(BOND_EXP_PER_LEVEL) + 1

# SCIP の制限時間（秒）。実データ規模では数ミリ秒で解けるが、
# 想定外の重い入力で UI が固まらないための保険。
# 到達時は status="timelimit" で暫定（最良実行可能）解を返す。
DEFAULT_TIME_LIMIT = 15.0


def _range_bonus(bond_bonuses: list[int], rank: int) -> int:
    """rank（2..50）が属する区間の絆ボーナス。"""
    for idx, (lo, hi) in enumerate(BOND_RANGES):
        if lo <= rank <= hi:
            return bond_bonuses[idx]
    return 0


def _level_exp(rank: int) -> int:
    """(rank-1) -> rank に必要な EXP。rank は 2..100。"""
    return BOND_EXP_PER_LEVEL[rank - 2]


def _rankup_costs(
    current_rank: int, remaining_exp, max_rank: int = _MAX_RANK
) -> dict[int, int]:
    """current_rank から max_rank（既定 50）までの各ランクアップ必要 EXP。

    最初の (current_rank -> current_rank+1) のみ remaining_exp（次の絆上昇
    までの残り経験値）で上書きできる。None・0以下は満額。[1, 満額] にクランプ。
    """
    cost = {}
    for r in range(current_rank + 1, max_rank + 1):
        base = _level_exp(r)
        if (
            r == current_rank + 1
            and remaining_exp is not None
            and int(remaining_exp) > 0
        ):
            base = max(1, min(int(remaining_exp), base))
        cost[r] = base
    return cost


def exp_to_reach_rank(current_rank: int, target_rank: int, remaining_exp=None) -> int:
    """current_rank から target_rank に上げるのに必要な EXP 合計。

    target_rank <= current_rank なら 0。target_rank は絆100が上限。
    remaining_exp の扱いは solve_gift_distribution と同じ（最初の
    ランクアップのみ上書き）。
    """
    target_rank = min(target_rank, _MAX_EXP_RANK)
    if target_rank <= current_rank:
        return 0
    cost = _rankup_costs(current_rank, remaining_exp, target_rank)
    return sum(cost.values())


def boxes_to_reach_rank(
    current_rank: int,
    target_rank: int,
    box_exp: int,
    remaining_exp=None,
) -> int:
    """贈り物選択ボックスのみで current_rank から target_rank に上げるのに
    必要なボックス個数（切り上げ）。

    box_exp は ボックス1個あたりの獲得EXP（gift_select_box_exp の値）。
    target_rank <= current_rank または box_exp <= 0 なら 0。
    remaining_exp の扱いは exp_to_reach_rank と同じ。
    """
    need = exp_to_reach_rank(current_rank, target_rank, remaining_exp)
    if need <= 0 or box_exp <= 0:
        return 0
    return -(-need // box_exp)


def bonus_gain(bond_bonuses: list[int], from_rank: int, to_rank: int) -> int:
    """from_rank から to_rank へのランクアップで得られる絆ボーナス合計。"""
    return sum(
        _range_bonus(bond_bonuses, r)
        for r in range(from_rank + 1, min(to_rank, _MAX_RANK) + 1)
    )


def _priority_groups(
    priorities: list[int | None] | None, n: int
) -> tuple[list[list[int]], bool]:
    """優先順位リストを順位ごとの衣装グループ（上位から順）に正規化する。

    priorities[c] は 1 が最優先で、同値は同順位（同じグループ）。None・不正値・
    1 未満は「順位未指定」として最後のグループにまとめる。

    Returns
    -------
    (groups, has_unspecified)
        groups : 順位が上のグループから並んだ衣装 index のリスト。
        has_unspecified : 末尾のグループが「順位未指定」かどうか。
    """
    prio: list[int | None] = []
    for c in range(n):
        try:
            r = int(priorities[c]) if priorities is not None else None
        except (TypeError, ValueError, IndexError):
            r = None
        prio.append(r if r is not None and r >= 1 else None)
    groups = [
        [c for c in range(n) if prio[c] == r]
        for r in sorted({r for r in prio if r is not None})
    ]
    has_unspecified = any(r is None for r in prio)
    if has_unspecified:
        groups.append([c for c in range(n) if prio[c] is None])
    return groups, has_unspecified


def solve_gift_distribution(
    current_ranks: list[int],
    bond_bonuses: list[list[int]],
    gift_qty: list[int],
    value: list[list[int]],
    time_limit: float = DEFAULT_TIME_LIMIT,
    remaining_exp: list[int | None] | None = None,
    costume_priorities: list[int | None] | None = None,
) -> dict:
    """贈り物配分 MILP を解く。

    Parameters
    ----------
    current_ranks : list[int]
        衣装ごとの現在絆ランク (1..50)。
    bond_bonuses : list[list[int]]
        衣装ごとの絆ボーナス（各 7 要素、BOND_RANGES 対応）。
    gift_qty : list[int]
        贈り物ごとの所持数。
    value : list[list[int]]
        value[g][c] = 贈り物 g を衣装 c に 1 個使ったときの獲得EXP。
    time_limit : float
        SCIP の制限時間（秒）。
    remaining_exp : list[int | None] | None
        衣装ごとの「次の絆上昇までの残り経験値」。指定された衣装は
        最初のランクアップ (r0 -> r0+1) の必要EXPをこの値で上書きする
        （途中まで経験値が貯まっているケース）。None / 該当要素が
        None・0以下 の場合は通常どおりレベル満額を要求する。値は
        [1, 満額] にクランプする。
    costume_priorities : list[int | None] | None
        衣装ごとの優先順位（1 が最優先、同値は同順位）。絆ボーナス合計が
        最大かつ使用贈り物数が最小である解が複数ある場合のタイブレークに
        使う。順位が上のグループほど絆ランクの合計が高い解を辞書式に選ぶ
        （= 同コストなら優先度の高い衣装に絆経験値が寄る）。使用贈り物数は
        増えないので、余った贈り物が無駄に配られることはない。None・不正値・
        1 未満は「順位未指定」でタイブレーク対象外。全衣装が同順位（または
        未指定）なら従来どおり 1 回の求解。

    Returns
    -------
    dict
        {
          "allocation": list[list[int]]  # allocation[g][c]
          "final_ranks": list[int]
          "total_gain": int
          "status": str
        }
    """
    from pyscipopt import Model, quicksum

    n = len(current_ranks)
    m = len(gift_qty)

    model = Model("gift_distribution")
    model.hideOutput()
    model.setParam("limits/time", time_limit)

    # x[g][c]
    x = {}
    for g in range(m):
        ub = max(0, int(gift_qty[g]))
        for c in range(n):
            x[g, c] = model.addVar(vtype="I", lb=0, ub=ub, name=f"x_{g}_{c}")

    # delta[c][r] : r = current_rank+1 .. 50
    delta = {}
    for c in range(n):
        r0 = current_ranks[c]
        for r in range(r0 + 1, _MAX_RANK + 1):
            delta[c, r] = model.addVar(vtype="B", name=f"d_{c}_{r}")

    # 所持数
    for g in range(m):
        if n > 0:
            model.addCons(
                quicksum(x[g, c] for c in range(n)) <= max(0, int(gift_qty[g]))
            )

    for c in range(n):
        r0 = current_ranks[c]
        # 連続性: 上位ランクアップは下位を前提
        for r in range(r0 + 2, _MAX_RANK + 1):
            model.addCons(delta[c, r] <= delta[c, r - 1])
        # 各ランクアップの必要EXP。最初の r0 -> r0+1 のみ「次の絆上昇
        # までの残り経験値」で上書きできる（途中まで貯まっている場合）。
        rem = (
            remaining_exp[c]
            if remaining_exp is not None and c < len(remaining_exp)
            else None
        )
        cost = _rankup_costs(r0, rem)
        # 消費EXP <= 獲得EXP
        consumed = quicksum(cost[r] * delta[c, r] for r in range(r0 + 1, _MAX_RANK + 1))
        gained = quicksum(value[g][c] * x[g, c] for g in range(m))
        model.addCons(consumed <= gained)

    # 目的: 絆ボーナス上昇量の合計を最大化（主目的）。
    # 同点時は使用贈り物の総数を最小化（無駄な配分を避ける二次目的）。
    # W は「贈り物を1個節約するより絆ボーナス1点が常に優先」される十分大の重み。
    bonus_term = quicksum(
        _range_bonus(bond_bonuses[c], r) * delta[c, r]
        for c in range(n)
        for r in range(current_ranks[c] + 1, _MAX_RANK + 1)
    )
    used_term = quicksum(x[g, c] for g in range(m) for c in range(n))
    weight = sum(max(0, int(q)) for q in gift_qty) + 1
    main_term = weight * bonus_term - used_term

    # タイブレーク用: 順位ごとの「獲得ランク数の合計」。順位未指定の
    # グループ（末尾）はタイブレークに使わない。
    groups, has_unspecified = _priority_groups(costume_priorities, n)
    ranked_groups = groups[:-1] if has_unspecified else groups
    rank_terms = [
        quicksum(
            delta[c, r] for c in grp for r in range(current_ranks[c] + 1, _MAX_RANK + 1)
        )
        for grp in ranked_groups
    ]

    def _extract():
        sol = model.getBestSol()
        al = [
            [int(round(model.getSolVal(sol, x[g, c]))) for c in range(n)]
            for g in range(m)
        ]
        fr = []
        for c in range(n):
            r0 = current_ranks[c]
            cnt = sum(
                1
                for r in range(r0 + 1, _MAX_RANK + 1)
                if model.getSolVal(sol, delta[c, r]) > 0.5
            )
            fr.append(r0 + cnt)
        return al, fr

    snapshot = None
    statuses = []

    if len(groups) <= 1:
        # 優先順位の指定なし（全衣装が同順位 or 全て未指定）:
        # タイブレークの余地がないので従来どおり1回の求解。
        model.setObjective(main_term, "maximize")
        model.optimize()
        statuses.append(model.getStatus())
        if model.getNSols() > 0:
            snapshot = _extract()
    else:
        # 辞書式最適化: 主目的（ボーナス最大 → 使用数最小）を制約として
        # 固定したうえで、順位が上のグループから獲得ランク数を最大化する。
        # time_limit は全段の合計に対する制限として扱う。
        deadline = monotonic() + time_limit

        def _optimize():
            model.setParam("limits/time", max(0.1, deadline - monotonic()))
            model.optimize()
            statuses.append(model.getStatus())
            return model.getNSols() > 0

        model.setObjective(main_term, "maximize")
        if _optimize():
            snapshot = _extract()
            bound = int(round(model.getObjVal()))
            model.freeTransform()
            model.addCons(main_term >= bound)
            for term in rank_terms:
                model.setObjective(term, "maximize")
                if not _optimize():
                    break
                snapshot = _extract()
                grp_bound = int(round(model.getObjVal()))
                model.freeTransform()
                model.addCons(term >= grp_bound)

    if all(s == "optimal" for s in statuses):
        status = "optimal"
    elif snapshot is not None:
        # 途中で時間制限等に達した場合は暫定解として扱う
        status = "timelimit"
    else:
        status = statuses[0]

    allocation = [[0] * n for _ in range(m)]
    final_ranks = list(current_ranks)
    total_gain = 0

    if snapshot is not None:
        allocation, final_ranks = snapshot
        # 目的値は重み付き式なので、絆ボーナス上昇量は実ランクから再計算
        total_gain = sum(
            _range_bonus(bond_bonuses[c], r)
            for c in range(n)
            for r in range(current_ranks[c] + 1, final_ranks[c] + 1)
        )

    return {
        "allocation": allocation,
        "final_ranks": final_ranks,
        "total_gain": total_gain,
        "status": status,
    }


def solve_required_boxes(
    current_ranks: list[int],
    bond_bonuses: list[list[int]],
    gift_qty: list[int],
    value: list[list[int]],
    box_values: list[int],
    target_ranks: list[int | None] | None = None,
    target_gain: int | None = None,
    time_limit: float = DEFAULT_TIME_LIMIT,
    remaining_exp: list[int | None] | None = None,
    box_priorities: list[int | None] | None = None,
) -> dict:
    """目標達成に不足する贈り物選択ボックス数の最小値を求める。

    所持贈り物（gift_qty / value、solve_gift_distribution と同形式）を
    自由に配分してよい前提で、目標の達成に追加で必要な
    贈り物選択ボックスの総数を最小化する。同点時は box_priorities の
    順位が上の衣装から不足ボックス数を最小化し（辞書式）、最後に
    所持贈り物の使用数が最少の解を選ぶ（無駄な配分を避ける）。

    目標は次のいずれか（両方指定した場合は両方を課す）:
      - target_ranks : 衣装ごとの目標絆ランク（None の衣装は対象外）
      - target_gain  : 絆ボーナス上昇量の合計の下限

    Parameters
    ----------
    box_values : list[int]
        衣装ごとの ボックス1個あたり獲得EXP（gift_select_box_exp の値）。
        所持している選択ボックスは gift_qty / value 側に含めてよい
        （その場合ここで数えるのは「追加で必要な」個数）。
    box_priorities : list[int | None] | None
        衣装ごとの優先順位（1 が最優先、同値は同順位）。追加ボックスの
        総数が最小である解の中から、順位が上のグループほど不足ボックス
        数が少ない解を辞書式に選ぶ（= 順位が上の衣装から所持贈り物を
        充当する）。総ボックス数が増えることはない。None・不正値・
        1 未満は「順位未指定」として最後のグループ扱い。全衣装が
        同一グループなら従来どおり 1 回の求解。

    Returns
    -------
    dict
        {
          "boxes": list[int]             # 衣装ごとの追加ボックス数
          "allocation": list[list[int]]  # 所持贈り物の配分 allocation[g][c]
          "final_ranks": list[int]
          "total_boxes": int
          "total_gain": int
          "status": str                  # "optimal" / "timelimit" / "infeasible" 等
        }
    """
    from pyscipopt import Model, quicksum

    n = len(current_ranks)
    m = len(gift_qty)
    if target_ranks is None:
        target_ranks = [None] * n
    # 優先順位を正規化し、順位ごとの衣装グループ（上位から順）を作る。
    groups, _ = _priority_groups(box_priorities, n)
    has_rank_target = any(
        t is not None and t > current_ranks[c] for c, t in enumerate(target_ranks)
    )
    if not has_rank_target and (target_gain is None or target_gain <= 0):
        return {
            "boxes": [0] * n,
            "allocation": [[0] * n for _ in range(m)],
            "final_ranks": list(current_ranks),
            "total_boxes": 0,
            "total_gain": 0,
            "status": "optimal",
        }

    model = Model("required_boxes")
    model.hideOutput()
    model.setParam("limits/time", time_limit)

    # x[g][c]: 所持贈り物の配分
    x = {}
    for g in range(m):
        ub = max(0, int(gift_qty[g]))
        for c in range(n):
            x[g, c] = model.addVar(vtype="I", lb=0, ub=ub, name=f"x_{g}_{c}")
    for g in range(m):
        if n > 0:
            model.addCons(
                quicksum(x[g, c] for c in range(n)) <= max(0, int(gift_qty[g]))
            )

    # y[c]: 追加ボックス数。delta[c][r]: ランク到達（目標ランクまでは lb=1 で強制）
    y = {}
    delta = {}
    top = {}
    for c in range(n):
        r0 = current_ranks[c]
        rem = (
            remaining_exp[c]
            if remaining_exp is not None and c < len(remaining_exp)
            else None
        )
        forced_to = target_ranks[c]
        forced_to = min(int(forced_to), _MAX_EXP_RANK) if forced_to is not None else r0
        # 絆ボーナスは絆50まで。目標が絆51以上ならその目標までランクを持つ
        top[c] = max(_MAX_RANK, forced_to)
        costs = _rankup_costs(r0, rem, top[c])
        # top 到達分を超えるボックスは無意味なので上限にする
        v = int(box_values[c])
        ub = 0 if v <= 0 else -(-sum(costs.values()) // v)
        y[c] = model.addVar(vtype="I", lb=0, ub=ub, name=f"y_{c}")

        for r in range(r0 + 1, top[c] + 1):
            lb = 1 if r <= forced_to else 0
            delta[c, r] = model.addVar(vtype="B", lb=lb, name=f"d_{c}_{r}")
        for r in range(r0 + 2, top[c] + 1):
            model.addCons(delta[c, r] <= delta[c, r - 1])
        consumed = quicksum(costs[r] * delta[c, r] for r in range(r0 + 1, top[c] + 1))
        gained = quicksum(value[g][c] * x[g, c] for g in range(m))
        model.addCons(consumed <= gained + v * y[c])

    if target_gain is not None and target_gain > 0:
        bonus_term = quicksum(
            _range_bonus(bond_bonuses[c], r) * delta[c, r]
            for c in range(n)
            for r in range(current_ranks[c] + 1, _MAX_RANK + 1)
        )
        model.addCons(bonus_term >= int(target_gain))

    # 主目的: 追加ボックス総数の最小化。同点時は優先順位の高いグループ
    # から順に不足ボックス数を最小化し（辞書式）、最後に所持贈り物の
    # 使用数を最小化する（無駄な配分を避ける）。
    total_y = quicksum(y[c] for c in range(n))
    used_term = quicksum(x[g, c] for g in range(m) for c in range(n))

    def _extract():
        sol = model.getBestSol()
        bx = [int(round(model.getSolVal(sol, y[c]))) for c in range(n)]
        al = [
            [int(round(model.getSolVal(sol, x[g, c]))) for c in range(n)]
            for g in range(m)
        ]
        fr = []
        for c in range(n):
            r0 = current_ranks[c]
            cnt = sum(
                1
                for r in range(r0 + 1, top[c] + 1)
                if model.getSolVal(sol, delta[c, r]) > 0.5
            )
            fr.append(r0 + cnt)
        return bx, al, fr

    snapshot = None
    statuses = []

    if len(groups) <= 1:
        # 優先順位の指定なし（実質1グループ）: 従来どおり1回の求解。
        # W は「所持贈り物を全部ケチってもボックス1個の節約に勝てない」重み。
        weight = sum(max(0, int(q)) for q in gift_qty) + 1
        model.setObjective(weight * total_y + used_term, "minimize")
        model.optimize()
        statuses.append(model.getStatus())
        if model.getNSols() > 0:
            snapshot = _extract()
    else:
        # 辞書式最適化: 上位の目的値を制約として固定しながら順に解く。
        # time_limit は全段の合計に対する制限として扱う。
        deadline = monotonic() + time_limit

        def _optimize():
            model.setParam("limits/time", max(0.1, deadline - monotonic()))
            model.optimize()
            statuses.append(model.getStatus())
            return model.getNSols() > 0

        model.setObjective(total_y, "minimize")
        if _optimize():
            snapshot = _extract()
            bound = int(round(model.getObjVal()))
            model.freeTransform()
            model.addCons(total_y <= bound)
            # 最後のグループは総数と他グループから一意に決まるので省略。
            # 上位グループの合計が総数に達したら残りは 0 で確定なので省略。
            ok = True
            fixed = 0
            for grp in groups[:-1]:
                if fixed >= bound:
                    break
                grp_y = quicksum(y[c] for c in grp)
                model.setObjective(grp_y, "minimize")
                if not _optimize():
                    ok = False
                    break
                snapshot = _extract()
                grp_bound = int(round(model.getObjVal()))
                model.freeTransform()
                model.addCons(grp_y <= grp_bound)
                fixed += grp_bound
            if ok:
                model.setObjective(used_term, "minimize")
                if _optimize():
                    snapshot = _extract()

    if all(s == "optimal" for s in statuses):
        status = "optimal"
    elif snapshot is not None:
        # 途中で時間制限等に達した場合は暫定解として扱う
        status = "timelimit"
    else:
        status = statuses[0]

    boxes = [0] * n
    allocation = [[0] * n for _ in range(m)]
    final_ranks = list(current_ranks)
    total_gain = 0

    if snapshot is not None:
        boxes, allocation, final_ranks = snapshot
        total_gain = sum(
            bonus_gain(bond_bonuses[c], current_ranks[c], final_ranks[c])
            for c in range(n)
        )

    return {
        "boxes": boxes,
        "allocation": allocation,
        "final_ranks": final_ranks,
        "total_boxes": sum(boxes),
        "total_gain": total_gain,
        "status": status,
    }
