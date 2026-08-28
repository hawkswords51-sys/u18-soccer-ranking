#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大学サッカーハブ /university/ の順位表セクションを生成する。

- データの正本: data/university/leagues-2026.json（手で直してこのスクリプトを再実行するだけで反映）
- university/index.html の <!-- UNIV_STANDINGS_START --> 〜 <!-- UNIV_STANDINGS_END --> の間だけを書き換える。
- 検算の安全装置（U-15ハブ /u15/ と同方式）:
    勝点=勝×3+分 / 試合数=勝+分+敗 / 得失差=得点-失点 / 順位順で勝点が単調非増加 /
    リーグ内の得点合計=失点合計・勝数合計=敗数合計・引分合計が偶数・総試合数が偶数
  1つでも合わないリーグはそのリーグだけ描画しない（警告を出す）。誤データを載せない設計。
- sitemap には触らない（/university/ の sitemap 登録は generate_interhigh_page.py の static_pages）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "university" / "leagues-2026.json"
PAGE = ROOT / "university" / "index.html"
START = "<!-- UNIV_STANDINGS_START -->"
END = "<!-- UNIV_STANDINGS_END -->"

REGION_ORDER = ["北海道", "東北", "関東", "北信越", "東海", "関西", "中国", "四国", "九州"]


def validate(lg):
    errs = []
    ts = lg["teams"]
    for t in ts:
        if t["p"] != t["w"] * 3 + t["d"]:
            errs.append(f"勝点不一致: {t['name']}")
        if t["g"] != t["w"] + t["d"] + t["l"]:
            errs.append(f"試合数不一致: {t['name']}")
        if t["gd"] != t["gf"] - t["ga"]:
            errs.append(f"得失差不一致: {t['name']}")
    pts = [t["p"] for t in ts]
    ranks = [t["rank"] for t in ts]
    if ranks != sorted(ranks):
        errs.append("順位が昇順でない")
    for i in range(len(pts) - 1):
        if pts[i] < pts[i + 1]:
            errs.append(f"勝点が順位順で増加: {ts[i+1]['name']}")
    if sum(t["gf"] for t in ts) != sum(t["ga"] for t in ts):
        errs.append("リーグ内の得点合計≠失点合計")
    if sum(t["w"] for t in ts) != sum(t["l"] for t in ts):
        errs.append("勝数合計≠敗数合計")
    if sum(t["d"] for t in ts) % 2 != 0:
        errs.append("引分合計が奇数")
    if sum(t["g"] for t in ts) % 2 != 0:
        errs.append("総試合数が奇数")
    return errs


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_league(lg):
    rows = []
    last = len(lg["teams"])
    for t in lg["teams"]:
        cls = ""
        if t["rank"] == 1:
            cls = ' class="uv-top"'
        elif t["rank"] == last:
            cls = ' class="uv-bottom"'
        gd = t["gd"]
        gd_s = f"+{gd}" if gd > 0 else str(gd)
        rows.append(
            f'                <tr{cls}><td class="uv-rank">{t["rank"]}</td>'
            f'<td class="uv-name">{esc(t["name"])}</td>'
            f'<td class="uv-c">{t["g"]}</td><td class="uv-c">{t["w"]}</td>'
            f'<td class="uv-c">{t["d"]}</td><td class="uv-c">{t["l"]}</td>'
            f'<td class="uv-c">{t["gf"]}</td><td class="uv-c">{t["ga"]}</td>'
            f'<td class="uv-c">{gd_s}</td><td class="uv-pts">{t["p"]}</td></tr>'
        )
    note = f'\n            <p class="uv-src2">※{esc(lg["note"])}</p>' if lg.get("note") else ""
    return f"""          <div class="uv-div">
            <h3>{esc(lg["name"])}</h3>
            <p class="uv-asof">{esc(lg["asof"])}</p>
            <div class="univ-scroll">
            <table class="uv-table">
              <thead><tr><th>順</th><th class="uv-name" style="text-align:left;">チーム</th><th>試</th><th>勝</th><th>分</th><th>敗</th><th>得</th><th>失</th><th>差</th><th>点</th></tr></thead>
              <tbody>
{chr(10).join(rows)}
              </tbody>
            </table>
            </div>
            <p class="uv-src2">出典：<a href="{lg["sourceUrl"]}" target="_blank" rel="noopener">{esc(lg["sourceLabel"])}</a></p>{note}
          </div>"""


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    ok_leagues = []
    for lg in data["leagues"]:
        errs = validate(lg)
        if errs:
            print(f"[要確認] {lg['id']}: 検算NGのため描画をスキップ → {'; '.join(errs)}")
            continue
        ok_leagues.append(lg)

    # 地域ごとにまとめる
    by_region = {}
    for lg in ok_leagues:
        by_region.setdefault(lg["region"], []).append(lg)

    jump = ['        <div class="uv-jump">']
    for i, r in enumerate(REGION_ORDER, 1):
        if r in by_region:
            jump.append(f'          <a href="#uv-region-{i}">{r}<span class="uv-cnt">{len(by_region[r])}</span></a>')
    jump.append("        </div>")

    sections = []
    for i, r in enumerate(REGION_ORDER, 1):
        if r not in by_region:
            continue
        divs = "\n".join(render_league(lg) for lg in by_region[r])
        sections.append(f"""        <div id="uv-region-{i}">
        <h3 style="margin:22px 0 10px;"><i class="fas fa-map-location-dot"></i> {r}</h3>
        <div class="uv-divs">
{divs}
        </div>
        </div>""")

    html = "\n".join(jump) + "\n" + "\n".join(sections) + "\n"

    src = PAGE.read_text(encoding="utf-8")
    if START not in src or END not in src:
        print("[エラー] マーカーが見つかりません。university/index.html を確認してください。")
        sys.exit(1)
    pre, rest = src.split(START, 1)
    _, post = rest.split(END, 1)
    PAGE.write_text(pre + START + "\n" + html + END + post, encoding="utf-8")
    n_teams = sum(len(lg["teams"]) for lg in ok_leagues)
    print(f"OK: {len(ok_leagues)}リーグ・{n_teams}チームを描画（スキップ {len(data['leagues']) - len(ok_leagues)}）")


if __name__ == "__main__":
    main()
