#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data/teams.json の県内総合順位（prefectureRank / rank）を、県ページの表示と同じ並びで振り直す。

2026-09-13 新設。並べ替えのルールは scraper/pref_order.py の pref_sort_key が正本
（格 → 部 → リーグ内順位 → 勝点 → 得失点差 → 得点 → 名前）。

それまでは cleanup_aliases.renumber_pref_ranks() が (rank, leagueRank) で振っており、
同値のチームが配列順まかせで毎回入れ替わっていた（公開ページは生成時に並べ直すので正しかった）。

⚠️ ワークフローでは sync_teams_from_pref.py の**後ろ**、ページ生成の**前**に置くこと。
   県1部の leagueRank は sync_teams_from_pref.py で確定する。
ネットワークは使わない。

使い方:
    python scraper/renumber_pref_overall.py            # 振り直して保存
    python scraper/renumber_pref_overall.py --dry-run  # 保存せず件数だけ出す
"""
import argparse
import json
from pathlib import Path

from pref_order import pref_sort_key

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "teams.json"


def renumber(data: dict) -> tuple[int, int]:
    """県ごとに並べ替えて 1..N を振る。戻り値 = (変わった県数, prefectureRank が変わったチーム数)"""
    changed_prefs = changed_teams = 0
    for pref_id, pref in data.items():
        if pref_id == "_meta" or not isinstance(pref, dict) or "teams" not in pref:
            continue
        teams = pref.get("teams") or []
        teams.sort(key=pref_sort_key)
        n_changed = 0
        for i, t in enumerate(teams, 1):
            if t.get("prefectureRank") != i:
                n_changed += 1
            t["prefectureRank"] = i
            t["rank"] = i
        if n_changed:
            changed_prefs += 1
            changed_teams += n_changed
    return changed_prefs, changed_teams


def main() -> int:
    parser = argparse.ArgumentParser(
        description="teams.json の県内総合順位を、県ページの表示と同じ並びで振り直す")
    parser.add_argument("--dry-run", action="store_true",
                        help="保存せず件数だけ出す")
    args = parser.parse_args()

    original = DATA_FILE.read_text(encoding="utf-8")
    data = json.loads(original)
    n_prefs, n_teams = renumber(data)

    if args.dry_run:
        print(f"[DRY RUN] {n_prefs}県 / {n_teams}チームの県内順位が変わります。書き込みなし。")
        return 0

    new_text = json.dumps(data, ensure_ascii=False, indent=2)
    if new_text != original:
        DATA_FILE.write_text(new_text, encoding="utf-8")
    print(f"[完了] {n_prefs}県 / {n_teams}チームの県内順位を振り直しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
