#!/usr/bin/env python3
"""
U-15（3種）県リーグ1部ページの生成（2026-09-30 新設・試作7県）
=============================================================
data/u15/pref/u15-{県}-1.json（fetch_u15_pref.py が作る）を読み、/u15/{県}/index.html を作る。
- 順位表（official_standings）＋戦績表（cross_table.render_cross_table_html を match_dir 付きで共用）
- sitemap.xml への登録（何度実行しても重複しない）
分類は「導出」（data を読んでページを書くだけ）なので push 起動でも走らせる。
⚠️ 中学生の選手名は出さない（チーム単位の情報だけ）。
"""
import json
from html import escape as esc
from pathlib import Path
import fetch_status

from cross_table import render_cross_table_html
from generate_u15_page import ADSENSE_CLIENT, DOMAIN, GA_ID, REGION_ORDER, jst_today

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data" / "u15" / "pref"
OUT_ROOT = BASE_DIR / "u15"

# 表示順（北から）。JSON が無い県は飛ばす
# 2026-10-01 第3弾で秋田・長野・石川・愛媛を追加（既存8県の並びは変えず、地域の近くに差し込む）
PREF_ORDER = ["akita", "niigata", "nagano", "ishikawa", "tochigi", "gunma", "kanagawa",
              "shimane", "hiroshima", "ehime", "saga", "nagasaki"]


def _jp_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(m)}月{int(d)}日"


def load_all() -> dict:
    out = {}
    for key in PREF_ORDER:
        p = DATA_DIR / f"u15-{key}-1.json"
        if p.exists():
            out[key] = json.loads(p.read_text(encoding="utf-8"))
    return out


def summary(d: dict) -> dict:
    ms = d["matches"]
    played = [m for m in ms if m.get("status") == "played"]
    last = max((m["date"] for m in played if m.get("date")), default="")
    top = d["official_standings"][0]
    return dict(played=len(played), total=len(ms), last=last, top=top["team"], top_pts=top["points"],
                teams=len(d["teams"]))


def standings_html(d: dict) -> str:
    n = len(d["official_standings"])
    rows = []
    for t in d["official_standings"]:
        gd = t["gd"]
        cls = ' class="u15-top"' if t["rank"] == 1 else (' class="u15-bottom"' if t["rank"] == n else "")
        rows.append(f'<tr{cls}><td class="u15-rank">{t["rank"]}</td><td class="u15-name">{esc(t["team"])}</td>'
                    f'<td>{t["played"]}</td><td>{t["won"]}</td><td>{t["drawn"]}</td><td>{t["lost"]}</td>'
                    f'<td>{t["gf"]}</td><td>{t["ga"]}</td><td>{"+" if gd > 0 else ""}{gd}</td>'
                    f'<td class="u15-pts">{t["points"]}</td></tr>')
    src = d.get("standings_source")
    note = ("※公式の順位表が公開されていないため、全試合の結果から当サイトが計算した順位です"
            "（勝点→得失点差→得点の順）。" if src == "self" else
            # 長野（2026-10-01）：星取表の得点・失点が試合結果と合わない＝勝点だけ一致を確かめ、順位は自前で計算
            "※全試合の結果から当サイトが計算した順位です（勝点→得失点差→得点の順）。"
            "勝点は出典の星取表と一致することを確かめて更新しています。" if src == "self_pts" else
            "※出典の順位表の値です（全試合の結果から計算し直した値と一致したときだけ更新）。")
    return f'''
      <section class="lp-section" id="standings">
        <h2><i class="fas fa-list-ol"></i> 順位表</h2>
        <div class="u15-scroll">
        <table class="u15-table">
          <thead><tr><th>順</th><th>チーム</th><th>試</th><th>勝</th><th>分</th><th>敗</th><th>得</th><th>失</th><th>差</th><th>点</th></tr></thead>
          <tbody>
            {(chr(10) + "            ").join(rows)}
          </tbody>
        </table>
        </div>
        <p class="u15-note">{note}</p>
      </section>'''


