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
    "okinawa": "沖縄"
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
# [P1-8] 長野県は北信越プリンスリーグ所属 (関東から移動)
PRINCE_REGION_PREFS = {
    "hokkaido": ["hokkaido"],
    "tohoku": ["aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima"],
    "kanto": ["ibaraki", "tochigi", "gunma", "saitama", "chiba", "tokyo", "kanagawa", "yamanashi"],
    "hokushinetsu": ["niigata", "toyama", "ishikawa", "fukui", "nagano"],
    "tokai": ["shizuoka", "aichi", "mie", "gifu"],
    "kansai": ["shiga", "kyoto", "osaka", "hyogo", "nara", "wakayama"],
    "chugoku": ["tottori", "shimane", "okayama", "hiroshima", "yamaguchi"],
    "shikoku": ["tokushima", "kagawa", "ehime", "kochi"],
    "kyushu": ["fukuoka", "saga", "nagasaki", "kumamoto", "oita", "miyazaki", "kagoshima", "okinawa"],
}

JFA_BASE = "https://www.jfa.jp"

# 1部・2部に分かれている地域リーグ
REGIONS_WITH_DIVISIONS = {"kanto", "kansai", "kyushu", "hokushinetsu"}


# [P1-10] JFA側の略称 → teams.json の正式名称
# JFAの順位表で使われる省略形を、こちらのデータで使う正式名に変換する辞書。
# スクレイピング直後に _resolve_alias() で名前を書き換え、
# そのあとの match_team_to_pref で該当の都道府県チームとちゃんと紐付く。
TEAM_ALIASES: dict[str, str] = {
    # --- 関西 (大学名略称) ---
    "関大北陽":                 "関西大学北陽高校",
    "産大附属":                 "大阪産業大学附属高校",
    # --- 東北 ---
    "青森山田高校セカンド":     "青森山田高校2nd",
    "青森山田セカンド":         "青森山田高校2nd",
    "専修大北上高校":           "専修大学北上高校",
    "専修大北上":               "専修大学北上高校",
    # --- 東北 (追加分・宮城県1部対応) ---
    "聖和学園II":               "聖和学園高校2nd",
    "ベガルタII":               "ベガルタ仙台ユース2nd",
    "東北学院II":               "東北学院高校2nd",
    "東北生文大":               "東北生活文化大学高校",
    "東北":                     "東北高校",
    # --- 宮城県1部「II / Ⅱ」両対応 ---
    "聖和学園Ⅱ":               "聖和学園高校2nd",
    "聖和学園II":               "聖和学園高校2nd",
    "ベガルタⅡ":               "ベガルタ仙台ユース2nd",
    "ベガルタII":               "ベガルタ仙台ユース2nd",
    "東北学院Ⅱ":               "東北学院高校2nd",
    "東北学院II":               "東北学院高校2nd",
    # --- 九州 (大学名略称 / 「学」「付/附属」の揺れ) ---
    "東海大熊本星翔高校":       "東海大学付属熊本星翔高校",
    "東海大熊本星翔":           "東海大学付属熊本星翔高校",
    "九州国際大学付属高校":     "九州国際大付属高校",
    "九州国際大付":             "九州国際大付属高校",
    # JFA九州2部は「東海大福岡高校」と略記される (teams.json は「東海大学付属福岡高校」)
    "東海大福岡高校":           "東海大学付属福岡高校",
    "東海大福岡":               "東海大学付属福岡高校",
    # --- 北信越 (Jクラブ下部 U-18 の「地名U18」略称) ---
    # JFA北信越1部/2部は J下部 U-18 を「地名U18」と略記するため、正式クラブ名に戻す
    "新潟U18":                  "アルビレックス新潟U-18",
    "松本U18":                  "松本山雅FC U-18",
    "富山U18":                  "カターレ富山U-18",
    "金沢U18":                  "ツエーゲン金沢U-18",
    "長野U18":                  "AC長野パルセイロU-18",
    # --- 東北 (秋田) ---
    "BB2nd":                    "ブラウブリッツ秋田U-18 2nd",
    "ブラウブリッツ秋田U-18B":  "ブラウブリッツ秋田U-18 2nd",

    # --- 東北 (福島) ---
    "尚志セカンド":             "尚志高校2nd",
    "学法石川セカンド":         "学法石川高校2nd",
    "帝京安積セカンド":         "帝京安積高校2nd",

    # --- 関東 (茨城) ---
    "明秀日立A":                "明秀学園日立高校",
    "鹿島アントラーズユースB":  "鹿島アントラーズユース2nd",
    "鹿島学園B":                "鹿島学園高校2nd",
    "第一学院A":                "第一学院高校",
    "東洋大牛久A":              "東洋大牛久高校",
    "霞ヶ浦A":                  "霞ヶ浦高校",
    "水戸啓明A":                "水戸啓明高校",
    "牛久栄進A":                "牛久栄進高校",
    "水戸葵陵A":                "水戸葵陵高校",
    "鹿島A":                    "鹿島高校",
    "水戸ホーリーホックユースA": "水戸ホーリーホックユース",

    # --- 関東 (神奈川・栃木) ---
    "湘南工科大附Ａ":           "湘南工科大学附属高校",
    "湘南工科大附A":            "湘南工科大学附属高校",
    "日大藤沢B":                "日本大学藤沢高校2nd",
    "日大藤沢高校2nd":          "日本大学藤沢高校2nd",
    "栃木SC U-18B":             "栃木SC U-18 2nd",
    "栃木SC B":                 "栃木SC U-18 2nd",
    "文星芸大附":               "文星芸術大学附属高校",

    # --- 関東 (東京・群馬) ---
    "帝京B":                    "帝京高校2nd",
    "FC東京B":                  "FC東京U-18 2nd",
    "健大高崎":                 "高崎健康福祉大学高崎高校",
    "高経大附属":               "高崎経済大学附属高校",

    # --- 北信越・東海 (石川・岐阜・愛知・静岡) ---
    "金沢学院2nd":              "金沢学院大学附属高校2nd",
    "帝京可児B":                "帝京大学可児高校2nd",
    "グランパスB":              "名古屋グランパスU-18 2nd",
    "日福大付":                 "日本福祉大学付属高校",
    "藤枝明誠②":               "藤枝明誠高校2nd",
    "藤枝明誠2nd":              "藤枝明誠高校2nd",

    # --- 関西 (大阪・兵庫・京都・滋賀) ---
    "履正社B":                  "履正社高校2nd",
    "興國B":                    "興國高校2nd",
    "近大附属":                 "近畿大学附属高校",
    "滝川第二B":                "滝川第二高校2nd",
    "三田学園B":                "三田学園高校2nd",
    "神戸科技A":                "神戸科学技術高校",
    "神戸国際附A":              "神戸国際附属高校",
    "神戸弘陵B":                "神戸弘陵学園高校2nd",
    "京都橘B":                  "京都橘高校2nd",
    "京都橘C":                  "京都橘高校3rd",
    "東山B":                    "東山高校2nd",
    "近江C":                    "近江高校3rd",

    # --- 中国 (鳥取・島根・岡山・広島) ---
    "米子北B":                  "米子北高校2nd",
    "大社B":                    "大社高校2nd",
    "立正大淞南B":              "立正大学淞南高校2nd",
    "岡山学芸館B":              "岡山学芸館高校2nd",
    "玉野光南B":                "玉野光南高校2nd",
    "就実B":                    "就実高校2nd",
    "ファジ岡山U-18B":          "ファジアーノ岡山U-18 2nd",
    "作陽B":                    "作陽学園高校2nd",
    "瀬戸内セカンド":           "広島瀬戸内高校2nd",

    # --- 四国 (徳島・香川・愛媛・高知) ---
    "徳島商業S":                "徳島商業高校2nd",
    "徳島ヴォルティスS":        "徳島ヴォルティスユース2nd",
    "徳島市立S":                "徳島市立高校2nd",
    "大手前高松S":              "大手前高松高校2nd",
    "カマタマーレ讃岐S":        "カマタマーレ讃岐U-18 2nd",
    "愛媛FCU-18S":              "愛媛FC U-18 2nd",
    "愛媛FCU-18 S":             "愛媛FC U-18 2nd",
    "FC今治U-18S":              "FC今治U-18 2nd",
    "今治東S":                  "県立今治東中等教育学校 2nd",
    "高知S":                    "高知高校2nd",

    # --- 九州 (福岡・熊本・大分) ---
    "東福岡B":                  "東福岡高校2nd",
    "アビスパ福岡B":            "アビスパ福岡U-18 2nd",
    "福大若葉":                 "福岡大学附属若葉高校",
    "福大大濠":                 "福岡大学附属大濠高校",
    "東海大福岡B":              "東海大学付属福岡高校2nd",
    "学園大付":                 "熊本学園大学付属高校",
    "ロアッソ2nd":              "ロアッソ熊本U-18_2nd",
    "トリニータ2nd":            "大分トリニータU-18_2nd",
    "宮崎日大":                 "宮崎日本大学高校",

    # --- 千葉 ---
    "レイソルU-18B":            "柏レイソルU-18 2nd",
    # --- 関東 (栃木・神奈川) 追加分 ---
    "矢板中央B":                "矢板中央高校2nd",
    "桐光学園B":                "桐光学園高校2nd",
    "桐蔭学園B":                "桐蔭学園高校2nd",
    # --- 追加分（プリンスリーグ系の漏れ）---
    "流通経済大学付属柏Ｂ":       "流通経済大学付属柏高校2nd",
    "流経大柏B":                "流通経済大学付属柏高校2nd",
    "流経大柏2nd":              "流通経済大学付属柏高校2nd",
    "近江B":                    "近江高校2nd",
    "京都橘B":                  "京都橘高校2nd",
    "ヴィッセル神戸B":          "ヴィッセル神戸U-18 2nd",
    "神戸U-18 2nd":             "ヴィッセル神戸U-18 2nd",
    "ヴィッセル神戸U18 2nd":    "ヴィッセル神戸U-18 2nd",

    # --- 県リーグ系の漏れ ---
    "金沢U18 2nd":              "ツエーゲン金沢U-18 2nd",
    "金沢U18B":                 "ツエーゲン金沢U-18 2nd",
    "ツエーゲン金沢2nd":          "ツエーゲン金沢U-18 2nd",
    "四日市中央工業":           "四日市中央工業高校",
    "四中工":                   "四日市中央工業高校",
    "広島FCユース2nd":          "サンフレッチェ広島F.C.ユース 2nd",
    "サンフレッチェB":          "サンフレッチェ広島F.C.ユース 2nd",
    "広島ユースB":              "サンフレッチェ広島F.C.ユース 2nd",
    "サンフレセカンド":          "サンフレッチェ広島F.C.ユース 2nd",
    "高川学園B":                "高川学園高校2nd",
}


