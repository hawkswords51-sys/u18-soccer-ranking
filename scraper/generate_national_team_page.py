#!/usr/bin/env python3
"""
日本代表（U-16/U-17/U-18）選出選手一覧ページ生成スクリプト
==========================================================
data/national-team-players.yml から /national-team/index.html を生成。
所属チームは national_team.resolve_club で3段階フォールバック（詳細ページ>県ページ>無リンク）。
sitemap.xml に /national-team/ を登録（idempotent）。

依存: pyyaml, （同ディレクトリの national_team.py）
反映: 他のmd/JSON編集と同じく Commit→Push→「高円宮杯 順位自動更新」を Run workflow。
      ※このスクリプトを update_rankings.yml のページ生成ステップに1行足しておけば毎朝自動再生成される。
"""

import json
import re
from datetime import datetime, timezone, timedelta
from html import escape as html_escape
from pathlib import Path

import national_team as nt

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "national-team"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"

GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"
DOMAIN = "https://u18-soccer.com"
JST = timezone(timedelta(hours=9))

POS_ORDER = {"GK": 0, "DF": 1, "MF": 2, "FW": 3}
POS_LABEL = {"GK": "GK", "DF": "DF", "MF": "MF", "FW": "FW"}


def _club_cell(player: dict) -> str:
    """所属セルの表示:
       - origin（出身U-18年代チーム）があれば「現所属 ← 出身チーム(リンク)」
         例）増田大空: ジュビロ磐田 ← 流通経済大学付属柏高校（流経大柏にリンク）
       - それ以外で詳細ページにヒットすればそのチームの正式名（＝U-18表記）でリンク
         （2種登録の選手もU-18側の所属名で表示・リンクされる。例 北原槙→FC東京U-18）
       - 県ページのみヒット＝JFA表記＋県ページ誘導 ／ どれも無ければテキストのみ"""
    r = player.get("_resolved") or {}
    club = html_escape(player.get("club", ""))
    origin = player.get("origin")

    def _linkify(res: dict, fallback_text: str) -> str:
        if res.get("tier") == "team":
            label = html_escape(res.get("label") or fallback_text)
            return f'<a href="{res["url"]}">{label} <i class="fas fa-arrow-right" style="font-size:.7em"></i></a>'
        if res.get("tier") == "pref":
            pref = html_escape(res.get("label", "県ページ"))
            return f'{html_escape(fallback_text)} <a href="{res["url"]}" style="font-size:.85em">（{pref}の順位 ›）</a>'
        return html_escape(fallback_text)

    if origin:
        # 「現所属」と「出身U-18チーム」を1セル内で2段に分けて表示（矢印の二重表示を避ける）
        # 例）ジュビロ磐田 / 出身: 流通経済大学付属柏高校 ›
        if r.get("tier") == "team":
            link = f'<a href="{r["url"]}">{html_escape(r.get("label") or origin)} ›</a>'
        elif r.get("tier") == "pref":
            link = f'<a href="{r["url"]}">{html_escape(origin)} ›</a>'
        else:
            link = html_escape(origin)
        return (
            f'{club}'
            f'<span style="display:block;font-size:.85em;color:var(--text-light);margin-top:2px">'
            f'出身: {link}</span>'
        )
    # origin の無い選手＝ユース年代所属。JFAがトップ名で登録していても表示はU-18名にそろえる
    # （例: RB大宮アルディージャ → RB大宮アルディージャU18。県ページ扱いでもU-18表記で出す）
    return _linkify(r, nt.canonical_club(player.get("club", "")))


def _category_section(cat: dict) -> str:
    players = sorted(cat.get("players", []), key=lambda p: (POS_ORDER.get(p.get("pos"), 9), p.get("no", 99)))
    rows = []
    for p in players:
        rows.append(
            "<tr>"
            f'<td class="nt-no">{html_escape(str(p.get("no","")))}</td>'
            f'<td class="nt-pos nt-pos-{html_escape(p.get("pos",""))}">{POS_LABEL.get(p.get("pos"),"")}</td>'
            f'<td class="nt-name">{html_escape(p.get("name",""))}</td>'
            f'<td class="nt-club">{_club_cell(p)}</td>'
            "</tr>"
        )
    linked = sum(1 for p in players if (p.get("_resolved") or {}).get("tier"))
    note = f'<p class="nt-note">{html_escape(cat["note"])}</p>' if cat.get("note") else ""
    return f"""
    <section class="nt-cat" id="{html_escape(cat.get('code',''))}">
      <h2>{html_escape(cat.get('label',''))}</h2>
      <p class="nt-meta">
        <span class="nt-event">{html_escape(cat.get('event',''))}</span>
        <span class="nt-period">{html_escape(cat.get('period',''))}</span>
        <span class="nt-age">{html_escape(cat.get('age_note',''))}</span>
      </p>
      <table class="nt-table">
        <thead><tr><th>背番号</th><th>Pos</th><th>氏名</th><th>所属チーム</th></tr></thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
      {note}
      <p class="nt-source">出典：<a href="{html_escape(cat.get('source',''))}" rel="nofollow noopener" target="_blank">JFA公式 招集メンバー</a>（{html_escape(cat.get('label',''))}）</p>
    </section>"""


