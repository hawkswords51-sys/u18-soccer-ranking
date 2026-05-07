#!/usr/bin/env python3
"""
data/teams.json から重複エントリと空チームを削除するクリーンアップスクリプト。

機能:
    1) MANUAL_RENAMES に基づき canonical エントリの名前を補正
    2) MANUAL_ALIAS_ADDITIONS に基づき canonical エントリに alias を追加
    3) 各チームの aliases リストを見て、その alias 名で別エントリが
       存在したら削除する (canonical 側は残す)
    4) (--remove-empty 指定時) played=0 かつ leagueRank>=90 のチームを削除
    5) 削除後に prefectureRank と rank と leagueRank を 1..N で振り直す
"""
import json
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "teams.json"

# =====================================================================
# 手動補正テーブル
# =====================================================================
MANUAL_RENAMES: dict[tuple[str, str], str] = {
    ("shizuoka", "藤枝明誠②"):       "藤枝明誠高校2nd",
    ("ibaraki",  "鹿島アントラーズユースB"): "鹿島アントラーズユース2nd",
    ("miyazaki", "テゲバジャーロ"): "テゲバジャーロ宮崎U-18",
    ("fukushima", "郡山商業高校"): "郡山高校",
    ("fukushima", "郡山高校"): "郡山商業高校",
    # ★ 福岡: canonical 不在のため rename で正式名にする
    ("fukuoka", "東福岡B"): "東福岡高校2nd",
    ("fukuoka", "アビスパ福岡B"): "アビスパ福岡U-18 2nd",
    # ★ 「B」「II」「C」表記 → 「高校2nd」「高校3rd」表記に統一
    ("tokyo", "帝京B"):           "帝京高校2nd",
    ("tokyo", "FC東京B"):         "FC東京U-18 2nd",
    ("chiba", "八千代"):           "八千代高校",
    ("saitama", "昌平II"):         "昌平高校2nd",
    ("saitama", "西武台II"):       "西武台高校2nd",
    ("ibaraki", "鹿島学園B"):      "鹿島学園高校2nd",
    ("shiga", "近江C"):            "近江高校3rd",
    ("osaka", "履正社B"):          "履正社高校2nd",
    ("hyogo", "滝川第二B"):        "滝川第二高校2nd",
    ("hyogo", "三田学園B"):        "三田学園高校2nd",
}

