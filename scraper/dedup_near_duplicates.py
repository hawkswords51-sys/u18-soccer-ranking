#!/usr/bin/env python3
"""
近似重複チームの自動検出・除去スクリプト (v6)

v5 までの「ベース名+階層」マッチに加えて：
- 同リーグ・同統計値 (勝点・試合数・勝・分・負・得点・失点 全て一致) のチームを重複と判定
"""
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
TEAMS_FILE = BASE_DIR / "data" / "teams.json"


def get_base_and_tier(name):
    if not name:
        return ("", "first")
    n = name.strip()
    tier = "first"
    if re.search(r'(セカンド|2nd|2軍|II)', n):
        tier = "second"
        n = re.sub(r'(セカンド|2nd|2軍|II)', '', n)
    elif re.search(r'(サード|3rd|3軍|III)', n):
        tier = "third"
        n = re.sub(r'(サード|3rd|3軍|III)', '', n)
    else:
        m = re.search(r'[ABCＡＢＣ]$', n)
        if m:
            letter = m.group(0)
            if letter in ('A', 'Ａ'):
                tier = "first"
            elif letter in ('B', 'Ｂ'):
                tier = "second"
            elif letter in ('C', 'Ｃ'):
                tier = "third"
            n = n[:-1]
    for suffix in ["高校", "高等学校", "学校", "FC", "fc",
                   "U-18", "U18", "U-15", "U15",
                   "ユース", "高等部"]:
        n = n.replace(suffix, "")
    n = re.sub(r'[\s・\-_()（）]', '', n).strip()
    return (n, tier)


def stats_key(team):
    """同リーグ・同統計値の重複検出用キー"""
    return (
        team.get("points", 0) or 0,
        team.get("played", 0) or 0,
        team.get("won", 0) or 0,
        team.get("drawn", 0) or 0,
        team.get("lost", 0) or 0,
        team.get("goalsFor", 0) or 0,
        team.get("goalsAgainst", 0) or 0,
    )


def main():
    if not TEAMS_FILE.exists():
        print(f"[ERROR] {TEAMS_FILE} が見つかりません")
        return 1

    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))

    print("=" * 70)
    print("近似重複チーム検出・除去 開始 (v6)")
    print("=" * 70)

    total_removed = 0

    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue

        teams_to_remove = []

        # === Step 1: ベース名+階層マッチ ===
        groups_basetier = {}
        for t in pref["teams"]:
            league = t.get("league") or ""
            if not league:
                continue
            base, tier = get_base_and_tier(t.get("name", ""))
            if not base:
                continue
            groups_basetier.setdefault((league, base, tier), []).append(t)

        for (league, base, tier), grp in groups_basetier.items():
            if len(grp) <= 1:
                continue
            grp.sort(key=lambda t: (
                -(t.get("played", 0) or 0),
                -(t.get("points", 0) or 0),
            ))
            kept = grp[0]
            for t in grp[1:]:
                print(f"  [DEDUP-tier] {pref_id}/{league}: '{base}' / {tier}")
                print(f"    残: {kept.get('name')} ({kept.get('played', 0)}試合, {kept.get('points', 0)}pt)")
                print(f"    削: {t.get('name')} ({t.get('played', 0)}試合, {t.get('points', 0)}pt)")
                teams_to_remove.append(t)

        remaining = [t for t in pref["teams"] if t not in teams_to_remove]

        # === Step 2: 同リーグ・同統計値マッチ ===
        groups_stats = {}
        for t in remaining:
            league = t.get("league") or ""
            if not league:
                continue
            played = t.get("played", 0) or 0
            if played == 0:
                continue  # 未試合チームは対象外
            key = (league, stats_key(t))
            groups_stats.setdefault(key, []).append(t)

        for (league, stats), grp in groups_stats.items():
            if len(grp) <= 1:
                continue
            # 名前が長い方を残す (フルネームの可能性が高い)
            grp.sort(key=lambda t: -len(t.get("name", "")))
            kept = grp[0]
            for t in grp[1:]:
                print(f"  [DEDUP-stats] {pref_id}/{league}: 統計値完全一致 {stats}")
                print(f"    残: {kept.get('name')} ({kept.get('points', 0)}pt)")
                print(f"    削: {t.get('name')} ({t.get('points', 0)}pt)")
                teams_to_remove.append(t)

        if teams_to_remove:
            pref["teams"] = [t for t in pref["teams"] if t not in teams_to_remove]
            total_removed += len(teams_to_remove)

        # === Step 3: 残った 11+ チームのリーグを警告 ===
        league_counts = {}
        for t in pref["teams"]:
            lg = t.get("league") or ""
            if lg:
                league_counts[lg] = league_counts.get(lg, 0) + 1
        for lg, cnt in league_counts.items():
            if cnt >= 11:
                same_league = [t for t in pref["teams"] if t.get("league") == lg]
                print(f"  [STILL_SUSPICIOUS] {pref_id}/{lg}: {cnt} チーム")
                for idx, t in enumerate(same_league, 1):
                    gd = (t.get('goalsFor', 0) or 0) - (t.get('goalsAgainst', 0) or 0)
                    print(f"    {idx:2d}. {t.get('name','?')} | {t.get('points',0)}pt | "
                          f"{t.get('played',0)}試合 | GD={gd}")

    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 70)
    print(f"[完了] {total_removed} 件の重複チームを削除")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
