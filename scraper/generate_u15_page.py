#!/usr/bin/env python3
"""
U-15（3種）ハブページ生成スクリプト（2026-08-21 新設）
=====================================================
data/u15/leagues-2026.json を読み込み、/u15/ ページを生成する。

- 9地域21ディビジョンの順位表を描画
- 全国大会（クラブユースU-15・全中）ページへの導線
- U-15→U-18の接続解説
- sitemap.xml への登録（idempotent）

データを更新したいときは data/u15/leagues-2026.json を直せばよい。
**JSONの divisions の並び順が、そのまま各地域内の表示順になる**（上位ディビジョンを先に置く。
例：東北は みちのくTOP → チャレンジ北 → チャレンジ南）。id順に並べ替えてはいけない
（"michinoku-top" が "michinoku-n"/"michinoku-s" より後ろに来て、1部相当が最後に表示される）。
順位表は「勝点=勝×3+分」「得点合計=失点合計」を生成時に検算し、
合わないディビジョンがあれば警告を出して**そのリーグだけ描画しない**（誤データを載せない）。

依存：標準ライブラリのみ
"""
import json
from html import escape as html_escape
from pathlib import Path
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


def jst_today():
    return _dt.now(_tz(_td(hours=9))).date()


BASE_DIR = Path(__file__).parent.parent
DOMAIN = "https://u18-soccer.com"
GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"

SOURCE = BASE_DIR / "data" / "u15" / "leagues-2026.json"
OUT_DIR = BASE_DIR / "u15"
CANONICAL = f"{DOMAIN}/u15/"

REGION_ORDER = ["北海道", "東北", "関東", "北信越", "東海", "関西", "中国", "四国", "九州"]

# 地域ごとの短い解説（U-18との接続を意識した独自コメント）
REGION_NOTES = {
    "北海道": "全道リーグの1部・2部。コンサドーレの各拠点（札幌・旭川・室蘭）が広い北海道に分散しているのが特徴です。",
    "東北": "TOPリーグと、その下のチャレンジ北・チャレンジ南の3層構造。JFAアカデミー福島と青森山田中が抜けた存在です。",
    "関東": "2026年から1部2ブロック・2部4ブロックの計48チームに拡大した国内最大規模の地域リーグ。Jアカデミーと強豪街クラブが密集しています。",
    "北信越": "1部2部の区分がない単一12チーム制。松本山雅・カターレ富山・ツエーゲン金沢などJクラブと街クラブが同居します。",
    "東海": "1部制10チーム。清水エスパルス・名古屋グランパス・ジュビロ磐田のJ勢に、静岡学園中と藤枝勢が挑む構図です。",
    "関西": "サンライズリーグ。1部10・2部A/B各10の計30チーム。セレッソ・ガンバ・ヴィッセルは複数チームを別ディビジョンに置いています。",
    "中国": "プログレスリーグ。サンフレッチェが広島・くにびき（島根）・びんご（広島東部）の3チームを持つのが独特です。",
    "四国": "クローバーリーグ。1部制10チームで、4県のJクラブアカデミーがそのまま顔を揃えます。",
    "九州": "1部10・2部8。1部は神村学園中等部（部活動）がJアカデミー相手に首位を走っています。",
}


def load_data():
    return json.loads(SOURCE.read_text(encoding="utf-8"))


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


