#!/usr/bin/env python3
"""
高円宮杯 U-18 サッカーリーグ 自動順位更新スクリプト
JFA公式サイトから試合結果を取得し、teams.jsonを更新します。

使い方:
  python scraper/update.py             # 現在の年度で実行
  python scraper/update.py --year 2026 # 年度を指定
  python scraper/update.py --dry-run   # 実際には保存せずテスト実行
"""

import json
import os
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
    print("必要なライブラリをインストールしてください:")
    print("  pip install requests beautifulsoup4 lxml")
    sys.exit(1)

# Selenium は任意（JFAサイトがJS描画の場合に使用）
SELENIUM_AVAILABLE = False
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    pass  # Seleniumなしでも動作する

# ===== 設定 =====
BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "teams.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# 都道府県ID → 都道府県名のマッピング
PREF_ID_TO_NAME = {
    "hokkaido": "北海道", "aomori": "青森", "iwate": "岩手",
    "miyagi": "宮城", "akita": "秋田", "yamagata": "山形",
    "fukushima": "福島", "ibaraki": "茨城", "tochigi": "栃木",
    "gunma": "群馬", "saitama": "埼玉", "chiba": "千葉",
    "tokyo": "東京", "kanagawa": "神奈川", "niigata": "新潟",
    "toyama": "富山", "ishikawa": "石川", "fukui": "福井",
    "yamanashi": "山梨", "nagano": "長野", "shizuoka": "静岡",
    "aichi": "愛知", "mie": "三重", "shiga": "滋賀",
    "kyoto": "京都", "osaka": "大阪", "hyogo": "兵庫",
    "nara": "奈良", "wakayama": "和歌山", "tottori": "鳥取",
    "shimane": "島根", "okayama": "岡山", "hiroshima": "広島",
    "yamaguchi": "山口", "tokushima": "徳島", "kagawa": "香川",
    "ehime": "愛媛", "kochi": "高知", "fukuoka": "福岡",
    "saga": "佐賀", "nagasaki": "長崎", "kumamoto": "熊本",
    "oita": "大分", "miyazaki": "宮崎", "kagoshima": "鹿児島",
    "okinawa": "沖縄",
    "gifu": "岐阜",
}

# プレミアリーグのチーム → 都道府県マッピング（主要チーム）
# ※ 降格/昇格したチームはここに残さず削除すること
PREMIER_TEAM_PREF = {
    # EAST
    "青森山田": "aomori",
    "仙台育英": "miyagi",
    "尚志": "fukushima",
    "鹿島アントラーズ": "ibaraki",
    "前橋育英": "gunma",
    "昌平": "saitama",
    "浦和レッズ": "saitama",
    "流通経済大付属柏": "chiba",
    "FC東京": "tokyo",
    "東京ヴェルディ": "tokyo",
    "川崎フロンターレ": "kanagawa",
    "横浜FC": "kanagawa",
    "清水エスパルス": "shizuoka",
    # WEST
    "名古屋グランパス": "aichi",
    "ガンバ大阪": "osaka",
    "セレッソ大阪": "osaka",
    "京都橘": "kyoto",
    "京都サンガ": "kyoto",
    "ヴィッセル神戸": "hyogo",
    "サンフレッチェ広島": "hiroshima",
    "東福岡": "fukuoka",
    "大津": "kumamoto",
    "神村学園": "kagoshima",
}

# プリンスリーグ地域キー → 表示名（league フィールドに使用）
REGION_DISPLAY_NAMES = {
    "hokkaido":     "北海道",
    "tohoku":       "東北",
    "kanto":        "関東",
    "hokushinetsu": "北信越",
    "tokai":        "東海",
    "kansai":       "関西",
    "chugoku":      "中国",
    "shikoku":      "四国",
    "kyushu":       "九州",
}

# プリンスリーグ地域 → 対象都道府県
PRINCE_REGION_PREFS = {
    "hokkaido": ["hokkaido"],
    "tohoku": ["aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima"],
    "kanto": ["ibaraki", "tochigi", "gunma", "saitama", "chiba", "tokyo", "kanagawa", "yamanashi", "nagano"],
    "hokushinetsu": ["niigata", "toyama", "ishikawa", "fukui"],
    "tokai": ["shizuoka", "aichi", "mie", "gifu"],
    "kansai": ["shiga", "kyoto", "osaka", "hyogo", "nara", "wakayama"],
    "chugoku": ["tottori", "shimane", "okayama", "hiroshima", "yamaguchi"],
    "shikoku": ["tokushima", "kagawa", "ehime", "kochi"],
    "kyushu": ["fukuoka", "saga", "nagasaki", "kumamoto", "oita", "miyazaki", "kagoshima", "okinawa"],
}

