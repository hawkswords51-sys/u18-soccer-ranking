#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
`pref-hokkaido-1.json` の土台を1回だけ作る（2026-09-18・47県目）
================================================================
`fetch_pref_official.process()` は**既存のJSONを更新する仕組みで、新規作成しない**
（`if not path.exists(): return "[skip] JSONなし"`）。他41県はすべて junior-soccer 由来の
既存JSONがあり、そこへ公式を被せる形で移行してきた。**北海道はその土台が無い初めてのケース。**

なぜ「手で書く」でも「process に分岐を足す」でもないのか
--------------------------------------------------------
- ❌ **手で書く**… 2026-09-18に埼玉でやった「関門の迂回」そのもの。手で書いた数字が土台に入る。
- ❌ **process に「無ければ作る」を足す**… 「JSONなし → skip」は**県idを打ち間違えたときに
  空ファイルを作らない安全装置**として働いている。47県目が最後の1県で、この分岐を将来使う見込みも薄い。
  **41県が通る経路に分岐を増やさない。**
- ✅ **読み手の出力から土台を作る**（この方式）… 手で書いた数字が1つも入らない。

⭐️ そのための条件2つ
--------------------
1. **枠は `generate_fixtures` に作らせる。手で並べない。**
   土台だけ別の書き方をすると、そこが「もう1つの経路」になる。
2. **土台を書く前に、本番と同じ関門を通す。**
   Σ得失点差＝0 ／ 公式順位表（pts・gd・rank）⇄ 試合から計算した値 ／ 試合数と枠数。
   ⚠️ ここを飛ばすと、埼玉の迂回を**仕組みとして**作ることになる。

📌 役目を終えたあとも残してよい。「土台をどう作ったか」が消えると、
   次に新しいリーグを足す人が同じ所で止まる。

使い方（⚠️ /tmp にコピーして実行すること。リポジトリ内で生成スクリプトを走らせない規約）
  python scraper/bootstrap_hokkaido.py --dry-run   # 検算だけ。書かない
  python scraper/bootstrap_hokkaido.py             # 検算が通ったら書く
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_pref_official as F                                   # noqa: E402
from update_pref_cross_tables import generate_fixtures, recompute  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "league_matches" / "pref-hokkaido-1.json"
SLUG = "hokkaido"


