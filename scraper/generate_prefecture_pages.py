#!/usr/bin/env python3
"""
SEO 用の都道府県別ランディングページを自動生成するスクリプト。

機能:
    1. data/teams.json を読み込み、47都道府県それぞれの HTML を生成
       → prefectures/<id>/index.html (例: /prefectures/tokyo/index.html)
    2. sitemap.xml を更新して全ページを Google に伝える
    3. 各ページに OGP / 構造化データ / canonical / 内部リンクを完備

Phase 9-A ステップ2 で追加された構造化データ:
    - FAQPage: 各都道府県ごとの Q&A (検索 / AI 検索エンジン対策)
    - ItemList: 順位表をリスト構造として明示
    - SportsTeam (強化版): URL / sport / location / memberOf

使い方:
    cd <repo-root>
    python scraper/generate_prefecture_pages.py

依存ライブラリ: 標準ライブラリのみ (Python 3.8+)
"""
import json
from pathlib import Path
from datetime import date

# ============================================================
# 設定
# ============================================================
BASE_DIR = Path(__file__).parent.parent
TEAMS_FILE = BASE_DIR / "data" / "teams.json"
OUTPUT_ROOT = BASE_DIR / "prefectures"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"
DOMAIN = "https://u18-soccer.com"
GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"


# ============================================================
# ヘルパー
# ============================================================
def html_escape(s):
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def league_category(team_league):
    lg = team_league or ""
    if "プレミアリーグ" in lg:
        return "premier"
    if "プリンスリーグ" in lg:
        return "prince"
    return "prefecture"


def get_top_league(teams):
    if not teams:
        return "未登録"
    has_premier = any(league_category(t.get("league")) == "premier" for t in teams)
    has_prince = any(league_category(t.get("league")) == "prince" for t in teams)
    if has_premier:
        return "プレミアリーグ"
    if has_prince:
        return "プリンスリーグ"
    return "都道府県リーグ1部"


def is_club_youth(team_name):
    """クラブのユース・U-18 チームか判定 (FC東京U-18, ○○ユース, ○○U18 など)"""
    n = team_name or ""
    return any(kw in n for kw in ("U-18", "U18", "ユース", "ジュニアユース"))


def is_high_school(team_name):
    """高校サッカー部か判定 (高校 / 高等学校 を含み、かつクラブユースでない)"""
    n = team_name or ""
    if is_club_youth(n):
        return False
    return ("高校" in n) or ("高等学校" in n)


def count_team_types(teams):
    """高校サッカー部数とクラブユース数をカウント"""
    hs = sum(1 for t in teams if is_high_school(t.get("name", "")))
    cy = sum(1 for t in teams if is_club_youth(t.get("name", "")))
    return hs, cy


def sort_teams(teams):
    """ティア順 → 県内順位順にソート"""
    tier_order = {"premier": 0, "prince": 1, "prefecture": 2}
    return sorted(
        teams,
        key=lambda t: (
            tier_order.get(league_category(t.get("league")), 9),
            t.get("rank") or 99,
        ),
    )


def render_team_row(team, pref_rank):
    league = team.get("league", "—")
    badge_class = league_category(league)
    rank_class = f"rank-{pref_rank}" if pref_rank <= 3 else "rank-other"
    league_rank = team.get("leagueRank") if team.get("leagueRank") is not None else team.get("rank")
    league_rank_str = f"{league_rank}位" if league_rank not in (None, "") else "—"
    points = team.get("points", 0) or 0
    played = team.get("played", 0) or 0
    won = team.get("won", 0) or 0
    drawn = team.get("drawn", 0) or 0
    lost = team.get("lost", 0) or 0
    goal_diff = (team.get("goalsFor", 0) or 0) - (team.get("goalsAgainst", 0) or 0)
    diff_str = f"+{goal_diff}" if goal_diff > 0 else str(goal_diff)
    diff_class = (
        "goal-diff-positive" if goal_diff > 0
        else "goal-diff-negative" if goal_diff < 0
        else "goal-diff-zero"
    )
    return f"""        <tr>
          <td><span class="rank-badge {rank_class}">{pref_rank}</span></td>
          <td><strong>{html_escape(team.get('name', '—'))}</strong></td>
          <td><span class="league-badge {badge_class}">{html_escape(league)}</span></td>
          <td>{league_rank_str}</td>
          <td><strong>{points}</strong></td>
          <td>{played}</td>
          <td>{won}</td>
          <td>{drawn}</td>
          <td>{lost}</td>
          <td class="{diff_class}" style="color:{'#28a745' if goal_diff > 0 else ('#dc3545' if goal_diff < 0 else '#666')}">{diff_str}</td>
        </tr>"""


