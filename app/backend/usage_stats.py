"""管理画面ダッシュボード用の、絆ランク管理の利用状況の集計。

ログインして絆ランクをサーバーに保存した人だけが対象（ログインせずに
使っている人のデータはブラウザにしか無いので数えられない）。
DB には触らず、accounts.load_all_user_bond_ranks の値を受け取って集計する。
"""

from datetime import datetime, timedelta, timezone
from statistics import median

JST = timezone(timedelta(hours=9))

# 絆ランクの分布の区切り。絆ランク画像のグループ（100 / 99〜90 / … / 9〜1）と揃える。
RANK_BUCKETS = [(1, 9)] + [(lo, lo + 9) for lo in range(10, 100, 10)] + [(100, 100)]

# 新規利用者の日別グラフに出す日数（最大・最小）。
DAILY_DAYS = 30
DAILY_MIN_DAYS = 14

# 「よく使っている」とみなす直近の日数。
RECENT_DAYS = 7


def bucket_label(lo: int, hi: int) -> str:
    return str(lo) if lo == hi else f"{lo}〜{hi}"


def rank_histogram(ranks: list[int]) -> list[int]:
    """RANK_BUCKETS の区切りごとの件数。"""
    return [sum(1 for r in ranks if lo <= r <= hi) for lo, hi in RANK_BUCKETS]


def _rank_summary(ranks: list[int]) -> dict:
    if not ranks:
        return {"count": 0, "avg": None, "median": None, "max": None}
    return {
        "count": len(ranks),
        "avg": sum(ranks) / len(ranks),
        "median": median(ranks),
        "max": max(ranks),
    }


def compute_usage_stats(
    users: list[dict],
    costumes: list[dict],
    now: datetime,
    exclude_admin: bool = False,
) -> dict:
    """利用状況の集計。

    Parameters
    ----------
    users : accounts.load_all_user_bond_ranks の値。
    costumes : [{costume_id, student_name, costume_name}, ...]（表示順）。
        ここに無い衣装（削除済み）の保存値は集計から外す。
    now : 現在時刻（timezone 付き）。
    exclude_admin : 管理者のアカウントを除くか（既定は含める）。
    """
    known = {c["costume_id"] for c in costumes}
    targets = [u for u in users if not (exclude_admin and u["is_admin"])]
    recent = now - timedelta(days=RECENT_DAYS)

    per_user = []
    ranks_by_costume: dict[int, list[int]] = {cid: [] for cid in known}
    all_ranks: list[int] = []
    for u in targets:
        ranks = []
        for e in u["entries"]:
            if e["costume_id"] in known:
                ranks.append(e["rank"])
                ranks_by_costume[e["costume_id"]].append(e["rank"])
        all_ranks.extend(ranks)
        per_user.append(
            {
                "id": u["id"],
                "is_admin": u["is_admin"],
                "created_at": u["created_at"],
                "last_login_at": u["last_login_at"],
                "updated_at": u["updated_at"],
                "total": sum(ranks),
                **_rank_summary(ranks),
            }
        )

    counts = [p["count"] for p in per_user if p["count"]]
    summary = {
        "users": len(per_user),
        "savers": len(counts),
        "new_recent": sum(1 for u in targets if u["created_at"] >= recent),
        "saved_recent": sum(
            1 for p in per_user if p["count"] and p["updated_at"] >= recent
        ),
        "avg_count": sum(counts) / len(counts) if counts else None,
        "median_count": median(counts) if counts else None,
        "costume_total": len(costumes),
        "entries": len(all_ranks),
        "avg_rank": sum(all_ranks) / len(all_ranks) if all_ranks else None,
    }

    rank_hist = [
        {"label": bucket_label(lo, hi), "low": lo, "count": n}
        for (lo, hi), n in zip(RANK_BUCKETS, rank_histogram(all_ranks))
    ]

    # 新規利用者（初回ログイン）の日別件数。最初の利用者の日から今日まで
    # （日本時間）。日数が少なくても DAILY_MIN_DAYS 日分は並べる。
    today = now.astimezone(JST).date()
    created_days = [u["created_at"].astimezone(JST).date() for u in targets]
    daily_new = []
    if created_days:
        start = min(min(created_days), today - timedelta(days=DAILY_MIN_DAYS - 1))
        start = max(start, today - timedelta(days=DAILY_DAYS - 1))
        day = start
        while day <= today:
            daily_new.append(
                {
                    "date": day,
                    "count": sum(1 for d in created_days if d == day),
                }
            )
            day += timedelta(days=1)

    by_costume = []
    # 同じ生徒の衣装を合計した絆ランク（生徒は衣装の表示順で最初に出た順）
    ranks_by_student: dict[str, list[int]] = {}
    costumes_by_student: dict[str, int] = {}
    for c in costumes:
        ranks = ranks_by_costume[c["costume_id"]]
        by_costume.append(
            {
                "costume_id": c["costume_id"],
                "student_name": c["student_name"],
                "costume_name": c["costume_name"],
                "over50": sum(1 for r in ranks if r >= 50),
                "hist": rank_histogram(ranks),
                **_rank_summary(ranks),
            }
        )
        name = c["student_name"]
        ranks_by_student.setdefault(name, []).extend(ranks)
        costumes_by_student[name] = costumes_by_student.get(name, 0) + 1

    by_student = [
        {
            "student_name": name,
            "costumes": costumes_by_student[name],
            "over50": sum(1 for r in ranks if r >= 50),
            "hist": rank_histogram(ranks),
            **_rank_summary(ranks),
        }
        for name, ranks in ranks_by_student.items()
    ]

    return {
        "summary": summary,
        "rank_hist": rank_hist,
        "daily_new": daily_new,
        "by_costume": by_costume,
        "by_student": by_student,
        "users": per_user,
        "admin_excluded": len(users) - len(targets),
    }
