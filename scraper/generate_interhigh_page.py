#!/usr/bin/env python3
"""
インターハイ本選（全国大会）専用ページ生成スクリプト
====================================================
data/tournaments/interhigh-final-2026.md を読み込み、
独立ページ /tournaments/interhigh-2026/ を生成する。

- 「各県代表」セクション：県名: 学校名 を一覧化（学校はチーム詳細へ自動リンク）
- 「トーナメント」セクション：予選と同じ書式の試合行を描画し、スコアから勝者を自動ハイライト
- まだ組み合わせ未定でも「準備中」表示で正しく出力される

依存：標準ライブラリ + PyYAML
"""
import re
import yaml
from pathlib import Path
from datetime import date

BASE_DIR = Path(__file__).parent.parent
DOMAIN = "https://u18-soccer.com"
GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"

SOURCE = BASE_DIR / "data" / "tournaments" / "interhigh-final-2026.md"
OUT_DIR = BASE_DIR / "tournaments" / "interhigh-2026"
CANONICAL = f"{DOMAIN}/tournaments/interhigh-2026/"

# ---- チーム詳細リンク用マップ ----
def load_team_profile_map() -> dict:
    profiles_dir = BASE_DIR / "data" / "team-profiles"
    team_map = {}
    if not profiles_dir.exists():
        return team_map
    for md in profiles_dir.glob("*.md"):
        try:
            c = md.read_text(encoding="utf-8")
            if not c.startswith("---"):
                continue
            parts = c.split("---", 2)
            if len(parts) < 3:
                continue
            meta = yaml.safe_load(parts[1]) or {}
            tid, tname = meta.get("id"), meta.get("name")
            if tid and tname:
                team_map[tname] = tid
                sn = meta.get("short_name")
                if sn and sn != tname:
                    team_map[sn] = tid
        except Exception:
            pass
    return team_map

TEAM_MAP = load_team_profile_map()