def build_ai_summary(data: dict) -> str:
    cats = data.get("categories", [])
    total = sum(len(c.get("players", [])) for c in cats)
    labels = "・".join(c.get("label", "").replace("日本代表", "") for c in cats)
    linked = 0
    for c in cats:
        for p in c.get("players", []):
            if (p.get("_resolved") or {}).get("tier") == "team":
                linked += 1
    body = (
        f"このページは、サッカー{labels}日本代表に選出された高校生・ユース年代の選手計{total}名を、"
        f"ポジション・背番号・所属チームつきで一覧できるまとめです。"
        f"所属チームのうち当サイトに詳細ページがある{linked}名はチームページへ直接リンクしています。"
    )
    style = (
        "margin:0 0 14px;padding:12px 16px;background:rgba(255,255,255,0.95);"
        "color:#16264a;border-left:4px solid #1e40af;border-radius:0 8px 8px 0;"
        "font-size:0.95rem;line-height:1.8;"
    )
    return f'<p class="lp-lead-summary" style="{style}">{body}</p>'


def build_schema(data: dict) -> str:
    bc = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "日本代表選出選手", "item": f"{DOMAIN}/national-team/"},
        ],
    }
    return json.dumps(bc, ensure_ascii=False, indent=2)


TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <script async src="https://www.googletagmanager.com/gtag/js?id=__GA__"></script>
  <script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','__GA__');</script>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=__AD__" crossorigin="anonymous"></script>
  <meta name="google-adsense-account" content="__AD__">
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__TITLE__</title>
  <meta name="description" content="__DESC__">
  <meta name="keywords" content="U-16日本代表,U-17日本代表,U-18日本代表,メンバー,招集,高校サッカー,ユース,所属チーム">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="__CANON__">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="__TITLE__">
  <meta property="og:description" content="__DESC__">
  <meta property="og:url" content="__CANON__">
  <meta property="og:image" content="__DOMAIN__/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:locale" content="ja_JP">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:title" content="__TITLE__">
  <meta name="twitter:description" content="__DESC__">
  <meta name="twitter:image" content="__DOMAIN__/og-image.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <meta name="theme-color" content="#1e40af">
  <script type="application/ld+json">
