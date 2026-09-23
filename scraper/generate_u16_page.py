#!/usr/bin/env python3
"""
U-16（高校1年生年代）ルーキーリーグ ハブページ生成（2026-09-21 新設）
====================================================================
data/u16/leagues-2026.json を読み込み、/u16/ ページを生成する。

- 9地域20リーグの順位表を描画
- 12月の全国大会（MIZUNO CHAMPIONSHIP U-16ルーキーリーグ）ページへの導線
- チーム名は data/team-profiles にページがあれば自動で内部リンク
- sitemap.xml への登録（idempotent）

★安全装置：順位表は「勝点=勝×3+分」「試合数=勝+分+敗」「得点合計=失点合計」
  「勝数合計=敗数合計」「順位順で勝点が単調非増加」を生成時に検算し、
  合わないリーグは**そのリーグだけ描画しない**（誤データを載せない）。

★JSONの divisions の並び順が、そのまま地域内の表示順になる（1部を先に置く）。
依存：標準ライブラリのみ
"""
import json
import re
from html import escape as html_escape
from pathlib import Path
from datetime import datetime as _dt, timedelta as _td, timezone as _tz

# 各リーグの順位表の直下に置く得点ランキング（1ページに20枚並ぶので compact 版）。
# 既存の render_scorer_ranking_html() は id と <style> を吐くので使えない。
from scorer_table import render_scorer_compact_html


def jst_today():
    return _dt.now(_tz(_td(hours=9))).date()


BASE_DIR = Path(__file__).parent.parent
DOMAIN = "https://u18-soccer.com"
GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"

SOURCE = BASE_DIR / "data" / "u16" / "leagues-2026.json"
PROFILES = BASE_DIR / "data" / "team-profiles"
OUT_DIR = BASE_DIR / "u16"
CANONICAL = f"{DOMAIN}/u16/"
CS_PAGE = "/tournaments/rookie-league-championship-2026/"

REGION_ORDER = ["北海道", "東北", "関東", "北信越", "東海", "関西", "中国", "四国", "九州"]

# 地域ごとの短い解説。全国大会（16枠）への出場権の決まり方は各地域の大会概要に基づく。
REGION_NOTES = {
    "北海道": "1部・2部・3部の3層19チーム。1部は6チームの2回戦総当たりで、1セルに2試合分のスコアが入ります。"
            "全国大会の出場枠の決め方は大会概要に記載がありません（2025年度は1枠）。",
    "東北": "1部・2部とも12チーム。大会概要に「1部リーグ優勝チーム、準優勝チームは、東北代表として全国大会の出場権を獲得する」と明記されています。",
    "関東": "A・B・Cの3リーグ各10チーム＝30チームで、国内最大規模。2026年度は3枠。"
          "A1位・A2位が自動的に代表となり、第3代表はB1位とC1位のプレーオフ勝者がA3位と対戦して決まります。",
    "北信越": "1部・2部とも12チーム。2枠。出場枠は「過去5年間の成績をポイント制にして各地域に配分」する仕組みです。",
    "東海": "1部・2部各10チーム。全国大会の出場枠の決め方は大会概要に記載がありません（2025年度は2枠）。",
    "関西": "G1・G2各10チーム。「G1リーグの1位は関西代表として全国大会の出場権を獲得する」＝1枠です。下部に登竜門U-16リーグがあります。",
    "中国": "N1が10チーム、N2が9チーム。「N-1の1位＋プレーオフ勝者」が全国大会へ進む2枠です。",
    "四国": "S1・S2の2層。「S1の1位チームが全国大会の出場権を得る」＝1枠。S2はPK決着の試合があり、当サイトでは勝点上は引き分けとして扱っています。",
    "九州": "球蹴男児U-16リーグ。D1・D2各10チーム。「D1リーグの1位、2位が自動的に九州第一・第二代表として全国大会の出場権を獲得する」＝2枠です。",
}


def norm_team(s):
    s = re.sub(r"\s", "", s or "")
    return s.replace("高等学校", "高校").replace("髙", "高")


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
        for key in ("name", "short_name"):
            nm = re.search(rf'^{key}:\s*["\']?([^"\'\n]+)', fm, re.M)
            if nm:
                names.append(nm.group(1).strip())
        am = re.search(r"^aliases:\s*\n((?:\s*-\s*.+\n?)+)", fm, re.M)
        if am:
            names += [re.sub(r"^\s*-\s*", "", ln).strip().strip('"\'')
                      for ln in am.group(1).strip().splitlines()]
        for n in names:
            if n:
                links.setdefault(norm_team(n), md.stem)
    return links


