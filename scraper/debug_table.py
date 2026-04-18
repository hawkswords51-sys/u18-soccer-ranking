#!/usr/bin/env python3
"""
JFAページのテーブル構造を確認するデバッグスクリプト
実行: python scraper/debug_table.py
"""
import sys
from pathlib import Path

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("pip install selenium webdriver-manager を実行してください")
    sys.exit(1)

def get_table_with_selenium(url):
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,800")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts
    )
    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "table"))
        )
        import time; time.sleep(2)
        return driver.page_source
    except Exception as e:
        print(f"エラー: {e}")
        return None
    finally:
        driver.quit()

url = "https://www.jfa.jp/match/takamado_jfa_u18_premier2026/east/standings/"
print(f"取得中: {url}")
html = get_table_with_selenium(url)

if not html:
    print("取得失敗")
    sys.exit(1)

from bs4 import BeautifulSoup
soup = BeautifulSoup(html, "html.parser")
tables = soup.find_all("table")
print(f"\nテーブル数: {len(tables)}\n")

output_lines = []
for i, table in enumerate(tables):
    rows = table.find_all("tr")
    output_lines.append(f"=== テーブル {i+1} ({len(rows)}行) ===")
    for j, row in enumerate(rows[:6]):
        cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        output_lines.append(f"  行{j}: {cols}")
    output_lines.append("")

result = "\n".join(output_lines)
print(result)

# ファイルにも保存
out_file = Path(__file__).parent / "debug_output.txt"
out_file.write_text(result, encoding="utf-8")
print(f"\n→ 結果を {out_file} に保存しました")
