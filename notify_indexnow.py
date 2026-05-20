#!/usr/bin/env python3
"""
IndexNow への更新通知スクリプト
==================================
sitemap.xml を読み込み、直近24時間以内に更新された URL を
IndexNow API（Bing・Yandex 等）に通知します。

GitHub Actions の毎日のスクレイピング後に実行することを想定。

使い方:
    python notify_indexnow.py

依存ライブラリ: 標準ライブラリのみ（Python 3.7+）
"""

import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# =====================================================================
# 設定（必要に応じて変更してください）
# =====================================================================

# IndexNow API キー（リポジトリルートに同名の .txt ファイルが必要）
INDEXNOW_KEY = "bd1f75d31a1a7369f3ee17cd7774a102"

# サイトのドメイン（www. なし、httpsなし）
HOST = "u18-soccer.com"

# ローカルの sitemap.xml へのパス
# GitHub Pages の場合：通常はリポジトリルートか、生成スクリプトの出力先
SITEMAP_PATH = "sitemap.xml"

# 何時間以内に更新された URL を通知するか（25時間 = 24h + 1h余裕）
LOOKBACK_HOURS = 25

# IndexNow エンドポイント
# - api.indexnow.org は IndexNow に参加する全検索エンジンに伝播
# - bing.com は Bing への直接送信（冗長化のため両方）
ENDPOINTS = [
    "https://api.indexnow.org/IndexNow",
    "https://www.bing.com/indexnow",
]

# 1リクエストあたりの最大 URL 数（IndexNow 仕様: 10,000）
BATCH_SIZE = 1000

# =====================================================================
# 以下、ロジック部分
# =====================================================================

INDEXNOW_KEY_LOCATION = f"https://{HOST}/{INDEXNOW_KEY}.txt"
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def parse_sitemap(path: Path) -> list[dict]:
    """sitemap.xml を解析して (url, lastmod) のリストを返す"""
    tree = ET.parse(path)
    root = tree.getroot()
    entries = []
    for url_elem in root.findall("sm:url", NS):
        loc = url_elem.find("sm:loc", NS)
        lastmod = url_elem.find("sm:lastmod", NS)
        if loc is not None and loc.text:
            entries.append({
                "url": loc.text.strip(),
                "lastmod": lastmod.text.strip() if (lastmod is not None and lastmod.text) else None,
            })
    return entries


def parse_lastmod(value: str) -> datetime | None:
    """ISO 8601 形式の lastmod を datetime に変換"""
    if not value:
        return None
    try:
        # "2026-05-20T12:00:00+00:00" や "2026-05-20T12:00:00Z" に対応
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        # "2026-05-20" だけの場合は UTC 0:00 として扱う
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def recent_urls(entries: list[dict], hours: int) -> list[str]:
    """指定時間以内に更新された URL を抽出"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for e in entries:
        dt = parse_lastmod(e["lastmod"]) if e["lastmod"] else None
        if dt is None:
            # lastmod がない URL は安全側で含める（毎回通知される可能性あり）
            recent.append(e["url"])
        elif dt >= cutoff:
            recent.append(e["url"])
    return recent


def chunks(lst: list, size: int):
    """リストを size 個ずつに分割するジェネレータ"""
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def notify_indexnow(urls: list[str]) -> None:
    """IndexNow API に URL リストを通知"""
    if not urls:
        print("[IndexNow] 通知する URL がありません")
        return

    headers = {"Content-Type": "application/json; charset=utf-8"}

    for batch_idx, batch in enumerate(chunks(urls, BATCH_SIZE), start=1):
        payload = {
            "host": HOST,
            "key": INDEXNOW_KEY,
            "keyLocation": INDEXNOW_KEY_LOCATION,
            "urlList": batch,
        }
        data = json.dumps(payload).encode("utf-8")
        print(f"[IndexNow] バッチ {batch_idx}: {len(batch)} URLs 送信")

        for endpoint in ENDPOINTS:
            try:
                req = urllib.request.Request(
                    endpoint, data=data, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    print(f"  ✅ {endpoint} → HTTP {resp.status}")
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="ignore")[:200]
                print(f"  ❌ {endpoint} → HTTP {e.code} {e.reason} | {body}")
            except urllib.error.URLError as e:
                print(f"  ❌ {endpoint} → URLエラー: {e.reason}")
            except Exception as e:
                print(f"  ❌ {endpoint} → 想定外のエラー: {e}")


def main() -> int:
    sitemap = Path(SITEMAP_PATH)
    if not sitemap.exists():
        print(f"[IndexNow] sitemap.xml が見つかりません: {sitemap.absolute()}")
        print("[IndexNow] SITEMAP_PATH の設定を確認してください")
        return 1

    print(f"[IndexNow] sitemap.xml を読み込み: {sitemap}")
    entries = parse_sitemap(sitemap)
    print(f"[IndexNow] sitemap.xml の総 URL 数: {len(entries)}")

    urls = recent_urls(entries, LOOKBACK_HOURS)
    print(f"[IndexNow] 直近 {LOOKBACK_HOURS} 時間以内の更新 URL: {len(urls)} 件")

    # 通知対象の最初の 10 件を表示（デバッグ用）
    for u in urls[:10]:
        print(f"  - {u}")
    if len(urls) > 10:
        print(f"  ...他 {len(urls) - 10} 件")

    notify_indexnow(urls)
    print("[IndexNow] 完了")
    return 0


if __name__ == "__main__":
    exit(main())