def _resolve_alias(name: str) -> str:
    """[P1-10] JFAでの略称を teams.json 用の正式名に変換する。未登録なら素通し。"""
    return TEAM_ALIASES.get(name, name)


# ヘッダー検出に使うキーワードセット（標準化のため外に定義）
_HEADER_HINTS = {
    'チーム名', 'クラブ名', 'チーム', 'クラブ',
    '勝点', '勝ち点', '試合数', '試合',
    '勝', '勝利', '勝数', '引分', '引き分け', '引分数', '引',
    '負', '敗', '敗戦', '敗数',
    '得点', '失点', '得失点差', '得失差', '得失点',
}


def _is_standings_table(table) -> bool:
    """
    与えられた <table> 要素が「順位表」っぽいか判定する。
    最初の5行のどれかに「チーム名」「勝点」などのヘッダーキーワードが2つ以上含まれるか見る。
    """
    rows = table.find_all("tr")
    if len(rows) < 2:
        return False
    for row in rows[:5]:
        cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        score = sum(1 for c in cols if c.strip() in _HEADER_HINTS)
        if score >= 2:
            return True
    return False


def _find_standings_tables(soup: BeautifulSoup) -> list:
    """
    ページ内の順位表テーブルを **すべて** 見つけて、各テーブルを個別の BeautifulSoup として返す。
    [P1-5] 関東・関西・九州・北信越は同じページに 1部と2部が並んで載っていることがあるため、
           すべての順位表をテーブル単位で分離する。
    """
    result = []
    for table in soup.find_all("table"):
        if _is_standings_table(table):
            wrapper = BeautifulSoup(str(table), "html.parser")
            result.append(wrapper)
    return result


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


