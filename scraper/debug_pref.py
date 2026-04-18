#!/usr/bin/env python3
"""
県リーグURLの診断スクリプト
各URLにアクセスしてHTMLテーブルが取得できるか確認します。

使い方:
  python scraper/debug_pref.py              # 全県チェック
  python scraper/debug_pref.py --pref tokyo # 特定の県だけ
  python scraper/debug_pref.py --show tokyo # テーブルの内容も表示
"""

import sys
import time
import argparse
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# 各都道府県の候補URL（先頭から順に試す）
PREF_LEAGUE_URLS = {
    "hokkaido": [
        "https://www.juniorsoccer-news.com/post-1901428",
    ],
    "aomori": [
        "https://www.juniorsoccer-news.com/post-1901545",
    ],
    "iwate": [
        "https://www.goalnote.net/detail-standings.php?tid=18702",
        "https://www.juniorsoccer-news.com/post-1901508",
    ],
    "miyagi": [
        "https://www.juniorsoccer-news.com/post-1901509",
    ],
    "akita": [
        "https://www.juniorsoccer-news.com/post-1901538",
    ],
    "yamagata": [
        "https://www.goalnote.net/detail-standings.php?tid=18649",
        "https://www.juniorsoccer-news.com/post-1901552",
    ],
    "fukushima": [
        "https://www.juniorsoccer-news.com/post-1902469",
    ],
    "ibaraki": [
        "https://www.goalnote.net/detail-standings.php?tid=18463",
        "https://www.juniorsoccer-news.com/post-1901275",
    ],
    "tochigi": [
        "https://api.lsin.jp/?m=r&e=1059&c=3",
        "https://www.juniorsoccer-news.com/post-1905703",
    ],
    "gunma": [
        "https://management.gunma-fa.com/api/table/173#439",
        "https://www.juniorsoccer-news.com/post-1901255",
    ],
    "saitama": [
        "https://www.juniorsoccer-news.com/post-1901283",
    ],
    "chiba": [
        "https://www.goalnote.net/detail-standings.php?tid=18441",
        "https://www.juniorsoccer-news.com/post-1903434",
    ],
    "tokyo": [
        "https://www.tleague-u18.com/rank.php?dy=2026&dt=1&ltno=16",
    ],
    "kanagawa": [
        "https://www.kanagawa-fa.gr.jp/cms/u18-league/2026/div1/",
        "https://www.juniorsoccer-news.com/post-1893297",
    ],
    "yamanashi": [
        "https://www.juniorsoccer-news.com/post-1901595",
    ],
    "niigata": [
        "https://www.juniorsoccer-news.com/post-1901205",
    ],
    "toyama": [
        "https://www.taikai-go.com/tournaments/82/standings",
        "https://www.juniorsoccer-news.com/post-1901201",
    ],
    "ishikawa": [
        "https://www.juniorsoccer-news.com/post-1901210",
    ],
    "fukui": [
        "https://www.juniorsoccer-news.com/post-1901189",
    ],
    "nagano": [
        "https://www.juniorsoccer-news.com/post-1901196",
    ],
    "gifu": [
        "https://www.juniorsoccer-news.com/post-1899410",
    ],
    "shizuoka": [
        "https://www.juniorsoccer-news.com/post-1886173",
    ],
    "aichi": [
        "https://www.goalnote.net/detail-standings.php?tid=18269",
        "https://www.juniorsoccer-news.com/post-1886136",
    ],
    "mie": [
        "https://www.juniorsoccer-news.com/post-1899863",
    ],
    "shiga": [
        "https://shiga-fa-u18.com/order/1",
        "https://www.juniorsoccer-news.com/post-1900100",
    ],
    "kyoto": [
        "https://www.juniorsoccer-news.com/post-1900097",
    ],
    "osaka": [
        "http://www.ofa-tec.jp/gm/gmresult.cgi?tsl=170",
        "https://www.juniorsoccer-news.com/post-1900098",
    ],
    "hyogo": [
        "https://www.juniorsoccer-news.com/post-1902111",
    ],
    "nara": [
        "https://www.juniorsoccer-news.com/post-1900096",
    ],
    "wakayama": [
        "https://www.juniorsoccer-news.com/post-1887751",
    ],
    "tottori": [
        "https://www.goalnote.net/detail-standings.php?tid=18541",
        "https://www.juniorsoccer-news.com/post-1903928",
    ],
    "shimane": [
        "https://www.juniorsoccer-news.com/post-1903927",
    ],
    "okayama": [
        "https://www.juniorsoccer-news.com/post-1908596",
    ],
    "hiroshima": [
        "https://www.juniorsoccer-news.com/post-1907016",
    ],
    "yamaguchi": [
        "https://www.juniorsoccer-news.com/post-1903929",
    ],
    "tokushima": [
        "https://tokushima-fa.jp/post-414/",
        "https://www.juniorsoccer-news.com/post-1899806",
    ],
    "kagawa": [
        "https://www.goalnote.net/detail-standings.php?tid=18633",
        "https://www.juniorsoccer-news.com/post-1899807",
    ],
    "ehime": [
        "https://efa.jp/meeting/44502.html",
        "https://www.juniorsoccer-news.com/post-1900842",
    ],
    "kochi": [
        "https://www.juniorsoccer-news.com/post-1900845",
    ],
    "fukuoka": [
        "https://fukuoka-fa-u18.com/order/groups",
        "https://www.juniorsoccer-news.com/post-1901544",
    ],
    "saga": [
        "https://saga-fa-u18.com/order/1/2026",
        "https://www.juniorsoccer-news.com/post-1900762",
    ],
    "nagasaki": [
        "https://www.juniorsoccer-news.com/post-1900461",
    ],
    "kumamoto": [
        "https://kumamoto-fa.net/league/competition/ranking/?id=1006&category=2%E7%A8%AE",
        "https://www.juniorsoccer-news.com/post-1900781",
    ],
    "oita": [
        "https://www.juniorsoccer-news.com/post-1900464",
    ],
    "miyazaki": [
        "https://miyazaki-fa-u18.net/",
        "https://www.juniorsoccer-news.com/post-1901363",
    ],
    "kagoshima": [
        "https://www.juniorsoccer-news.com/post-1900786",
    ],
    "okinawa": [
        "http://www.okinawa-soccer-habu.com/scores/sheet/161",
        "https://www.juniorsoccer-news.com/post-1901476",
    ],
}