JFA_BASE = "https://www.jfa.jp"

# 1部・2部に分かれている地域リーグ（requestsで1ページしか取れなくてもデフォルト"1部"にする）
REGIONS_WITH_DIVISIONS = {"kanto", "kansai", "kyushu", "hokushinetsu"}


# 順位表テーブルを検出するためのヘッダーヒント（_extract_standing_tables 用）
_STANDING_TABLE_HINTS = {
    'チーム名', 'クラブ名', 'チーム', 'クラブ',
    '勝点', '勝ち点', '試合数', '試合',
    '勝', '勝利', '引分', '引き分け', '引分数',
    '負', '敗', '敗戦',
    '得点', '失点', '得失点差', '得失差', '得失点',
}


def _extract_standing_tables(soup: BeautifulSoup) -> list:
    """
    ページ内に複数ある <table> の中から「順位表らしき table」だけを抽出し、
    それぞれを独立した BeautifulSoup として返す。
    プリンス関東/関西/九州/北信越のように 1部と2部が同じページに並ぶケースで、
    どれが1部のテーブルでどれが2部のテーブルかを分けて扱うために使う。

    返り値: 順位表テーブル1つにつき1つの BeautifulSoup（ページ内の出現順）。
    """
    out = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        best_score = 0
        for i, row in enumerate(rows[:5]):
            cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            score = sum(1 for c in cols if c in _STANDING_TABLE_HINTS)
            if score > best_score:
                best_score = score
        if best_score < 2:
            continue
        mini = BeautifulSoup(f"<html><body>{table}</body></html>", "html.parser")
        out.append(mini)
    return out


def _fetch_with_selenium(url: str) -> BeautifulSoup | None:
    """Seleniumを使ってJS描画後のページを取得する（シンプル版: 1ページ分のみ）"""
    if not SELENIUM_AVAILABLE:
        return None
    print("  → Selenium (ヘッドレス Chrome) で再試行...")
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument(f"--user-agent={HEADERS['User-Agent']}")
    driver = None
    try:
        driver = webdriver.Chrome(options=opts)
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
        )
        time.sleep(2)
        return BeautifulSoup(driver.page_source, "html.parser")
    except Exception as e:
        print(f"  Selenium 取得失敗: {e}")
        return None
    finally:
        if driver:
            driver.quit()


def _split_prince_page(page_soup: BeautifulSoup, region_key: str) -> list:
    """
    1ページ分の soup から 1部/2部 を抽出して [(mini_soup, league_name), ...] を返す。
    JFAのプリンスページは 1ページ内に「1部の順位表」「2部の順位表」が並んで
    レンダリングされるため、タブクリックではなく複数 table を切り出す。
    """
    region_name = REGION_DISPLAY_NAMES.get(region_key, region_key)
    tables = _extract_standing_tables(page_soup)
    results = []

    if region_key in REGIONS_WITH_DIVISIONS:
        if len(tables) >= 2:
            results.append((tables[0], f"プリンスリーグ{region_name}1部"))
            results.append((tables[1], f"プリンスリーグ{region_name}2部"))
            if len(tables) > 2:
                print(f"    [WARN] {region_name}: 順位表が{len(tables)}個検出されました（1部/2部のみ使用）")
        elif len(tables) == 1:
            print(f"    [WARN] {region_name}: 順位表が1個しか検出されませんでした（1部のみとして扱います）")
            results.append((tables[0], f"プリンスリーグ{region_name}1部"))
        else:
            print(f"    [WARN] {region_name}: 順位表を検出できませんでした")
    else:
        if len(tables) >= 1:
            results.append((tables[0], f"プリンスリーグ{region_name}"))
            if len(tables) > 1:
                print(f"    [WARN] {region_name}: 順位表が{len(tables)}個検出されました（先頭のみ使用）")
        else:
            print(f"    [WARN] {region_name}: 順位表を検出できませんでした")

    return results


