#!/usr/bin/env python3
"""
リーグ順位の安全な再計算スクリプト (v4 - 詳細チーム一覧付き)

- 各都道府県内のみで リーグごとに再計算
- 11チーム以上の不審なリーグは全チーム名を出力
"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
TEAMS_FILE = BASE_DIR / "data" / "teams.json"


def main():
    if not TEAMS_FILE.exists():
        print(f"[ERROR] {TEAMS_FILE} が見つかりません")
        return 1

    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))

    print("=" * 70)
    print("リーグ順位再計算 開始 (v4 - 詳細診断)")
    print("=" * 70)

    total_fixes = 0
    suspicious_leagues = []

    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue

        by_league = {}
        for t in pref["teams"]:
            league = t.get("league") or ""
            if not league:
                continue
            by_league.setdefault(league, []).append(t)

        for league, teams in by_league.items():
            print(f"  {pref_id} / {league}: {len(teams)} チーム")

            # 11 チーム以上の不審なリーグは全チームを詳細出力
            if len(teams) >= 11:
                print(f"  ★ 不審 (11チーム以上) のため全チーム表示:")
                for idx, t in enumerate(teams, 1):
                    name = t.get("name", "?")
                    pts = t.get("points", 0) or 0
                    played = t.get("played", 0) or 0
                    won = t.get("won", 0) or 0
                    drawn = t.get("drawn", 0) or 0
                    lost = t.get("lost", 0) or 0
                    gf = t.get("goalsFor", 0) or 0
                    ga = t.get("goalsAgainst", 0) or 0
                    rank = t.get("leagueRank", "?")
                    print(f"    {idx:2d}. {name} | {pts}pt | {played}試合 ({won}勝{drawn}分{lost}負) | {gf}-{ga} | leagueRank={rank}")
                suspicious_leagues.append((pref_id, league, len(teams)))

            # 順位再計算
            sorted_teams = sorted(teams, key=lambda t: (
                -(t.get("points", 0) or 0),
                -((t.get("goalsFor", 0) or 0) - (t.get("goalsAgainst", 0) or 0)),
                -(t.get("goalsFor", 0) or 0),
            ))
            for i, t in enumerate(sorted_teams):
                new_rank = i + 1
                old_rank = t.get("leagueRank")
                if old_rank != new_rank:
                    t["leagueRank"] = new_rank
                    total_fixes += 1
                if "rank" in t and t.get("rank") != new_rank:
                    t["rank"] = new_rank

    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 70)
    print(f"[完了] 合計 {total_fixes} 件のチーム順位を再計算")
    if suspicious_leagues:
        print(f"[警告] 11チーム以上の不審なリーグ: {len(suspicious_leagues)} 件")
        for pref, lg, n in suspicious_leagues:
            print(f"  - {pref} / {lg}: {n} チーム")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
