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
    "リーグ解説",
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
__SCHEMA_EXTRA__
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
        <div class="site-title">
          <a href="/" style="color:white;text-decoration:none;display:inline-flex;align-items:center;gap:10px">
            <i class="fas fa-futbol"></i>
            高校サッカー順位確認システム
          </a>
        </div>
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
__UPDATED_HTML__
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
__AI_SUMMARY__
__TOC_HTML__
__ARTICLE_BODY__
__FAQ_HTML__
        </div>

__AUTHOR_BOX__
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

# ============================================================
# E-E-A-T 強化 (2026-07-02): 著者情報・医療系構造化データ・FAQ
# ============================================================
MEDICAL_CATEGORY = "医学コラム"
AUTHOR_X_URL = "https://x.com/DrKazuSoccer"
AUTHOR_NOTE_URL = "https://note.com/drkazusoccer"
AUTHOR_BIO = (
    "救命救急センターに勤務する救急科専門医（日本救急医学会認定）。"
    "脳神経外科専門医・脳卒中専門医でもあり、医師17年目・救急医療12年。"
    "熱中症・頭部外傷・外傷全般・心肺停止などの救急診療と病院前救急に従事。"
    "日本の育成年代サッカーへの関心から当サイトを運営し、"
    "熱中症・脳震盪・栄養・睡眠・怪我予防など選手の安全に関する"
    "医学コラムを、公的ガイドライン・医学的根拠に基づいて執筆しています。"
)


def build_author_person(article):
    """構造化データ用の著者 Person オブジェクト (E-E-A-T 対応)"""
    person = {
        "@type": "Person",
        "name": article.get("author", "Dr.Kazu Soccer"),
        "jobTitle": "救急科専門医",
        "description": AUTHOR_BIO,
        "hasCredential": [
            {
                "@type": "EducationalOccupationalCredential",
                "credentialCategory": "専門医資格",
                "name": "救急科専門医",
                "recognizedBy": {"@type": "Organization", "name": "日本救急医学会"},
            },
            {
                "@type": "EducationalOccupationalCredential",
                "credentialCategory": "専門医資格",
                "name": "脳神経外科専門医",
                "recognizedBy": {"@type": "Organization", "name": "日本脳神経外科学会"},
            },
            {
                "@type": "EducationalOccupationalCredential",
                "credentialCategory": "専門医資格",
                "name": "脳卒中専門医",
                "recognizedBy": {"@type": "Organization", "name": "日本脳卒中学会"},
            },
            {
                "@type": "EducationalOccupationalCredential",
                "credentialCategory": "専門医資格",
                "name": "脳血管内治療専門医",
                "recognizedBy": {"@type": "Organization", "name": "日本脳神経血管内治療学会"},
            },
            {
                "@type": "EducationalOccupationalCredential",
                "credentialCategory": "学位",
                "name": "医学博士",
            },
        ],
        "url": f"{DOMAIN}/about.html",
        "sameAs": [AUTHOR_X_URL, AUTHOR_NOTE_URL],
        "knowsAbout": [
            "救急医学", "スポーツ医学", "熱中症", "脳震盪",
            "コンディショニング", "高校サッカー",
        ],
    }
    return person


def build_schema_extra(article, canonical):
    """医学コラム向けの追加 JSON-LD (MedicalWebPage / FAQPage)。
    医学コラム以外のカテゴリでは空文字を返す (既存記事に影響なし)。"""
    scripts = []
    if article.get("category") == MEDICAL_CATEGORY:
        person = build_author_person(article)
        last_reviewed = str(article.get("updated") or article["date"])
        medical = {
            "@context": "https://schema.org",
            "@type": "MedicalWebPage",
            "name": article["title"],
            "url": canonical,
            "description": article.get("description", "")[:160],
            "inLanguage": "ja-JP",
            "lastReviewed": last_reviewed,
            "reviewedBy": person,
            "author": person,
            "audience": {
                "@type": "PeopleAudience",
                "audienceType": "サッカー選手・保護者・指導者",
            },
        }
        topic = article.get("medicalTopic")
        if topic:
            medical["about"] = {"@type": "MedicalCondition", "name": topic}
        scripts.append(medical)

        faq = article.get("faq") or []
        faq_items = [
            f for f in faq
            if isinstance(f, dict) and f.get("q") and f.get("a")
        ]
        if faq_items:
            scripts.append({
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": f["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": f["a"]},
                    }
                    for f in faq_items
                ],
            })
    if not scripts:
        return ""
    blocks = []
    for s in scripts:
        blocks.append(
            '  <script type="application/ld+json">\n'
            + json.dumps(s, ensure_ascii=False, indent=2)
            + "\n  </script>"
        )
    return "\n".join(blocks) + "\n"