def fetch_prince_divisions(url: str, region_key: str) -> list[tuple]:
    """
    プリンスリーグのURLを取得し、[(soup, league_name), ...] を返す。
    [P1-1/P1-4/P1-5] 1ページ内に複数の順位表 (1部/2部) がある場合は個別に分けて返す。
    - 関東・関西・九州・北信越 (REGIONS_WITH_DIVISIONS): 1部/2部を分離する
    - その他 (東海・中国・四国・北海道・東北): 単一リーグ扱い
    """
    region_name = REGION_DISPLAY_NAMES.get(region_key, region_key)
    results = []

    def _assign_labels(standings_soups):
        """順位表 soup のリストから [(soup, league_name), ...] を作る"""
        out = []
        if not standings_soups:
            return out
        if region_key in REGIONS_WITH_DIVISIONS:
            if len(standings_soups) >= 2:
                out.append((standings_soups[0], f"プリンスリーグ{region_name}1部"))
                out.append((standings_soups[1], f"プリンスリーグ{region_name}2部"))
            else:
                out.append((standings_soups[0], f"プリンスリーグ{region_name}1部"))
        else:
            out.append((standings_soups[0], f"プリンスリーグ{region_name}"))
        return out

    # --- まず requests で試みる ---
    requests_soup = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")
            standings_tables = _find_standings_tables(soup)
            if standings_tables:
                labeled = _assign_labels(standings_tables)
                # 分割地域なのに表が1つだけなら Selenium でタブクリック試行
                if region_key in REGIONS_WITH_DIVISIONS and len(standings_tables) < 2:
                    requests_soup = soup
                    break
                return labeled
            print("  順位表テーブルが見つかりません。JSレンダリングが必要かもしれません。")
            break
        except requests.RequestException as e:
            print(f"  取得失敗 (試行 {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2)

    # --- Selenium フォールバック (1部・2部タブ両対応) ---
    if not SELENIUM_AVAILABLE:
        print("  Selenium が利用できません。")
        if requests_soup is not None:
            standings_tables = _find_standings_tables(requests_soup)
            return _assign_labels(standings_tables)
        return results

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

        soup1 = BeautifulSoup(driver.page_source, "html.parser")
        tables1 = _find_standings_tables(soup1)

        if region_key in REGIONS_WITH_DIVISIONS and len(tables1) >= 2:
            results.append((tables1[0], f"プリンスリーグ{region_name}1部"))
            results.append((tables1[1], f"プリンスリーグ{region_name}2部"))
            print(f"    → 同ページ上に1部/2部テーブルを検出 (プリンスリーグ{region_name}1部 + 2部)")
            return results

        if region_key in REGIONS_WITH_DIVISIONS:
            div2_xpaths = [
                "//button[contains(text(),'2部')]",
                "//a[contains(text(),'2部')]",
                "//li/a[contains(text(),'2部')]",
                "//*[contains(@class,'tab') and contains(text(),'2部')]",
            ]
            found_div2 = False
            for xpath in div2_xpaths:
                try:
                    tab = driver.find_element(By.XPATH, xpath)
                    driver.execute_script("arguments[0].click();", tab)
                    time.sleep(2)
                    soup2 = BeautifulSoup(driver.page_source, "html.parser")
                    tables2 = _find_standings_tables(soup2)
                    if tables1 and tables2:
                        results.append((tables1[0], f"プリンスリーグ{region_name}1部"))
                        results.append((tables2[0], f"プリンスリーグ{region_name}2部"))
                        print(f"    → 2部タブを検出しました (プリンスリーグ{region_name}1部 + 2部)")
                        found_div2 = True
                    break
                except Exception:
                    continue

            if not found_div2 and tables1:
                results.append((tables1[0], f"プリンスリーグ{region_name}1部"))
        else:
            if tables1:
                results.append((tables1[0], f"プリンスリーグ{region_name}"))

    except Exception as e:
        print(f"  Selenium 取得失敗: {e}")
    finally:
        if driver:
            driver.quit()

    return results


def fetch_page(url: str, retries: int = 3) -> BeautifulSoup | None:
    """JFAサイトのページを取得する（requests → Selenium フォールバック）"""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")
            if soup.find("table"):
                return soup
            print("  テーブルが見つかりません。JSレンダリングが必要かもしれません。")
            break
        except requests.RequestException as e:
            print(f"  取得失敗 (試行 {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)

    return _fetch_with_selenium(url)


def _clean_team_name(name: str) -> str:
    """チーム名から末尾の都道府県表記 (例: '(千葉県)') を除去する。
    [P1-9b] 括弧内に「県/都/府/道」を含む場合のみ除去する。
            '(2nd)' '(B)' などの控えチームマーカーは保持する。
    """
    # 全角括弧と半角括弧の両方に対応。中身に 県/都/府/道 を含むもののみ削除。
    return re.sub(
        r'\s*(?:（[^）]*[県都府道][^）]*）|\([^)]*[県都府道][^)]*\))',
        '',
        name,
    ).strip()


def _detect_col_indices(header_cols: list[str]) -> dict:
    """
    ヘッダー行からフィールド→列インデックスのマッピングを返す。
    完全一致を優先し、「勝点平均」などの複合語に誤マッチしないようにする。
    """
    mapping = {}
    field_specs = [
        ("name",         ["チーム名", "クラブ名", "チーム", "クラブ"], ["club", "team"]),
        ("points",       ["勝点", "勝ち点"],                           ["pts", "pt", "points"]),
        ("played",       ["試合数", "試合"],                           ["mp", "games", "played"]),
        ("won",          ["勝", "勝利", "勝数", "勝利数"],             ["win", "wins"]),
        ("drawn",        ["分", "引分", "引き分け", "ドロー", "引分数", "引"], ["draw", "draws"]),
        ("lost",         ["負", "敗", "敗戦", "敗北", "敗数", "敗戦数"], ["loss", "lose"]),
        ("goalsFor",     ["得点"],                                      ["gf"]),
        ("goalsAgainst", ["失点"],                                      ["ga"]),
        ("goalDiff",     ["得失点差", "得失差", "得失点"],              ["得失", "gd"]),
    ]

    for idx, header in enumerate(header_cols):
        h = header.strip()
        for field, exact_kws, _ in field_specs:
            if field not in mapping and h in exact_kws:
                mapping[field] = idx
                break

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
    """JFAの順位表テーブルをパースする"""
    results = []
    seen_names: set[str] = set()

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        best_i, best_score = 0, 0
        for i, row in enumerate(rows[:5]):
            cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            score = sum(1 for c in cols if c.strip() in _HEADER_HINTS)
            if score > best_score:
                best_i, best_score = i, score
        header_row_idx = best_i

        header_cols = [th.get_text(strip=True) for th in rows[header_row_idx].find_all(["th", "td"])]
        col_map = _detect_col_indices(header_cols)

        if "points" not in col_map or "played" not in col_map:
            continue

        offset = 0
        if len(rows) > header_row_idx + 1:
            first_data = [c.get_text(strip=True) for c in rows[header_row_idx + 1].find_all(["td", "th"])]
            diff = len(first_data) - len(header_cols)
            if diff > 0 and first_data and re.match(r'^\d+$', first_data[0].strip()):
                offset = diff
        if offset:
            col_map = {k: v + offset for k, v in col_map.items()}

        for row in rows[header_row_idx + 1:]:
            cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cols) < 5:
                continue
            try:
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
                    val = cols[idx].strip().lstrip('+')
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
                    "leagueRank":   len(results) + 1,
                }
                results.append(record)
                seen_names.add(name)
            except (ValueError, IndexError):
                continue
    return results


