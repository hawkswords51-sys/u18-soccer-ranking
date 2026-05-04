#!/usr/bin/env python3
"""
data/teams.json から重複エントリと空チームを削除するクリーンアップスクリプト。

機能:
    1) MANUAL_RENAMES に基づき canonical エントリの名前を補正
       (例: "日大藤沢高校2nd" → "日本大学藤沢高校2nd")
    2) MANUAL_ALIAS_ADDITIONS に基づき canonical エントリに alias を追加
       (例: "湘南工科大学附属高校" の aliases に "湘南工科大附Ａ" を追加)
    3) 各チームの aliases リストを見て、その alias 名で別エントリが
       存在したら削除する (canonical 側は残す)
    4) (--remove-empty 指定時) played=0 かつ leagueRank>=90 のチームを削除
    5) 削除後に prefectureRank と rank を 1..N で振り直す

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


# =====================================================================
# 手動補正テーブル ★ 新しい補正が必要になったらここに追記 ★
# =====================================================================

# canonical エントリの名前を変更する。
# {(都道府県ID, 旧名): 新名}
# 用途: スクレイパーが拾ってくる略称ではなく、こちらで使う正式名に統一したい場合
MANUAL_RENAMES: dict[tuple[str, str], str] = {
    ("kanagawa", "日大藤沢高校2nd"): "日本大学藤沢高校2nd",
}

# canonical エントリに alias を追加する。
# {(都道府県ID, canonical名): [追加するalias配列]}
# 用途: スクレイパーが別表記で拾ってきても重複検出されるよう alias を増やしておく
MANUAL_ALIAS_ADDITIONS: dict[tuple[str, str], list[str]] = {
    # 湘南工科大附Ａ は湘南工科大学附属高校の別表記
    ("kanagawa", "湘南工科大学附属高校"): ["湘南工科大附Ａ", "湘南工科大附A"],
    # rename 後の "日本大学藤沢高校2nd" にも旧名を alias として登録
    ("kanagawa", "日本大学藤沢高校2nd"): ["日大藤沢高校2nd", "日大藤沢B"],
}


# =====================================================================
# 処理ロジック
# =====================================================================


def apply_manual_renames(prefectures: dict) -> int:
    """canonical エントリの名前を MANUAL_RENAMES に基づき書き換える。"""
    count = 0
    for (pref_id, old_name), new_name in MANUAL_RENAMES.items():
        pref = prefectures.get(pref_id)
        if not pref:
            continue
        for t in pref.get("teams", []):
            if t.get("name") == old_name:
                t["name"] = new_name
                count += 1
                print(f"  rename: [{pref_id}] '{old_name}' → '{new_name}'")
                break
    return count


def apply_manual_alias_additions(prefectures: dict) -> int:
    """canonical エントリの aliases に MANUAL_ALIAS_ADDITIONS の値を追加。"""
    count = 0
    for (pref_id, canonical), to_add in MANUAL_ALIAS_ADDITIONS.items():
        pref = prefectures.get(pref_id)
        if not pref:
            continue
        for t in pref.get("teams", []):
            if t.get("name") == canonical:
                existing = t.get("aliases", []) or []
                added = []
                for a in to_add:
                    if a not in existing:
                        existing.append(a)
                        added.append(a)
                if added:
                    t["aliases"] = existing
                    count += len(added)
                    print(f"  add aliases: [{pref_id}] '{canonical}' ← {added}")
                break
    return count


def find_alias_duplicates(prefectures: dict) -> list[tuple[str, str, str]]:
    """各都道府県内で、別チームの alias と同名のエントリを抽出。"""
    out = []
    for pref_id, pref in prefectures.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        teams = pref.get("teams", [])
        alias_to_main = {}
        for t in teams:
            for a in t.get("aliases", []) or []:
                alias_to_main[a] = t.get("name", "?")
        for t in teams:
            name = t.get("name", "")
            if name in alias_to_main and name != alias_to_main[name]:
                out.append((pref_id, name, alias_to_main[name]))
    return out


def find_empty_teams(prefectures: dict) -> list[tuple[str, str, str]]:
    """データなし (played=0 / leagueRank>=90) チームを抽出。"""
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
    """指定された (pref_id, team_name, ...) のチームを削除。"""
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
    """削除後に prefectureRank と rank を 1..N で振り直す。"""
    count = 0
    for pref_id, pref in prefectures.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        teams = pref.get("teams", [])
        teams.sort(
            key=lambda t: (
                t.get("rank", 99),
                t.get("leagueRank", 99),
            )
        )
        for i, t in enumerate(teams, 1):
            t["prefectureRank"] = i
            t["rank"] = i
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="実際に保存する")
    parser.add_argument("--remove-empty", action="store_true", help="データなしチームも削除")
    parser.add_argument("--no-renumber", action="store_true", help="連番振り直しをしない")
    args = parser.parse_args()

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    print("\n=== 手動補正 (rename) ===")
    renamed = apply_manual_renames(data)
    print(f"→ {renamed} 件 リネーム")

    print("\n=== 手動補正 (alias 追加) ===")
    aliased = apply_manual_alias_additions(data)
    print(f"→ {aliased} 件 alias 追加")

    print("\n=== エイリアス重複検出 ===")
    dups = find_alias_duplicates(data)
    print(f"→ {len(dups)} 件")
    for p, n, m in dups:
        print(f"  [{p}] '{n}'  (canonical: '{m}')")

    empties = []
    if args.remove_empty:
        print("\n=== データなしチーム検出 ===")
        empties = find_empty_teams(data)
        print(f"→ {len(empties)} 件")
        for p, n, l in empties:
            print(f"  [{p}] '{n}'  (league: {l})")

    targets = dups + empties
    print(f"\n→ 削除対象: 計 {len(targets)} 件")

    if not args.apply:
        print("\n[DRY RUN] 変更は保存していません。")
        print("実行するには --apply を付けてください:")
        print("  python scraper/cleanup_aliases.py --apply --remove-empty")
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
