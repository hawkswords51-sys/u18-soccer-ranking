#!/usr/bin/env python3
"""
地域大会まとめ 特設ページ生成スクリプト
====================================================
data/tournaments/regional/*.md（東北・北信越・東海・中国・四国・九州）を読み込み、
1ページ /tournaments/regional-2026/ に 6大会をまとめて出力する。

- 各大会：Jユース／本選と同じSVGトーナメント表（勝ち上がりを自動描画）＋「全試合結果」折りたたみ
- 描画ロジックは generate_jyouth_page を再利用（校名照合・正規化・SVG）
- ファイル名先頭の番号で表示順を制御（1-tohoku, 2-hokushinetsu, ...）

依存：標準ライブラリ + PyYAML + generate_jyouth_page
"""
import re
import yaml
from pathlib import Path

import generate_jyouth_page as jy

BASE_DIR = jy.BASE_DIR
DOMAIN = jy.DOMAIN
GA_ID = jy.GA_ID
ADSENSE_CLIENT = jy.ADSENSE_CLIENT
date = jy.date
html_escape = jy.html_escape

SRC_DIR = BASE_DIR / "data" / "tournaments" / "regional"
OUT_DIR = BASE_DIR / "tournaments" / "regional-2026"
CANONICAL = f"{DOMAIN}/tournaments/regional-2026/"


def parse_file(path):
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    body_nocomment = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    sections = {}
    cur = None
    for line in body_nocomment.splitlines():
        h = re.match(r"^##\s+(.*)$", line)
        if h:
            cur = h.group(1).strip()
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(line)
    return meta, sections


def render_region_section(idx, meta, sections):
    region = meta.get("region", "")
    title = meta.get("title", region)
    period = meta.get("period", "")
    host = meta.get("host", "")
    status = meta.get("status", "")

    bracket_html = jy.render_bracket_svg(sections)
    rounds_html = jy.render_rounds(sections)

    status_badge = (
        f'<span style="display:inline-block;padding:3px 12px;border-radius:999px;'
        f'background:#dbeafe;color:#1e40af;font-weight:600;font-size:0.8em;margin-left:8px;">'
        f"{html_escape(status)}</span>"
        if status else ""
    )
    meta_line = " / ".join([x for x in [html_escape(title), html_escape(period)] if x])

    if bracket_html:
        body_html = (
            f'        <div class="tournament-bracket-wrap">\n{bracket_html}\n        </div>\n'
            f'        <details class="tournament-fulllist">\n'
            f"          <summary>全試合結果を見る</summary>\n"
            f"          {rounds_html}\n"
            f"        </details>"
        )
    else:
        body_html = f"        {rounds_html}"

    return (
        f'      <section class="lp-section" id="region-{idx}">\n'
        f'        <h2><i class="fas fa-trophy"></i> {html_escape(region)}大会{status_badge}</h2>\n'
        f'        <p style="color:var(--text-secondary,#6b7280);margin:-4px 0 10px;font-size:0.92em;">{meta_line}</p>\n'
        f"{body_html}\n"
        f"      </section>"
    )


