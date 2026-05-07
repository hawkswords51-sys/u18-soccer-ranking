#!/usr/bin/env python3
"""
近似重複チームの自動検出・除去スクリプト

各都道府県内のリーグごとに「ベース名+階層」が同じチームを重複として検出し、
試合数の多いエントリ（=最新データ）を残して他を削除する。

例:
    尚志セカンド (12pt 6試合) ← 残す
    尚志高校2nd (9pt 5試合)  ← 削除
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
    n = name

    # 階層判定（先に判定して除去）
    tier = "first"
    if re.search(r'(セカンド|2nd|2軍|II)', n):
        tier = "second"
        n = re.sub(r'(セカンド|2nd|2軍|II)', '', n)
    elif re.search(r'(サード|3rd|3軍|III)', n):
        tier = "third"
        n = re.sub(r'(サード|3rd|3軍|III)', '', n)

    # 一般的なサフィックスを除去
    for suffix in ["高校", "高等学校", "学校", "FC", "fc",
                   "U-18", "U18", "U-15", "U15",
                   "ユース", "高等部"]:
        n = n.replace(suffix, "")

    # 空白・記号除去
    n = re.sub(r'[\s・\-_()（）]', '', n).strip()

    return (n, tier)


def main():
    if not TEAMS_FILE.exists():
        print(f"[ERROR] {TEAMS_FILE} が見つかりません")
        return 1

    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))

    print("=" * 70)
    print("近似重複チーム検出・除去 開始")
    print("=" * 70)

    total_removed = 0

    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue

        # 「リーグ+(ベース名,階層)」でグルーピング
        groups = {}
        for t in pref["teams"]:
            league = t.get("league") or ""
            if not league:
                continue
            base, tier = get_base_and_tier(t.get("name", ""))
            if not base:
                continue
            key = (league, base, tier)
            groups.setdefault(key, []).append(t)

        # 重複検出
        teams_to_remove = []
        for (league, base, tier), grp in groups.items():
            if len(grp) <= 1:
                continue
            # 試合数(played)降順 → 勝点降順 でソート
            grp.sort(key=lambda t: (
                -(t.get("played", 0) or 0),
                -(t.get("points", 0) or 0),
            ))
            kept = grp[0]
            removed = grp[1:]
            print(f"  [DEDUP] {pref_id} / {league}: ベース='{base}' 階層='{tier}'")
            print(f"    残す  : {kept.get('name')} "
                  f"({kept.get('played', 0)}試合, {kept.get('points', 0)}pt)")
            for t in removed:
                print(f"    削除 : {t.get('name')} "
                      f"({t.get('played', 0)}試合, {t.get('points', 0)}pt)")
                teams_to_remove.append(t)

        # 削除実行
        if teams_to_remove:
            pref["teams"] = [t for t in pref["teams"] if t not in teams_to_remove]
            total_removed += len(teams_to_remove)

    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 70)
    print(f"[完了] {total_removed} 件の重複チームを削除しました")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
