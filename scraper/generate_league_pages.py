#!/usr/bin/env python3
"""
高円宮杯 U-18 各リーグ専用ページを自動生成 (Phase 9-B)
機能:
    1. data/teams.json を読み込み、ユニークなリーグごとにページ生成
       → leagues/<slug>/index.html (例: /leagues/premier-east/index.html)
    2. リーグ一覧ハブページ生成
       → leagues/index.html
    3. sitemap.xml を完全版で更新（トップ + 47都道府県 + 静的 + 全リーグ）
    4. 各ページに OGP / 構造化データ / canonical / 内部リンクを完備
    5. data/league_history.yml から過去5年優勝校履歴を表示
使い方:
    cd <repo-root>
    python scraper/generate_league_pages.py
依存ライブラリ: 標準ライブラリ + PyYAML (pip install pyyaml)
注意:
    このスクリプトは generate_prefecture_pages.py の **後** に実行してください。
    sitemap.xml をこのスクリプトが最終的に書き換えます。
"""
import json
import re
import yaml
from pathlib import Path
from datetime import date

# === リーグ履歴データの読み込み ===
LEAGUE_HISTORY_PATH = Path(__file__).parent.parent / "data" / "league_history.yml"

def load_league_history():
    """過去優勝校データを読み込み"""
    if not LEAGUE_HISTORY_PATH.exists():
        print(f"⚠️ {LEAGUE_HISTORY_PATH} が存在しません")
        return {}
    try:
        with open(LEAGUE_HISTORY_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"⚠️ league_history.yml 読み込みエラー: {e}")
        return {}

LEAGUE_HISTORY = load_league_history()

# ============================================================
# 設定
# ============================================================
BASE_DIR = Path(__file__).parent.parent
TEAMS_FILE = BASE_DIR / "data" / "teams.json"
OUTPUT_ROOT = BASE_DIR / "leagues"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"
DOMAIN = "https://u18-soccer.com"
GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"


# ============================================================
# リーグ → URL slug & メタ情報
# ============================================================
# キー: data 内のリーグ名（完全一致）
# 値: (URL slug, 表示名, カテゴリ, 説明)
LEAGUE_DEFS = {
    "プレミアリーグEAST": (
        "premier-east",
        "プレミアリーグ EAST",
        "premier",
        "高円宮杯 JFA U-18 サッカープレミアリーグ EAST。全国2地域に分かれる最上位リーグの東日本側で、東日本の強豪12チームが参加。",
    ),
    "プレミアリーグWEST": (
        "premier-west",
        "プレミアリーグ WEST",
        "premier",
        "高円宮杯 JFA U-18 サッカープレミアリーグ WEST。全国2地域に分かれる最上位リーグの西日本側で、西日本の強豪12チームが参加。",
    ),
    "プリンスリーグ北海道": (
        "prince-hokkaido",
        "プリンスリーグ 北海道",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 北海道。北海道の強豪チームが集結する2部相当のリーグ。",
    ),
    "プリンスリーグ東北": (
        "prince-tohoku",
        "プリンスリーグ 東北",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 東北。青森・岩手・宮城・秋田・山形・福島の強豪チームが参加。",
    ),
    "プリンスリーグ関東1部": (
        "prince-kanto-1",
        "プリンスリーグ 関東 1部",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 関東 1部。関東地方（茨城・栃木・群馬・埼玉・千葉・東京・神奈川・山梨）の上位チームが参加。",
    ),
    "プリンスリーグ関東2部": (
        "prince-kanto-2",
        "プリンスリーグ 関東 2部",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 関東 2部。関東地方の準上位チームが参加。",
    ),
    "プリンスリーグ北信越": (
        "prince-hokushinetsu",
        "プリンスリーグ 北信越",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 北信越。新潟・長野・富山・石川・福井の強豪チームが参加。",
    ),
    "プリンスリーグ東海": (
        "prince-tokai",
        "プリンスリーグ 東海",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 東海。静岡・愛知・岐阜・三重の強豪チームが参加。",
    ),
    "プリンスリーグ関西1部": (
        "prince-kansai-1",
        "プリンスリーグ 関西 1部",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 関西 1部。関西地方（滋賀・京都・大阪・兵庫・奈良・和歌山）の上位チームが参加。",
    ),
    "プリンスリーグ関西2部": (
        "prince-kansai-2",
        "プリンスリーグ 関西 2部",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 関西 2部。関西地方の準上位チームが参加。",
    ),
    "プリンスリーグ中国": (
        "prince-chugoku",
        "プリンスリーグ 中国",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 中国。鳥取・島根・岡山・広島・山口の強豪チームが参加。",
    ),
    "プリンスリーグ四国": (
        "prince-shikoku",
        "プリンスリーグ 四国",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 四国。徳島・香川・愛媛・高知の強豪チームが参加。",
    ),
    "プリンスリーグ九州1部": (
        "prince-kyushu-1",
        "プリンスリーグ 九州 1部",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 九州 1部。九州・沖縄地方の上位チームが参加。",
    ),
    "プリンスリーグ九州2部": (
        "prince-kyushu-2",
        "プリンスリーグ 九州 2部",
        "prince",
        "高円宮杯 JFA U-18 サッカープリンスリーグ 九州 2部。九州・沖縄地方の準上位チームが参加。",
    ),
}


