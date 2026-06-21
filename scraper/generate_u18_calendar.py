#!/usr/bin/env python3
"""
U-18 高校サッカー 年間スケジュール 独自ページ生成スクリプト
====================================================
月別カレンダー表＋主要大会の日程・解説＋規約比較表＋内部リンクを
1ページ /tournaments/u18-calendar-2026/ に出力する。

- 内容はこのファイル内のデータ（MONTHS / COMPETITIONS / RULES）を編集すれば更新可能
- 事実確認済み：インターハイ本戦は51校（47都道府県＋東京・神奈川・大阪・福島が2枠）
- 12月のプレミアファイナル/参入戦などの具体日は年度で前後する「予定」値

依存：標準ライブラリ + generate_jyouth_page（テンプレ定数・html_escape）
"""
import generate_jyouth_page as jy

BASE_DIR = jy.BASE_DIR
DOMAIN = jy.DOMAIN
GA_ID = jy.GA_ID
ADSENSE_CLIENT = jy.ADSENSE_CLIENT
date = jy.date
html_escape = jy.html_escape

OUT_DIR = BASE_DIR / "tournaments" / "u18-calendar-2026"
CANONICAL = f"{DOMAIN}/tournaments/u18-calendar-2026/"

# 月別カレンダー（月, 高体連, クラブユース・Jアカデミー, 高円宮杯リーグ）
MONTHS = [
    ("1月", "新人戦（地区予選〜都道府県大会開始）", "新チーム始動・冬季キャンプ", "前年度・全国高校選手権 本戦（決勝＝1月）"),
    ("2月", "新人戦（都道府県大会・決勝）", "プレシーズンマッチ・各種フェスティバル", "—"),
    ("3月", "春季遠征・フェスティバル（サニックス杯など）", "春季遠征・海外遠征（一部クラブ）", "東京都新人戦 都大会本戦 など"),
    ("4月", "地方大会（関東・東海等）都道府県予選 開始", "—", "プレミア・プリンス・都道府県（FA）各リーグ 一斉開幕"),
    ("5月", "地方大会予選 決勝／インターハイ都道府県予選 開始", "Jユースカップ 開幕（1回戦）", "リーグ戦進行（GW中の過密日程あり）"),
    ("6月", "地方大会（関東・東海等）本戦／インターハイ予選 決勝", "Jユースカップ（2回戦〜準々決勝）", "リーグ戦 第1クール 最終盤"),
    ("7月", "インターハイ（全国高校総体）本戦 開幕", "Jユースカップ 準決勝・決勝", "サマーブレイク（リーグ戦 一時中断）"),
    ("8月", "インターハイ本戦 決勝／選手権 1次予選 開始", "夏期強化合宿・招待大会", "（サマーブレイク 継続）"),
    ("9月", "選手権 都道府県予選（ブロック予選）", "—", "リーグ戦 再開（第2クール）"),
    ("10月", "選手権 都道府県予選（決勝トーナメント開始）", "国スポ（国民スポーツ大会）少年男子の部", "リーグ戦終盤の順位・残留争い"),
    ("11月", "選手権 都道府県予選 準決勝・決勝", "—", "リーグ戦 最終盤"),
    ("12月", "全国高校選手権 本戦 開幕（12/28頃〜）", "クラブユース選手権 本戦（12/23〜29）／Town Club CUP（12/26〜29）", "リーグ最終節・プレミアファイナル・各参入戦（12月／予定）"),
]

