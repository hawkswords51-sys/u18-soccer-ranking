#!/usr/bin/env python3
"""
リーグ順位の安全な再計算スクリプト (v4 - 詳細チーム一覧付き)

- 各都道府県内のみで リーグごとに再計算
- 11チーム以上の不審なリーグは全チーム名を出力

✅ leagueRank はもう触らない（2026-09-07 修正）
-----------------------------------------------
**このスクリプトは `rank` / `prefectureRank` の振り直しと診断ログだけを担当する。**

かつてはここで `leagueRank` も「県ごと・リーグごと」に振り直していた。ところが
**プレミアとプリンスは全国／地域で1つのリーグ**なので、県内で区切ると誤った順位になる。
例: 千葉にはプレミアEASTのチームが2つ（流通経済大柏=1位、柏レイソル=3位）いるが、
    県内だけを見ると「1位・2位」に書き換わってしまう。実測で24チーム中22チームが壊れた。

サイトが壊れていなかったのは、直後に走る `cleanup_aliases.py --apply` が leagueRank を
全国単位で振り直していたからだが、**その覆いは「県内順位を全国順位に直す」だけで
正しさを保証していなかった**（teams.json 自身の勝点から再計算しており、リーグJSONの
`official_standings.rank` を見ていない）。実際 2026-09-07 に、プリンス九州1部が koko へ
フォールバックして teams.json だけ古くなり、**東福岡と飯塚の順位が入れ替わって
公開されていた**（同じページの順位表と戦績表が食い違っていた）。

⚠️ **覆い隠されているから大丈夫、は成り立たない。** 覆っている側の実行順・処理内容が
   変わった瞬間に、誰も気づかないまま表に出る。

→ **leagueRank の出どころは `sync_teams_from_leagues.py`（プレミア・プリンス）と
   `sync_teams_from_pref.py`（県1部）に一本化した。どちらもリーグJSONの
   `official_standings.rank` を正本とする。ここでは書かない。**

⚠️ このスクリプトを消さないこと。`rank` / `prefectureRank` の振り直しと、
   11チーム以上の不審なリーグの検出ログは、いまも必要。
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
                # ⚠️ leagueRank はここでは書かない（県内で区切ると全国リーグが壊れる）。
                #    出どころは sync_teams_from_leagues.py / sync_teams_from_pref.py。
                if "rank" in t and t.get("rank") != new_rank:
                    t["rank"] = new_rank
                    rank_fixes += 1

    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 70)
    print(f"[完了] rank {rank_fixes} 件を再計算（leagueRank はここでは書きません）")
    print("  leagueRank の出どころは sync_teams_from_leagues.py / sync_teams_from_pref.py です。")
    if suspicious_leagues:
        print(f"[警告] 11チーム以上の不審なリーグ: {len(suspicious_leagues)} 件")
        for pref, lg, n in suspicious_leagues:
            print(f"  - {pref} / {lg}: {n} チーム")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
