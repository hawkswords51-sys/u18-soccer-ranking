#!/usr/bin/env python3
"""定期実行（毎朝・毎晩）の見張りログを GitHub から取ってきて、見張りの部分だけを出す。

使い方:
  python3 fetch_watch_log.py            # いちばん新しい定期実行
  python3 fetch_watch_log.py 2          # 2つ前（前回と比べたいとき）
  python3 fetch_watch_log.py --id 123   # 実行番号を指定

読み取りだけ。リポジトリのファイルには何も書かない。
"""
import json
import re
import subprocess
import sys

WORKFLOW = "update_rankings.yml"

# ログから切り出す見張りの工程（ログ上の「Run if [ -f scraper/xxx.py ]」で見分ける）
WATCH_SCRIPTS = [
    ("県予選mdと出典の突き合わせ", "audit_tournament_md.py"),
    ("県1部の鮮度", "audit_pref_freshness.py"),
    ("参入戦の出場権", "audit_premier_playoff.py"),
    ("順位表と試合一覧の矛盾", "check_standings_vs_matches.py"),
    ("取得元（JFA以外に落ちたリーグ）", "check_fetch_status.py"),
]


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def pick_run(argv):
    if "--id" in argv:
        rid = argv[argv.index("--id") + 1]
        return json.loads(gh("run", "view", rid, "--json", "databaseId,conclusion,status,createdAt,headSha"))
    nth = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 1
    runs = json.loads(gh("run", "list", "-w", WORKFLOW, "-e", "schedule", "-L", str(nth + 2),
                         "--json", "databaseId,conclusion,status,createdAt,headSha"))
    return runs[nth - 1]


def main():
    run = pick_run(sys.argv)
    rid = str(run["databaseId"])
    print(f"実行番号 {rid}  開始 {run['createdAt']}(UTC)  状態 {run['status']}  結果 {run.get('conclusion') or '-'}")
    print(f"https://github.com/hawkswords51-sys/u18-soccer-ranking/actions/runs/{rid}")
    if run["status"] != "completed":
        print("\n⏳ まだ走っています。終わってから見てください。")
        return

    jobs = json.loads(gh("run", "view", rid, "--json", "jobs"))["jobs"]
    print("\n--- 工程の結果（成功以外だけ） ---")
    bad = 0
    for j in jobs:
        for s in j["steps"]:
            if s["conclusion"] not in ("success", "skipped") or (
                s["conclusion"] == "skipped" and ("点検" in s["name"])):
                print(f"  {s['conclusion']:8} {s['name']}")
                bad += 1
    if not bad:
        print("  （すべて成功）")

    lines = []
    for raw in gh("run", "view", rid, "--log").splitlines():
        parts = raw.split("\t", 2)
        text = parts[2] if len(parts) == 3 else raw
        text = re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ", "", text)
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
        lines.append(text)

    starts = [i for i, t in enumerate(lines) if t.startswith("##[group]Run ")]
    for label, script in WATCH_SCRIPTS:
        idx = next((i for i in starts if f"scraper/{script}" in lines[i]), None)
        print(f"\n===== {label}（{script}） =====")
        if idx is None:
            print("  （この回は走っていません＝前の工程が赤で止まったか、対象外の回）")
            continue
        nxt = next((i for i in starts if i > idx), len(lines))
        body = lines[idx:nxt]
        try:
            body = body[body.index("##[endgroup]") + 1:]
        except ValueError:
            pass
        body = [t for t in body if not t.startswith(("##[group]", "##[endgroup]", "Post job"))]
        print("\n".join(body).rstrip())


if __name__ == "__main__":
    main()
