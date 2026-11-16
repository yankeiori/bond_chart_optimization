"""贈り物 EXP テーブル。

ba-kizuna-calc (https://github.com/zeroichi/ba-kizuna-calc) の
utils/utils.ts: getEffectivity / getEffectivityId を移植したもの。

effectivity 文字列は "normal" | "favorite" | "super" | "ultra"。
DB の present.tier ("favorite" | "superFavorite" | "ultraFavorite") とは
別表現なので tier_to_effectivity() で変換する。
"""

# present.tier -> effectivity 文字列
_TIER_TO_EFFECTIVITY = {
    "favorite": "favorite",
    "superFavorite": "super",
    "ultraFavorite": "ultra",
}


# present.tier -> リアクションアイコン名 (assets/reaction/<name>.webp)。
TIER_ICON = {
    "favorite": "favorite",
    "superFavorite": "super",
    "ultraFavorite": "ultra",
}

# present.tier -> 効果ラベル。normal / high のどちらでも同じ対応になる
# （get_effectivity 参照。獲得EXPだけが gift_type で変わる）。
TIER_LABEL = {
    "favorite": "中",
    "superFavorite": "大",
    "ultraFavorite": "特大",
}


def tier_to_effectivity(tier: str | None) -> str:
    """present.tier を effectivity に変換する。

    好みに入らない（present に無い）場合は "normal"。
    """
    return _TIER_TO_EFFECTIVITY.get(tier or "", "normal")


def get_effectivity(gift_type: str, effectivity: str = "normal") -> tuple[str, int]:
    """贈り物タイプと effectivity から (効果ラベル, 獲得EXP) を返す。

    getEffectivity の移植。

    - high-all : 常に ("特大", 240)
    - normal-all : 常に ("大", 60)
    - high : super=("大",180) / ultra=("特大",240) / その他=("中",120)
    - normal : favorite=("中",40) / super=("大",60) / ultra=("特大",80)
               / その他=("小",20)
    """
    if gift_type == "high-all":
        return ("特大", 240)
    if gift_type == "normal-all":
        return ("大", 60)
    if gift_type == "high":
        if effectivity == "super":
            return ("大", 180)
        if effectivity == "ultra":
            return ("特大", 240)
        return ("中", 120)
    if gift_type == "normal":
        if effectivity == "favorite":
            return ("中", 40)
        if effectivity == "super":
            return ("大", 60)
        if effectivity == "ultra":
            return ("特大", 80)
        return ("小", 20)
    return ("？", 0)


_LABEL_TO_EFFECTIVITY_ID = {
    "小": "normal",
    "中": "favorite",
    "大": "super",
    "特大": "ultra",
}


def effectivity_id(label: str) -> str:
    """効果ラベル(小/中/大/特大) を effectivity id に変換する。

    getEffectivityId の移植。リアクションアイコン名に対応。
    """
    return _LABEL_TO_EFFECTIVITY_ID.get(label, "unknown")


def gift_exp(gift_type: str, tier: str | None = None) -> int:
    """present.tier から直接 獲得EXP を返す簡便関数。

    tier は DB present.tier ("favorite"/"superFavorite"/"ultraFavorite")
    または None（好みに入らない）。
    """
    return get_effectivity(gift_type, tier_to_effectivity(tier))[1]


# 贈り物選択ボックスの gift_id。
GIFT_SELECT_BOX_ID = "gift-select-box"


def gift_select_box_exp(costume_gifts) -> int:
    """贈り物選択ボックスの獲得EXP。

    その衣装の normal タイプ（normal-all は除く）の贈り物のうち、
    最も EXP が大きいものに一致する。好みの normal 贈り物が
    無くても、通常 normal の 20 が下限（任意の normal 贈り物を選べるため）。

    Parameters
    ----------
    costume_gifts : iterable of (gift_type, tier)
        対象衣装の present 行（贈り物タイプと present.tier）。
        gift-select-box 自身は含めても無害（normal/最大判定に吸収される）。
    """
    best = get_effectivity("normal", "normal")[1]  # 20
    for gift_type, tier in costume_gifts:
        if gift_type != "normal":
            continue
        exp = get_effectivity("normal", tier_to_effectivity(tier))[1]
        if exp > best:
            best = exp
    return best
