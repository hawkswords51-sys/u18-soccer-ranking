#!/usr/bin/env python3
"""
リーグ順位の再計算スクリプト

teams.json 内の各チームの leagueRank を、リーグごとに以下の優先順位で再計算：
    1. 勝点 (points) 降順
    2. 得失差 (goalsFor - goalsAgainst) 降順
    3. 得点 (goalsFor) 降順

同点・同得失差・同得点のチームは同順位を割り当て、次の順位はスキップする
（標準の競技順位方式）。

スクレイパーが順位を間違って割り当てた場合に、勝点ベースで正規化することで
表示が正しくなる。
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

    # リーグごとにチームを集計
    by_league = {}
    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        for t in pref["teams"]:
            league = t.get("league") or ""
            if not league:
                continue
            by_league.setdefault(league, []).append(t)

    # 各リーグ内で順位を再計算
    total_fixes = 0
    for league, teams in by_league.items():
        # 勝点降順 → 得失差降順 → 得点降順 でソート
        sorted_teams = sorted(teams, key=lambda t: (
            -(t.get("points", 0) or 0),
            -((t.get("goalsFor", 0) or 0) - (t.get("goalsAgainst", 0) or 0)),
            -(t.get("goalsFor", 0) or 0),
        ))
        # 順位を割り当て（同統計のチームは同順位、次は順位飛ばし）
        prev_stats = None
        prev_rank = 0
        for i, t in enumerate(sorted_teams):
            curr_stats = (
                t.get("points", 0) or 0,
                (t.get("goalsFor", 0) or 0) - (t.get("goalsAgainst", 0) or 0),
                t.get("goalsFor", 0) or 0,
            )
            if curr_stats == prev_stats:
                new_rank = prev_rank
            else:
                new_rank = i + 1
                prev_rank = new_rank
                prev_stats = curr_stats

            old_rank = t.get("leagueRank")
            old_rank2 = t.get("rank")
            if old_rank != new_rank:
                t["leagueRank"] = new_rank
                total_fixes += 1
            # 「rank」フィールドも持つ古いデータは併せて更新
            if "rank" in t and old_rank2 != new_rank:
                t["rank"] = new_rank

    # JSON 書き戻し
    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[OK] {total_fixes} 件のチーム順位を再計算しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
