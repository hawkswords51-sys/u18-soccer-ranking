#!/usr/bin/env python3
"""
プロ内定・2種登録選手一覧ページ生成スクリプト
==========================================================
data/pro-signings.yml から /pro-signings/index.html を生成。
現所属チーム別にグループ化し、①プロ内定 ②2種登録 の2セクションで表示。
現所属チームに当サイトの詳細ページがあれば、そのチームページへ直接リンク
（対応付けは pro_signings→national_team の resolve_club、3段階フォールバック）。
sitemap.xml に /pro-signings/ を登録（idempotent）。

依存: pyyaml, （同ディレクトリの pro_signings.py / national_team.py）
反映: 他のmd/JSON編集と同じく Commit→Push→「高円宮杯 順位自動更新」を Run workflow。
"""

import json
import re
from datetime import datetime, timezone, timedelta
from html import escape as html_escape
from pathlib import Path

import pro_signings as ps

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "pro-signings"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"

GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"
DOMAIN = "https://u18-soccer.com"
JST = timezone(timedelta(hours=9))

POS_ORDER = {"GK": 0, "DF": 1, "MF": 2, "FW": 3}


def _team_link(group: dict) -> str:
    """グループ見出しの現所属チーム名（詳細ページがあればリンク）"""
    r = group.get("resolved") or {}
    team = group.get("team", "")
    if r.get("tier") == "team":
        label = html_escape(r.get("label") or team)
        return (f'<a href="{r["url"]}">{label} '
                f'<i class="fas fa-arrow-right" style="font-size:.7em"></i></a>')
    if r.get("tier") == "pref":
        pref = html_escape(r.get("label", "県ページ"))
        return (f'{html_escape(team)} '
                f'<a href="{r["url"]}" style="font-size:.8em;font-weight:400">（{pref}の順位 ›）</a>')
    return html_escape(team)


def _player_rows(players: list, show_dest: bool) -> str:
    ordered = sorted(players, key=lambda p: POS_ORDER.get(p.get("pos"), 9))
    rows = []
    for p in ordered:
        pos = html_escape(p.get("pos", ""))
        name = html_escape(p.get("name", ""))
        chip = ' <span class="ps-2nd">2種登録</span>' if p.get("type2") else ""
        note = f'<span class="ps-note-inline">※{html_escape(p["note"])}</span>' if p.get("note") else ""
        if show_dest:
            dest = html_escape(p.get("dest", ""))
            dest_cell = (f'<td class="ps-dest"><span class="ps-arrow">→</span>'
                         f'<span class="ps-club">{dest}</span> {note}</td>')
        else:
            dest_cell = f'<td class="ps-dest">{note}</td>'
        rows.append(
            "<tr>"
            f'<td class="ps-pos ps-pos-{pos}">{pos}</td>'
            f'<td class="ps-name">{name}{chip}</td>'
            f"{dest_cell}"
            "</tr>"
        )
    return "".join(rows)


def _section(title: str, subtitle: str, players: list, show_dest: bool, empty_msg: str) -> str:
    groups = ps.group_by_team(players)
    if not groups:
        body = f'<p class="ps-empty">{html_escape(empty_msg)}</p>'
    else:
        blocks = []
        for g in groups:
            cat = g["players"][0].get("cat", "")
            cat_badge = f'<span class="ps-cat">{html_escape(cat)}</span>' if cat else ""
            blocks.append(
                '<div class="ps-team">'
                f'<h3 class="ps-team-name">{_team_link(g)} {cat_badge}</h3>'
                '<table class="ps-table"><tbody>'
                f'{_player_rows(g["players"], show_dest)}'
                '</tbody></table></div>'
            )
        body = "".join(blocks)
    return f"""
    <section class="ps-cat-sec">
      <h2>{html_escape(title)}</h2>
      <p class="ps-sub">{subtitle}</p>
      {body}
    </section>"""


