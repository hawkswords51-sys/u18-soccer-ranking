#!/usr/bin/env python3
"""
リーグ順位の安全な再計算スクリプト (v3 - 診断機能付き)

- 各都道府県内のみで リーグごとに再計算
- 重複チーム検出
- 詳細ログ出力（ワークフローのログで確認可能）
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

    print("=" * 60)
    print("リーグ順位再計算 開始")
    print("=" * 60)

    total_fixes = 0
    duplicate_warnings = 0

    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue

        # この都道府県のチームを「league 名」で分類
        by_league = {}
        for t in pref["teams"]:
            league = t.get("league") or ""
            if not league:
                continue
            by_league.setdefault(league, []).append(t)

        # 各リーグについて処理
        for league, teams in by_league.items():
            # 重複チーム検出
            seen_names = {}
            dup_in_this_league = []
            for t in teams:
                name = t.get("name", "")
                if name in seen_names:
                    dup_in_this_league.append(name)
                seen_names[name] = True
            
            if dup_in_this_league:
                print(f"  [WARN] {pref_id} {league}: 重複チーム検出 {dup_in_this_league}")
                duplicate_warnings += 1

            # 福島F1 など重要リーグの詳細ログ
            if len(teams) > 0:
                print(f"  {pref_id} / {league}: {len(teams)} チーム")

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
                if "rank" in t and t.get("rank") != new_rank:
                    t["rank"] = new_rank

    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 60)
    print(f"[完了] 合計 {total_fixes} 件のチーム順位を再計算")
    if duplicate_warnings > 0:
        print(f"[警告] {duplicate_warnings} リーグで重複チームを検出しました")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