def fetch_prince_divisions(url: str, region_key: str) -> list[tuple]:
    """
    プリンスリーグのURLを取得し、[(soup, league_name), ...] を返す。
    JFAページは 1部と2部が同じページに並べて描画される（タブではない）ので、
    ページ内の table を順序どおりに切り出して 1部/2部 に割り当てる。
    league_name は "プリンスリーグ関東1部" / "プリンスリーグ関東2部" など。
    """
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")
            if soup.find("table"):
                splits = _split_prince_page(soup, region_key)
                if splits:
                    return splits
                print("  順位表として認識できるテーブルがありません。Selenium に切り替えます。")
                break
            print("  テーブルが見つかりません。JSレンダリングが必要かもしれません。")
            break
        except requests.RequestException as e:
            print(f"  取得失敗 (試行 {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2)

    if not SELENIUM_AVAILABLE:
        print("  Selenium が利用できません。スキップします。")
        return []

    print("  → Selenium (ヘッドレス Chrome) でプリンスリーグ取得...")
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--ignore-ssl-errors")
    opts.add_argument(f"--user-agent={HEADERS['User-Agent']}")
    driver = None
    try:
        driver = webdriver.Chrome(options=opts)
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
        )
        time.sleep(2)
        page_soup = BeautifulSoup(driver.page_source, "html.parser")
        return _split_prince_page(page_soup, region_key)
    except Exception as e:
        print(f"  Selenium 取得失敗: {e}")
        return []
    finally:
        if driver:
            driver.quit()


def fetch_page(url: str, retries: int = 3) -> BeautifulSoup | None:
    """JFAサイトのページを取得する（requests → Selenium フォールバック）"""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")
            # テーブルが取得できた場合はそのまま返す
            if soup.find("table"):
                return soup
            # テーブルなし = JSレンダリングが必要な可能性
            print("  テーブルが見つかりません。JSレンダリングが必要かもしれません。")
            break
        except requests.RequestException as e:
            print(f"  取得失敗 (試行 {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)

    # Selenium フォールバック
    return _fetch_with_selenium(url)


def _clean_team_name(name: str) -> str:
    """チーム名から末尾の都道府県表記 (例: '(千葉県)') を除去する"""
    return re.sub(r'\s*（[^）]+）|\s*\([^)]+\)', '', name).strip()


def _detect_col_indices(header_cols: list[str]) -> dict:
    """
    ヘッダー行からフィールド→列インデックスのマッピングを返す。
    JFA2026実績テーブル形式:
      順位 | チーム名 | 勝点平均 | 勝点 | 試合数 | 勝 | 分 | 負 | 得点 | 失点 | 得失点差
    完全一致を優先し、「勝点平均」などの複合語に誤マッチしないようにする。
    """
    mapping = {}

    # (フィールド名, 完全一致キーワード, 部分一致キーワード)
    # 完全一致リストの語に完全一致した場合のみ優先的に採用する
    field_specs = [
        ("name",         ["チーム名", "クラブ名", "チーム", "クラブ"], ["club", "team"]),
        ("points",       ["勝点", "勝ち点"],                           ["pts", "pt", "points"]),
        ("played",       ["試合数", "試合"],                           ["mp", "games", "played"]),
        ("won",          ["勝", "勝利", "勝数", "勝利数"],                          ["win", "wins"]),
        ("drawn",        ["分", "引分", "引き分け", "ドロー", "引分数", "引"],     ["draw", "draws"]),
        ("lost",         ["負", "敗", "敗戦", "敗北", "敗数", "敗戦数"],           ["loss", "lose"]),
        ("goalsFor",     ["得点"],                                                  ["gf"]),
        ("goalsAgainst", ["失点"],                                                  ["ga"]),
        ("goalDiff",     ["得失点差", "得失差", "得失点"],                          ["得失", "gd"]),
    ]

    # パス1: 完全一致（「勝」vs「勝点平均」問題を回避）
    for idx, header in enumerate(header_cols):
        h = header.strip()
        for field, exact_kws, _ in field_specs:
            if field not in mapping and h in exact_kws:
                mapping[field] = idx
                break

    # パス2: 部分一致（「平均」「rate」など複合語はスキップ）
    skip_words = ["平均", "rate", "avg", "average"]
    for idx, header in enumerate(header_cols):
        h = header.strip()
        h_lower = h.lower()
        if any(sw in h_lower for sw in skip_words):
            continue
        for field, _, partial_kws in field_specs:
            if field not in mapping:
                if any(k.lower() in h_lower for k in partial_kws):
                    mapping[field] = idx
                    break

    return mapping


def parse_standing_table(soup: BeautifulSoup) -> list[dict]:
    """
    JFAの順位表テーブルをパースする。
    ヘッダー行の列名を使って正確に列を特定する。
    JFA2026形式: 順位|チーム名(都道府県)|勝点平均|勝点|試合数|勝|分|負|得点|失点|得失点差
    返り値: [{"name": str, "played": int, "won": int, "drawn": int,
               "lost": int, "goalsFor": int, "goalsAgainst": int, "points": int}, ...]
    重複チーム名は最初の出現のみ保持する。
    """
    results = []
    seen_names: set[str] = set()

    # ヘッダー検出に使うキーワードセット
    _HEADER_HINTS = {
        'チーム名', 'クラブ名', 'チーム', 'クラブ',
        '勝点', '勝ち点', '試合数', '試合',
        '勝', '勝利', '勝数', '引分', '引き分け', '引分数', '引',
        '負', '敗', '敗戦', '敗数',
        '得点', '失点', '得失点差', '得失差', '得失点',
    }

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # ヘッダー行を自動検出（最初5行の中でヘッダーキーワードが最も多い行）
        best_i, best_score = 0, 0
        for i, row in enumerate(rows[:5]):
            cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            score = sum(1 for c in cols if c.strip() in _HEADER_HINTS)
            if score > best_score:
                best_i, best_score = i, score
        header_row_idx = best_i

        header_cols = [th.get_text(strip=True) for th in rows[header_row_idx].find_all(["th", "td"])]
        col_map = _detect_col_indices(header_cols)

        # 最低限「勝点」と「試合数」が特定できる表のみ処理
        if "points" not in col_map or "played" not in col_map:
            continue

        # 列オフセット検出（goalnote形式: データ行にヘッダーより1列多い = 先頭に順位列）
        offset = 0
        if len(rows) > header_row_idx + 1:
            first_data = [c.get_text(strip=True) for c in rows[header_row_idx + 1].find_all(["td", "th"])]
            diff = len(first_data) - len(header_cols)
            if diff > 0 and first_data and re.match(r'^\d+$', first_data[0].strip()):
                offset = diff
        if offset:
            col_map = {k: v + offset for k, v in col_map.items()}

        position = 0  # テーブル内での行位置（= そのリーグでの順位）
        for row in rows[header_row_idx + 1:]:
            position += 1
            cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cols) < 5:
                continue
            try:
                # チーム名取得（都道府県表記を除去）
                raw_name = cols[col_map["name"]] if "name" in col_map else None
                if not raw_name:
                    raw_name = next(
                        (c for c in cols if len(c) > 2 and not re.match(r"^[\d.+\-]+$", c)), None
                    )
                if not raw_name:
                    continue
                name = _clean_team_name(raw_name)
                if not name or name in seen_names:
                    continue

                def gcol(field: str, default: int = 0) -> int:
                    idx = col_map.get(field)
                    if idx is None or idx >= len(cols):
                        return default
                    val = cols[idx].strip().lstrip('+')  # "+4" → "4"
                    return int(val) if re.match(r"^-?\d+$", val) else default

                record = {
                    "name":         name,
                    "played":       gcol("played"),
                    "won":          gcol("won"),
                    "drawn":        gcol("drawn"),
                    "lost":         gcol("lost"),
                    "goalsFor":     gcol("goalsFor"),
                    "goalsAgainst": gcol("goalsAgainst"),
                    "points":       gcol("points"),
                    # テーブル内での順位（= そのリーグでの公式順位）。
                    # JFA のテーブルは勝点→得失点差→直接対決などの tiebreaker 込みで
                    # 既に並び替えられているので、行順をそのまま使うのが最も正確。
                    "leagueRank":   position,
                }

                results.append(record)
                seen_names.add(name)
            except (ValueError, IndexError):
                continue
    return results