PREF_NAMES = {
    "hokkaido":"北海道","aomori":"青森","iwate":"岩手","miyagi":"宮城",
    "akita":"秋田","yamagata":"山形","fukushima":"福島","ibaraki":"茨城",
    "tochigi":"栃木","gunma":"群馬","saitama":"埼玉","chiba":"千葉",
    "tokyo":"東京","kanagawa":"神奈川","yamanashi":"山梨","niigata":"新潟",
    "toyama":"富山","ishikawa":"石川","fukui":"福井","nagano":"長野",
    "gifu":"岐阜","shizuoka":"静岡","aichi":"愛知","mie":"三重",
    "shiga":"滋賀","kyoto":"京都","osaka":"大阪","hyogo":"兵庫",
    "nara":"奈良","wakayama":"和歌山","tottori":"鳥取","shimane":"島根",
    "okayama":"岡山","hiroshima":"広島","yamaguchi":"山口","tokushima":"徳島",
    "kagawa":"香川","ehime":"愛媛","kochi":"高知","fukuoka":"福岡",
    "saga":"佐賀","nagasaki":"長崎","kumamoto":"熊本","oita":"大分",
    "miyazaki":"宮崎","kagoshima":"鹿児島","okinawa":"沖縄",
}


def try_fetch(url: str, timeout: int = 10) -> BeautifulSoup | None:
    """requestsでURLを取得してBeautifulSoupを返す。失敗はNone。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        return soup
    except Exception as e:
        return None


def check_pref(pref_id: str, show_content: bool = False):
    """1県のURLをチェックして結果を表示"""
    urls = PREF_LEAGUE_URLS.get(pref_id, [])
    pref_name = PREF_NAMES.get(pref_id, pref_id)
    print(f"\n{'='*60}")
    print(f"【{pref_name}】({pref_id})")

    for url in urls:
        print(f"  URL: {url}")
        soup = try_fetch(url)
        if soup is None:
            print("  → ✗ 取得失敗（接続エラーまたはタイムアウト）")
            continue

        tables = soup.find_all("table")
        if not tables:
            print(f"  → △ 取得成功だがHTMLテーブルなし (文字数:{len(soup.get_text())})")
            # テキストの冒頭を表示してどんな内容か確認
            text = soup.get_text()[:300].strip()
            print(f"     テキスト冒頭: {text[:200]}")
            continue

        print(f"  → ✓ テーブル {len(tables)}個 発見！")

        for i, table in enumerate(tables[:2]):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            print(f"     テーブル{i+1} ヘッダー: {headers}")
            if show_content and len(rows) > 1:
                print(f"     データ行例:")
                for row in rows[1:4]:
                    cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                    print(f"       {cols}")
        return  # 最初に成功したURLで終了

    print("  → ✗ 全URLで失敗")


def main():
    parser = argparse.ArgumentParser(description="県リーグURL診断スクリプト")
    parser.add_argument("--pref", type=str, help="特定の県のみチェック (例: tokyo)")
    parser.add_argument("--show", type=str, help="テーブル内容も表示する県 (例: tokyo)")
    args = parser.parse_args()

    target = args.pref or args.show
    show = bool(args.show)

    if target:
        if target not in PREF_LEAGUE_URLS:
            print(f"エラー: '{target}' は未登録の県IDです")
            print(f"登録済み: {', '.join(sorted(PREF_LEAGUE_URLS.keys()))}")
            sys.exit(1)
        check_pref(target, show_content=show)
    else:
        print("全県のURLをチェック中... (時間がかかります)")
        ok = []
        table_ok = []
        ng = []
        for pref_id in PREF_LEAGUE_URLS:
            urls = PREF_LEAGUE_URLS[pref_id]
            pref_name = PREF_NAMES.get(pref_id, pref_id)
            found = False
            for url in urls:
                soup = try_fetch(url, timeout=8)
                if soup:
                    tables = soup.find_all("table")
                    if tables:
                        print(f"  ✓ {pref_name}: テーブル{len(tables)}個")
                        table_ok.append(pref_id)
                    else:
                        print(f"  △ {pref_name}: 取得OK・テーブルなし")
                        ok.append(pref_id)
                    found = True
                    break
                time.sleep(0.3)
            if not found:
                print(f"  ✗ {pref_name}: 全URL失敗")
                ng.append(pref_id)
            time.sleep(0.5)

        print(f"\n===== 結果サマリー =====")
        print(f"✓ テーブル取得OK: {len(table_ok)}県 - {table_ok}")
        print(f"△ 取得OK・テーブルなし: {len(ok)}県 - {ok}")
        print(f"✗ 取得失敗: {len(ng)}県 - {ng}")


if __name__ == "__main__":
    main()
