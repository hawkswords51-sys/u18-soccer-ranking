#!/usr/bin/env python3
"""
ブログ記事ページの自動生成 (Phase 9-D)

機能:
    1. blog-source/ 内の Markdown ファイルを読み込み
    2. 各記事から HTML ページを生成 → blog/posts/<slug>/index.html
    3. ブログ一覧ページ (記事リスト・カテゴリ別フィルタ) を生成 → blog/index.html
    4. sitemap.xml にブログ URL を追加 (既存を尊重)

Markdown ファイルの先頭にフロントマター (YAML) を書きます:

    ---
    title: 記事タイトル
    slug: my-article-slug    # URL になる文字列 (英数とハイフン)
    date: 2026-05-06
    category: シーズン展望
    tags: [プレミアリーグ, EAST, 2026]
    description: メタディスクリプション (120-160 字推奨)
    author: 医師ブロガー
    ---

    本文 (Markdown 記法)

依存ライブラリ:
    pip install markdown pyyaml

使い方:
    python scraper/generate_blog_pages.py
"""
import json
import re
from pathlib import Path
from datetime import date, datetime

try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML が必要です: pip install pyyaml")
    raise

try:
    import markdown as md
except ImportError:
    print("[ERROR] markdown が必要です: pip install markdown")
    raise


# ============================================================
# 設定
# ============================================================
BASE_DIR = Path(__file__).parent.parent
BLOG_SOURCE_DIR = BASE_DIR / "blog-source"
BLOG_OUTPUT_DIR = BASE_DIR / "blog"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"
DOMAIN = "https://u18-soccer.com"
GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"

# 表示するカテゴリ一覧 (順序を固定)
CATEGORIES = [
    "シーズン展望",
    "注目チーム解説",
    "戦術分析",
    "選手紹介",
    "医学コラム",
    "コラム・取材",
    "お知らせ",
]


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


def parse_markdown_file(path):
    """Markdown ファイルを読み込み、frontmatter とコンテンツを分離"""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None, None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, None
    try:
        meta = yaml.safe_load(parts[1])
        body = parts[2].strip()
    except yaml.YAMLError as e:
        print(f"[ERROR] {path.name} の frontmatter が壊れています: {e}")
        return None, None
    return meta, body


def md_to_html(body):
    """Markdown を HTML に変換 (拡張機能付き)"""
    return md.markdown(
        body,
        extensions=[
            "extra",       # テーブル・脚注・etc
            "toc",         # 見出しに id を自動付与
            "sane_lists",
            "smarty",
        ],
        extension_configs={
            "toc": {
                "permalink": False,
                "baselevel": 2,
            }
        },
    )


def slugify(text):
    """日本語混じりも安全な slug 化 (asciiのみ・- 区切り)"""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text or "post"


def format_date(d):
    """日付を見やすく整形 (2026-05-06 -> 2026年5月6日)"""
    if isinstance(d, str):
        try:
            d = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            return d
    if isinstance(d, (date, datetime)):
        return f"{d.year}年{d.month}月{d.day}日"
    return str(d)


