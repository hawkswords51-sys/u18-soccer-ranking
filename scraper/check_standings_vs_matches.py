#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
`official_standings` ⇄ 試合一覧 の突き合わせチェッカー（2026-09-18 新設）
=======================================================================
`data/league_matches/pref-*.json` の中にある**同じ事実の2か所**
 ・`official_standings`（⚠️ 名前に反して**出典の表そのものではない**。試合から再計算した値。下記）
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

⚠️⚠️⚠️ この検査が効く範囲（2026-09-18 に取り違えていたので明記する）
--------------------------------------------------------------------
`official_standings` は**出典の順位表そのものではない**。`build_from_source` が
`recompute(js_matches, teams)` で**試合から計算した値**を詰めている
（`update_pref_cross_tables.py` の `data["official_standings"] = meta["official"]`）。
出典の表と突き合わせる本物の関門は `build_from_source` の中にあり、**書き込む時点で**効いている。
ここに保存されるのはその後の派生物。

→ **この検査は `recompute(matches)` 同士を比べている場面がある。**

| 経路 | `official_standings` | `source_standings`（2026-09-19 新設） |
|---|---|---|
| 自動で書かれた直後 | **無意味**（`recompute` 同士） | 書き込み時に `build_from_source` が同じ検算を通しているので一致する |
| ⭐️ 自動のあと人が触った | 有効 | **有効。しかも「出典と違う」と言える**（`official_standings` は派生物なので「こちらの2か所が食い違う」までしか言えない） |
| 手書き（埼玉・鹿児島の訂正） | 有効（実測で捕まった） | 出典の表も手で入れたときだけ有効 |

📌 項目数は**表ごとに分けて出す**。`official_standings` 側は
   **原理的に0になるものを0だと言っている部分を含む**ので、件数の大きさを守備範囲の広さと読まないこと。
⚠️ **両方あるリーグは両方見る。**「`source_standings` を優先」にすると、
   `official_standings` が古いまま放置されても誰も見なくなる（＝この検査を作った理由が抜ける）。
⚠️ **やらないこと**：ここは `matches` と `official_standings` の整合しか見ない。
   **スコアが黙って書き換わったこと自体は見ていない**（それは出典の固有ID＝北海道の `srcId` を
   使う別の仕組みの担当。未実装）。
✅ 2026-09-19：**`official_standings` を統一するのではなく、別キー `source_standings` を並べて足した。**
   統一すると13リーグで列が減り（okinawa 9＝勝分敗なし／pts_gd 2＝得点・失点なし）、
   self の4リーグ（宮崎・新潟・岡山・徳島）は表そのものが無くなる。
   さらに `sync_teams_from_pref` が `official_standings` の**9列を teams.json に書き戻している**ので、
   県ページ上部の総合順位表が13リーグで列落ちする。**だから足すだけにした。**
   ⭐️ `source_standings` は**出典の並び順のまま**入る。
   ⚠️⚠️ **ただし「行順＝順位」ではなかった**（2026-09-19 実測。設計時の想定が外れた）。
      38リーグ中**16リーグで行順が順位になっていない**（星取表の行順。長野は3番目が11点・4番目が30点、
      岐阜は先頭が17点）。**`rank` 列を持つリーグでも行順とは限らない**（兵庫は先頭23点・3番目24点）。
      → **同着を戻す材料になるのは `rank` の値だけ。並び順は使えない。**
   ⚠️ `rank` を持つのは**7リーグ**（北海道・兵庫・三重・奈良・沖縄・大阪・和歌山）。
      2026-09-18 にソースを読んで「4本」と数えたが、**実物は7本**だった（読むだけでは外れる）。
      同着が見つかった長野は既定ゲートで `rank` が入らないので、**長野を直すには読み手の改修が要る**。
      ここでやったのは材料を残すところまで。

使い方
------
  python scraper/check_standings_vs_matches.py                     # 全リーグ。食い違いがあれば終了コード1
  python scraper/check_standings_vs_matches.py --report            # 報告だけ。常に終了コード0
  python scraper/check_standings_vs_matches.py path/to/one.json    # そのファイルだけ（週1の手動取り込み用）
