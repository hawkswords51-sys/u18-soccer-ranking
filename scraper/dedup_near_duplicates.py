#!/usr/bin/env python3
"""
近似重複チームの自動検出・除去スクリプト (v8)

新機能 (v7からの追加):
- 名前類似度判定に LCS (最長共通部分列) を追加
- 「日本福祉大学付属高校 vs 日福大付」のような略称マッチングにも対応
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
    if not name:
        return ""
    n = name.strip()
    for suffix in ["高校", "高等学校", "学校", "FC", "fc",
                   "U-18", "U18", "U-15", "U15", "ユース", "高等部",
                   "セカンド", "2nd", "サード", "3rd", "II", "III"]:
        n = n.replace(suffix, "")
    n = re.sub(r'[ABCＡＢＣ]$', '', n)
    n = re.sub(r'[\s・\-_()（）_\.]', '', n)
    return n


def lcs_length(s1, s2):
    """最長共通部分列の長さ (Longest Common Subsequence)"""
    m, n = len(s1), len(s2)
    if m == 0 or n == 0:
        return 0
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i-1] == s2[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
            else:
                dp[i][j] = max(dp[i-1][j], dp[i][j-1])
    return dp[m][n]


def names_similar(name1, name2):
    """2つのチーム名が類似しているか"""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    if not n1 or not n2:
        return False
    if len(n1) < 2 or len(n2) < 2:
        return False  # 短すぎる名前は誤判定回避

    # 部分文字列チェック
    if len(n1) >= 2 and n1 in n2:
        return True
    if len(n2) >= 2 and n2 in n1:
        return True

    # 連続2文字 (bigram) の共通部分
    bigrams1 = set(n1[i:i+2] for i in range(len(n1)-1))
    bigrams2 = set(n2[i:i+2] for i in range(len(n2)-1))
    if len(bigrams1 & bigrams2) >= 1:
        return True

    # ★ NEW: LCS ベースの類似度
    # 短い方の名前の60%以上が共通部分列なら類似と判定
    shorter = min(len(n1), len(n2))
    if shorter >= 3:
        lcs = lcs_length(n1, n2)
        if lcs / shorter >= 0.6:
            return True

    return False


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
    print("近似重複チーム検出・除去 開始 (v8)")
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
            grp.sort(key=lambda t: -len(t.get("name", "")))
            kept = grp[0]
            for t in grp[1:]:
                if not names_similar(kept.get("name", ""), t.get("name", "")):
                    print(f"  [SKIP-fp] {pref_id}/{league}: 統計一致だが名前異 "
                          f"({kept.get('name')} vs {t.get('name')})")
                    false_positive_warns += 1
                    continue
                print(f"  [DEDUP-stats] {pref_id}/{league}: 統計値完全一致 + 名前類似")
                print(f"    残: {kept.get('name')} ({kept.get('points', 0)}pt)")
                print(f"    削: {t.get('name')} ({t.get('points', 0)}pt)")
                teams_to_remove.append(t)

        remaining = [t for t in pref["teams"] if t not in teams_to_remove]

        # === Step 3: 同リーグ・名前類似 (統計が違っても合併) ===
        groups_by_league = {}
        for t in remaining:
            league = t.get("league") or ""
            if not league:
                continue
            groups_by_league.setdefault(league, []).append(t)

        for league, league_teams in groups_by_league.items():
            n_teams = len(league_teams)
            handled = set()
            for i in range(n_teams):
                if i in handled:
                    continue
                for j in range(i + 1, n_teams):
                    if j in handled:
                        continue
                    t1 = league_teams[i]
                    t2 = league_teams[j]
                    if t1 in teams_to_remove or t2 in teams_to_remove:
                        continue
                    # 階層が同じか確認
                    _, tier1 = get_base_and_tier(t1.get("name", ""))
                    _, tier2 = get_base_and_tier(t2.get("name", ""))
                    if tier1 != tier2:
                        continue
                    # 名前が類似しているか
                    if not names_similar(t1.get("name", ""), t2.get("name", "")):
                        continue
                    # 試合数が多い方を残す
                    if (t1.get("played", 0) or 0) >= (t2.get("played", 0) or 0):
                        kept, removed = t1, t2
                        idx_handled = j
                    else:
                        kept, removed = t2, t1
                        idx_handled = i
                    print(f"  [DEDUP-fuzzy] {pref_id}/{league}: 階層一致+名前類似")
                    print(f"    残: {kept.get('name')} ({kept.get('played',0)}試合, {kept.get('points',0)}pt)")
                    print(f"    削: {removed.get('name')} ({removed.get('played',0)}試合, {removed.get('points',0)}pt)")
                    teams_to_remove.append(removed)
                    handled.add(idx_handled)

        if teams_to_remove:
            pref["teams"] = [t for t in pref["teams"] if t not in teams_to_remove]
            total_removed += len(teams_to_remove)

        # === Step 4: 残った 11+ チームのリーグを警告 ===
        league_counts: dict = {}
        for t in pref.get("teams", []):
            lg = (t.get("league") or "").strip()
            if not lg:
                continue
            league_counts[lg] = league_counts.get(lg, 0) + 1

        for lg, cnt in league_counts.items():
            # 1部・F1・プレミア・プリンスは10チーム想定
            # 2部・F2は10〜12チーム、3部以下は12チーム以上もありうる
            is_top_tier = any(k in lg for k in ["1部", "F1", "プレミア", "プリンス"])
            threshold = 11 if is_top_tier else 13
            if cnt >= threshold:
                suspicious_leagues.append(f"{pref_id} / {lg}: {cnt}チーム")

    # === 結果を保存 ===
    if total_removed > 0:
        with TEAMS_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ teams.json を更新しました（{total_removed}チームを削除）")
    else:
        print("\nℹ️ 削除対象なし。teams.json は変更されません。")

    # === サマリー出力 ===
    print("\n" + "=" * 60)
    print(f"📊 dedup_near_duplicates v8 完了サマリー")
    print("=" * 60)
    print(f"  削除チーム数: {total_removed}")
    print(f"  安全スキップ（名前不一致で保護）: {safety_skipped}")
    print(f"  まだ要確認のリーグ数: {len(suspicious_leagues)}")
    if suspicious_leagues:
        print("\n⚠️ チーム数が想定より多いリーグ（手動確認推奨）:")
        for s in suspicious_leagues[:50]:
            print(f"    - {s}")
        if len(suspicious_leagues) > 50:
            print(f"    ... 他 {len(suspicious_leagues) - 50} 件")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
