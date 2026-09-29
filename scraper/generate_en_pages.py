#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英語ページ /en/premier-league/ を生成する（2026-09-20 Cowork試作・参考実装）。

- 順位の正本: data/teams.json（プレミアEAST/WESTの leagueRank・勝点など。毎朝の自動更新で入る値）
- 英語名の正本: data/en/team_names_en.json（Coworkが公式表記を確認して置く。自動ローマ字化はしない）
  ⚠️ キーは「data/teams.json のチーム名（日本語）」。2026-09-21にチームidから変更した（idは96チームで未設定・ni010が重複していたため）。
- 出力: en/premier-league/・en/prince-leagues/・en/national-team/・en/pro-signings/・en/inter-high/
        ＋ data/en/teams/*.md があればその英語チームページ en/teams/<slug>/ （すべて毎回全体を書き直す）
- 選手名の正本: data/en/player_names_en.json（JFA英語版・J.LEAGUE英語版の表記のみ。無い選手は日本語のまま出す）
- 検算（1つでも合わないリーグがあれば、ページを書き換えずに [要確認] を出して終わる＝誤データを載せない）:
    12チームそろっている / 英語名が全員分ある / 順位が1..12で重複なし /
    勝点=勝×3+分 / 試合数=勝+分+敗 / 順位順で勝点が増えない /
    リーグ内の得点合計=失点合計・勝数合計=敗数合計・引分合計が偶数
- sitemap には触らない（登録は generate_interhigh_page.py の static_pages に足す）。
- 使い方: python generate_en_pages.py [出力先ルート]  ※省略時はリポジトリ直下
"""
import html
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEAMS = ROOT / "data" / "teams.json"
NAMES = ROOT / "data" / "en" / "team_names_en.json"
PLAYERS = ROOT / "data" / "en" / "player_names_en.json"
NT_YML = ROOT / "data" / "national-team-players.yml"
IH_MD = ROOT / "data" / "tournaments" / "interhigh-final-2026.md"       # YEARLY: 年度が変わったらファイル名を差し替える
IH_EN = ROOT / "data" / "en" / "inter-high-notes.md"
TEAMS_EN_DIR = ROOT / "data" / "en" / "teams"      # 英語チームページの本文（1チーム1ファイル）
PS_YML = ROOT / "data" / "pro-signings.yml"
DOMAIN = "https://u18-soccer.com"
LEAGUES = [("プレミアリーグEAST", "EAST"), ("プレミアリーグWEST", "WEST")]

# プリンスリーグ：地域ごとに（日本語リーグ名, 英語見出し, 日本語ページのslug）
PRINCE_REGIONS = [
    ("Hokkaido", [("プリンスリーグ北海道", "Prince League Hokkaido", "prince-hokkaido")]),
    ("Tohoku", [("プリンスリーグ東北", "Prince League Tohoku", "prince-tohoku")]),
    ("Kanto", [("プリンスリーグ関東1部", "Prince League Kanto Division 1", "prince-kanto-1"),
                ("プリンスリーグ関東2部", "Prince League Kanto Division 2", "prince-kanto-2")]),
    ("Hokushinetsu", [("プリンスリーグ北信越1部", "Prince League Hokushinetsu Division 1", "prince-hokushinetsu-1"),
                       ("プリンスリーグ北信越2部", "Prince League Hokushinetsu Division 2", "prince-hokushinetsu-2")]),
    ("Tokai", [("プリンスリーグ東海", "Prince League Tokai", "prince-tokai")]),
    ("Kansai", [("プリンスリーグ関西1部", "Prince League Kansai Division 1", "prince-kansai-1"),
                 ("プリンスリーグ関西2部", "Prince League Kansai Division 2", "prince-kansai-2")]),
    ("Chugoku", [("プリンスリーグ中国", "Prince League Chugoku", "prince-chugoku")]),
    ("Shikoku", [("プリンスリーグ四国", "Prince League Shikoku", "prince-shikoku")]),
    ("Kyushu", [("プリンスリーグ九州1部", "Prince League Kyushu Division 1", "prince-kyushu-1"),
                 ("プリンスリーグ九州2部", "Prince League Kyushu Division 2", "prince-kyushu-2")]),
]


def esc(s):
    return html.escape(str(s), quote=True)


def collect(teams_data, league_names=None):
    """リーグ名 → そのリーグのチーム（leagueRank順）"""
    if league_names is None:
        league_names = [jp for jp, _ in LEAGUES]
    out = {jp: [] for jp in league_names}
    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict):
            continue
        for t in pref.get("teams", []):
            if t.get("league") in out:
                out[t["league"]].append({**t, "_pref": pref_id})
    for jp in out:
        out[jp].sort(key=lambda t: t.get("leagueRank") or 99)
    return out


def validate(ts, names, expect=None):
    errs = []
    if expect is not None and len(ts) != expect:
        errs.append(f"チーム数が{expect}ではない（{len(ts)}）")
    if len(ts) < 6:
        errs.append(f"チーム数が少なすぎる（{len(ts)}）")
    missing = [t["name"] for t in ts if t["name"] not in names]
    if missing:
        errs.append("英語名が未登録: " + "、".join(missing))
    ranks = [t.get("leagueRank") for t in ts]
    if sorted(ranks) != list(range(1, len(ts) + 1)):
        errs.append(f"順位が1..{len(ts)}の並びになっていない: {ranks}")
    for t in ts:
        w, d, l = t["won"], t["drawn"], t["lost"]
        if t["points"] != w * 3 + d:
            errs.append(f"勝点不一致: {t['name']}")
        if t["played"] != w + d + l:
            errs.append(f"試合数不一致: {t['name']}")
    for a, b in zip(ts, ts[1:]):
        if a["points"] < b["points"]:
            errs.append(f"勝点が順位順で増えている: {b['name']}")
    if sum(t["goalsFor"] for t in ts) != sum(t["goalsAgainst"] for t in ts):
        errs.append("得点合計≠失点合計")
    if sum(t["won"] for t in ts) != sum(t["lost"] for t in ts):
        errs.append("勝数合計≠敗数合計")
    if sum(t["drawn"] for t in ts) % 2:
        errs.append("引分合計が奇数")
    return errs


EN_TEAM_PAGES = {}   # 日本語チーム名 -> /en/teams/<slug>/


def row(t, names, zones=True):
    n = names[t["name"]]
    r = t["leagueRank"]
    gd = t["goalsFor"] - t["goalsAgainst"]
    gd_s = f"+{gd}" if gd > 0 else str(gd)
    cls = ""
    if zones:
        cls = ' class="en-final"' if r == 1 else (' class="en-releg"' if r >= 11 else "")
    link = EN_TEAM_PAGES.get(t["name"]) or n.get("jp_page")
    name = f'<a href="{esc(link)}">{esc(n["en"])}</a>' if link else esc(n["en"])
    return (f'<tr{cls}><td class="en-c">{r}</td><td class="en-name">{name}</td>'
            f'<td>{esc(t["_pref"].capitalize())}</td><td class="en-c"><strong>{t["points"]}</strong></td>'
            f'<td class="en-c">{t["played"]}</td><td class="en-c">{t["won"]}</td><td class="en-c">{t["drawn"]}</td>'
            f'<td class="en-c">{t["lost"]}</td><td class="en-c">{t["goalsFor"]}</td><td class="en-c">{t["goalsAgainst"]}</td>'
            f'<td class="en-c">{gd_s}</td></tr>')


def table(heading, ts, names, jp_slug, jp_label, anchor, level="h2", extra=""):
    """順位表1つ分のHTML。heading=英語見出し、jp_label=日本語ページのリンク文字、anchor=id"""
    rows = "\n".join(row(t, names, zones=(level == "h2")) for t in ts)
    return f"""
      <section class="lp-section" id="{anchor}">
        <{level}>{heading}</{level}>
        <div class="en-scroll">
        <table class="en-table">
          <thead><tr><th>Pos</th><th class="en-name">Team</th><th>Pref.</th><th>Pts</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th></tr></thead>
          <tbody>
{rows}
          </tbody>
        </table>
        </div>
{extra}        <p class="en-note">Japanese version with fixtures, results and top scorers: <a href="/leagues/{jp_slug}/">{jp_label}</a></p>
      </section>"""


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-KTPR94SPYS"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-KTPR94SPYS');
  </script>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-6953440022497606" crossorigin="anonymous"></script>
  <meta name="google-adsense-account" content="ca-pub-6953440022497606">
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">
  <link rel="canonical" href="{url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="U-18 Soccer Japan (u18-soccer.com)">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="{url}">
  <meta property="og:image" content="https://u18-soccer.com/og-image.png">
  <meta property="og:locale" content="en_US">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/css/style.css">
  <script>
    (function() {{
      try {{
        var t = localStorage.getItem('theme');
        if (t === 'light' || t === 'dark') {{ document.documentElement.setAttribute('data-theme', t); }}
      }} catch (e) {{}}
    }})();
  </script>
  <script type="application/ld+json">{breadcrumb}</script>
  <style>
    .en-scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    .en-table {{ width:100%; border-collapse:collapse; font-size:0.9rem; }}
    .en-table th, .en-table td {{ border-bottom:1px solid var(--border-color,#e2e8f0); padding:8px 6px; text-align:left; white-space:nowrap; }}
    .en-table th {{ font-weight:600; opacity:0.85; }}
    .en-table .en-c {{ text-align:center; }}
    .en-table td.en-name {{ white-space:normal; min-width:180px; }}
    .en-table tr.en-final td:first-child {{ box-shadow:inset 4px 0 0 #d4a017; }}
    .en-table tr.en-releg td:first-child {{ box-shadow:inset 4px 0 0 var(--danger-color,#dc2626); }}
    .en-note {{ font-size:0.85rem; opacity:0.8; margin-top:8px; }}
    .en-legend {{ font-size:0.85rem; line-height:1.9; }}
    .en-legend span {{ display:inline-block; width:12px; height:12px; margin-right:6px; vertical-align:-1px; }}{rr_style}
  </style>
</head>
<body>
  <header class="header">
    <div class="container">
      <div class="header-content">
        <div class="site-title">
          <a href="/en/" style="color:white;text-decoration:none;display:inline-flex;align-items:center;gap:10px">
            <i class="fas fa-futbol"></i> U-18 Soccer Japan
          </a>
        </div>
        <nav class="nav">
          <a href="/en/premier-league/" class="nav-link"><i class="fas fa-trophy"></i> Premier</a>
          <a href="/en/prince-leagues/" class="nav-link"><i class="fas fa-list-ol"></i> Prince</a>
          <a href="/en/national-team/" class="nav-link"><i class="fas fa-flag"></i> Japan squads</a>
          <a href="/en/pro-signings/" class="nav-link"><i class="fas fa-arrow-up-right-dots"></i> Turning pro</a>
          <a href="/" class="nav-link" lang="ja"><i class="fas fa-language"></i> 日本語</a>
        </nav>
      </div>
    </div>
  </header>

  <main class="main-content">
    <div class="container">
      <nav class="breadcrumb" aria-label="Breadcrumb">
        <a href="/en/">English Guide</a>
        <span class="breadcrumb__sep">›</span>
        <span>{crumb}</span>
      </nav>

      <h1 class="lp-title">{h1}</h1>

      <p class="blog-article__summary" style="margin:0 0 20px;padding:14px 18px;background:var(--bg-light,#f1f5fb);border-left:4px solid var(--primary-color,#1e3a8a);border-radius:0 8px 8px 0;font-size:0.97rem;line-height:1.85;">
{intro}
      </p>
{legend}{tables}
{tail}
    </div>
  </main>

  <footer class="footer">
    <div class="container">
      <p>&copy; 2025-2026 u18-soccer.com</p>
      <nav class="footer-nav" style="margin-top:12px;">
        <a href="/about.html" lang="ja">About (Japanese)</a> ・
        <a href="/privacy.html" lang="ja">Privacy Policy (Japanese)</a> ・
        <a href="/contact.html" lang="ja">Contact (Japanese)</a>
      </nav>
    </div>
  </footer>
  <script src="/js/main.js"></script>
</body>
</html>
"""


def render_premier(out_root, teams, names, season):
    by = collect(teams)
    for jp, label in LEAGUES:
        errs = validate(by[jp], names, expect=12)
        if errs:
            print(f"[要確認] {label}: 検算NGのため英語ページを書き換えません → " + "; ".join(errs))
            return
    tables = "".join(
        table(f"Premier League {label}", by[jp], names, "premier-" + label.lower(), f"プレミアリーグ{label}", label.lower(),
              extra=results_html("premier-" + label.lower(), jp, f"Premier {label}", teams, names, show_next=True))
        for jp, label in LEAGUES)
    url = f"{DOMAIN}/en/premier-league/"
    title = f"Japan U-18 Premier League {season} Standings (EAST & WEST)"
    desc = (f"Live standings of the {season} Prince Takamado Trophy JFA U-18 Premier League in English: "
            "EAST and WEST tables, updated daily from official JFA data, with links to team profiles.")
    intro = ("        The Prince Takamado Trophy JFA U-18 Football Premier League is the top league for under-18 football in Japan.\n"
             "        24 teams — high-school clubs and J.League club academies — play in two divisions of 12 (EAST and WEST),\n"
             "        home and away, from April to December. The standings, latest results and next fixtures below are updated daily from official JFA data.")
    legend = ('      <div class="en-legend">\n'
              '        <div><span style="background:#d4a017"></span>1st place: plays the Premier League Final (EAST winner vs WEST winner) in December to decide the national champion.</div>\n'
              '        <div><span style="background:var(--danger-color,#dc2626)"></span>11th–12th: relegated to the regional Prince Leagues.</div>\n'
              '      </div>\n')
    tail = ('''      <section class="lp-section">
        <h2>How to read these tables</h2>
        <p>Pos = position, Pts = points (3 for a win, 1 for a draw), P = played, W/D/L = won/drawn/lost, GF/GA = goals for/against, GD = goal difference. Pref. is the prefecture where the team is based.
        Team names link to our English team profiles; the Japanese profiles linked from each of them add history, notable alumni and current squads.</p>
'''
            '        <p>One level below: <a href="/en/prince-leagues/">Prince League standings</a> — the 13 regional leagues that feed into this one.</p>\n'
            '        <p>New to Japanese youth football? See <a href="/en/japan-youth-football-system/">how youth football works in Japan</a> — school clubs, J.League academies, the league pyramid and the national tournaments.</p>\n'
            '      </section>')
    breadcrumb = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "English Guide", "item": f"{DOMAIN}/en/"},
        {"@type": "ListItem", "position": 2, "name": f"Premier League {season}", "item": url}]}, ensure_ascii=False)
    page = PAGE_RR.format(title=esc(title), desc=esc(desc), url=url, breadcrumb=breadcrumb,
                       crumb=f"Premier League {season}", h1=f"Japan U-18 Premier League {season} Standings",
                       intro=intro, legend=legend, tables=tables, tail=tail)
    dest = out_root / "en" / "premier-league" / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")
    print(f"OK: {dest} を書きました（EAST {len(by['プレミアリーグEAST'])}・WEST {len(by['プレミアリーグWEST'])}チーム）")


def render_prince(out_root, teams, names, season):
    jp_names = [jp for _, lgs in PRINCE_REGIONS for jp, _, _ in lgs]
    by = collect(teams, jp_names)
    blocks, jump, skipped, shown = [], [], [], 0
    for region, lgs in PRINCE_REGIONS:
        parts = []
        for jp, label, slug in lgs:
            ts = by.get(jp, [])
            errs = validate(ts, names)
            if errs:
                skipped.append(label)
                print(f"[要確認] {label}: 検算NGのためこのリーグだけ描画しません → " + "; ".join(errs))
                continue
            parts.append(table(label, ts, names, slug, jp, slug, level="h3",
                               extra=results_html(slug, jp, label, teams, names, show_next=False, htag="h4")))
            shown += 1
        if not parts:
            continue
        anchor = region.lower()
        jump.append(f'        <a href="#{anchor}" style="display:inline-block;padding:7px 14px;border-radius:999px;'
                    f'background:var(--primary-color,#1e3a8a);color:#fff;text-decoration:none;font-size:0.9rem;font-weight:600;">{region}</a>')
        blocks.append(f'      <div id="{anchor}">\n        <h2 style="margin:26px 0 6px;">{region}</h2>\n' + "".join(parts) + "      </div>")
    if shown == 0:
        print("[要確認] プリンスリーグは1つも描画できませんでした。ページは書き換えません。")
        return
    tables = ('      <div style="display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 12px;">\n'
              + "\n".join(jump) + "\n      </div>\n" + "\n".join(blocks))
    url = f"{DOMAIN}/en/prince-leagues/"
    title = f"Japan U-18 Prince Leagues {season} Standings (all 13 regional leagues)"
    desc = (f"Standings of the {season} Prince Takamado Trophy JFA U-18 Prince Leagues in English — all 13 leagues "
            "in 9 regions, the second tier of Japanese youth football, updated daily from official JFA data.")
    intro = ("        The Prince Leagues are the second tier of under-18 football in Japan: 13 leagues across 9 regions,\n"
             "        played from April to December by high-school clubs and J.League academies alike.\n"
             "        Most of the schools that reach the winter All Japan High School Soccer Tournament play here,\n"
             "        so these tables are the best guide to how strong those teams are. Standings and the latest results are updated daily from official JFA data.")
    legend = ('      <p class="en-note" style="margin:0 0 10px;">In December the leading Prince League teams enter a play-off for four places in the\n'
              '        <a href="/en/premier-league/">Premier League</a>, and the bottom teams are relegated to their prefectural leagues. The number of places\n'
              '        changes from year to year, so no promotion or relegation zones are marked here.</p>\n')
    tail = ('''      <section class="lp-section">
        <h2>How to read these tables</h2>
        <p>Pos = position, Pts = points (3 for a win, 1 for a draw), P = played, W/D/L = won/drawn/lost, GF/GA = goals for/against, GD = goal difference. Pref. is the prefecture where the team is based.
        Team names link to our English team profiles; the Japanese profiles linked from each of them add history, notable alumni and current squads.</p>
'''
            '        <p>One level above: <a href="/en/premier-league/">Premier League standings</a> (EAST and WEST).</p>\n'
            '        <p>New to Japanese youth football? See <a href="/en/japan-youth-football-system/">how youth football works in Japan</a> — school clubs, J.League academies, the league pyramid and the national tournaments.</p>\n'
            '      </section>')
    breadcrumb = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "English Guide", "item": f"{DOMAIN}/en/"},
        {"@type": "ListItem", "position": 2, "name": f"Prince Leagues {season}", "item": url}]}, ensure_ascii=False)
    page = PAGE_RR.format(title=esc(title), desc=esc(desc), url=url, breadcrumb=breadcrumb,
                       crumb=f"Prince Leagues {season}", h1=f"Japan U-18 Prince Leagues {season} Standings",
                       intro=intro, legend=legend, tables=tables, tail=tail)
    dest = out_root / "en" / "prince-leagues" / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")
    n = sum(len(by[jp]) for _, lgs in PRINCE_REGIONS for jp, _, _ in lgs)
    print(f"OK: {dest} を書きました（{shown}リーグ・{n}チーム" + (f"／スキップ {', '.join(skipped)}" if skipped else "") + "）")


# ---------------------------------------------------------------------
# 代表・プロ内定ページ（YAML → 英語ページ）
# ---------------------------------------------------------------------
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


# ---------------------------------------------------------------------
# 直近の試合結果（英語）  2026-09-27 追加（Kei依頼：プレミア・プリンスの英語ページにも出す）
# ---------------------------------------------------------------------
# - どの節を出すかは日本語リーグページと同じ部品（recent_results.pick_rounds）で決める
#   ＝日本語ページと英語ページで「直近の節」が食い違わない。
# - 試合データ（data/league_matches/<slug>.json）のチーム名は JFA の短い表記（「流通経済大柏」
#   「近江(B)」など）で、teams.json の名前（英語名辞書のキー）と違う。そこで
#   そのリーグのチームの name＋aliases を正規化して突き合わせる（_resolver）。
# - ⚠️ 1チームでも英語名に解決できなければ、そのリーグの試合結果ブロックだけ出さない
#   （[要確認] を出す）。順位表は今まで通り出る＝日本語が英語ページに混ざらない。
# - プリンスは直近節のみ（13リーグあるので次節まで出すとページが長くなりすぎる／
#   延期分の再試合だけの節が「次節」に選ばれることがあり英語だと説明しにくい）。
# - 会場名は日本語しか無いので出さない。キックオフ時刻は次節にだけ「JST」付きで出す。
import unicodedata                                    # noqa: E402
from datetime import date as _date                    # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recent_results import pick_rounds, _is_played    # noqa: E402

# 正規化だけでは届かない略称（試合データ側の表記 → teams.json の名前）
MATCH_NAME_FIX = {
    "旭川実": "旭川実業高校",
    "ジェフユナイテッド千葉U-18": "ジェフユナイテッド市原・千葉U-18",
}
_WD_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _nk(s):
    """チーム名の正規化キー。2nd/3rd/(B) は別チームなので落とさず「2nd」にそろえる。"""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\s・．\.]", "", s)
    s = s.replace("(B)", "2nd").replace("セカンド", "2nd")
    return re.sub(r"(高等学校|高等部|高校|学校)(?=(2nd|3rd)?$)", "", s)


def _resolver(teams_data, league_jp):
    """試合データのチーム名 → teams.json の名前（解決できなければ None）を返す関数を作る。"""
    in_league, anywhere = {}, {}
    for pref in teams_data.values():
        if not isinstance(pref, dict):
            continue
        for t in pref.get("teams", []):
            for k in [t["name"]] + list(t.get("aliases") or []):
                anywhere.setdefault(_nk(k), t["name"])
                if t.get("league") == league_jp:
                    in_league.setdefault(_nk(k), t["name"])

    def resolve(name):
        k = _nk(MATCH_NAME_FIX.get(name, name))
        if k in in_league:
            return in_league[k]
        m = re.fullmatch(r"(.+?)(2nd|3rd)", k)
        if m and m.group(1) in anywhere:          # 例: 流通経済大柏(B) → 流通経済大学付属柏高校 + 2nd
            return in_league.get(_nk(anywhere[m.group(1)]) + m.group(2))
        return None
    return resolve


def _en_day(iso):
    try:
        y, mo, d = (int(x) for x in str(iso).split("-")[:3])
        return _date(y, mo, d)
    except Exception:
        return None


def _en_range(isos):
    ds = sorted({d for d in (_en_day(x) for x in isos) if d})
    if not ds:
        return ""
    a, b = ds[0], ds[-1]
    if a == b:
        return f"{_WD_EN[a.weekday()]} {a.day} {MONTHS[a.month - 1]} {a.year}"
    if a.month == b.month:
        return f"{a.day}&ndash;{b.day} {MONTHS[a.month - 1]} {a.year}"
    return f"{a.day} {MONTHS[a.month - 1]} &ndash; {b.day} {MONTHS[b.month - 1]} {b.year}"


def _en_short(iso):
    d = _en_day(iso)
    return f"{_WD_EN[d.weekday()]} {d.day} {MONTHS[d.month - 1][:3]}" if d else "Date TBC"


def _en_team(jp, names):
    n = names[jp]
    link = EN_TEAM_PAGES.get(jp) or n.get("jp_page")
    # 「U-18」の途中（ハイフン）でスマホ改行されないよう、U-18 だけ改行禁止で包む
    txt = re.sub(r"(U-\d+)", r'<span class="en-nw">\1</span>', esc(n["en"]))
    return f'<a href="{esc(link)}">{txt}</a>' if link else txt


def _en_match_row(m, names, resolve, with_ko=False, note=""):
    h, a = _en_team(resolve(m["home"]), names), _en_team(resolve(m["away"]), names)
    if _is_played(m):
        hs, as_ = int(m["hs"]), int(m["as"])
        hc = " en-rr-win" if hs > as_ else ""
        ac = " en-rr-win" if as_ > hs else ""
        mid = f'<span class="en-rr-score">{hs}<span class="en-rr-dash">-</span>{as_}</span>'
        sub = ""
    else:
        hc = ac = ""
        mid = '<span class="en-rr-vs">vs</span>'
        ko = str(m.get("kickoff") or "").strip() if with_ko else ""
        bits = [esc(note)] if note else []
        if re.fullmatch(r"\d{1,2}:\d{2}", ko):
            bits.append(f"Kick-off {esc(ko)} JST")
        sub = f'<span class="en-rr-sub">{" &middot; ".join(bits)}</span>' if bits else ""
    return (f'<li class="en-rr-row"><span class="en-rr-date">{_en_short(m.get("date"))}</span>'
            f'<span class="en-rr-team en-rr-home{hc}">{h}</span>{mid}'
            f'<span class="en-rr-team en-rr-away{ac}">{a}</span>{sub}</li>')


def results_html(slug, league_jp, label, teams_data, names, show_next, htag="h3"):
    """リーグ1つ分の「Latest results（＋Next fixtures）」。出せないときは ''。"""
    r = pick_rounds(slug)
    if r is None:
        return ""
    resolve = _resolver(teams_data, league_jp)
    shown = r["last_matches"] + (r["next_matches"] if show_next and r["next_md"] is not None else []) \
        + ((r.get("makeups") or []) if show_next else [])
    bad = sorted({n for m in shown for n in (m["home"], m["away"])
                  if not resolve(n) or resolve(n) not in names})
    if bad:
        print(f"[要確認] {label}: 試合結果のチーム名を英語名に解決できないため、試合結果だけ出しません → " + "、".join(bad))
        return ""
    played, pending = r["last_played"], r["pending"]
    rows = [_en_match_row(m, names, resolve) for m in played]
    rows += [_en_match_row(m, names, resolve) for m in pending]
    meta = [_en_range([m.get("date") for m in played]),
            f"{len(played)} match" + ("es" if len(played) != 1 else "")]
    if pending:
        meta.append(f"{len(pending)} not yet played")
    out = [f'        <{htag} class="en-rr-h">Latest results &mdash; Matchday {r["last_md"]}</{htag}>',
           f'        <p class="en-note" style="margin:0 0 8px;">{" &middot; ".join(x for x in meta if x)}</p>',
           '        <ul class="en-rr-list">', "\n".join("          " + x for x in rows), "        </ul>"]
    if show_next and r["next_md"] is not None:
        nxt = [m for m in r["next_matches"] if not _is_played(m)]
        if nxt:
            rng = _en_range([m.get("date") for m in nxt]) or "dates to be confirmed"
            out += [f'        <{htag} class="en-rr-h">Next fixtures &mdash; Matchday {r["next_md"]} <span class="en-note">({rng})</span></{htag}>',
                    '        <ul class="en-rr-list">',
                    "\n".join("          " + _en_match_row(m, names, resolve, with_ko=True) for m in nxt),
                    "        </ul>"]
    mk = (r.get("makeups") or []) if show_next else []
    if mk:
        out += [f'        <{htag} class="en-rr-h">Rescheduled matches <span class="en-note">(played before the next matchday)</span></{htag}>',
                '        <ul class="en-rr-list">',
                "\n".join("          " + _en_match_row(m, names, resolve, with_ko=True, note=f"Matchday {m['md']}, rescheduled") for m in mk),
                "        </ul>"]
    upd = r["data"].get("lastUpdated", "")
    src = r["data"].get("source", "")
    host = str(src).split("//")[-1].split("/")[0].removeprefix("www.") if src else ""
    bits = []
    if host:
        bits.append(f'Source: <a href="{esc(src)}" target="_blank" rel="nofollow noopener">{esc(host)}</a>'
                    + (" (official JFA data)" if host == "jfa.jp" else ""))
    if upd:
        bits.append(f"updated {esc(str(upd)[:10])}")
    if bits:
        out.append(f'        <p class="en-note">{" &middot; ".join(bits)}</p>')
    return "\n".join(out) + "\n"


RR_STYLE = """
    .en-rr-h {{ font-size:1.02rem; margin:22px 0 4px; }}
    .en-rr-list {{ list-style:none; margin:0 0 6px; padding:0; border:1px solid var(--border-color,#e2e8f0); border-radius:10px; overflow:hidden; background:var(--bg-white,#fff); }}
    .en-rr-row {{ display:grid; grid-template-columns:92px 1fr auto 1fr; align-items:center; gap:8px; padding:10px 14px; border-bottom:1px solid var(--border-color,#e2e8f0); }}
    .en-rr-list .en-rr-row:last-child {{ border-bottom:none; }}
    .en-rr-date {{ font-size:0.82rem; opacity:0.75; white-space:nowrap; }}
    .en-rr-team {{ font-size:0.95rem; line-height:1.35; }}
    .en-rr-home {{ text-align:right; }}
    .en-rr-away {{ text-align:left; }}
    .en-rr-team a {{ color:inherit; text-decoration:none; border-bottom:1px dotted var(--border-color,#cbd5e1); }}
    .en-rr-win {{ font-weight:700; }}
    .en-rr-score {{ font-weight:700; font-size:1.08rem; color:var(--accent-color,#2563eb); white-space:nowrap; min-width:58px; text-align:center; }}
    .en-rr-dash {{ margin:0 5px; opacity:0.6; font-weight:400; }}
    .en-rr-vs {{ font-size:0.85rem; opacity:0.7; min-width:58px; text-align:center; }}
    .en-rr-sub {{ grid-column:1 / -1; font-size:0.78rem; opacity:0.7; text-align:center; }}
    .en-nw {{ white-space:nowrap; }}
    @media (max-width:600px) {{
      .en-rr-row {{ grid-template-columns:1fr auto 1fr; gap:6px; padding:9px 10px; row-gap:2px; }}
      .en-rr-date {{ grid-column:1 / -1; order:-1; }}
      .en-rr-team {{ font-size:0.9rem; }}
    }}"""
PAGE_RR = PAGE.replace("{rr_style}", RR_STYLE)   # 試合結果を載せるページ（プレミア・プリンス）だけCSSを足す
PAGE = PAGE.replace("{rr_style}", "")           # それ以外の英語ページは今までと1文字も変えない


def club_html(jp_name, names, extra):
    """クラブ名（日本語表記）→ 英語名のHTML。英語名が無ければ None を返す（＝ページを作らない）。"""
    rec = names.get(jp_name) or extra.get(jp_name)
    if not rec:
        return None
    en = esc(rec["en"])
    # [2026-09-25] リンク先は ①英語チームページ → ②日本語チームページ（jp_page）→ ③リンクなし。
    #   順位表の row() と同じ考え方。別名（source: "alias-of:◯◯"）は別名の先の名前でも英語ページを引く
    #   （例: 大津高 → 大津高校、流通経済大学付属柏高 → 流通経済大学付属柏高校）。
    page = EN_TEAM_PAGES.get(jp_name)
    src = rec.get("source") or ""
    if not page and isinstance(src, str) and src.startswith("alias-of:"):
        page = EN_TEAM_PAGES.get(src[len("alias-of:"):])
    page = page or rec.get("jp_page")
    return f'<a href="{esc(page)}">{en}</a>' if page else en


def player_html(jp_name, players):
    rec = players.get(jp_name)
    if rec:
        return esc(rec["en"]), False
    return f'<span lang="ja">{esc(jp_name)}</span>', True


def timing_en(s):
    """加入時期の日本語表記を英語に。想定外の書き方は空欄にする（推測しない）。"""
    if not s:
        return ""
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月プロ契約", s)
    if m:
        return f"Signed pro contract in {MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月", s)
    if m:
        return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    m = re.fullmatch(r"(\d{4})/(\d{2})シーズン(昇格|加入)?", s)
    if m:
        base = f"{m.group(1)}/{m.group(2)} season"
        return base + (" (promoted from the academy)" if m.group(3) == "昇格" else "")
    m = re.fullmatch(r"(\d{4})シーズン加入", s)
    if m:
        return f"{m.group(1)} season"
    if s == "時期未発表":
        return "Not announced"
    if re.fullmatch(r"(\d{4})年", s):
        return s[:4]
    return ""


def _same_name(a, b):
    """日本語版（generate_national_team_page._same）と同じ比較：NFKC・空白除去で同じ名前か"""
    import national_team as nt
    return bool(a) and nt._norm(a) == nt._norm(b or "")


def render_national_team(out_root, names, extra, players, season):
    data = yaml.safe_load(NT_YML.read_text(encoding="utf-8"))
    blocks, jump, jp_only = [], [], 0
    # [2026-09-25] label_en の無いカテゴリ（SAMURAI BLUE・U-21・U-19）は英語ページに出さない。
    #   所属が海外クラブ・大学で英語名が未登録のため、そのまま回すと下の「未登録なら書き換えない」で
    #   英語の代表ページ全体が更新されなくなる。英語名をそろえたら label_en を足せば出る。
    skipped = [c["code"] for c in data["categories"] if not c.get("label_en")]
    if skipped:
        print(f"[en] 代表ページ: 英語名未設定のため飛ばした: {', '.join(skipped)}")
    for cat in data["categories"]:
        if not cat.get("label_en"):
            continue
        label = cat.get("label_en") or cat["code"].upper()
        # [2026-09-25] 経歴型（table: career＝SAMURAI BLUE・U-21・U-19）は日本語版と同じく
        #   Club／University／U-18 の列にする。U-15 列は英語版では出さない（Kei決定：町クラブ・市立中学は
        #   公式の英語表記がほぼ無い）。ユース型（U-18・U-17・U-16）の表は従来のまま。
        career = cat.get("table") == "career"
        has_univ = career and any(pl.get("univ") for pl in cat["players"])
        rows = []
        for pl in cat["players"]:
            club = club_html(pl["club"], names, extra)
            if club is None:
                print(f"[要確認] 代表ページ: クラブの英語名が未登録 → {pl['club']}（ページは書き換えません）")
                return
            if career:
                cells = [club]
                if has_univ:
                    uv = pl.get("univ")
                    if uv:
                        rec = names.get(uv) or extra.get(uv)
                        if not rec:
                            print(f"[要確認] 代表ページ: 大学の英語名が未登録 → {uv}（ページは書き換えません）")
                            return
                        cell = esc(rec["en"])            # 大学はリンクしない
                        if _same_name(uv, pl["club"]):
                            cell += ' <span class="en-note">(current)</span>'
                    else:
                        cell = "&ndash;"
                    cells.append(cell)
                if pl.get("u18"):
                    u18 = club_html(pl["u18"], names, extra)
                    if u18 is None:
                        print(f"[要確認] 代表ページ: クラブの英語名が未登録 → {pl['u18']}（ページは書き換えません）")
                        return
                elif _same_name(pl.get("u15"), pl["club"]):
                    u18 = "&ndash;"                      # いま U-15 在籍＝U-18 の所属は無い
                else:
                    u18 = f'{club} <span class="en-note">(current)</span>'
                cells.append(u18)
                name, is_jp = player_html(pl["name"], players)
                jp_only += 1 if is_jp else 0
                no = pl.get("no", "")
                rows.append(f'<tr><td class="en-c">{esc(no) if no != "" else "&ndash;"}</td>'
                            f'<td class="en-c">{esc(pl["pos"])}</td><td class="en-name">{name}</td>'
                            + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
                continue
            # 2026-09-25 以降は u18 に書く（origin は互換のため読むだけ）
            origin = pl.get("u18") or pl.get("origin")
            if origin:
                org = club_html(origin, names, extra)
                if org is None:
                    print(f"[要確認] 代表ページ: クラブの英語名が未登録 → {origin}（ページは書き換えません）")
                    return
                club = f"{club} <span class=\"en-note\">← {org}</span>"
            name, is_jp = player_html(pl["name"], players)
            jp_only += 1 if is_jp else 0
            no = pl.get("no", "")
            rows.append(f'<tr><td class="en-c">{esc(no) if no != "" else "&ndash;"}</td>'
                        f'<td class="en-c">{esc(pl["pos"])}</td><td class="en-name">{name}</td><td>{club}</td></tr>')
        anchor = cat["code"]
        jump.append(f'        <a href="#{anchor}" style="display:inline-block;padding:7px 14px;border-radius:999px;'
                    f'background:var(--primary-color,#1e3a8a);color:#fff;text-decoration:none;font-size:0.9rem;font-weight:600;">{esc(label)}</a>')
        meta = " &middot; ".join(x for x in [esc(cat.get("event_en", "")), esc(cat.get("period_en", ""))] if x)
        note = f'<p class="en-note">{esc(cat["age_note_en"])}</p>' if cat.get("age_note_en") else ""
        src = f'<p class="en-note">Source: <a href="{esc(cat["source"])}" target="_blank" rel="noopener">JFA official announcement (in Japanese)</a></p>'
        head = ("<th>Club</th>" + ("<th>University</th>" if has_univ else "")
                + "<th>U-18 (high school / academy)</th>") if career else "<th>Club / school</th>"
        blocks.append(f"""
      <section class="lp-section" id="{anchor}">
        <h2>{esc(label)}</h2>
        <p class="en-note">{meta}</p>
        {note}
        <div class="en-scroll">
        <table class="en-table">
          <thead><tr><th>No.</th><th>Pos</th><th class="en-name">Player</th>{head}</tr></thead>
          <tbody>
{chr(10).join("            " + r for r in rows)}
          </tbody>
        </table>
        </div>
        {src}
      </section>""")
    url = f"{DOMAIN}/en/national-team/"
    title = f"Japan National Team Squads {season}: SAMURAI BLUE, U-21, U-19, U-18, U-17 and U-16"
    desc = ("The latest Japan national team squads from SAMURAI BLUE down to U-16, in English — with each player's current club, "
            "university and the high school or J.League academy he came through. Compiled from JFA official announcements.")
    intro = ("        These are the most recent call-ups for every Japan men's national team, from SAMURAI BLUE down to the U-16s, compiled from the JFA's official announcements.\n"
             "        For SAMURAI BLUE, the U-21s and the U-19s, the table also shows the university (if any) and the U-18 team — a high school club or a J.League academy — each player came through, so you can trace which schools and academies produce Japan internationals.\n"
             "        For the U-18 and younger squads, a player listed with a professional club and an arrow (&larr;) came through the youth team shown after the arrow.")
    legend = ""
    tail = ('''      <section class="lp-section">
        <h2>Notes</h2>
'''
            '        <p>Where a player has no official English spelling published by the JFA or the J.League, the name is shown in Japanese.</p>\n'
            '        <p>See also: <a href="/en/pro-signings/">players turning professional</a>, <a href="/en/premier-league/">Premier League standings</a> and '
            '<a href="/en/japan-youth-football-system/">how youth football works in Japan</a>.</p>\n      </section>')
    breadcrumb = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "English Guide", "item": f"{DOMAIN}/en/"},
        {"@type": "ListItem", "position": 2, "name": "Japan national team squads", "item": url}]}, ensure_ascii=False)
    tables = ('      <div style="display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 12px;">\n'
              + "\n".join(jump) + "\n      </div>" + "".join(blocks))
    page = PAGE.format(title=esc(title), desc=esc(desc), url=url, breadcrumb=breadcrumb,
                       crumb="Japan national teams", h1="Japan National Team Squads — SAMURAI BLUE to U-16",
                       intro=intro, legend=legend, tables=tables, tail=tail)
    dest = out_root / "en" / "national-team" / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")
    shown = [c for c in data["categories"] if c.get("label_en")]
    n = sum(len(c["players"]) for c in shown)
    print(f"OK: {dest} を書きました（{len(shown)}カテゴリ・{n}人／うち日本語表記のまま {jp_only}人）")


def render_pro_signings(out_root, names, extra, players, season):
    data = yaml.safe_load(PS_YML.read_text(encoding="utf-8"))
    groups = [("naitei", "Provisional signings (joining after graduation)",
               "These players are still at their high school or club academy. Their professional clubs have announced that they will join."),
              ("pro", "Already under professional contract",
               "These players have already signed professional contracts while still in the U-18 age group. Most are registered as type-2 players, "
               "which lets them play for the first team while remaining with the academy.")]
    blocks, jp_only = [], 0
    for status, heading, lead in groups:
        rows = []
        for pl in [p for p in data["signings"] if p["status"] == status]:
            team = club_html(pl["team"], names, extra)
            dest_club = club_html(pl["dest"], names, extra)
            if team is None or dest_club is None:
                print(f"[要確認] プロ内定ページ: クラブの英語名が未登録 → {pl['team'] if team is None else pl['dest']}（ページは書き換えません）")
                return
            name, is_jp = player_html(pl["name"], players)
            jp_only += 1 if is_jp else 0
            cat = "High school" if pl.get("cat") == "高体連" else "Club academy"
            num = f'#{pl["num"]}' if pl.get("num") else ""
            extra_mark = ' <span class="en-note">type-2</span>' if pl.get("type2") else ""
            rows.append(f'<tr><td class="en-c">{esc(pl["pos"])}</td><td class="en-name">{name}{extra_mark}</td>'
                        f'<td>{team}</td><td class="en-c">{cat}</td><td>{dest_club} {esc(num)}</td>'
                        f'<td>{esc(timing_en(pl.get("timing", "")))}</td></tr>')
        blocks.append(f"""
      <section class="lp-section" id="{status}">
        <h2>{heading} <span class="en-note">({len(rows)})</span></h2>
        <p>{lead}</p>
        <div class="en-scroll">
        <table class="en-table">
          <thead><tr><th>Pos</th><th class="en-name">Player</th><th>Current team</th><th>Route</th><th>Joining</th><th>When</th></tr></thead>
          <tbody>
{chr(10).join("            " + r for r in rows)}
          </tbody>
        </table>
        </div>
      </section>""")
    url = f"{DOMAIN}/en/pro-signings/"
    title = f"Japanese Youth Players Turning Professional ({data.get('season', season)})"
    desc = (f"Players from Japanese high schools and J.League academies joining professional clubs for {data.get('season', season)}, in English: "
            "provisional signings and those already under contract, each checked against the clubs' own announcements.")
    intro = ("        Every year dozens of players sign for professional clubs straight out of the U-18 age group in Japan.\n"
             "        The list below separates players who will join after graduating from those who have already signed a professional contract\n"
             "        while still playing for their high school or academy. Each entry has been checked against the club's own announcement.")
    legend = ""
    tail = ('''      <section class="lp-section">
        <h2>Notes</h2>
'''
            '        <p>&ldquo;type-2&rdquo; marks a player registered to play J.League matches for the first team while remaining in the academy. '
            'That list is not complete: clubs announce type-2 registrations in batches.</p>\n'
            '        <p>Where a player has no official English spelling published by the JFA or the J.League, the name is shown in Japanese.</p>\n'
            '        <p>See also: <a href="/en/national-team/">Japan national team squads (SAMURAI BLUE to U-16)</a> and <a href="/en/japan-youth-football-system/">how youth football works in Japan</a>.</p>\n'
            '      </section>')
    breadcrumb = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "English Guide", "item": f"{DOMAIN}/en/"},
        {"@type": "ListItem", "position": 2, "name": "Players turning professional", "item": url}]}, ensure_ascii=False)
    page = PAGE.format(title=esc(title), desc=esc(desc), url=url, breadcrumb=breadcrumb,
                       crumb="Players turning professional", h1=f"Japanese Youth Players Turning Professional ({data.get('season', season)})",
                       intro=intro, legend=legend, tables="".join(blocks), tail=tail)
    dest = out_root / "en" / "pro-signings" / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")
    print(f"OK: {dest} を書きました（{len(data['signings'])}人／うち日本語表記のまま {jp_only}人）")


PREFS_EN = {
    "北海道": "Hokkaido", "青森": "Aomori", "岩手": "Iwate", "宮城": "Miyagi", "秋田": "Akita", "山形": "Yamagata",
    "福島": "Fukushima", "茨城": "Ibaraki", "栃木": "Tochigi", "群馬": "Gunma", "埼玉": "Saitama", "千葉": "Chiba",
    "東京": "Tokyo", "神奈川": "Kanagawa", "新潟": "Niigata", "富山": "Toyama", "石川": "Ishikawa", "福井": "Fukui",
    "山梨": "Yamanashi", "長野": "Nagano", "岐阜": "Gifu", "静岡": "Shizuoka", "愛知": "Aichi", "三重": "Mie",
    "滋賀": "Shiga", "京都": "Kyoto", "大阪": "Osaka", "兵庫": "Hyogo", "奈良": "Nara", "和歌山": "Wakayama",
    "鳥取": "Tottori", "島根": "Shimane", "岡山": "Okayama", "広島": "Hiroshima", "山口": "Yamaguchi",
    "徳島": "Tokushima", "香川": "Kagawa", "愛媛": "Ehime", "高知": "Kochi", "福岡": "Fukuoka", "佐賀": "Saga",
    "長崎": "Nagasaki", "熊本": "Kumamoto", "大分": "Oita", "宮崎": "Miyazaki", "鹿児島": "Kagoshima", "沖縄": "Okinawa",
}


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def appearance_en(note):
    """「(4大会連続10回目)」→「10th appearance」／「(初出場)」→「First appearance」。読めない書き方は空欄。"""
    if not note:
        return ""
    if "初出場" in note:
        return "First appearance"
    m = re.search(r"(\d+)(?:回目|度目)", note)
    return f"{_ordinal(int(m.group(1)))} appearance" if m else ""


def md_to_html(text):
    """英語メモの簡易Markdown（段落・「- 」箇条書き・表・**太字**）をHTMLに。"""
    out, bullets, rows = [], [], []

    def inline(t):
        t = esc(t).replace("&amp;", "&")
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)

    def flush_bullets():
        if bullets:
            out.append('<ul style="padding-left:1.5em;">' + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    def flush_table():
        if not rows:
            return
        head, body = rows[0], [r for r in rows[1:] if not re.fullmatch(r"[\s|:-]+", "|".join(r))]
        th = "".join(f"<th>{inline(c)}</th>" for c in head)
        tb = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
        out.append('<div class="en-scroll"><table class="en-table"><thead><tr>' + th
                   + "</tr></thead><tbody>" + tb + "</tbody></table></div>")
        rows.clear()

    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            flush_bullets(); flush_table(); continue
        if line.startswith("|") and line.endswith("|"):
            flush_bullets()
            rows.append([c.strip() for c in line.strip("|").split("|")])
            continue
        flush_table()
        if line.startswith("- "):
            bullets.append(inline(line[2:]))
        else:
            flush_bullets()
            out.append(f"<p>{inline(line)}</p>")
    flush_bullets(); flush_table()
    return "\n        ".join(out)


def _section(md, heading):
    m = re.search(r"^##\s*" + re.escape(heading) + r".*?$(.*?)(?=^##\s|\Z)", md, re.M | re.S)
    return m.group(1) if m else ""


def render_interhigh(out_root, names, extra, season):
    src = IH_MD.read_text(encoding="utf-8")
    fm = yaml.safe_load(src.split("---")[1])
    body = src
    en_src = IH_EN.read_text(encoding="utf-8")
    en_fm = yaml.safe_load(en_src.split("---")[1])
    year = en_fm.get("title_year", season)

    def team(jp):
        h = club_html(jp, names, extra)
        if h is None:
            print(f"[要確認] インターハイ英語ページ: 学校の英語名が未登録 → {jp}（ページは書き換えません）")
        return h

    # 各県代表
    reps = []
    for line in _section(body, "各県代表").splitlines():
        m = re.match(r"-\s*([^:：]+)[:：]\s*(.+)", line.strip())
        if not m:
            continue
        pref = PREFS_EN.get(m.group(1).strip(), m.group(1).strip())
        for chunk in m.group(2).split("、"):
            note = re.search(r"[(（](.+?)[)）]\s*$", chunk)
            jp = re.sub(r"[(（].*?[)）]\s*$", "", chunk).strip()
            h = team(jp)
            if h is None:
                return
            reps.append((pref, h, appearance_en(note.group(1) if note else "")))

    # ラウンド（準々決勝以降）
    rounds = []
    for jp_head, en_head in [("準々決勝", "Quarter-finals"), ("準決勝", "Semi-finals"), ("決勝", "Final")]:
        rows = []
        for line in _section(body, jp_head).splitlines():
            m = re.match(r"-\s*(.+?)\s+([0-9]+-[0-9]+(?:\(PK[0-9]+-[0-9]+\))?)\s+(.+)", line.strip())
            if not m:
                continue
            a, sc, b = team(m.group(1).strip()), m.group(2), team(m.group(3).strip())
            if a is None or b is None:
                return
            sc = sc.replace("(PK", " (pens ")
            rows.append(f'<tr><td class="en-name" style="text-align:right;">{a}</td>'
                        f'<td class="en-c"><strong>{esc(sc)}</strong></td><td class="en-name">{b}</td></tr>')
        if rows:
            rounds.append((en_head, rows))

    results_html = ""
    for head, rows in rounds:
        results_html += f"""
      <section class="lp-section">
        <h2>{head}</h2>
        <div class="en-scroll">
        <table class="en-table">
          <tbody>
{chr(10).join("            " + r for r in rows)}
          </tbody>
        </table>
        </div>
      </section>"""

    rep_rows = "\n".join(
        f'            <tr><td>{esc(p)}</td><td class="en-name">{h}</td><td class="en-note">{esc(a)}</td></tr>'
        for p, h, a in reps)
    reps_html = f"""
      <section class="lp-section" id="teams">
        <h2>The {len(reps)} qualified schools</h2>
        <p>One school per prefecture, with a second place for Tokyo, Kanagawa, Osaka and the host prefecture.</p>
        <div class="en-scroll">
        <table class="en-table">
          <thead><tr><th>Prefecture</th><th class="en-name">School</th><th>Appearances</th></tr></thead>
          <tbody>
{rep_rows}
          </tbody>
        </table>
        </div>
      </section>"""

    origins_html = f"""
      <section class="lp-section" id="where-players-come-from">
        <h2>Where the players come from</h2>
        {md_to_html(_section(en_src, "origins"))}
      </section>"""

    url = f"{DOMAIN}/en/inter-high/"
    title = f"Inter-High {year}: Japan's Summer High School Football Championship"
    desc = (f"The {year} Inter-High School Championships in English: how Japan's summer high-school tournament works, "
            "the results from the quarter-finals on, all qualified schools, and where their players were developed.")
    intro = "        " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", md_to_html(_section(en_src, "intro")))).strip()
    facts = ""
    if en_fm.get("period_en"):
        facts = (f'      <p class="en-note">{esc(en_fm["period_en"])} &middot; {esc(en_fm.get("venue_en", ""))} &middot; '
                 f'{len(reps)} schools, knockout, 70-minute matches</p>\n')
    result_html = f"""
      <section class="lp-section" id="result">
        <h2>The {year} final</h2>
        {md_to_html(_section(en_src, "result"))}
      </section>"""
    tail = ('''      <section class="lp-section">
        <h2>Notes</h2>
'''
            '        <p>Full bracket, every round and the top scorers (in Japanese): '
            f'<a href="/tournaments/interhigh-{year}/" lang="ja">インターハイ{year}</a>.</p>\n'
            '        <p>See also: <a href="/en/japan-youth-football-system/">how youth football works in Japan</a> and '
            '<a href="/en/premier-league/">Premier League standings</a>.</p>\n      </section>')
    breadcrumb = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "English Guide", "item": f"{DOMAIN}/en/"},
        {"@type": "ListItem", "position": 2, "name": f"Inter-High {year}", "item": url}]}, ensure_ascii=False)
    page = PAGE.format(title=esc(title), desc=esc(desc), url=url, breadcrumb=breadcrumb,
                       crumb=f"Inter-High {year}", h1=f"Inter-High {year}: Japan's Summer High School Championship",
                       intro=intro, legend=facts, tables=result_html + results_html + origins_html + reps_html, tail=tail)
    dest = out_root / "en" / "inter-high" / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")
    print(f"OK: {dest} を書きました（{len(reps)}校・{sum(len(r) for _, r in rounds)}試合）")


def render_team_pages(out_root, teams, names, extra, season):
    """data/en/teams/*.md から英語のチーム紹介ページを作る。"""
    if not TEAMS_EN_DIR.exists():
        return
    live = {}
    for pref_id, pref in teams.items():
        if not isinstance(pref, dict):
            continue
        for t in pref.get("teams", []):
            live[t["name"]] = {**t, "_pref": pref_id}
    done = 0
    for md_path in sorted(TEAMS_EN_DIR.glob("*.md")):
        raw = md_path.read_text(encoding="utf-8")
        fm = yaml.safe_load(raw.split("---")[1])
        jp = fm["jp_name"]
        rec = names.get(jp) or extra.get(jp)
        if not rec:
            print(f"[要確認] 英語チームページ: 英語名が辞書にない -> {jp}（{md_path.name} は作りません）")
            continue
        slug = fm.get("slug") or md_path.stem
        t = live.get(jp)
        facts = [fm.get("prefecture_en", ""),
                 f"founded {fm['founded']}" if fm.get("founded") else "",
                 f"{fm['squad_size']} players" if fm.get("squad_size") else "",
                 f"head coach {fm['head_coach_en']}" if fm.get("head_coach_en") else ""]
        facts = " &middot; ".join(esc(x) for x in facts if x)
        legend = f'      <p class="en-note">{facts}</p>\n' if facts else ""
        standing = ""
        if t and t.get("leagueRank"):
            lg = t.get("league", "")
            lg_en = ("Premier League EAST" if lg == "プレミアリーグEAST" else
                     "Premier League WEST" if lg == "プレミアリーグWEST" else
                     "Prince League" if "プリンス" in lg else lg)
            lg_link = ("/en/premier-league/" if "プレミア" in lg else
                       "/en/prince-leagues/" if "プリンス" in lg else "")
            where = f'<a href="{lg_link}">{esc(lg_en)}</a>' if lg_link else esc(lg_en)
            r = t["leagueRank"]
            suf = "st" if r == 1 else "nd" if r == 2 else "rd" if r == 3 else "th"
            standing = f"""
      <section class="lp-section">
        <h2>{season} season</h2>
        <p>Currently <strong>{r}{suf}</strong> in the {where} with <strong>{t.get('points', 0)} points</strong>
        from {t.get('played', 0)} matches ({t.get('won', 0)}W {t.get('drawn', 0)}D {t.get('lost', 0)}L,
        {t.get('goalsFor', 0)}-{t.get('goalsAgainst', 0)}). Updated daily.</p>
      </section>"""
        blocks = [("style", "Playing style"), ("honours", "Honours"), ("history", "History"),
                  ("model", "The Ryukei model" if slug == "ryukei-kashiwa" else "Development pathway"),
                  ("alumni", "Former players"), ("squad", f"Players to watch in {season}")]
        body = standing
        for key, head in blocks:
            sec = _section(raw, key)
            if not sec.strip():
                continue
            body += f"""
      <section class="lp-section" id="{key}">
        <h2>{head}</h2>
        {md_to_html(sec)}
      </section>"""
        url = f"{DOMAIN}/en/teams/{slug}/"
        jp_link = rec.get("jp_page") or f"/teams/{slug}/"
        tail = ('      <section class="lp-section">\n        <h2>Notes</h2>\n'
                f'        <p>Full profile in Japanese, with the current squad list and every result: '
                f'<a href="{esc(jp_link)}" lang="ja">{esc(jp)}</a>.</p>\n'
                '        <p>Where a player has no official English spelling published by the JFA or the J.League, the name is shown in Japanese.</p>\n'
                '        <p>See also: <a href="/en/premier-league/">Premier League standings</a> and '
                '<a href="/en/japan-youth-football-system/">how youth football works in Japan</a>.</p>\n'
                '      </section>')
        breadcrumb = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "English Guide", "item": f"{DOMAIN}/en/"},
            {"@type": "ListItem", "position": 2, "name": rec["en"], "item": url}]}, ensure_ascii=False)
        intro = "        " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", md_to_html(_section(raw, "intro")))).strip()
        page = PAGE.format(title=esc(fm.get("title") or rec["en"]), desc=esc(fm.get("description", "")),
                           url=url, breadcrumb=breadcrumb, crumb=esc(rec["en"]), h1=esc(rec["en"]),
                           intro=intro, legend=legend, tables=body, tail=tail)
        dest = out_root / "en" / "teams" / slug / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page, encoding="utf-8")
        done += 1
        print(f"OK: {dest} を書きました")


# ---------------------------------------------------------------------
# プリンスリーグ所属チームの「短い英語チームページ」  2026-09-29 追加（Kei依頼・二段構えの1段目）
# ---------------------------------------------------------------------
# - data/en/teams/<slug>.md（手書きの詳しいページ）が無いプリンス所属チームについて、
#   データだけから自動で1枚作る。手書きの文章は一切ない＝事実の誤りが入り込む余地を作らない。
# - 載せるもの：①定型の紹介2文 ②今季の順位 ③今季のリーグ戦の全試合（英語名に引けないチームが
#   1つでもあればこのブロックだけ出さない） ④全国大会の記録（tournaments_data.yml・
#   premier_final_history.yml・league_history_full.yml から自動抽出。記録が0件なら節ごと出さない）
# - 人名は1つも出さない（Kei決定 2026-09-29：公式英語表記がある人だけ＝短いページには人名の欄が無い）。
# - slug は日本語チームページと同じ（英語名辞書の jp_page の末尾）。
# - 2nd/3rd は作らない。英語ページ内のリンクは親チームの英語ページへ向ける（Kei決定 2026-09-29）。
# - あとで data/en/teams/<slug>.md を置けば、そのチームはこの短いページではなく詳しいページになる（2段目）。
TOURN_YML = ROOT / "data" / "tournaments_data.yml"
PFINAL_YML = ROOT / "data" / "premier_final_history.yml"
LHIST_YML = ROOT / "data" / "league_history_full.yml"
PROFILES_DIR = ROOT / "data" / "team-profiles"

TOURN_EN = {
    "all_japan_highschool": "All Japan High School Soccer Tournament",
    "interhigh": "Inter-High School Championships",
    "club_youth_u18": "Japan Club Youth (U-18) Championship",
    "j_youth_cup": "J.League Youth Cup",
}
STAGE_EN = [("優勝", "Winners"), ("準優勝", "Runners-up"), ("ベスト4", "Semi-finals"),
            ("ベスト8", "Quarter-finals"), ("都道府県代表", "Qualified")]
SHORT_PAGES = {}   # 日本語チーム名 -> slug（短いページを作るチーム）


def _league_info():
    """日本語リーグ名 -> (英語名, 試合データのslug, 英語順位表のリンク, 段の説明)。
    プレミアも入れておく＝12月の参入戦でプリンスから上がったチームに手書きページが無くても、
    翌年そのURLが消えない（短いページのまま Premier League として出続ける）。"""
    info = {"プレミアリーグEAST": ("Premier League EAST", "premier-east", "/en/premier-league/#east", "premier"),
            "プレミアリーグWEST": ("Premier League WEST", "premier-west", "/en/premier-league/#west", "premier")}
    for region, lgs in PRINCE_REGIONS:
        for jp, label, slug in lgs:
            info[jp] = (label, slug, f"/en/prince-leagues/#{region.lower()}", "prince")
    return info


def _jp_slug(rec):
    return str(rec.get("jp_page") or "").strip("/").split("/")[-1]


def _is_second(jp):
    return bool(re.search(r"(2nd|3rd)$", jp.replace(" ", "")))


def _parent_of(jp):
    return re.sub(r"\s*(2nd|3rd)$", "", jp)


def plan_short_pages(teams, names, hand_written):
    """短いページを作るチームと、2nd/3rd のリンク先を EN_TEAM_PAGES に登録する（main の最初で呼ぶ）。"""
    for pref in teams.values():
        if not isinstance(pref, dict):
            continue
        for t in pref.get("teams", []):
            jp = t["name"]
            if t.get("league") not in _league_info() or jp in hand_written or _is_second(jp):
                continue
            rec = names.get(jp)
            slug = _jp_slug(rec or {})
            if not rec or not slug:
                print(f"[要確認] 短い英語チームページ: 英語名または日本語ページが辞書にない -> {jp}（作りません）")
                continue
            SHORT_PAGES[jp] = slug
            EN_TEAM_PAGES[jp] = f"/en/teams/{slug}/"
    # 2nd/3rd は親チームの英語ページへ（親に英語ページが無ければ今まで通り日本語ページ）
    for pref in teams.values():
        if not isinstance(pref, dict):
            continue
        for t in pref.get("teams", []):
            jp = t["name"]
            if _is_second(jp) and _parent_of(jp) in EN_TEAM_PAGES:
                EN_TEAM_PAGES[jp] = EN_TEAM_PAGES[_parent_of(jp)]


def _team_keys(jp, teams_rec, slug):
    """全国大会データと突き合わせるための名前キー（teams.json の名前・aliases＋日本語ページの name/short_name/aliases）。"""
    ks = {jp} | set((teams_rec or {}).get("aliases") or [])
    p = PROFILES_DIR / f"{slug}.md"
    if p.exists():
        try:
            fm = yaml.safe_load(p.read_text(encoding="utf-8").split("---")[1]) or {}
            for k in ("name", "short_name"):
                if fm.get(k):
                    ks.add(str(fm[k]))
            ks |= {str(a) for a in (fm.get("aliases") or [])}
        except Exception:
            pass
    keys = {_nk(k) for k in ks if k}
    # 「県立徳島商業高校」⇔「徳島商業高校」のように、設置者の冠だけ違う表記も同じ学校として拾う
    return keys | {re.sub(r"^(県立|府立|都立|道立|市立|私立)", "", k) for k in keys}


def _ranges(years):
    ys, out = sorted(set(years)), []
    for y in ys:
        if out and y == out[-1][1] + 1:
            out[-1][1] = y
        else:
            out.append([y, y])
    return ", ".join(str(a) if a == b else f"{a}&ndash;{b}" for a, b in out)


def national_record(slug, keys, tourn, pfinal, lhist):
    """(year, 大会, 成績) のリストと、Premier League の在籍年、プリンス優勝年を返す。"""
    rows = []
    for tk, label in TOURN_EN.items():
        for year, res in (tourn.get(tk) or {}).items():
            if not isinstance(res, dict):
                continue
            for stage, st_en in STAGE_EN:
                v = res.get(stage)
                vs = v if isinstance(v, list) else [v] if v else []
                if any(_nk(x["name"] if isinstance(x, dict) else x) in keys for x in vs):
                    rows.append((int(year), label, st_en))
                    break          # 1大会1年につき最上位の成績だけ
    for f in (pfinal or {}).get("finals", []):
        ch = (f.get("champion") or {}).get("team")
        for side in ("east_winner", "west_winner"):
            tm = (f.get(side) or {}).get("team")
            if tm and _nk(tm) in keys:
                rows.append((int(f["year"]), "U-18 Premier League Final (national play-off)",
                             "Winners" if ch and _nk(ch) in keys else "Runners-up"))
    premier, prince_titles = [], []
    for key, lg in (lhist or {}).items():
        for era in lg.get("eras", []):
            cols = era.get("cols") or []
            for s in era.get("seasons", []):
                blocks = s.get("rows") or []
                for bi, blk in enumerate(blocks):
                    for pos, tm in enumerate(blk.get("teams", [])):
                        hit = tm.get("link") == slug or _nk(tm.get("name", "")) in keys
                        if not hit or _is_second(str(tm.get("name", ""))):
                            continue
                        if key.startswith("premier"):
                            premier.append(int(s["year"]))
                        # 優勝＝最上位の部（rows[0]）の1番目。A/Bブロック制・2020年の特別大会は
                        # 見出しが「1位」なので対象外（どちらが優勝か表から決められない）。
                        elif (pos == 0 and bi == 0 and cols and cols[0] == "優勝"
                              and (len(blocks) == 1 or "部" in str(era.get("title", "")))):
                            prince_titles.append((int(s["year"]), lg.get("label", "")))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return rows, sorted(set(premier)), sorted(set(prince_titles))


def season_results_html(jp, league_jp, league_slug, teams_data, names):
    """そのチームの今季リーグ戦を新しい順に全部。英語名に引けない相手が1チームでもあれば ''。"""
    path = ROOT / "data" / "league_matches" / f"{league_slug}.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    resolve = _resolver(teams_data, league_jp)
    mine = [m for m in data.get("matches", []) if jp in (resolve(m.get("home")), resolve(m.get("away")))]
    if not mine:
        return ""
    bad = sorted({n for m in mine for n in (m["home"], m["away"]) if not resolve(n) or resolve(n) not in names})
    if bad:
        print(f"[要確認] 短い英語チームページ {jp}: 試合のチーム名を英語名に解決できないため試合一覧を出しません → " + "、".join(bad))
        return ""
    played = sorted([m for m in mine if _is_played(m)], key=lambda m: (str(m.get("date") or ""), m.get("md") or 0), reverse=True)
    upcoming = sorted([m for m in mine if not _is_played(m)], key=lambda m: (str(m.get("date") or "9999"), m.get("md") or 0))
    w = d = l = 0
    for m in played:
        mine_s, opp_s = (int(m["hs"]), int(m["as"])) if resolve(m["home"]) == jp else (int(m["as"]), int(m["hs"]))
        w += mine_s > opp_s; d += mine_s == opp_s; l += mine_s < opp_s
    out = []
    if played:
        out += [f'        <h3 class="en-rr-h">Results</h3>',
                f'        <p class="en-note" style="margin:0 0 8px;">{len(played)} played &middot; {w}W {d}D {l}L &middot; newest first</p>',
                '        <ul class="en-rr-list">',
                "\n".join("          " + _en_match_row(m, names, resolve, note="") .replace(
                    '<span class="en-rr-date">', f'<span class="en-rr-date">MD{m.get("md")} &middot; ', 1) for m in played),
                "        </ul>"]
    if upcoming:
        out += ['        <h3 class="en-rr-h">Remaining fixtures</h3>',
                '        <ul class="en-rr-list">',
                "\n".join("          " + _en_match_row(m, names, resolve, with_ko=True).replace(
                    '<span class="en-rr-date">', f'<span class="en-rr-date">MD{m.get("md")} &middot; ', 1) for m in upcoming),
                "        </ul>"]
    src = data.get("source", "")
    host = str(src).split("//")[-1].split("/")[0].removeprefix("www.") if src else ""
    if host:
        out.append(f'        <p class="en-note">Source: <a href="{esc(src)}" target="_blank" rel="nofollow noopener">{esc(host)}</a>'
                   + (" (official JFA data)" if host == "jfa.jp" else "")
                   + (f' &middot; updated {esc(str(data.get("lastUpdated"))[:10])}' if data.get("lastUpdated") else "") + "</p>")
    return "\n".join(out) + "\n"


def render_short_team_pages(out_root, teams, names, season):
    if not SHORT_PAGES:
        return
    tourn = yaml.safe_load(TOURN_YML.read_text(encoding="utf-8")) if TOURN_YML.exists() else {}
    pfinal = yaml.safe_load(PFINAL_YML.read_text(encoding="utf-8")) if PFINAL_YML.exists() else {}
    lhist = yaml.safe_load(LHIST_YML.read_text(encoding="utf-8")) if LHIST_YML.exists() else {}
    league_info = _league_info()
    live = {}
    for pref_id, pref in teams.items():
        if isinstance(pref, dict):
            for t in pref.get("teams", []):
                live[t["name"]] = {**t, "_pref": pref_id}
    done = 0
    for jp, slug in sorted(SHORT_PAGES.items(), key=lambda x: x[1]):
        rec, t = names[jp], live.get(jp) or {}
        en = rec["en"]
        lg_jp = t.get("league", "")
        if lg_jp not in league_info:
            print(f"[要確認] 短い英語チームページ {jp}: リーグ {lg_jp} が PRINCE_REGIONS にない（作りません）")
            continue
        lg_en, lg_slug, lg_link, tier = league_info[lg_jp]
        pref_en = t["_pref"].capitalize()            # 辞書 _meta.prefecture_rule と同じ
        pref_where = pref_en if t["_pref"] in ("hokkaido", "tokyo") else f"{pref_en} Prefecture"
        is_club = bool(re.search(r"U-1\d|U1\d|Youth", en)) and "School" not in en
        kind = "J.League club academy" if is_club else "High school team"
        if is_club:
            intro = (f"{esc(en)} (<span lang=\"ja\">{esc(jp)}</span>) is the under-18 academy team of a professional club "
                     f"based in {esc(pref_where)}, Japan.")
        else:
            intro = (f"{esc(en)} (<span lang=\"ja\">{esc(jp)}</span>) is a high school football team "
                     f"from {esc(pref_where)}, Japan.")
        if tier == "prince":
            intro += (f" In {season} it plays in the <a href=\"{lg_link}\">{esc(lg_en)}</a>, "
                      "one of the regional Prince Leagues that form the second tier of under-18 league football in Japan, "
                      "directly below the national <a href=\"/en/premier-league/\">Premier League</a>.")
        else:
            intro += (f" In {season} it plays in the <a href=\"{lg_link}\">{esc(lg_en)}</a>, "
                      "the top tier of under-18 league football in Japan.")
        legend = f'      <p class="en-note">{esc(pref_en)} &middot; {esc(lg_en)} &middot; {kind}</p>\n'
        body = ""
        if t.get("leagueRank"):
            r = t["leagueRank"]
            suf = "st" if r == 1 else "nd" if r == 2 else "rd" if r == 3 else "th"
            body += f"""
      <section class="lp-section">
        <h2>{season} season</h2>
        <p>Currently <strong>{r}{suf}</strong> in the <a href="{lg_link}">{esc(lg_en)}</a> with <strong>{t.get('points', 0)} points</strong>
        from {t.get('played', 0)} matches ({t.get('won', 0)}W {t.get('drawn', 0)}D {t.get('lost', 0)}L,
        {t.get('goalsFor', 0)}-{t.get('goalsAgainst', 0)}). Updated daily.</p>
{season_results_html(jp, lg_jp, lg_slug, teams, names)}      </section>"""
        keys = _team_keys(jp, t, slug)
        rows, premier, titles = national_record(slug, keys, tourn, pfinal, lhist)
        if rows or premier or titles:
            parts = []
            if premier:
                parts.append(f"<p><strong>Premier League (top tier):</strong> {_ranges(premier)}.</p>")
            if titles:
                parts.append("<p><strong>Prince League champions:</strong> " + ", ".join(str(y) for y, _ in titles) + ".</p>")
            if rows:
                tb = "".join(f"<tr><td>{y}</td><td class=\"en-name\">{esc(c)}</td><td>{esc(s)}</td></tr>" for y, c, s in rows)
                parts.append('<div class="en-scroll"><table class="en-table"><thead><tr><th>Year</th><th>Competition</th>'
                             f'<th>Result</th></tr></thead><tbody>{tb}</tbody></table></div>')
            parts.append('<p class="en-note">National tournaments are listed from 2016 (the years recorded on this site); '
                         '&ldquo;Qualified&rdquo; means the team won its prefectural qualifying tournament. '
                         'Premier League seasons are listed from the league&rsquo;s start in 2011, Prince League titles from 2003.</p>')
            body += f"""
      <section class="lp-section" id="record">
        <h2>National record</h2>
        {chr(10).join('        ' + p for p in parts).strip()}
      </section>"""
        url = f"{DOMAIN}/en/teams/{slug}/"
        jp_link = rec.get("jp_page")
        tail = ('      <section class="lp-section">\n        <h2>Notes</h2>\n'
                f'        <p>This is a short English profile built from the data on this site. The full profile in Japanese — history, playing style, notable alumni and the current squad — is here: '
                f'<a href="{esc(jp_link)}" lang="ja">{esc(jp)}</a>.</p>\n'
                f'        <p>See also: <a href="{lg_link}">all {"Prince League" if tier == "prince" else "Premier League"} standings</a> and '
                '<a href="/en/japan-youth-football-system/">how youth football works in Japan</a>.</p>\n'
                '      </section>')
        title = f"{en} — {season} season, results and national record"
        desc = (f"{en} ({pref_en}) in English: {season} {lg_en} position and every league result, updated daily, "
                "plus the team's record in Japan's national youth tournaments.")
        breadcrumb = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "English Guide", "item": f"{DOMAIN}/en/"},
            {"@type": "ListItem", "position": 2, "name": f"Prince Leagues {season}" if tier == "prince" else f"Premier League {season}",
             "item": f"{DOMAIN}/en/prince-leagues/" if tier == "prince" else f"{DOMAIN}/en/premier-league/"},
            {"@type": "ListItem", "position": 3, "name": en, "item": url}]}, ensure_ascii=False)
        page = PAGE_RR.format(title=esc(title), desc=esc(desc), url=url, breadcrumb=breadcrumb, crumb=esc(en),
                              h1=esc(en), intro="        " + intro, legend=legend, tables=body, tail=tail)
        dest = out_root / "en" / "teams" / slug / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page, encoding="utf-8")
        done += 1
    print(f"OK: 短い英語チームページ {done} 枚を書きました（en/teams/<slug>/）")


def main():
    out_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    teams = json.loads(TEAMS.read_text(encoding="utf-8"))
    names_all = json.loads(NAMES.read_text(encoding="utf-8"))
    names = names_all["teams"]
    extra = names_all.get("clubs_extra", {})
    players = json.loads(PLAYERS.read_text(encoding="utf-8"))["players"]
    season = str(teams["_meta"]["year"])  # teams.json の _meta.year（年度切替で自動追従）
    if TEAMS_EN_DIR.exists():
        for md_path in TEAMS_EN_DIR.glob("*.md"):
            fm0 = yaml.safe_load(md_path.read_text(encoding="utf-8").split("---")[1])
            EN_TEAM_PAGES[fm0["jp_name"]] = f"/en/teams/{fm0.get('slug') or md_path.stem}/"
    plan_short_pages(teams, names, hand_written=set(EN_TEAM_PAGES))   # 2026-09-29 プリンスの短いページ（先にリンク先を登録）
    render_premier(out_root, teams, names, season)
    render_prince(out_root, teams, names, season)
    render_national_team(out_root, names, extra, players, season)
    render_pro_signings(out_root, names, extra, players, season)
    render_interhigh(out_root, names, extra, season)
    render_team_pages(out_root, teams, names, extra, season)
    render_short_team_pages(out_root, teams, names, season)


if __name__ == "__main__":
    main()