MANUAL_ALIAS_ADDITIONS: dict[tuple[str, str], list[str]] = {
    ("kanagawa", "湘南工科大学附属高校"):    ["湘南工科大附Ａ", "湘南工科大附A"],
    ("kanagawa", "日本大学藤沢高校2nd"):     ["日大藤沢高校2nd", "日大藤沢B"],
    ("tochigi", "栃木SC U-18 2nd"):          ["栃木SC U-18B", "栃木SC B"],
    ("tochigi", "文星芸術大学附属高校"):      ["文星芸大附"],
    ("shizuoka", "藤枝明誠高校2nd"):          ["藤枝明誠②", "藤枝明誠2nd"],
    ("fukushima", "帝京安積高校2nd"):         ["帝京安積セカンド"],
    ("fukushima", "学法石川高校2nd"):         ["学法石川セカンド"],
    ("ishikawa", "金沢学院大学附属高校2nd"):  ["金沢学院2nd"],
    ("ibaraki", "鹿島アントラーズユース2nd"): ["鹿島アントラーズユースB"],
    ("ibaraki", "明秀学園日立高校"):          ["明秀日立A"],
    ("gunma", "高崎健康福祉大学高崎高校"):    ["健大高崎"],
    ("gunma", "高崎経済大学附属高校"):        ["高経大附属"],
    ("tokyo", "帝京高校2nd"):                 ["帝京B"],
    ("tokyo", "FC東京U-18 2nd"):              ["FC東京B"],
    ("gifu", "帝京大学可児高校2nd"):          ["帝京可児B"],
    ("aichi", "名古屋グランパスU-18 2nd"):    ["グランパスB"],
    ("aichi", "日本福祉大学付属高校"):        ["日福大付"],
    ("shiga", "近江高校3rd"):                 ["近江C"],
    ("osaka", "履正社高校2nd"):               ["履正社B"],
    ("osaka", "興國高校2nd"):                 ["興國B"],
    ("osaka", "近畿大学附属高校"):            ["近大附属"],
    ("hyogo", "滝川第二高校2nd"):             ["滝川第二B"],
    ("hyogo", "三田学園高校2nd"):             ["三田学園B"],
    ("hyogo", "神戸科学技術高校"):            ["神戸科技A"],
    ("hyogo", "神戸国際附属高校"):            ["神戸国際附A"],
    ("hyogo", "神戸弘陵学園高校2nd"):         ["神戸弘陵B"],
    ("tottori", "米子北高校2nd"):             ["米子北B"],
    ("shimane", "大社高校2nd"):               ["大社B"],
    ("shimane", "立正大学淞南高校2nd"):       ["立正大淞南B"],
    ("okayama", "岡山学芸館高校2nd"):         ["岡山学芸館B"],
    ("okayama", "玉野光南高校2nd"):           ["玉野光南B"],
    ("okayama", "就実高校2nd"):               ["就実B"],
    ("okayama", "ファジアーノ岡山U-18 2nd"):  ["ファジ岡山U-18B"],
    ("okayama", "作陽学園高校2nd"):           ["作陽B"],
    ("chiba", "柏レイソルU-18 2nd"):          ["レイソルU-18B"],
    ("kyoto", "京都橘高校3rd"):               ["京都橘C"],
    ("kyoto", "東山高校2nd"):                 ["東山B"],
    ("hiroshima", "広島瀬戸内高校2nd"):       ["瀬戸内セカンド"],
    ("tokushima", "徳島商業高校2nd"):         ["徳島商業S"],
    ("tokushima", "徳島ヴォルティスユース2nd"): ["徳島ヴォルティスS"],
    ("tokushima", "徳島市立高校2nd"):         ["徳島市立S"],
    ("kagawa", "大手前高松高校2nd"):          ["大手前高松S"],
    ("kagawa", "カマタマーレ讃岐U-18 2nd"):   ["カマタマーレ讃岐S"],
    ("ehime", "愛媛FC U-18 2nd"):             ["愛媛FCU-18S", "愛媛FCU-18 S"],
    ("ehime", "FC今治U-18 2nd"):              ["FC今治U-18S"],
    ("ehime", "県立今治東中等教育学校 2nd"):  ["今治東S"],
    ("kochi", "高知高校2nd"):                 ["高知S"],
    ("fukuoka", "東福岡高校2nd"):             ["東福岡B"],
    ("fukuoka", "アビスパ福岡U-18 2nd"):      ["アビスパ福岡B"],
    ("fukuoka", "福岡大学附属若葉高校"):      ["福大若葉"],
    ("fukuoka", "福岡大学附属大濠高校"):      ["福大大濠"],
    ("fukuoka", "東海大学付属福岡高校2nd"):   ["東海大福岡B"],
    ("kumamoto", "熊本学園大学付属高校"):     ["学園大付"],
    ("kumamoto", "ロアッソ熊本U-18_2nd"):     ["ロアッソ2nd"],
    ("oita", "大分トリニータU-18_2nd"):       ["トリニータ2nd"],
    ("miyazaki", "宮崎日本大学高校"):         ["宮崎日大"],
}

# =====================================================================
# 処理ロジック
# =====================================================================
def apply_manual_renames(prefectures: dict) -> int:
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


def renumber_league_ranks(prefectures: dict) -> int:
    """削除後にリーグ内順位を 1..N で振り直す。
    プレミア・プリンスは複数県をまたぐのでグローバル処理。
    都道府県リーグは県内処理。
    並び順は points → 得失点差 → 得点 の降順。"""
    # ステップ1: 全チームをリーグ単位でグループ化
    groups: dict[tuple[str, str], list] = {}
    for pref_id, pref in prefectures.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        for t in pref.get("teams", []):
            lg = (t.get("league") or "").strip()
            if not lg:
                continue
            # ★ プレミア・プリンスは全国規模なので県をまたいで集計
            if "プレミア" in lg or "プリンス" in lg:
                key = ("__global__", lg)
            else:
                # 都道府県リーグは県内で集計
                key = (pref_id, lg)
            groups.setdefault(key, []).append(t)

    # ステップ2: 各リーグで並び替え + 連番
    leagues_renumbered = 0
    for key, lg_teams in groups.items():
        lg_teams.sort(
            key=lambda t: (
                -(t.get("points", 0) or 0),
                -((t.get("goalsFor", 0) or 0) - (t.get("goalsAgainst", 0) or 0)),
                -(t.get("goalsFor", 0) or 0),
            )
        )
        for i, t in enumerate(lg_teams, 1):
            t["leagueRank"] = i
        leagues_renumbered += 1
    return leagues_renumbered

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
        renum_pref = renumber_pref_ranks(data)
        print(f"県内連番振り直し: {renum_pref} 都道府県")
        renum_lg = renumber_league_ranks(data)
        print(f"リーグ内順位振り直し: {renum_lg} リーグ")

    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"保存: {DATA_FILE}")


if __name__ == "__main__":
    main()
