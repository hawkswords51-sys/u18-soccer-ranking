#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
試合日程の日付を出典と突き合わせて、ズレの一覧を出すだけのスクリプト
====================================================================
2026-09-05 新設。

**このスクリプトは1バイトも書き込みません。** 見るだけです。
「サイトに出ている日付が実際と違う」と気づいたときに、どのリーグの
どの試合がずれているのかを一覧で確認するために使います。

きっかけ:
  プリンス東北の第12節「聖和学園 vs ブラウブリッツ秋田U-18」が、実際は9/6なのに
  サイトでは9/5と出ていた（2026-09-05にKeiが発見）。調べたところ出典のkoko側が
  9/5のままだった時期があり、こちらはそれを忠実に取り込んでいた（＝コードの不具合
  ではなく出典の遅れ）。同じことが他リーグで起きていないか点検できるようにした。

使い方:
  python scraper/audit_match_dates.py            # プレミア2＋プリンス13を点検
  python scraper/audit_match_dates.py --pref     # 県1部の状況も併せて報告

読み方:
  - 「未消化」のズレ … 出典側で日程が変わった。次の自動更新で自動的に直る。
  - 「★消化済」のズレ … 結果が確定した試合の日付が動いている。出典が別の試合と
    取り違えている可能性があるので、出典の個別試合ページで確認すること。

注意（突き合わせの作り）:
  対戦カードは「節番号＋ホーム＋アウェイ」で照合する。ホームとアウェイだけで
  照合すると、四国・北信越のように**同じ組み合わせが2回出てくるリーグ**で
  取り違えて誤検出が出る（2026-09-05に実際に出た）。
"""
import argparse
import collections
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_jfa_premier as fj          # noqa: E402
import update_cross_tables as uct       # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "league_matches"

UA = {"User-Agent": "Mozilla/5.0 (u18-soccer.com date audit)"}
JFA_SCHEDULE = (fj.BASE + "schedule.json")

PREMIER = {"premier-east": "east", "premier-west": "west"}


def _load(slug: str) -> dict:
    return json.loads((DIR / f"{slug}.json").read_text(encoding="utf-8"))


def _source_matches(slug: str) -> list[dict]:
    """出典から [{md, home, away, date, status}] を取ってくる"""
    if slug in PREMIER:
        url = JFA_SCHEDULE.format(season=fj.SEASON, side=PREMIER[slug])
        req = urllib.request.Request(url, headers=UA)
        raw = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
        resolve = fj._build_resolver([t["name"] for t in _load(slug).get("teams", [])])
        out = []
        for m in raw["matchScheduleList"]["matchSchedule"]:
            out.append(dict(
                md=fj._md_of(m.get("matchTypeName")),
                home=resolve(m.get("homeTeamName", "")),
                away=resolve(m.get("awayTeamName", "")),
                date=fj._iso_date(m.get("matchDate")),
                status="played" if m.get("matchStatus") == "試合終了" else "scheduled",
            ))
        return out
    uct._CURRENT_SLUG = slug   # LEAGUE_ALIASES をこのリーグの分だけ有効にする
    return uct.extract(uct.KOKO_URL[slug])[1]


def audit(slug: str) -> tuple[list[tuple], str]:
    """1リーグ分を点検して (ズレの一覧, サマリー文) を返す"""
    try:
        src = _source_matches(slug)
    except Exception as e:
        return [], f"  {slug:24s} [取得失敗] {e}"

    by_key = collections.defaultdict(list)
    for m in src:
        by_key[(m["md"], m["home"], m["away"])].append(m)

    rows = []
    unplayed = played = missing = 0
    for m in _load(slug).get("matches", []):
        key = (m.get("md"), m.get("home"), m.get("away"))
        if not by_key.get(key):
            missing += 1
            continue
        s = by_key[key].pop(0)
        if (m.get("date") or "") == (s.get("date") or ""):
            continue
        kind = "未消化" if m.get("status") != "played" else "★消化済"
        rows.append((slug, m.get("md"), m.get("home"), m.get("away"),
                     m.get("date") or "(空)", s.get("date") or "(空)", kind))
        if kind == "未消化":
            unplayed += 1
        else:
            played += 1
    return rows, (f"  {slug:24s} ズレ 未消化{unplayed:3d} / 消化済{played:3d} / "
                  f"出典に無い試合{missing:3d}")


def report_pref() -> None:
    """県1部の状況を報告する（自動修正はしない）"""
    print("\n=== 県1部（pref-*-1.json）の状況 ===")
    print("  出典（junior-soccer等）は「結果が出た試合」しか載せないため、")
    print("  update_pref_cross_tables.py は未消化試合を日付なしの枠として作る。")
    print("  つまり県1部の未消化試合に日付が入らないのは仕様であって、ズレではない。")
    total = empty = 0
    for path in sorted(DIR.glob("pref-*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        un = [m for m in d.get("matches", []) if m.get("status") != "played"]
        total += len(un)
        empty += sum(1 for m in un if not m.get("date"))
    print(f"  未消化試合 {total} 件のうち、日付なし {empty} 件")
    print("  ※ 埼玉(pref-saitama-1.json)は手動編集がbotに戻されるため対象外と決めてある。")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="試合日付を出典と突き合わせて一覧を出す（書き込みはしない）")
    parser.add_argument("--pref", action="store_true", help="県1部の状況も報告する")
    args = parser.parse_args()

    print("=== 試合日付の点検（書き込みはしません） ===")
    slugs = list(PREMIER) + [s for s in uct.KOKO_URL if s.startswith("prince")]
    rows = []
    for slug in slugs:
        r, summary = audit(slug)
        rows += r
        print(summary)

    print("\n=== ズレの一覧 ===")
    if not rows:
        print("  なし（全リーグで出典と一致）")
    for r in sorted(rows):
        print(f"  {r[0]:22s} 第{r[1]:2d}節 {r[2]} vs {r[3]}   "
              f"保存:{r[4]} → 出典:{r[5]}  [{r[6]}]")

    if args.pref:
        report_pref()
    return 0


if __name__ == "__main__":
    sys.exit(main())
