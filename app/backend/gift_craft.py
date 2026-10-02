"""製造（クラフトチェンバー）の2次ノードで出る贈り物の対応表。

出典: ブルーアーカイブ攻略 Wiki「製造」2次ノードの選択
https://bluearchive.wikiru.jp/?%E8%A3%BD%E9%80%A0#SecondNodeChoice

花弁系の2次ノード（アサガオ〜翡翠花）はそれぞれ贈り物の1カテゴリに
対応し、ノード内の各贈り物は等確率で出る。贈り物はすべて通常（SR）の
もので、高級贈り物は2次ノードでは出ない。
贈り物名は DB の gift.name（= アイコン画像のファイル名）と一致させる。

製造1回あたりの期待値 (craft_expected_exp) は、SchaleDB から生成した
crafting_data の1〜3次ノードの重みと贈り物の出現率を使う。
"""

from functools import lru_cache

import numpy as np

from app.backend.crafting_data import TIERS
from app.backend.gift_exp import gift_exp

# (ノード名, 贈り物カテゴリ, そのノードで出る贈り物名)
SECOND_NODES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("アサガオ", "運動用品", ("ペロロの腹筋ローラー", "O-フィット")),
    (
        "百日紅",
        "おもちゃ",
        (
            "天体望遠鏡",
            "コスプレ用ぐるぐるメガネ",
            "リボンのついた熊のぬいぐるみ",
            "30色の絵の具セット",
            "頭脳開発キューブパズル",
        ),
    ),
    (
        "タンポポ",
        "古美術",
        (
            "埋蔵金の地図",
            "世界で最も無駄な絡繰りボックス",
            "高級そうな欲望のつぼ",
            "ぜんまい式オルゴール",
        ),
    ),
    (
        "スイセン",
        "スイーツ",
        (
            "高級なクッキーセット",
            "MX-レーションC型デザート風味",
            "抹茶味の瓶ラムネ",
            "大きなホールケーキ",
        ),
    ),
    ("薔薇", "電子機器", ("エーポッドプロ", "ゲームガールカラー復刻版")),
    (
        "チューリップ",
        "書籍",
        (
            "禁断の愛～許されないからこそ美しく～",
            "ゲームマガジン「ヒットガールズ」",
            "『銃 可愛い 青春』",
            "跳躍探偵ウサギ～霧に包まれた温泉での滑落～",
            "古典の詩集",
            "百科事典",
        ),
    ),
    ("牡丹", "寝具類", ("ウェーブキャットの枕", "ゼリーズの枕")),
    (
        "桜",
        "化粧品",
        (
            "チェリーローズカラーのグロス",
            "お肌を透明にするBBクリーム",
            "ミリタリー用カモフラージュクリーム3種セット",
        ),
    ),
    ("ユリ", "チケット", ("映画の前売りペアチケット", "ハイクラスビュッフェ招待券")),
    ("桔梗", "園芸関連", ("食虫植物の植木鉢",)),
    ("ツツジ", "健康食品", ("ザ・サプリメント",)),
    ("モクレン", "ファッション雑貨", ("刺繍付きのハンカチ",)),
    ("キンセンカ", "家事用品", ("可愛い食器セット",)),
    ("翡翠花", "水遊び", ("夏模様の浮き輪",)),
)

_BY_GIFT_NAME: dict[str, dict] = {
    name: {
        "node": node,
        "category": category,
        # ノード内は等確率
        "rate": 1 / len(names),
    }
    for node, category, names in SECOND_NODES
    for name in names
}


def second_node(gift_name: str) -> dict | None:
    """贈り物が出る2次ノードの情報を返す。2次ノードで出ない贈り物は None。

    {"node": ノード名, "category": カテゴリ, "rate": ノード内の出現率 (0〜1)}
    """
    return _BY_GIFT_NAME.get(gift_name)


# 花弁ノード: 2次ノードで出る贈り物すべてから等確率で1つ出る。
PETAL_NODE: tuple[str, str, tuple[str, ...]] = (
    "花弁",
    "贈り物（全種）",
    tuple(name for _, _, names in SECOND_NODES for name in names),
)