# ============================================================
# ヘルパー
# ============================================================
def html_escape(s):
    if s is None:
        return ""
    return (
        str(s).replace("&", "&amp;")
        .replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&#39;")
    )


def league_category(team_league):
    lg = team_league or ""
    if "プレミアリーグ" in lg:
        return "premier"
    if "プリンスリーグ" in lg:
        return "prince"
    return "prefecture"


def collect_teams_by_league(teams_data):
    """リーグ名 → そのリーグ所属チームのリスト
    各チームには所属都道府県情報も付与
    """
    result = {}
    for pref_id, pref_data in teams_data.items():
        if not isinstance(pref_data, dict) or "teams" not in pref_data:
            continue
        for t in pref_data["teams"]:
            league = t.get("league", "")
            if league not in result:
                result[league] = []
            result[league].append({
                **t,
                "_pref_id": pref_id,
                "_pref_name": pref_data.get("name", pref_id),
            })
    return result

def format_team_name(name):
    """チーム名: U-18, 2nd, 3rd, ユース, F.C. を <span class="nb"> で改行禁止に"""
    if not name:
        return "—"
    escaped = html_escape(name)
    tokens = ["U-18", "U-15", "F.C.", "U18", "U15", "2nd", "3rd", "ユース"]
    for token in sorted(tokens, key=len, reverse=True):
        escaped_token = html_escape(token)
        escaped = escaped.replace(
            escaped_token,
            f'<span class="nb">{escaped_token}</span>'
        )
    return escaped

def render_team_row_for_league(team, rank):
    """リーグページの順位表用 1行 HTML"""
    pref_id = team.get("_pref_id", "")
    pref_name = team.get("_pref_name", "—")
    points = team.get("points", 0) or 0
    played = team.get("played", 0) or 0
    won = team.get("won", 0) or 0
    drawn = team.get("drawn", 0) or 0
    lost = team.get("lost", 0) or 0
    goal_diff = (team.get("goalsFor", 0) or 0) - (team.get("goalsAgainst", 0) or 0)
    diff_str = f"+{goal_diff}" if goal_diff > 0 else str(goal_diff)
    diff_color = "#28a745" if goal_diff > 0 else ("#dc3545" if goal_diff < 0 else "#666")
    rank_class = f"rank-{rank}" if rank <= 3 else "rank-other"
    return f"""        <tr>
          <td><span class="rank-badge {rank_class}">{rank}</span></td>
          <td><strong>{format_team_name(team.get("name", "—"))}</strong></td>
          <td><a href="/prefectures/{pref_id}/" class="league-pref-link">{html_escape(pref_name)}</a></td>
          <td><strong>{points}</strong></td>
          <td>{played}</td>
          <td>{won}</td>
          <td>{drawn}</td>
          <td>{lost}</td>
          <td style="color:{diff_color};font-weight:600;">{diff_str}</td>
        </tr>"""


def render_breadcrumb_schema(label, slug):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム",
             "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "リーグ一覧",
             "item": f"{DOMAIN}/leagues/"},
            {"@type": "ListItem", "position": 3, "name": label,
             "item": f"{DOMAIN}/leagues/{slug}/"},
        ],
    }


