#!/usr/bin/env python3
"""
データ整合性パトロール（data QA）
==================================
サイトの生成データ/ページに対し、ルールで機械判定できる不整合を一括チェックする。
Web不要・決定論的なので毎回同じ基準で「バグの芽」を洗い出せる。

実行: python scraper/data_qa.py   （リポジトリのルートから）
出力: 標準出力にカテゴリ別の検出結果。問題が無ければ「異常なし」。
※このスクリプトは検出のみ。修正は行わない。
"""
import json, re, glob, os
from pathlib import Path

BASE = Path(__file__).parent.parent
issues = {}

def add(cat, msg):
    issues.setdefault(cat, []).append(msg)

# 1) 控えチーム(2nd/3rd/B/C 等)が「代表/成績」に混入していないか
def check_reserve_in_results():
    tj = BASE / "data" / "tournaments.json"
    if not tj.exists():
        return
    try:
        d = json.loads(tj.read_text(encoding="utf-8"))
    except Exception as e:
        add("tournaments.json 読み込みエラー", str(e)); return
    for tid, t in d.get("tournaments", {}).items():
        for year, yd in (t.get("results", {}) or {}).items():
            for x in yd.get("teams", []):
                nm = x.get("team", "")
                if re.search(r"(2nd|3rd|Ⅱ|Ⅲ|セカンド|サード)$", nm) or re.search(r"(高校|学園|学院|ユース)[BC]$", nm):
                    add("控えチームが代表/成績に混入", f"{tid} {year}: {nm}（result={x.get('result')}）")
                if not x.get("pref"):
                    add("都道府県が未解決(pref=null)", f"{tid} {year}: {nm}")

# 2) 県リーグのチーム数が異常／同一県内の重複チーム名
def check_team_counts():
    tjson = BASE / "data" / "teams.json"
    if not tjson.exists():
        return
    teams = json.loads(tjson.read_text(encoding="utf-8"))
    for pid, blk in teams.items():
        if pid == "_meta":
            continue
        tl = blk.get("teams", []) if isinstance(blk, dict) else blk
        pref_league = [t for t in tl if "プレミア" not in t.get("league", "") and "プリンス" not in t.get("league", "")]
        if len(pref_league) >= 25:
            add("県リーグのチーム数が異常(膨張疑い)", f"{pid}: 県リーグ {len(pref_league)} チーム")
        names = [t.get("name") for t in tl]
        for n in sorted(set(x for x in names if names.count(x) > 1)):
            add("同一県内の重複チーム名", f"{pid}: {n}")

# 3) 空ページ/データ未登録の残り
def check_empty_pages():
    for f in glob.glob(str(BASE / "leagues/*/index.html")) + glob.glob(str(BASE / "prefectures/*/index.html")):
        s = Path(f).read_text(encoding="utf-8", errors="ignore")
        if "まだ登録されていません" in s or "データはまだ" in s:
            add("データ未登録の表示が残るページ", os.path.relpath(f, BASE))

# 4) 内部リンク切れ
def _exists(p):
    p = p.split("#")[0].split("?")[0]
    if p in ("", "/"):
        return (BASE / "index.html").exists()
    p = p.lstrip("/")
    cand = BASE / p
    if cand.is_file():
        return True
    if p.endswith("/"):
        return (BASE / p / "index.html").exists()
    if "." not in os.path.basename(p):
        return (cand / "index.html").exists() or (BASE / (p + ".html")).exists()
    return False

def check_broken_links():
    broken = {}
    for h in glob.glob(str(BASE / "**/*.html"), recursive=True):
        if ".git" in h:
            continue
        txt = Path(h).read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'href="(/[^"]*)"', txt):
            u = m.group(1)
            if not _exists(u):
                broken.setdefault(u.split("#")[0], 0)
                broken[u.split("#")[0]] += 1
    for u in sorted(broken):
        add("内部リンク切れ", f"{u}（{broken[u]}箇所）")

def main():
    check_reserve_in_results()
    check_team_counts()
    check_empty_pages()
    check_broken_links()
    print("=" * 10, "データ整合性パトロール 結果", "=" * 10)
    if not issues:
        print("✅ 異常は見つかりませんでした")
        return
    total = sum(len(v) for v in issues.values())
    print(f"⚠️ {len(issues)} カテゴリ・計 {total} 件の要確認項目")
    for cat, lst in issues.items():
        print(f"\n■ {cat}（{len(lst)}件）")
        for m in lst[:20]:
            print("   -", m)
        if len(lst) > 20:
            print(f"   ... ほか {len(lst)-20} 件")

if __name__ == "__main__":
    main()