def find_league_urls(year: int) -> dict[str, list[str]]:
    """JFAサイトから各リーグのURLを収集する

    JFA公式URLパターン（2026年確認済み）:
      プレミア: /match/takamado_jfa_u18_premier{year}/{east|west}/standings/
      プリンス: /match/takamado_jfa_u18_prince{year}/{region}/standings/
    """
    urls = {"premier_east": [], "premier_west": [], "prince": {}}

    # プレミアリーグ
    for division in ["east", "west"]:
        url = f"{JFA_BASE}/match/takamado_jfa_u18_premier{year}/{division}/standings/"
        urls[f"premier_{division}"].append(url)

    # プリンスリーグ (地域別)
    # JFA中央管理: 地域トップページに順位表が埋め込まれている
    # 東北・近畿は地域協会管理のためJFAページが存在しない → 協会URLを使用
    prince_region_urls = {
        "hokkaido":     f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/hokkaido/",
        "tohoku":       f"https://www.jfa.jp/match_47fa/102_tohoku/takamado_jfa_u18_prince{year}/thfa/ranking.html",  # 東北（JFA iframeソース）
        "kanto":        f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/kanto/",
        "hokushinetsu": f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/hokushinetsu/",
        "tokai":        f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/tokai/",
        "kansai":       f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/kansai/",      # 関西（JFA管理）
        "chugoku":      f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/chugoku/",
        "shikoku":      f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/shikoku/",
        "kyushu":       f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/kyushu/",
    }
    for region_key, url in prince_region_urls.items():
        urls["prince"][region_key] = url

    return urls


