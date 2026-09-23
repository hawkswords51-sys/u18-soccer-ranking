#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
プレミア参入プレーオフの「出場権が確定したチーム」を見張る
==========================================================
2026-09-23 新設。データは一切さわらない（読むだけ）。常に exit 0。

なぜ作ったか
------------
参入戦ページ tournaments/promotion-playoff-2026/index.html の「出場決定チーム」の表は
手書きで、12月まで1チームずつ埋まっていく。ところが確定を知らせる仕組みが無かった。
ニュースで拾う方式だと、記事にならない小さいリーグの確定を取りこぼす
（2026-09-21の尚志はゲキサカ・kokoが報じたが、いつもそうとは限らない）。

必要なデータは全部リポジトリの中にある。data/league_matches/prince-*.json に
順位表（勝点・消化数）と未消化試合の両方があり、毎朝更新される。だから毎朝の実行で
「数学的にもう確定したチーム」を数えて、ページの表と食い違ったら🟡を出す。

同じ事実を2か所に持たないための約束
------------------------------------
  - 枠の数は data/league_zones.yml の playoff ゾーンの slots から読む（合計16）。
    ★このスクリプトに枠の表を書かない。
  - セカンドチームの判定は league_zones の関数を使う。
    ★正規表現を新しく書かない。
  - 対象リーグも yml の「skipSecondTeams を持つ playoff ゾーン」から決める。
    ★prince-* を名前で列挙しない。

判定
----
JFA『プレミアリーグ2026 プレーオフ』大会要項の「出場チーム」は
「9地域の成績上位の16チーム（プレミアリーグ所属チームのセカンドチームは含まない）」。
枠は次の順位に繰り下がる。

  チームXが確定 ⇔「X以外の**資格のある**チームのうち、残り全勝で X の現在の勝点に
                  並ぶか上回れるチームの数」が slots 未満

⚠️ 並ぶ場合も脅威に数える（>=）。並んだら得失点差の勝負になり、データからは決められない。
⚠️ セカンドチームは枠も取らないし、脅威にも数えない（要項どおり）。
⚠️ dateTbd の試合も「残り」に数える（いずれ行われるので）。

赤にしない理由
--------------
表の更新が遅れているのはデータの不具合ではない。人が表を1行直せば済む話なので🟡にとどめる。
（audit_pref_freshness.py の「打つ手があるものだけを赤にする」と同じ考え方）

単体テスト:
    python scraper/audit_premier_playoff.py
    python scraper/audit_premier_playoff.py --no-skip-second   # 除外を切って比べる
    python scraper/audit_premier_playoff.py --matches-dir /tmp/fake --page /tmp/fake.html
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jst import today as _jst_today          # noqa: E402
from league_zones import (                    # noqa: E402
    _LEAGUES,
    _base_team_name,
    is_second_team,
    premier_teams_from_league_matches,
)

BASE_DIR = Path(__file__).resolve().parent.parent
PAGE = BASE_DIR / "tournaments" / "promotion-playoff-2026" / "index.html"
_PAGE_RE = re.compile(r"(\d+)\s*／\s*(\d+)\s*決定")


def playoff_zones():
    """yml から「参入戦の枠を持つリーグ」を取り出す → [(slug, slots), ...]"""
    out = []
    for slug, cfg in (_LEAGUES or {}).items():
        for z in (cfg.get("zones") or []):
            if z.get("type") == "playoff" and z.get("skipSecondTeams"):
                slots = z.get("slots")
                if isinstance(slots, int) and slots > 0:
                    out.append((slug, slots))
                break
    return sorted(out)


def load_league(slug, matches_dir):
    p = Path(matches_dir) / f"{slug}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def remaining_counts(matches):
    """チーム名 -> 未消化試合数（dateTbd も数える）"""
    rem = {}
    for m in matches or []:
        if (m or {}).get("status") == "played":
            continue
        for t in ((m or {}).get("home"), (m or {}).get("away")):
            if t:
                rem[t.strip()] = rem.get(t.strip(), 0) + 1
    return rem