def render_league_schema(label, slug, description, teams):
    """SportsOrganization としてリーグを表現"""
    return {
        "@context": "https://schema.org",
        "@type": "SportsOrganization",
        "name": label,
        "url": f"{DOMAIN}/leagues/{slug}/",
        "sport": "Football",
        "description": description,
        "memberOf": {
            "@type": "SportsOrganization",
            "name": "高円宮杯 JFA U-18 サッカーリーグ",
            "url": "https://www.jfa.jp/match/takamado_jfa_u18/",
        },
        "numberOfEmployees": len(teams),
        "areaServed": {"@type": "Country", "name": "日本"},
    }


def render_itemlist_schema(teams, label, slug):
    """順位表 ItemList"""
    canonical = f"{DOMAIN}/leagues/{slug}/"
    if not teams:
        return None
    items = []
    for i, t in enumerate(teams[:30]):
        items.append({
            "@type": "ListItem",
            "position": i + 1,
            "item": {
                "@type": "SportsTeam",
                "name": t.get("name", ""),
                "sport": "Football",
                "memberOf": label,
                "location": {
                    "@type": "Place",
                    "name": t.get("_pref_name", ""),
                    "address": {
                        "@type": "PostalAddress",
                        "addressCountry": "JP",
                        "addressRegion": t.get("_pref_name", ""),
                    },
                },
            },
        })
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"{label} 順位表",
        "description": f"{label}の最新順位（U-18 高校サッカー）",
        "url": canonical,
        "numberOfItems": len(items),
        "itemListElement": items,
    }


def build_faqs(label, teams, slug, category):
    """リーグごとの FAQ"""
    team_count = len(teams)
    sorted_t = sorted(teams, key=lambda t: t.get("leagueRank") or t.get("rank") or 99)
    top3 = sorted_t[:3]

    if top3:
        top3_names = "、".join(html_escape(t.get("name", "")) for t in top3)
        a1 = (
            f"現在の最新データでは、{html_escape(label)}の上位3チームは"
            f"<strong>{top3_names}</strong>です。各チームの所属都道府県の順位表ページから詳細を確認できます。"
        )
    else:
        a1 = f"{html_escape(label)}のデータはまだ準備中です。"

    a2 = (
        f"{html_escape(label)}には現在<strong>{team_count}チーム</strong>が所属しています。"
        f"全国47都道府県から実力上位のチームが集結し、年間を通じて順位を競います。"
    )

    if category == "premier":
        a3 = (
            "プレミアリーグは高円宮杯 JFA U-18 サッカーリーグの<strong>最上位</strong>です。"
            "全国を EAST と WEST の2地域に分けて、それぞれ12チームで構成されています。"
            "上位2チームには昇降格プレーオフへの進出権が、下位2チームにはプリンスリーグ降格の可能性があります。"
            "また、シーズン終盤の「プレミアリーグファイナル」で東西1位同士が対戦し、年間王者を決定します。"
        )
    else:
        a3 = (
            "プリンスリーグはプレミアリーグの一段下にあたる<strong>2部相当</strong>のリーグで、"
            "全国9地域（北海道・東北・関東・北信越・東海・関西・中国・四国・九州）に分かれています。"
            "上位チームはプリンスリーグへの昇格、下位チームは都道府県リーグへの降格があり、"
            "毎年熱い昇降格争いが繰り広げられます。"
        )

    a4 = (
        "本サイトの順位データは <strong>毎日 9:00 (JST)</strong> 頃に自動更新されています。"
        "JFA（日本サッカー協会）公式サイト・各地域サッカー協会の最新データを反映しています。"
    )

    a5 = (
        "本ページではリーグ全体の順位表を一覧できますが、各チーム名の右側にある"
        "<strong>都道府県名のリンク</strong>をクリックすると、そのチームが所属する都道府県の"
        "全チーム順位表（プレミア・プリンス・都道府県リーグ1部）も確認できます。"
        "多角的に強豪校のデータをご覧いただけます。"
    )

    return [
        (f"{html_escape(label)}で現在強いチームはどこですか？", a1),
        (f"{html_escape(label)}には何チームが所属していますか？", a2),
        ("プレミアリーグとプリンスリーグの違いは何ですか？", a3),
        ("順位データはいつ更新されますか？", a4),
        ("本サイトでチームの所属都道府県の他チームも見られますか？", a5),
    ]