def build_faq_html(article):
    """frontmatter の faq: [{q:, a:}, ...] を「よくある質問」セクションとして描画"""
    faq = article.get("faq") or []
    faq_items = [
        f for f in faq
        if isinstance(f, dict) and f.get("q") and f.get("a")
    ]
    if not faq_items:
        return ""
    parts = [
        '<section class="blog-article__faq" id="faq">',
        '<h2><i class="fas fa-circle-question"></i> よくある質問</h2>',
    ]
    for f in faq_items:
        parts.append(
            '<div style="margin:0 0 18px;">'
            f'<h3 style="margin:0 0 6px;font-size:1.05rem;">Q. {html_escape(f["q"])}</h3>'
            f'<p style="margin:0;">A. {html_escape(f["a"])}</p>'
            "</div>"
        )
    parts.append("</section>")
    return "\n".join(parts)


def build_author_box(article):
    """医学コラム記事の末尾に置く著者プロフィール (E-E-A-T 対応)。
    医学コラム以外では表示しない。"""
    if article.get("category") != MEDICAL_CATEGORY:
        return ""
    author = html_escape(article.get("author", "Dr.Kazu Soccer"))
    box_style = (
        "margin:8px 0 24px;padding:18px 20px;"
        "background:var(--bg-light,#f8fafc);"
        "border:1px solid var(--border-color,#e2e8f0);border-radius:12px;"
        "font-size:0.95rem;line-height:1.85;"
    )
    label_style = (
        "font-size:0.8rem;font-weight:600;letter-spacing:0.06em;"
        "color:var(--primary-color,#1e40af);margin:0 0 6px;"
    )
    return (
        f'        <aside class="blog-article__authorbox" style="{box_style}">\n'
        f'          <p style="{label_style}"><i class="fas fa-user-md"></i> この記事の執筆者</p>\n'
        f'          <p style="margin:0 0 8px;"><strong>{author}</strong>（日本救急医学会認定 救急科専門医・脳神経外科専門医・医学博士）</p>\n'
        f'          <p style="margin:0 0 10px;">{html_escape(AUTHOR_BIO)}</p>\n'
        f'          <p style="margin:0;">\n'
        f'            <a href="/blog/medical/">医学コラム一覧 ›</a>　\n'
        f'            <a href="/about.html">運営者情報を見る ›</a>　\n'
        f'            <a href="{AUTHOR_X_URL}" target="_blank" rel="noopener">X（@DrKazuSoccer）›</a>　\n'
        f'            <a href="{AUTHOR_NOTE_URL}" target="_blank" rel="noopener">note ›</a>\n'
        f'          </p>\n'
        f'        </aside>\n'
    )


def build_article_ai_summary(article):
    """記事本文の冒頭に置くAI引用向け要約。
    frontmatterに aiSummary があればそれを優先（meta descriptionだけ変えたい時に
    AI要約を固定できる）。なければ従来どおり description を可視化する。"""
    desc = (article.get("aiSummary") or article.get("description") or "").strip()
    if not desc:
        return ""
    style = (
        "margin:0 0 24px;padding:14px 18px;background:var(--bg-light,#f1f5fb);"
        "border-left:4px solid var(--primary-color,#1e40af);border-radius:0 8px 8px 0;"
        "font-size:0.97rem;line-height:1.85;"
    )
    return f'          <p class="blog-article__summary" style="{style}">{html_escape(desc)}</p>\n'

TOC_MIN_ENTRIES = 3          # 見出しがこれ未満の短い記事には目次を付けない
TOC_EXCLUDE_TITLES = {"関連ページ"}  # 目次に載せない定型見出し

