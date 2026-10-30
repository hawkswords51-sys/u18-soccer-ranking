#!/usr/bin/env python3
"""公開ページをキャッシュよけ付きで取り、確かめたい文字が入っているかを見る。読むだけ。

使い方: python3 check_live.py <URL> "<入っているはずの文字>" ["<もう1つ>" ...]
        先頭に ! を付けると「入っていないはず」の確認になる（例: "!要確認"）
"""
import sys
import time
import urllib.request

url = sys.argv[1]
sep = "&" if "?" in url else "?"
full = f"{url}{sep}nocache={time.strftime('%Y%m%d%H%M')}"
req = urllib.request.Request(full, headers={"User-Agent": "Mozilla/5.0 (u18-soccer check)"})
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
print(f"{full}  （{len(html):,}文字）")
ng = 0
for want in sys.argv[2:]:
    neg = want.startswith("!")
    text = want[1:] if neg else want
    hit = html.count(text)
    ok = (hit == 0) if neg else (hit > 0)
    ng += not ok
    print(f"  {'✅' if ok else '❌'} {'無いはず' if neg else 'あるはず'}「{text}」… {hit}か所")
sys.exit(1 if ng else 0)