def render_faq_schema(faqs):
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": strip_tags(q),
                "acceptedAnswer": {"@type": "Answer", "text": strip_tags(a)},
            }
            for q, a in faqs
        ],
    }


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s)


def render_faq_html(faqs):
    items = []
    for q, a in faqs:
        items.append(
            f'        <details class="lp-faq-item">\n'
            f'          <summary class="lp-faq-q">{q}</summary>\n'
            f'          <div class="lp-faq-a">{a}</div>\n'
            f'        </details>'
        )
    return "\n".join(items)


def render_past_champions_html(slug):
    """過去5年の優勝校履歴セクションのHTMLを生成"""
    league_data = LEAGUE_HISTORY.get(slug, {})
    champions = league_data.get("champions", [])
    if not champions:
        return ""

    # 年降順でソートし、最新5年分
    sorted_champs = sorted(
        champions, key=lambda x: -int(x.get("year", 0))
    )[:5]

    rows_html = ""
    for i, c in enumerate(sorted_champs):
        year = c.get("year", "")
        team = c.get("team", "")
        pref = c.get("pref", "")
        # 最新年度のみ🏆、それ以外は🥇
        medal = "🏆" if i == 0 else "🥇"
        if pref:
            team_html = (
                f'<a href="/prefectures/{pref}/" '
                f'style="color:var(--accent-color, #2563eb); '
                f'text-decoration:none; font-weight:600;">'
                f'{html_escape(team)}</a>'
            )
        else:
            team_html = html_escape(team)
        rows_html += f"""
        <li style="display:flex; align-items:center; padding:12px 0; border-bottom:1px solid var(--border-color, #e5e7eb);">
          <span style="display:inline-block; width:70px; font-weight:600; color:var(--text-secondary, #6b7280);">{year}年</span>
          <span style="margin-right:8px; font-size:1.2em;">{medal}</span>
          <span style="flex:1;">{team_html}</span>
        </li>"""

    return f"""
      <ul style="list-style:none; padding:0; margin:0;">
        {rows_html}
      </ul>
      <p style="font-size:0.85em; color:var(--text-secondary, #6b7280); margin:16px 0 0 0;">
        ※ 高円宮杯JFA U-18 サッカープレミアリーグ／プリンスリーグ 公式記録に基づく
      </p>
    </section>
    """


def render_pref_distribution_html(teams, current_slug):
    """所属都道府県の分布を地方別グリッドで表示"""
    pref_counts = {}
    for t in teams:
        pid = t.get("_pref_id", "")
        pname = t.get("_pref_name", pid)
        if pid not in pref_counts:
            pref_counts[pid] = {"name": pname, "count": 0}
        pref_counts[pid]["count"] += 1

    if not pref_counts:
        return '          <p style="color:#888;">所属チームの都道府県情報がありません</p>'

    items = []
    for pid in sorted(pref_counts.keys()):
        p = pref_counts[pid]
        items.append(
            f'          <a href="/prefectures/{pid}/" class="lp-league-pref">'
            f'{html_escape(p["name"])}<small>({p["count"]}校)</small></a>'
        )
    return "\n".join(items)


def render_related_leagues_html(current_slug, current_category):
    """関連リーグへのリンク (現在のリーグ以外を全部)"""
    items = []
    for league_name, (slug, label, category, _desc) in LEAGUE_DEFS.items():
        if slug == current_slug:
            continue
        cls = f"league-link league-link--{category}"
        items.append(
            f'          <a href="/leagues/{slug}/" class="{cls}">'
            f'{html_escape(label)}</a>'
        )
    return "\n".join(items)