def build_ai_summary(data: dict) -> str:
    sign = data.get("signings") or []
    total = len(sign)
    hs = sum(1 for p in sign if p.get("cat") == "高体連")
    yth = total - hs
    season = html_escape(str(data.get("season", "")))
    body = (
        f"このページは、高校・Jクラブユース（U-18年代）から{season}シーズンのJリーグ加入が内定した"
        f"選手計{total}名（高体連{hs}名・Jクラブユース{yth}名）を、現所属チーム別に一覧できるまとめです。"
        f"現所属チームに当サイトの詳細ページがある選手は、そのチームページ（順位・OB情報）へ直接移動できます。"
        f"ユース所属のままトップチームの公式戦に出られる「2種登録選手」には氏名の横に「2種登録」タグを表示します。"
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
            {"@type": "ListItem", "position": 2, "name": "プロ内定・2種登録選手", "item": f"{DOMAIN}/pro-signings/"},
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
  <meta name="keywords" content="プロ内定,Jリーグ内定,加入内定,2種登録,高校サッカー,ユース,トップ昇格,__SEASON__">
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
    .ps-jump{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 22px;}
    .ps-jump a{background:var(--bg-white);border:1px solid var(--border-color);border-radius:999px;padding:8px 16px;text-decoration:none;color:var(--primary-color);font-weight:700;font-size:.9rem;box-shadow:var(--shadow);}
    .ps-cat-sec{background:var(--bg-white);border-radius:12px;padding:24px;box-shadow:var(--shadow);margin:0 0 24px;}
    .ps-cat-sec h2{font-size:1.3rem;color:var(--primary-color);border-bottom:3px solid var(--primary-color);padding-bottom:8px;margin:0 0 6px;}
    .ps-sub{margin:0 0 16px;font-size:.85rem;color:var(--text-light);line-height:1.7;}
    .ps-team{margin:0 0 16px;border:1px solid var(--border-color);border-radius:10px;overflow:hidden;}
    .ps-team-name{font-size:1.02rem;margin:0;padding:10px 14px;background:var(--bg-light);color:var(--text-dark);font-weight:700;display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
    .ps-team-name a{color:var(--primary-color);text-decoration:underline;}
    .ps-cat{font-size:.72rem;font-weight:700;color:#fff;background:#64748b;border-radius:999px;padding:2px 10px;}
    .ps-table{width:100%;border-collapse:collapse;font-size:.92rem;}
    .ps-table td{border-top:1px solid var(--border-color);padding:9px 12px;vertical-align:middle;}
    .ps-pos{width:48px;text-align:center;font-weight:700;color:#fff;}
    .ps-pos-GK{background:#6b7280;}.ps-pos-DF{background:#2563eb;}.ps-pos-MF{background:#059669;}.ps-pos-FW{background:#dc2626;}
    .ps-name{font-weight:600;white-space:nowrap;}
    .ps-dest{color:var(--text-dark);}
    .ps-arrow{color:var(--text-light);margin-right:4px;}
    .ps-club{font-weight:700;color:#15803d;}
    .ps-note-inline{display:inline-block;font-size:.78rem;color:var(--text-light);margin-left:6px;}
    .ps-2nd{display:inline-block;font-size:.7rem;font-weight:700;color:#fff;background:#16a34a;border-radius:999px;padding:2px 8px;margin-left:6px;vertical-align:middle;}
    .ps-empty{margin:0;padding:16px;background:var(--bg-light);border-radius:8px;color:var(--text-light);font-size:.9rem;line-height:1.8;}
    .ps-source{margin:6px 0 0;font-size:.8rem;color:var(--text-light);}
    .ps-source a{color:var(--text-light);}
    @media(max-width:768px){.team-hero h1{font-size:1.25rem;}.ps-cat-sec{padding:16px 14px;}.ps-table{font-size:.85rem;}.ps-table td{padding:7px 8px;}.ps-name{white-space:normal;}}
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
    <nav class="breadcrumb"><a href="/">ホーム</a><span class="breadcrumb__sep">›</span><span>プロ内定選手</span></nav>
    <section class="team-hero">
      <h1>__SEASON__年 Jリーグ プロ内定選手一覧（高校・ユース）</h1>
      __AI_SUMMARY__
      <p class="team-lead">高校・Jクラブユースから来季Jリーグ加入が内定した選手を、現所属チーム別に掲載。所属チームに当サイトの詳細ページがある選手は、そのチームページへ直接移動できます。ユース所属のままトップの公式戦に出られる「2種登録」の選手には氏名の横にタグを表示します。</p>
    </section>
    __SECTIONS__
    <section class="ps-cat-sec">
      <h2><i class="fas fa-circle-info"></i> 「プロ内定」と「2種登録」の仕組み</h2>
      <p style="line-height:1.9;margin:0 0 12px;">
        <strong>プロ内定</strong>とは、高校やJクラブユースに在籍したまま、翌シーズンからのJリーグクラブ加入がクラブから公式に発表されることです。発表は夏頃から始まり、秋から冬（選手権の前後）にかけて増えていきます。ルートは大きく2つあり、Jクラブユースの選手はそのまま下部組織からトップチームへ上がる「トップ昇格」、高校（高体連）の選手は他クラブへの「加入内定」が中心です。内訳は年によって変わりますが、近年はクラブユースからのトップ昇格が多数を占める傾向にあります。高体連の内定選手にとっては、冬の<a href="/tournaments/senshuken-2026/">全国高校サッカー選手権</a>が「プロ入り前の集大成」となることが多く、内定発表後のプレーにも注目が集まります。
      </p>
      <p style="line-height:1.9;margin:0 0 12px;">
        <strong>2種登録</strong>とは、JFAの選手登録制度で高校年代にあたる「第2種」の選手を、Jクラブがトップチームにも登録する仕組みです。登録された選手は、ユースや高校に所属したままJリーグやカップ戦などトップチームの公式戦に出場できます。加入内定済みの有望選手が、ひと足早くプロの舞台を経験するために活用されることが多い制度です。当ページでは、各クラブ公式の「2種登録完了のお知らせ」等で確認できた選手にだけ、氏名の横に緑の「2種登録」タグを表示しています（憶測では付けません）。
      </p>
      <p style="line-height:1.9;margin:0;">
        内定選手には年代別の<a href="/national-team/">日本代表に選出されている選手</a>も多く含まれます。所属チームのリンクからは当サイトのチーム詳細ページ（最新順位・チームの歩み・OB選手）に移動できるので、「この選手のチームは今リーグで何位か」を<a href="/leagues/">プレミアリーグ・プリンスリーグの順位表</a>とあわせて追いかけるのがおすすめです。内定・2種登録が在籍するチームの詳細ページには緑の「プロ内定・2種登録」バッジを表示しています。
      </p>
    </section>
    <section class="ps-cat-sec">
      <h2><i class="fas fa-book-open"></i> あわせて読みたい特集</h2>
      <ul style="list-style:none;margin:0;padding:0;display:grid;gap:8px;">
        <li><a href="/blog/posts/worldcup-2026-japan-roots/" style="display:block;padding:10px 14px;background:var(--bg-light,#f8f9fa);border:1px solid var(--border-color,#e0e0e0);border-radius:10px;text-decoration:none;color:var(--text-dark,#1a1a1a);line-height:1.6;"><strong>【2026W杯】日本代表26人は"どこから"来たのか｜全員の出身高校・ユース完全ガイド</strong><br><span style="font-size:.85em;color:var(--text-light,#666);">プロ内定のその先──W杯代表26人の出身高校・ユースを全員分たどると、高体連とクラブユース双方からの道筋が見えてきます。</span></a></li>
        <li><a href="/blog/posts/2026-07-11-japan-world-youth-development/" style="display:block;padding:10px 14px;background:var(--bg-light,#f8f9fa);border:1px solid var(--border-color,#e0e0e0);border-radius:10px;text-decoration:none;color:var(--text-dark,#1a1a1a);line-height:1.6;"><strong>W杯開催中に考える、日本と世界の育成の違い</strong><br><span style="font-size:.85em;color:var(--text-light,#666);">強豪国の育成システムと比較しながら、日本の「分厚さ」がプロへの道にどう効いているかを解説します。</span></a></li>
      </ul>
    </section>
    <p class="ps-source">
      出典：<a href="__SOURCE_HUB__" rel="nofollow noopener" target="_blank">高校サッカードットコム「__SEASON__年 高校年代・Jリーグ内定者一覧」</a>ほか各クラブ公式発表（__SOURCE_ASOF__時点の発表分を反映）。
    </p>
    <p style="font-size:.82rem;color:var(--text-light);margin:8px 0 30px;line-height:1.8">
      ※選手名・所属・内定先はクラブ公式発表に準拠。学年はJFA非公表のため個別には記載していません。加入内定・2種登録は随時発表され、本ページも順次更新します（最終更新：__UPDATED__）。
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
    content = re.sub(r'\s*<url>\s*<loc>[^<]*?/pro-signings/</loc>.*?</url>', '', content, flags=re.DOTALL)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    entry = (f"  <url>\n    <loc>{DOMAIN}/pro-signings/</loc>\n    <lastmod>{today}</lastmod>\n"
             f"    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>\n")
    content = content.replace("</urlset>", entry + "</urlset>")
    SITEMAP_FILE.write_text(content, encoding="utf-8")
    print("  → sitemap.xml に /pro-signings/ を登録")


def main() -> int:
    data = ps.load_signings(BASE_DIR)
    if not data.get("signings"):
        print("[pro-signings] データが無いのでスキップ")
        return 0

    season = str(data.get("season", ""))
    title = f"{season}年 Jリーグ プロ内定選手一覧【高校・ユース】｜所属チーム別・2種登録"
    desc = (f"高校・Jクラブユースから{season}シーズンのJリーグ加入が内定した選手を現所属チーム別に一覧。"
            f"2種登録の選手にはタグを表示。所属チームの詳細ページ（順位・OB）へも移動できます。クラブ公式発表に準拠。")

    # 内定選手（現所属チーム別）。2種登録は各選手の type2 タグで表示（専用セクションは設けない）。
    sections = _section(
        "プロ内定選手", f"{season}シーズンのJリーグ加入が内定した高校・ユース年代の選手（現所属チーム別）。"
        "ユース所属のままトップに出られる「2種登録」の選手には氏名の横にタグを表示します。",
        data.get("signings") or [], show_dest=True,
        empty_msg="現在、掲載できる内定選手はありません。")

    html = (TEMPLATE
            .replace("__GA__", GA_ID).replace("__AD__", ADSENSE_CLIENT).replace("__DOMAIN__", DOMAIN)
            .replace("__TITLE__", html_escape(title)).replace("__DESC__", html_escape(desc))
            .replace("__CANON__", f"{DOMAIN}/pro-signings/")
            .replace("__SCHEMA__", build_schema(data))
            .replace("__AI_SUMMARY__", build_ai_summary(data))
            .replace("__SECTIONS__", sections)
            .replace("__SEASON__", html_escape(season))
            .replace("__SOURCE_HUB__", html_escape(str(data.get("source_hub", ""))))
            .replace("__SOURCE_ASOF__", html_escape(str(data.get("source_asof", ""))))
            .replace("__UPDATED__", html_escape(str(data.get("updated", "")))))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"  [OK] /pro-signings/ を生成（内定{len(data.get('signings') or [])}名・"
          f"2種{len(data.get('second_category') or [])}名）")
    update_sitemap()
    return 0


if __name__ == "__main__":
    exit(main())
