#!/usr/bin/env python3
"""高校選手権・インターハイ・クラブユース・Jユースカップの結果を JFA からスクレイプ。

使い方:
  python scraper/scrape_tournaments.py                  # 全大会・全年度
  python scraper/scrape_tournaments.py --year 2025      # 2025年のみ
  python scraper/scrape_tournaments.py --tournament all_japan_highschool --year 2025
  python scraper/scrape_tournaments.py --debug          # 詳細ログ

出力: data/tournaments.json
"""

import json
import re
import sys
import time
import argparse
import unicodedata
from datetime import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("必要なライブラリ: pip install requests beautifulsoup4 lxml")
    sys.exit(1)

# ===== 設定 =====
BASE_DIR = Path(__file__).parent.parent
TOURNAMENTS_FILE = BASE_DIR / "data" / "tournaments.json"
TEAMS_FILE = BASE_DIR / "data" / "teams.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ===== 大会定義 =====
# 各大会の URL パターン と category
TOURNAMENT_DEFS = {
    "all_japan_highschool": {
        "displayName": "全国高校サッカー選手権大会",
        "shortName":   "高校選手権",
        "category":    "high_school",   # 都道府県代表 + ベスト8以上 を記録
        "url_pattern": "https://www.jfa.jp/match/alljapan_highschool_{year}/schedule_result/",
    },
    "interhigh": {
        "displayName": "全国高等学校総合体育大会サッカー競技大会",
        "shortName":   "インターハイ",
        "category":    "high_school",
        "url_pattern": "https://www.jfa.jp/match/koukou_soutai_{year}/men/schedule_result/",
    },
    "club_youth_u18": {
        "displayName": "日本クラブユース選手権(U-18)大会",
        "shortName":   "クラブユース",
        "category":    "club_youth",   # ベスト8以上 のみ記録
        "url_pattern": "https://www.jfa.jp/match/club_youth_u18_{year}/schedule_result/",
    },
    "j_youth_cup": {
        "displayName": "Jユースカップ",
        "shortName":   "Jユース",
        "category":    "j_youth",
        "url_pattern": "https://www.jleague.jp/jyouth/{year}/match/quarter_final.html",
    },
}

# ===== 順位ラベルの標準化 =====
# JFA / Jリーグページに現れる表記 → (result, rank)
ROUND_LABELS = [
    # (検出キーワード, 正規化ラベル, rank)
    ("優勝",       "優勝",     1),
    ("準優勝",     "準優勝",   2),
    ("3位",        "ベスト4",  4),
    ("第3位",      "ベスト4",  4),
    ("ベスト4",    "ベスト4",  4),
    ("準決勝",     "ベスト4",  4),
    ("ベスト8",    "ベスト8",  8),
    ("準々決勝",   "ベスト8",  8),
    ("ベスト16",   "ベスト16", 16),
]

DEBUG = False


def log(msg: str) -> None:
    print(msg)


def dlog(msg: str) -> None:
    if DEBUG:
        print(f"[DEBUG] {msg}")


# ===== チーム名照合 =====
_KANJI_MAP = str.maketrans({
    '國': '国', '學': '学', '體': '体',
    '濱': '浜', '濵': '浜', '澤': '沢',
    '齋': '斉', '齊': '斉', '龍': '竜',
    '廣': '広', '藏': '蔵', '遙': '遥',
})


def _normalize_name(name: str) -> str:
    """teams.json の照合用: NFKC・括弧除去・空白除去・旧字体置換"""
    name = unicodedata.normalize('NFKC', name)
    name = name.translate(_KANJI_MAP)
    name = name.replace(' ', '').replace('\u3000', '')
    name = re.sub(r'[()]', '', name)
    return name


def find_team_pref(team_name: str, teams_data: dict) -> str | None:
    """teams.json からチームの所属都道府県を探す。返り値は pref_id (例: "hokkaido")"""
    target = _normalize_name(team_name)
    for pref_id, pref_data in teams_data.items():
        if pref_id == "_meta":
            continue
        for t in pref_data.get("teams", []):
            existing = _normalize_name(t.get("name", ""))
            if existing == target or target in existing or existing in target:
                return pref_id
    return None