# 控えチームを示す末尾キーワード（1軍チームのスクレイピング時にマッチさせない）
RESERVE_SUFFIXES = (
    "B", "C", "D",
    "Ⅱ", "Ⅲ", "Ⅳ", "II", "III",
    "2nd", "3rd", "4th",
    "セカンド", "サード", "フォース",
    "2", "3",
)


def _is_reserve_team(name: str) -> bool:
    """チーム名が控えチーム（B・Ⅱ・セカンドなど）かどうかを判定する"""
    for suffix in RESERVE_SUFFIXES:
        if name.endswith(suffix):
            return True
        # スペース区切り: "青森山田高校 B" のような形式
        if name.endswith(" " + suffix) or name.endswith("　" + suffix):
            return True
    return False


def _name_similarity(a: str, b: str) -> bool:
    """チーム名の類似判定（短縮名や略称に対応）"""
    # "U-18", "ユース", "FC" などの接尾語を除去して比較
    suffixes = ["U-18", "U18", "ユース", "Youth", "高校", "高等学校"]
    a_clean = a
    b_clean = b
    for s in suffixes:
        a_clean = a_clean.replace(s, "").strip()
        b_clean = b_clean.replace(s, "").strip()
    return a_clean and b_clean and (a_clean in b_clean or b_clean in a_clean)


# 旧字体・異体字 → 常用漢字への変換テーブル（チーム名比較用）
_KANJI_MAP = str.maketrans({
    '國': '国', '學': '学', '體': '体',
    '濱': '浜', '濵': '浜', '澤': '沢',
    '齋': '斉', '齊': '斉', '龍': '竜',
    '廣': '広', '藏': '蔵', '遙': '遥',
    '塚': '塚',  # 塚(U+585A) / 塚(U+FA10) 統一
})


def _normalize_name(name: str) -> str:
    """
    チーム名を比較用に正規化する。
    ・NFKC正規化（全角英数→半角、ローマ数字など）
    ・旧字体/異体字 → 常用漢字（國→国、學→学 など）
    ・スペース除去
    ・中黒の統一（U+00B7 · U+FF65 ･ → U+30FB ・）
    """
    name = unicodedata.normalize('NFKC', name)
    name = name.translate(_KANJI_MAP)
    name = name.replace(' ', '').replace('\u3000', '')
    # 中黒の種類を統一
    name = name.replace('\u00b7', '・').replace('\uff65', '・')
    return name


def _teams_match(scraped: str, existing: str) -> bool:
    """
    スクレイピング名と既存チーム名が同じチームを指すか判定。
    【重要】1軍チーム名（B/Ⅱなし）が控えチーム名（B/Ⅱあり）にマッチするのを防ぐ。
    スペース有無の表記ゆれ（例: "青森山田高校 セカンド" vs "青森山田高校セカンド"）にも対応。
    """
    # 完全一致は常にOK
    if scraped == existing:
        return True

    # スペース正規化後の一致（"青森山田高校 セカンド" == "青森山田高校セカンド"）
    s_norm = _normalize_name(scraped)
    e_norm = _normalize_name(existing)
    if s_norm == e_norm:
        return True

    # スクレイピング名が1軍、既存が控え → 絶対にマッチさせない
    if not _is_reserve_team(scraped) and _is_reserve_team(existing):
        return False

    # 部分一致（正規化後）
    if s_norm in e_norm or e_norm in s_norm:
        return True
    # 元の文字列でも部分一致チェック
    if scraped in existing or existing in scraped:
        return True
    # 略称・接尾語を除いた類似判定
    return _name_similarity(scraped, existing)


def match_team_to_pref(team_name: str, candidate_prefs: list[str], data: dict) -> str | None:
    """
    チーム名を既存データの都道府県チームとマッチングする。
    完全一致を優先し、控えチームへの誤マッチを防ぐ。
    """
    # パス1: 完全一致
    for pref_id in candidate_prefs:
        for team in data.get(pref_id, {}).get("teams", []):
            if team.get("name", "") == team_name:
                return pref_id
    # パス2: 部分一致（1軍→控えへのマッチは除外）
    for pref_id in candidate_prefs:
        for team in data.get(pref_id, {}).get("teams", []):
            if _teams_match(team_name, team.get("name", "")):
                return pref_id
    return None