def analyze(slug, slots, matches_dir, premier_names, skip_second=True):
    """1リーグぶん。戻り値 (確定リスト, 除外リスト, リーグ表示名) """
    d = load_league(slug, matches_dir)
    if not d:
        return [], [], slug
    st = d.get("official_standings") or []
    if not st:
        return [], [], d.get("league") or slug
    rem = remaining_counts(d.get("matches"))

    def ineligible(name):
        if not skip_second:
            return False
        if not is_second_team(name):
            return False
        return _base_team_name(name) in premier_names

    rows = []
    excluded = []
    for r in st:
        name = (r.get("team") or "").strip()
        if not name:
            continue
        if ineligible(name):
            excluded.append(name)
            continue
        rows.append({
            "name": name,
            "rank": r.get("rank"),
            "pts": r.get("pts") or 0,
            "played": r.get("played") or 0,
            "rem": rem.get(name, 0),
        })

    fixed = []
    for x in rows:
        # x より上（または同点）に来られる相手の数
        threats = sum(1 for o in rows
                      if o["name"] != x["name"] and o["pts"] + 3 * o["rem"] >= x["pts"])
        if threats < slots:
            fixed.append(x)
    fixed.sort(key=lambda x: (x["rank"] or 99))
    return fixed, excluded, (d.get("league") or slug)


def region_label(league_name, slug):
    """「高円宮杯 JFA U-18 プリンスリーグ 2026 東北」→「東北」"""
    m = re.search(r"プリンスリーグ\s*\d{4}\s*(.+)$", league_name or "")
    return (m.group(1).strip() if m else slug.replace("prince-", ""))


def page_decided(page_path):
    """参入戦ページの「N ／ 16 決定」から N と 16 を読む。無ければ (None, None)"""
    p = Path(page_path)
    if not p.exists():
        return None, None
    m = _PAGE_RE.search(p.read_text(encoding="utf-8"))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def main():
    ap = argparse.ArgumentParser(description="プレミア参入プレーオフの出場権確定を見張る")
    ap.add_argument("--no-skip-second", action="store_true",
                    help="セカンドチームの除外を切る（検証用の比較）")
    ap.add_argument("--matches-dir", default=str(BASE_DIR / "data" / "league_matches"))
    ap.add_argument("--page", default=str(PAGE))
    args = ap.parse_args()

    zones = playoff_zones()
    total_slots = sum(s for _, s in zones)
    # 比べる相手は league_matches のプレミア24チーム名（teams.json とは名前の世界が違う）
    premier_names = {t["name"] for t in premier_teams_from_league_matches(BASE_DIR)}

    print(f"=== プレミア参入プレーオフ 出場権の確定状況（{_jst_today()} JST）===")
    print(f"  対象 {len(zones)}リーグ／枠 合計 {total_slots}"
          + ("　※セカンドチームの除外を切って実行中" if args.no_skip_second else ""))

    fixed_all, excluded_all = [], []
    for slug, slots in zones:
        fixed, excluded, league_name = analyze(
            slug, slots, args.matches_dir, premier_names,
            skip_second=not args.no_skip_second)
        rg = region_label(league_name, slug)
        for x in fixed:
            fixed_all.append((rg, x))
        for n in excluded:
            excluded_all.append((rg, n))

    print(f"  確定 {len(fixed_all)} / {total_slots}")
    if fixed_all:
        for rg, x in fixed_all:
            print(f"   {rg}   {x['name']}（{x['pts']}点/{x['played']}試合・残り{x['rem']}）")
    else:
        print("   まだ確定したチームはありません")

    # ★除外の一覧は毎回出す。名前の変換が壊れると、真っ先にここの数が減る。
    print(f"  除外（プレミア所属チームのセカンドチーム）: {len(excluded_all)}")
    if excluded_all:
        print("   " + "／".join(f"{rg} {n}" for rg, n in excluded_all))

    n, denom = page_decided(args.page)
    if n is None:
        print("  ℹ️ 参入戦ページの「N ／ 16 決定」が読めませんでした（表の書式が変わった？）")
    elif n != len(fixed_all) or (denom is not None and denom != total_slots):
        print(f"  🟡 ページの表と食い違っています"
              f"（ページ={n} ／ {denom}・データ={len(fixed_all)} ／ {total_slots}）"
              " ← 表の更新が必要です")
    else:
        print(f"  ✅ 参入戦ページの表と一致（{n} ／ {denom}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