def compare_second_nodes(gifts: list[dict], members: list[dict]) -> list[dict]:
    """2次ノードごとに、1回の製造で出る贈り物の絆EXP期待値を比べる。

    贈り物1つの価値は、絆上げ対象のうち最も効果が高い衣装に贈ったときの
    (重み × 獲得EXP) とする。ノードの期待値はノード内の贈り物（等確率）の
    価値の平均。花弁ノード（全種から等確率）も比較対象に含める。

    Parameters
    ----------
    gifts : load_gifts() の結果 [{id, name, gift_type}, ...]。
        gift.name で対応表と突き合わせ、DB に無い贈り物は計算から除く。
    members : [{"label": 表示名, "weight": 重み, "present": {gift_id: tier}}]
        空なら全贈り物を好み無し（小）として扱う。

    Returns
    -------
    期待値の降順（同値は定義順）に並べた
    [{"node", "category", "ev", "gifts": [{"id", "name", "value", "exp",
      "tier", "label"}]}]。
    value は重み付きの値、exp/tier/label はその値を出した衣装のもの
    （好物にしている衣装が無ければ tier/label は None）。
    """
    by_name = {g["name"]: g for g in gifts}
    rows = []
    for node, category, names in (*SECOND_NODES, PETAL_NODE):
        details = []
        for name in names:
            gift = by_name.get(name)
            if gift is None:
                continue
            details.append(_best_member(gift, members))
        if not details:
            continue
        ev = sum(d["value"] for d in details) / len(details)
        rows.append({"node": node, "category": category, "ev": ev, "gifts": details})
    rows.sort(key=lambda r: -r["ev"])
    return rows


def _best_member(gift: dict, members: list[dict]) -> dict:
    """贈り物を最も価値が高くなる衣装に贈ったときの値と、その衣装。"""
    best = {
        "id": gift["id"],
        "name": gift["name"],
        "value": float(gift_exp(gift["gift_type"])) if not members else -1.0,
        "exp": gift_exp(gift["gift_type"]),
        "tier": None,
        "label": None,
    }
    for m in members:
        tier = m["present"].get(gift["id"])
        exp = gift_exp(gift["gift_type"], tier)
        value = m["weight"] * exp
        # 同値なら好物にしている衣装を優先して表示する
        if value > best["value"] or (
            value == best["value"] and tier and best["tier"] is None
        ):
            best.update(
                value=value,
                exp=exp,
                tier=tier,
                label=m["label"] if tier else None,
            )
    return best


# ---------------------------------------------------------------------------
# 製造1回あたりの期待値（1〜3次）
# ---------------------------------------------------------------------------

# 各段で提示されるノードの数。未選択のノードから重み付きで1つずつ選ぶ。
OFFERED_NODES = 5


def _none_offered(w_top: float, w_rest: np.ndarray, k: int = OFFERED_NODES) -> float:
    """重み w_top のノード群が、k 個の重み付き非復元抽出に1つも入らない確率。

    重み付き非復元抽出は、各ノードに Exp(重み) の到着時刻を与えて早い順に
    k 個取るのと同じ。よって「ノード群の最初の到着 t より前に、残りの
    ノードが k 個以上到着する確率」を t で積分すればよい。
    w_rest は残りのノードの重み（全ノードの合計が 1 になるよう正規化済み）。
    """
    if len(w_rest) < k:
        return 0.0
    # 被積分関数は log t でなめらかな山になるので、log t の等間隔格子で台形則
    u = np.linspace(np.log(1e-3 / max(w_rest.max(), w_top)), np.log(60 / w_top), 2000)
    t = np.exp(u)
    # d[j] = 時刻 t までに到着した残りノードが j 個（d[k] は k 個以上）の確率
    d = np.zeros((k + 1, len(t)))
    d[0] = 1
    for w in w_rest:
        p = -np.expm1(-w * t)
        at_least_k = d[k] + d[k - 1] * p
        d[1:k] = d[1:k] * (1 - p) + d[: k - 1] * p
        d[0] *= 1 - p
        d[k] = at_least_k
    return float(np.trapezoid(w_top * np.exp(-w_top * t) * t * d[k], u))