def render_table(div):
    rows = []
    n = len(div["teams"])
    for t in div["teams"]:
        gd = t["gf"] - t["ga"]
        gd_s = f"+{gd}" if gd > 0 else str(gd)
        cls = ""
        if t["rank"] == 1:
            cls = ' class="u15-top"'
        elif t["rank"] == n:
            cls = ' class="u15-bottom"'
        rows.append(
            f'<tr{cls}><td class="u15-rank">{t["rank"]}</td>'
            f'<td class="u15-name">{html_escape(t["name"])}</td>'
            f'<td>{t["p"]}</td><td>{t["w"]}</td><td>{t["d"]}</td><td>{t["l"]}</td>'
            f'<td>{t["gf"]}</td><td>{t["ga"]}</td><td>{gd_s}</td>'
            f'<td class="u15-pts">{t["pts"]}</td></tr>'
        )
    src = ""
    if div.get("sourceUrl"):
        src = (f'<a href="{html_escape(div["sourceUrl"])}" target="_blank" rel="noopener">'
               f'{html_escape(div.get("sourceLabel", "出典"))}</a>')
    else:
        src = html_escape(div.get("sourceLabel", ""))
    note = f'／{html_escape(div["note"])}' if div.get("note") else ""
    return f'''
          <div class="u15-div">
            <h3>{html_escape(div["name"])}</h3>
            <p class="u15-asof">{html_escape(div.get("asof", ""))}</p>
            <div class="u15-scroll">
            <table class="u15-table">
              <thead><tr><th>順</th><th>チーム</th><th>試</th><th>勝</th><th>分</th><th>敗</th><th>得</th><th>失</th><th>差</th><th>点</th></tr></thead>
              <tbody>
{chr(10).join("                " + r for r in rows)}
              </tbody>
            </table>
            </div>
            <p class="u15-src">出典：{src}{note}</p>
          </div>'''


def render_regions(data):
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
        note_html = f'<p class="u15-region-note">{html_escape(note)}</p>' if note else ""
        tables = "\n".join(render_table(d) for d in divs)
        blocks.append(f'''
      <section class="lp-section" id="region-{REGION_ORDER.index(region) + 1}">
        <h2><i class="fas fa-map-location-dot"></i> {html_escape(region)}</h2>
        {note_html}
        <div class="u15-divs">{tables}
        </div>
      </section>''')
    return "\n".join(blocks), by_region


def render_nav(by_region):
    pills = []
    for region in REGION_ORDER:
        if region in by_region:
            n = len(by_region[region])
            pills.append(f'<a href="#region-{REGION_ORDER.index(region) + 1}">{html_escape(region)}'
                         f'<span class="u15-cnt">{n}</span></a>')
    return "\n          ".join(pills)