def build_toc_html(body_html):
    """記事本文HTMLから目次（もくじ）ボックスを生成する（AdSense改善A-2・2026-07-19）。

    md_to_html は toc 拡張（baselevel=2）で変換するため、mdの「## 見出し」は
    id付きの <h3> になっている。そのidへのページ内リンク一覧を作る。
    - 対象は id 付き h3 のみ（FAQのh3はid無しなので混入しない）
    - 冒頭のh2はタイトルの繰り返しなので対象外
    - 見出しが TOC_MIN_ENTRIES 本未満の記事はスキップ（短い記事に目次は過剰）
    """
    entries = []
    for m in re.finditer(r'<h3 id="([^"]+)"[^>]*>(.*?)</h3>', body_html, re.S):
        anchor, inner = m.group(1), m.group(2)
        text = re.sub(r"<[^>]+>", "", inner).strip()
        if not text or text in TOC_EXCLUDE_TITLES:
            continue
        entries.append((anchor, text))
    if len(entries) < TOC_MIN_ENTRIES:
        return ""
    items = "\n".join(
        f'              <li style="margin:0;"><a href="#{html_escape(a)}" '
        f'style="color:var(--primary-color,#1e40af);text-decoration:none;">{html_escape(t)}</a></li>'
        for a, t in entries
    )
    return (
        '          <nav class="blog-toc" aria-label="目次" '
        'style="margin:0 0 24px;padding:14px 18px;background:var(--bg-light,#f8f9fa);'
        'border:1px solid var(--border-color,#e0e0e0);border-radius:10px;font-size:0.95rem;">\n'
        '            <div style="font-weight:700;margin-bottom:8px;">'
        '<i class="fas fa-list-ul" aria-hidden="true"></i> 目次</div>\n'
        '            <ol style="margin:0;padding-left:1.5em;line-height:2.0;">\n'
        f"{items}\n"
        "            </ol>\n"
        "          </nav>\n"
    )

