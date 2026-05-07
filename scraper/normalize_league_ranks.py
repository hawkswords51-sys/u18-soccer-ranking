#!/usr/bin/env python3
"""
リーグ順位の安全な再計算スクリプト (v2)

teams.json の各都道府県内のみで リーグごとに順位を再計算する。
都道府県を跨いだ集計はしないため、データの混入が発生しない。

ロジック:
    - 各都道府県内のチームを league フィールドで分類
    - 勝点 > 得失差 > 得点 でソート
    - 1, 2, 3...N の順番で順位を割り振る（独立した順位、同点も独立）
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

    total_fixes = 0
    pref_count = 0
    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        pref_count += 1

        # この都道府県内のチームを「league 名」で分類
        by_league = {}
        for t in pref["teams"]:
            league = t.get("league") or ""
            if not league:
                continue
            by_league.setdefault(league, []).append(t)

        # 各リーグ内で順位を再計算 (この都道府県内のみ)
        for league, teams in by_league.items():
            # 勝点 → 得失差 → 得点 で降順ソート
            sorted_teams = sorted(teams, key=lambda t: (
                -(t.get("points", 0) or 0),
                -((t.get("goalsFor", 0) or 0) - (t.get("goalsAgainst", 0) or 0)),
                -(t.get("goalsFor", 0) or 0),
            ))
            # 1, 2, 3... と独立した順位を割り振る
            for i, t in enumerate(sorted_teams):
                new_rank = i + 1
                old_rank = t.get("leagueRank")
                if old_rank != new_rank:
                    t["leagueRank"] = new_rank
                    total_fixes += 1
                # 「rank」フィールドも併せて更新
                if "rank" in t and t.get("rank") != new_rank:
                    t["rank"] = new_rank

    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[OK] {pref_count} 都道府県中、{total_fixes} 件のチーム順位を再計算")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