# ============================================================
# 記事ページ HTML テンプレート
# ============================================================
ARTICLE_TEMPLATE = """<!DOCTYPE html>
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
  <title>__TITLE__</title>
  <meta name="description" content="__DESCRIPTION__">
  <meta name="keywords" content="__KEYWORDS__">
  <meta name="author" content="__AUTHOR__">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="__CANONICAL__">

  <meta property="og:type" content="article">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="__TITLE__">
  <meta property="og:description" content="__DESCRIPTION__">
  <meta property="og:url" content="__CANONICAL__">
  <meta property="og:image" content="__OG_IMAGE__">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:locale" content="ja_JP">
  <meta property="article:published_time" content="__DATE_ISO__">
  <meta property="article:section" content="__CATEGORY__">
  <meta property="article:author" content="Dr.Kazu Soccer">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:creator" content="@DrKazuSoccer">
  <meta name="twitter:title" content="__TITLE__">
  <meta name="twitter:description" content="__DESCRIPTION__">
  <meta name="twitter:image" content="__OG_IMAGE__">

  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <meta name="theme-color" content="#1e40af">

  <script type="application/ld+json">
__SCHEMA_BREADCRUMB__
  </script>
  <script type="application/ld+json">
__SCHEMA_ARTICLE__
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
          <a href="/leagues/" class="nav-link"><i class="fas fa-trophy"></i> リーグ</a>
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
        <a href="/blog/">ブログ</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">__TITLE__</span>
      </nav>

      <article class="blog-article">
        <header class="blog-article__header">
          <div class="blog-article__meta">
            <span class="blog-article__category">__CATEGORY__</span>
            <time class="blog-article__date" datetime="__DATE_ISO__">__DATE_DISPLAY__</time>
          </div>
          <h1 class="blog-article__title">__TITLE__</h1>
          <div class="blog-article__author">
            <i class="fas fa-user-md"></i> by __AUTHOR__
          </div>
          <div class="blog-article__tags">
__TAGS_HTML__
          </div>
        </header>

        <div class="blog-article__body">
__ARTICLE_BODY__
        </div>

        <footer class="blog-article__footer">
          <div class="blog-article__share">
            <span>シェア:</span>
            <a href="https://twitter.com/intent/tweet?url=__CANONICAL_URL_ENC__&text=__TITLE_URL_ENC__"
               target="_blank" rel="noopener" class="share-btn share-btn--twitter">
              <i class="fab fa-x-twitter"></i> X
            </a>
            <a href="https://www.facebook.com/sharer/sharer.php?u=__CANONICAL_URL_ENC__"
               target="_blank" rel="noopener" class="share-btn share-btn--facebook">
              <i class="fab fa-facebook"></i> Facebook
            </a>
            <a href="https://social-plugins.line.me/lineit/share?url=__CANONICAL_URL_ENC__"
               target="_blank" rel="noopener" class="share-btn share-btn--line">
              <i class="fab fa-line"></i> LINE
            </a>
          </div>
        </footer>
      </article>

      <!-- 関連記事 -->
      <section class="lp-section">
        <h2><i class="fas fa-newspaper"></i> 同じカテゴリの最新記事</h2>
        <ul class="blog-related-list">
__RELATED_HTML__
        </ul>
        <p style="margin-top:16px;text-align:center;">
          <a href="/blog/" class="lp-cta__btn">
            <i class="fas fa-list"></i> ブログトップへ戻る
          </a>
        </p>
      </section>

      <!-- 関連リンク -->
      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/">全国の高校サッカー順位表トップ</a></li>
          <li><a href="/leagues/">リーグ一覧</a></li>
          <li><a href="/blog/">ブログ一覧</a></li>
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


def url_encode(s):
    """簡易URL エンコード"""
    from urllib.parse import quote
    return quote(s)


def render_tags_html(tags):
    if not tags:
        return ""
    items = []
    for t in tags:
        items.append(
            f'            <span class="blog-tag">#{html_escape(t)}</span>'
        )
    return "\n".join(items)


def render_related_html(current_slug, current_category, all_articles):
    """同じカテゴリの記事を上位5件"""
    related = [
        a for a in all_articles
        if a["category"] == current_category and a["slug"] != current_slug
    ][:5]
    if not related:
        return '          <li style="color:#888;">同カテゴリの記事はまだありません</li>'
    items = []
    for a in related:
        items.append(
            f'          <li>'
            f'<a href="/blog/posts/{a["slug"]}/" class="blog-related-link">'
            f'<span class="blog-related-link__date">{format_date(a["date"])}</span>'
            f'<span class="blog-related-link__title">{html_escape(a["title"])}</span>'
            f'</a>'
            f'</li>'
        )
    return "\n".join(items)


def generate_article_page(article, all_articles):
    """個別記事ページ HTML を生成"""
    slug = article["slug"]
    canonical = f"{DOMAIN}/blog/posts/{slug}/"
    title = article["title"]
    description = article.get("description", "")[:160]
    keywords = ",".join(article.get("tags", []) + [article.get("category", "")])
    author = article.get("author", "U18 Soccer Ranking")
    date_iso = str(article["date"])
    date_display = format_date(article["date"])
    category = article.get("category", "コラム・取材")
    og_image = article.get("ogImage", f"{DOMAIN}/og-image.png")

    # 構造化データ
    breadcrumb = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "ブログ", "item": f"{DOMAIN}/blog/"},
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical},
        ],
    }, ensure_ascii=False, indent=2)

    article_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": description,
        "author": {"@type": "Person", "name": author},
        "datePublished": date_iso,
        "dateModified": date_iso,
        "mainEntityOfPage": canonical,
        "publisher": {
            "@type": "Organization",
            "name": "高校サッカー順位確認システム",
            "logo": {
                "@type": "ImageObject",
                "url": f"{DOMAIN}/og-image.png",
            },
        },
        "image": og_image,
        "articleSection": category,
        "keywords": ",".join(article.get("tags", [])),
        "inLanguage": "ja-JP",
    }, ensure_ascii=False, indent=2)

    body_html = md_to_html(article["body"])
    tags_html = render_tags_html(article.get("tags", []))
    related_html = render_related_html(slug, category, all_articles)

    return (
        ARTICLE_TEMPLATE
        .replace("__GA_ID__", GA_ID)
        .replace("__ADSENSE__", ADSENSE_CLIENT)
        .replace("__TITLE__", html_escape(title))
        .replace("__DESCRIPTION__", html_escape(description))
        .replace("__KEYWORDS__", html_escape(keywords))
        .replace("__AUTHOR__", html_escape(author))
        .replace("__CANONICAL__", canonical)
        .replace("__OG_IMAGE__", og_image)
        .replace("__DATE_ISO__", date_iso)
        .replace("__DATE_DISPLAY__", date_display)
        .replace("__CATEGORY__", html_escape(category))
        .replace("__SCHEMA_BREADCRUMB__", breadcrumb)
        .replace("__SCHEMA_ARTICLE__", article_schema)
        .replace("__ARTICLE_BODY__", body_html)
        .replace("__TAGS_HTML__", tags_html)
        .replace("__RELATED_HTML__", related_html)
        .replace("__CANONICAL_URL_ENC__", url_encode(canonical))
        .replace("__TITLE_URL_ENC__", url_encode(title))
    )


# ============================================================
# ブログ一覧ページ HTML
# ============================================================
INDEX_TEMPLATE = """<!DOCTYPE html>
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
  <title>ブログ | 高校サッカー U-18 戦術・選手・コラム情報</title>
  <meta name="description" content="高校サッカーU-18 のシーズン展望、注目チーム解説、戦術分析、選手紹介、医学コラムなどを医師ブロガーがお届けする情報サイト。最新記事を毎週更新。">
  <meta name="keywords" content="高校サッカー,U-18,ブログ,シーズン展望,戦術分析,医学コラム,選手紹介">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="https://u18-soccer.com/blog/">

  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="ブログ | 高校サッカー U-18 戦術・選手・コラム情報">
  <meta property="og:description" content="高校サッカーU-18 のシーズン展望・戦術分析・医学コラムなど">
  <meta property="og:url" content="https://u18-soccer.com/blog/">
  <meta property="og:image" content="https://u18-soccer.com/og-image.png">
  <meta property="og:locale" content="ja_JP">

  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <meta name="theme-color" content="#1e40af">

  <script type="application/ld+json">
