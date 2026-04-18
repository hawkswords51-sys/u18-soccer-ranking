#!/usr/bin/env python3
"""
東北プリンスリーグのデータソース（APIエンドポイント・JSONファイル等）を探すスクリプト。

使い方:
  python scraper/debug_tohoku.py
"""

import re
import json
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
BASE = "https://tohoku-fa.jp"

def try_url(url, label=""):
    tag = f"[{label}] " if label else ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        size = len(resp.content)
        ct = resp.headers.get("Content-Type", "")
        print(f"  {tag}{resp.status_code} ({size}B) [{ct.split(';')[0]}]  {url}")
        return resp if resp.status_code == 200 else None
    except Exception as e:
        print(f"  {tag}ERROR: {e}  {url}")
        return None

# ===== 1. rankingページのJavaScriptを解析 =====
print("\n[1] ranking.html のスクリプトタグを解析")
resp = try_url(f"{BASE}/score/2026/prince2026/ranking.html", "ranking.html")
if resp:
    soup = BeautifulSoup(resp.text, "html.parser")

    # script タグ内の URL・JSONを探す
    scripts = soup.find_all("script")
    print(f"  script タグ数: {len(scripts)}")
    json_urls = []
    for sc in scripts:
        src_attr = sc.get("src", "")
        if src_attr:
            print(f"  外部JS: {src_attr}")
        body = sc.string or ""
        # JSON/APIっぽいURLを探す
        found = re.findall(r'["\']([^"\']*(?:json|api|data|ranking|score)[^"\']*)["\']', body, re.I)
        for f in found:
            if f not in json_urls:
                json_urls.append(f)
        # チーム名や勝点が含まれているか確認
        if any(kw in body for kw in ["勝点", "ranking", "teams", "standing"]):
            print(f"  ★ データ含むスクリプト発見 (先頭200文字): {body[:200]}")

    print(f"  見つかったURL候補: {json_urls}")

# ===== 2. よくあるJSONファイルのパスを試す =====
print("\n[2] JSONデータファイルを直接試す")
json_candidates = [
    f"{BASE}/score/2026/prince2026/ranking.json",
    f"{BASE}/score/2026/prince2026/data.json",
    f"{BASE}/score/2026/prince2026/teams.json",
    f"{BASE}/prince/data/2026/ranking.json",
    f"{BASE}/wp-json/wp/v2/posts?categories=prince&per_page=1",
    f"{BASE}/score/2026/prince2026/ranking_data.json",
]
for u in json_candidates:
    r = try_url(u)
    if r and "json" in r.headers.get("Content-Type", ""):
        print(f"  ★ JSON発見! 内容: {r.text[:300]}")

# ===== 3. 過去年度の同じパスで構造を確認 =====
print("\n[3] 過去年度の ranking.html を試す（ページ構造の参考）")
for yr in [2025, 2024]:
    r = try_url(f"{BASE}/score/{yr}/prince{yr}/ranking.html", f"{yr}年")
    if r:
        s = BeautifulSoup(r.text, "html.parser")
        tables = s.find_all("table")
        print(f"    テーブル数: {len(tables)}")
        if tables:
            rows = tables[0].find_all("tr")
            if rows:
                h = [c.get_text(strip=True) for c in rows[0].find_all(["th","td"])]
                print(f"    ヘッダー: {h}")
                for row in rows[1:3]:
                    d = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
                    print(f"    データ: {d}")
        # scriptタグのsrcを表示
        for sc in s.find_all("script", src=True):
            print(f"    外部JS: {sc['src']}")

# ===== 4. library.js の中身を確認（データ取得ロジックを探す） =====
print("\n[4] library.js を確認（データ読み込みロジック）")
r = try_url(f"{BASE}/common/js/library.js", "library.js")
if r:
    # AJAXやloadのパターンを探す
    import re
    text = r.text
    patterns = re.findall(r'(?:\.load|\.ajax|\.get|\.post|fetch)\s*\(["\']([^"\']+)["\']', text)
    xml_patterns = re.findall(r'["\']([^"\']+\.xml)["\']', text)
    json_patterns = re.findall(r'["\']([^"\']+\.json)["\']', text)
    php_patterns = re.findall(r'["\']([^"\']+\.php[^"\']*)["\']', text)
    data_patterns = re.findall(r'["\']([^"\']*(?:ranking|score|data|result)[^"\']*)["\']', text, re.I)

    print(f"  .load/.ajax URLパターン: {patterns[:10]}")
    print(f"  XMLファイル: {xml_patterns[:10]}")
    print(f"  JSONファイル: {json_patterns[:10]}")
    print(f"  PHPエンドポイント: {php_patterns[:10]}")
    print(f"  ranking/data系パターン: {list(set(data_patterns))[:10]}")
    print(f"  --- library.js 先頭500文字 ---")
    print(text[:500])

# ===== 5. ranking.html の生HTML全文を表示（本文部分をすべて表示） =====
print("\n[5] ranking.html の全HTML（body部分）")
r2 = try_url(f"{BASE}/score/2026/prince2026/ranking.html")
if r2:
    # エンコーディング修正
    r2.encoding = 'utf-8'
    soup_rank = BeautifulSoup(r2.text, "html.parser")
    body = soup_rank.find("body")
    if body:
        body_text = str(body)
        # インラインscriptを探す
        inline_scripts = soup_rank.find_all("script", src=False)
        print(f"  インラインscript数: {len(inline_scripts)}")
        for i, sc in enumerate(inline_scripts):
            print(f"  インラインscript[{i}]: {(sc.string or '')[:500]}")
        # divやtableを探す
        print(f"\n  body全文 ({len(body_text)}文字):")
        print(body_text[:5000])
    else:
        print("  bodyタグなし。全HTML:")
        print(r2.text)

# ===== 6. XMLデータファイルを試す =====
print("\n[6] XMLデータファイルを試す")
xml_candidates = [
    f"{BASE}/score/2026/prince2026/ranking.xml",
    f"{BASE}/score/2026/prince2026/data.xml",
    f"{BASE}/score/2026/prince2026/result.xml",
    f"{BASE}/score/2026/prince2026/score.xml",
]
for u in xml_candidates:
    r = try_url(u)
    if r:
        print(f"  内容先頭: {r.text[:200]}")

print("\n完了。")

