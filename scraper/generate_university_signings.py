#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大学経由のJクラブ内定選手ページ（/university/pro-signings-2027/）を生成する。

- データの正本: data/university/pro-signings-2027.json（1件追加→本スクリプト再実行→Pushで反映）
- ページの <!-- UNIV_SIGNINGS_START --> 〜 <!-- UNIV_SIGNINGS_END --> の間だけを書き換える。
- U-18の出身チームに当サイトのチーム詳細ページ（data/team-profiles）があれば自動で内部リンクを張る。
- 検証: 必須項目の欠落・発表日形式・重複選手名をチェックし、問題があれば生成を中止する。
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "university" / "pro-signings-2027.json"
PAGE = ROOT / "university" / "pro-signings-2027" / "index.html"
PROFILES = ROOT / "data" / "team-profiles"
START = "<!-- UNIV_SIGNINGS_START -->"
END = "<!-- UNIV_SIGNINGS_END -->"
# 関東ブロック（1部〜3部＋その下の県リーグ）→ 各地域ブロックの順。
# 県リーグは「関東3部の直後」に置く（2026-09-22 Kei 決定。今後 東京都・千葉県 が出たらここに並べる）。
# ★このリストは3つの役目を兼ねている：
#   95行目=ホワイトリスト（無い値は「不明なリーグ」で生成中止）／130行目=セクションの表示順／
#   150行目=見出しの文字そのもの（「{lg}リーグの大学」）。
#   130行目がループの駆動元なので、ここに無いリーグは（検証を通れば）黙ってページから消える。
LEAGUE_ORDER = ["関東1部", "関東2部", "関東3部", "神奈川県", "北信越", "東海", "関西", "中国", "九州"]
# よくある質問（画面）と構造化データ（FAQPage）の差し替え範囲。人数は毎回計算して入れる＝手で書かない
FAQ_START = "<!-- UNIV_FAQ_START -->"
FAQ_END = "<!-- UNIV_FAQ_END -->"
FAQLD_START = "<!-- UNIV_FAQLD_START -->"
FAQLD_END = "<!-- UNIV_FAQLD_END -->"
HS_SIGNINGS = ROOT / "data" / "pro-signings.yml"  # 高校・ユース年代の内定（/pro-signings/ と同じデータ）


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def norm_team(s):
    s = re.sub(r"\s", "", s)
    s = s.replace("高等学校", "高校").replace("髙", "高")
    return s


def load_team_links():
    """team-profiles の frontmatter name/aliases → /teams/{slug}/ の対応表"""
    links = {}
    if not PROFILES.is_dir():
        return links
    for md in PROFILES.glob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not m:
            continue
        fm = m.group(1)
        names = []
        nm = re.search(r'^name:\s*["\']?([^"\'\n]+)', fm, re.M)
        if nm:
            names.append(nm.group(1).strip())
        am = re.search(r"^aliases:\s*\n((?:\s*-\s*.+\n?)+)", fm, re.M)
        if am:
            names += [re.sub(r"^\s*-\s*", "", ln).strip().strip('"\'')
                      for ln in am.group(1).strip().splitlines()]
        slug = md.stem
        for n in names:
            if n:
                links[norm_team(n)] = slug
    return links


def team_link(name, links):
    if name in ("—", ""):
        return "—"
    key = norm_team(name)
    slug = links.get(key)
    if not slug and not key.endswith("高校"):
        slug = links.get(key + "高校")
    if not slug and key.endswith("高校"):
        slug = links.get(key[:-2])
    if slug:
        return f'<a href="/teams/{slug}/">{esc(name)}</a>'
    return esc(name)


def is_youth(u18):
    return ("ユース" in u18) or ("U-18" in u18) or ("U18" in u18) or ("高等部" not in u18 and "アカデミー" in u18)