# ============================================================
# HTML テンプレート（リーグ個別ページ）
# ============================================================
LEAGUE_PAGE_TEMPLATE = """<!DOCTYPE html>
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
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:creator" content="@DrKazuSoccer">
  <meta name="twitter:title" content="__TITLE__">
  <meta name="twitter:description" content="__DESCRIPTION__">
  <meta name="twitter:image" content="https://u18-soccer.com/og-image.png">

  <!-- ファビコン -->
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <meta name="theme-color" content="#1e40af">

  <!-- 構造化データ -->
  <script type="application/ld+json">
__SCHEMA_BREADCRUMB__
  </script>
  <script type="application/ld+json">
__SCHEMA_LEAGUE__
  </script>
  <script type="application/ld+json">
__SCHEMA_ITEMLIST__
  </script>
  <script type="application/ld+json">
__SCHEMA_FAQ__
  </script>

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/css/style.css">

  <!-- ダークモード初期化 -->
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
        <a href="/leagues/">リーグ一覧</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">__LEAGUE_LABEL__</span>
      </nav>

      <h1 class="lp-title">__LEAGUE_LABEL__ 順位表 | U-18 高校サッカー</h1>

      <p class="lp-intro">
        __DESCRIPTION_LONG__
      </p>

      <div class="stats-summary">
        <div class="stat-item">
          <div class="stat-label">所属チーム数</div>
          <div class="stat-value">__TEAM_COUNT__</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">カテゴリ</div>
          <div class="stat-value">__CATEGORY_LABEL__</div>
        </div>
      </div>

      <div class="lp-cta">
        <a href="/" class="lp-cta__btn">
          <i class="fas fa-bolt"></i> 全国版・インタラクティブビューに戻る
        </a>
      </div>

      <h2 class="section-title-lp">__LEAGUE_LABEL__ 順位表</h2>
      <div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">
        <table class="data-table">
          <thead>
            <tr>
              <th>順位</th>
              <th>チーム名</th>
              <th>所属県</th>
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

      <section class="lp-section">
        <h2><i class="fas fa-map-marker-alt"></i> 所属チームの都道府県分布</h2>
        <p class="lp-section-desc">
          __LEAGUE_LABEL__に参加しているチームの所属都道府県一覧です。
          各都道府県をクリックすると、その県の全チーム（プレミア・プリンス・県リーグ1部）の順位表ページに移動できます。
        </p>
        <div class="lp-league-prefs">
__PREF_DISTRIBUTION__
        </div>
      </section>
      
      <section class="lp-section lp-past-champions">
        <h2><i class="fas fa-trophy"></i> 過去5年の優勝校</h2>
__PAST_CHAMPIONS__
      </section>
      
      <section class="lp-section lp-faq">
        <h2><i class="fas fa-question-circle"></i> よくある質問</h2>
__FAQ_HTML__
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-trophy"></i> 関連リーグ</h2>
        <p class="lp-section-desc">
          高円宮杯 U-18 サッカーリーグの他のカテゴリ・地域のリーグ順位表もご覧いただけます。
        </p>
        <div class="lp-related-leagues">
__RELATED_LEAGUES__
        </div>
      </section>

      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/">全国の高校サッカー順位表トップ</a></li>
          <li><a href="/leagues/">リーグ一覧トップ</a></li>
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
        データ出典：JFA（日本サッカー協会）、各都道府県・地域サッカー協会、各高校・クラブ公式情報。最新情報は各公式サイトをご確認ください。
      </p>
    </div>
  </footer>
  <script src="/js/main.js" defer></script>
</body>
</html>
"""