# ============================================================
# 構造化データ
# ============================================================
def render_team_schema(teams, pref_name, pref_id):
    """SportsTeam 構造化データ (上位5チーム)"""
    items = []
    canonical = f"{DOMAIN}/prefectures/{pref_id}/"
    for t in sort_teams(teams)[:5]:
        items.append({
            "@type": "SportsTeam",
            "name": t.get("name", ""),
            "sport": "Football",
            "url": canonical,
            "location": {
                "@type": "Place",
                "name": pref_name,
                "address": {
                    "@type": "PostalAddress",
                    "addressCountry": "JP",
                    "addressRegion": pref_name,
                },
            },
            "memberOf": {
                "@type": "SportsOrganization",
                "name": t.get("league", ""),
            },
        })
    return items


def render_breadcrumb_schema(pref_name, pref_id):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": pref_name,
             "item": f"{DOMAIN}/prefectures/{pref_id}/"},
        ],
    }


def render_itemlist_schema(teams, pref_name, pref_id):
    """順位表を ItemList として表現"""
    canonical = f"{DOMAIN}/prefectures/{pref_id}/"
    sorted_t = sort_teams(teams)[:20]  # 上位20チームまで構造化データ化
    if not sorted_t:
        return None
    item_list = []
    for i, t in enumerate(sorted_t):
        item_list.append({
            "@type": "ListItem",
            "position": i + 1,
            "item": {
                "@type": "SportsTeam",
                "name": t.get("name", ""),
                "sport": "Football",
                "memberOf": t.get("league", ""),
            },
        })
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"{pref_name} U-18 高校サッカー 順位表",
        "description": f"{pref_name}の高校サッカーチーム順位リスト",
        "url": canonical,
        "numberOfItems": len(item_list),
        "itemListElement": item_list,
    }


