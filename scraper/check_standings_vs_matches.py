#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
`official_standings` ⇄ 試合一覧 の突き合わせチェッカー（2026-09-18 新設）
=======================================================================
`data/league_matches/pref-*.json` の中にある**同じ事実の2か所**
 ・`official_standings`（出典の順位表をそのまま保存したもの）
 ・`matches` の消化分から計算した順位
が互いに矛盾していないかを見る。**読むだけで、何も書かない。**

なぜ要るか
----------
`update_pref_cross_tables.build_from_source` は**この検算が通らなければ書き込まない**設計だが、
**手でJSONを書くとその関門を迂回できてしまう**。2026-09-18に埼玉を手で更新したとき、
`matches` だけ 47→54 に直して `official_standings` を9/13前の版のまま残し、
同じページの中で「戦績表のマス＝54試合ぶん／順位表＝47試合ぶん」になる寸前だった。
→ **関門をスクリプトに出して、誰が書いても通せるようにする。**

📌 他の見張り（`audit_pref_freshness.py` / `check_fetch_status.py`）と同じ位置づけ。
📌 他の検算ゲートが「出典 ⇄ 出典」なのに対し、これは**「保存したJSONの中の2か所」**を見る別の軸。

使い方
------
  python scraper/check_standings_vs_matches.py                     # 全リーグ。食い違いがあれば終了コード1
  python scraper/check_standings_vs_matches.py --report            # 報告だけ。常に終了コード0
  python scraper/check_standings_vs_matches.py path/to/one.json    # そのファイルだけ（週1の手動取り込み用）
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from update_pref_cross_tables import recompute   # noqa: E402  ← 書き込む側と同じ計算を使う

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "league_matches"

# ⚠️ キー名が両側で違う。recompute() は `pts` を返し、official_standings は `points`。
#    さらに recompute() は `gd` を返さない（gf-ga で自分で出す）。
#    素直に繋ぐと**勝点だけ突き合わせが効かないまま「全項目一致」と出る**ので、
#    対応表をここ1か所に書いて、両側から同じ表を見る。
KEYS = [("played", "played"), ("won", "won"), ("drawn", "drawn"), ("lost", "lost"),
        ("gf", "gf"), ("ga", "ga"), ("pts", "points")]


def check_one(path: Path) -> tuple[list[str], list[str], int]:
    """1ファイルを見る → (食い違い, 名寄せのずれ, 突き合わせた項目数)"""
    data = json.loads(path.read_text(encoding="utf-8"))
    slug = path.stem
    rows = data.get("official_standings") or []
    if not rows:
        # 出典が機械可読な順位表を出していないリーグ（宮崎など）はここに来る。
        # **食い違いではない**ので終了コードは上げず、⚪️情報として1行出すだけ。
        return [], [f"⚪️ {slug}: official_standings が無い（突き合わせをスキップ）"], 0

    names = {t.get("name") for t in (data.get("teams") or []) if t.get("name")}
    played = [m for m in data.get("matches", [])
              if m.get("status") == "played" and m.get("hs") is not None and m.get("as") is not None]

    # ⚠️⚠️ recompute() は `teams` に無い名前の試合を**黙って捨てる**。
    #    名寄せがずれていると、試合が消えたぶん「順位表のほうが多い」という数値の食い違いに化けて、
    #    原因がデータなのか名寄せなのか区別がつかなくなる。**先に別立てで報告する。**
    dropped = [m for m in played if m["home"] not in names or m["away"] not in names]
    unknown = [r.get("team") for r in rows if r.get("team") not in names]

    misname = []
    for t in sorted(set(unknown)):
        misname.append(f"⚠ {slug}: 順位表のチーム「{t}」が teams[].name に無い（名寄せのずれ）")
    for m in dropped[:5]:
        bad = [x for x in (m["home"], m["away"]) if x not in names]
        misname.append(f"⚠ {slug}: 試合「{m['home']} vs {m['away']}」の {'/'.join(bad)} が "
                       f"teams[].name に無い → この試合は順位の計算から落ちる（名寄せのずれ）")
    if len(dropped) > 5:
        misname.append(f"⚠ {slug}: 同様に計算から落ちる試合が他に {len(dropped) - 5} 件")

    st = recompute(played, [r.get("team") for r in rows])
    diffs, checked = [], 0
    for r in rows:
        team = r.get("team")
        s = st.get(team)
        if s is None:
            continue                      # 上の misname で報告済み
        for src_key, off_key in KEYS:
            if off_key not in r:
                continue
            checked += 1
            if r[off_key] != s[src_key]:
                diffs.append(f"⚠ {slug}: {team}.{off_key} 順位表{r[off_key]} ≠ 試合から{s[src_key]}")
        if "gd" in r:
            checked += 1
            if r["gd"] != s["gf"] - s["ga"]:
                diffs.append(f"⚠ {slug}: {team}.gd 順位表{r['gd']} ≠ 試合から{s['gf'] - s['ga']}")
    return diffs, misname, checked


def main() -> int:
    parser = argparse.ArgumentParser(
        description="official_standings と試合一覧が矛盾していないかを見る（読むだけ）")
    parser.add_argument("paths", nargs="*",
                        help="見るJSON（省略すると data/league_matches/pref-*.json を全部）")
    parser.add_argument("--report", action="store_true",
                        help="報告だけ。食い違いがあっても終了コード0で終わる")
    args = parser.parse_args()

    targets = [Path(p) for p in args.paths] if args.paths else sorted(DIR.glob("pref-*.json"))
    if not targets:
        print("対象のJSONが見つかりません")
        return 0

    all_diffs, all_misname, checked, skipped = [], [], 0, 0
    for p in targets:
        if not p.exists():
            all_misname.append(f"⚠ {p}: ファイルが見つかりません")
            continue
        diffs, misname, n = check_one(p)
        all_diffs += diffs
        all_misname += misname
        checked += n
        if n == 0 and not diffs:
            skipped += 1

    print(f"=== 順位表 ⇄ 試合一覧 の突き合わせ（{len(targets)}リーグ・{checked}項目）===")
    # ⚠️ 名寄せのずれを**先に**出す。これがあると数値の食い違いはその結果でしかないことが多い。
    for line in all_misname:
        print("  " + line)
    for line in all_diffs:
        print("  " + line)

    ng = [x for x in all_misname if x.startswith("⚠")]
    if not all_diffs and not ng:
        print(f"  ✅ 食い違いなし"
              f"{f'（うち順位表が無くスキップ {skipped} リーグ）' if skipped else ''}")
        return 0
    print(f"\n--- 数値の食い違い {len(all_diffs)} 件 ／ 名寄せのずれ {len(ng)} 件 ---")
    print("  ※ JSONを手で書いたときは、保存の**前に**これを通すこと"
          "（build_from_source と同じ関門。手で書くと迂回できてしまう）")
    if args.report:
        print("  （--report のため終了コード0で終わります）")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
