#!/usr/bin/env python3
"""
チーム個別プロフィールページ生成スクリプト v2
==============================================
v2 の変更点:
  - 既存サイトの css/style.css を共有してヘッダーを完全統一
  - Font Awesome + Noto Sans JP を使用
  - ダークモード切替ボタン（.theme-toggle）追加
  - localStorage ベースの dark/light/auto 切り替え
  - 既存 CSS 変数（--bg-white, --primary-color 等）を活用

data/team-profiles/*.md を読み込んで teams/{id}/index.html を生成。
sitemap.xml にも /teams/{id}/ の URL を追加する。

依存:
  - pyyaml
  - markdown
"""

import json
import re
from datetime import datetime, timezone, timedelta
from html import escape as html_escape
from pathlib import Path

import yaml
import markdown


# =========================================================================
# 設定
# =========================================================================

BASE_DIR = Path(__file__).parent.parent

def _fix_prince_league_links(html: str) -> str:
    """本文中の /leagues/prince-◯/ リンクを自動補正する。
    関東・関西・九州・北信越は 1部/2部 に分かれており bare(無印) ページが無いため、
    「無印が存在せず -1 が存在する」場合のみ /leagues/prince-◯-1/ に書き換える。
    （例: /leagues/prince-kanto/ → /leagues/prince-kanto-1/）
    これにより、どのチーム詳細mdに無印リンクが書かれても二度とリンク切れにならない。"""
    def repl(m):
        slug = m.group(1)  # 例: prince-kanto
        bare = BASE_DIR / "leagues" / slug / "index.html"
        one = BASE_DIR / "leagues" / f"{slug}-1" / "index.html"
        if (not bare.exists()) and one.exists():
            return f'href="/leagues/{slug}-1/"'
        return m.group(0)
    return re.sub(r'href="/leagues/(prince-[a-z]+)/"', repl, html)



PROFILES_DIR = BASE_DIR / "data" / "team-profiles"
OUTPUT_ROOT = BASE_DIR / "teams"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"

GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"
DOMAIN = "https://u18-soccer.com"

JST = timezone(timedelta(hours=9))


# =========================================================================
# HTML テンプレート（既存サイトの style.css を活用）
# =========================================================================