def find_league_urls(year: int) -> dict[str, list[str]]:
    """JFAサイトから各リーグのURLを収集する"""
    urls = {"premier_east": [], "premier_west": [], "prince": {}}

    for division in ["east", "west"]:
        url = f"{JFA_BASE}/match/takamado_jfa_u18_premier{year}/{division}/standings/"
        urls[f"premier_{division}"].append(url)

    prince_region_urls = {
        "hokkaido":     f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/hokkaido/",
        "tohoku":       f"https://www.jfa.jp/match_47fa/102_tohoku/takamado_jfa_u18_prince{year}/thfa/ranking.html",
        "kanto":        f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/kanto/",
        "hokushinetsu": f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/hokushinetsu/",
        "tokai":        f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/tokai/",
        "kansai":       f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/kansai/",
        "chugoku":      f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/chugoku/",
        "shikoku":      f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/shikoku/",
        "kyushu":       f"{JFA_BASE}/match/takamado_jfa_u18_prince{year}/kyushu/",
    }
    for region_key, url in prince_region_urls.items():
        urls["prince"][region_key] = url

    return urls


# [P1-7] 控えチームを示す末尾キーワード (丸数字・全角Ｂ対応は _is_reserve_team で NFKC)
RESERVE_SUFFIXES = (
    "B", "C", "D",
    "Ⅱ", "Ⅲ", "Ⅳ", "II", "III",
    "2nd", "3rd", "4th",
    "セカンド", "サード", "フォース",
    "2", "3",
    "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
)