def update_team_stats(
    data: dict,
    pref_id: str,
    team_name: str,
    stats: dict,
    already_updated: set[str],
) -> bool:
    """teamsデータの特定チームの成績を更新する。already_updated で重複更新を防ぐ。"""
    pref_data = data.get(pref_id, {})
    teams = pref_data.get("teams", [])

    # パス1: 完全一致を優先
    for team in teams:
        existing = team.get("name", "")
        if existing != team_name:
            continue
        key = f"{pref_id}::{existing}"
        if key in already_updated:
            return False
        _apply_stats(team, stats)
        already_updated.add(key)
        print(f"    ✓ 更新: {existing} ({pref_id})")
        return True

    # パス2: 部分一致（控えチームへの誤マッチを防ぐ）
    for team in teams:
        existing = team.get("name", "")
        if not _teams_match(team_name, existing):
            continue
        key = f"{pref_id}::{existing}"
        if key in already_updated:
            return False
        _apply_stats(team, stats)
        already_updated.add(key)
        print(f"    ✓ 更新: {existing} ({pref_id})")
        return True

    return False


def _apply_stats(team: dict, stats: dict) -> None:
    """チームエントリに成績データを適用する。league が stats に含まれる場合は更新する。"""
    team["points"]       = stats["points"]
    team["played"]       = stats["played"]
    team["won"]          = stats["won"]
    team["drawn"]        = stats["drawn"]
    team["lost"]         = stats["lost"]
    team["goalsFor"]     = stats["goalsFor"]
    team["goalsAgainst"] = stats["goalsAgainst"]
    # league名が渡された場合は更新（昇格・降格後の表示を自動修正）
    if stats.get("league"):
        team["league"] = stats["league"]
    # leagueRank（プリンス/プレミア等、リーグ内での順位）が渡されたら上書き
    if "leagueRank" in stats:
        team["leagueRank"] = stats["leagueRank"]


def recalculate_ranks(data: dict) -> None:
    """各都道府県内でポイント順に順位を再計算する"""
    for pref_id, pref_data in data.items():
        teams = pref_data.get("teams", [])
        # ポイント降順 → 得失点差降順 → 得点降順
        sorted_teams = sorted(
            teams,
            key=lambda t: (
                -t.get("points", 0),
                -(t.get("goalsFor", 0) - t.get("goalsAgainst", 0)),
                -t.get("goalsFor", 0)
            )
        )
        for i, team in enumerate(sorted_teams, 1):
            team["rank"] = i
            team["prefectureRank"] = i
        pref_data["teams"] = sorted_teams


