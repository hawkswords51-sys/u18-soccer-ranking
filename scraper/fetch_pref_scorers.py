# -*- coding: utf-8 -*-
"""
県別 得点ランキング 自動更新スクリプト（GitHub Actions 用）

県サッカー協会の共通リーグ運営システム（tecra系 *-fa-u18.com / GoalNote）は
得点ランキングを HTML（サーバーレンダリング）で公開している。これを定期取得して
data/scorers/pref-<id>-1.json を更新する。生成された JSON は scorer_table.py が
県ページ（generate_prefecture_pages.py）に描画する。

設計方針:
- これらの出典は「公式集計」なので検算（選手合計==GF）は不要。掲載順をそのまま反映。
- 取得失敗・0件のときは既存 JSON を上書きしない（事故防止）。
- PDF 出典（茨城/福井/三重/愛媛/福島）は本スクリプトの対象外（別途・手動更新）。

ローカルでは外部取得が制限されるため、Actions（オープンネットワーク）で実行する。
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DIR = Path(__file__).resolve().parent.parent / "data" / "scorers"
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; u18-soccer-bot/1.0; +https://u18-soccer.com)"}
TIMEOUT = 25

# NFKC で直らない CJK 部首・互換漢字の補正
_RAD = {"⻑": "長", "⻄": "西", "⻘": "青", "⻩": "黄", "⼾": "戸"}


def _norm(s: str) -> str:
    for a, b in _RAD.items():
        s = s.replace(a, b)
    return unicodedata.normalize("NFKC", s).strip()


def _clean_name(n: str) -> str:
    n = _norm(n).replace("　", " ")
    n = re.sub(r"\s+", " ", n).strip()
    # 姓 名 の間の空白1個（両側が日本語）のみ詰める。外国人名(複数空白)は維持
    if n.count(" ") == 1:
        a, b = n.split(" ")
        if a and b and re.fullmatch(r"[一-鿿々〆぀-ゟ゠-ヿ]+", a + b):
            return a + b
    return n


def parse_ranking_html(html: str):
    """得点ランキングの表から [{rank,name,team,goals}] を抽出。tecra/GoalNote 共通。"""
    soup = BeautifulSoup(html, "lxml")
    best = None
    for t in soup.find_all("table"):
        txt = t.get_text()
        if "得点" in txt and ("選手" in txt or "名前" in txt or "氏名" in txt):
            best = t
            break
    if best is None:
        # フォールバック: 最も行数の多い表
        tables = soup.find_all("table")
        if not tables:
            return []
        best = max(tables, key=lambda t: len(t.find_all("tr")))
    out = []
    for tr in best.find_all("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 4:
            continue
        if not re.fullmatch(r"\d+", tds[0].strip()):
            continue
        m = re.search(r"\d+", tds[3])
        if not m:
            continue
        name = _clean_name(tds[1])
        team = _norm(tds[2])
        if not name or not team:
            continue
        if name.upper().replace(".", "").replace(" ", "") in ("OG", "オウンゴール"):
            continue  # オウンゴールは選手ランキングから除外
        out.append({"rank": int(tds[0]), "name": name, "team": team, "goals": int(m.group())})
    return out


def _last_updated(html: str, default: str) -> str:
    m = re.search(r"最終更新日[:：]\s*([0-9][0-9:\-\s/]+)", html)
    return m.group(1).strip() if m else default


# slug -> 出典設定
SOURCES = {
    "pref-fukuoka-1": dict(
        url="https://fukuoka-fa-u18.com/ranking/1/2026",
        label="福岡県サッカー協会 公式",
        league="高円宮杯 JFA U-18 サッカーリーグ2026 福岡県リーグ 1部 得点ランキング",
        note="福岡県サッカー協会公式サイトの得点ランキングをそのまま掲載しています。"),
    "pref-shiga-1": dict(
        url="https://shiga-fa-u18.com/ranking/index/1/2026/all",
        label="滋賀県サッカー協会 公式",
        league="高円宮杯 JFA U-18 サッカーリーグ2026 滋賀 1部 得点ランキング",
        note="滋賀県サッカー協会公式サイトの得点ランキングをそのまま掲載しています。"),
    "pref-aichi-1": dict(
        url="https://www.goalnote.net/detail-ranking.php?tid=18269",
        label="GoalNote（愛知県1部 公式）",
        league="高円宮杯 JFA U-18 サッカーリーグ2026 愛知県1部 得点ランキング",
        note="愛知県1部リーグ公式（GoalNote）掲載の得点ランキングです。"),
    "pref-iwate-1": dict(
        url="https://www.goalnote.net/detail-ranking.php?tid=18702",
        label="GoalNote（岩手 i.LEAGUE DIVISION I 公式）",
        league="高円宮杯 JFA U-18 サッカーリーグ2026 岩手 i.LEAGUE DIVISION I 得点ランキング",
        note="岩手県1部（i.LEAGUE DIVISION I）公式（GoalNote）掲載の得点ランキングです。"),
    "pref-nagasaki-1": dict(
        url="https://www.goalnote.net/detail-ranking.php?tid=18526",
        label="GoalNote（長崎県1部 公式）",
        league="高円宮杯 JFA U-18 サッカーリーグ2026 長崎県リーグ1部 得点ランキング",
        note="長崎県1部リーグ公式（GoalNote）掲載の得点ランキングです。"),
    "pref-tottori-1": dict(
        url="https://www.goalnote.net/detail-ranking.php?tid=18541",
        label="GoalNote（わかとりリーグ1部 公式）",
        league="高円宮杯 JFA U-18 サッカーリーグ2026 わかとりリーグ1部 得点ランキング",
        note="鳥取県1部（わかとりリーグ1部前期）公式（GoalNote）掲載の得点ランキングです。"),
    # 以下は現時点で得点者データが未入力の「枠だけ」県。入力されたら自動で埋まる。
    "pref-chiba-1": dict(
        url="https://www.goalnote.net/detail-ranking.php?tid=18441",
        label="GoalNote（千葉県1部 公式）",
        league="高円宮杯 JFA U-18 サッカーリーグ2026 千葉県1部 得点ランキング",
        note="千葉県1部リーグ公式（GoalNote）掲載の得点ランキングです。"),
    "pref-kagawa-1": dict(
        url="https://www.goalnote.net/detail-ranking.php?tid=18633",
        label="GoalNote（香川県1部 公式）",
        league="高円宮杯 JFA U-18 サッカーリーグ2026 香川県1部 得点ランキング",
        note="香川県1部リーグ公式（GoalNote）掲載の得点ランキングです。"),
}

MAX_ROWS = 50


def update_one(slug: str, cfg: dict, today: str) -> str:
    path = DIR / f"{slug}.json"
    try:
        r = requests.get(cfg["url"], headers=HEAD, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding
        scorers = parse_ranking_html(r.text)
    except Exception as e:
        return f"  {slug}: 取得失敗のためスキップ（既存維持）: {e}"
    if not scorers:
        return f"  {slug}: 得点者0件のためスキップ（既存維持）"
    scorers = scorers[:MAX_ROWS]
    last_updated = _last_updated(r.text, today)
    obj = {
        "league": cfg["league"],
        "season": "2026",
        "source": cfg["url"],
        "sourceLabel": cfg["label"],
        "lastUpdated": last_updated,
        "note": cfg["note"],
        "scorers": scorers,
    }
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"  {slug}: 更新 {len(scorers)}名 1位={scorers[0]['name']}({scorers[0]['goals']}) 更新日={last_updated}"


def main():
    import datetime
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    print("県別得点ランキング 自動更新")
    for slug, cfg in SOURCES.items():
        if only and slug not in only:
            continue
        print(update_one(slug, cfg, today))


if __name__ == "__main__":
    main()