def _is_reserve_team(name: str) -> bool:
    """
    チーム名が控えチーム（B・Ⅱ・②・セカンドなど）かどうかを判定する。
    [P1-7] NFKC正規化してから判定するので「藤枝明誠Ｂ」(全角) も「藤枝明誠B」と同じ扱い。
    [P1-8] 末尾の括弧 "(2nd)" "（B）" 等にも対応。
           例: 「旭川実業(2nd)」→ 内側 "2nd" を見て True 判定。
    """
    normalized = unicodedata.normalize('NFKC', name).strip()
    # 末尾の括弧を空白に置換 (例: "旭川実業(2nd)" → "旭川実業 2nd")
    normalized = re.sub(r'[\(]\s*', ' ', normalized)
    normalized = re.sub(r'[\)]\s*$', '', normalized).strip()
    for suffix in RESERVE_SUFFIXES:
        if normalized.endswith(suffix):
            return True
        if normalized.endswith(" " + suffix) or normalized.endswith("　" + suffix):
            return True
    return False


def _name_similarity(a: str, b: str) -> bool:
    """チーム名の類似判定（短縮名や略称に対応）。
    [P1-9] 内部で _normalize_name() を通すので、括弧・全角半角・空白・略字差を吸収する。
    """
    suffixes = ["U-18", "U18", "ユース", "Youth", "高校", "高等学校"]
    a_clean = _normalize_name(a)
    b_clean = _normalize_name(b)
    for s in suffixes:
        a_clean = a_clean.replace(s, "")
        b_clean = b_clean.replace(s, "")
    return bool(a_clean) and bool(b_clean) and (a_clean in b_clean or b_clean in a_clean)


