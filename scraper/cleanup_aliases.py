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
    # 神奈川県: 「日大」→「日本大学」表記に統一
    ("kanagawa", "日大藤沢高校2nd"): "日本大学藤沢高校2nd",
    # 栃木県: 「U-18B」→「U-18 2nd」表記に統一
    ("tochigi",  "栃木SC U-18B"):    "栃木SC U-18 2nd",
    # 静岡県: 「②」→「高校2nd」表記に統一
    ("shizuoka", "藤枝明誠②"):       "藤枝明誠高校2nd",
    # 茨城県: 鹿島アントラーズユースB は canonical 不在。
    # トップが「鹿島アントラーズユース」(Premier EAST) なので 2nd 表記に統一
    ("ibaraki",  "鹿島アントラーズユースB"): "鹿島アントラーズユース2nd",
    # 宮崎県: 「テゲバジャーロ」→「テゲバジャーロ宮崎U-18」に正式名称化
    ("miyazaki", "テゲバジャーロ"): "テゲバジャーロ宮崎U-18",
    # 福島県: 郡山高校と郡山商業高校のデータがスワップされていた
    ("fukushima", "郡山商業高校"): "郡山高校",
    ("fukushima", "郡山高校"): "郡山商業高校",
}

# canonical エントリに alias を追加する。
# {(都道府県ID, canonical名): [追加するalias配列]}
# 用途: スクレイパーが別表記で拾ってきても重複検出されるよう alias を増やしておく
MANUAL_ALIAS_ADDITIONS: dict[tuple[str, str], list[str]] = {
    # === 神奈川県 ===
    ("kanagawa", "湘南工科大学附属高校"):    ["湘南工科大附Ａ", "湘南工科大附A"],
    ("kanagawa", "日本大学藤沢高校2nd"):     ["日大藤沢高校2nd", "日大藤沢B"],
    # === 栃木県 ===
    ("tochigi", "栃木SC U-18 2nd"):         ["栃木SC U-18B", "栃木SC B"],
    # === 静岡県 ===
    ("shizuoka", "藤枝明誠高校2nd"):         ["藤枝明誠②", "藤枝明誠2nd"],
    # === 福島県 ===
    ("fukushima", "帝京安積高校2nd"):        ["帝京安積セカンド"],
    ("fukushima", "学法石川高校2nd"):        ["学法石川セカンド"],
    # === 石川県 ===
    ("ishikawa", "金沢学院大学附属高校2nd"): ["金沢学院2nd"],
    # === 茨城県 ===
    # rename 後の「鹿島アントラーズユース2nd」に旧表記をalias登録
    ("ibaraki", "鹿島アントラーズユース2nd"): ["鹿島アントラーズユースB"],
    # 明秀学園日立高校 の表記揺れ
    ("ibaraki", "明秀学園日立高校"):         ["明秀日立A"],
    # === 東京都 ===
    ("tokyo", "帝京高校2nd"):                ["帝京B"],
    ("tokyo", "FC東京U-18 2nd"):             ["FC東京B"],
    # === 滋賀県 ===
    ("shiga", "近江高校3rd"):                ["近江C"],
    # === 大阪府 ===
    ("osaka", "履正社高校2nd"):              ["履正社B"],
    ("osaka", "興國高校2nd"):                ["興國B"],
    # === 兵庫県 ===
    ("hyogo", "滝川第二高校2nd"):            ["滝川第二B"],
    ("hyogo", "三田学園高校2nd"):            ["三田学園B"],
    # === 鳥取県 ===
    ("tottori", "米子北高校2nd"):            ["米子北B"],
    # === 島根県 ===
    ("shimane", "大社高校2nd"):              ["大社B"],
    # === 岡山県 (高校なしのB表記もキャッチ) ===
    ("okayama", "岡山学芸館高校2nd"):        ["岡山学芸館B"],
    ("okayama", "玉野光南高校2nd"):          ["玉野光南B"],
    ("okayama", "就実高校2nd"):              ["就実B"],
    # === 千葉県 (大文字U の異字体) ===
    ("chiba", "柏レイソルU-18 2nd"):         ["レイソルU-18B"],
    # === 京都府 (高校なしのC表記もキャッチ) ===
    ("kyoto", "京都橘高校3rd"):              ["京都橘C"],
    ("kyoto", "東山高校2nd"):                ["東山B"],
    # === 広島県 ===
    ("hiroshima", "広島瀬戸内高校2nd"):      ["瀬戸内セカンド"],
    # === 徳島県 ===
    ("tokushima", "徳島商業高校2nd"):        ["徳島商業S"],
    ("tokushima", "徳島ヴォルティスユース2nd"): ["徳島ヴォルティスS"],
    # === 香川県 ===
    ("kagawa", "大手前高松高校2nd"):         ["大手前高松S"],
    ("kagawa", "カマタマーレ讃岐U-18 2nd"):  ["カマタマーレ讃岐S"],
    # === 愛媛県 (スペースなし表記) ===
    ("ehime", "愛媛FC U-18 2nd"):            ["愛媛FCU-18S", "愛媛FCU-18 S"],
    # === 高知県 ===
    ("kochi", "高知高校2nd"):                ["高知S"],
    # === 福岡県 ===
    ("fukuoka", "東福岡高校2nd"):            ["東福岡B"],
    ("fukuoka", "アビスパ福岡U-18 2nd"):     ["アビスパ福岡B"],
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