TEAM_PAGE_TEMPLATE = """<!DOCTYPE html>
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
  <meta property="og:image" content="__DOMAIN__/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:locale" content="ja_JP">

  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:creator" content="@DrKazuSoccer">
  <meta name="twitter:title" content="__TITLE__">
  <meta name="twitter:description" content="__DESCRIPTION__">
  <meta name="twitter:image" content="__DOMAIN__/og-image.png">

  <!-- ファビコン -->
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <meta name="theme-color" content="#1e40af">

  <!-- 構造化データ: SportsTeam -->
  <script type="application/ld+json">
__SCHEMA_TEAM__
  </script>

  <!-- 構造化データ: BreadcrumbList -->
  <script type="application/ld+json">
__SCHEMA_BREADCRUMB__
  </script>

  <!-- ===== フォント / アイコン / スタイル ===== -->
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
        if (t === 'dark' || t === 'light') {
          document.documentElement.setAttribute('data-theme', t);
        }
      } catch (e) {}
    })();
  </script>

  <!-- チームページ固有スタイル（既存 CSS 変数を活用） -->
  <style>
    /* ===== チームページ ヒーロー ===== */
    .team-hero {
      background: linear-gradient(135deg, var(--primary-color), #004999);
      color: white;
      padding: 28px 24px;
      border-radius: 12px;
      margin: 16px 0 24px;
      box-shadow: var(--shadow);
    }
    .team-hero h1 {
      font-size: 1.6rem;
      color: white;
      margin: 0 0 10px;
      line-height: 1.4;
      font-weight: 700;
    }
    .team-hero p.team-lead {
      margin: 0;
      opacity: 0.95;
      line-height: 1.7;
      font-size: 0.95rem;
    }

    /* ===== チーム統計カード ===== */
    .team-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 16px 0 28px;
    }
    .team-stat-card {
      background: var(--bg-white);
      border: 1px solid var(--border-color);
      border-radius: 10px;
      padding: 16px 14px;
      text-align: center;
      box-shadow: var(--shadow);
    }
    .team-stat-label {
      color: var(--text-light);
      font-size: 0.82rem;
      margin-bottom: 6px;
    }
    .team-stat-value {
      color: var(--primary-color);
      font-size: 1.05rem;
      font-weight: 700;
      word-break: break-word;
    }

    /* ===== チーム本文 ===== */
    .team-content {
      background: var(--bg-white);
      border-radius: 12px;
      padding: 28px;
      box-shadow: var(--shadow);
      font-size: 0.95rem;
      line-height: 1.85;
      color: var(--text-dark);
    }
    .team-content h2 {
      font-size: 1.3rem;
      color: var(--primary-color);
      border-bottom: 3px solid var(--primary-color);
      padding-bottom: 8px;
      margin: 32px 0 14px;
    }
    .team-content h2:first-child {
      margin-top: 0;
    }
    .team-content h3 {
      font-size: 1.1rem;
      color: var(--text-dark);
      border-left: 4px solid var(--primary-color);
      padding-left: 10px;
      margin: 24px 0 10px;
    }
    .team-content p {
      margin: 12px 0;
    }
    .team-content table {
      width: 100%;
      border-collapse: collapse;
      margin: 14px 0 20px;
      font-size: 0.88rem;
      overflow-x: auto;
      display: block;
    }
    .team-content table thead,
    .team-content table tbody,
    .team-content table tr {
      display: table;
      width: 100%;
      table-layout: fixed;
    }
    .team-content th, .team-content td {
      border: 1px solid var(--border-color);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }
    .team-content th {
      background: var(--primary-color);
      color: white;
      font-weight: 600;
    }
    .team-content strong {
      color: var(--primary-color);
      font-weight: 700;
    }
    .team-content blockquote {
      border-left: 4px solid var(--secondary-color);
      background: rgba(255, 215, 0, 0.08);
      padding: 12px 18px;
      margin: 16px 0;
      font-style: italic;
      border-radius: 0 8px 8px 0;
    }
    .team-content ul, .team-content ol {
      padding-left: 24px;
      margin: 10px 0;
    }
    .team-content li {
      margin: 5px 0;
    }
    .team-content a {
      color: var(--primary-color);
      text-decoration: underline;
    }
    .team-content a:hover {
      color: #004999;
    }

    /* ダークモード対応 (blockquote の背景色) */
    [data-theme="dark"] .team-content blockquote {
      background: rgba(251, 191, 36, 0.10);
    }
    @media (prefers-color-scheme: dark) {
      :root:not([data-theme="light"]) .team-content blockquote {
        background: rgba(251, 191, 36, 0.10);
      }
    }

    /* モバイル調整 */
    @media (max-width: 768px) {
      .team-hero {
        padding: 20px 16px;
        margin: 12px 0 18px;
      }
      .team-hero h1 {
        font-size: 1.3rem;
      }
      .team-hero p.team-lead {
        font-size: 0.9rem;
      }
      .team-stats {
        grid-template-columns: repeat(2, 1fr);
        gap: 8px;
      }
      .team-stat-card {
        padding: 12px 8px;
      }
      .team-stat-label {
        font-size: 0.75rem;
      }
      .team-stat-value {
        font-size: 0.92rem;
      }
      .team-content {
        padding: 18px 16px;
        font-size: 0.9rem;
      }
      .team-content h2 {
        font-size: 1.15rem;
      }
      .team-content h3 {
        font-size: 1rem;
      }
      .team-content table {
        font-size: 0.82rem;
      }
      .team-content th, .team-content td {
        padding: 6px 8px;
      }
    }
  </style>
</head>
<body>
  <!-- ===== ヘッダー (既存サイトと統一) ===== -->
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
          <a href="/" class="nav-link">
            <i class="fas fa-home"></i>
            ホーム
          </a>
          <a href="/leagues/" class="nav-link">
            <i class="fas fa-trophy"></i>
            リーグ
          </a>
          <a href="/blog/" class="nav-link">
            <i class="fas fa-newspaper"></i>
            ブログ
          </a>
          <button class="theme-toggle" id="themeToggleBtn"
                  aria-label="ダークモード切替"
                  title="ダークモード切替">
            <i class="fas fa-moon" id="themeToggleIcon"></i>
          </button>
        </nav>
      </div>
    </div>
  </header>

  <main class="container">
    <nav class="breadcrumb">
      <a href="/">ホーム</a>
      <span class="breadcrumb__sep">›</span>
      <a href="/prefectures/__PREFECTURE_ID__/">__PREFECTURE_NAME__</a>
      <span class="breadcrumb__sep">›</span>
      <span>__TEAM_NAME__</span>
    </nav>

    <section class="team-hero">
      <h1>__TEAM_NAME__ U-18 高校サッカー</h1>
__AI_SUMMARY__
      <p class="team-lead">__LEAD__</p>
    </section>

    <section class="team-stats">
      <div class="team-stat-card">
        <div class="team-stat-label">所属リーグ</div>
        <div class="team-stat-value">__LEAGUE__</div>
      </div>
      <div class="team-stat-card">
        <div class="team-stat-label">創部</div>
        <div class="team-stat-value">__FOUNDED__</div>
      </div>
      <div class="team-stat-card">
        <div class="team-stat-label">所在地</div>
        <div class="team-stat-value">__LOCATION__</div>
      </div>
      <div class="team-stat-card">
        <div class="team-stat-label">監督</div>
        <div class="team-stat-value">__HEAD_COACH__</div>
      </div>
    </section>

    <article class="team-content">
__BODY_HTML__
    </article>
  </main>

  <footer class="footer">
    <div class="container">
      <p>&copy; 2025-2026 高校サッカー順位確認システム</p>
      <nav class="footer-nav" style="margin-top:12px;">
        <a href="/about.html">運営者情報</a> ・
        <a href="/privacy.html">プライバシーポリシー</a> ・
        <a href="/contact.html">お問い合わせ</a>
      </nav>
      <p class="footer-note" style="margin-top:10px;"><i class="fas fa-database"></i> 順位データは毎日自動更新 ・ X: <a href="https://x.com/DrKazuSoccer" style="color:#93c5fd;">@DrKazuSoccer</a></p>
    </div>
  </footer>

  <!-- ダークモード切替ロジック -->
  <script>
    (function() {
      var btn = document.getElementById('themeToggleBtn');
      var icon = document.getElementById('themeToggleIcon');
      if (!btn || !icon) return;

      function getCurrentTheme() {
        var attr = document.documentElement.getAttribute('data-theme');
        if (attr === 'dark' || attr === 'light') return attr;
        // 属性なし: システム設定に従う
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
          return 'dark';
        }
        return 'light';
      }

      function updateIcon() {
        var t = getCurrentTheme();
        icon.className = (t === 'dark') ? 'fas fa-sun' : 'fas fa-moon';
      }

      btn.addEventListener('click', function() {
        var current = getCurrentTheme();
        var next = (current === 'dark') ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        try { localStorage.setItem('theme', next); } catch (e) {}
        updateIcon();
      });

      // システム設定変更を検知してアイコン更新（手動設定がない場合のみ）
      if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
          if (!document.documentElement.getAttribute('data-theme')) {
            updateIcon();
          }
        });
      }

      updateIcon();
    })();
  </script>
</body>
</html>
"""