_KANJI_MAP = str.maketrans({
    '國': '国', '學': '学', '體': '体',
    '濱': '浜', '濵': '浜', '澤': '沢',
    '齋': '斉', '齊': '斉', '龍': '竜',
    '廣': '広', '藏': '蔵', '遙': '遥',
    '塚': '塚',
})


def _normalize_name(name: str) -> str:
    """チーム名を比較用に正規化する。
    NFKC正規化・旧字体置換・空白除去・括弧除去を行う。
    """
    name = unicodedata.normalize('NFKC', name)
    name = name.translate(_KANJI_MAP)
    name = name.replace(' ', '').replace('\u3000', '')
    name = name.replace('\u00b7', '・').replace('\uff65', '・')
    # [P1-9] 括弧 "(2nd)" 等を除去 (例: "旭川実業(2nd)" → "旭川実業2nd")
    name = re.sub(r'[()]', '', name)
    return name


def _teams_match(scraped: str, existing: str) -> bool:
    """
    スクレイピング名と既存チーム名が同じチームを指すか判定。
    [P1-6] 1軍↔控えの双方向ブロック: 片方だけが控えなら絶対にマッチしない。
    """
    if scraped == existing:
        return True
    s_norm = _normalize_name(scraped)
    e_norm = _normalize_name(existing)
    if s_norm == e_norm:
        return True
    if _is_reserve_team(scraped) != _is_reserve_team(existing):
        return False
    if s_norm in e_norm or e_norm in s_norm:
        return True
    if scraped in existing or existing in scraped:
        return True
    return _name_similarity(scraped, existing)