@lru_cache(maxsize=256)
def _miss_prob(tier: int, top: frozenset[int]) -> float:
    """tier 段で、ノード（TIERS 内の添字）の集合 top が提示されない確率。"""
    weights = np.array([n[2] for n in TIERS[tier - 1]], dtype=float)
    weights /= weights.sum()
    mask = np.zeros(len(weights), dtype=bool)
    mask[list(top)] = True
    return _none_offered(float(weights[mask].sum()), weights[~mask])


def craft_expected_exp(gifts: list[dict], members: list[dict]) -> dict:
    """製造1回で、1〜3次ノードから得られる贈り物の絆EXP期待値。

    各段では、未選択のノードから重み付きで1つ選ぶことを OFFERED_NODES 回
    繰り返して提示ノードを決め、その中で期待値が最大のノードを選ぶ。
    選んだノードの報酬が段ごとに1回出るとして、3段分を合計する。

    ノードの期待値は Σ (出現率 × 平均個数 × 贈り物の価値)。贈り物の価値は
    compare_second_nodes と同じく、絆上げ対象のうち最も効果が高い衣装に
    贈ったときの (重み × 獲得EXP)。個数は最小〜最大を等確率とする。

    Parameters
    ----------
    gifts, members : compare_second_nodes と同じ。

    Returns
    -------
    {"ev": 合計, "tiers": [{"tier", "ev", "nodes": [...]}]}
    nodes は贈り物が出るノードを期待値の降順に並べた
    [{"id", "name", "ev", "offered": 提示される確率, "pick": 選ぶ確率,
      "gifts": [{"id", "name", "rate", "amount", "value", "exp", "tier",
      "label"}]}]。
    期待値が同じノードはどれを選んでも同じなので、同率のノードをまとめて
    選ぶ確率を求め、各ノードの pick はそれを提示される確率で按分した値。
    """
    by_name = {g["name"]: g for g in gifts}
    best = {}
    tiers = []
    for tier, nodes in enumerate(TIERS, start=1):
        rows = []
        for index, (node_id, name, _, node_gifts) in enumerate(nodes):
            if not node_gifts:
                continue
            details = []
            for gift_name, rate, amount_min, amount_max in node_gifts:
                gift = by_name.get(gift_name)
                if gift is None:
                    continue
                if gift_name not in best:
                    best[gift_name] = _best_member(gift, members)
                details.append(
                    {
                        **best[gift_name],
                        "rate": rate,
                        "amount": (amount_min + amount_max) / 2,
                    }
                )
            ev = sum(d["rate"] * d["amount"] * d["value"] for d in details)
            rows.append(
                {
                    "index": index,
                    "id": node_id,
                    "name": name,
                    "ev": ev,
                    "offered": 1 - _miss_prob(tier, frozenset({index})),
                    "gifts": details,
                }
            )
        rows.sort(key=lambda r: -r["ev"])

        # 期待値の高い順に、同率のノードをまとめて「その中から選ぶ確率」を求める
        tier_ev = 0.0
        above = frozenset()
        miss_above = 1.0
        i = 0
        while i < len(rows):
            j = i
            while j < len(rows) and np.isclose(rows[j]["ev"], rows[i]["ev"]):
                j += 1
            block = rows[i:j]
            above |= {r["index"] for r in block}
            miss = _miss_prob(tier, above)
            pick = miss_above - miss if rows[i]["ev"] > 0 else 0.0
            offered = sum(r["offered"] for r in block)
            for r in block:
                r["pick"] = pick * r["offered"] / offered
            tier_ev += pick * rows[i]["ev"]
            miss_above = miss
            i = j
        for r in rows:
            del r["index"]
        tiers.append({"tier": tier, "ev": tier_ev, "nodes": rows})
    return {"ev": sum(t["ev"] for t in tiers), "tiers": tiers}
