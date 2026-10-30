#!/usr/bin/env python3
"""push のあと、GitHub の処理が終わるまで待って結果を出す。読むだけ。

使い方: python3 wait_deploy.py <pushしたコミット番号>   （最大20分待つ）

- push が data/ の対象パスに触れていれば「高円宮杯 順位自動更新」が走り、
  ボットが続けてコミットすることがある。その場合はボットのコミットの公開を待つ。
- 自分のコミットの「pages build and deployment」が cancelled なのは、
  ボットのコミットの公開に置き換わっただけなので問題ない。
"""
import json
import subprocess
import sys
import time

SHA = sys.argv[1]
DEADLINE = time.time() + 20 * 60


def runs():
    out = subprocess.run(["gh", "run", "list", "-L", "15", "--json",
                          "databaseId,workflowName,status,conclusion,headSha,event,createdAt"],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def origin_head():
    out = subprocess.run(["git", "ls-remote", "origin", "main"], check=True,
                         capture_output=True, text=True).stdout
    return out.split()[0]


time.sleep(15)
while True:
    rs = runs()
    mine = [r for r in rs if r["headSha"].startswith(SHA)]
    update = [r for r in mine if "順位自動更新" in r["workflowName"]]
    head = origin_head()
    pages_head = [r for r in rs if r["workflowName"] == "pages-build-deployment" and r["headSha"] == head]
    busy = [r for r in update if r["status"] != "completed"]
    if not busy and pages_head and pages_head[0]["status"] == "completed":
        break
    if time.time() > DEADLINE:
        print("⏳ 20分待っても終わりませんでした。途中の状態を出します。")
        break
    time.sleep(20)

print(f"いまの main の先頭: {head[:9]}" + ("（自分のコミット）" if head.startswith(SHA) else "（ボットのコミットが後に入った）"))
for r in runs():
    if r["headSha"].startswith(SHA) or r["headSha"] == head:
        print(f"  {r['workflowName']:28} {r['status']:10} {r.get('conclusion') or '-':10} {r['headSha'][:9]}  id={r['databaseId']}")