# ===== ページ取得 =====
def fetch_html(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log(f"  ⚠ 取得失敗: {e}")
        return None


# ===== 大会ページの解析 =====
def extract_results_from_page(soup: BeautifulSoup) -> list[dict]:
    """JFA 大会ページから「優勝/準優勝/ベスト4/ベスト8」をざっくり抽出。

    JFAページの典型的構造:
      - 上部に試合結果テーブル(決勝→準決勝→QF...の順)
      - "優勝" "準優勝" "第3位" "ベスト8" などのテキストラベル付近にチーム名

    戦略:
      A) "優勝"等のキーワードを含む要素の近傍テキストをチーム名とみなす
      B) 試合表テーブルから決勝→準決勝→QFの参加チームを順に拾う

    今回は A) を主軸に、後で B) を追加できる構造で書く。
    """
    results: list[dict] = []
    seen: set[str] = set()

    text_blocks = soup.find_all(text=True)

    for label_kw, normalized, rank in ROUND_LABELS:
        # ページ全文から label_kw を探し、近傍のチーム名を拾う
        for block in text_blocks:
            txt = block.strip()
            if not txt or label_kw not in txt:
                continue
            # ラベル直後のチーム名候補をいくつか拾う
            parent = block.parent
            if not parent:
                continue
            # 親要素の兄弟を見て、リンク(<a>) や強調(<strong>) の中身を拾う
            container = parent.find_parent(["table", "section", "div", "li"]) or parent
            for cand in container.find_all(["a", "strong", "td", "span"]):
                ctxt = cand.get_text(strip=True)
                if not ctxt or len(ctxt) < 2 or len(ctxt) > 40:
                    continue
                # 数字のみ・英字のみは除外
                if re.fullmatch(r'[\d:\-\s]+', ctxt):
                    continue
                # 大会名・カテゴリ名は除外
                if any(skip in ctxt for skip in [label_kw, "決勝", "回戦", "選手権", "大会", "結果", "速報", "JFA", "公式"]):
                    continue
                # チーム名らしい(日本語高校/FC/U-18 等)
                if not re.search(r'[高校学院FC園\u3041-\u309F\u30A0-\u30FF]', ctxt):
                    continue
                key = f"{normalized}::{ctxt}"
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "team":   ctxt,
                    "result": normalized,
                    "rank":   rank,
                })
                dlog(f"    候補: {normalized} = {ctxt}")
                break  # 一つのラベルあたり最初の有力候補のみ

    return results


def extract_prefecture_reps(soup: BeautifulSoup) -> list[dict]:
    """都道府県代表のリストを抽出する(高校選手権/インターハイ用)。

    JFAページに「組合せ表」や「出場校一覧」がある場合に拾う。
    現状はベストエフォートで、見つからなければ空リストを返す。
    """
    reps: list[dict] = []
    # 「○○高校（北海道）」のような表記を全文検索で拾う
    text = soup.get_text("\n")
    pattern = re.compile(r'([^\s\n（）()]{2,20}(?:高校|学園|学院|高等学校))[\s（(]([^\s）)]{2,8})[）)]')
    seen = set()
    for m in pattern.finditer(text):
        team = m.group(1).strip()
        pref = m.group(2).strip()
        # pref が都道府県名らしいか
        if not re.search(r'(都|道|府|県)$', pref) and pref not in [
            "北海道", "東京", "大阪", "京都"
        ]:
            continue
        key = team
        if key in seen:
            continue
        seen.add(key)
        reps.append({
            "team":   team,
            "pref_label": pref,   # 後で teams.json と照合
            "result": "代表",
            "rank":   None,
        })
        dlog(f"    代表候補: {team} ({pref})")
    return reps


