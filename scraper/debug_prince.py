#!/usr/bin/env python3
"""
プリンスリーグのスクレイピング結果を診断するデバッグスクリプト。
teams.json との名前マッチング結果も表示する。

使い方:
  python scraper/debug_prince.py             # 全地域を診断
  python scraper/debug_prince.py --region tohoku   # 特定地域のみ
  python scraper/debug_prince.py --region kanto
"""

import sys
import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from update import (
    fetch_prince_divisions, parse_standing_table,
    match_team_to_pref, _normalize_name, _teams_match,
    PRINCE_REGION_PREFS, REGION_DISPLAY_NAMES,
    find_league_urls, DATA_FILE
)
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent

def debug_region(region_key: str, url: str, data: dict):
    region_name = REGION_DISPLAY_NAMES.get(region_key, region_key)
    candidate_prefs = PRINCE_REGION_PREFS.get(region_key, [])

    print(f"\n{'='*60}")
    print(f"地域: {region_key} ({region_name})")
    print(f"URL: {url}")
    print(f"対象都道府県: {', '.join(candidate_prefs)}")
    print()

    divisions = fetch_prince_divisions(url, region_key)
    if not divisions:
        print("  ⚠ データ取得失敗")
        return

    for soup, league_name in divisions:
        standings = parse_standing_table(soup)
        print(f"[{league_name}] 取得チーム数: {len(standings)}")

        if not standings:
            print("  ⚠ テーブルが見つかりません。列名を確認してください。")
            # 全テーブルのヘッダーを表示
            tables = soup.find_all("table")
            print(f"  ページ内テーブル数: {len(tables)}")
            for i, tbl in enumerate(tables):
                rows = tbl.find_all("tr")
                if rows:
                    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
                    print(f"  テーブル{i+1} ヘッダー: {headers}")
            continue

        for s in standings:
            pref_id = match_team_to_pref(s["name"], candidate_prefs, data)
            norm = _normalize_name(s["name"])

            if pref_id:
                status = f"✓ → {pref_id}"
            else:
                status = "✗ マッチなし"
                # 類似チームを探す
                candidates = []
                for pid in candidate_prefs:
                    for team in data.get(pid, {}).get("teams", []):
                        ename = team.get("name", "")
                        enorm = _normalize_name(ename)
                        if norm[:4] in enorm or enorm[:4] in norm:
                            candidates.append(f"{ename}({pid})")
                if candidates:
                    status += f" [類似候補: {', '.join(candidates[:3])}]"

            print(f"  {s['name']:<25} 正規化:{norm:<25} {status}")
        print()


def main():
    parser = argparse.ArgumentParser(description="プリンスリーグ スクレイピング診断")
    parser.add_argument("--region", help="地域キー (例: tohoku, kanto)")
    parser.add_argument("--year", type=int, default=datetime.now().year)
    args = parser.parse_args()

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    league_urls = find_league_urls(args.year)
    prince_urls = league_urls["prince"]

    if args.region:
        if args.region not in prince_urls:
            print(f"Error: 地域 '{args.region}' が見つかりません。")
            print(f"利用可能: {', '.join(prince_urls.keys())}")
            sys.exit(1)
        debug_region(args.region, prince_urls[args.region], data)
    else:
        for region_key, url in prince_urls.items():
            debug_region(region_key, url, data)


if __name__ == "__main__":
    main()