def build_updated_html(article):
    """frontmatter に updated がある記事に「最終更新日」を可視表示する
    （AdSense改善B-4・2026-07-19）。構造化データのdateModifiedとは別に、
    読者と審査員の目に見える形で鮮度を示す。updated が公開日と同じ場合は出さない。"""
    updated = article.get("updated")
    if not updated or str(updated) == str(article.get("date")):
        return ""
    return (
        f'            <time class="blog-article__updated" datetime="{str(updated)}" '
        f'style="font-size:0.85em;color:var(--text-light,#666);">'
        f'<i class="fas fa-rotate" aria-hidden="true"></i> 最終更新：{format_date(updated)}</time>'
    )

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

    date_modified = str(article.get("updated") or article["date"])
    article_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": description,
        "author": build_author_person(article),
        "datePublished": date_iso,
        "dateModified": date_modified,
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
        .replace("__UPDATED_HTML__", build_updated_html(article))
        .replace("__CATEGORY__", html_escape(category))
        .replace("__SCHEMA_BREADCRUMB__", breadcrumb)
        .replace("__SCHEMA_ARTICLE__", article_schema)
        .replace("__SCHEMA_EXTRA__", build_schema_extra(article, canonical))
        .replace("__TOC_HTML__", build_toc_html(body_html))
        .replace("__ARTICLE_BODY__", body_html)
        .replace("__FAQ_HTML__", build_faq_html(article))
        .replace("__AUTHOR_BOX__", build_author_box(article))
        .replace("__AI_SUMMARY__", build_article_ai_summary(article))
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
  <meta name="description" content="高校サッカーU-18のシーズン展望・注目チーム解説・戦術分析・選手紹介に加え、救急科専門医による熱中症・貧血・睡眠・脳震盪などの医学コラムを毎週お届けします。選手・保護者・指導者に役立つ、医学的根拠にもとづくコンディショニング情報を発信中です。">
  <meta name="keywords" content="高校サッカー,U-18,ブログ,シーズン展望,戦術分析,医学コラム,選手紹介">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="https://u18-soccer.com/blog/">
  <link rel="alternate" type="application/rss+xml" title="高校サッカー順位確認システム ブログ" href="https://u18-soccer.com/blog/feed.xml">

  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="ブログ | 高校サッカー U-18 戦術・選手・コラム情報">
  <meta property="og:description" content="高校サッカーU-18 のシーズン展望・戦術分析・医学コラムなど">
  <meta property="og:url" content="https://u18-soccer.com/blog/">
  <meta property="og:image" content="https://u18-soccer.com/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:locale" content="ja_JP">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:creator" content="@DrKazuSoccer">
  <meta name="twitter:title" content="ブログ | 高校サッカー U-18 戦術・選手・コラム情報">
  <meta name="twitter:description" content="高校サッカーU-18 のシーズン展望・戦術分析・医学コラムなど">
  <meta name="twitter:image" content="https://u18-soccer.com/og-image.png">
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
        <div class="site-title">
          <a href="/" style="color:white;text-decoration:none;display:inline-flex;align-items:center;gap:10px">
            <i class="fas fa-futbol"></i>
            高校サッカー順位確認システム
          </a>
        </div>
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

      <!-- 医学コラム特設ページへの導線 -->
      <a href="/blog/medical/" style="display:flex;align-items:center;gap:14px;margin:16px 0 24px;padding:16px 20px;border-radius:12px;background:linear-gradient(135deg,#0f766e,#14b8a6);color:#fff;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,0.12);">
        <span style="font-size:1.8em;" aria-hidden="true">🩺</span>
        <span>
          <span style="display:block;font-weight:700;font-size:1.05em;">救急医の医学コラム 特設ページ</span>
          <span style="display:block;font-size:0.88em;opacity:0.92;">熱中症・脳震盪・栄養・睡眠——テーマ別の一覧と「読む順ガイド」はこちら →</span>
        </span>
      </a>

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
    for cat, count in sorted(cat_counts.items()):
        if cat not in CATEGORIES:
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
def generate_rss(articles):
    """ブログのRSSフィード (blog/feed.xml) を生成"""
    from datetime import timezone, timedelta
    from email.utils import format_datetime

    def _to_dt(d):
        if isinstance(d, datetime):
            return d
        if isinstance(d, date):
            return datetime(d.year, d.month, d.day, 9, 0, 0)
        try:
            return datetime.strptime(str(d), "%Y-%m-%d")
        except ValueError:
            return datetime.now()

    jst = timezone(timedelta(hours=9))
    sorted_articles = sorted(articles, key=lambda a: str(a["date"]), reverse=True)[:20]
    items = []
    for a in sorted_articles:
        link = f"{DOMAIN}/blog/posts/{a['slug']}/"
        dt = _to_dt(a["date"]).replace(tzinfo=jst)
        items.append(
            "  <item>\n"
            f"    <title>{html_escape(a['title'])}</title>\n"
            f"    <link>{link}</link>\n"
            f'    <guid isPermaLink="true">{link}</guid>\n'
            f"    <pubDate>{format_datetime(dt)}</pubDate>\n"
            f"    <category>{html_escape(a.get('category', ''))}</category>\n"
            f"    <description>{html_escape(a.get('description', ''))}</description>\n"
            "  </item>"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        "  <title>高校サッカー順位確認システム ブログ</title>\n"
        f"  <link>{DOMAIN}/blog/</link>\n"
        "  <description>高校サッカーU-18のシーズン展望・戦術分析・選手紹介と、救急科専門医による医学コラム</description>\n"
        "  <language>ja</language>\n"
        f'  <atom:link href="{DOMAIN}/blog/feed.xml" rel="self" type="application/rss+xml"/>\n'
        + "\n".join(items) + "\n"
        "</channel>\n"
        "</rss>\n"
    )
    (BLOG_OUTPUT_DIR / "feed.xml").write_text(rss, encoding="utf-8")
    print(f"[OK] RSSフィード -> /blog/feed.xml ({len(sorted_articles)}件)")

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
    # 医学コラムハブ（B-3。/blog/配下は上の正規表現で毎回消えるのでここで再追加）
    new_urls.append(
        f'  <url>\n'
        f'    <loc>{DOMAIN}/blog/{MEDICAL_HUB_DIR_NAME}/</loc>\n'
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
# トップページ「新着コラム」欄の更新 (2026-07-18 追加)
#
# 狙い: ブログ記事(とくに医学コラム)は従来 /blog/ 一覧の奥にしか
# リンクがなく、GSCで「参照元=sitemap.xmlのみ」→インデックス未登録が
# 多発していた。サイト内で最も評価の高いトップページから最新記事へ
# 常設リンクを張り、Googleのクロール優先度を引き上げる。
#
# index.html の LATEST_BLOG_START/END マーカー間を毎回書き換える方式
# (HOME_SUMMARY と同じ)。マーカーを消すと更新が止まるので手で編集しない。
# ============================================================
HOME_FILE = BASE_DIR / "index.html"
HOME_LATEST_START = "<!-- LATEST_BLOG_START -->"
HOME_LATEST_END = "<!-- LATEST_BLOG_END -->"
HOME_LATEST_COUNT = 6

# カテゴリバッジの色 (それ以外は青)
HOME_LATEST_CATEGORY_COLORS = {
    "医学コラム": "#0f766e",
    "リーグ解説": "#7c2d12",
    "育成コラム": "#6d28d9",
}


def update_home_latest_blog(articles):
    """トップページ index.html のマーカー間に新着記事リスト(最新5本)を書き込む"""
    if not HOME_FILE.exists():
        print(f"[INFO] {HOME_FILE} が見つかりません。新着コラム欄はスキップ。")
        return
    content = HOME_FILE.read_text(encoding="utf-8")
    if HOME_LATEST_START not in content or HOME_LATEST_END not in content:
        print("[INFO] index.html に LATEST_BLOG マーカーがありません。新着コラム欄はスキップ。")
        return

    latest = sorted(articles, key=lambda a: str(a["date"]), reverse=True)[:HOME_LATEST_COUNT]
    items = []
    for a in latest:
        cat = a.get("category", "コラム")
        color = HOME_LATEST_CATEGORY_COLORS.get(cat, "#1e40af")
        items.append(
            f'    <li style="margin:0;">\n'
            f'      <a href="/blog/posts/{a["slug"]}/" style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--bg-light,#f8f9fa);border:1px solid var(--border-color,#e0e0e0);border-radius:10px;text-decoration:none;color:var(--text-dark,#1a1a1a);">\n'
            f'        <span style="flex-shrink:0;font-size:0.72em;font-weight:700;color:#fff;background:{color};padding:3px 9px;border-radius:999px;white-space:nowrap;">{html_escape(cat)}</span>\n'
            f'        <span style="font-size:0.92em;line-height:1.5;">{html_escape(a["title"])}</span>\n'
            f'        <time style="margin-left:auto;flex-shrink:0;font-size:0.78em;color:var(--text-light,#666);" datetime="{a["date"]}">{format_date(a["date"])}</time>\n'
            f'      </a>\n'
            f'    </li>'
        )

    section = (
        HOME_LATEST_START + "\n"
        '<section class="home-latest-blog" aria-label="新着ブログ記事" style="margin:24px 0;">\n'
        '  <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:10px;">\n'
        '    <h2 style="font-size:1.15rem;margin:0;">📝 新着コラム — 医学・戦術・特集</h2>\n'
        '    <a href="/blog/" style="margin-left:auto;font-size:0.88em;color:#2563eb;text-decoration:none;font-weight:600;">記事一覧へ →</a>\n'
        '  </div>\n'
        '  <ul style="list-style:none;margin:0;padding:0;display:grid;gap:8px;">\n'
        + "\n".join(items) + "\n"
        '  </ul>\n'
        '</section>\n'
        + HOME_LATEST_END
    )

    pattern = re.compile(
        re.escape(HOME_LATEST_START) + r".*?" + re.escape(HOME_LATEST_END),
        re.DOTALL,
    )
    new_content = pattern.sub(lambda m: section, content, count=1)
    HOME_FILE.write_text(new_content, encoding="utf-8")
    print(f"[OK] トップページの新着コラム欄を更新: {len(latest)} 記事")


# ============================================================
# Main
# ============================================================
# ============================================================
# 医学コラム ハブページ /blog/medical/ (2026-07-19 新設・AdSense改善B-3)
#
# 狙い: 医学コラム9本の入口がブログ一覧のカテゴリラベルしかなかったため、
# 著者紹介＋テーマ別整理＋読む順ガイドを備えた「専門コーナー」の常設ページを作る。
# YMYLコンテンツの束ね・内部リンク強化・AdSense審査への見せ場を兼ねる。
# テーマ分けは MEDICAL_HUB_THEMES（slug指定）。未登録の医学コラムは
# 自動で「新着コラム」グループに入るので、新記事を書いてもページから漏れない。
# 恒久的にテーマへ入れたい記事は MEDICAL_HUB_THEMES に slug を足す。
# ============================================================
MEDICAL_HUB_THEMES = [
    (
        "☀️ 暑さ対策・熱中症",
        "夏の練習・大会で命に関わるリスクを予防する",
        [
            "2026-05-08-may-heatstroke-prevention",
            "2026-07-10-summer-hydration-strategy",
            "interhigh-2026-heat-safety",
        ],
    ),
    (
        "🚑 外傷・緊急対応",
        "頭を打った・胸に当たった・足をひねった——その場での正しい判断",
        [
            "concussion-return-to-play-2026",
            "commotio-cordis-aed-2026",
            "2026-06-25-ankle-sprain-treatment",
        ],
    ),
    (
        "🔋 コンディショニング・栄養",
        "「走れない」「疲れが抜けない」の医学的な背景と対策",
        [
            "pre-match-meal-strategy-2026",
            "2026-07-19-overtraining-syndrome",
            "2026-06-08-iron-deficiency-anemia",
            "2026-05-22-pre-match-sleep-strategy",
        ],
    ),
]

MEDICAL_HUB_DIR_NAME = "medical"

def _medical_card(a):
    """ハブページ用の記事カード1枚"""
    updated = a.get("updated")
    date_line = f'公開 {format_date(a["date"])}'
    if updated and str(updated) != str(a.get("date")):
        date_line += f'　最終更新 {format_date(updated)}'
    desc = html_escape((a.get("description") or "")[:110])
    return (
        f'          <li style="margin:0 0 10px;list-style:none;">\n'
        f'            <a href="/blog/posts/{a["slug"]}/" style="display:block;padding:14px 18px;'
        f'background:var(--bg-light,#f8f9fa);border:1px solid var(--border-color,#e0e0e0);'
        f'border-radius:10px;text-decoration:none;color:var(--text-dark,#1a1a1a);">\n'
        f'              <span style="display:block;font-weight:600;line-height:1.6;">{html_escape(a["title"])}</span>\n'
        f'              <span style="display:block;font-size:0.85em;color:var(--text-light,#666);margin-top:4px;">{date_line}</span>\n'
        f'              <span style="display:block;font-size:0.88em;color:var(--text-light,#555);margin-top:6px;line-height:1.7;">{desc}…</span>\n'
        f'            </a>\n'
        f'          </li>'
    )

def generate_medical_hub(articles):
    """医学コラムのハブページ /blog/medical/index.html を生成"""
    medical = [a for a in articles if a.get("category") == MEDICAL_CATEGORY]
    if not medical:
        print("[INFO] 医学コラムが無いためハブページをスキップ")
        return None
    by_slug = {a["slug"]: a for a in medical}
    used = set()
    theme_sections = []
    for theme_title, theme_desc, slugs in MEDICAL_HUB_THEMES:
        cards = []
        for s in slugs:
            if s in by_slug:
                cards.append(_medical_card(by_slug[s]))
                used.add(s)
            else:
                print(f"[WARN] 医学ハブ: slug {s} が見つかりません（テーマ: {theme_title}）")
        if cards:
            theme_sections.append(
                f'      <section class="lp-section">\n'
                f'        <h2>{theme_title}</h2>\n'
                f'        <p style="margin:0 0 14px;color:var(--text-light,#555);">{theme_desc}</p>\n'
                f'        <ul style="margin:0;padding:0;">\n' + "\n".join(cards) + '\n        </ul>\n'
                f'      </section>'
            )
    # テーマ未登録の医学コラムは「新着コラム」として自動掲載（漏れ防止）
    rest = [a for a in sorted(medical, key=lambda x: str(x["date"]), reverse=True) if a["slug"] not in used]
    if rest:
        cards = "\n".join(_medical_card(a) for a in rest)
        theme_sections.append(
            '      <section class="lp-section">\n'
            '        <h2>🆕 新着コラム</h2>\n'
            '        <ul style="margin:0;padding:0;">\n' + cards + '\n        </ul>\n'
            '      </section>'
        )

    canonical = f"{DOMAIN}/blog/{MEDICAL_HUB_DIR_NAME}/"
    title = "救急医の医学コラム｜熱中症・脳震盪・栄養・睡眠 — 高校サッカー選手を守る医学の話"
    description = (
        "救急科専門医（脳神経外科専門医・医学博士）が、高校サッカー選手・保護者・指導者向けに"
        "熱中症・脳震盪・心臓振盪・捻挫・貧血・睡眠・オーバートレーニングを医学的根拠と共に解説。"
        "テーマ別一覧と読む順ガイド。"
    )
    breadcrumb = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "ブログ", "item": f"{DOMAIN}/blog/"},
            {"@type": "ListItem", "position": 3, "name": "医学コラム", "item": canonical},
        ],
    }, ensure_ascii=False)
    collection = json.dumps({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": description,
        "url": canonical,
        "inLanguage": "ja",
        "about": {"@type": "Thing", "name": "スポーツ医学・選手の安全"},
        "author": build_author_person({}),
        "hasPart": [
            {"@type": "BlogPosting", "headline": a["title"], "url": f"{DOMAIN}/blog/posts/{a['slug']}/"}
            for a in medical
        ],
    }, ensure_ascii=False)

    html = MEDICAL_HUB_TEMPLATE
    html = (
        html
        .replace("__GA_ID__", GA_ID)
        .replace("__ADSENSE__", ADSENSE_CLIENT)
        .replace("__TITLE__", html_escape(title))
        .replace("__DESCRIPTION__", html_escape(description))
        .replace("__CANONICAL__", canonical)
        .replace("__SCHEMA_BREADCRUMB__", breadcrumb)
        .replace("__SCHEMA_COLLECTION__", collection)
        .replace("__AUTHOR_BIO__", html_escape(AUTHOR_BIO))
        .replace("__AUTHOR_X_URL__", AUTHOR_X_URL)
        .replace("__AUTHOR_NOTE_URL__", AUTHOR_NOTE_URL)
        .replace("__THEME_SECTIONS__", "\n\n".join(theme_sections))
        .replace("__ARTICLE_COUNT__", str(len(medical)))
    )
    out_dir = BLOG_OUTPUT_DIR / MEDICAL_HUB_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    print(f"[OK] 医学コラムハブ -> /blog/{MEDICAL_HUB_DIR_NAME}/ （{len(medical)}記事）")
    return canonical


