#!/usr/bin/env python3
"""
近似重複チームの自動検出・除去スクリプト (v9 安全版)
v8 の Step 3 (fuzzy match) は誤検出が多すぎたため無効化。
Step 1 (ベース名+階層完全一致) と Step 2 (統計値完全一致+名前類似) のみ実行。
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


def names_similar_strict(name1, name2):
    """v9: 統計値完全一致のときだけ使う厳しめ判定。
    地域名だけが共通する別チームの誤マージを防ぐ。"""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    if not n1 or not n2:
        return False
    if len(n1) < 2 or len(n2) < 2:
        return False
    # 完全一致
    if n1 == n2:
        return True
    # 短い方が長い方に完全に含まれる（略称対応）
    shorter, longer = (n1, n2) if len(n1) <= len(n2) else (n2, n1)
    # 短い方が3文字以上で、長い方に部分文字列として含まれていれば類似とみなす
    if len(shorter) >= 3 and shorter in longer:
        return True
    # 連続する3文字（trigram）が共通する場合
    if len(shorter) >= 3:
        trigrams1 = set(n1[i:i+3] for i in range(len(n1)-2))
        trigrams2 = set(n2[i:i+3] for i in range(len(n2)-2))
        common = trigrams1 & trigrams2
        # 短い方の trigram の半分以上が共通していれば類似
        shorter_trigrams = min(len(trigrams1), len(trigrams2))
        if shorter_trigrams > 0 and len(common) / shorter_trigrams >= 0.5:
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
    print("近似重複チーム検出・除去 開始 (v9 安全版)")
    print("=" * 70)

    total_removed = 0
    false_positive_warns = 0
    suspicious_leagues = []

    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        teams_to_remove = []

        # === Step 1: ベース名+階層完全マッチ（同じ学校の重複登録を除去）===
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

        # === Step 2: 同リーグ・統計値完全一致 + 名前類似（厳しめ判定）===
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
                if not names_similar_strict(kept.get("name", ""), t.get("name", "")):
                    print(f"  [SKIP-fp] {pref_id}/{league}: 統計一致だが名前異 "
                          f"({kept.get('name')} vs {t.get('name')})")
                    false_positive_warns += 1
                    continue
                print(f"  [DEDUP-stats] {pref_id}/{league}: 統計値完全一致 + 名前類似")
                print(f"    残: {kept.get('name')} ({kept.get('points', 0)}pt)")
                print(f"    削: {t.get('name')} ({t.get('points', 0)}pt)")
                teams_to_remove.append(t)

        # === Step 3 (fuzzy match) は v9 で無効化 ===
        # 地域名の共通だけで別チームを誤マージする問題があったため削除。
        # 残った重複は cleanup_aliases.py の MANUAL_RENAMES で対応する。

        if teams_to_remove:
            pref["teams"] = [t for t in pref["teams"] if t not in teams_to_remove]
            total_removed += len(teams_to_remove)

        # === Step 4: 残った 11+ チームのリーグを警告（手動確認用）===
        league_counts = {}
        for t in pref.get("teams", []):
            lg = (t.get("league") or "").strip()
            if not lg:
                continue
            league_counts[lg] = league_counts.get(lg, 0) + 1

        for lg, cnt in league_counts.items():
            is_top_tier = any(k in lg for k in ["1部", "F1", "プレミア", "プリンス"])
            threshold = 11 if is_top_tier else 13
            if cnt >= threshold:
                suspicious_leagues.append(f"{pref_id} / {lg}: {cnt}チーム")

    # === 結果を保存 ===
    if total_removed > 0:
        with TEAMS_FILE.open("w", encoding="utf-8") as f:
            json.dump(teams_data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ teams.json を更新しました（{total_removed}チームを削除）")
    else:
        print("\nℹ️ 削除対象なし。teams.json は変更されません。")

    # === サマリー出力 ===
    print("\n" + "=" * 60)
    print(f"📊 dedup_near_duplicates v9 完了サマリー")
    print("=" * 60)
    print(f"  削除チーム数: {total_removed}")
    print(f"  安全スキップ（名前不一致で保護）: {false_positive_warns}")
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