def match_team_to_pref(team_name: str, candidate_prefs: list[str], data: dict) -> str | None:
    """
    チーム名を既存データの都道府県チームとマッチングする。
    完全一致を優先し、控えチームへの誤マッチを防ぐ。
    """
    for pref_id in candidate_prefs:
        for team in data.get(pref_id, {}).get("teams", []):
            if team.get("name", "") == team_name:
                return pref_id
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
    auto_create: bool = False,
    default_league: str = "",
) -> bool:
    """teamsデータの特定チームの成績を更新する。already_updated で重複更新を防ぐ。

    auto_create=True のとき、teams.json に未登録のチームを発見したら
    新規エントリを自動追加する（県リーグスクレイピング用）。
    default_league は新規追加時に "league" フィールドへ入れる既定値。
    """
    pref_data = data.get(pref_id, {})
    teams = pref_data.get("teams", [])

    for team in teams:
        existing = team.get("name", "")
        if existing != team_name:
            continue
        key = f"{pref_id}::{existing}"
        if key in already_updated:
            # 同じ pref_id で既に更新済み → 二重更新は不要
            return False
        _apply_stats(team, stats)
        already_updated.add(key)
        print(f"    ✓ 更新: {existing} ({pref_id})")
        return True

    for team in teams:
        existing = team.get("name", "")
        if not _teams_match(team_name, existing):
            continue
        key = f"{pref_id}::{existing}"
        if key in already_updated:
            # ファジーマッチが他のチームに当たった可能性 → 探索継続
            # 例: 「旭川実業(2nd)」が先にプリンスの「旭川実業高校」(更新済) と
            #     誤マッチしても、後ろの「旭川実業高校 2nd」を見つけられるようにする
            continue
        _apply_stats(team, stats)
        already_updated.add(key)
        print(f"    ✓ 更新: {existing} ({pref_id})")
        return True

    # マッチなし：auto_create=True なら新規登録（県リーグ取得時のみ）
    if auto_create:
        if pref_id not in data:
            data[pref_id] = {"teams": []}
            pref_data = data[pref_id]
            teams = pref_data["teams"]
        elif "teams" not in pref_data:
            pref_data["teams"] = []
            teams = pref_data["teams"]

        new_team: dict = {
            "name":         team_name,
            "league":       default_league or stats.get("league", ""),
            "points":       0,
            "played":       0,
            "won":          0,
            "drawn":        0,
            "lost":         0,
            "goalsFor":     0,
            "goalsAgainst": 0,
        }
        # スクレイプ結果の数値を反映（league だけは default_league を保持）
        stats_for_apply = {k: v for k, v in stats.items() if k != "league"}
        _apply_stats(new_team, stats_for_apply)
        teams.append(new_team)
        key = f"{pref_id}::{team_name}"
        already_updated.add(key)
        print(f"    + 新規登録: {team_name} → {pref_id} [{new_team['league']}]")
        return True

    return False


def _apply_stats(team: dict, stats: dict) -> None:
    """チームエントリに成績データを適用する"""
    team["points"]       = stats["points"]
    team["played"]       = stats["played"]
    team["won"]          = stats["won"]
    team["drawn"]        = stats["drawn"]
    team["lost"]         = stats["lost"]
    team["goalsFor"]     = stats["goalsFor"]
    team["goalsAgainst"] = stats["goalsAgainst"]
    if stats.get("league"):
        team["league"] = stats["league"]
    if "leagueRank" in stats and stats["leagueRank"] is not None:
        team["leagueRank"] = stats["leagueRank"]


