#!/usr/bin/env python3
"""
チーム個別プロフィールページ生成スクリプト
==============================================
data/team-profiles/*.md を読み込んで teams/{id}/index.html を生成。
sitemap.xml にも /teams/{id}/ の URL を追加する。

使い方:
    python scraper/generate_team_pages.py

依存:
    - pyyaml
    - markdown
    （workflow.yml で既に pip install 済み）
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
PROFILES_DIR = BASE_DIR / "data" / "team-profiles"
OUTPUT_ROOT = BASE_DIR / "teams"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"

GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"
DOMAIN = "https://u18-soccer.com"

# JST 現在時刻
JST = timezone(timedelta(hours=9))


# =========================================================================
# HTML テンプレート
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

  <style>
    :root {
      --bg-primary: #0f172a;
      --bg-secondary: #1e293b;
      --bg-card: rgba(30, 41, 59, 0.5);
      --accent-blue: #60a5fa;
      --accent-blue-dark: #1e40af;
      --accent-gold: #fbbf24;
      --text-primary: #e2e8f0;
      --text-secondary: #94a3b8;
      --border: rgba(96, 165, 250, 0.2);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Hiragino Sans', 'Hiragino Kaku Gothic ProN',
                   'Yu Gothic UI', 'Meiryo', sans-serif;
      background: var(--bg-primary);
      color: var(--text-primary);
      line-height: 1.7;
    }
    a { color: var(--accent-blue); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .site-header {
      background: linear-gradient(135deg, #1e40af 0%, #2563eb 100%);
      padding: 1rem 1.5rem;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .site-header-inner {
      max-width: 960px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .site-title {
      font-size: 1.1rem;
      font-weight: 700;
      color: white;
    }
    .site-header nav {
      display: flex;
      gap: 1rem;
    }
    .site-header nav a {
      color: rgba(255, 255, 255, 0.95);
    }
    main.container {
      max-width: 960px;
      margin: 0 auto;
      padding: 1rem 1.5rem 3rem;
    }
    .breadcrumb {
      font-size: 0.9rem;
      color: var(--text-secondary);
      margin: 1rem 0;
    }
    .breadcrumb a { color: var(--accent-blue); }
    .breadcrumb span { margin: 0 0.4rem; opacity: 0.6; }
    .team-hero {
      background: linear-gradient(135deg, var(--accent-blue-dark) 0%, #2563eb 100%);
      color: white;
      padding: 2rem 1.5rem;
      border-radius: 1rem;
      margin: 1.5rem 0;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    .team-hero h1 {
      font-size: 1.8rem;
      margin: 0 0 0.75rem 0;
      line-height: 1.3;
    }
    .team-hero .lead {
      opacity: 0.95;
      font-size: 0.95rem;
      margin: 0;
    }
    .team-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem;
      margin: 1.5rem 0;
    }
    .team-stat-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 0.75rem;
      padding: 1rem;
      text-align: center;
    }
    .team-stat-label {
      color: var(--text-secondary);
      font-size: 0.85rem;
    }
    .team-stat-value {
      color: var(--accent-blue);
      font-size: 1.1rem;
      font-weight: 600;
      margin-top: 0.3rem;
      word-break: break-word;
    }
    .team-content {
      font-size: 0.95rem;
    }
    .team-content h2 {
      color: var(--accent-blue);
      margin-top: 2.5rem;
      margin-bottom: 0.75rem;
      padding-bottom: 0.5rem;
      border-bottom: 2px solid var(--border);
      font-size: 1.35rem;
    }
    .team-content h3 {
      color: #93c5fd;
      margin-top: 1.5rem;
      margin-bottom: 0.5rem;
      font-size: 1.1rem;
    }
    .team-content p { margin: 0.75rem 0; }
    .team-content ul { padding-left: 1.5rem; }
    .team-content li { margin: 0.3rem 0; }
    .team-content strong { color: #fde68a; font-weight: 600; }
    .team-content table {
      width: 100%;
      border-collapse: collapse;
      margin: 1rem 0;
      background: rgba(15, 23, 42, 0.6);
      border-radius: 0.5rem;
      overflow: hidden;
      font-size: 0.9rem;
    }
    .team-content th, .team-content td {
      padding: 0.6rem 0.8rem;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }
    .team-content th {
      background: rgba(30, 64, 175, 0.3);
      color: #cbd5e1;
      font-weight: 600;
    }
    .team-content blockquote {
      border-left: 4px solid var(--accent-gold);
      padding: 0.5rem 1rem;
      margin: 1rem 0;
      background: rgba(251, 191, 36, 0.08);
      font-style: italic;
      color: #fef3c7;
    }
    .related-links {
      margin-top: 3rem;
      padding-top: 1.5rem;
      border-top: 2px solid var(--border);
    }
    .related-links h2 {
      color: var(--accent-blue);
      font-size: 1.2rem;
      margin-bottom: 0.5rem;
    }
    .site-footer {
      max-width: 960px;
      margin: 3rem auto 1rem;
      padding: 1.5rem;
      text-align: center;
      color: var(--text-secondary);
      font-size: 0.85rem;
      border-top: 1px solid var(--border);
    }
    @media (max-width: 640px) {
      .team-hero h1 { font-size: 1.4rem; }
      .team-hero { padding: 1.5rem 1rem; }
      .team-content h2 { font-size: 1.2rem; }
    }
  </style>
</head>
<body>
  <header class="site-header">
    <div class="site-header-inner">
      <div class="site-title">⚽ 高校サッカー順位確認システム</div>
      <nav>
        <a href="/">🏠 ホーム</a>
        <a href="/leagues/">🏆 リーグ一覧</a>
      </nav>
    </div>
  </header>

  <main class="container">
    <nav class="breadcrumb">
      <a href="/">ホーム</a>
      <span>›</span>
      <a href="/prefectures/__PREFECTURE_ID__/">__PREFECTURE_NAME__</a>
      <span>›</span>
      <span>__TEAM_NAME__</span>
    </nav>

    <section class="team-hero">
      <h1>__TEAM_NAME__ U-18 高校サッカー</h1>
      <p class="lead">__LEAD__</p>
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

  <footer class="site-footer">
    <p>© 高校サッカー順位確認システム / Dr.Kazu Soccer (<a href="https://x.com/DrKazuSoccer">@DrKazuSoccer</a>)</p>
  </footer>
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
    parts_text.append(f"{name}サッカー部")
    if league:
        parts_text.append(f"は {league} 所属")
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
    # 空白除去 & 重複除外
    seen = set()
    out = []
    for p in parts:
        p = (p or "").strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return ",".join(out)


def render_team_page(profile: dict) -> str:
    """1チームのプロフィールから HTML を生成"""
    meta = profile["meta"]
    body_md = profile["body_md"]

    # markdown → HTML（テーブル拡張あり）
    md = markdown.Markdown(extensions=["tables", "fenced_code", "nl2br", "sane_lists"])
    body_html = md.convert(body_md)

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

    # 既存の /teams/ URL エントリを削除
    pattern = re.compile(
        r'\s*<url>\s*<loc>[^<]*?/teams/[^<]*?</loc>.*?</url>',
        re.DOTALL
    )
    content_cleaned = pattern.sub('', content)

    # 新しい /teams/ URL エントリを生成
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
        return 0  # エラーで止めない

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

    # sitemap.xml 更新
    update_sitemap(profiles)

    print(f"[Teams] 完了")
    return 0


if __name__ == "__main__":
    exit(main())
