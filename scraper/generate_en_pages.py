#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英語ページ /en/premier-league/ を生成する（2026-09-20 Cowork試作・参考実装）。

- 順位の正本: data/teams.json（プレミアEAST/WESTの leagueRank・勝点など。毎朝の自動更新で入る値）
- 英語名の正本: data/en/team_names_en.json（Coworkが公式表記を確認して置く。自動ローマ字化はしない）
- 出力: en/premier-league/index.html （全体を毎回書き直す）
- 検算（1つでも合わないリーグがあれば、ページを書き換えずに [要確認] を出して終わる＝誤データを載せない）:
    12チームそろっている / 英語名が全員分ある / 順位が1..12で重複なし /
    勝点=勝×3+分 / 試合数=勝+分+敗 / 順位順で勝点が増えない /
    リーグ内の得点合計=失点合計・勝数合計=敗数合計・引分合計が偶数
- sitemap には触らない（登録は generate_interhigh_page.py の static_pages に足す）。
- 使い方: python generate_en_pages.py [出力先ルート]  ※省略時はリポジトリ直下
"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEAMS = ROOT / "data" / "teams.json"
NAMES = ROOT / "data" / "en" / "team_names_en.json"
DOMAIN = "https://u18-soccer.com"
LEAGUES = [("プレミアリーグEAST", "EAST"), ("プレミアリーグWEST", "WEST")]


def esc(s):
    return html.escape(str(s), quote=True)


def collect(teams_data):
    out = {jp: [] for jp, _ in LEAGUES}
    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict):
            continue
        for t in pref.get("teams", []):
            if t.get("league") in out:
                out[t["league"]].append({**t, "_pref": pref_id})
    for jp in out:
        out[jp].sort(key=lambda t: t.get("leagueRank") or 99)
    return out


def validate(ts, names):
    errs = []
    if len(ts) != 12:
        errs.append(f"チーム数が12ではない（{len(ts)}）")
    missing = [t["name"] for t in ts if t["id"] not in names]
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


def row(t, names):
    n = names[t["id"]]
    r = t["leagueRank"]
    gd = t["goalsFor"] - t["goalsAgainst"]
    gd_s = f"+{gd}" if gd > 0 else str(gd)
    cls = ' class="en-final"' if r == 1 else (' class="en-releg"' if r >= 11 else "")
    name = f'<a href="{esc(n["jp_page"])}">{esc(n["en"])}</a>' if n.get("jp_page") else esc(n["en"])
    return (f'<tr{cls}><td class="en-c">{r}</td><td class="en-name">{name}</td>'
            f'<td>{esc(t["_pref"].capitalize())}</td><td class="en-c"><strong>{t["points"]}</strong></td>'
            f'<td class="en-c">{t["played"]}</td><td class="en-c">{t["won"]}</td><td class="en-c">{t["drawn"]}</td>'
            f'<td class="en-c">{t["lost"]}</td><td class="en-c">{t["goalsFor"]}</td><td class="en-c">{t["goalsAgainst"]}</td>'
            f'<td class="en-c">{gd_s}</td></tr>')


def table(label, ts, names, jp_slug):
    rows = "\n".join(row(t, names) for t in ts)
    return f"""
      <section class="lp-section" id="{label.lower()}">
        <h2>Premier League {label}</h2>
        <div class="en-scroll">
        <table class="en-table">
          <thead><tr><th>Pos</th><th class="en-name">Team</th><th>Pref.</th><th>Pts</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th></tr></thead>
          <tbody>
{rows}
          </tbody>
        </table>
        </div>
        <p class="en-note">Japanese version with fixtures, results and top scorers: <a href="/leagues/{jp_slug}/">プレミアリーグ{label}</a></p>
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
    .en-legend span {{ display:inline-block; width:12px; height:12px; margin-right:6px; vertical-align:-1px; }}
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
          <a href="/en/" class="nav-link"><i class="fas fa-book-open"></i> Guide</a>
          <a href="/en/premier-league/" class="nav-link"><i class="fas fa-trophy"></i> Premier League</a>
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
        <span>Premier League {season}</span>
      </nav>

      <h1 class="lp-title">Japan U-18 Premier League {season} Standings</h1>

      <p class="blog-article__summary" style="margin:0 0 20px;padding:14px 18px;background:var(--bg-light,#f1f5fb);border-left:4px solid var(--primary-color,#1e3a8a);border-radius:0 8px 8px 0;font-size:0.97rem;line-height:1.85;">
        The Prince Takamado Trophy JFA U-18 Football Premier League is the top league for under-18 football in Japan.
        24 teams — high-school clubs and J.League club academies — play in two divisions of 12 (EAST and WEST),
        home and away, from April to December. The standings below are updated daily from official JFA data.
      </p>

      <div class="en-legend">
        <div><span style="background:#d4a017"></span>1st place: plays the Premier League Final (EAST winner vs WEST winner) in December to decide the national champion.</div>
        <div><span style="background:var(--danger-color,#dc2626)"></span>11th–12th: relegated to the regional Prince Leagues.</div>
      </div>
{tables}
      <section class="lp-section">
        <h2>How to read this table</h2>
        <p>Pos = position, Pts = points (3 for a win, 1 for a draw), P = played, W/D/L = won/drawn/lost, GF/GA = goals for/against, GD = goal difference. Pref. is the prefecture where the team is based.
        Team names link to our team profiles (in Japanese), which include history, notable alumni and current squads.</p>
        <p>New to Japanese youth football? Start with our <a href="/en/">guide to the U-18 system in Japan</a> — high schools vs club academies, the league pyramid, and the major national tournaments.</p>
        <p>Why do high schools and professional academies play in the same league? See <a href="/en/japan-youth-football-system/">how youth football works in Japan</a>.</p>
      </section>
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


def main():
    out_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    teams = json.loads(TEAMS.read_text(encoding="utf-8"))
    names = json.loads(NAMES.read_text(encoding="utf-8"))["teams"]
    season = str(teams["_meta"]["year"])  # teams.json の _meta.year（年度切替で自動追従）
    by = collect(teams)
    ok = True
    for jp, label in LEAGUES:
        errs = validate(by[jp], names)
        if errs:
            ok = False
            print(f"[要確認] {label}: 検算NGのため英語ページを書き換えません → " + "; ".join(errs))
    if not ok:
        return
    tables = "".join(table(label, by[jp], names, "premier-" + label.lower()) for jp, label in LEAGUES)
    url = f"{DOMAIN}/en/premier-league/"
    title = f"Japan U-18 Premier League {season} Standings (EAST & WEST)"
    desc = (f"Live standings of the {season} Prince Takamado Trophy JFA U-18 Premier League in English: "
            "EAST and WEST tables, updated daily from official JFA data, with links to team profiles.")
    breadcrumb = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "English Guide", "item": f"{DOMAIN}/en/"},
        {"@type": "ListItem", "position": 2, "name": f"Premier League {season}", "item": url}]}, ensure_ascii=False)
    page = PAGE.format(title=esc(title), desc=esc(desc), url=url, breadcrumb=breadcrumb, season=season, tables=tables)
    dest = out_root / "en" / "premier-league" / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")
    print(f"OK: {dest} を書きました（EAST {len(by['プレミアリーグEAST'])}・WEST {len(by['プレミアリーグWEST'])}チーム）")


if __name__ == "__main__":
    main()