def validate(players):
    errs = []
    seen = set()
    for p in players:
        for k in ("name", "pos", "univ", "league", "club", "announced", "u18", "u15", "source"):
            if not str(p.get(k, "")).strip():
                errs.append(f"{p.get('name','?')}: {k} が空")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", p["announced"]):
            errs.append(f"{p['name']}: 発表日の形式が不正")
        key = (p["name"], p["univ"])
        if key in seen:
            errs.append(f"重複: {p['name']}")
        seen.add(key)
        if p["league"] not in LEAGUE_ORDER:
            errs.append(f"{p['name']}: 不明なリーグ {p['league']}")
    return errs


def replace_between(src, start, end, body):
    if start not in src or end not in src:
        print(f"[エラー] マーカーが見つかりません: {start}")
        sys.exit(1)
    pre, rest = src.split(start, 1)
    _, post = rest.split(end, 1)
    return pre + start + "\n" + body + end + post


def hs_signing_counts():
    """/pro-signings/ と同じ数え方（status: pro 以外＝内定者、pro＝プロ契約済み）で人数を返す。
    2種登録だけの選手は pro-signings.yml に載せない運用なので、数にも入らない。"""
    import yaml
    data = yaml.safe_load(HS_SIGNINGS.read_text(encoding="utf-8")) or {}
    sign = data.get("signings") or []
    pro = sum(1 for p in sign if p.get("status") == "pro")
    return len(sign) - pro, pro