def generate_league_page(league_name, slug, label, category, description, teams):
    """個別リーグページの HTML を生成"""
    canonical = f"{DOMAIN}/leagues/{slug}/"
    sorted_teams = sorted(teams, key=lambda t: t.get("leagueRank") or t.get("rank") or 99)
    team_count = len(sorted_teams)
    category_label = "全国最上位（プレミア）" if category == "premier" else "地域上位（プリンス）"

    if sorted_teams:
        team_rows = "\n".join(render_team_row_for_league(t, i + 1) for i, t in enumerate(sorted_teams))
    else:
        team_rows = (
            '        <tr><td colspan="9" style="text-align:center;padding:30px;color:#888;">'
            'このリーグのデータはまだ登録されていません</td></tr>'
        )

    # === SEO最適化：GSC実検索キーワードに対応 ===
    year_label = date.today().year

    # 上位2チームをタイトル用の強豪校として抽出（「高校」「高等学校」は省略）
    top_team_names = []
    for t in sorted_teams[:2]:
        nm = (t.get("name") or "").strip()
        if not nm:
            continue
        nm_short = nm.replace("高等学校", "").replace("高校", "")
        top_team_names.append(nm_short)
    top_teams_str = "・".join(top_team_names)

    # カテゴリ別のSEOプレフィックス
    if category == "premier":
        seo_prefix = "高円宮杯U-18"
        league_role = "U-18高校サッカー全国最高峰リーグ"
    else:
        seo_prefix = "高円宮杯U-18"
        league_role = "プレミアリーグ参入を懸けた地域最上位リーグ"

    # title 生成（GSC検索クエリ「{リーグ名}順位」に空白なし完全一致）
    if top_teams_str and team_count > 0:
        title = (
            f"【{year_label}最新】{seo_prefix}{label} 順位表"
            f" | {top_teams_str}など全{team_count}チーム"
        )
    else:
        title = f"【{year_label}最新】{seo_prefix}{label} 順位表 | U-18高校サッカー"

    # description_short（meta description）
    notable_phrase = f"{top_teams_str}など" if top_teams_str else ""
    description_short = (
        f"{label}の最新順位・試合結果を毎日自動更新。"
        f"{notable_phrase}全{team_count}チームのU-18高校サッカー勝点・得失点差・日程を一覧表示。"
        f"{league_role}の最新動向を網羅。"
    )

    description_long = description + f"現在 <strong>{team_count}チーム</strong> が所属し、年間を通じて熾烈な順位争いが繰り広げられます。"

    keywords = (
        f"{label},{label}順位,{label}順位表,{label}{year_label},"
        f"高円宮杯,高円宮杯JFA,U-18,U18,高校サッカー,クラブユース,"
        f"順位,成績,試合結果,日程,得点ランキング,"
        f"プレミアリーグ,プリンスリーグ,プレミアリーグ高校,プリンスリーグ高校"
    )

    breadcrumb = json.dumps(render_breadcrumb_schema(label, slug), ensure_ascii=False, indent=2)
    league_schema = json.dumps(render_league_schema(label, slug, description, sorted_teams), ensure_ascii=False, indent=2)
    itemlist = render_itemlist_schema(sorted_teams, label, slug)
    if itemlist:
        itemlist_json = json.dumps(itemlist, ensure_ascii=False, indent=2)
    else:
        itemlist_json = json.dumps({
            "@context": "https://schema.org", "@type": "ItemList",
            "name": f"{label} 順位表 (準備中)", "itemListElement": []
        }, ensure_ascii=False, indent=2)

    faqs = build_faqs(label, sorted_teams, slug, category)
    faq_schema = json.dumps(render_faq_schema(faqs), ensure_ascii=False, indent=2)
    faq_html = render_faq_html(faqs)

    pref_distribution = render_pref_distribution_html(sorted_teams, slug)
    related_leagues = render_related_leagues_html(slug, category)
    past_champions_html = render_past_champions_html(slug)  # ← この行を追加
    return (
        LEAGUE_PAGE_TEMPLATE
        .replace("__GA_ID__", GA_ID)
        .replace("__ADSENSE__", ADSENSE_CLIENT)
        .replace("__TITLE__", html_escape(title))
        .replace("__DESCRIPTION__", html_escape(description_short))
        .replace("__KEYWORDS__", html_escape(keywords))
        .replace("__CANONICAL__", canonical)
        .replace("__SCHEMA_BREADCRUMB__", breadcrumb)
        .replace("__SCHEMA_LEAGUE__", league_schema)
        .replace("__SCHEMA_ITEMLIST__", itemlist_json)
        .replace("__SCHEMA_FAQ__", faq_schema)
        .replace("__LEAGUE_LABEL__", html_escape(label))
        .replace("__DESCRIPTION_LONG__", description_long)
        .replace("__TEAM_COUNT__", str(team_count))
        .replace("__CATEGORY_LABEL__", html_escape(category_label))
        .replace("__TEAM_ROWS__", team_rows)
        .replace("__PREF_DISTRIBUTION__", pref_distribution)
        .replace("__FAQ_HTML__", faq_html)
        .replace("__RELATED_LEAGUES__", related_leagues)
        .replace("__PAST_CHAMPIONS__", past_champions_html)  # ← この行を追加
    )