def merge_and_filter(
    results: list[dict],
    reps:    list[dict],
    category: str,
) -> list[dict]:
    """ランク結果と代表リストを統合。category により記載対象を絞る。"""
    by_team: dict[str, dict] = {}

    # ベスト8以上の結果を優先で記録
    for r in results:
        team = r["team"]
        existing = by_team.get(team)
        if existing is None or (r.get("rank") or 99) < (existing.get("rank") or 99):
            by_team[team] = r

    # 高校カテゴリのみ「代表」も記録(ベスト8以上があれば上書きしない)
    if category == "high_school":
        for rep in reps:
            team = rep["team"]
            if team not in by_team:
                by_team[team] = rep

    return list(by_team.values())


def attach_pref(entries: list[dict], teams_data: dict) -> list[dict]:
    """各エントリに pref_id を付与する(teams.json から逆引き)"""
    out = []
    for e in entries:
        pref_id = find_team_pref(e["team"], teams_data)
        if pref_id:
            e["pref"] = pref_id
        else:
            e["pref"] = None
            dlog(f"    ⚠ pref不明: {e['team']}")
        # 内部用フィールドは出力に残さない
        e.pop("pref_label", None)
        out.append(e)
    return out


def scrape_one(tournament_id: str, year: int, teams_data: dict) -> dict | None:
    """指定大会・年度をスクレイプして結果データを返す"""
    spec = TOURNAMENT_DEFS[tournament_id]
    url = spec["url_pattern"].format(year=year)
    log(f"\n[{spec['shortName']} {year}] {url}")

    soup = fetch_html(url)
    if soup is None:
        log("  ⚠ ページ取得失敗、スキップ")
        return None

    raw_results = extract_results_from_page(soup)
    log(f"  ランク結果検出: {len(raw_results)}件")
    for r in raw_results:
        log(f"    - {r['result']:<8} {r['team']}")

    reps: list[dict] = []
    if spec["category"] == "high_school":
        reps = extract_prefecture_reps(soup)
        log(f"  都道府県代表検出: {len(reps)}件")

    merged = merge_and_filter(raw_results, reps, spec["category"])
    final = attach_pref(merged, teams_data)
    log(f"  最終エントリ数: {len(final)}件")

    return {
        "url":   url,
        "teams": final,
    }


# ===== メイン =====
def main() -> int:
    global DEBUG
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="特定年のみ実行")
    parser.add_argument("--tournament", choices=list(TOURNAMENT_DEFS.keys()), help="特定大会のみ")
    parser.add_argument("--years-back", type=int, default=5, help="過去何年分(default: 5)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    DEBUG = args.debug

    # teams.json を読む(チーム→pref 照合用)
    if not TEAMS_FILE.exists():
        log(f"❌ teams.json が見つかりません: {TEAMS_FILE}")
        return 1
    with open(TEAMS_FILE, "r", encoding="utf-8") as f:
        teams_data = json.load(f)

    # 既存 tournaments.json を読む(なければ新規)
    if TOURNAMENTS_FILE.exists():
        with open(TOURNAMENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"_meta": {}, "tournaments": {}}

    # 大会一覧を初期化
    tournaments_data = data.setdefault("tournaments", {})
    for tid, spec in TOURNAMENT_DEFS.items():
        if tid not in tournaments_data:
            tournaments_data[tid] = {
                "displayName": spec["displayName"],
                "shortName":   spec["shortName"],
                "category":    spec["category"],
                "results":     {},
            }

    # 対象大会・年度を決定
    target_tournaments = [args.tournament] if args.tournament else list(TOURNAMENT_DEFS.keys())
    if args.year:
        target_years = [args.year]
    else:
        current_year = datetime.now().year
        target_years = list(range(current_year - args.years_back, current_year + 1))
    log(f"対象大会: {target_tournaments}")
    log(f"対象年度: {target_years}")

    for tid in target_tournaments:
        for year in target_years:
            year_data = scrape_one(tid, year, teams_data)
            if year_data is not None:
                tournaments_data[tid]["results"][str(year)] = year_data
            time.sleep(1.5)

    # メタ情報更新
    data["_meta"] = {
        "lastUpdated": datetime.now().isoformat(timespec="seconds"),
        "schemaVersion": 1,
    }

    # 保存
    TOURNAMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOURNAMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"\n✅ 保存: {TOURNAMENTS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