def build_faqs(pref_name, teams):
    """都道府県ごとの FAQ を生成（5問）"""
    sorted_t = sort_teams(teams)
    team_count = len(teams)
    hs_count, cy_count = count_team_types(teams)

    # Q1: 上位チーム（上位3チーム = 高校・クラブユース両方を含む）
    top3 = sorted_t[:3]
    if top3:
        top3_names = "、".join(html_escape(t.get("name", "")) for t in top3)
        a1 = (
            f"現在の最新データでは、{html_escape(pref_name)}の上位3チームは<strong>{top3_names}</strong>です。"
            f"順位はリーグカテゴリ（プレミア＞プリンス＞都道府県1部）と、各リーグ内順位を加味してランキングしています。"
        )
    else:
        a1 = f"{html_escape(pref_name)}のデータはまだ準備中です。"

    # Q2: チーム数（高校サッカー部・クラブユースを区別）
    if hs_count > 0 and cy_count > 0:
        a2 = (
            f"{html_escape(pref_name)}には<strong>高校サッカー部 {hs_count}校</strong>と"
            f"<strong>クラブユース {cy_count}チーム</strong>（J リーグクラブの U-18 / ユースなど）の"
            f"合計 {team_count} チームが U-18 年代の各種リーグ"
            f"（高円宮杯JFA U-18 サッカープレミアリーグ・プリンスリーグ・都道府県リーグ1部）に参加しています。"
            f"なお、本サイトでは都道府県リーグの<strong>1部</strong>に所属するチームのみを掲載しており、2部以下は対象外です。"
        )
    elif hs_count > 0:
        a2 = (
            f"{html_escape(pref_name)}からは<strong>高校サッカー部 {hs_count}校</strong>が"
            f" U-18 年代の各種リーグ（高円宮杯JFA U-18 サッカープレミアリーグ・プリンスリーグ・都道府県リーグ1部）に参加しています。"
            f"なお、本サイトでは都道府県リーグの<strong>1部</strong>に所属するチームのみを掲載しており、2部以下は対象外です。"
        )
    elif cy_count > 0:
        a2 = (
            f"{html_escape(pref_name)}からは<strong>クラブユース {cy_count}チーム</strong>が"
            f" U-18 年代の各種リーグ（高円宮杯JFA U-18 サッカープレミアリーグ・プリンスリーグ・都道府県リーグ1部）に参加しています。"
        )
    else:
        a2 = f"{html_escape(pref_name)}のデータはまだ準備中です。"

    # Q3: プレミア所属チーム
    premier_teams = [t for t in teams if league_category(t.get("league")) == "premier"]
    if premier_teams:
        names = "、".join(html_escape(t.get("name", "")) for t in premier_teams)
        a3 = f"<strong>{names}</strong>がプレミアリーグに所属しています。プレミアリーグは全国2地域（EAST/WEST 各12チーム）の最上位リーグです。"
    else:
        prince_teams = [t for t in teams if league_category(t.get("league")) == "prince"]
        if prince_teams:
            names = "、".join(html_escape(t.get("name", "")) for t in prince_teams)
            a3 = (
                f"現在、{html_escape(pref_name)}からプレミアリーグへの所属はありません。"
                f"プリンスリーグには<strong>{names}</strong>が所属しています。"
            )
        else:
            a3 = (
                f"現在、{html_escape(pref_name)}からプレミアリーグ・プリンスリーグへの所属はありません。"
                f"上位リーグへの昇格を目指す<strong>都道府県リーグ1部</strong>所属チームの順位を本サイトで確認できます。"
            )

    # Q4: 更新頻度
    a4 = (
        "本サイトの順位データは <strong>毎日 9:00 (JST)</strong> 頃に自動更新されています。"
        "JFA（日本サッカー協会）公式サイト・各都道府県サッカー協会の最新データを反映しているため、"
        "週末の試合結果も最短で翌朝には順位表に反映されます。"
    )

    # Q5: 大会説明
    a5 = (
        "高円宮杯 JFA U-18 サッカーリーグは、日本サッカー協会主催の U-18（高校生年代）向けリーグ戦です。"
        "<strong>プレミアリーグ</strong>（全国2地域 各12チーム）、<strong>プリンスリーグ</strong>（9地域）、"
        "<strong>都道府県リーグ</strong>（1部・2部・3部など複数のディビジョン）という階層的なピラミッド構造になっており、"
        "各リーグ間で昇降格があります。"
        f"なお本サイトでは、{html_escape(pref_name)}を含む各都道府県の<strong>1部</strong>所属チームのみを掲載対象としています。"
    )

    return [
        (f"{html_escape(pref_name)}で最も強い高校サッカー部・クラブユースはどこですか？", a1),
        (f"{html_escape(pref_name)}の U-18 年代のチーム構成は？（高校サッカー部・クラブユース）", a2),
        (f"{html_escape(pref_name)}のプレミアリーグ・プリンスリーグ所属チームは？", a3),
        ("順位データはいつ更新されますか？", a4),
        ("高円宮杯 JFA U-18 サッカーリーグとは何ですか？", a5),
    ]


def render_faq_schema(faqs):
    """FAQPage 構造化データ"""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": strip_tags(q),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": strip_tags(a),
                },
            }
            for q, a in faqs
        ],
    }


def strip_tags(s):
    """構造化データ用に簡易的にタグを除去"""
    import re
    return re.sub(r"<[^>]+>", "", s)


def render_faq_html(faqs):
    """可視 FAQ セクションの HTML を生成 (details/summary)"""
    items = []
    for q, a in faqs:
        items.append(
            f'        <details class="lp-faq-item">\n'
            f'          <summary class="lp-faq-q">{q}</summary>\n'
            f'          <div class="lp-faq-a">{a}</div>\n'
            f'        </details>'
        )
    return "\n".join(items)


# ============================================================
# HTML テンプレート
# ============================================================
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <!-- Google Analytics -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=__GA_ID__"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', '__GA_ID__');
  </script>

  <!-- Google AdSense -->
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=__ADSENSE__"
          crossorigin="anonymous"></script>
  <meta name="google-adsense-account" content="__ADSENSE__">

  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">

  <title>__TITLE__</title>
  <meta name="description" content="__DESCRIPTION__">
  <meta name="keywords" content="__KEYWORDS__">
  <meta name="robots" content="index, follow">
  <meta name="format-detection" content="telephone=no">
  <link rel="canonical" href="__CANONICAL__">

  <!-- OGP -->
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="__TITLE__">
  <meta property="og:description" content="__DESCRIPTION__">
  <meta property="og:url" content="__CANONICAL__">
  <meta property="og:image" content="https://u18-soccer.com/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:locale" content="ja_JP">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="__TITLE__">
  <meta name="twitter:description" content="__DESCRIPTION__">
  <meta name="twitter:image" content="https://u18-soccer.com/og-image.png">

  <!-- ファビコン -->
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <meta name="theme-color" content="#1e40af">

  <!-- 構造化データ: BreadcrumbList -->
  <script type="application/ld+json">
