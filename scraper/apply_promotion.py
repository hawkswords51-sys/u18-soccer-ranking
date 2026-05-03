#!/usr/bin/env python3
"""data/promotion_data.yml を読んで teams.json のリーグ所属を更新するスクリプト

毎年12月のプレミアリーグ参入戦の結果を promotion_data.yml に記入し、
このスクリプトを実行することで、翌年シーズンの teams.json のリーグ所属が
一括で書き換えられます。

使い方:
  python scraper/apply_promotion.py                  # 一覧表示
  python scraper/apply_promotion.py --season 2025-2026  # 特定seasonを適用
  python scraper/apply_promotion.py --season 2025-2026 --dry-run  # 適用前のプレビュー
"""
import argparse
import json
import sys
import unicodedata
from pathlib import Path

try:
    import yaml
except ImportError:
    print("❌ PyYAML が必要です: pip install pyyaml")
    sys.exit(1)

BASE = Path(__file__).parent.parent
PROM_FILE = BASE / "data" / "promotion_data.yml"
TEAMS_FILE = BASE / "data" / "teams.json"


def normalize_name(name):
    """teams.json 照合用の正規化"""
    if not name:
        return ""
    n = unicodedata.normalize("NFKC", name)
    return n.replace(" ", "").replace("　", "")


def find_team(name, teams_data):
    """teams.json でチームを検索 (name → aliases の順)"""
    target = normalize_name(name)
    if not target:
        return None
    for pref_id, info in teams_data.items():
        if pref_id == "_meta":
            continue
        for t in info.get("teams", []):
            if normalize_name(t.get("name", "")) == target:
                return (pref_id, t)
            for a in (t.get("aliases", []) or []):
                if normalize_name(a) == target:
                    return (pref_id, t)
    return None


def list_seasons(promotions):
    """promotion_data.yml の seasons 一覧表示"""
    print("=== promotion_data.yml に記録されている seasons ===")
    for p in promotions:
        season = p.get("season", "?")
        notes = p.get("notes", "")
        n_changes = len(p.get("changes", []) or [])
        print(f"  {season}  ({n_changes} 件の変更)  {notes}")
    print()


def apply_season(promotions, season_id, teams_data, dry_run=False):
    """指定 season の changes を teams.json に適用"""
    target_season = None
    for p in promotions:
        if p.get("season") == season_id:
            target_season = p
            break
    if not target_season:
        print(f"❌ season {season_id!r} が promotion_data.yml に見つかりません")
        return 1

    changes = target_season.get("changes", []) or []
    if not changes:
        print(f"⚠ season {season_id} に変更がありません")
        return 0

    print(f"=== {season_id} の変更を適用 ({len(changes)}件) ===\n")
    success = 0
    fail = 0
    not_found = []
    league_mismatch = []

    for c in changes:
        team_name = c.get("team", "")
        from_league = c.get("from", "")
        to_league = c.get("to", "")
        if not team_name or not from_league or not to_league:
            print(f"⚠ 不完全なエントリ: {c}")
            fail += 1
            continue

        result = find_team(team_name, teams_data)
        if not result:
            print(f"  ❌ {team_name!r}: チームが見つかりません (from={from_league} → to={to_league})")
            not_found.append(team_name)
            fail += 1
            continue

        pref_id, team = result
        cur_league = team.get("league", "")
        if cur_league != from_league:
            print(f"  ⚠ {team_name!r}: 現在のリーグが {cur_league!r} で、"
                  f"指定の from={from_league!r} と異なります → スキップ")
            league_mismatch.append((team_name, cur_league, from_league))
            fail += 1
            continue

        if dry_run:
            print(f"  [DRY-RUN] {pref_id}/{team.get('id'):<7} {team['name']!r} : {cur_league} → {to_league}")
        else:
            team["league"] = to_league
            print(f"  ✓ {pref_id}/{team.get('id'):<7} {team['name']!r} : {cur_league} → {to_league}")
        success += 1

    print(f"\n=== 結果: 成功 {success} / 失敗 {fail} ===")
    if not_found:
        print(f"\n[未発見チーム]")
        for n in not_found:
            print(f"  - {n}")
    if league_mismatch:
        print(f"\n[現リーグ不一致]")
        for n, cur, exp in league_mismatch:
            print(f"  - {n}: 現={cur!r}, 期待={exp!r}")

    return 0 if fail == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="プレミアリーグ参入戦結果を teams.json に適用")
    parser.add_argument("--season", type=str, help="適用する season (例: 2025-2026)")
    parser.add_argument("--dry-run", action="store_true", help="実際には保存せずプレビュー")
    args = parser.parse_args()

    if not PROM_FILE.exists():
        print(f"❌ {PROM_FILE} が見つかりません")
        return 1
    if not TEAMS_FILE.exists():
        print(f"❌ {TEAMS_FILE} が見つかりません")
        return 1

    with open(PROM_FILE, encoding="utf-8") as f:
        prom_yml = yaml.safe_load(f) or {}
    promotions = prom_yml.get("promotions", []) or []

    if not promotions:
        print("⚠ promotion_data.yml に promotions が記入されていません")
        print(f"  ファイル: {PROM_FILE}")
        print("  例:")
        print("    promotions:")
        print('      - season: "2025-2026"')
        print('        changes:')
        print('          - team: "○○高校"')
        print('            from: "プレミアEAST"')
        print('            to: "プリンスリーグ関東1部"')
        return 0

    if not args.season:
        list_seasons(promotions)
        print("適用するには --season <season名> を指定してください")
        return 0

    with open(TEAMS_FILE, encoding="utf-8") as f:
        teams_data = json.load(f)

    rc = apply_season(promotions, args.season, teams_data, dry_run=args.dry_run)

    if rc == 0 and not args.dry_run:
        # 再採番もしてから保存
        def lp(name):
            if not name:
                return 99
            if name.startswith("プレミア"):
                return 1
            if name.startswith("プリンス"):
                return 2
            return 3
        for pref, info in teams_data.items():
            if pref == "_meta":
                continue
            teams = info.get("teams", [])
            teams.sort(key=lambda t: (
                lp(t.get("league", "")),
                -(t.get("points", 0) or 0),
                -(t.get("goalDifference", t.get("goalDiff", 0)) or 0),
                -(t.get("goalsFor", 0) or 0),
                t.get("name", ""),
            ))
            for i, t in enumerate(teams, 1):
                t["prefectureRank"] = i
                t["rank"] = i
        with open(TEAMS_FILE, "w", encoding="utf-8") as f:
            json.dump(teams_data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ {TEAMS_FILE} に保存しました")

    return rc


if __name__ == "__main__":
    sys.exit(main())