# 主要大会（見出し, バッジ, リンク先(無ければ空), 説明HTML）
COMPETITIONS = [
    ("高円宮杯 JFA U-18サッカーリーグ", "通年リーグ", "/leagues/",
     "U-18強化の根幹。<strong>プレミアリーグ</strong>（全国24チーム＝EAST/WEST各12）を頂点に、地域の<strong>プリンスリーグ</strong>（9地域）、47<strong>都道府県リーグ</strong>が連なるピラミッド構造で、全結果が昇降格に直結します。4月開幕・全22節（プレミア）、夏（7〜8月）はインターハイ等のため一時中断（サマーブレイク）し、9月再開、12月中旬最終節。"),
    ("インターハイ（全国高校総体）", "夏・7/25〜8/1", "/tournaments/interhigh-2026/",
     "高体連の夏の最大目標。都道府県予選（5月中旬〜6月中旬）を勝ち抜いた<strong>全国51校</strong>（47都道府県＋東京・神奈川・大阪・開催県福島が各2枠）が出場。2026年度は<strong>福島県・Jヴィレッジ</strong>で7/25〜8/1の約1週間に集中開催。70分（35分ハーフ）・決勝のみ20分延長。"),
    ("地域大会（東北・北信越・東海・中国・四国・九州 など）", "5月下旬〜6月", "/tournaments/regional-2026/",
     "各県予選の上位校が地区ごとに集う前哨戦。関東大会は5月下旬、東海大会は6月中旬（6/20〜23頃）など、インターハイ直前に開催されます。"),
    ("全国高校サッカー選手権大会", "冬・12/28〜1月", "",
     "冬の風物詩。都道府県予選は早い地域で8月下旬から、決勝は概ね11月上旬〜中旬に集中。本戦は例年<strong>12月28日（または30日）開幕、1月の成人の日に決勝</strong>。3年生の集大成となる最後の公式戦です。"),
    ("Jユースカップ（Jリーグユース選手権）", "5/9〜7/5", "/tournaments/j-youth-cup-2026/",
     "Jクラブのユース（U-18）等<strong>64チーム</strong>による完全ノックアウト。かつての秋開催から前倒しされ、2026年度は5/9開幕・7/4準決勝・<strong>7/5決勝（IAIスタジアム日本平）</strong>。80分（決勝のみ90分）・延長なしの即PK。"),
    ("日本クラブユースサッカー選手権（U-18）", "冬・12/23〜29", "",
     "JCY主催の最高峰。猛暑対策（過去にピッチ44℃を記録）から<strong>2026年度より完全に冬季へ移行</strong>。広島・山口で12/23〜29開催。グループリーグを廃止し、全国9地域代表<strong>32チームのストレートノックアウト</strong>に刷新。90分・即PK（決勝のみ20分延長後PK）、交代5名。"),
    ("12月のプレーオフ・ファイナル", "12月（予定）", "",
     "通年リーグの最終決着。プレミアEAST王者×WEST王者の<strong>プレミアファイナル</strong>（12/20〜21頃・埼玉スタジアム等）、プリンス上位16チームがプレミア昇格4枠を争う<strong>プレミア参入戦（プレーオフ）</strong>、都道府県リーグ→プリンスの<strong>各地域参入戦</strong>が集中。日付は年度で前後します。"),
]

# 主要トーナメントの規約比較（大会, 出場, 試合時間, 勝敗決定, 交代）
RULES = [
    ("インターハイ（高校総体）", "51校", "70分（35分ハーフ）／決勝のみ20分延長", "延長なし→PK（決勝は延長後PK）", "—"),
    ("Jユースカップ", "64チーム", "80分（前後半40分）／決勝のみ90分", "延長なし・即PK", "—"),
    ("日本クラブユース選手権 U-18", "32チーム", "90分（前後半45分）", "延長なし・即PK（決勝のみ20分延長後PK）", "最大5名（交代3回まで）"),
    ("Town Club CUP", "16チーム", "80分／準決勝・決勝は90分", "延長なし・即PK（決勝のみ20分延長後PK）", "—"),
]


def render_month_table():
    rows = []
    for m, kt, cy, lg in MONTHS:
        rows.append(
            f'<tr><th scope="row" style="white-space:nowrap;">{html_escape(m)}</th>'
            f'<td>{html_escape(kt)}</td><td>{html_escape(cy)}</td><td>{html_escape(lg)}</td></tr>'
        )
    return (
        '<div style="overflow-x:auto;">'
        '<table class="u18cal-table">'
        '<thead><tr><th>月</th><th>高体連（高校サッカー部）</th>'
        '<th>クラブユース・Jアカデミー</th><th>高円宮杯リーグ ほか</th></tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody></table></div>'
    )


def render_competitions():
    blocks = []
    for title, badge, href, body in COMPETITIONS:
        badge_html = (f'<span style="display:inline-block;margin-left:8px;padding:2px 10px;border-radius:999px;'
                      f'background:#dbeafe;color:#1e40af;font-weight:600;font-size:0.78em;">{html_escape(badge)}</span>'
                      if badge else "")
        h = (f'<a href="{href}">{html_escape(title)}</a>' if href else html_escape(title))
        link_more = (f'<p style="margin:8px 0 0;"><a href="{href}">→ {html_escape(title)}のページへ</a></p>' if href else "")
        blocks.append(
            f'<div style="padding:14px 16px;margin:10px 0;background:var(--bg-light);'
            f'border:1px solid var(--border-color);border-radius:10px;">'
            f'<h3 style="margin:0 0 6px;font-size:1.05rem;">{h}{badge_html}</h3>'
            f'<p style="margin:0;line-height:1.85;">{body}</p>{link_more}</div>'
        )
    return "\n".join(blocks)


def render_rules_table():
    rows = []
    for name, n, t, dec, sub in RULES:
        rows.append(
            f'<tr><th scope="row" style="white-space:nowrap;">{html_escape(name)}</th>'
            f'<td>{html_escape(n)}</td><td>{html_escape(t)}</td><td>{html_escape(dec)}</td><td>{html_escape(sub)}</td></tr>'
        )
    return (
        '<div style="overflow-x:auto;">'
        '<table class="u18cal-table">'
        '<thead><tr><th>大会</th><th>出場</th><th>試合時間</th><th>勝敗決定</th><th>交代</th></tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody></table></div>'
    )