def build_faq(data, total, koutairen, youth, home):
    """[(質問, 答えのHTML), ...]。画面とFAQPageの両方にこのまま使う。"""
    y, m = data["updated"].split("-")[:2]
    asof = f"{int(y)}年{int(m)}月時点"
    hs_naitei, hs_pro = hs_signing_counts()
    scale = "それを上回る規模で" if total > hs_naitei + hs_pro else "それに並ぶ規模で"
    return [
        ("大学からJリーグに内定した選手はどのくらいいますか？",
         f"2027年シーズン加入の内定発表は年間を通じて続きます。当ページでは{asof}で{total}人を掲載しており、"
         f"うち高体連（高校サッカー部）出身が{koutairen}人、Jクラブなどのクラブユース出身が{youth}人です。"),
        ("ユースから昇格できなかった選手も大学からプロになれますか？",
         f"なれます。今回の一覧にはユースからトップ昇格できずに大学へ進み、育ったクラブへ「復帰内定」を勝ち取った選手が{home}人います。"
         "大学サッカーは高校年代で夢が途切れた選手にとっての敗者復活の舞台になっています。"),
        ("高卒でプロになる選手との違いは？",
         f"高校・ユースから直接プロ入りする選手は、2027年加入の内定者{hs_naitei}人・すでにプロ契約済み{hs_pro}人"
         f'（<a href="/pro-signings/">高校・ユース年代の内定ページ</a>）。'
         f"大学経由は{scale}、22歳前後で心身が完成してから加入するため即戦力として期待されます。"),
        ("内定＝すぐプロ入りですか？",
         "多くは卒業後の2027年シーズンからの加入ですが、在学中に「特別指定選手」としてJリーグの試合に出場する選手もいます。"
         "また「28年加入」注記の選手は大学3年以下での早期内定です。"),
        ("経歴の情報は何で確認していますか？",
         "各Jクラブ公式サイトの加入内定リリース（経歴欄）を第一の出典とし、確認できない場合は大学サッカー部・高校の公式発表で補っています。"
         "公式に確認できない項目は「—」として推測では掲載していません。"),
        ("この一覧は更新されますか？",
         "内定発表は秋から冬にかけて増え続けるため、随時追加していきます。"),
    ]


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    players = data["players"]
    errs = validate(players)
    if errs:
        print("[エラー] データ検証NGのため生成を中止:")
        for e in errs:
            print("  -", e)
        sys.exit(1)

    links = load_team_links()
    total = len(players)
    youth = sum(1 for p in players if is_youth(p["u18"]))
    koutairen = total - youth
    home = sum(1 for p in players if p.get("homecoming"))
    linked = 0

    # 集計ボックス
    stats = f"""        <div class="pmc-info" style="margin-bottom:6px;">
          <div><strong>掲載人数</strong>{total}人（{data['updated']}時点）</div>
          <div><strong>U-18の出身</strong>高校サッカー部（高体連）{koutairen}人 ／ クラブユース{youth}人</div>
          <div><strong>アカデミー古巣への復帰内定</strong>{home}人</div>
        </div>"""

    # リーグ→大学ごとにグループ化
    by_league = {}
    for p in players:
        by_league.setdefault(p["league"], {}).setdefault(p["univ"], []).append(p)

    sections = []
    for lg in LEAGUE_ORDER:
        if lg not in by_league:
            continue
        rows = []
        for univ, ps in by_league[lg].items():
            for i, p in enumerate(ps):
                u18html = team_link(p["u18"], links)
                if "<a " in u18html:
                    linked += 1
                mark = " 🏠" if p.get("homecoming") else ""
                note = f'<div class="us-note">※{esc(p["note"])}</div>' if p.get("note") else ""
                ann = p["announced"].replace("-", "/")
                univ_cell = f'<td class="us-univ" rowspan="{len(ps)}">{esc(univ)}</td>' if i == 0 else ""
                rows.append(
                    f'                <tr>{univ_cell}<td class="us-name">{esc(p["name"])}'
                    f'<span class="us-pos">{esc(p["pos"])}</span></td>'
                    f'<td class="us-club">{esc(p["club"])}{mark}</td>'
                    f'<td class="us-career">{team_link(p["u15"], links)} → {u18html}{note}</td>'
                    f'<td class="us-date">{ann}</td></tr>'
                )
        sections.append(f"""        <h3 style="margin:22px 0 10px;"><i class="fas fa-map-location-dot"></i> {lg}リーグの大学</h3>
        <div class="univ-scroll">
        <table class="uv-table us-table">
          <thead><tr><th>大学</th><th class="us-name" style="text-align:left;">選手</th><th>内定先</th><th style="text-align:left;">経歴（U-15 → U-18）</th><th>発表日</th></tr></thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
        </div>""")

    html = stats + "\n" + "\n".join(sections) + "\n"
    src = PAGE.read_text(encoding="utf-8")
    if START not in src or END not in src:
        print("[エラー] マーカーが見つかりません")
        sys.exit(1)
    pre, rest = src.split(START, 1)
    _, post = rest.split(END, 1)
    src = pre + START + "\n" + html + END + post
    # よくある質問：画面の表示と構造化データ（FAQPage）を同じ質問・答えから作る
    faq = build_faq(data, total, koutairen, youth, home)
    faq_html = "".join(
        f'        <h3 style="margin:14px 0 6px;">Q. {esc(q)}</h3>\n'
        f'        <p style="line-height:1.9;">{a}</p>\n'
        for q, a in faq
    )
    faq_ld = json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq],
    }, ensure_ascii=False)
    src = replace_between(src, FAQ_START, FAQ_END, faq_html)
    src = replace_between(src, FAQLD_START, FAQLD_END,
                          f'  <script type="application/ld+json">{faq_ld}</script>\n  ')
    # 掲載人数などの本文中の数字も更新
    src = re.sub(r"<!--COUNT-->\d+<!--/COUNT-->", f"<!--COUNT-->{total}<!--/COUNT-->", src)
    src = re.sub(r"<!--KTR-->\d+<!--/KTR-->", f"<!--KTR-->{koutairen}<!--/KTR-->", src)
    src = re.sub(r"<!--YTH-->\d+<!--/YTH-->", f"<!--YTH-->{youth}<!--/YTH-->", src)
    PAGE.write_text(src, encoding="utf-8")
    print(f"OK: {total}人（高体連{koutairen}/ユース{youth}/復帰{home}）・チームページ内部リンク{linked}件")


if __name__ == "__main__":
    main()