__SCHEMA_BREADCRUMB__
  </script>
  <!-- 構造化データ: SportsTeam (上位5チーム) -->
  <script type="application/ld+json">
__SCHEMA_TEAMS__
  </script>
  <!-- 構造化データ: ItemList (順位表) -->
  <script type="application/ld+json">
__SCHEMA_ITEMLIST__
  </script>
  <!-- 構造化データ: FAQPage -->
  <script type="application/ld+json">
__SCHEMA_FAQ__
  </script>

  <!-- フォント・アイコン・スタイル -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/css/style.css">

  <!-- ダークモード初期化 (FOUC 防止) -->
  <script>
    (function() {
      try {
        var t = localStorage.getItem('theme');
        if (t === 'light' || t === 'dark') {
          document.documentElement.setAttribute('data-theme', t);
        }
      } catch (e) {}
    })();
  </script>
</head>
<body>
  <header class="header">
    <div class="container">
      <div class="header-content">
        <h1 class="site-title">
          <a href="/" style="color:white;text-decoration:none;display:inline-flex;align-items:center;gap:10px">
            <i class="fas fa-futbol"></i>
            高校サッカー順位確認システム
          </a>
        </h1>
        <nav class="nav">
          <a href="/" class="nav-link"><i class="fas fa-home"></i> ホーム</a>
          <a href="/#search" class="nav-link"><i class="fas fa-search"></i> 検索</a>
        </nav>
      </div>
    </div>
  </header>

  <main class="main-content">
    <div class="container">
      <!-- パンくずリスト -->
      <nav class="breadcrumb" aria-label="パンくずリスト">
        <a href="/">ホーム</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">__PREF_NAME__</span>
      </nav>

      <h1 class="lp-title">__PREF_NAME__ U-18 高校サッカー 順位表</h1>

      <p class="lp-intro">
        __PREF_NAME__の高校サッカー部・クラブユース（U-18年代）所属
        <strong>__TEAM_COUNT__チーム</strong>（高校 __HS_COUNT__校＋クラブユース __CY_COUNT__チーム）
        の最新順位・成績情報。
        高円宮杯JFA U-18サッカープレミアリーグ・プリンスリーグ・__PREF_NAME__リーグ1部の順位表を、
        毎日最新データに自動更新しています（都道府県リーグは1部のみ掲載）。
      </p>

      <!-- 統計 -->
      <div class="stats-summary">
        <div class="stat-item">
          <div class="stat-label">登録チーム数</div>
          <div class="stat-value">__TEAM_COUNT__</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">最高リーグ</div>
          <div class="stat-value">__TOP_LEAGUE__</div>
        </div>
      </div>

      <!-- メイン CTA -->
      <div class="lp-cta">
        <a href="/" class="lp-cta__btn">
          <i class="fas fa-bolt"></i> 全国版・インタラクティブビュー (検索/お気に入り/詳細表示)
        </a>
      </div>

      <!-- チーム一覧 -->
      <h2 class="section-title-lp">__PREF_NAME__ 所属チーム順位表</h2>
      <div id="teamsTableLP" style="overflow-x:auto;-webkit-overflow-scrolling:touch;">
        <table class="data-table">
          <thead>
            <tr>
              <th>県内順位</th>
              <th>チーム名</th>
              <th>リーグ</th>
              <th>順位</th>
              <th>勝点</th>
              <th>試合</th>
              <th>勝</th>
              <th>分</th>
              <th>負</th>
              <th>得失差</th>
            </tr>
          </thead>
          <tbody>
