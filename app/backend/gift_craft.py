"""製造（クラフトチェンバー）の2次ノードで出る贈り物の対応表。

出典: ブルーアーカイブ攻略 Wiki「製造」2次ノードの選択
https://bluearchive.wikiru.jp/?%E8%A3%BD%E9%80%A0#SecondNodeChoice

花弁系の2次ノード（アサガオ〜翡翠花）はそれぞれ贈り物の1カテゴリに
対応し、ノード内の各贈り物は等確率で出る。贈り物はすべて通常（SR）の
もので、高級贈り物は2次ノードでは出ない。
贈り物名は DB の gift.name（= アイコン画像のファイル名）と一致させる。
"""

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
        "siblings": [n for n in names if n != name],
    }
    for node, category, names in SECOND_NODES
    for name in names
}


def second_node(gift_name: str) -> dict | None:
    """贈り物が出る2次ノードの情報を返す。2次ノードで出ない贈り物は None。

    {"node": ノード名, "category": カテゴリ, "rate": ノード内の出現率 (0〜1),
     "siblings": 同じノードで出る他の贈り物名のリスト}
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