__SCHEMA_BREADCRUMB__
  </script>
  <script type="application/ld+json">
__SCHEMA_BLOG__
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
          <a href="/leagues/" class="nav-link"><i class="fas fa-trophy"></i> リーグ</a>
        </nav>
      </div>
    </div>
  </header>

  <main class="main-content">
    <div class="container">
      <nav class="breadcrumb" aria-label="パンくずリスト">
        <a href="/">ホーム</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">ブログ</span>
      </nav>

      <h1 class="lp-title"><i class="fas fa-newspaper"></i> ブログ</h1>
      <p class="lp-intro">
        高校サッカー U-18 のシーズン展望・注目チーム解説・戦術分析・選手紹介・医学コラムを
        医師ブロガーがお届けします。最新の試合結果や順位の動向もブログで深く解説していきます。
      </p>

      <!-- カテゴリフィルタ -->
      <section class="lp-section">
        <h2><i class="fas fa-filter"></i> カテゴリから探す</h2>
        <div class="blog-categories">
__CATEGORY_BUTTONS__
        </div>
      </section>

      <!-- 記事リスト -->
      <section class="lp-section">
        <h2><i class="fas fa-list"></i> 最新の記事</h2>
        <ul class="blog-list">
__ARTICLES_HTML__
        </ul>
      </section>

      <!-- 関連リンク -->
      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/">全国の高校サッカー順位表トップ</a></li>
          <li><a href="/leagues/">リーグ一覧</a></li>
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