__TEAM_ROWS__
          </tbody>
        </table>
      </div>

      <!-- 説明文 (SEO 用) -->
      <section class="lp-section">
        <h2>__PREF_NAME__ U-18 高校サッカーについて</h2>
        <p>
          __PREF_NAME__からは現在<strong>高校サッカー部 __HS_COUNT__校</strong>と
          <strong>クラブユース __CY_COUNT__チーム</strong>（合計 __TEAM_COUNT__ チーム）が
          U-18 年代の各種リーグに参加しています。所属する最高位リーグは<strong>__TOP_LEAGUE__</strong>です。
        </p>
        <p>
          高円宮杯 JFA U-18 サッカーリーグは、日本サッカー協会主催の U-18（高校生年代）向けリーグ戦で、
          全国規模の<strong>プレミアリーグ</strong>（東西各12チーム）、9地域それぞれの<strong>プリンスリーグ</strong>、
          各都道府県の<strong>都道府県リーグ</strong>（1部・2部・3部などの複数ディビジョン）という階層構造になっています。
          各リーグの上位・下位チームには毎年昇降格があり、上位リーグ昇格を目指してハイレベルな戦いが繰り広げられています。
          なお、本サイトでは都道府県リーグは<strong>1部</strong>所属チームのみを掲載しています。
        </p>
      </section>

      <!-- ★ FAQ セクション (Phase 9-A ステップ2 で追加) -->
      <section class="lp-section lp-faq">
        <h2><i class="fas fa-question-circle"></i> よくある質問</h2>
__FAQ_HTML__
      </section>

      <!-- 近隣の都道府県 -->
      <section class="lp-section">
        <h2>近隣の都道府県</h2>
        <div class="lp-neighbor-grid">
__NEIGHBOR_LINKS__
        </div>
      </section>

      <!-- 関連リンク -->
      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/">全国の高校サッカー順位表トップ</a></li>
          <li><a href="/#search">チーム名で検索</a></li>
          <li><a href="/about.html">運営者情報</a></li>
          <li><a href="/contact.html">お問い合わせ</a></li>
        </ul>
      </section>
    </div>
  </main>

  <footer class="footer">
    <div class="container">
      <p>&copy; 2025 高校サッカー順位確認システム</p>
      <nav class="footer-nav" style="margin-top:12px;">
        <a href="/about.html">運営者情報</a> ・
        <a href="/privacy.html">プライバシーポリシー</a> ・
        <a href="/contact.html">お問い合わせ</a>
      </nav>
      <p class="footer-note" style="margin-top:12px;">
        <i class="fas fa-info-circle"></i>
        データ出典：JFA（日本サッカー協会）、各都道府県サッカー協会、各高校・クラブ公式情報。最新情報は各公式サイトをご確認ください。
      </p>
    </div>
  </footer>