# ============================================================
# リーグ一覧ハブページ
# ============================================================
LEAGUE_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <script async src="https://www.googletagmanager.com/gtag/js?id=__GA_ID__"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', '__GA_ID__');
  </script>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=__ADSENSE__"
          crossorigin="anonymous"></script>
  <meta name="google-adsense-account" content="__ADSENSE__">

  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">

  <title>リーグ一覧 | 高円宮杯 JFA U-18 サッカープレミア・プリンスリーグ全国順位表</title>
  <meta name="description" content="高円宮杯 JFA U-18 サッカーリーグ全カテゴリの順位表を一括確認。プレミアリーグEAST/WESTとプリンスリーグ9地域の所属チーム・最新順位を毎日自動更新。">
  <meta name="keywords" content="高円宮杯,U-18,プレミアリーグ,プリンスリーグ,高校サッカー,順位,リーグ一覧">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="https://u18-soccer.com/leagues/">

  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="リーグ一覧 | U-18 高校サッカー全リーグ順位表">
  <meta property="og:description" content="プレミア・プリンスリーグ全カテゴリの順位を一覧表示">
  <meta property="og:url" content="https://u18-soccer.com/leagues/">
  <meta property="og:image" content="https://u18-soccer.com/og-image.png">
  <meta property="og:locale" content="ja_JP">

  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <meta name="theme-color" content="#1e40af">

  <script type="application/ld+json">
__SCHEMA_BREADCRUMB__
  </script>

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/css/style.css">

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
        </nav>
      </div>
    </div>
  </header>

  <main class="main-content">
    <div class="container">
      <nav class="breadcrumb" aria-label="パンくずリスト">
        <a href="/">ホーム</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">リーグ一覧</span>
      </nav>

      <h1 class="lp-title">高円宮杯 JFA U-18 サッカーリーグ 一覧</h1>

      <p class="lp-intro">
        高円宮杯 JFA U-18 サッカーリーグは、日本サッカー協会主催の U-18（高校生年代）向けリーグ戦です。
        全国規模の<strong>プレミアリーグ</strong>、9地域の<strong>プリンスリーグ</strong>、各都道府県の<strong>都道府県リーグ</strong>という
        ピラミッド構造になっています。本ページではプレミア・プリンス各リーグの最新順位表ページへリンクしています。
      </p>

      <section class="lp-section">
        <h2><i class="fas fa-star"></i> プレミアリーグ（全国最上位）</h2>
        <p class="lp-section-desc">
          全国を東日本・西日本の2地域に分け、各12チームで構成される最上位リーグです。
        </p>
        <div class="lp-league-cards">
__PREMIER_CARDS__
        </div>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-medal"></i> プリンスリーグ（9地域）</h2>
        <p class="lp-section-desc">
          全国9地域それぞれで開催される2部相当のリーグ。プレミアリーグへの昇格を目指して激戦が繰り広げられます。
        </p>
        <div class="lp-league-cards">
__PRINCE_CARDS__
        </div>
      </section>

      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/">全国の高校サッカー順位表トップ</a></li>
          <li><a href="/#search">チーム名で検索</a></li>
          <li><a href="/about.html">運営者情報</a></li>
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
    </div>
  </footer>
  <script src="/js/main.js" defer></script>