def render_index_page(articles):
    """ブログ一覧ページ HTML"""
    # カテゴリボタン
    cat_buttons = []
    cat_counts = {}
    for a in articles:
        cat = a.get("category", "その他")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    for cat in CATEGORIES:
        count = cat_counts.get(cat, 0)
        if count == 0:
            continue
        cat_buttons.append(
            f'          <span class="blog-category-tag">'
            f'{html_escape(cat)} <small>({count})</small></span>'
        )
    cat_buttons_html = "\n".join(cat_buttons) if cat_buttons else (
        '          <span style="color:#888;">記事はまだありません</span>'
    )

    # 記事リスト (新しい順)
    sorted_articles = sorted(articles, key=lambda a: str(a["date"]), reverse=True)
    items = []
    for a in sorted_articles:
        items.append(
            f'          <li class="blog-list-item">\n'
            f'            <a href="/blog/posts/{a["slug"]}/" class="blog-list-link">\n'
            f'              <div class="blog-list-meta">\n'
            f'                <span class="blog-list-category">{html_escape(a.get("category", ""))}</span>\n'
            f'                <time class="blog-list-date" datetime="{a["date"]}">{format_date(a["date"])}</time>\n'
            f'              </div>\n'
            f'              <h3 class="blog-list-title">{html_escape(a["title"])}</h3>\n'
            f'              <p class="blog-list-desc">{html_escape(a.get("description", "")[:120])}</p>\n'
            f'            </a>\n'
            f'          </li>'
        )
    articles_html = "\n".join(items) if items else (
        '          <li style="color:#888;text-align:center;padding:40px;">'
        '記事はまだありません。最初の記事を準備中です。</li>'
    )

    breadcrumb = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "ブログ", "item": f"{DOMAIN}/blog/"},
        ],
    }, ensure_ascii=False, indent=2)

    blog_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "Blog",
        "name": "高校サッカー U-18 ブログ",
        "url": f"{DOMAIN}/blog/",
        "description": "高校サッカー U-18 のシーズン展望・戦術分析・医学コラム",
        "inLanguage": "ja-JP",
        "publisher": {
            "@type": "Organization",
            "name": "高校サッカー順位確認システム",
        },
        "blogPost": [
            {
                "@type": "BlogPosting",
                "headline": a["title"],
                "url": f"{DOMAIN}/blog/posts/{a['slug']}/",
                "datePublished": str(a["date"]),
            }
            for a in sorted_articles[:10]
        ],
    }, ensure_ascii=False, indent=2)

    return (
        INDEX_TEMPLATE
        .replace("__GA_ID__", GA_ID)
        .replace("__ADSENSE__", ADSENSE_CLIENT)
        .replace("__SCHEMA_BREADCRUMB__", breadcrumb)
        .replace("__SCHEMA_BLOG__", blog_schema)
        .replace("__CATEGORY_BUTTONS__", cat_buttons_html)
        .replace("__ARTICLES_HTML__", articles_html)
    )


# ============================================================
# Sitemap 更新 (既存に append)
# ============================================================
def append_sitemap(slugs):
    """既存 sitemap.xml にブログ URL を追加"""
    if not SITEMAP_FILE.exists():
        print(f"[WARN] {SITEMAP_FILE} が存在しません。先に他の generator を実行してください。")
        return
    today = date.today().isoformat()
    content = SITEMAP_FILE.read_text(encoding="utf-8")

    # 既存ブログ URL を一旦除去 (重複防止)
    content = re.sub(
        r'\s*<url>\s*<loc>[^<]*?/blog/[^<]*</loc>.*?</url>',
        '', content, flags=re.DOTALL,
    )

    new_urls = []
    # ブログトップ
    new_urls.append(
        f'  <url>\n'
        f'    <loc>{DOMAIN}/blog/</loc>\n'
        f'    <lastmod>{today}</lastmod>\n'
        f'    <changefreq>weekly</changefreq>\n'
        f'    <priority>0.7</priority>\n'
        f'  </url>'
    )
    # 各記事
    for slug in slugs:
        new_urls.append(
            f'  <url>\n'
            f'    <loc>{DOMAIN}/blog/posts/{slug}/</loc>\n'
            f'    <lastmod>{today}</lastmod>\n'
            f'    <changefreq>monthly</changefreq>\n'
            f'    <priority>0.6</priority>\n'
            f'  </url>'
        )

    # </urlset> の直前に追加
    content = content.replace("</urlset>", "\n".join(new_urls) + "\n</urlset>")
    SITEMAP_FILE.write_text(content, encoding="utf-8")
    print(f"sitemap.xml にブログ URL を追加: {len(slugs) + 1} URL")


# ============================================================
# Main
# ============================================================
def main():
    if not BLOG_SOURCE_DIR.exists():
        print(f"[INFO] {BLOG_SOURCE_DIR} が存在しません。スキップ。")
        return 0

    # Markdown ファイルを全て読み込み
    articles = []
    for md_file in sorted(BLOG_SOURCE_DIR.glob("*.md")):
        meta, body = parse_markdown_file(md_file)
        if not meta or not body:
            print(f"[SKIP] {md_file.name}: frontmatter が読めません")
            continue
        if not meta.get("slug"):
            meta["slug"] = slugify(meta.get("title", md_file.stem))
        article = {**meta, "body": body, "_source": md_file.name}
        articles.append(article)
        print(f"[OK] {md_file.name} -> /blog/posts/{article['slug']}/")

    if not articles:
        print("[INFO] 記事がありません。ブログトップだけ生成します。")

    # 出力先
    BLOG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    posts_dir = BLOG_OUTPUT_DIR / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)

    # 個別記事ページ
    for a in articles:
        article_dir = posts_dir / a["slug"]
        article_dir.mkdir(parents=True, exist_ok=True)
        html = generate_article_page(a, articles)
        (article_dir / "index.html").write_text(html, encoding="utf-8")

    # ブログ一覧ページ
    index_html = render_index_page(articles)
    (BLOG_OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print(f"[OK] ブログ一覧 -> /blog/")

    # sitemap 更新
    append_sitemap([a["slug"] for a in articles])

    print(f"完了: {len(articles)} 記事 + 1 一覧ページを生成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