def recalculate_ranks(data: dict) -> None:
    """各都道府県内でポイント順に順位を再計算する"""
    for pref_id, pref_data in data.items():
        if pref_id == "_meta":
            continue
        teams = pref_data.get("teams", [])
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


PREF_LEAGUE_URLS: dict[str, list[str]] = {
    "hokkaido":  ["https://junior-soccer.jp/hokkaido/hokkaido/league/order/163368"],
    "aomori":    ["https://junior-soccer.jp/tohoku/aomori/league/order/163886"],
    "iwate":     ["https://junior-soccer.jp/tohoku/iwate/league/order/164020",
                  "https://www.goalnote.net/detail-standings.php?tid=18702"],
    "akita":     ["https://junior-soccer.jp/tohoku/akita/league/order/163671"],
    "yamagata":  ["https://junior-soccer.jp/tohoku/yamagata/league/order/163965",
                  "https://www.goalnote.net/detail-standings.php?tid=18649"],
    "miyagi":    ["https://junior-soccer.jp/tohoku/miyagi/league/order/163782"],
    "fukushima": ["https://junior-soccer.jp/tohoku/fukushima/league/order/163405"],
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
    """各都道府県の県リーグURLを取得し、teams.json を更新する (league上書きしない)"""
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

        if soup is None and urls:
            soup = _fetch_with_selenium(urls[0])

        if soup is None or not soup.find("table"):
            print(f"    ⚠ {pref_name}: テーブル取得失敗、スキップ")
            time.sleep(0.5)
            continue

        standings = parse_standing_table(soup)
        print(f"    取得チーム数: {len(standings)}")
        # 既存チームの league 名（あれば）を新規登録のデフォルトに使う
        # これによりプリンス所属チームの league 名は上書きされず、
        # 新規追加される県リーグチームには正しい県リーグ名が付与される
        existing_pref_league = ""
        for t in data.get(pref_id, {}).get("teams", []):
            lg = t.get("league", "")
            if lg and "プリンス" not in lg and "プレミア" not in lg:
                existing_pref_league = lg
                break
        for s in standings:
            # 県リーグでもエイリアスを解決 (例: "関大北陽" → "関西大学北陽高校")
            s["name"] = _resolve_alias(s["name"])
            s_no_league = {k: v for k, v in s.items() if k != "league"}
            scraped_league = s.get("league", "") or existing_pref_league
            if update_team_stats(
                data, pref_id, s["name"], s_no_league, already_updated,
                auto_create=True,
                default_league=scraped_league,
            ):
                total += 1
        time.sleep(0.8)

    return total


def scrape_and_update(year: int, dry_run: bool = False) -> int:
    """メイン処理: スクレイピングしてteams.jsonを更新"""
    print(f"\n===== 高円宮杯 {year} データ取得開始 =====")
    print(f"データファイル: {DATA_FILE}")

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_updated = 0
    already_updated: set[str] = set()
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
                # [P1-10] エイリアス解決
                s["name"] = _resolve_alias(s["name"])
                s["league"] = league_name
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

    print("\n[1/4] プレミアリーグ EAST を取得中...")
    _process_premier("EAST", league_urls["premier_east"], "プレミアリーグEAST")

    print("\n[2/4] プレミアリーグ WEST を取得中...")
    _process_premier("WEST", league_urls["premier_west"], "プレミアリーグWEST")

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
                # [P1-10] エイリアス解決 (北信越の "新潟U18" → "アルビレックス新潟U-18" など)
                s["name"] = _resolve_alias(s["name"])
                s["league"] = league_name
                pref_id = match_team_to_pref(s["name"], candidate_prefs, data)
                if pref_id and update_team_stats(data, pref_id, s["name"], s, already_updated):
                    total_updated += 1
        time.sleep(1)

    print("\n[4/4] 県リーグ (各都道府県) を取得中...")
    pref_updated = scrape_pref_leagues(data, already_updated)
    total_updated += pref_updated
    print(f"\n  県リーグ更新チーム数: {pref_updated}")

    print(f"\n順位を再計算中... ({len(data)} 都道府県)")
    recalculate_ranks(data)

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
