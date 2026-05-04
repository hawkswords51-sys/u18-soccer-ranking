#!/usr/bin/env python3
"""
data/teams.json から「エイリアスの重複エントリ」と「空データ・チーム」を削除する
クリーンアップスクリプト。

背景:
    自動スクレイピングが、既に aliases として登録されているチーム名
    (例: "桐光学園B" は "桐光学園高校2nd" の alias) を別エントリとして
    追加してしまうため、重複が発生する。

    また、JFA順位表に載っているがまだ試合データが無いチーム
    (played=0, leagueRank=99) は「99位」と表示されてしまうため、
    表示が見苦しくなる。

このスクリプトの動作:
    1) 重複削除モード (デフォルト)
       各チームの aliases リストを見て、その alias 名で別エントリが
       存在したら削除する。aliases を持つ canonical 側は残す。

    2) 空チーム削除モード (--remove-empty オプション)
       played=0 かつ won=0 かつ lost=0 かつ leagueRank>=90 のチームを削除。

使い方:
    cd <repo-root>
    python scraper/cleanup_aliases.py            # 確認モード (変更しない)
    python scraper/cleanup_aliases.py --apply    # 重複だけ削除
    python scraper/cleanup_aliases.py --apply --remove-empty   # 重複 + 空チーム削除
"""
import json
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "teams.json"


def find_alias_duplicates(prefectures: dict) -> list[tuple[str, str, str]]:
    """各都道府県内で、別チームの alias と同名のエントリを抽出。
    Returns: [(pref_id, duplicate_team_name, canonical_team_name), ...]
    """
    out = []
    for pref_id, pref in prefectures.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        teams = pref.get("teams", [])
        # alias -> canonical name のマップ作成
        alias_to_main = {}
        for t in teams:
            for a in t.get("aliases", []) or []:
                alias_to_main[a] = t.get("name", "?")
        # 重複検出
        for t in teams:
            name = t.get("name", "")
            if name in alias_to_main and name != alias_to_main[name]:
                out.append((pref_id, name, alias_to_main[name]))
    return out


def find_empty_teams(prefectures: dict) -> list[tuple[str, str, str]]:
    """データなし (played=0 / leagueRank>=90) チームを抽出。
    Returns: [(pref_id, team_name, league), ...]
    """
    out = []
    for pref_id, pref in prefectures.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        for t in pref.get("teams", []):
            if (
                t.get("played", 0) == 0
                and t.get("won", 0) == 0
                and t.get("lost", 0) == 0
                and t.get("drawn", 0) == 0
                and t.get("leagueRank", 0) >= 90
            ):
                out.append((pref_id, t.get("name", "?"), t.get("league", "?")))
    return out


def remove_teams(prefectures: dict, targets: list[tuple[str, str, str]]) -> int:
    """指定された (pref_id, team_name, ...) のチームを削除。
    Returns: 削除した件数。
    """
    target_set = {(p, n) for (p, n, *_rest) in targets}
    removed = 0
    for pref_id, pref in prefectures.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        original = pref["teams"]
        kept = [t for t in original if (pref_id, t.get("name", "")) not in target_set]
        if len(kept) != len(original):
            removed += len(original) - len(kept)
            pref["teams"] = kept
    return removed


def renumber_pref_ranks(prefectures: dict) -> int:
    """削除後に prefectureRank と rank を 1..N で振り直す (連番が綺麗になる)。
    Returns: 振り直した都道府県数。"""
    count = 0
    for pref_id, pref in prefectures.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        teams = pref.get("teams", [])
        # 既存の rank 順 (もしくは leagueRank) でソートして連番に振り直す
        teams.sort(
            key=lambda t: (
                t.get("rank", 99),
                t.get("leagueRank", 99),
            )
        )
        for i, t in enumerate(teams, 1):
            t["prefectureRank"] = i
            t["rank"] = i  # rank も連番に揃える
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="実際に保存する (指定しないと dry-run)")
    parser.add_argument("--remove-empty", action="store_true", help="データなしチームも削除")
    parser.add_argument("--no-renumber", action="store_true", help="削除後の連番振り直しをしない")
    args = parser.parse_args()

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    # 検出
    dups = find_alias_duplicates(data)
    print(f"\n=== エイリアス重複: {len(dups)}件 ===")
    for p, n, m in dups:
        print(f"  [{p}] '{n}'  (canonical: '{m}')")

    empties = []
    if args.remove_empty:
        empties = find_empty_teams(data)
        print(f"\n=== データなしチーム: {len(empties)}件 ===")
        for p, n, l in empties:
            print(f"  [{p}] '{n}'  (league: {l})")

    targets = dups + empties
    print(f"\n→ 削除対象: 計 {len(targets)} 件")

    if not args.apply:
        print("\n[DRY RUN] 変更は保存していません。")
        print("実行するには --apply を付けてください:")
        print("  python scraper/cleanup_aliases.py --apply")
        if not args.remove_empty:
            print("  python scraper/cleanup_aliases.py --apply --remove-empty  # 空チームも削除")
        return

    removed = remove_teams(data, targets)
    print(f"\n削除しました: {removed} 件")

    if not args.no_renumber:
        renum = renumber_pref_ranks(data)
        print(f"連番振り直し: {renum} 都道府県")

    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"保存: {DATA_FILE}")


if __name__ == "__main__":
    main()