def html_escape(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def format_team_name(name):
    if not name:
        return "—"
    esc = html_escape(name)
    for token in sorted(["U-18","U-15","F.C.","U18","U15","2nd","3rd","ユース"], key=len, reverse=True):
        et = html_escape(token)
        esc = esc.replace(et, f'<span class="nb">{et}</span>')
    return esc

def team_link(name):
    """チーム詳細ページがあればリンク。無ければ整形のみ。"""
    name = name.strip()
    tid = TEAM_MAP.get(name)
    formatted = format_team_name(name)
    if tid:
        return f'<a href="/teams/{tid}/" class="team-profile-link">{formatted}</a>'
    return formatted

def detect_winner_and_wrap(s):
    """ "A 3-1 B" / "A 0-1 B" / "A 2-2(PK4-2) B" の勝者を <span class="match-winner"> で強調。
        "A vs B"（試合前）はそのまま。"""
    pk = re.search(r'(\d+)\s*-\s*(\d+)\s*\(\s*PK\s*(\d+)\s*-\s*(\d+)\s*\)', s)
    if pk:
        ss, se = pk.start(), pk.end()
        l, r = int(pk.group(3)), int(pk.group(4))
    else:
        m = re.search(r'(\d+)\s*-\s*(\d+)', s)
        if not m:
            return None  # スコアなし＝未実施
        ss, se = m.start(), m.end()
        l, r = int(m.group(1)), int(m.group(2))
    if l == r:
        return s
    left, center, right = s[:ss], s[ss:se], s[se:]
    if l > r:
        st = left.rstrip(); tw = left[len(st):]
        return f'<span class="match-winner">{st}</span>{tw}{center}{right}'
    else:
        st = right.lstrip(); lw = right[:len(right)-len(st)]
        return f'{left}{center}{lw}<span class="match-winner">{st}</span>'

def linkify_match(match_str):
    """試合行のチーム名をリンク化しつつ勝者強調。
       'A 3-1 B' 形式を分解してチーム名だけリンク化する。"""
    m = re.match(r'^(.*?)(\s*\d+\s*-\s*\d+(?:\s*\(\s*PK\s*\d+\s*-\s*\d+\s*\))?\s*|\s+vs\s+)(.*)$', match_str)
    if not m:
        return html_escape(match_str)
    a, mid, b = m.group(1).strip(), m.group(2), m.group(3).strip()
    a_html, b_html = team_link(a), team_link(b)
    if "vs" in mid:
        return f'{a_html} <span style="color:#888;">vs</span> {b_html}'
    score = mid.strip()
    rebuilt = f'{a_html} <strong style="color:var(--accent-color,#2563eb);">{html_escape(score)}</strong> {b_html}'
    # 勝者強調：プレーンテキストで勝敗判定し、勝った側のhtmlをラップ
    pk = re.search(r'\(\s*PK\s*(\d+)\s*-\s*(\d+)\s*\)', score)
    if pk:
        lwin = int(pk.group(1)) > int(pk.group(2))
        rwin = int(pk.group(2)) > int(pk.group(1))
    else:
        sm = re.search(r'(\d+)\s*-\s*(\d+)', score)
        lwin = int(sm.group(1)) > int(sm.group(2))
        rwin = int(sm.group(2)) > int(sm.group(1))
    if lwin:
        a_html = f'<span class="match-winner">{a_html}</span>'
    elif rwin:
        b_html = f'<span class="match-winner">{b_html}</span>'
    return f'{a_html} <strong style="color:var(--accent-color,#2563eb);">{html_escape(score)}</strong> {b_html}'

def parse_source():
    text = SOURCE.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    # コメント除去
    body_nocomment = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    # セクション分割（## 見出し）
    sections = {}
    cur = None
    for line in body_nocomment.splitlines():
        h = re.match(r'^##\s+(.*)$', line)
        if h:
            cur = h.group(1).strip()
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(line)
    return meta, sections

def render_reps(lines):
    items = []
    school_count = 0
    for ln in lines:
        m = re.match(r'^\s*-\s*([^:：]+)[:：]\s*(.+)$', ln)
        if not m:
            continue
        pref = m.group(1).strip()
        schools_raw = m.group(2).strip()
        rendered = []
        for token in re.split(r'[、,]', schools_raw):
            token = token.strip()
            if not token:
                continue
            # 末尾の（記録）または(記録)を分離
            rm = re.search(r'[（(]([^）)]*)[）)]\s*$', token)
            if rm:
                name = token[:rm.start()].strip()
                record = rm.group(1).strip()
            else:
                name, record = token, ""
            if not name:
                continue
            badge = (f'<span style="font-size:0.82em;color:var(--text-secondary,#6b7280);">（{html_escape(record)}）</span>' if record else "")
            # 学校名は途中で折り返さない（nowrap）。記録バッジは別要素で必要時のみ改行。
            rendered.append(f'<span style="white-space:nowrap;font-weight:600;">{team_link(name)}</span>{badge}')
            school_count += 1
        if not rendered:
            continue
        items.append(
            '<div style="padding:10px 4px;border-bottom:1px solid var(--border-color,#e5e7eb);">'
            f'<div style="color:var(--text-secondary,#6b7280);font-size:0.82em;margin-bottom:2px;">{html_escape(pref)}</div>'
            f'<div style="line-height:1.6;">{"、".join(rendered)}</div>'
            '</div>'
        )
    if not items:
        return '<p style="color:var(--text-secondary,#6b7280);">各県予選の終了後、代表校を順次掲載します。</p>'
    # 画面幅に応じて自動で1〜2カラム（モバイル=1列、PC=2列）。multi-columnの途中改行を回避。
    return ('<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:0 28px;">'
            + "\n".join(items) + '</div>'
            + f'<p style="margin-top:10px;color:var(--text-secondary,#6b7280);font-size:0.9em;">出場校 {school_count} 校</p>')

def render_rounds(sections):
    blocks = []
    for name, lines in sections.items():
        if name.startswith("各県代表") or name.startswith("トーナメント"):
            continue
        # ラウンド見出し（## 1回戦（8/1） 等）のみ対象
        matches = [ln for ln in lines if re.match(r'^\s*-\s+', ln)]
        rows = []
        for ln in matches:
            content = re.sub(r'^\s*-\s+', '', ln).strip()
            rows.append(f'<li style="padding:10px 12px;border-bottom:1px solid var(--border-color,#e5e7eb);font-size:1.05em;">{linkify_match(content)}</li>')
        if rows:
            blocks.append(f'<h3 style="margin-top:24px;color:var(--accent-color,#2563eb);">{html_escape(name)}</h3>'
                          f'<ul style="list-style:none;padding:0;">' + "\n".join(rows) + '</ul>')
    if not blocks:
        return '<p style="color:var(--text-secondary,#6b7280);">組み合わせ抽選後、トーナメント表と試合結果をここに掲載します（決勝まで随時更新）。</p>'
    return "\n".join(blocks)

def main():
    meta, sections = parse_source()
    title_main = meta.get("title", "全国高校総体 サッカー競技")
    year = meta.get("year", date.today().year)
    venue = meta.get("venue", "")
    host = meta.get("host", "")
    period = meta.get("period", "")
    status = meta.get("status", "")
    champion = meta.get("champion") or ""
    slots = meta.get("slots", "")
    fmt = meta.get("format", "")
    schedule = meta.get("schedule") or []
    slots_li = f'<li><strong>出場枠</strong>：{html_escape(slots)}</li>' if slots else ""
    format_li = f'<li><strong>大会方式</strong>：{html_escape(fmt)}</li>' if fmt else ""
    if schedule:
        _items = "\n".join(f'<li style="padding:6px 12px;border-bottom:1px solid var(--border-color,#e5e7eb);">{html_escape(x)}</li>' for x in schedule)
        schedule_html = f'<h3 style="margin-top:16px;">📅 日程</h3><ul style="list-style:none;padding:0;">{_items}</ul>'
    else:
        schedule_html = ""

    seo_title = f"インターハイ サッカー {year} 結果・組み合わせ｜全国高校総体（男子）トーナメント速報"
    description = (f"高校総体（インターハイ）サッカー競技 男子 {year} の全国大会（本選）の組み合わせ・試合結果・"
                  f"各県代表校を速報でまとめています。{html_escape(period)}開催。決勝まで随時更新。")
    keywords = (f"インターハイ サッカー {year},全国高校総体 サッカー,高校総体 サッカー 結果,"
                f"インターハイ サッカー 組み合わせ,インターハイ サッカー 速報,高校サッカー,U-18,{year}")

    # 代表校・ラウンド
    reps_lines = sections.get("各県代表", [])
    # トーナメント見出し名のゆれ吸収
    reps_html = render_reps(reps_lines)
    rounds_html = render_rounds(sections)

    champion_html = ""
    if champion and isinstance(champion, dict) and champion.get("team"):
        champion_html = (f'<div style="text-align:center;padding:16px;margin:16px 0;'
                         f'background:linear-gradient(135deg,#fde68a,#fbbf24);border-radius:10px;'
                         f'font-weight:700;color:#7c2d12;font-size:1.2em;">🏆 全国優勝：{team_link(champion["team"])}</div>')
    elif isinstance(champion, str) and champion.strip():
        champion_html = (f'<div style="text-align:center;padding:16px;margin:16px 0;'
                         f'background:linear-gradient(135deg,#fde68a,#fbbf24);border-radius:10px;'
                         f'font-weight:700;color:#7c2d12;font-size:1.2em;">🏆 全国優勝：{team_link(champion.strip())}</div>')

    status_badge = (f'<span style="display:inline-block;padding:4px 14px;border-radius:999px;'
                    f'background:#dbeafe;color:#1e40af;font-weight:600;font-size:0.9em;">{html_escape(status)}</span>'
                    if status else "")

    breadcrumb_schema = (
        '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":['
        '{"@type":"ListItem","position":1,"name":"ホーム","item":"' + DOMAIN + '/"},'
        '{"@type":"ListItem","position":2,"name":"インターハイ' + str(year) + '","item":"' + CANONICAL + '"}]}'
    )
    
    # --- FAQ と大会構造化データ（SportsEvent / FAQPage） ---
    import json as _json
    faq_items = [
        (f"インターハイ{year}のサッカー競技はいつ開催されますか？",
         f"{period} に開催されます。" if period else "日程は確定後に掲載します。"),
        ("開催地・会場はどこですか？",
         (f"{venue}（{host}）で開催されます。" if host else f"{venue}で開催されます。") if venue else "確定後に掲載します。"),
        ("出場枠・出場校数は？", slots or "各都道府県の予選を勝ち抜いた代表校が出場します。"),
        ("試合方式・試合時間は？", fmt or "ノックアウト方式で行われます。"),
        ("試合結果・組み合わせはどこで確認できますか？",
         "このページで組み合わせ・試合結果を随時更新しています。各都道府県予選の結果は当サイトの都道府県別ページで確認できます。"),
    ]
    faq_schema = _json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in faq_items
        ],
    }, ensure_ascii=False)
    _event = {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        "name": title_main,
        "description": description,
        "url": CANONICAL,
        "sport": "サッカー",
        "eventStatus": "https://schema.org/EventScheduled",
        "organizer": {"@type": "Organization", "name": "公益財団法人全国高等学校体育連盟"},
    }
    if meta.get("start_date"):
        _event["startDate"] = str(meta["start_date"])
    if meta.get("end_date"):
        _event["endDate"] = str(meta["end_date"])
    if venue:
        _event["location"] = {"@type": "Place", "name": venue, "address": host or venue}
    event_schema = _json.dumps(_event, ensure_ascii=False)
    faq_html = "".join(
        '<details style="margin:8px 0;padding:10px 14px;background:var(--bg-white,#fff);'
        'border:1px solid var(--border-color,#e5e7eb);border-radius:8px;">'
        f'<summary style="font-weight:600;cursor:pointer;">{html_escape(q)}</summary>'
        f'<p style="margin:10px 0 4px;line-height:1.8;">{html_escape(a)}</p></details>'
        for q, a in faq_items
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
  <script type="application/ld+json">{event_schema}</script>
  <script type="application/ld+json">{faq_schema}</script>
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
        <span aria-current="page">インターハイ{year}</span>
      </nav>
      <h1 class="lp-title">{html_escape(title_main)}</h1>
      <p class="lp-intro">
        高校総体（<strong>インターハイ</strong>）サッカー競技 男子 {year} の<strong>全国大会（本選）</strong>の
        組み合わせ・試合結果・各県代表校をまとめています。各県予選の結果は
        <a href="/">都道府県別ページ</a>からご確認いただけます。
      </p>
      
      <p style="margin:4px 0 16px;display:flex;flex-wrap:wrap;gap:10px;">
        <a href="/tournaments/interhigh-history/" style="display:inline-block;padding:9px 18px;border-radius:999px;background:var(--primary-color,#1e40af);color:#fff;text-decoration:none;font-weight:600;font-size:0.92em;">🏆 歴代優勝校一覧（2008-2025）</a>
        <a href="/blog/posts/interhigh-2026-heat-safety/" style="display:inline-block;padding:9px 18px;border-radius:999px;background:#dc2626;color:#fff;text-decoration:none;font-weight:600;font-size:0.92em;">🌡️ 救急医の暑熱対策ガイド</a>
      </p>
      
      <section class="lp-section">
        <h2><i class="fas fa-circle-info"></i> 大会概要 {status_badge}</h2>
        <ul style="list-style:none;padding:0;line-height:2;">
          <li><strong>大会名</strong>：{html_escape(title_main)}</li>
          <li><strong>会期</strong>：{html_escape(period) or '日程確定後に掲載'}</li>
          <li><strong>開催地</strong>：{html_escape(venue) or '確定後に掲載'}{(' / ' + html_escape(host)) if host else ''}</li>
          {slots_li}
          {format_li}
        </ul>
        {schedule_html}
        {champion_html}
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-flag"></i> 各県代表</h2>
        {reps_html}
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-sitemap"></i> トーナメント・試合結果</h2>
        {rounds_html}
      </section>
      
      <section class="lp-section">
        <h2><i class="fas fa-circle-question"></i> よくある質問</h2>
        {faq_html}
      </section>
      
      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/">全国47都道府県の高校サッカー順位・予選結果</a></li>
          <li><a href="/leagues/">リーグ一覧（プレミア・プリンス）</a></li>
          <li><a href="/blog/">ブログ・医学コラム</a></li>
          <li><a href="/blog/posts/interhigh-2026-heat-safety/">【医学コラム】真夏のインターハイ暑熱対策ガイド（選手・保護者・指導者向け）</a></li>
          <li><a href="/tournaments/interhigh-history/">インターハイ サッカー男子 歴代優勝校一覧</a></li>
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

    # --- sitemap に登録（idempotent） ---
    sm = BASE_DIR / "sitemap.xml"
    if sm.exists():
        s = sm.read_text(encoding="utf-8")
        if CANONICAL not in s:
            entry = f"  <url>\n    <loc>{CANONICAL}</loc>\n    <lastmod>{date.today().isoformat()}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>\n"
            s = s.replace("</urlset>", entry + "</urlset>")
            sm.write_text(s, encoding="utf-8")
            print("✅ sitemap.xml に登録")
        else:
            print("ℹ️ sitemap.xml は登録済み")

            # --- 歴代優勝校ページも sitemap に登録（idempotent） ---
        history_url = f"{DOMAIN}/tournaments/interhigh-history/"
        s = sm.read_text(encoding="utf-8")
        if history_url not in s:
            entry = f"  <url>\n    <loc>{history_url}</loc>\n    <lastmod>{date.today().isoformat()}</lastmod>\n    <changefreq>monthly</changefreq>\n    <priority>0.6</priority>\n  </url>\n"
            s = s.replace("</urlset>", entry + "</urlset>")
            sm.write_text(s, encoding="utf-8")
            print("✅ sitemap.xml に歴代優勝校ページを登録")

if __name__ == "__main__":
    main()
