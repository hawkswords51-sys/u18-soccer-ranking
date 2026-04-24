#!/usr/bin/env python3
"""
古い誤 league 値のクリーンアップ (一回だけ実行するスクリプト)

背景:
    以前のスクレイパーのバグで、「藤枝明誠高校②」のような控えチームが
    「プリンスリーグ東海」など一軍リーグのラベルで誤って上書きされていた。
    新しい update.py (P1-6 双方向ブロック) でもう汚染は起きないが、
    既に付いてしまった古い league 値は自動では直らないため、
    ここで一回だけ手動クリーンアップする。

対象チームと現状 (ユーザー確認済み 2026-04-24):
    [shizuoka] 藤枝明誠高校②    → プリンスリーグ東海     (本来は 静岡県Aリーグ)
    [nagano]   市立長野高校       → プリンスリーグ北信越2部 (本来は 長野県1部)
    [toyama]   富山東高校         → プリンスリーグ北信越1部 (本来は 富山県1部 相当)
    [toyama]   龍谷富山高校       → プリンスリーグ北信越1部 (本来は 富山県1部 相当)
    [niigata]  東京学館新潟高校   → プリンスリーグ北信越1部 (本来は 新潟県1部)

処理:
    各チームが所属する都道府県内で、**最もよく使われている「県リーグ名」**を
    自動検出して、その名前に置き換える。teams.json 内で他のチームがどう
    表記しているか(「静岡県Aリーグ」「長野県1部」など)に揃える形。

使い方:
    cd <repo>
    python scraper/cleanup_legacy_league.py          # 確認モード (変更を保存しない)
    python scraper/cleanup_legacy_league.py --apply  # 実際に保存
"""
import json
import argparse
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "teams.json"

# (都道府県ID, チーム名) のリスト ― 誤 league が残っているチーム
TARGETS: list[tuple[str, str]] = [
    ("shizuoka", "藤枝明誠高校②"),
    ("nagano",   "市立長野高校"),
    ("toyama",   "富山東高校"),
    ("toyama",   "龍谷富山高校"),
    ("niigata",  "東京学館新潟高校"),
]


def most_common_pref_league(pref: dict) -> str | None:
    """
    その都道府県内で最も多く使われている「県リーグ名」を返す。
    プリンスリーグ / プレミアリーグ は除外する。
    """
    counter: Counter[str] = Counter()
    for t in pref.get("teams", []):
        lg = (t.get("league") or "").strip()
        if not lg:
            continue
        if "プリンスリーグ" in lg or "プレミアリーグ" in lg:
            continue
        counter[lg] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def main() -> int:
    parser = argparse.ArgumentParser(description="古い誤 league 値をクリーンアップする")
    parser.add_argument("--apply", action="store_true",
                        help="実際に teams.json に保存する (省略時は確認のみ)")
    args = parser.parse_args()

    print(f"データファイル: {DATA_FILE}")
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    changes: list[tuple[str, str, str, str]] = []  # (pref, name, old, new)

    for pref_id, target_name in TARGETS:
        pref = data.get(pref_id, {})
        if not pref:
            print(f"  ⚠ [{pref_id}] 都道府県データが見つかりません")
            continue

        new_league = most_common_pref_league(pref)
        if not new_league:
            print(f"  ⚠ [{pref_id}] 県リーグ名を検出できませんでした (スキップ)")
            continue

        found = False
        for team in pref.get("teams", []):
            if team.get("name") != target_name:
                continue
            found = True
            old = team.get("league")
            if not ("プリンスリーグ" in (old or "") or "プレミアリーグ" in (old or "")):
                print(f"  - [{pref_id}] {target_name}: 既に県リーグ '{old}' です (変更不要)")
                break
            changes.append((pref_id, target_name, old or "", new_league))
            team["league"] = new_league
            break

        if not found:
            print(f"  ⚠ [{pref_id}] チーム '{target_name}' が見つかりません")

    print("\n===== 修正プレビュー =====")
    if not changes:
        print("  変更対象なし")
        return 0
    for pref_id, name, old, new in changes:
        print(f"  ✓ [{pref_id}] {name}")
        print(f"      {old!r} → {new!r}")

    if not args.apply:
        print(f"\n[確認モード] {len(changes)} 件の変更が見つかりました")
        print("実際に保存するには --apply を付けて再実行してください:")
        print("    python scraper/cleanup_legacy_league.py --apply")
        return 0

    # 保存
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 完了: {len(changes)} 件の league 値を修正して保存しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
