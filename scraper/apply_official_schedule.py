#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公式の「日程だけ」で既存データを補う（2026-09-17 新設）
======================================================
**結果（スコア）は公開していないが、日程（節・日付・会場・左右）は公開している**県のための仕組み。
スコアは junior-soccer のまま、**節と日付と格納の向きだけ**を公式にそろえる。

なぜ別のステップにするか
------------------------
- `fetch_pref_official.py` の読み手（`read_*`）は **standings と matches を作る**もので、
  「スコアを保ったまま日付と節だけ更新する」経路が無い。
- 対象の県は junior-soccer からの取り込み自体が**手動（週1）**なので、この上書きも同じタイミングで回せばよい。
  **Actions から毎日走らせる必要は無い。**
- → **junior-soccer の取り込みが終わったあとに走る「日程の上書き」**として独立させた。
  同じ型（日程は公式・結果は無い）の県が出たら `OFFICIAL_SCHEDULES` に足すだけで使える。

⚠️ 大原則
---------
1. **スコア（`hs`/`as`/`status`）には絶対に触らない。**
2. **決められるものだけ決める。** 既存の2件とも日付が無いペアは、どちらがどちらか決められないので
   **日付も節も付けない**（増分での巡目割り当てと同じ考え方）。
3. 既存の日付が公式の候補日のどちらとも違うときは、**公式を採る**（junior-soccer 側の誤り）。
   ⚠️ ただし**順延の反映は有志のほうが速いことがある**ので、食い違いは必ず一覧で出して人が見る。

使い方
------
  python scraper/apply_official_schedule.py --pref ishikawa --dry-run   # 何が変わるか見るだけ
  python scraper/apply_official_schedule.py --pref ishikawa             # 書き込む