</body>
</html>
"""


def render_league_card(slug, label, team_count, description):
    """リーグカード HTML"""
    return (
        f'          <a href="/leagues/{slug}/" class="lp-league-card">\n'
        f'            <div class="lp-league-card__title">{html_escape(label)}</div>\n'
        f'            <div class="lp-league-card__count">所属 {team_count}チーム</div>\n'
        f'            <div class="lp-league-card__desc">{html_escape(description[:80])}...</div>\n'
        f'          </a>'
    )


def generate_index_page(teams_by_league):
    """リーグ一覧ハブページ"""
    premier_cards = []
    prince_cards = []
    for league_name, (slug, label, category, description) in LEAGUE_DEFS.items():
        teams = teams_by_league.get(league_name, [])
        card = render_league_card(slug, label, len(teams), description)
        if category == "premier":
            premier_cards.append(card)
        else:
            prince_cards.append(card)

    breadcrumb = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "リーグ一覧",
             "item": f"{DOMAIN}/leagues/"},
        ],
    }, ensure_ascii=False, indent=2)

    return (
        LEAGUE_INDEX_TEMPLATE
        .replace("__GA_ID__", GA_ID)
        .replace("__ADSENSE__", ADSENSE_CLIENT)
        .replace("__SCHEMA_BREADCRUMB__", breadcrumb)
        .replace("__PREMIER_CARDS__", "\n".join(premier_cards))
        .replace("__PRINCE_CARDS__", "\n".join(prince_cards))
    )


# ============================================================
# Sitemap 完全版（トップ + 47都道府県 + 静的 + リーグ）
# ============================================================
def update_sitemap_complete(teams_data, generated_league_slugs):
    today = date.today().isoformat()
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
             '  <url>',
             f'    <loc>{DOMAIN}/</loc>',
             f'    <lastmod>{today}</lastmod>',
             '    <changefreq>daily</changefreq>',
             '    <priority>1.0</priority>',
             '  </url>']

    # 47都道府県
    for pref_id, pref_data in teams_data.items():
        if not isinstance(pref_data, dict) or "teams" not in pref_data:
            continue
        parts.extend([
            '  <url>',
            f'    <loc>{DOMAIN}/prefectures/{pref_id}/</loc>',
            f'    <lastmod>{today}</lastmod>',
            '    <changefreq>daily</changefreq>',
            '    <priority>0.8</priority>',
            '  </url>',
        ])

    # 静的ページ
    for static_url in ("/about.html", "/privacy.html", "/contact.html"):
        parts.extend([
            '  <url>',
            f'    <loc>{DOMAIN}{static_url}</loc>',
            f'    <lastmod>{today}</lastmod>',
            '    <changefreq>monthly</changefreq>',
            '    <priority>0.4</priority>',
            '  </url>',
        ])

    # リーグ一覧トップ
    parts.extend([
        '  <url>',
        f'    <loc>{DOMAIN}/leagues/</loc>',
        f'    <lastmod>{today}</lastmod>',
        '    <changefreq>daily</changefreq>',
        '    <priority>0.7</priority>',
        '  </url>',
    ])

    # 各リーグページ
    for slug in generated_league_slugs:
        parts.extend([
            '  <url>',
            f'    <loc>{DOMAIN}/leagues/{slug}/</loc>',
            f'    <lastmod>{today}</lastmod>',
            '    <changefreq>daily</changefreq>',
            '    <priority>0.7</priority>',
            '  </url>',
        ])

    parts.append('</urlset>')
    SITEMAP_FILE.write_text("\n".join(parts) + "\n", encoding="utf-8")
    pref_count = sum(1 for v in teams_data.values() if isinstance(v, dict) and "teams" in v)
    total = 1 + pref_count + 3 + 1 + len(generated_league_slugs)
    print(f"sitemap.xml 完全版で更新: {total} URL "
          f"(トップ + {pref_count}都道府県 + 3静的 + リーグindex + {len(generated_league_slugs)}リーグ)")


# ============================================================
# Main
# ============================================================
def main():
    if not TEAMS_FILE.exists():
        print(f"[ERROR] {TEAMS_FILE} が見つかりません。先にスクレイパーを実行してください。")
        return 1

    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    teams_by_league = collect_teams_by_league(teams_data)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    # 各リーグページ生成
    generated_slugs = []
    for league_name, (slug, label, category, description) in LEAGUE_DEFS.items():
        teams = teams_by_league.get(league_name, [])
        # 0チームのリーグはスキップ（データが無いリーグ）
        if not teams:
            print(f"[SKIP] {league_name}: チーム0 (データなし)")
            continue

        league_dir = OUTPUT_ROOT / slug
        league_dir.mkdir(parents=True, exist_ok=True)
        html = generate_league_page(league_name, slug, label, category, description, teams)
        (league_dir / "index.html").write_text(html, encoding="utf-8")
        print(f"[OK] {league_name} -> /leagues/{slug}/ ({len(teams)} チーム)")
        generated_slugs.append(slug)

    # リーグ一覧ハブ
    index_html = generate_index_page(teams_by_league)
    (OUTPUT_ROOT / "index.html").write_text(index_html, encoding="utf-8")
    print(f"[OK] リーグ一覧 -> /leagues/")

    # sitemap 完全版で更新
    update_sitemap_complete(teams_data, generated_slugs)

    print(f"完了: {len(generated_slugs)} リーグページ + 1 一覧ページを生成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