</body>
</html>
"""


def generate_page(pref, all_prefs):
    pref_id = pref["id"]
    pref_name = pref["name"]
    teams = pref["teams"]
    team_count = len(teams)
    hs_count, cy_count = count_team_types(teams)
    top_league = get_top_league(teams)
    canonical = f"{DOMAIN}/prefectures/{pref_id}/"

    sorted_teams = sort_teams(teams)
    if sorted_teams:
        team_rows = "\n".join(
            render_team_row(t, i + 1) for i, t in enumerate(sorted_teams)
        )
    else:
        team_rows = (
            '        <tr><td colspan="10" '
            'style="text-align:center;padding:30px;color:#888;">'
            f'{html_escape(pref_name)}のデータはまだ登録されていません</td></tr>'
        )

    region = pref.get("region") or ""
    neighbors = [p for p in all_prefs if p.get("region") == region and p["id"] != pref_id]
    if neighbors:
        neighbor_links = "\n".join(
            f'          <a href="/prefectures/{n["id"]}/" class="lp-neighbor-link">{html_escape(n["name"])}</a>'
            for n in neighbors
        )
    else:
        neighbor_links = '          <p style="color:#888;">情報を準備中</p>'

    title = f"{pref_name} 高校サッカー U-18 順位表 | プレミア・プリンス・{pref_name}リーグ1部"
    description = (
        f"{pref_name}の高校サッカー部・クラブユース（U-18年代）{team_count}チームの最新順位・成績。"
        f"高円宮杯JFA U-18サッカープレミアリーグ・プリンスリーグ・{pref_name}リーグ1部の順位表を毎日自動更新。"
        "（都道府県リーグは1部のみ掲載）"
    )
    keywords = (
        f"{pref_name},高校サッカー,クラブユース,U-18,U18,高円宮杯,プレミアリーグ,プリンスリーグ,"
        f"{pref_name}リーグ1部,{pref_name}リーグ,順位,成績,日程,結果"
    )

    # 構造化データ
    breadcrumb = json.dumps(
        render_breadcrumb_schema(pref_name, pref_id),
        ensure_ascii=False, indent=2
    )
    teams_schema = json.dumps(
        {"@context": "https://schema.org", "@graph": render_team_schema(teams, pref_name, pref_id)},
        ensure_ascii=False, indent=2
    )
    itemlist = render_itemlist_schema(teams, pref_name, pref_id)
    if itemlist:
        itemlist_json = json.dumps(itemlist, ensure_ascii=False, indent=2)
    else:
        # データなし都道府県は空の ItemList を出さない
        itemlist_json = json.dumps({"@context": "https://schema.org", "@type": "ItemList", "name": f"{pref_name} 順位表 (準備中)", "itemListElement": []}, ensure_ascii=False, indent=2)

    # FAQ
    faqs = build_faqs(pref_name, teams)
    faq_schema = json.dumps(render_faq_schema(faqs), ensure_ascii=False, indent=2)
    faq_html = render_faq_html(faqs)

    return (
        PAGE_TEMPLATE
        .replace("__GA_ID__", GA_ID)
        .replace("__ADSENSE__", ADSENSE_CLIENT)
        .replace("__TITLE__", html_escape(title))
        .replace("__DESCRIPTION__", html_escape(description))
        .replace("__KEYWORDS__", html_escape(keywords))
        .replace("__CANONICAL__", canonical)
        .replace("__SCHEMA_BREADCRUMB__", breadcrumb)
        .replace("__SCHEMA_TEAMS__", teams_schema)
        .replace("__SCHEMA_ITEMLIST__", itemlist_json)
        .replace("__SCHEMA_FAQ__", faq_schema)
        .replace("__PREF_NAME__", html_escape(pref_name))
        .replace("__TEAM_COUNT__", str(team_count))
        .replace("__HS_COUNT__", str(hs_count))
        .replace("__CY_COUNT__", str(cy_count))
        .replace("__TOP_LEAGUE__", html_escape(top_league))
        .replace("__TEAM_ROWS__", team_rows)
        .replace("__NEIGHBOR_LINKS__", neighbor_links)
        .replace("__FAQ_HTML__", faq_html)
    )


def update_sitemap(all_prefs):
    today = date.today().isoformat()
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
             '  <url>',
             f'    <loc>{DOMAIN}/</loc>',
             f'    <lastmod>{today}</lastmod>',
             '    <changefreq>daily</changefreq>',
             '    <priority>1.0</priority>',
             '  </url>']
    for p in all_prefs:
        parts.extend([
            '  <url>',
            f'    <loc>{DOMAIN}/prefectures/{p["id"]}/</loc>',
            f'    <lastmod>{today}</lastmod>',
            '    <changefreq>daily</changefreq>',
            '    <priority>0.8</priority>',
            '  </url>',
        ])
    # 静的ページも登録
    for static_url in ("/about.html", "/privacy.html", "/contact.html"):
        parts.extend([
            '  <url>',
            f'    <loc>{DOMAIN}{static_url}</loc>',
            f'    <lastmod>{today}</lastmod>',
            '    <changefreq>monthly</changefreq>',
            '    <priority>0.4</priority>',
            '  </url>',
        ])
    parts.append('</urlset>')
    SITEMAP_FILE.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"sitemap.xml 更新: {len(all_prefs) + 1 + 3} URL を登録")


def main():
    if not TEAMS_FILE.exists():
        print(f"[ERROR] {TEAMS_FILE} が見つかりません。先にスクレイパーを実行してください。")
        return 1

    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    all_prefs = [
        {"id": pid, **p}
        for pid, p in teams_data.items()
        if isinstance(p, dict) and "teams" in p
    ]

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    for pref in all_prefs:
        pref_dir = OUTPUT_ROOT / pref["id"]
        pref_dir.mkdir(parents=True, exist_ok=True)
        html = generate_page(pref, all_prefs)
        (pref_dir / "index.html").write_text(html, encoding="utf-8")

    update_sitemap(all_prefs)
    print(f"完了: {len(all_prefs)} 都道府県の SEO ランディングページを生成しました")
    print(f"   出力先: {OUTPUT_ROOT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