"""
from __future__ import annotations
import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdf_source                                    # noqa: E402
from fetch_pref_official import fetch_html, HEADERS, TIMEOUT, SLEEP, SEASON_YEAR  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "league_matches"

# ---------------------------------------------------------------------------
# 対象の県（「日程は公式・結果は公開されていない」型）
# ---------------------------------------------------------------------------
# ⚠️ ここに入れても `PREF_OFFICIAL` には入れないこと。**検算（結果の突き合わせ）ができない**ので
#    公式移行ではない。取り込みは今までどおり junior-soccer から。
OFFICIAL_SCHEDULES: dict[str, dict] = {
    # 石川（2026-09-17）。県高体連サッカー専門部の1部日程PDF。
    # ⚠️ ページには「日程 結果」と並ぶが、**「結果」はリンクではなくただの文字**＝結果は公開されていない。
    #    ⏳ 「結果」が <a> になったら全面移行できる（見張りに足す価値あり）。
    # ⚠️ 試合NOは一意ではない（前第6節と前第7節が両方1061-1064、後第4節で1101が飛ぶ）。**キーに使わない。**
    # ⚠️ 節・日付・会場は結合セルで値が縦の中央に来る。`page_tables` なら結合範囲の先頭行に入るので素直に解ける。
    #    ❌ 座標の「いちばん近いラベル」で割り当てないこと（節2と節8の先頭が前のブロックに吸われる）。
    "ishikawa": {
        "url": "https://soccer-u18.ishikawa.jp/u18/2026/2026_1st.pdf",
        "source": "https://soccer-u18.ishikawa.jp/u-18.html",
        "title": "サッカーリーグ{year}石川1部リーグ日程",
        "teams": 8,
        "half": 7,                       # 前第N節 → md=N、後第N節 → md=half+N
        "alias": {"金沢市立工業": "金沢市工"},
    },
}


def _nfkc(s: str) -> str:
    """⚠️ チーム名・節ラベルにだけ当てる（丸数字などが化けるので、セル全体には当てない）。"""
    return re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", s or ""))


def read_schedule(pref: str, cfg: dict, teams: list[str]) -> list[dict]:
    """公式PDFから (md, date, home, away, venue) を読む。"""
    year = str(SEASON_YEAR)
    alias = cfg.get("alias", {})
    names = set(teams) | set(alias)
    card = re.compile("({0})vs({0})".format("|".join(sorted((re.escape(x) for x in names),
                                                            key=len, reverse=True))))
    content = pdf_source.fetch_pdf(cfg["url"], HEADERS, TIMEOUT, wait=SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        head = _nfkc(pdf.pages[0].extract_text() or "")
        want = cfg["title"].format(year=year)
        if want not in head:
            raise RuntimeError(f"日程PDFの表題が想定と違う（{want} が無い）")
        rows = [r for pg in pdf.pages for t in pdf_source.page_tables(pg) for r in t]
    md = date = venue = None
    out = []
    for r in rows:
        c = [_nfkc(x) for x in r]
        if len(c) != 7 or c[0] == "節":
            continue
        mm = re.fullmatch(r"(前|後)第(\d+)節", c[0])
        if mm:
            md = (0 if mm.group(1) == "前" else cfg["half"]) + int(mm.group(2))
        dm = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", c[1])
        if dm:
            date = f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
        if c[6]:
            venue = c[6]
        for h, a in card.findall(c[5]):
            if not (md and date):
                raise RuntimeError(f"日程PDFの行に節または日付が無い: {r}")
            out.append(dict(md=md, date=date, venue=venue,
                            home=alias.get(h, h), away=alias.get(a, a)))
    n = cfg["teams"]
    if len(out) != n * (n - 1):
        raise RuntimeError(f"日程PDFから{len(out)}試合（{n * (n - 1)}試合のはず）")
    if any(sum(1 for s in out if s["md"] == k) != n // 2 for k in range(1, 2 * cfg["half"] + 1)):
        raise RuntimeError("日程PDFの節ごとの試合数が想定と違う")
    pairs = collections.Counter(frozenset((s["home"], s["away"])) for s in out)
    if len(pairs) != n * (n - 1) // 2 or set(pairs.values()) != {2}:
        raise RuntimeError(f"日程PDFのペアが{len(pairs)}組（各2回のはず）")
    return out


def apply_official_schedule(pref: str, cfg: dict, dry_run: bool) -> int:
    path = DIR / f"pref-{pref}-1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    teams = [t["name"] for t in data.get("teams", [])]
    sched = read_schedule(pref, cfg, teams)

    by_off = collections.defaultdict(list)
    for s in sched:
        by_off[frozenset((s["home"], s["away"]))].append(s)
    by_ex = collections.defaultdict(list)
    for m in data["matches"]:
        by_ex[frozenset((m["home"], m["away"]))].append(m)
    if set(by_off) != set(by_ex):
        raise RuntimeError(f"公式と既存で対戦カードが違う: {sorted(set(by_off) ^ set(by_ex))}")

    changed = collections.Counter()
    fixed_dates, skipped = [], []
    for key, off in by_off.items():
        off = sorted(off, key=lambda s: s["md"])
        ex = by_ex[key]
        dated = [m for m in ex if m.get("date")]
        # ⚠️ 2件とも日付が無いペアは、どちらがどちらか決められないので触らない
        if not dated:
            skipped.append(sorted(key))
            continue
        used, rest_off = {}, list(off)
        for m in dated:
            hit = [o for o in rest_off if o["date"] == m["date"]]
            if not hit:
                # 既存の日付が公式のどちらとも違う → 公式を採る（junior-soccer 側の誤り）
                hit = [rest_off[0]]
                fixed_dates.append((m["date"], hit[0]["date"], m["home"], m["away"]))
            o = hit[0]
            rest_off.remove(o)
            used[id(m)] = o
        for m in ex:                                   # 日付の無い残り＝もう一方の節に決まる
            if id(m) not in used and rest_off:
                used[id(m)] = rest_off.pop(0)
        for m in ex:
            o = used.get(id(m))
            if o is None:
                continue
            if m.get("md") != o["md"]:
                m["md"] = o["md"]
                changed["節を付けた"] += 1
            if m.get("date") != o["date"]:
                changed["日付を付けた" if not m.get("date") else "日付を直した"] += 1
                m["date"] = o["date"]
            # 格納の向きを公式にそろえる（⚠️ スコアは入れ替えるのではなく、向きと一緒に付け替える）
            if m["home"] != o["home"]:
                m["home"], m["away"] = o["home"], o["away"]
                if m.get("hs") is not None:
                    m["hs"], m["as"] = m["as"], m["hs"]
                changed["向きをそろえた"] += 1

    print(f"=== 公式の日程で補う: pref-{pref}-1 ===")
    for k, v in sorted(changed.items()):
        print(f"  {k}: {v}件")
    for old, new, h, a in fixed_dates:
        print(f"  ⚠️ 既存の日付が公式と違う（公式を採用）: {old} → {new}  {h}×{a}")
    for k in skipped:
        print(f"  ⏸️ 2件とも日付が無いので触らない: {k[0]}×{k[1]}")
    played = [m for m in data["matches"] if m.get("status") == "played"]
    print(f"  枠{len(data['matches'])}／消化{len(played)}／"
          f"消化で日付なし{sum(1 for m in played if not m.get('date'))}／"
          f"節が付いた{sum(1 for m in data['matches'] if m.get('md'))}件")
    if dry_run:
        print("  （--dry-run：書き込みなし）")
        return 0
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {path.name} を更新しました")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="公式の日程（節・日付・向き）だけで既存データを補う")
    parser.add_argument("--pref", required=True, help=f"県id（{'/'.join(OFFICIAL_SCHEDULES)}）")
    parser.add_argument("--dry-run", action="store_true", help="書き込まずに差分だけ見る")
    args = parser.parse_args()
    cfg = OFFICIAL_SCHEDULES.get(args.pref)
    if not cfg:
        print(f"{args.pref} は OFFICIAL_SCHEDULES に登録されていません")
        return 1
    return apply_official_schedule(args.pref, cfg, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