def build_page(key: str, d: dict, all_data: dict) -> str:
    slug = f"u15-{key}-1"
    pref = d["prefName"]
    s = summary(d)
    url = f"{DOMAIN}/u15/{key}/"
    title = f"{pref}U-15リーグ1部 順位表・星取表 {d['season']}｜中学生サッカー"
    h1 = f"{pref}U-15リーグ1部 順位表・星取表【{d['season']}】"
    desc = (f"{d['league']}（{s['teams']}チーム・2回戦総当たり）の順位表と戦績表（星取り表）。"
            f"消化{s['played']}／{s['total']}試合、首位は{s['top']}（勝点{s['top_pts']}）。公式サイトの結果を毎朝自動で更新。")
    asof = f"（{_jp_date(s['last'])}まで）" if s["last"] else ""
    region = d["region"]
    region_no = REGION_ORDER.index(region) + 1
    cross = render_cross_table_html(slug, match_dir=DATA_DIR)
    others = "".join(
        f'<li><a href="/u15/{k}/">{esc(v["prefName"])}U-15リーグ1部</a></li>'
        for k, v in all_data.items() if k != key)
    breadcrumb = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
        {"@type": "ListItem", "position": 2, "name": "U-15（中学生年代）", "item": f"{DOMAIN}/u15/"},
        {"@type": "ListItem", "position": 3, "name": f"{pref}1部", "item": url}]}, ensure_ascii=False)
    webpage = json.dumps({"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": url,
                          "description": desc, "inLanguage": "ja", "dateModified": d["lastUpdated"]},
                         ensure_ascii=False)
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
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">
  <link rel="canonical" href="{url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:url" content="{url}">
  <meta property="og:image" content="{DOMAIN}/og-image.png">
  <meta property="og:locale" content="ja_JP">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:title" content="{esc(title)}">
  <meta name="twitter:description" content="{esc(desc)}">
  <meta name="twitter:image" content="{DOMAIN}/og-image.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <meta name="theme-color" content="#1e40af">
  <script type="application/ld+json">{breadcrumb}</script>
  <script type="application/ld+json">{webpage}</script>
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
    .u15-scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    .u15-table {{ width:100%; max-width:640px; border-collapse:collapse; font-size:0.9rem; }}
    .u15-table th, .u15-table td {{ border-bottom:1px solid var(--border-color,#e2e8f0); padding:7px 5px; text-align:center; }}
    .u15-table th {{ font-weight:600; opacity:0.85; white-space:nowrap; }}
    .u15-table .u15-name {{ text-align:left; }}
    .u15-table .u15-rank {{ opacity:0.7; }}
    .u15-table .u15-pts {{ font-weight:700; }}
    .u15-table tr.u15-top .u15-name {{ font-weight:700; }}
    .u15-table tr.u15-top .u15-rank {{ color:#b45309; font-weight:700; opacity:1; }}
    .u15-table tr.u15-bottom {{ opacity:0.78; }}
    [data-theme="dark"] .u15-table tr.u15-top .u15-rank {{ color:#fbbf24; }}
    @media (prefers-color-scheme:dark) {{
      :root:not([data-theme="light"]) .u15-table tr.u15-top .u15-rank {{ color:#fbbf24; }}
    }}
    .u15-note {{ font-size:0.85rem; opacity:0.8; }}
    .u15-lead {{ margin:0 0 20px; padding:14px 18px; background:var(--bg-light,#f1f5fb);
      border-left:4px solid var(--primary-color,#1e40af); border-radius:0 8px 8px 0; font-size:0.97rem; line-height:1.85; }}
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
          <a href="/en/" class="nav-link" lang="en" aria-label="English"><i class="fas fa-globe"></i> English</a>
        </nav>
      </div>
    </div>
  </header>

  <main class="main-content">
    <div class="container">
      <nav class="breadcrumb" aria-label="パンくずリスト">
        <a href="/">ホーム</a>
        <span class="breadcrumb__sep">›</span>
        <a href="/u15/">U-15</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">{esc(pref)}1部</span>
      </nav>

      <h1 class="lp-title">{esc(h1)}</h1>

      <p class="u15-lead">
        <strong>{esc(d["league"])}</strong>の順位表と戦績表（星取り表）です。
        {s["teams"]}チームによる2回戦総当たりで、<strong>消化 {s["played"]}／{s["total"]}試合</strong>{esc(asof)}。
        出典は<a href="{esc(d["source"])}" target="_blank" rel="nofollow noopener">{esc(d["sourceName"])}</a>、
        最終更新は{esc(_jp_date(d["lastUpdated"]))}です。
      </p>
{standings_html(d)}
{cross}

      <section class="lp-section">
        <h2><i class="fas fa-arrow-up"></i> 上の地域リーグ</h2>
        <p style="line-height:1.9;">この県の1部の上には、{esc(region)}のU-15地域リーグがあります。
          → <a href="/u15/#region-{region_no}">{esc(region)}のU-15リーグ順位表</a></p>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-map"></i> ほかの都道府県のU-15リーグ1部</h2>
        <ul style="line-height:2.1;">{others}</ul>
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-circle-info"></i> このページについて</h2>
        <p style="line-height:1.9;">
          公式サイトの結果を毎朝取得し、全試合の結果から計算し直した順位が公式の順位表と一致したときだけ更新しています
          （公式の順位表が無いリーグは、チーム数・対戦の組み合わせが揃っていることを確かめてから当サイトで計算しています）。
          合わないときは更新せず、前回の内容を残します。
        </p>
        <p style="line-height:1.9;">高校年代の{esc(pref)}1部リーグは<a href="/prefectures/{key}/">{esc(pref)}のページ</a>へ。
          U-15年代の地域リーグ・全国大会は<a href="/u15/">U-15ハブ</a>にまとめています。</p>
      </section>
    </div>
  </main>

  <footer class="footer">
    <div class="container">
      <p>&copy; 2025-2026 高校サッカー順位確認システム</p>
      <nav class="footer-nav" style="margin-top:12px;">
        <a href="/about.html">運営者情報</a> ・
        <a href="/privacy.html">プライバシーポリシー</a> ・
        <a href="/contact.html">お問い合わせ</a> ・
        <a href="/en/" lang="en">English</a>
      </nav>
    </div>
  </footer>
  <script src="/js/main.js" defer></script>
</body>
</html>
'''


def register_sitemap(keys) -> None:
    sm = BASE_DIR / "sitemap.xml"
    if not sm.exists():
        print("ℹ️ sitemap.xml が無いのでスキップ")
        return
    s = sm.read_text(encoding="utf-8")
    added = []
    for key in keys:
        u = f"{DOMAIN}/u15/{key}/"
        if f"<loc>{u}</loc>" in s:
            continue
        s = s.replace("</urlset>", f"  <url>\n    <loc>{u}</loc>\n    <lastmod>{jst_today().isoformat()}</lastmod>\n"
                                   f"    <changefreq>daily</changefreq>\n    <priority>0.6</priority>\n  </url>\n</urlset>")
        added.append(key)
    if added:
        sm.write_text(s, encoding="utf-8")
        print(f"✅ sitemap.xml に登録: {', '.join(added)}")


def main() -> None:
    data = load_all()
    if not data:
        print("ℹ️ data/u15/pref/ にJSONが無いのでスキップ")
        return
    for key, d in data.items():
        out = OUT_ROOT / key / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(build_page(key, d, data), encoding="utf-8")
        s = summary(d)
        print(f"✅ /u15/{key}/ を生成（消化{s['played']}／{s['total']}・首位 {s['top']}）")
    register_sitemap(data.keys())


def _run_and_record(job: str = "u15_pref_pages") -> None:
    """main() を走らせ、成否を fetch_status.json の jobs に記録する（2026-10-07追加）。

    ⚠️ ワークフローではこのステップに continue-on-error: true が付いている。
       **外してはいけない**（コミットより前のステップなので、赤くすると U-15 の失敗1つで
       U-18 を含むその日のサイト更新が丸ごと止まる。2026-10-06〜07 に3回連続で実際に起きた）。
       → **握りつぶすが、必ず表に出す。** ここで成否を記録し、コミット・デプロイより
         後にいる audit_pref_freshness.py が赤にする（build_tournaments と同じ形）。
    """
    try:
        main()
    except Exception as e:
        fetch_status.set_job_result(job, type(e).__name__, str(e))
        raise
    fetch_status.set_job_result(job, "ok")


if __name__ == "__main__":
    _run_and_record()