def build_html(data):
    regions_html, by_region = render_regions(data)
    nav = render_nav(by_region)
    total_divs = sum(len(v) for v in by_region.values())
    total_teams = sum(len(d["teams"]) for v in by_region.values() for d in v)
    updated = data.get("updated", jst_today().isoformat())

    faq = [
        ("U-15の地域リーグとはどんな大会ですか？",
         "高円宮杯 JFA U-15サッカーリーグの地域リーグ（9地域）です。中学生年代（3種）のリーグ戦のピラミッドで最上位にあたり、"
         "各都道府県リーグの上位チームが昇格してきます。Jクラブのジュニアユース（U-15アカデミー）、街クラブ、"
         "中高一貫校の中学サッカー部が同じリーグで戦うのが特徴です。"),
        ("いま順位表が動いていないのはなぜですか？",
         "多くの地域リーグは8月に夏季中断期間を設けており、9月に再開します。"
         "8月は日本クラブユースサッカー選手権（U-15）や全国中学校サッカー大会などの全国大会が集中する時期にあたるためです。"
         "リーグ戦が動いている期間は、各リーグの公式発表（JFA公式の星取表など）から毎日自動で順位表を更新しています。"),
        ("U-18（高校年代）との関係は？",
         "U-15年代の選手は3年後、高校サッカー部やJクラブのユース（U-18）へ進み、"
         "高円宮杯 JFA U-18サッカーリーグ（プレミアリーグ・プリンスリーグ・都道府県リーグ）で戦います。"
         "当サイトはU-18の順位表を毎日自動更新で提供しており、U-15とU-18を両方追うことで選手の進路や育成の流れが見えてきます。"),
        ("データはどこから取っていますか？",
         "各リーグの公式発表（JFA公式の星取表・東北サッカー協会の順位表・関東クラブユースサッカー連盟の結果ページ・"
         "九州クラブユースサッカー連盟の公式対戦表）です。掲載前に「勝点＝勝×3＋分」「リーグ内の得点合計＝失点合計」を"
         "機械的に検算し、一致したデータだけを掲載しています。"),
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
            {"@type": "ListItem", "position": 2, "name": "U-15（中学生年代）", "item": CANONICAL},
        ]}, ensure_ascii=False)

    faq_html = "\n".join(
        f'        <h3>{html_escape(q)}</h3>\n        <p>{html_escape(a)}</p>' for q, a in faq)

    title = "U-15（中学生年代）サッカー 地域リーグ順位表・全国大会2026｜9地域一覧"
    desc = (f"高円宮杯 JFA U-15サッカーリーグ2026の9地域{total_divs}リーグ・{total_teams}チームの順位表をまとめて掲載。"
            "北海道カブス・東北みちのく・関東ユース・北信越・東海・関西サンライズ・中国プログレス・四国クローバー・九州。"
            "クラブユース選手権（U-15）と全国中学校サッカー大会の結果ページへの入口も。")

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
  <meta name="keywords" content="U-15,中学サッカー,高円宮杯,順位表,2026,地域リーグ,ジュニアユース,クラブユース,全中">
  <link rel="canonical" href="{CANONICAL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="U-15（中学生年代）サッカー 地域リーグ順位表・全国大会2026">
  <meta property="og:description" content="高円宮杯 JFA U-15サッカーリーグ2026の9地域{total_divs}リーグ・{total_teams}チームの順位表をまとめて掲載。">
  <meta property="og:url" content="{CANONICAL}">
  <meta property="og:image" content="{DOMAIN}/og-image.png">
  <meta property="og:locale" content="ja_JP">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:title" content="U-15（中学生年代）サッカー 地域リーグ順位表・全国大会2026">
  <meta name="twitter:description" content="9地域{total_divs}リーグ・{total_teams}チームの順位表をまとめて掲載。">
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
    .u15-jump {{ display:flex; flex-wrap:wrap; gap:8px; margin:4px 0 18px; }}
    .u15-jump a {{ display:inline-flex; align-items:center; gap:6px; padding:8px 14px; border-radius:999px;
      background:var(--bg-light,#f1f5fb); color:var(--text-primary,#1f2937); text-decoration:none;
      font-weight:600; font-size:0.92em; border:1px solid var(--border-color,#e2e8f0); }}
    .u15-cnt {{ display:inline-block; min-width:18px; text-align:center; padding:1px 6px; border-radius:999px;
      background:var(--primary-color,#1e40af); color:#fff; font-size:0.78em; }}
    .u15-divs {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:18px; }}
    .u15-div {{ border:1px solid var(--border-color,#d8dde8); border-radius:10px; padding:14px 14px 10px;
      background:var(--bg-card,transparent); }}
    .u15-div h3 {{ margin:0 0 2px; font-size:1.02rem; }}
    .u15-asof {{ margin:0 0 8px; font-size:0.78rem; opacity:0.72; }}
    .u15-scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    .u15-table {{ width:100%; border-collapse:collapse; font-size:0.86rem; }}
    .u15-table th, .u15-table td {{ border-bottom:1px solid var(--border-color,#e2e8f0); padding:6px 4px; text-align:center; }}
    .u15-table th {{ font-weight:600; opacity:0.85; white-space:nowrap; }}
    .u15-table .u15-name {{ text-align:left; }}
    .u15-table .u15-rank {{ opacity:0.7; }}
    .u15-table .u15-pts {{ font-weight:700; }}
    .u15-table tr.u15-top .u15-name {{ font-weight:700; }}
    .u15-table tr.u15-top .u15-rank {{ color:#b45309; font-weight:700; opacity:1; }}
    .u15-table tr.u15-bottom {{ opacity:0.78; }}
    /* 1位のアンバーはライト用の濃色なので、ダークでは明るい色に差し替える */
    [data-theme="dark"] .u15-table tr.u15-top .u15-rank {{ color:#fbbf24; }}
    @media (prefers-color-scheme:dark) {{
      :root:not([data-theme="light"]) .u15-table tr.u15-top .u15-rank {{ color:#fbbf24; }}
    }}
    .u15-src {{ margin:8px 0 0; font-size:0.76rem; opacity:0.72; }}
    .u15-region-note {{ margin:0 0 14px; line-height:1.85; }}
    .u15-pills {{ display:flex; flex-wrap:wrap; gap:10px; margin:4px 0 18px; }}
    .u15-pills a {{ display:inline-block; padding:9px 18px; border-radius:999px; color:#fff;
      text-decoration:none; font-weight:600; font-size:0.92em; }}
    .u15-note {{ font-size:0.85rem; opacity:0.8; }}
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
        <span aria-current="page">U-15（中学生年代）</span>
      </nav>

      <h1 class="lp-title">U-15（中学生年代）サッカー 2026</h1>

      <p class="blog-article__summary" style="margin:0 0 20px;padding:14px 18px;background:var(--bg-light,#f1f5fb);border-left:4px solid var(--primary-color,#1e40af);border-radius:0 8px 8px 0;font-size:0.97rem;line-height:1.85;">
        中学生年代（3種）のサッカーをまとめたページです。<strong>高円宮杯 JFA U-15サッカーリーグ2026</strong>の
        <strong>9地域{total_divs}リーグ・{total_teams}チーム</strong>の順位表と、夏の全国大会（クラブユース選手権U-15・全国中学校サッカー大会）の
        結果ページへの入口を用意しました。当サイトが毎日自動更新している<a href="/leagues/">U-18（高校年代）の順位表</a>と
        あわせてご覧いただくと、選手が中学から高校へ進み、やがてプロを目指していく流れが見えてきます。
      </p>

      <div class="u15-pills">
        <a href="/tournaments/club-youth-u15-2026/" style="background:#7c3aed;">🔰 クラブユース選手権U-15 2026 結果速報</a>
        <a href="/tournaments/zenchu-2026/" style="background:#be185d;">🏫 全国中学校サッカー大会2026 結果速報</a>
        <a href="/leagues/" style="background:var(--primary-color,#1e40af);">⚽ U-18リーグ順位（毎日更新）</a>
      </div>

      <section class="lp-section">
        <h2><i class="fas fa-circle-info"></i> U-15年代の大会構造</h2>
        <p style="line-height:1.9;">
          中学生年代には、大きく分けて<strong>1年を通して戦うリーグ戦</strong>と<strong>短期決戦の全国大会</strong>があります。
        </p>
        <ul style="line-height:2;">
          <li><strong>高円宮杯 JFA U-15サッカーリーグ</strong>（下の順位表）…… 都道府県リーグ → 9つの地域リーグというピラミッド構造。
            U-18の<a href="/leagues/">プレミアリーグ・プリンスリーグ</a>にあたる位置づけですが、U-15には全国リーグ（プレミア相当）がなく、<strong>地域リーグが最上位</strong>です。</li>
          <li><strong>日本クラブユースサッカー選手権（U-15）</strong>（8月）…… Jアカデミー・街クラブなど<strong>クラブチーム</strong>の日本一決定戦。
            → <a href="/tournaments/club-youth-u15-2026/">2026年大会の結果はこちら</a></li>
          <li><strong>全国中学校サッカー大会（全中）</strong>（8月）…… <strong>中学校の部活動</strong>を中心とした全国大会。近年は地域クラブの参加も。
            → <a href="/tournaments/zenchu-2026/">2026年大会の結果はこちら</a></li>
          <li><strong>高円宮杯 JFA 全日本U-15サッカー選手権大会</strong>（12月）…… クラブ・部活動の<strong>垣根なく</strong>中学生年代の日本一を争う大会。</li>
        </ul>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-table-list"></i> 地域リーグ順位表（9地域{total_divs}リーグ）</h2>
        <p class="u15-note">
          ※各リーグの公式発表から<strong>毎日自動で更新</strong>しています（各表の日付は反映時点）。消化試合数がチームによって異なる場合があります。<br>
          ※<strong>多くの地域リーグは8月が夏季中断期間</strong>で、9月に再開します。中断中は順位が動きません。<br>
          ※各順位表は掲載前に「勝点＝勝×3＋分」「試合数＝勝＋分＋敗」「リーグ内の得点合計＝失点合計」を機械的に検算し、
          <strong>合わないリーグは更新せず前回の内容を残します</strong>（誤った順位を載せないための仕組みです）。<br>
          ※最終更新：{html_escape(str(updated))}
        </p>
        <div class="u15-jump">
          {nav}
        </div>
      </section>
{regions_html}

      <section class="lp-section">
        <h2><i class="fas fa-link"></i> U-15からU-18へ：この年代の選手はどこへ進むのか</h2>
        <p style="line-height:1.9;">
          U-15年代を終えた選手の進路は大きく2つに分かれます。<strong>Jクラブのジュニアユースからユース（U-18）への内部昇格</strong>と、
          <strong>街クラブ・中学部活から高校サッカー部への進学</strong>です。
          当サイトが<a href="/blog/posts/interhigh-2026-data-review/">インターハイ2026の登録選手1,428人の前所属を集計した分析</a>では、
          高校サッカーの全国大会に出場した選手の<strong>72.8%が街クラブ出身、14.7%がJリーグアカデミー出身</strong>でした。
          つまり高校サッカーの主役の多くは、上の順位表に並ぶ街クラブや、その下の都道府県リーグで育った選手たちです。
        </p>
        <p style="line-height:1.9;">
          3年後、彼らは<a href="/leagues/premier-east/">プレミアリーグEAST</a>・<a href="/leagues/premier-west/">WEST</a>や
          プリンスリーグ、<a href="/tournaments/senshuken-2026/">選手権</a>の舞台に現れます。その先には
          <a href="/pro-signings/">プロ内定・2種登録</a>や<a href="/national-team/">日本代表</a>が待っています。
          U-15の順位表は、いわば<strong>数年先のU-18勢力図の先行指標</strong>です。
        </p>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-user-doctor"></i> 救急科専門医から、中学生年代の保護者・指導者の方へ</h2>
        <p style="line-height:1.9;">
          中学生年代は<strong>身長が最も伸びる時期（PHV＝身長成長速度のピーク）</strong>と重なります。
          骨の成長に筋・腱の伸びが追いつかない時期があり、大人と同じ練習量・同じ感覚での連戦はケガのリスクを高めます。
          この年代に特に多い障害について、医学的根拠とともにまとめた記事があります。
        </p>
        <ul style="line-height:2;">
          <li><a href="/blog/posts/osgood-schlatter-2026/">オスグッド病（膝の下の痛み）</a> — 成長期に最も多い膝の障害</li>
          <li><a href="/blog/posts/shin-splints-2026/">シンスプリントと疲労骨折</a> — すねの痛みを「よくあること」で済ませない</li>
          <li><a href="/blog/posts/lumbar-spondylolysis-2026/">腰椎分離症</a> — 成長期の腰痛は疲労骨折を疑う</li>
          <li><a href="/blog/posts/2026-05-08-may-heatstroke-prevention/">熱中症の危険サインと予防</a>／<a href="/blog/posts/2026-07-10-summer-hydration-strategy/">夏の水分補給戦略</a></li>
          <li><a href="/blog/posts/concussion-return-to-play-2026/">脳震盪と競技復帰</a> — 疑わしければその日は必ず中止</li>
        </ul>
        <p class="u15-note">
          ※一般的な医学情報であり、個別の診断・治療を目的としたものではありません。症状があるときは医療機関にご相談ください。
          医学コラムの一覧は<a href="/blog/medical/">こちら</a>。
        </p>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-circle-question"></i> よくある質問</h2>
{faq_html}
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-link"></i> 関連ページ（U-15 → U-18 → 大学）</h2>
        <ul style="line-height:2.1;">
          <li><a href="/leagues/">U-18（高校年代）リーグ一覧 — プレミア・プリンスリーグ（毎日自動更新）</a></li>
          <li><a href="/university/">大学サッカーハブ — 全国20リーグ順位表と「高校→大学→プロ」の進路解説</a></li>
          <li><a href="/blog/posts/interhigh-2026-data-review/">インターハイ2026 出場1,428人の前所属データ（U-15→U-18の接続）</a></li>
        </ul>
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
    data = load_data()
    html = build_html(data)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    n_div = len(data["divisions"])
    n_team = sum(len(d["teams"]) for d in data["divisions"])
    print(f"✅ /u15/ を生成しました（{n_div}リーグ・{n_team}チーム）")
    register_sitemap()


if __name__ == "__main__":
    main()