# =========================================================================
# ロジック
# =========================================================================

def parse_profile(md_file: Path) -> dict | None:
    """frontmatter + markdown body を抽出"""
    content = md_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        print(f"  [SKIP] {md_file.name}: frontmatter なし")
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        print(f"  [SKIP] {md_file.name}: frontmatter の形式エラー")
        return None

    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        print(f"  [SKIP] {md_file.name}: YAML パースエラー: {e}")
        return None

    body_md = parts[2].strip()
    return {"meta": meta or {}, "body_md": body_md}


def build_lead(meta: dict) -> str:
    """frontmatter から hero セクションの lead 文を組み立て"""
    name = meta.get("short_name") or meta.get("name", "")
    league = meta.get("league", "")
    pref = meta.get("prefecture_name", "")
    founded = meta.get("founded", "")
    parts_text = []
    if pref:
        parts_text.append(pref)
    parts_text.append(f"{name}サッカー部は")
    if league:
        parts_text.append(f"{league} 所属")
    if founded:
        parts_text.append(f"（{founded}年創部）")
    return "".join(parts_text) + "。最新の順位・歴代タイトル・OB選手・育成哲学などを徹底まとめ。"


def build_schema_team(meta: dict) -> str:
    """SportsTeam JSON-LD を組み立て"""
    schema = {
        "@context": "https://schema.org",
        "@type": "SportsTeam",
        "name": meta.get("name", ""),
        "sport": "Football",
        "url": f"{DOMAIN}/teams/{meta.get('id')}/",
        "logo": f"{DOMAIN}/og-image.png",
    }
    if meta.get("league"):
        schema["memberOf"] = {
            "@type": "SportsOrganization",
            "name": meta["league"],
        }
    if meta.get("founded"):
        schema["foundingDate"] = str(meta["founded"])
    if meta.get("location"):
        schema["location"] = {
            "@type": "Place",
            "address": meta["location"],
        }
    if meta.get("description"):
        schema["description"] = meta["description"]
    return json.dumps(schema, ensure_ascii=False, indent=2)