# 各都道府県の県リーグURL（HTMLテーブルが確認できたもののみ掲載）
# juniorsoccer-news.com は画像/テキスト形式でテーブルなし → 除外
PREF_LEAGUE_URLS: dict[str, list[str]] = {
    "hokkaido":  ["https://junior-soccer.jp/hokkaido/hokkaido/league/order/163368"],
    "aomori":    ["https://junior-soccer.jp/tohoku/aomori/league/order/163886"],
    "iwate":     ["https://junior-soccer.jp/tohoku/iwate/league/order/164020",
                  "https://www.goalnote.net/detail-standings.php?tid=18702"],
    "akita":     ["https://junior-soccer.jp/tohoku/akita/league/order/163671"],
    "yamagata":  ["https://junior-soccer.jp/tohoku/yamagata/league/order/163965",
                  "https://www.goalnote.net/detail-standings.php?tid=18649"],
    "fukushima": ["https://junior-soccer.jp/tohoku/fukushima/league/order/163405"],
    "yamagata":  ["https://www.goalnote.net/detail-standings.php?tid=18649"],
    "ibaraki":   ["https://junior-soccer.jp/kanto/ibaraki/league/order/163357",
                  "https://www.goalnote.net/detail-standings.php?tid=18463"],
    "tochigi":   ["https://junior-soccer.jp/kanto/tochigi/league/order/163569",
                  "https://api.lsin.jp/?m=r&e=1059&c=3"],
    "gunma":     ["https://junior-soccer.jp/kanto/gunma/league/order/163348",
                  "https://management.gunma-fa.com/api/table/173#439"],
    "chiba":     ["https://junior-soccer.jp/kanto/chiba/league/order/163436",
                  "https://www.goalnote.net/detail-standings.php?tid=18441"],
    "saitama":   ["https://junior-soccer.jp/kanto/saitama/league/order/163779"],
    "tokyo":     ["https://junior-soccer.jp/kanto/tokyo/league/order/163371",
                  "https://www.tleague-u18.com/rank.php?dy=2026&dt=1&ltno=16"],
    "kanagawa":  ["https://junior-soccer.jp/kanto/kanagawa/league/order/163423",
                  "https://www.kanagawa-fa.gr.jp/cms/u18-league/2026/div1/"],
    "yamanashi": ["https://junior-soccer.jp/kanto/yamanashi/league/order/163809"],
    "niigata":   ["https://junior-soccer.jp/hokushinetsu/niigata/league/order/163784"],
    "toyama":    ["https://junior-soccer.jp/hokushinetsu/toyama/league/order/164007",
                  "https://www.taikai-go.com/tournaments/82/standings"],
    "ishikawa":  ["https://junior-soccer.jp/hokushinetsu/ishikawa/league/order/163986"],
    "fukui":     ["https://junior-soccer.jp/hokushinetsu/fukui/league/order/163632"],
    "nagano":    ["https://junior-soccer.jp/hokushinetsu/nagano/league/order/163461"],
    "gifu":      ["https://junior-soccer.jp/tokai/gifu/league/order/163412"],
    "shizuoka":  ["https://junior-soccer.jp/tokai/shizuoka/league/order/163487"],
    "aichi":     ["https://junior-soccer.jp/tokai/aichi/league/order/162912", "https://www.goalnote.net/detail-standings.php?tid=18269"],
    "mie":       ["https://junior-soccer.jp/tokai/mie/league/order/163696"],
    "shiga":     ["https://junior-soccer.jp/kansai/shiga/league/order/163309", "https://shiga-fa-u18.com/order/1"],
    "kyoto":     ["https://junior-soccer.jp/kansai/kyoto/league/order/163399"],
    "osaka":     ["https://junior-soccer.jp/kansai/osaka/league/order/163328", "http://www.ofa-tec.jp/gm/gmresult.cgi?tsl=170"],
    "hyogo":     ["https://junior-soccer.jp/kansai/hyogo/league/order/163634"],
    "nara":      ["https://junior-soccer.jp/kansai/nara/league/order/163879"],
    "wakayama":  ["https://junior-soccer.jp/kansai/wakayama/league/order/163380"],
    "tottori":   ["https://junior-soccer.jp/chugoku/tottori/league/order/163929"],
    "shimane":   ["https://junior-soccer.jp/chugoku/shimane/league/order/163918"],
    "okayama":   ["https://junior-soccer.jp/chugoku/okayama/league/order/163763"],
    "hiroshima": ["https://junior-soccer.jp/chugoku/hiroshima/league/order/163654"],
    "yamaguchi": ["https://junior-soccer.jp/chugoku/yamaguchi/league/order/163777"],
    "tokushima": ["https://junior-soccer.jp/shikoku/tokushima/league/order/163670"],
    "kagawa":    ["https://junior-soccer.jp/shikoku/kagawa/league/order/163930"],
    "ehime":     ["https://junior-soccer.jp/shikoku/ehime/league/order/163579"],
    "kochi":     ["https://junior-soccer.jp/shikoku/kochi/league/order/163885"],
    "fukuoka":   ["https://junior-soccer.jp/kyushu/fukuoka/league/order/163495"],
    "saga":      ["https://saga-fa-u18.com/order/1/2026"],
    "nagasaki":  ["https://junior-soccer.jp/kyushu/nagasaki/league/order/163666"],
    "kumamoto":  ["https://junior-soccer.jp/kyushu/kumamoto/league/order/163566"],
    "oita":      ["https://junior-soccer.jp/kyushu/oita/league/order/163920"],
    "miyazaki":  ["https://junior-soccer.jp/kyushu/miyazaki/league/order/163363"],
    "kagoshima": ["https://junior-soccer.jp/kyushu/kagoshima/league/order/163821"],
    "okinawa":   ["https://junior-soccer.jp/kyushu/okinawa/league/order/164083"],
}


def scrape_pref_leagues(data: dict, already_updated: set[str]) -> int:
    """
    各都道府県の県リーグURLを取得し、teams.json を更新する。
    league フィールドは上書きしない（既存の県リーグ名を保持）。
    goalnote / tleague / fa-u18.com など複数フォーマットに対応。
    """
    total = 0
    for pref_id, urls in PREF_LEAGUE_URLS.items():
        pref_name = PREF_ID_TO_NAME.get(pref_id, pref_id)
        print(f"\n  [{pref_name}] 県リーグ取得中...")
        soup = None
        for url in urls:
            print(f"    URL: {url}")
            try:
                resp = requests.get(url, headers=HEADERS, timeout=12)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding
                candidate = BeautifulSoup(resp.text, "html.parser")
                if candidate.find("table"):
                    soup = candidate
                    break
                print("    → テーブルなし、次のURLへ")
            except Exception as e:
                print(f"    → 取得失敗: {e}")

        if soup is None:
            # Selenium フォールバック（最初のURLのみ）
            if urls:
                soup = _fetch_with_selenium(urls[0])

        if soup is None or not soup.find("table"):
            print(f"    ⚠ {pref_name}: テーブル取得失敗、スキップ")
            time.sleep(0.5)
            continue

        standings = parse_standing_table(soup)
        print(f"    取得チーム数: {len(standings)}")
        for s in standings:
            # league / leagueRank フィールドを含めない
            # （県リーグの順位は recalculate_ranks でリーグ全体から計算するため）
            s_no_league = {k: v for k, v in s.items() if k not in ("league", "leagueRank")}
            if update_team_stats(data, pref_id, s["name"], s_no_league, already_updated):
                total += 1
        time.sleep(0.8)

    return total