def team_link(name, links):
    """ルーキーリーグの表記は略称（例：市立船橋）。高校/高等学校の有無を吸収して探す。"""
    key = norm_team(name)
    for cand in (key, key + "高校", key + "高等学校",
                 key[:-2] if key.endswith("高校") else key):
        slug = links.get(cand)
        if slug:
            return f'<a href="/teams/{slug}/">{html_escape(name)}</a>'
    return html_escape(name)


def verify(div):
    """検算。問題があれば理由のリストを返す（空なら健全）。"""
    problems = []
    teams = div.get("teams", [])
    if not teams:
        return ["チームが0件"]
    gf = sum(t["gf"] for t in teams)
    ga = sum(t["ga"] for t in teams)
    if gf != ga:
        problems.append(f"得点合計{gf} != 失点合計{ga}")
    w = sum(t["w"] for t in teams)
    l = sum(t["l"] for t in teams)
    if w != l:
        problems.append(f"勝数合計{w} != 敗数合計{l}")
    prev_pts = None
    for t in teams:
        if t["pts"] != t["w"] * 3 + t["d"]:
            problems.append(f"{t['name']}: 勝点が勝×3+分と不一致")
        if t["p"] != t["w"] + t["d"] + t["l"]:
            problems.append(f"{t['name']}: 試合数が勝分敗の合計と不一致")
        if prev_pts is not None and t["pts"] > prev_pts:
            problems.append(f"{t['name']}: 順位の並びで勝点が増えている")
        prev_pts = t["pts"]
    return problems


def render_table(div, links):
    rows = []
    n = len(div["teams"])
    for t in div["teams"]:
        gd = t["gf"] - t["ga"]
        gd_s = f"+{gd}" if gd > 0 else str(gd)
        cls = ""
        if t["rank"] == 1:
            cls = ' class="u16-top"'
        elif t["rank"] == n:
            cls = ' class="u16-bottom"'
        rows.append(
            f'<tr{cls}><td class="u16-rank">{t["rank"]}</td>'
            f'<td class="u16-name">{team_link(t["name"], links)}</td>'
            f'<td>{t["p"]}</td><td>{t["w"]}</td><td>{t["d"]}</td><td>{t["l"]}</td>'
            f'<td>{t["gf"]}</td><td>{t["ga"]}</td><td>{gd_s}</td>'
            f'<td class="u16-pts">{t["pts"]}</td></tr>'
        )
    if div.get("sourceUrl"):
        src = (f'<a href="{html_escape(div["sourceUrl"])}" target="_blank" rel="noopener">'
               f'{html_escape(div.get("sourceLabel", "出典"))}</a>')
    else:
        src = html_escape(div.get("sourceLabel", ""))
    note = f'<br>{html_escape(div["note"])}' if div.get("note") else ""
    return f'''
          <div class="u16-div">
            <h3>{html_escape(div["name"])}</h3>
            <p class="u16-asof">{html_escape(div.get("asof", ""))}</p>
            <div class="u16-scroll">
            <table class="u16-table">
              <thead><tr><th>順</th><th>チーム</th><th>試</th><th>勝</th><th>分</th><th>敗</th><th>得</th><th>失</th><th>差</th><th>点</th></tr></thead>
              <tbody>
{chr(10).join("                " + r for r in rows)}
              </tbody>
            </table>
            </div>
            <p class="u16-src">出典：{src}{note}</p>
{render_scorer_compact_html("u16-" + div["id"])}
          </div>'''


def render_regions(data, links):
    by_region = {}
    for div in data["divisions"]:
        problems = verify(div)
        if problems:
            print(f"⚠ [検算NG] {div['id']}: " + " / ".join(problems) + " → このリーグは掲載しません")
            continue
        by_region.setdefault(div["region"], []).append(div)

    blocks = []
    for region in REGION_ORDER:
        divs = by_region.get(region)
        if not divs:
            continue
        note = REGION_NOTES.get(region, "")
        note_html = f'<p class="u16-region-note">{html_escape(note)}</p>' if note else ""
        tables = "\n".join(render_table(d, links) for d in divs)
        blocks.append(f'''
      <section class="lp-section" id="region-{REGION_ORDER.index(region) + 1}">
        <h2><i class="fas fa-map-location-dot"></i> {html_escape(region)}</h2>
        {note_html}
        <div class="u16-divs">{tables}
        </div>
      </section>''')
    return "\n".join(blocks), by_region