def build_schema_breadcrumb(meta: dict) -> str:
    """BreadcrumbList JSON-LD を組み立て"""
    pref_id = meta.get("prefecture", "")
    pref_name = meta.get("prefecture_name", "")
    team_name = meta.get("name", "")
    items = [
        {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
    ]
    if pref_id and pref_name:
        items.append({
            "@type": "ListItem",
            "position": 2,
            "name": pref_name,
            "item": f"{DOMAIN}/prefectures/{pref_id}/",
        })
        items.append({
            "@type": "ListItem",
            "position": 3,
            "name": team_name,
            "item": f"{DOMAIN}/teams/{meta.get('id')}/",
        })
    else:
        items.append({
            "@type": "ListItem",
            "position": 2,
            "name": team_name,
            "item": f"{DOMAIN}/teams/{meta.get('id')}/",
        })
    schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }
    return json.dumps(schema, ensure_ascii=False, indent=2)


def build_keywords(meta: dict) -> str:
    """meta keywords 文字列を組み立て"""
    name = meta.get("name", "")
    short = meta.get("short_name", "")
    league = meta.get("league", "")
    pref = meta.get("prefecture_name", "")
    parts = [
        name, short, "高校サッカー", "U-18", "U18",
        "高円宮杯", "プレミアリーグ", "プリンスリーグ",
        league, pref, "順位", "成績", "OB", "プロ選手",
    ]
    seen = set()
    out = []
    for p in parts:
        p = (p or "").strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return ",".join(out)

def build_team_ai_summary(meta: dict) -> str:
    """チームページH1直下のAI引用向け一文要約。frontmatterから自動生成。"""
    name = meta.get("name", "")
    if not name:
        return ""

    place = meta.get("location") or meta.get("prefecture_name") or ""
    league = meta.get("league", "")
    founded = meta.get("founded", "")
    coach = str(meta.get("head_coach", "") or "").split("（")[0].strip()

    parts = [f"「{html_escape(name)}」サッカー部は"]
    if place:
        parts.append(f"{html_escape(place)}を拠点とする")
    if league:
        parts.append(f"高円宮杯 U-18 {html_escape(league)}所属の高校サッカー部")
    else:
        parts.append("U-18 年代の高校サッカー部")
    body = "".join(parts) + "。"

    extra = []
    if founded:
        extra.append(f"{html_escape(str(founded))}年創部")
    if coach and coach not in ("", "—"):
        extra.append(f"監督は{html_escape(coach)}")
    if extra:
        body += "、".join(extra) + "。"
    body += "最新の順位・歴代タイトル・OB選手情報をまとめています。"

    style = (
        "margin:0 0 14px;padding:12px 16px;background:rgba(255,255,255,0.95);"
        "color:#16264a;border-left:4px solid #1e40af;border-radius:0 8px 8px 0;"
        "font-size:0.95rem;line-height:1.8;"
    )
    return f'      <p class="lp-lead-summary" style="{style}">{body}</p>\n'