def scrape_and_update(year: int, dry_run: bool = False) -> int:
    """メイン処理: スクレイピングしてteams.jsonを更新"""
    print(f"\n===== 高円宮杯 {year} データ取得開始 =====")
    print(f"データファイル: {DATA_FILE}")

    # 既存データ読み込み
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_updated = 0
    already_updated: set[str] = set()   # 重複更新防止用
    league_urls = find_league_urls(year)

    def _process_premier(division_label, urls, league_name):
        nonlocal total_updated
        for url in urls:
            print(f"  URL: {url}")
            soup = fetch_page(url)
            if not soup:
                print("  ⚠ 取得失敗、スキップします")
                continue
            standings = parse_standing_table(soup)
            print(f"  取得チーム数: {len(standings)}")
            for s in standings:
                s["league"] = league_name  # league名も更新
                pref_id = None
                for key, pid in PREMIER_TEAM_PREF.items():
                    if key in s["name"]:
                        pref_id = pid
                        break
                if not pref_id:
                    pref_id = match_team_to_pref(s["name"], list(data.keys()), data)
                if pref_id and update_team_stats(data, pref_id, s["name"], s, already_updated):
                    total_updated += 1
            time.sleep(1)

    # --- プレミアリーグ EAST ---
    print("\n[1/3] プレミアリーグ EAST を取得中...")
    _process_premier("EAST", league_urls["premier_east"], "プレミアリーグEAST")

    # --- プレミアリーグ WEST ---
    print("\n[2/3] プレミアリーグ WEST を取得中...")
    _process_premier("WEST", league_urls["premier_west"], "プレミアリーグWEST")

    # --- プリンスリーグ (各地域・1部/2部を個別に処理) ---
    print("\n[3/4] プリンスリーグ (全9地域) を取得中...")
    for region_key, url in league_urls["prince"].items():
        candidate_prefs = PRINCE_REGION_PREFS.get(region_key, [])
        region_name = REGION_DISPLAY_NAMES.get(region_key, region_key)
        print(f"\n  地域: {region_key} / {region_name}")
        print(f"  URL: {url}")

        divisions = fetch_prince_divisions(url, region_key)
        if not divisions:
            print("  ⚠ 取得失敗、スキップします")
            continue

        for soup, league_name in divisions:
            standings = parse_standing_table(soup)
            print(f"  [{league_name}] 取得チーム数: {len(standings)}")
            for s in standings:
                s["league"] = league_name  # league名も更新
                pref_id = match_team_to_pref(s["name"], candidate_prefs, data)
                if pref_id and update_team_stats(data, pref_id, s["name"], s, already_updated):
                    total_updated += 1
        time.sleep(1)

    # --- 県リーグ (各都道府県・テーブル取得可能な21県) ---
    print("\n[4/4] 県リーグ (各都道府県) を取得中...")
    pref_updated = scrape_pref_leagues(data, already_updated)
    total_updated += pref_updated
    print(f"\n  県リーグ更新チーム数: {pref_updated}")

    # 順位再計算
    print(f"\n順位を再計算中... ({len(data)} 都道府県)")
    recalculate_ranks(data)

    # 更新日時を記録
    data["_meta"] = {
        "lastUpdated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "year": year,
        "updatedCount": total_updated,
    }

    if dry_run:
        print(f"\n[DRY RUN] {total_updated} チームを更新予定 (保存しません)")
    else:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 完了: {total_updated} チームを更新し、{DATA_FILE} に保存しました")

    return total_updated


def main():
    parser = argparse.ArgumentParser(description="高円宮杯 U-18 順位自動更新スクリプト")
    parser.add_argument("--year", type=int, default=datetime.now().year,
                        help="対象年度 (デフォルト: 今年)")
    parser.add_argument("--dry-run", action="store_true",
                        help="実際には保存せずテスト実行")
    args = parser.parse_args()

    updated = scrape_and_update(year=args.year, dry_run=args.dry_run)
    sys.exit(0 if updated >= 0 else 1)


if __name__ == "__main__":
    main()
