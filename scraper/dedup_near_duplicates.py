#!/usr/bin/env python3
"""
近似重複チームの自動検出・除去スクリプト (v7)

新機能 (v6からの追加):
- 統計値マッチでも、名前の類似度をチェック
- 「ジェフU-18B」と「八千代高校」のような偶然の統計一致を防ぐ
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


def normalize_name(name):
    """名前を正規化 (類似度比較用)"""
    if not name:
        return ""
    n = name.strip()
    # サフィックス類を除去
    for suffix in ["高校", "高等学校", "学校", "FC", "fc",
                   "U-18", "U18", "U-15", "U15", "ユース", "高等部",
                   "セカンド", "2nd", "サード", "3rd", "II", "III"]:
        n = n.replace(suffix, "")
    # 末尾のA/B/Cを除去
    n = re.sub(r'[ABCＡＢＣ]$', '', n)
    # 空白・記号類を除去
    n = re.sub(r'[\s・\-_()（）_\.]', '', n)
    return n


def names_similar(name1, name2):
    """2つのチーム名が類似しているか (連続2文字以上の共通部分)"""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    if not n1 or not n2:
        return False
    # 一方がもう一方の部分文字列ならOK
    if len(n1) >= 2 and n1 in n2:
        return True
    if len(n2) >= 2 and n2 in n1:
        return True
    # 連続2文字 (bigram) の共通部分があるか
    bigrams1 = set(n1[i:i+2] for i in range(len(n1)-1))
    bigrams2 = set(n2[i:i+2] for i in range(len(n2)-1))
    return len(bigrams1 & bigrams2) >= 1


def stats_key(team):
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
    print("近似重複チーム検出・除去 開始 (v7)")
    print("=" * 70)

    total_removed = 0
    false_positive_warns = 0

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

        # === Step 2: 同リーグ・同統計値 + 名前類似 マッチ ===
        groups_stats = {}
        for t in remaining:
            league = t.get("league") or ""
            if not league:
                continue
            played = t.get("played", 0) or 0
            if played == 0:
                continue
            key = (league, stats_key(t))
            groups_stats.setdefault(key, []).append(t)

        for (league, stats), grp in groups_stats.items():
            if len(grp) <= 1:
                continue
            # 名前が長い順にソート
            grp.sort(key=lambda t: -len(t.get("name", "")))
            kept = grp[0]
            for t in grp[1:]:
                # ★ 安全チェック: 名前が類似しているか確認
                if not names_similar(kept.get("name", ""), t.get("name", "")):
                    print(f"  [SKIP-fp] {pref_id}/{league}: 統計一致だが名前が異なるため別チームと判断 "
                          f"({kept.get('name')} vs {t.get('name')})")
                    false_positive_warns += 1
                    continue
                print(f"  [DEDUP-stats] {pref_id}/{league}: 統計値完全一致 + 名前類似")
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
    if false_positive_warns:
        print(f"[安全弾き] 統計一致だが別チームと判定: {false_positive_warns} 件")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