MEDICAL_HUB_TEMPLATE = """<!DOCTYPE html>
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
  <meta name="keywords" content="高校サッカー,医学コラム,熱中症,脳震盪,救急医,スポーツ医学,コンディショニング">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="__CANONICAL__">

  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="__TITLE__">
  <meta property="og:description" content="__DESCRIPTION__">
  <meta property="og:url" content="__CANONICAL__">
  <meta property="og:image" content="https://u18-soccer.com/og-image.png">
  <meta property="og:locale" content="ja_JP">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:title" content="__TITLE__">
  <meta name="twitter:description" content="__DESCRIPTION__">
  <meta name="twitter:image" content="https://u18-soccer.com/og-image.png">

  <script type="application/ld+json">
__SCHEMA_BREADCRUMB__
  </script>
  <script type="application/ld+json">
__SCHEMA_COLLECTION__
  </script>

  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <meta name="theme-color" content="#1e40af">
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
        <div class="site-title">
          <a href="/" style="color:inherit;text-decoration:none;">
            <i class="fas fa-futbol"></i>
            高校サッカー順位確認システム
          </a>
        </div>
        <nav class="nav">
          <a href="/" class="nav-link"><i class="fas fa-home"></i> ホーム</a>
          <a href="/leagues/" class="nav-link"><i class="fas fa-trophy"></i> リーグ</a>
          <a href="/blog/" class="nav-link"><i class="fas fa-newspaper"></i> ブログ</a>
        </nav>
      </div>
    </div>
  </header>

  <main class="main-content">
    <div class="container" style="max-width:900px;">
      <nav class="breadcrumb" aria-label="パンくずリスト" style="margin:16px 0;font-size:0.88em;">
        <a href="/">ホーム</a>
        <span class="breadcrumb__sep">›</span>
        <a href="/blog/">ブログ</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">医学コラム</span>
      </nav>

      <h1 style="margin:8px 0 12px;"><i class="fas fa-user-md" aria-hidden="true"></i> 救急医の医学コラム</h1>
      <p style="line-height:1.9;margin:0 0 18px;">
        救命救急センターに勤務する救急科専門医が、高校サッカーの選手・保護者・指導者の皆さまに向けて、
        「倒れてから病院で会うのではなく、倒れる前に届く情報を」という思いで書いている連載です（現在 __ARTICLE_COUNT__ 本）。
        すべての記事は公的ガイドライン・医学的根拠に基づき、要点まとめ・目次・FAQ付きで読めます。
      </p>

      <aside style="margin:0 0 24px;padding:18px 20px;background:var(--bg-light,#f8fafc);border:1px solid var(--border-color,#e2e8f0);border-radius:12px;font-size:0.95rem;line-height:1.85;">
        <p style="font-size:0.8rem;font-weight:600;letter-spacing:0.06em;color:var(--primary-color,#1e40af);margin:0 0 6px;"><i class="fas fa-user-md"></i> 執筆者</p>
        <p style="margin:0 0 8px;"><strong>Dr.Kazu Soccer</strong>（日本救急医学会認定 救急科専門医・脳神経外科専門医・医学博士）</p>
        <p style="margin:0 0 10px;">__AUTHOR_BIO__</p>
        <p style="margin:0;">
          <a href="/about.html">運営者情報を見る ›</a>
          <a href="__AUTHOR_X_URL__" target="_blank" rel="noopener">X（@DrKazuSoccer）›</a>
          <a href="__AUTHOR_NOTE_URL__" target="_blank" rel="noopener">note ›</a>
        </p>
      </aside>

      <section class="lp-section" style="background:var(--bg-light,#eff6ff);border-left:4px solid var(--primary-color,#1e40af);border-radius:0 10px 10px 0;padding:16px 20px;">
        <h2 style="margin-top:0;">📖 読む順ガイド</h2>
        <ul style="margin:0;padding-left:1.5em;line-height:2.0;">
          <li><strong>いま（夏の大会期）なら</strong>：熱中症対策 → 水分補給 → 大会当日の暑さ対策 の順で。チーム全員に関わる内容です。</li>
          <li><strong>試合・練習の「もしも」に備えるなら</strong>：脳震盪と心臓振盪は<strong>起きる前に</strong>読んでおくことに意味があります。ベンチに入る大人は必読です。</li>
          <li><strong>「最近走れない・疲れが抜けない」なら</strong>：オーバートレーニング → 貧血 → 睡眠。原因は1つとは限りません。</li>
        </ul>
      </section>

__THEME_SECTIONS__

      <section class="lp-section">
        <h2>ご利用にあたって（免責）</h2>
        <p style="line-height:1.9;">
          本連載は救急科専門医の知識と経験に基づく<strong>一般的な情報提供</strong>であり、個別の診断・治療を目的とするものではありません。
          選手の体調不良やケガは必ず医療機関を受診し、緊急時は迷わず119番へ。当サイトの情報を理由に受診を遅らせないでください。
          詳細は<a href="/about.html">運営者情報</a>の免責事項をご覧ください。
        </p>
      </section>

      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul>
          <li><a href="/blog/">ブログ記事一覧（大会分析・チーム特集も）</a></li>
          <li><a href="/leagues/">リーグ順位表一覧（プレミア・プリンス9地域）</a></li>
          <li><a href="/leagues/premier-east/">プレミアリーグEAST 順位表</a>／<a href="/leagues/premier-west/">プレミアリーグWEST 順位表</a></li>
          <li><a href="/tournaments/interhigh-2026/">インターハイ2026 速報・結果</a></li>
          <li><a href="/about.html">運営者情報・サイトについて</a></li>
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
    generate_rss(articles)

    # 医学コラムハブページ（B-3）
    generate_medical_hub(articles)

    # トップページの新着コラム欄を更新
    update_home_latest_blog(articles)

    # sitemap 更新
    append_sitemap([a["slug"] for a in articles])

    print(f"完了: {len(articles)} 記事 + 1 一覧ページを生成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