__SCHEMA__
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/css/style.css">
  <script>(function(){try{var t=localStorage.getItem('theme');if(t==='dark'||t==='light'){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();</script>
  <style>
    .team-hero{background:linear-gradient(135deg,var(--primary-color),#004999);color:#fff;padding:28px 24px;border-radius:12px;margin:16px 0 24px;box-shadow:var(--shadow);}
    .team-hero h1{font-size:1.6rem;color:#fff;margin:0 0 10px;line-height:1.4;font-weight:700;}
    .team-hero p.team-lead{margin:0;opacity:.95;line-height:1.7;font-size:.95rem;}
    .nt-jump{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 22px;}
    .nt-jump a{background:var(--bg-white);border:1px solid var(--border-color);border-radius:999px;padding:8px 16px;text-decoration:none;color:var(--primary-color);font-weight:700;font-size:.9rem;box-shadow:var(--shadow);}
    .nt-cat{background:var(--bg-white);border-radius:12px;padding:24px;box-shadow:var(--shadow);margin:0 0 24px;}
    .nt-cat h2{font-size:1.3rem;color:var(--primary-color);border-bottom:3px solid var(--primary-color);padding-bottom:8px;margin:0 0 10px;}
    .nt-meta{display:flex;flex-wrap:wrap;gap:8px 14px;margin:0 0 14px;font-size:.85rem;color:var(--text-light);}
    .nt-meta .nt-event{font-weight:700;color:var(--text-dark);}
    .nt-table{width:100%;border-collapse:collapse;font-size:.9rem;}
    .nt-table th{background:var(--primary-color);color:#fff;padding:8px 10px;text-align:left;font-weight:600;}
    .nt-table td{border-bottom:1px solid var(--border-color);padding:8px 10px;vertical-align:middle;}
    .nt-no{width:56px;text-align:center;color:var(--text-light);}
    .nt-pos{width:52px;text-align:center;font-weight:700;color:#fff;border-radius:6px;}
    .nt-pos-GK{background:#6b7280;}.nt-pos-DF{background:#2563eb;}.nt-pos-MF{background:#059669;}.nt-pos-FW{background:#dc2626;}
    .nt-name{font-weight:600;white-space:nowrap;}
    .nt-club a{color:var(--primary-color);text-decoration:underline;}
    .nt-note{margin:12px 0 0;font-size:.82rem;color:var(--text-light);background:var(--bg-light);padding:10px 12px;border-radius:8px;}
    .nt-source{margin:8px 0 0;font-size:.8rem;color:var(--text-light);}
    .nt-source a{color:var(--text-light);}
    @media(max-width:768px){.team-hero h1{font-size:1.25rem;}.nt-cat{padding:16px 14px;}.nt-table{font-size:.82rem;}.nt-table td,.nt-table th{padding:6px 6px;}.nt-name{white-space:normal;}}
  </style>
</head>
<body>
  <header class="header"><div class="container"><div class="header-content">
    <div class="site-title"><a href="/" style="color:#fff;text-decoration:none;display:inline-flex;align-items:center;gap:10px"><i class="fas fa-futbol"></i> 高校サッカー順位確認システム</a></div>
    <nav class="nav">
      <a href="/" class="nav-link"><i class="fas fa-home"></i> ホーム</a>
      <a href="/leagues/" class="nav-link"><i class="fas fa-trophy"></i> リーグ</a>
      <a href="/blog/" class="nav-link"><i class="fas fa-newspaper"></i> ブログ</a>
      <button class="theme-toggle" id="themeToggleBtn" aria-label="ダークモード切替" title="ダークモード切替"><i class="fas fa-moon" id="themeToggleIcon"></i></button>
    </nav>
  </div></div></header>
  <main class="container">
    <nav class="breadcrumb"><a href="/">ホーム</a><span class="breadcrumb__sep">›</span><span>日本代表選出選手</span></nav>
    <section class="team-hero">
      <h1>U-16・U-17・U-18 日本代表 選出選手一覧</h1>
      __AI_SUMMARY__
      <p class="team-lead">JFA公式発表の最新招集メンバーを、ポジション・背番号・所属チームつきで掲載。所属チームに当サイトの詳細ページがある選手は、そのチームページへ直接移動できます。</p>
    </section>
    <div class="nt-jump">__JUMP__</div>
    __SECTIONS__
    <section class="nt-cat">
      <h2><i class="fas fa-circle-info"></i> 年代別日本代表の仕組みと、このページの見方</h2>
      <p style="line-height:1.9;margin:0 0 12px;">
        U-16・U-17・U-18日本代表は、日本サッカー協会（JFA）が編成する年代別の代表チームです。フル代表と違って固定のメンバーは存在せず、国際大会・海外遠征・国内合宿といった活動ごとに招集メンバーが発表され、そのたびに顔ぶれが入れ替わります。つまりこのページの一覧は「最新の活動で招集された選手」であり、今回名前がない選手が次の招集で選ばれることも珍しくありません。年代はおおむね U-18＝高校3年生相当・U-17＝高校2年生相当・U-16＝高校1年生相当です（学年はJFA非公表のため個別には記載していません）。
      </p>
      <p style="line-height:1.9;margin:0 0 12px;">
        招集されるのは、高校の部活動（高体連）とJクラブのユースチームの両方の選手です。所属チーム欄のリンクは当サイトのチーム詳細ページ（最新順位・チームの歩み・OB選手）につながっており、「現所属 <span style="color:var(--text-light)">←</span> 出身チーム」と表記している選手は、U-18年代のチームを離れてプロや大学でプレーしながら招集されているケースです。また、代表クラスの選手は翌シーズンのJリーグ加入内定や2種登録（ユース所属のままトップチームの公式戦に出られる制度）が発表されることも多く、その一覧は<a href="/pro-signings/">プロ内定・2種登録選手ページ</a>にまとめています。
      </p>
      <p style="line-height:1.9;margin:0;">
        このページの楽しみ方としておすすめなのが、代表選手の所属チームを<a href="/leagues/">プレミアリーグ・プリンスリーグの順位表</a>と重ねて見ることです。代表選手を複数抱えるチームがリーグでどう戦っているか、逆に県リーグから招集された選手は誰か──といった見方をすると、日本の育成年代の全体像が立体的に見えてきます。当サイトでは、代表選出選手が在籍するチームの詳細ページに金色の「日本代表選出選手」バッジを表示しています。
      </p>
    </section>
    <p style="font-size:.82rem;color:var(--text-light);margin:8px 0 30px;line-height:1.8">
      ※選手名・所属はJFA公式発表に準拠。学年はJFA非公表のため、各カテゴリの年代の目安を見出しに記載しています。招集は大会・合宿ごとに入れ替わります（最終更新：__UPDATED__）。
    </p>
  </main>
  <footer class="footer"><div class="container">
    <p>&copy; 2025-2026 高校サッカー順位確認システム</p>
    <nav class="footer-nav" style="margin-top:12px;"><a href="/about.html">運営者情報</a> ・ <a href="/privacy.html">プライバシーポリシー</a> ・ <a href="/contact.html">お問い合わせ</a></nav>
    <p class="footer-note" style="margin-top:10px;"><i class="fas fa-database"></i> 順位データは毎日自動更新 ・ X: <a href="https://x.com/DrKazuSoccer" style="color:#93c5fd;">@DrKazuSoccer</a></p>
  </div></footer>
  <script>
    (function(){var b=document.getElementById('themeToggleBtn'),i=document.getElementById('themeToggleIcon');if(!b||!i)return;
    function cur(){var a=document.documentElement.getAttribute('data-theme');if(a==='dark'||a==='light')return a;return(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';}
    function upd(){i.className=(cur()==='dark')?'fas fa-sun':'fas fa-moon';}
    b.addEventListener('click',function(){var n=(cur()==='dark')?'light':'dark';document.documentElement.setAttribute('data-theme',n);try{localStorage.setItem('theme',n);}catch(e){}upd();});upd();})();
  </script>
</body>
</html>
"""


def update_sitemap():
    if not SITEMAP_FILE.exists():
        print("[WARN] sitemap.xml が無いのでスキップ")
        return
    content = SITEMAP_FILE.read_text(encoding="utf-8")
    content = re.sub(r'\s*<url>\s*<loc>[^<]*?/national-team/</loc>.*?</url>', '', content, flags=re.DOTALL)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    entry = (f"  <url>\n    <loc>{DOMAIN}/national-team/</loc>\n    <lastmod>{today}</lastmod>\n"
             f"    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>\n")
    content = content.replace("</urlset>", entry + "</urlset>")
    SITEMAP_FILE.write_text(content, encoding="utf-8")
    print("  → sitemap.xml に /national-team/ を登録")


def main() -> int:
    data = nt.load_categories(BASE_DIR)
    cats = data.get("categories", [])
    if not cats:
        print("[national-team] データが無いのでスキップ")
        return 0

    title = "U-16・U-17・U-18日本代表 選出選手一覧【2026最新】｜所属チーム・ポジション"
    desc = ("サッカーU-16・U-17・U-18日本代表の最新招集メンバーを、背番号・ポジション・所属チームつきで一覧。"
            "所属チームの詳細ページ（順位・OB）へも移動できます。JFA公式発表に準拠。")
    jump = "".join(f'<a href="#{html_escape(c.get("code",""))}">{html_escape(c.get("label",""))}</a>' for c in cats)
    sections = "".join(_category_section(c) for c in cats)

    html = (TEMPLATE
            .replace("__GA__", GA_ID).replace("__AD__", ADSENSE_CLIENT).replace("__DOMAIN__", DOMAIN)
            .replace("__TITLE__", html_escape(title)).replace("__DESC__", html_escape(desc))
            .replace("__CANON__", f"{DOMAIN}/national-team/")
            .replace("__SCHEMA__", build_schema(data))
            .replace("__AI_SUMMARY__", build_ai_summary(data))
            .replace("__JUMP__", jump)
            .replace("__SECTIONS__", sections)
            .replace("__UPDATED__", html_escape(str(data.get("updated", "")))))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"  [OK] /national-team/ を生成（{sum(len(c.get('players',[])) for c in cats)}名）")
    update_sitemap()
    return 0


if __name__ == "__main__":
    exit(main())