def main() -> int:
    ap = argparse.ArgumentParser(description="pref-hokkaido-1.json の土台を1回だけ作る")
    ap.add_argument("--dry-run", action="store_true", help="検算だけして書かない")
    args = ap.parse_args()

    if OUT.exists():
        print(f"⚠️ {OUT.name} は既にあります。土台づくりは1回だけです。")
        print("   以後の更新は fetch_pref_official.py（Actions）が行います。")
        return 1

    cfg = F.PREF_OFFICIAL[SLUG]
    standings, matches = F.read_hokkaido(cfg)
    site = json.loads((ROOT / "data" / "teams.json").read_text(encoding="utf-8"))[SLUG]

    # --- 名寄せ（本番と同じ build_name_map を使う。手で対応表を書かない） ---
    # ⚠️ teams.json の hokkaido には**プリンス北海道8とFAリーグ8が同居**している（計16）。
    #    土台に入れるのは**出典の順位表に出てくる8チームだけ**。
    #    どのサイト表記に寄るかは build_name_map に決めさせる（PREF_ALIAS と norm() の正本はあちら）。
    site_names = [t["name"] for t in site.get("teams", [])]
    official_names = (set(standings) | {m["home"] for m in matches} | {m["away"] for m in matches})
    name_map, unknown = F.build_name_map(official_names, site_names, SLUG)
    if unknown:
        print(f"⛔️ 名寄せできないチーム名: {unknown}")
        print("   → PREF_ALIAS['hokkaido'] に、**ここに出たものだけ**を登録してからやり直す")
        return 1

    standings = {name_map[k]: v for k, v in standings.items()}
    matches = [dict(m, home=name_map[m["home"]], away=name_map[m["away"]]) for m in matches]
    teams = sorted(standings, key=lambda t: standings[t]["rank"])

    # --- ⭐️ 関門（本番と同じ検算。通らなければ書かない） ---
    ng = []
    if sum(v["gd"] for v in standings.values()) != 0:
        ng.append("Σ得失点差が0でない")
    st = recompute(matches, teams)
    for t in teams:
        off, got = standings[t], st[t]
        if got["pts"] != off["pts"]:
            ng.append(f"{t}: 勝点 出典{off['pts']} ≠ 試合から{got['pts']}")
        if got["gf"] - got["ga"] != off["gd"]:
            ng.append(f"{t}: 得失点差 出典{off['gd']} ≠ 試合から{got['gf'] - got['ga']}")
    # 順位（勝点→得失点差。両方が並ぶチーム同士の前後だけは許す＝pts_gd ゲートと同じ扱い）
    mine = sorted(teams, key=lambda t: (-st[t]["pts"], -(st[t]["gf"] - st[t]["ga"])))
    for t in teams:
        if mine.index(t) + 1 != standings[t]["rank"]:
            key = (st[t]["pts"], st[t]["gf"] - st[t]["ga"])
            if sum(1 for x in teams if (st[x]["pts"], st[x]["gf"] - st[x]["ga"]) == key) < 2:
                ng.append(f"{t}: 順位 出典{standings[t]['rank']} ≠ 試合から{mine.index(t) + 1}")

    n = len(teams)
    # --- 枠は generate_fixtures に作らせる（手で並べない） ---
    fixtures = generate_fixtures(teams, double=True)
    if len(fixtures) != n * (n - 1):
        ng.append(f"枠が{len(fixtures)}（{n * (n - 1)}のはず）")

    key = {(f["home"], f["away"]): f for f in fixtures}
    for m in matches:
        f = key.get((m["home"], m["away"]))
        if f is None or f.get("status") == "played":
            # 出典の左右が2試合とも同じ並びのことがあるので、埋まっていたら反対回りへ
            f = key.get((m["away"], m["home"]))
        if f is None or f.get("status") == "played":
            ng.append(f"入れる枠が無い: {m['home']} vs {m['away']}")
            continue
        f["home"], f["away"] = m["home"], m["away"]
        f["hs"], f["as"], f["status"] = m["hs"], m["as"], "played"
        f["date"] = m["date"]
        # ⚠️ venue / srcId は**空なら書かない**（他県に無いキーなので、無くても壊れない作りにする）
        if m.get("venue"):
            f["venue"] = m["venue"]
        if m.get("srcId"):
            f["srcId"] = m["srcId"]

    played = sum(1 for f in fixtures if f.get("status") == "played")
    if played != len(matches):
        ng.append(f"枠に入った消化{played}件が読み取り{len(matches)}件と合わない")

    print(f"=== 北海道FAリーグ 土台の検算 ===")
    print(f"  チーム {n} ／ 枠 {len(fixtures)} ／ 消化 {played}")
    print(f"  会場が入った試合 {sum(1 for f in fixtures if f.get('venue'))}"
          f" ／ srcId {sum(1 for f in fixtures if f.get('srcId'))}")
    if ng:
        print("⛔️ 関門を通りませんでした。書き込みません:")
        for x in ng:
            print("   ", x)
        return 1
    print("  ✅ 関門を通りました（Σ得失点差0・勝点・得失点差・順位とも一致）")

    data = {
        "league": f"高円宮杯 JFA U-18 サッカーリーグ {F.SEASON_YEAR} 北海道FAリーグ",
        "season": str(F.SEASON_YEAR),
        "source": cfg["source"],
        "sourceName": cfg["label"],
        "lastUpdated": F._jst_today().isoformat(),
        "teams": [dict(name=t) for t in teams],
        "official_standings": [
            # ⚠️ 出典にある列だけ入れる（得点・失点は出典に無いので作らない）
            dict(rank=standings[t]["rank"], team=t,
                 points=standings[t]["pts"], gd=standings[t]["gd"])
            for t in teams
        ],
        "matches": fixtures,
    }
    if args.dry_run:
        print("  （--dry-run：書き込みなし）")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {OUT.name} を作りました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
