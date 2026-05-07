#!/usr/bin/env python3
"""
近似重複チームの自動検出・除去スクリプト (v5)

新機能:
- A/B/C/Ｂ等のアルファベット階層サフィックスを検出
- 不審なリーグ (11チーム以上) は全チーム名を詳細表示
"""
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
TEAMS_FILE = BASE_DIR / "data" / "teams.json"


def get_base_and_tier(name):
    """チーム名から (ベース名, 階層) のキーを取得"""
    if not name:
        return ("", "first")
    n = name.strip()

    tier = "first"

    # セカンド/2nd 系の検出
    if re.search(r'(セカンド|2nd|2軍|II)', n):
        tier = "second"
        n = re.sub(r'(セカンド|2nd|2軍|II)', '', n)
    elif re.search(r'(サード|3rd|3軍|III)', n):
        tier = "third"
        n = re.sub(r'(サード|3rd|3軍|III)', '', n)
    else:
        # 末尾の A/B/C (半角・全角) を階層と解釈
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

    # 一般的なサフィックス除去
    for suffix in ["高校", "高等学校", "学校", "FC", "fc",
                   "U-18", "U18", "U-15", "U15",
                   "ユース", "高等部"]:
        n = n.replace(suffix, "")

    n = re.sub(r'[\s・\-_()（）]', '', n).strip()
    return (n, tier)


def main():
    if not TEAMS_FILE.exists():
        print(f"[ERROR] {TEAMS_FILE} が見つかりません")
        return 1

    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))

    print("=" * 70)
    print("近似重複チーム検出・除去 開始 (v5)")
    print("=" * 70)

    total_removed = 0
    suspicious_leagues = []

    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue

        groups = {}
        for t in pref["teams"]:
            league = t.get("league") or ""
            if not league:
                continue
            base, tier = get_base_and_tier(t.get("name", ""))
            if not base:
                continue
            groups.setdefault((league, base, tier), []).append(t)

        teams_to_remove = []
        for (league, base, tier), grp in groups.items():
            if len(grp) <= 1:
                continue
            grp.sort(key=lambda t: (
                -(t.get("played", 0) or 0),
                -(t.get("points", 0) or 0),
            ))
            kept = grp[0]
            removed = grp[1:]
            print(f"  [DEDUP] {pref_id} / {league}: ベース='{base}' 階層='{tier}'")
            print(f"    残す  : {kept.get('name')} ({kept.get('played', 0)}試合, {kept.get('points', 0)}pt)")
            for t in removed:
                print(f"    削除 : {t.get('name')} ({t.get('played', 0)}試合, {t.get('points', 0)}pt)")
                teams_to_remove.append(t)

        if teams_to_remove:
            pref["teams"] = [t for t in pref["teams"] if t not in teams_to_remove]
            total_removed += len(teams_to_remove)

        # 重複削除後の各リーグ件数を確認
        league_counts = {}
        for t in pref["teams"]:
            lg = t.get("league") or ""
            if lg:
                league_counts[lg] = league_counts.get(lg, 0) + 1
        for lg, cnt in league_counts.items():
            if cnt >= 11:
                suspicious_leagues.append((pref_id, lg, cnt))
                # 不審なリーグの全チームを出力（後続診断用）
                same_league_teams = [t for t in pref["teams"] if t.get("league") == lg]
                print(f"  [STILL_SUSPICIOUS] {pref_id} / {lg}: {cnt} チーム")
                for idx, t in enumerate(same_league_teams, 1):
                    print(f"    {idx:2d}. {t.get('name', '?')} | "
                          f"{t.get('points', 0)}pt | {t.get('played', 0)}試合 | "
                          f"GD={(t.get('goalsFor', 0) or 0) - (t.get('goalsAgainst', 0) or 0)}")

    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 70)
    print(f"[完了] {total_removed} 件の重複チームを削除")
    if suspicious_leagues:
        print(f"[警告] 削除後もまだ 11 チーム以上ある不審なリーグ: {len(suspicious_leagues)} 件")
        for pref, lg, n in suspicious_leagues:
            print(f"  - {pref} / {lg}: {n} チーム")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