def render_nav(by_region):
    pills = []
    for region in REGION_ORDER:
        if region in by_region:
            n = len(by_region[region])
            pills.append(f'<a href="#region-{REGION_ORDER.index(region) + 1}">{html_escape(region)}'
                         f'<span class="u16-cnt">{n}</span></a>')
    return "\n          ".join(pills)


CHAMPIONS = [
    ("2025年度", "履正社", "神村学園", "2-1"),
    ("2024年度", "前橋育英", "尚志", "2-1"),
    ("2023年度", "鹿島学園", "大津", "2-1"),
    ("2022年度", "帝京長岡", "神村学園", "4-0"),
    ("2021年度", "静岡学園", "尚志", "0-0(PK5-3)"),
    ("2020年度", "静岡学園", "藤枝東", "3-1"),
    ("2019年度", "桐光学園", "大津", "5-1"),
]


def build_html(data, links):
    regions_html, by_region = render_regions(data, links)
    nav = render_nav(by_region)
    total_divs = sum(len(v) for v in by_region.values())
    total_teams = sum(len(d["teams"]) for v in by_region.values() for d in v)
    updated = data.get("updated", jst_today().isoformat())

    champ_rows = "\n".join(
        f'            <tr><td>{y}</td><td class="u16-name">{team_link(w, links)}</td>'
        f'<td class="u16-name">{team_link(r, links)}</td><td>{html_escape(s)}</td></tr>'
        for y, w, r, s in CHAMPIONS)

    faq = [
        ("ルーキーリーグとは何ですか？",
         "高校1年生年代（U-16）を対象にした、全国9地域（北海道・東北・関東・北信越・東海・関西・中国・四国・九州）の通年リーグ戦です。"
         "高円宮杯 JFA U-18サッカーリーグが主に2・3年生を含むトップチームの戦いであるのに対し、"
         "ルーキーリーグは入学したばかりの1年生が公式戦の経験を積む場として位置づけられています。"
         "各地域リーグの上位チームが、12月の全国大会「MIZUNO CHAMPIONSHIP U-16ルーキーリーグ」に集まります。"),
        ("12月の全国大会はどんな大会ですか？",
         "MIZUNO CHAMPIONSHIP U-16ルーキーリーグ（ミズノチャンピオンシップU-16 ルーキーリーグ）です。"
         "9地域から選ばれた16チームが静岡県裾野市の時之栖スポーツセンターに集まり、"
         "4チーム×4ブロックの予選リーグを行い、各ブロック1位の4チームが準決勝・決勝を戦います。"
         "2025年度は12月13〜15日に開催され、履正社が神村学園を2-1で破って優勝しました。"),
        ("全国大会の出場枠はどう決まりますか？",
         "2024・2025年度は 北海道1・東北2・北信越2・関東3・東海2・関西1・中国2・四国1・九州2 の計16枠でした。"
         "枠数は固定ではなく、「過去5年間の成績をポイント制にして各地域の出場枠を決定する」仕組みです（北信越の大会概要より）。"
         "2026年度の枠の全体内訳は、現時点で大会公式サイトに掲載されていません。"),
        ("順位表の数字はどこから取っていますか？",
         "大会公式サイト（u16-rookie-league.com）の各リーグの星取表です。"
         "公式の星取表には勝点や勝敗数の集計欄がないため、当サイトでは星取表の全セルから勝点・勝敗数・得失点を自前で計算しています。"
         "掲載前に「星取表の上下でスコアが裏返しになっているか」「勝点＝勝×3＋分」「リーグ内の得点合計＝失点合計」などを"
         "機械的に検算し、一致したデータだけを掲載しています。"),
        ("U-18（高校年代トップ）との関係は？",
         "ルーキーリーグで結果を残した1年生は、2年目以降にプレミアリーグ・プリンスリーグ・都道府県リーグといった"
         "高円宮杯 JFA U-18サッカーリーグのトップチームへ上がっていきます。"
         "つまりルーキーリーグの順位表は、1〜2年後のU-18勢力図を占う先行指標にあたります。"),
    ]
    faq_json = json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]
    }, ensure_ascii=False)
    breadcrumb_json = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "U-16ルーキーリーグ", "item": CANONICAL},
        ]}, ensure_ascii=False)

    faq_html = "\n".join(
        f'        <h3>{html_escape(q)}</h3>\n        <p>{html_escape(a)}</p>' for q, a in faq)

    title = "U-16 ルーキーリーグ2026 順位表｜9地域20リーグ・高校1年生年代"
    desc = (f"高校1年生年代（U-16）のルーキーリーグ2026、9地域{total_divs}リーグ・{total_teams}チームの順位表をまとめて掲載。"
            "関東ROOKIE LEAGUE・東北・北信越・東海・関西Groeien・中国LIGA NOVA・CLIMB四国・球蹴男児（九州）・北海道。"
            "12月のMIZUNO CHAMPIONSHIP U-16（全国大会）の歴代優勝校と出場枠も。")

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', '{GA_ID}');
  </script>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT}" crossorigin="anonymous"></script>
  <meta name="google-adsense-account" content="{ADSENSE_CLIENT}">
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html_escape(title)}</title>
  <meta name="description" content="{html_escape(desc)}">
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">
  <meta name="keywords" content="ルーキーリーグ,U-16,高校1年,順位表,2026,ミズノチャンピオンシップ,関東ROOKIE LEAGUE,球蹴男児,Groeien,LIGA NOVA,CLIMB四国">
  <link rel="canonical" href="{CANONICAL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="U-16 ルーキーリーグ2026 順位表｜9地域20リーグ">
  <meta property="og:description" content="高校1年生年代のルーキーリーグ2026、9地域{total_divs}リーグ・{total_teams}チームの順位表。12月の全国大会情報も。">
  <meta property="og:url" content="{CANONICAL}">
  <meta property="og:image" content="{DOMAIN}/og-image.png">
  <meta property="og:locale" content="ja_JP">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:title" content="U-16 ルーキーリーグ2026 順位表｜9地域20リーグ">
  <meta name="twitter:description" content="高校1年生年代のリーグ戦{total_divs}リーグ・{total_teams}チームの順位表をまとめて掲載。">
  <meta name="twitter:image" content="{DOMAIN}/og-image.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <meta name="theme-color" content="#1e40af">
  <script type="application/ld+json">{breadcrumb_json}</script>
  <script type="application/ld+json">{faq_json}</script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap" rel="stylesheet">
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
  <style>
    .u16-jump {{ display:flex; flex-wrap:wrap; gap:8px; margin:4px 0 18px; }}
    .u16-jump a {{ display:inline-flex; align-items:center; gap:6px; padding:8px 14px; border-radius:999px;
      background:var(--bg-white,#f1f5fb); color:var(--text-dark,#1f2937); text-decoration:none;
      font-weight:600; font-size:0.92em; border:1px solid var(--border-color,#e2e8f0); }}
    .u16-cnt {{ display:inline-block; min-width:18px; text-align:center; padding:1px 6px; border-radius:999px;
      background:var(--primary-color,#1e40af); color:#fff; font-size:0.78em; }}
    .u16-divs {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:18px; }}
    .u16-div {{ border:1px solid var(--border-color,#d8dde8); border-radius:10px; padding:14px 14px 10px;
      background:var(--bg-card,transparent); }}
    .u16-div h3 {{ margin:0 0 2px; font-size:1.02rem; }}
    .u16-asof {{ margin:0 0 8px; font-size:0.78rem; opacity:0.72; }}
    .u16-scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    .u16-table {{ width:100%; border-collapse:collapse; font-size:0.86rem; }}
    .u16-table th, .u16-table td {{ border-bottom:1px solid var(--border-color,#e2e8f0); padding:6px 4px; text-align:center; }}
    .u16-table th {{ font-weight:600; opacity:0.85; white-space:nowrap; }}
    .u16-table .u16-name {{ text-align:left; }}
    .u16-table .u16-rank {{ opacity:0.7; }}
    .u16-table .u16-pts {{ font-weight:700; }}
    .u16-table tr.u16-top .u16-name {{ font-weight:700; }}
    .u16-table tr.u16-top .u16-rank {{ color:#b45309; font-weight:700; opacity:1; }}
    .u16-table tr.u16-bottom {{ opacity:0.78; }}
    /* 1位のアンバーはライト用の濃色なので、ダークでは明るい色に差し替える */
    [data-theme="dark"] .u16-table tr.u16-top .u16-rank {{ color:#fbbf24; }}
    @media (prefers-color-scheme:dark) {{
      :root:not([data-theme="light"]) .u16-table tr.u16-top .u16-rank {{ color:#fbbf24; }}
    }}
    .u16-src {{ margin:8px 0 0; font-size:0.76rem; opacity:0.72; line-height:1.7; }}
    /* 各リーグの得点ランキング（scorer_table.render_scorer_compact_html）。
       ★色はテーマ変数だけで書く。--text-primary / --text-secondary は未定義で、
         使うとダークモードで文字が消える（手順書 4-19b）。 */
    .xsc-box {{ margin:14px 0 0; padding:12px 12px 8px; border:1px solid var(--border-color,#e2e8f0);
      border-radius:10px; background:var(--bg-white,#fff); }}
    .xsc-h {{ margin:0 0 4px; font-size:0.95rem; color:var(--text-dark,#1a1a1a); }}
    .xsc-meta {{ margin:0 0 8px; font-size:0.76rem; color:var(--text-light,#666); line-height:1.7; }}
    .xsc-note {{ margin:8px 0 0; font-size:0.74rem; color:var(--text-light,#666); line-height:1.6; }}
    .xsc-scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    .xsc-table {{ width:100%; border-collapse:collapse; font-size:0.84rem;
      color:var(--text-dark,#1a1a1a); }}
    .xsc-table th, .xsc-table td {{ border-bottom:1px solid var(--border-color,#e2e8f0);
      padding:6px 6px; text-align:left; }}
    .xsc-table th {{ font-weight:600; opacity:0.85; white-space:nowrap; }}
    .xsc-table .xsc-rk {{ width:2.4em; text-align:center; opacity:0.75; }}
    .xsc-table .xsc-go {{ width:3.2em; text-align:center; font-weight:700; }}
    .xsc-table .xsc-tm {{ color:var(--text-light,#666); }}
    .xsc-table .xsc-nm {{ white-space:nowrap; }}
    .u16-region-note {{ margin:0 0 14px; line-height:1.85; }}
    .u16-pills {{ display:flex; flex-wrap:wrap; gap:10px; margin:4px 0 18px; }}
    .u16-pills a {{ display:inline-block; padding:9px 18px; border-radius:999px; color:#fff;
      text-decoration:none; font-weight:600; font-size:0.92em; }}
    .u16-note {{ font-size:0.85rem; opacity:0.8; }}
    .u16-champ {{ width:100%; border-collapse:collapse; font-size:0.9rem; }}
    .u16-champ th, .u16-champ td {{ border-bottom:1px solid var(--border-color,#e2e8f0); padding:8px 6px; text-align:center; }}
  </style>
</head>
<body>
  <header class="header">
    <div class="container">
      <div class="header-content">
        <div class="site-title">
          <a href="/" style="color:white;text-decoration:none;display:inline-flex;align-items:center;gap:10px">
            <i class="fas fa-futbol"></i> 高校サッカー順位確認システム
          </a>
        </div>
        <nav class="nav">
          <a href="/" class="nav-link"><i class="fas fa-home"></i> ホーム</a>
          <a href="/leagues/" class="nav-link"><i class="fas fa-trophy"></i> リーグ一覧</a>
          <a href="/blog/" class="nav-link"><i class="fas fa-newspaper"></i> ブログ</a>
        </nav>
      </div>
    </div>
  </header>

  <main class="main-content">
    <div class="container">
      <nav class="breadcrumb" aria-label="パンくずリスト">
        <a href="/">ホーム</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">U-16ルーキーリーグ</span>
      </nav>

      <h1 class="lp-title">U-16 ルーキーリーグ 2026（高校1年生年代）</h1>

      <p class="blog-article__summary" style="margin:0 0 20px;padding:14px 18px;background:var(--bg-light,#f1f5fb);border-left:4px solid var(--primary-color,#1e40af);border-radius:0 8px 8px 0;font-size:0.97rem;line-height:1.85;">
        <strong>高校1年生年代（U-16）</strong>の通年リーグ戦をまとめたページです。全国9地域の
        <strong>{total_divs}リーグ・{total_teams}チーム</strong>の順位表を、大会公式サイトの星取表から毎日自動で集計して掲載しています。
        各地域の上位チームは12月の全国大会
        <a href="{CS_PAGE}"><strong>MIZUNO CHAMPIONSHIP U-16ルーキーリーグ</strong></a>に進みます。
        2・3年生を含むトップチームの戦いは<a href="/leagues/">高円宮杯 U-18リーグ（プレミア・プリンス）</a>をご覧ください。
      </p>

      <div class="u16-pills">
        <a href="{CS_PAGE}" style="background:#0f766e;">🏆 MIZUNO CHAMPIONSHIP U-16（12月・全国大会）</a>
        <a href="/leagues/" style="background:var(--primary-color,#1e40af);">⚽ U-18リーグ順位（毎日更新）</a>
        <a href="/u15/" style="background:#7c3aed;">🔰 U-15（中学生年代）順位表</a>
      </div>

      <section class="lp-section">
        <h2><i class="fas fa-circle-info"></i> ルーキーリーグとは</h2>
        <p style="line-height:1.9;">
          ルーキーリーグは、<strong>高校1年生年代（U-16）だけで戦う通年のリーグ戦</strong>です。
          高校サッカーのトップチームは<a href="/leagues/">高円宮杯 JFA U-18サッカーリーグ</a>（プレミア→プリンス→都道府県リーグ）で戦いますが、
          そこに出られるのは基本的に各校数十人のうち十数人。入学したばかりの1年生が公式戦の経験を積む場として、
          全国9地域にそれぞれ独立したリーグが作られています。
        </p>
        <ul style="line-height:2;">
          <li>各地域が<strong>独自の名前</strong>を持ちます（関東ROOKIE LEAGUE／関西 ～Groeien～／中国 LIGA NOVA／CLIMB四国／球蹴男児＝九州 など）。</li>
          <li>1部・2部（地域によりA〜C、G1/G2、N1/N2、S1/S2、D1/D2）に分かれ、<strong>昇降格</strong>があります。</li>
          <li>おおむね<strong>4〜11月</strong>に行われ、夏に中断期間を置く地域が多くなっています。</li>
          <li>上位チームは<strong>12月の全国大会</strong>（MIZUNO CHAMPIONSHIP U-16ルーキーリーグ）に出場します。</li>
        </ul>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-table-list"></i> 地域リーグ順位表（9地域{total_divs}リーグ）</h2>
        <p class="u16-note">
          ※大会公式サイトの<strong>星取表から毎日自動で集計</strong>しています（各表の日付は反映時点）。消化試合数がチームによって異なります。<br>
          ※<strong>順位は公式サイトの「暫定順位」をそのまま採用</strong>し、勝点・勝敗数・得失点は星取表の全セルから計算しています。
          公式の星取表には集計欄がないためです。<br>
          ※掲載前に「星取表の上下でスコアが裏返しか」「勝点＝勝×3＋分」「試合数＝勝＋分＋敗」「リーグ内の得点合計＝失点合計」を
          機械的に検算し、<strong>合わないリーグは更新せず前回の内容を残します</strong>（誤った順位を載せないための仕組みです）。<br>
          ※PK決着の試合は<strong>勝点上は引き分け</strong>として扱っています（四国S2など）。<br>
          ※最終更新：{html_escape(str(updated))}
        </p>
        <div class="u16-jump">
          {nav}
        </div>
      </section>
{regions_html}

      <section class="lp-section">
        <h2><i class="fas fa-trophy"></i> 全国大会（MIZUNO CHAMPIONSHIP U-16）歴代優勝校</h2>
        <p style="line-height:1.9;">
          9地域のリーグを勝ち上がった16チームが、毎年12月に静岡県裾野市の時之栖スポーツセンターで日本一を争います。
          詳しい大会方式・出場枠・2026年度の情報は<a href="{CS_PAGE}">全国大会のページ</a>にまとめました。
        </p>
        <div class="u16-scroll">
        <table class="u16-champ">
          <thead><tr><th>年度</th><th>優勝</th><th>準優勝</th><th>決勝</th></tr></thead>
          <tbody>
{champ_rows}
          </tbody>
        </table>
        </div>
        <p class="u16-note" style="margin-top:10px;">出典：<a href="https://rookie-league.com/" target="_blank" rel="noopener">大会公式サイト</a>の各年度結果ページ。</p>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-link"></i> ルーキーリーグを見ると何が分かるのか</h2>
        <p style="line-height:1.9;">
          ルーキーリーグの順位表は、<strong>1〜2年後のU-18勢力図の先行指標</strong>です。
          ここで主力を張っている1年生が、翌年には<a href="/leagues/premier-east/">プレミアリーグEAST</a>・<a href="/leagues/premier-west/">WEST</a>や
          プリンスリーグの舞台に立ち、3年目には<a href="/tournaments/senshuken-2026/">選手権</a>の中心になります。
        </p>
        <p style="line-height:1.9;">
          また、中学年代でどこにいた選手が高校でどこへ進んだのかという流れは
          <a href="/u15/">U-15（中学生年代）の順位表</a>や
          <a href="/blog/posts/interhigh-2026-data-review/">インターハイ2026 出場1,428人の前所属データ</a>から追えます。
          さらに先は<a href="/pro-signings/">プロ内定・2種登録</a>、<a href="/national-team/">日本代表選出選手</a>、
          <a href="/university/">大学サッカー</a>へとつながります。
        </p>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-user-doctor"></i> 救急科専門医から、高校1年生の保護者・指導者の方へ</h2>
        <p style="line-height:1.9;">
          高校1年の春から夏は、<strong>練習環境が一気に変わる時期</strong>です。中学までとは練習量・強度・気候条件が変わり、
          体がまだ追いついていない段階で連戦に入ります。この時期に増えるトラブルについて、医学的根拠とともにまとめた記事があります。
        </p>
        <ul style="line-height:2;">
          <li><a href="/blog/posts/2026-05-08-may-heatstroke-prevention/">熱中症の危険サインと予防</a>／<a href="/blog/posts/2026-07-10-summer-hydration-strategy/">夏の水分補給戦略</a> — 新入生は暑熱順化が済んでいません</li>
          <li><a href="/blog/posts/shin-splints-2026/">シンスプリントと疲労骨折</a> — 練習量が急に増えた直後に多い</li>
          <li><a href="/blog/posts/lumbar-spondylolysis-2026/">腰椎分離症</a> — 成長期の腰痛は疲労骨折を疑う</li>
          <li><a href="/blog/posts/osgood-schlatter-2026/">オスグッド病</a>／<a href="/blog/posts/hamstring-strain-2026/">ハムストリング肉離れ</a></li>
          <li><a href="/blog/posts/concussion-return-to-play-2026/">脳震盪と競技復帰</a> — 疑わしければその日は必ず中止</li>
        </ul>
        <p class="u16-note">
          ※一般的な医学情報であり、個別の診断・治療を目的としたものではありません。症状があるときは医療機関にご相談ください。
          医学コラムの一覧は<a href="/blog/medical/">こちら</a>。
        </p>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-circle-question"></i> よくある質問</h2>
{faq_html}
      </section>

    </div>
  </main>

  <footer class="footer">
    <div class="container">
      <p>&copy; 2025-2026 高校サッカー順位確認システム</p>
      <nav class="footer-nav" style="margin-top:12px;">
        <a href="/about.html">運営者情報</a> ・
        <a href="/privacy.html">プライバシーポリシー</a> ・
        <a href="/contact.html">お問い合わせ</a>
      </nav>
    </div>
  </footer>
  <script src="/js/main.js" defer></script>
</body>
</html>
'''


def register_sitemap():
    sm = BASE_DIR / "sitemap.xml"
    if not sm.exists():
        print("ℹ️ sitemap.xml が無いのでスキップ")
        return
    s = sm.read_text(encoding="utf-8")
    if CANONICAL in s:
        print("ℹ️ sitemap.xml は登録済み")
        return
    entry = (f"  <url>\n    <loc>{CANONICAL}</loc>\n"
             f"    <lastmod>{jst_today().isoformat()}</lastmod>\n"
             f"    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>\n")
    sm.write_text(s.replace("</urlset>", entry + "</urlset>"), encoding="utf-8")
    print(f"✅ sitemap.xml に登録: {CANONICAL}")


def main():
    if not SOURCE.exists():
        print(f"❌ データがありません: {SOURCE}")
        return
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    links = load_team_links()
    html = build_html(data, links)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    n_div = len(data["divisions"])
    n_team = sum(len(d["teams"]) for d in data["divisions"])
    print(f"✅ /u16/ を生成しました（{n_div}リーグ・{n_team}チーム）")
    register_sitemap()


if __name__ == "__main__":
    main()