def main():
    files = sorted(SRC_DIR.glob("*.md")) if SRC_DIR.exists() else []
    regions = []
    for f in files:
        meta, sections = parse_file(f)
        regions.append((meta, sections))

    # 地域選択ナビ（ページ内アンカー）
    nav_items = "\n".join(
        f'          <a href="#region-{i}" class="region-jump">{html_escape(m.get("region",""))}大会</a>'
        for i, (m, _) in enumerate(regions)
    )
    region_nav = (
        '      <section class="lp-section">\n'
        '        <h2><i class="fas fa-location-dot"></i> 地域を選ぶ</h2>\n'
        '        <div class="region-jump-grid">\n'
        f"{nav_items}\n"
        "        </div>\n"
        "      </section>"
    )

    sections_html = "\n\n".join(
        render_region_section(i, m, s) for i, (m, s) in enumerate(regions)
    )

    year = 2026
    seo_title = "2026 高校サッカー 地域大会まとめ｜東北・北信越・東海・中国・四国・九州 結果・トーナメント表"
    description = (
        "2026年の高校サッカー地域大会（東北・北信越・東海・中国・四国・九州）の"
        "結果・組み合わせ・トーナメント表を1ページにまとめて随時更新。"
        "各県インターハイ予選の上位校が集う地区大会の勝ち上がりを一目で確認できます。"
    )
    keywords = (
        "高校サッカー 地域大会,四国大会 サッカー 2026,九州大会 サッカー 2026,"
        "北信越大会 サッカー,東海大会 サッカー,中国大会 サッカー,東北大会 サッカー,"
        "高校サッカー 結果,トーナメント表,高校総体,選手権,U-18"
    )

    today = date.today()
    _wd = "月火水木金土日"[today.weekday()]
    updated_str = f"{today.year}年{today.month}月{today.day}日（{_wd}）"
    updated_html = (
        f'<p style="text-align:right;color:var(--text-secondary,#6b7280);font-size:0.85em;margin:4px 0 0;">'
        f'<i class="fas fa-clock"></i> 最終更新：{updated_str}</p>'
    )

    breadcrumb_schema = (
        '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":['
        '{"@type":"ListItem","position":1,"name":"ホーム","item":"' + DOMAIN + '/"},'
        '{"@type":"ListItem","position":2,"name":"高校サッカー地域大会まとめ' + str(year) + '","item":"' + CANONICAL + '"}]}'
    )

    page = f"""<!DOCTYPE html>
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
  <title>{html_escape(seo_title)}</title>
  <meta name="description" content="{html_escape(description)}">
  <meta name="keywords" content="{html_escape(keywords)}">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{CANONICAL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="{html_escape(seo_title)}">
  <meta property="og:description" content="{html_escape(description)}">
  <meta property="og:url" content="{CANONICAL}">
  <meta property="og:image" content="https://u18-soccer.com/og-image.png">
  <meta property="og:locale" content="ja_JP">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:title" content="{html_escape(seo_title)}">
  <meta name="twitter:description" content="{html_escape(description)}">
  <meta name="twitter:image" content="https://u18-soccer.com/og-image.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <meta name="theme-color" content="#1e40af">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/css/style.css">
  <script type="application/ld+json">{breadcrumb_schema}</script>
  <script>
    (function() {{
      try {{
        var t = localStorage.getItem('theme');
        if (t === 'light' || t === 'dark') {{ document.documentElement.setAttribute('data-theme', t); }}
      }} catch (e) {{}}
    }})();
  </script>
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
        </nav>
      </div>
    </div>
  </header>
  <main class="main-content">
    <div class="container">
      <nav class="breadcrumb" aria-label="パンくずリスト">
        <a href="/">ホーム</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">高校サッカー地域大会まとめ{year}</span>
      </nav>
      <h1 class="lp-title">2026 高校サッカー 地域大会まとめ</h1>
      {updated_html}
      <p class="lp-intro">
        各県のインターハイ予選を勝ち抜いた上位校が地区ごとに集う<strong>地域大会（東北・北信越・東海・中国・四国・九州）</strong>の
        組み合わせ・試合結果・トーナメント表を1ページにまとめています。結果が入るたびに勝ち上がりが自動で更新されます。
        各校の普段のリーグ戦成績は<a href="/leagues/">リーグ一覧</a>・<a href="/">都道府県別ページ</a>から、
        全国大会は<a href="/tournaments/interhigh-2026/">インターハイ2026</a>をご覧ください。
      </p>

{region_nav}

{sections_html}

      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/tournaments/interhigh-2026/">インターハイ2026 全国大会 速報・結果</a></li>
          <li><a href="/">全国47都道府県の高校サッカー順位・予選結果</a></li>
          <li><a href="/leagues/">リーグ一覧（プレミア・プリンス）</a></li>
          <li><a href="/blog/">ブログ・医学コラム</a></li>
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
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(page, encoding="utf-8")
    print(f"✅ 生成: {OUT_DIR / 'index.html'}（{len(regions)}大会）")

    sm = BASE_DIR / "sitemap.xml"
    if sm.exists():
        s = sm.read_text(encoding="utf-8")
        if CANONICAL not in s:
            entry = (f"  <url>\n    <loc>{CANONICAL}</loc>\n    <lastmod>{date.today().isoformat()}</lastmod>\n"
                     f"    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>\n")
            s = s.replace("</urlset>", entry + "</urlset>")
            sm.write_text(s, encoding="utf-8")
            print("✅ sitemap.xml に登録")
        else:
            print("ℹ️ sitemap.xml は登録済み")


if __name__ == "__main__":
    main()
