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
        # 背番号（プロ契約済みの選手のみ）
        num = f'<span class="ps-no">#{html_escape(str(p["num"]))}</span>' if p.get("num") else ""
        note = f'<span class="ps-note-inline">※{html_escape(p["note"])}</span>' if p.get("note") else ""
        if show_dest:
            dest = html_escape(p.get("dest", ""))
            dest_cell = (f'<td class="ps-dest"><span class="ps-arrow">→</span>'
                         f'<span class="ps-club">{dest}</span> {note}</td>')
        else:
            dest_cell = f'<td class="ps-dest">{note}</td>'
        timing = html_escape(str(p.get("timing", "")))
        timing_cell = f'<td class="ps-timing">{timing}</td>' if timing else '<td class="ps-timing"></td>'
        rows.append(
            "<tr>"
            f'<td class="ps-pos ps-pos-{pos}">{pos}</td>'
            f'<td class="ps-name">{name}{num}{chip}</td>'
            f"{dest_cell}"
            f"{timing_cell}"
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
    naitei = [p for p in sign if p.get("status") != "pro"]
    pro = [p for p in sign if p.get("status") == "pro"]
    hs = sum(1 for p in naitei if p.get("cat") == "高体連")
    yth = len(naitei) - hs
    season = html_escape(str(data.get("season", "")))
    body = (
        f"このページは、U-18年代（高校・Jクラブユース）からJリーグへ進む選手を、"
        f"「①これから加入する内定者{len(naitei)}名（高体連{hs}名・Jクラブユース{yth}名）」と"
        f"「②すでにプロ契約を結びトップチームに登録済みの選手{len(pro)}名」に分けて、"
        f"現所属チーム別に一覧できるまとめです。"
        f"近年のJクラブ育成組織では「高校在学中にプロ契約を結び、2種登録でユースにも所属する」形が一般的になり、"
        f"クラブの発表も「加入内定」ではなく「プロ契約締結」で出るため、両者を分けて掲載しています。"
        f"全選手をクラブ公式発表で個別に照合しています。"
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
    .team-hero{background:linear-gradient(135deg,var(--primary-color),var(--primary-deep, #16295f));color:#fff;padding:28px 24px;border-radius:12px;margin:16px 0 24px;box-shadow:var(--shadow);}
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
    .ps-timing{width:132px;text-align:right;white-space:nowrap;font-size:.82rem;color:var(--text-light);}
    .ps-no{display:inline-block;font-size:.72rem;font-weight:700;color:#fff;background:#475569;border-radius:999px;padding:2px 7px;margin-left:6px;vertical-align:middle;}
    .ps-2nd{display:inline-block;font-size:.7rem;font-weight:700;color:#fff;background:#16a34a;border-radius:999px;padding:2px 8px;margin-left:6px;vertical-align:middle;}
    .ps-empty{margin:0;padding:16px;background:var(--bg-light);border-radius:8px;color:var(--text-light);font-size:.9rem;line-height:1.8;}
    .ps-source{margin:6px 0 0;font-size:.8rem;color:var(--text-light);}
    .ps-source a{color:var(--text-light);}
    @media(max-width:768px){.team-hero h1{font-size:1.25rem;}.ps-cat-sec{padding:16px 14px;}.ps-table{font-size:.85rem;}.ps-table td{padding:7px 8px;}.ps-name{white-space:normal;}.ps-timing{width:auto;font-size:.75rem;}}
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
      <h1>__SEASON__年 Jリーグ内定・プロ契約選手一覧（高校・ユース）</h1>
      __AI_SUMMARY__
      <p class="team-lead">U-18年代からJリーグへ進む選手を、<strong>①これから加入する内定者</strong>と<strong>②すでにプロ契約済みの選手</strong>に分けて、現所属チーム別に掲載しています。所属チームに当サイトの詳細ページがある選手は、そのチームページへ直接移動できます。</p>
    </section>
    __SECTIONS__
    <section class="ps-cat-sec">
      <h2><i class="fas fa-circle-info"></i> 「内定」と「プロ契約済み」はどう違うのか</h2>
      <p style="line-height:1.9;margin:0 0 12px;">
        <strong>プロ内定</strong>とは、高校やJクラブユースに在籍したまま、これからのJリーグクラブ加入がクラブから公式に発表されることです。発表は夏頃から始まり、秋から冬（選手権の前後）にかけて増えていきます。ルートは大きく2つあり、Jクラブユースの選手はそのまま下部組織からトップチームへ上がる「トップ昇格」、高校（高体連）の選手は他クラブへの「加入内定」が中心です。高体連の内定選手にとっては、冬の<a href="/tournaments/senshuken-2026/">全国高校サッカー選手権</a>が「プロ入り前の集大成」となることが多く、内定発表後のプレーにも注目が集まります。
      </p>
      <p style="line-height:1.9;margin:0 0 12px;">
        ただし近年、Jクラブの育成組織では<strong>高校在学中にプロ契約を結び、そのままユースにも所属し続ける</strong>形が一般的になりました。この場合クラブの発表は「加入内定のお知らせ」ではなく「<strong>プロ契約締結のお知らせ</strong>」で出ます。契約はその時点から発効するため、<strong>「内定者」ではなく、すでに背番号を持つトップチームの選手</strong>です。当ページで①と②を分けているのはこのためで、両者を同じ表に並べている一覧も多く見られますが、実態はまったく違います。
      </p>
      <p style="line-height:1.9;margin:0 0 12px;">
        この二重の身分を支えているのが<strong>2種登録</strong>です。JFAの選手登録制度で高校年代にあたる「第2種」の選手を、Jクラブがトップチームにも登録する仕組みで、登録された選手はユースや高校に所属したままJリーグやカップ戦などトップチームの公式戦に出場できます。プロ契約を結んだ選手が高校卒業までユースの試合にも出続けられるのは、この制度があるからです。当ページでは、各クラブ公式の「2種登録完了のお知らせ」等で確認できた選手にだけ、氏名の横に緑の「2種登録」タグを表示しています（憶測では付けません）。<strong>2種登録はシーズン前後にクラブが一括発表する運用のため、当ページの掲載は網羅的ではありません</strong>。
      </p>
      <p style="line-height:1.9;margin:0 0 12px;">
        加入時期の表記がクラブごとにバラバラなのは、Jリーグが2026/27シーズンから<strong>秋春制</strong>に移行したためです。「2026/27シーズンより」「2027年1月より」「2027年2月より」という3通りの言い回しが混在しており、当ページでは統一せず<strong>各クラブ公式の表現をそのまま</strong>載せています。
      </p>
      <p style="line-height:1.9;margin:0;">
        内定・プロ契約選手には年代別の<a href="/national-team/">日本代表に選出されている選手</a>も多く含まれます。所属チームのリンクからは当サイトのチーム詳細ページ（最新順位・チームの歩み・OB選手）に移動できるので、「この選手のチームは今リーグで何位か」を<a href="/leagues/">プレミアリーグ・プリンスリーグの順位表</a>とあわせて追いかけるのがおすすめです。該当選手が在籍するチームの詳細ページには緑の「プロ内定・2種登録」バッジを表示しています。
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
    all_players = data.get("signings") or []
    naitei = [p for p in all_players if p.get("status") != "pro"]
    pro = [p for p in all_players if p.get("status") == "pro"]

    title = f"{season}年 Jリーグ内定・プロ契約選手一覧【高校・ユース】｜所属チーム別"
    desc = (f"U-18年代からJリーグへ進む選手を、これから加入する「内定者」{len(naitei)}名と、"
            f"すでにプロ契約済みの選手{len(pro)}名に分けて現所属チーム別に一覧。"
            f"全選手をクラブ公式発表で個別照合。所属チームの詳細ページ（順位・OB）へも移動できます。")

    sections = _section(
        "① これから加入する内定者",
        f"まだ高校・ユースに在籍していて、これからJリーグクラブに加入する選手です（現所属チーム別）。"
        f"加入時期は秋春制への移行にともないクラブごとに異なるため、公式発表の表記をそのまま載せています。",
        naitei, show_dest=True,
        empty_msg="現在、掲載できる内定選手はありません。")

    sections += _section(
        "② すでにプロ契約済みの選手",
        f"高校・ユースに在籍したままプロ契約を締結し、すでにトップチームに登録されている選手です（#は背番号）。"
        f"「内定者」ではありませんが、U-18年代からプロへ進んだ選手として同じページで追跡しています。",
        pro, show_dest=True,
        empty_msg="現在、掲載できる選手はありません。")

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
    print(f"  [OK] /pro-signings/ を生成（内定{len(naitei)}名・プロ契約済み{len(pro)}名・"
          f"うち2種登録タグ{sum(1 for p in all_players if p.get('type2'))}名）")
    update_sitemap()
    return 0


if __name__ == "__main__":
    exit(main())