def render_team_page(profile: dict) -> str:
    """1チームのプロフィールから HTML を生成"""
    meta = profile["meta"]
    body_md = profile["body_md"]

    md = markdown.Markdown(extensions=["tables", "fenced_code", "nl2br", "sane_lists"])
    body_html = md.convert(body_md)
    body_html = _fix_prince_league_links(body_html)

    title = f"{meta.get('name', '')} | 高校サッカー部 順位・OB・育成"
    description = meta.get("description") or build_lead(meta)
    canonical = f"{DOMAIN}/teams/{meta.get('id')}/"
    keywords = build_keywords(meta)
    schema_team = build_schema_team(meta)
    schema_bc = build_schema_breadcrumb(meta)
    lead = build_lead(meta)

    return (
        TEAM_PAGE_TEMPLATE
        .replace("__GA_ID__", GA_ID)
        .replace("__ADSENSE__", ADSENSE_CLIENT)
        .replace("__DOMAIN__", DOMAIN)
        .replace("__TITLE__", html_escape(title))
        .replace("__DESCRIPTION__", html_escape(description))
        .replace("__KEYWORDS__", html_escape(keywords))
        .replace("__CANONICAL__", canonical)
        .replace("__SCHEMA_TEAM__", schema_team)
        .replace("__SCHEMA_BREADCRUMB__", schema_bc)
        .replace("__PREFECTURE_ID__", html_escape(meta.get("prefecture", "")))
        .replace("__PREFECTURE_NAME__", html_escape(meta.get("prefecture_name", "")))
        .replace("__TEAM_NAME__", html_escape(meta.get("name", "")))
        .replace("__AI_SUMMARY__", build_team_ai_summary(meta))
        .replace("__LEAD__", html_escape(lead))
        .replace("__LEAGUE__", html_escape(meta.get("league", "—")))
        .replace("__FOUNDED__", html_escape(f"{meta.get('founded', '—')}年" if meta.get("founded") else "—"))
        .replace("__LOCATION__", html_escape(meta.get("location", "—")))
        .replace("__HEAD_COACH__", html_escape(str(meta.get("head_coach", "—")).split("（")[0]))
        .replace("__BODY_HTML__", body_html)
    )


def update_sitemap(profiles: list[dict]) -> None:
    """sitemap.xml に /teams/* の URL を追加（既存の teams 系 URL は置き換え）"""
    if not SITEMAP_FILE.exists():
        print(f"[WARN] {SITEMAP_FILE} が見つかりません。sitemap 更新をスキップします")
        return

    content = SITEMAP_FILE.read_text(encoding="utf-8")

    pattern = re.compile(
        r'\s*<url>\s*<loc>[^<]*?/teams/[^<]*?</loc>.*?</url>',
        re.DOTALL
    )
    content_cleaned = pattern.sub('', content)

    today = datetime.now(JST).strftime("%Y-%m-%d")
    new_entries = []
    for profile in profiles:
        team_id = profile["meta"].get("id")
        if not team_id:
            continue
        new_entries.append(
            f"  <url>\n"
            f"    <loc>{DOMAIN}/teams/{team_id}/</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>weekly</changefreq>\n"
            f"    <priority>0.7</priority>\n"
            f"  </url>"
        )

    if not new_entries:
        SITEMAP_FILE.write_text(content_cleaned, encoding="utf-8")
        return

    insertion = "\n" + "\n".join(new_entries) + "\n"
    content_new = content_cleaned.replace("</urlset>", insertion + "</urlset>")

    SITEMAP_FILE.write_text(content_new, encoding="utf-8")
    print(f"  → sitemap.xml にチームページ {len(new_entries)} 件を追加")


def main() -> int:
    if not PROFILES_DIR.exists():
        print(f"[ERROR] {PROFILES_DIR} が見つかりません。スキップします。")
        return 0

    md_files = sorted(PROFILES_DIR.glob("*.md"))
    print(f"[Teams] team-profiles ディレクトリ: {len(md_files)} ファイル")

    if not md_files:
        print("[Teams] .md ファイルがありません。終了。")
        return 0

    profiles = []
    for md_file in md_files:
        profile = parse_profile(md_file)
        if profile is None:
            continue
        if not profile["meta"].get("id"):
            print(f"  [SKIP] {md_file.name}: id が未設定")
            continue
        profiles.append(profile)

    print(f"[Teams] 有効プロフィール: {len(profiles)} 件")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    for profile in profiles:
        team_id = profile["meta"]["id"]
        html = render_team_page(profile)
        out_dir = OUTPUT_ROOT / team_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(html, encoding="utf-8")
        print(f"  [OK] {profile['meta'].get('name')} → /teams/{team_id}/")

    update_sitemap(profiles)

    print(f"[Teams] 完了")
    return 0


if __name__ == "__main__":
    exit(main())
