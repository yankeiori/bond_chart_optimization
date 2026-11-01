"""製造の家具ノードを、出る家具を素材として追加投入したときのゲージ増加量で比べる。

出典: ブルーアーカイブ攻略 Wiki「製造」3次ノードの選択
https://bluearchive.wikiru.jp/?%E8%A3%BD%E9%80%A0#ThirdNodeChoice

追加投入したときのゲージ増加量は家具の★で決まる（2次・3次とも同じ値）。
ノードの重みと★別の内訳は、SchaleDB から生成した crafting_data を使う。
対象は家具だけが出るノード（色彩・シリーズ・各色）で、明かり・輝き・煌めき
のように家具以外も出るノードは含めない。
"""

from app.backend.crafting_data import FURNITURE, TIERS

# ★ -> 追加投入したときのゲージ増加量（%）。★0 は ★1ノーマル家具
GAUGE = {0: 5, 1: 10, 2: 20, 3: 50}

# 2次の色彩ノード -> 家具の分類（Wiki の表記。グレーは製造画面では「装飾」）
COLOR_CATEGORIES = {
    "ブラック": "テーブル",
    "イエロー": "クローゼット",
    "レッド": "椅子",
    "グレー": "小物",
    "ピンク": "家電",
    "パープル": "ベッド",
    "グリーン": "壁の装飾",
    "アンバー": "床の装飾",
    "ブラウン": "床",
    "ホワイト": "背景",
    "ブルー": "壁紙",
}


def _category(tier: int, name: str) -> str:
    if name in COLOR_CATEGORIES:
        return COLOR_CATEGORIES[name]
    if name == "色彩":
        return "★2以上の家具" if tier == 3 else "家具全般"
    return "シリーズ家具"


def furniture_node_ranking(tier: int) -> list[dict]:
    """tier 次の家具ノードを、ゲージ増加量の期待値（%）の高い順に並べる。

    3次は個数に幅があり（★2 2〜3個、★3 1〜2個）、最小〜最大を等確率とする。
    返り値の各要素:
        node: ノード名, category: 家具の分類, ev: ゲージ増加量の期待値（%）,
        appear: 段内でのノードの出現率（重みの割合）,
        stars: [{star, rate, min, max}, ...]（★の低い順）
    """
    nodes = TIERS[tier - 1]
    total = sum(weight for _, _, weight, _ in nodes)
    rows = []
    for node_id, name, weight, _ in nodes:
        if node_id not in FURNITURE:
            continue
        stars = [
            {"star": star, "rate": rate, "min": lo, "max": hi}
            for star, rate, lo, hi in FURNITURE[node_id]
        ]
        ev = sum(
            s["rate"] * (s["min"] + s["max"]) / 2 * GAUGE[s["star"]] for s in stars
        )
        rows.append(
            {
                "node": name,
                "category": _category(tier, name),
                "ev": ev,
                "appear": weight / total,
                "stars": stars,
            }
        )
    rows.sort(key=lambda r: -r["ev"])
    return rows