"""
from __future__ import annotations
import argparse
import collections
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
OFFICIAL_KEYS = [("played", "played"), ("won", "won"), ("drawn", "drawn"), ("lost", "lost"),
                 ("gf", "gf"), ("ga", "ga"), ("pts", "points")]
# `source_standings`（出典の表そのもの）側。⚠️ **勝点のキー名が違う**（`points` ではなく `pts`）。
#    出典が持っていない列はそもそもキーが無いので `if off_key not in r: continue` で飛ぶ。
#    ⚠️ `rank` は比べない。recompute() は順位を返さないので、比べる相手が無い。
SOURCE_KEYS = [("played", "played"), ("won", "won"), ("drawn", "drawn"), ("lost", "lost"),
               ("gf", "gf"), ("ga", "ga"), ("pts", "pts")]

# ⚠️ **両方あるリーグは両方見る。**「source_standings があればそちらを優先」にしてはいけない。
#    優先にすると `official_standings` が古いまま放置されていても誰も見なくなる。
#    この検査を作った理由そのもの（2026-09-18 埼玉で matches だけ 47→54 に直して
#    順位表を9/13前のまま残した件）が抜け落ちる。**あるものは全部、独立に見る。**
TABLES = [("official_standings", OFFICIAL_KEYS, "保存した順位表"),
          ("source_standings", SOURCE_KEYS, "出典の表")]


def check_one(path: Path) -> tuple[list[str], list[str], dict]:
    """1ファイルを見る → (食い違い, 名寄せのずれ, {表の名前: 突き合わせた項目数})"""
    data = json.loads(path.read_text(encoding="utf-8"))
    slug = path.stem
    present = [(key, keymap, label) for key, keymap, label in TABLES if data.get(key)]
    if not present:
        # 出典が機械可読な順位表を出していないリーグ（宮崎など）はここに来る。
        # **食い違いではない**ので終了コードは上げず、⚪️情報として1行出すだけ。
        return [], [f"⚪️ {slug}: 突き合わせる順位表が無い（official_standings も source_standings も）"], {}

    # 名寄せのずれは表ごとに出すと重複するので、official_standings（全リーグにある）を代表にして1回だけ見る
    rows = data.get("official_standings") or data.get("source_standings") or []
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

    diffs, checked = [], {}
    for key, keymap, label in present:
        table = data[key]
        st = recompute(played, [r.get("team") for r in table])
        n = 0
        for r in table:
            team = r.get("team")
            s = st.get(team)
            if s is None:
                continue                  # 上の misname で報告済み
            for src_key, off_key in keymap:
                if off_key not in r:
                    continue              # 出典が持っていない列＝比べる相手が無い（正常）
                n += 1
                if r[off_key] != s[src_key]:
                    diffs.append(f"⚠ {slug}: {team}.{off_key} {label}{r[off_key]} ≠ 試合から{s[src_key]}")
            if "gd" in r:
                n += 1
                if r["gd"] != s["gf"] - s["ga"]:
                    diffs.append(f"⚠ {slug}: {team}.gd {label}{r['gd']} ≠ 試合から{s['gf'] - s['ga']}")
        checked[key] = n
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

    all_diffs, all_misname, skipped = [], [], 0
    checked = collections.Counter()
    tables = collections.Counter()
    for p in targets:
        if not p.exists():
            all_misname.append(f"⚠ {p}: ファイルが見つかりません")
            continue
        diffs, misname, n = check_one(p)
        all_diffs += diffs
        all_misname += misname
        checked.update(n)
        for key in n:
            tables[key] += 1
        if not n and not diffs:
            skipped += 1

    # ⚠️ 表ごとに分けて出す。official_standings 側は自動更新直後だと
    #    原理的に一致する部分を含むので、**件数の大きさを守備範囲の広さと読ませない**ため。
    detail = "／".join(f"{k} {tables[k]}リーグ {checked[k]:,}項目" for k, _, _ in TABLES if tables[k])
    print(f"=== 順位表 ⇄ 試合一覧 の突き合わせ（{len(targets)}リーグ・{detail}）===")
    # ⚠️ 名寄せのずれを**先に**出す。これがあると数値の食い違いはその結果でしかないことが多い。
    for line in all_misname:
        print("  " + line)
    for line in all_diffs:
        print("  " + line)

    ng = [x for x in all_misname if x.startswith("⚠")]
    if not all_diffs and not ng:
        print(f"  ✅ 食い違いなし"
              f"{f'（うち突き合わせる順位表が無くスキップ {skipped} リーグ）' if skipped else ''}")
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
