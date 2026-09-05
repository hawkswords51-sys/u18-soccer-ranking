#!/usr/bin/env python3
"""
リーグ順位の安全な再計算スクリプト (v4 - 詳細チーム一覧付き)

- 各都道府県内のみで リーグごとに再計算
- 11チーム以上の不審なリーグは全チーム名を出力

⚠️ このスクリプトを単体で実行してはいけない（2026-09-05 調査で判明）
---------------------------------------------------------------
このスクリプトは「県ごと・リーグごと」に順位を振り直す。ところが**プレミアと
プリンスは全国／地域で1つのリーグ**なので、県内で区切ると誤った順位になる。
例: 千葉にはプレミアEASTのチームが2つ（流通経済大柏=1位、柏レイソル=3位）いるが、
    ここでは千葉の中だけを見るので「1位・2位」に書き換わってしまう。
実測では24チーム中22チームの leagueRank が壊れる。

**いまサイトが壊れていないのは、ワークフローでこの直後に走る
`cleanup_aliases.py --apply` が leagueRank を全国単位で振り直して直しているから。**
（update_rankings.yml のステップ順: 順位データを更新 → 近似重複を削除 →
  ★このスクリプト★ → 大会成績YAML → エイリアス重複・空チームを自動クリーンアップ）

したがって:
  - 単体で `python scraper/normalize_league_ranks.py` を実行して、その結果を
    そのままコミットしてはいけない。必ず `cleanup_aliases.py --apply --remove-empty`
    まで続けて実行すること。
  - ワークフローのステップ順を入れ替えるときは、この2つの前後関係を必ず保つこと。

根本的に直すには、ここで leagueRank を触らないようにするのが筋だが、
`cleanup_aliases.py` が県内順位(rank/prefectureRank)の並べ替えキーに leagueRank を
使っているため、直すと県内順位まで動いてしまい、かえって不自然な並び（第2チームが
上位リーグのチームより上に来る等）になるケースが出る。2026-09-05時点では
「現状維持＋この注意書き」を選んでいる。着手するなら cleanup_aliases.py の
renumber_pref_ranks() の並べ替えキーごと設計し直すこと。
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
    rank_fixes = 0      # [2026-09-05] rank の書き換えも数える。従来は leagueRank しか
                        # 数えていなかったので、rank を数百件書き換えていても
                        # 「合計 0 件」と表示され、ログが実態と食い違っていた。
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
                    rank_fixes += 1

    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 70)
    print(f"[完了] leagueRank {total_fixes} 件 / rank {rank_fixes} 件を再計算")
    print("⚠ このスクリプト単体ではプレミア・プリンスの leagueRank が県内順位に化けます。")
    print("  必ず続けて cleanup_aliases.py --apply --remove-empty を実行してください")
    print("  （ワークフローでは自動で実行されます）。")
    if suspicious_leagues:
        print(f"[警告] 11チーム以上の不審なリーグ: {len(suspicious_leagues)} 件")
        for pref, lg, n in suspicious_leagues:
            print(f"  - {pref} / {lg}: {n} チーム")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
