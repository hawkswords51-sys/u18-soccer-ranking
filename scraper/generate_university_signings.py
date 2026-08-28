#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大学経由のJクラブ内定選手ページ（/university/pro-signings-2027/）を生成する。

- データの正本: data/university/pro-signings-2027.json（1件追加→本スクリプト再実行→Pushで反映）
- ページの <!-- UNIV_SIGNINGS_START --> 〜 <!-- UNIV_SIGNINGS_END --> の間だけを書き換える。
- U-18の出身チームに当サイトのチーム詳細ページ（data/team-profiles）があれば自動で内部リンクを張る。
- 検証: 必須項目の欠落・発表日形式・重複選手名をチェックし、問題があれば生成を中止する。
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "university" / "pro-signings-2027.json"
PAGE = ROOT / "university" / "pro-signings-2027" / "index.html"
PROFILES = ROOT / "data" / "team-profiles"
START = "<!-- UNIV_SIGNINGS_START -->"
END = "<!-- UNIV_SIGNINGS_END -->"
LEAGUE_ORDER = ["関東1部", "関東2部", "関東3部", "北信越", "東海", "関西", "中国", "九州"]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def norm_team(s):
    s = re.sub(r"\s", "", s)
    s = s.replace("高等学校", "高校").replace("髙", "高")
    return s


def load_team_links():
    """team-profiles の frontmatter name/aliases → /teams/{slug}/ の対応表"""
    links = {}
    if not PROFILES.is_dir():
        return links
    for md in PROFILES.glob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not m:
            continue
        fm = m.group(1)
        names = []
        nm = re.search(r'^name:\s*["\']?([^"\'\n]+)', fm, re.M)
        if nm:
            names.append(nm.group(1).strip())
        am = re.search(r"^aliases:\s*\n((?:\s*-\s*.+\n?)+)", fm, re.M)
        if am:
            names += [re.sub(r"^\s*-\s*", "", ln).strip().strip('"\'')
                      for ln in am.group(1).strip().splitlines()]
        slug = md.stem
        for n in names:
            if n:
                links[norm_team(n)] = slug
    return links


def team_link(name, links):
    if name in ("—", ""):
        return "—"
    key = norm_team(name)
    slug = links.get(key)
    if not slug and not key.endswith("高校"):
        slug = links.get(key + "高校")
    if not slug and key.endswith("高校"):
        slug = links.get(key[:-2])
    if slug:
        return f'<a href="/teams/{slug}/">{esc(name)}</a>'
    return esc(name)


def is_youth(u18):
    return ("ユース" in u18) or ("U-18" in u18) or ("U18" in u18) or ("高等部" not in u18 and "アカデミー" in u18)


def validate(players):
    errs = []
    seen = set()
    for p in players:
        for k in ("name", "pos", "univ", "league", "club", "announced", "u18", "u15", "source"):
            if not str(p.get(k, "")).strip():
                errs.append(f"{p.get('name','?')}: {k} が空")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", p["announced"]):
            errs.append(f"{p['name']}: 発表日の形式が不正")
        key = (p["name"], p["univ"])
        if key in seen:
            errs.append(f"重複: {p['name']}")
        seen.add(key)
        if p["league"] not in LEAGUE_ORDER:
            errs.append(f"{p['name']}: 不明なリーグ {p['league']}")
    return errs


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    players = data["players"]
    errs = validate(players)
    if errs:
        print("[エラー] データ検証NGのため生成を中止:")
        for e in errs:
            print("  -", e)
        sys.exit(1)

    links = load_team_links()
    total = len(players)
    youth = sum(1 for p in players if is_youth(p["u18"]))
    koutairen = total - youth
    home = sum(1 for p in players if p.get("homecoming"))
    linked = 0

    # 集計ボックス
    stats = f"""        <div class="pmc-info" style="margin-bottom:6px;">
          <div><strong>掲載人数</strong>{total}人（{data['updated']}時点）</div>
          <div><strong>U-18の出身</strong>高校サッカー部（高体連）{koutairen}人 ／ クラブユース{youth}人</div>
          <div><strong>アカデミー古巣への復帰内定</strong>{home}人</div>
        </div>"""

    # リーグ→大学ごとにグループ化
    by_league = {}
    for p in players:
        by_league.setdefault(p["league"], {}).setdefault(p["univ"], []).append(p)

    sections = []
    for lg in LEAGUE_ORDER:
        if lg not in by_league:
            continue
        rows = []
        for univ, ps in by_league[lg].items():
            for i, p in enumerate(ps):
                u18html = team_link(p["u18"], links)
                if "<a " in u18html:
                    linked += 1
                mark = " 🏠" if p.get("homecoming") else ""
                note = f'<div class="us-note">※{esc(p["note"])}</div>' if p.get("note") else ""
                ann = p["announced"].replace("-", "/")
                univ_cell = f'<td class="us-univ" rowspan="{len(ps)}">{esc(univ)}</td>' if i == 0 else ""
                rows.append(
                    f'                <tr>{univ_cell}<td class="us-name">{esc(p["name"])}'
                    f'<span class="us-pos">{esc(p["pos"])}</span></td>'
                    f'<td class="us-club">{esc(p["club"])}{mark}</td>'
                    f'<td class="us-career">{team_link(p["u15"], links)} → {u18html}{note}</td>'
                    f'<td class="us-date">{ann}</td></tr>'
                )
        sections.append(f"""        <h3 style="margin:22px 0 10px;"><i class="fas fa-map-location-dot"></i> {lg}リーグの大学</h3>
        <div class="univ-scroll">
        <table class="uv-table us-table">
          <thead><tr><th>大学</th><th class="us-name" style="text-align:left;">選手</th><th>内定先</th><th style="text-align:left;">経歴（U-15 → U-18）</th><th>発表日</th></tr></thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
        </div>""")

    html = stats + "\n" + "\n".join(sections) + "\n"
    src = PAGE.read_text(encoding="utf-8")
    if START not in src or END not in src:
        print("[エラー] マーカーが見つかりません")
        sys.exit(1)
    pre, rest = src.split(START, 1)
    _, post = rest.split(END, 1)
    src = pre + START + "\n" + html + END + post
    # 掲載人数などの本文中の数字も更新
    src = re.sub(r"<!--COUNT-->\d+<!--/COUNT-->", f"<!--COUNT-->{total}<!--/COUNT-->", src)
    src = re.sub(r"<!--KTR-->\d+<!--/KTR-->", f"<!--KTR-->{koutairen}<!--/KTR-->", src)
    src = re.sub(r"<!--YTH-->\d+<!--/YTH-->", f"<!--YTH-->{youth}<!--/YTH-->", src)
    PAGE.write_text(src, encoding="utf-8")
    print(f"OK: {total}人（高体連{koutairen}/ユース{youth}/復帰{home}）・チームページ内部リンク{linked}件")


if __name__ == "__main__":
    main()