def main():
    year = 2026
    seo_title = "U-18高校サッカー 年間スケジュール2026｜高円宮杯・インターハイ・選手権・Jユース・クラブユース 完全カレンダー"
    description = (
        "U-18（高校生年代）サッカーの年間スケジュールを1ページに集約。高円宮杯プレミア/プリンス/都道府県リーグ、"
        "インターハイ（7/25〜8/1・福島）、全国高校選手権、地域大会、Jユースカップ、冬季移行した日本クラブユース選手権まで、"
        "月別カレンダーと主要大会の日程・規約をまとめて解説します。"
    )
    keywords = (
        "U-18 高校サッカー 年間スケジュール,高円宮杯 日程,インターハイ サッカー 日程,高校サッカー選手権 日程,"
        "Jユースカップ 日程,クラブユース選手権 冬季,プレミアリーグ プリンスリーグ,高校サッカー カレンダー,U-18"
    )

    today = date.today()
    _wd = "月火水木金土日"[today.weekday()]
    updated_str = f"{today.year}年{today.month}月{today.day}日（{_wd}）"
    updated_html = (f'<p style="text-align:right;color:var(--text-secondary,#6b7280);font-size:0.85em;margin:4px 0 0;">'
                    f'<i class="fas fa-clock"></i> 最終更新：{updated_str}</p>')

    breadcrumb_schema = (
        '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":['
        '{"@type":"ListItem","position":1,"name":"ホーム","item":"' + DOMAIN + '/"},'
        '{"@type":"ListItem","position":2,"name":"U-18高校サッカー 年間スケジュール' + str(year) + '","item":"' + CANONICAL + '"}]}'
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
        <span aria-current="page">U-18高校サッカー 年間スケジュール{year}</span>
      </nav>
      <h1 class="lp-title">U-18 高校サッカー 年間スケジュール {year}</h1>
      {updated_html}
      <p class="lp-intro">
        日本のU-18（高校生年代）サッカーは、学校体育を基盤とする<strong>高体連</strong>の大会（インターハイ・選手権）と、
        Jクラブ育成組織を中心とする<strong>クラブユース</strong>の大会（Jユースカップ・クラブユース選手権）、
        そして両者が拮抗する通年リーグ<strong>「高円宮杯 JFA U-18サッカーリーグ」</strong>が複雑に交差する、世界でも珍しい育成エコシステムです。
        このページは、その1年間の流れを月別カレンダーと主要大会の日程で“地図”のようにまとめたものです。
        各大会の最新の結果・順位は当サイトの<a href="/">都道府県別ページ</a>・<a href="/leagues/">リーグ一覧</a>からご覧いただけます。
      </p>

      <section class="lp-section">
        <h2><i class="fas fa-calendar-days"></i> 月別カレンダー（年間の流れ）</h2>
        {render_month_table()}
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-trophy"></i> 主要大会の日程と解説</h2>
        {render_competitions()}
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-scale-balanced"></i> 主要トーナメントの規約比較</h2>
        {render_rules_table()}
        <p style="color:var(--text-secondary,#6b7280);font-size:0.88em;margin-top:8px;">
          ※ 12月のプレミアファイナル・各参入戦などの具体的な日付は年度ごとに前後します。最終的な日程は各主催（JFA・JCY・各都道府県高体連）の公式情報をご確認ください。
        </p>
      </section>

      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/tournaments/interhigh-2026/">インターハイ2026 全国大会 速報・結果</a></li>
          <li><a href="/tournaments/regional-2026/">高校サッカー 地域大会まとめ2026</a></li>
          <li><a href="/tournaments/j-youth-cup-2026/">Jユースカップ2026</a></li>
          <li><a href="/leagues/">リーグ一覧（プレミア・プリンス）</a></li>
          <li><a href="/">全国47都道府県の高校サッカー順位・予選結果</a></li>
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
    print(f"✅ 生成: {OUT_DIR / 'index.html'}")

    sm = BASE_DIR / "sitemap.xml"
    if sm.exists():
        s = sm.read_text(encoding="utf-8")
        if CANONICAL not in s:
            entry = (f"  <url>\n    <loc>{CANONICAL}</loc>\n    <lastmod>{date.today().isoformat()}</lastmod>\n"
                     f"    <changefreq>monthly</changefreq>\n    <priority>0.7</priority>\n  </url>\n")
            s = s.replace("</urlset>", entry + "</urlset>")
            sm.write_text(s, encoding="utf-8")
            print("✅ sitemap.xml に登録")
        else:
            print("ℹ️ sitemap.xml は登録済み")


if __name__ == "__main__":
    main()
