#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
U-16ルーキーリーグ 得点ランキングの取得
=======================================
2026-09-23 新設。大会公式サイトが20リーグそれぞれに持っている得点ランキングを
data/scorers/u16-{division_id}.json に書き出す（/u16/ の各リーグ順位表の直下に載せる）。

★★ URLの罠：`ranking/index/{ID}/…` は ID を無視する
--------------------------------------------------------
    /{地域}/ranking/index/{ID}/{年}/…   ← ✘ IDを無視。地域ごとに固定の1リーグしか返らない。
                                            末尾の second / first / total / 無し も全部同じ内容。
    /{地域}/ranking/groups/{ID}/{年}     ← ✔ 正しい。IDごとに別のランキングが返る。

index 版で関東を引くと **Bリーグ** が返る（Aのつもりで使うと丸ごと別リーグの選手を載せる）。
必ず groups 版を使うこと。

掲載範囲（Kei 決定・2026-09-23）
--------------------------------
**上位10人＋同点は全員**。20リーグ合計で267人前後（全員だと1,455人になるので載せない）。
⚠️ 「rank <= 10」で切ってはいけない。出典は dense rank（1,2,2,3,4,4,4,…）なので
   10位まで取ると30人以上になる。行数で10人を数え、同点が続く間だけ伸ばす。

リーグの定義は fetch_u16_rookie.py の DIVISIONS をそのまま使う（2か所に持たない）。

安全装置（1つでも引っかかったらそのリーグだけ既存維持・終了コードは常に0）
  (1) 表が無い／行が0
  (2) 4列でない行、順位か得点が数値でない行がある
  (3) 順位が単調非減少でない
  (4) 得点が単調非増加でない
  (5) チーム名が data/u16/leagues-2026.json のそのリーグの顔ぶれに無い
      → 四国S1だけ例外（ALLOW_EXTRA_TEAMS。星取表が2ndステージの4チームしか返さないため）
  (6) 掲載人数が既存の半分未満に減る更新は退行として破棄

使い方:
    python scraper/fetch_u16_scorers.py
    python scraper/fetch_u16_scorers.py --dry-run --debug
    python scraper/fetch_u16_scorers.py --only kanto-a,shikoku-s1
"""
import argparse
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_u16_rookie import (DIVISIONS, HEAD, ORIGIN, TIMEOUT,  # noqa: E402
                              norm, today_jst, warn_unfixed)

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "data" / "scorers"
LEAGUES = BASE_DIR / "data" / "u16" / "leagues-2026.json"
SEASON = "2026"
TOP_N = 10

NOTE = ("上位10人（同点は全員）を掲載。公式の集計は総当たりリーグ戦のみで、"
        "入替戦・プレーオフは含みません。")

# 順位表に居ないチームが得点ランキングに出ることを許すリーグ（ID）。
# ★2026-09-23：いったん shikoku-s1 を入れていたが、順位表の出典を
#   /{地域}/order/15 へ移行して shikoku-s1 が「前期8チームの表」になったため不要になり、
#   空に戻した（得点ランキングの顔ぶれ8チームと一致することを実測で確認）。
#   仕組みは残してあるので、同じことが起きたらIDを入れて理由をここに書く。
ALLOW_EXTRA_TEAMS = set()

_DATE_RE = re.compile(r"最終更新日\s*[:：]\s*(\d{4})-(\d{2})-(\d{2})")


def ranking_url(spec):
    return f"{ORIGIN}/{spec['slug']}/ranking/groups/{spec['gid']}/{SEASON}"


def load_roster():
    """division id -> そのリーグの正規化済みチーム名の集合"""
    if not LEAGUES.exists():
        return {}
    d = json.loads(LEAGUES.read_text(encoding="utf-8"))
    return {x["id"]: {norm(t["name"]) for t in (x.get("teams") or [])}
            for x in d.get("divisions", [])}


def parse_ranking(html, div_id):
    """(scorers, last_updated) を返す。壊れていれば ValueError。"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ValueError("表が見つからない")

    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if not cells:
            continue
        if cells[0] in ("順位", "順"):        # 見出し行
            continue
        if len(cells) != 4:
            raise ValueError(f"4列でない行がある: {cells[:5]}")
        rk, name, team, goals = cells
        if not rk.isdigit() or not goals.isdigit():
            raise ValueError(f"順位か得点が数値でない: {cells}")
        team_n = norm(team)
        warn_unfixed(team_n, f"{div_id} 得点ランキング")
        rows.append({"rank": int(rk), "name": norm(name),
                     "team": team_n, "goals": int(goals)})

    if not rows:
        raise ValueError("行が0")

    for i in range(1, len(rows)):
        if rows[i]["rank"] < rows[i - 1]["rank"]:
            raise ValueError(f"順位が逆行している: {rows[i-1]['rank']} → {rows[i]['rank']}")
        if rows[i]["goals"] > rows[i - 1]["goals"]:
            raise ValueError(f"得点が増えている: {rows[i-1]['goals']} → {rows[i]['goals']}")

    # ★上位10人＋同点は全員。dense rank なので「rank <= 10」では切らない。
    cut = min(TOP_N, len(rows))
    while cut < len(rows) and rows[cut]["rank"] == rows[cut - 1]["rank"]:
        cut += 1

    m = _DATE_RE.search(soup.get_text(" ", strip=True))
    last = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else today_jst().isoformat()
    return rows[:cut], last


def fetch_one(spec, roster, debug=False):
    url = ranking_url(spec)
    r = requests.get(url, headers=HEAD, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "utf-8"          # ★自動判定に任せない
    scorers, last = parse_ranking(r.text, spec["id"])

    known = roster.get(spec["id"])
    if known:
        extra = sorted({s["team"] for s in scorers} - known)
        if extra and spec["id"] not in ALLOW_EXTRA_TEAMS:
            raise ValueError("順位表に居ないチームがある: " + "、".join(extra[:4]))
        if extra and debug:
            print(f"  [debug] {spec['id']}: 星取表に無いチーム（許可済み）: {'、'.join(extra)}")

    if debug:
        head = "、".join(f"{s['rank']}.{s['name']}({s['goals']})" for s in scorers[:3])
        print(f"  [debug] {spec['id']}: {len(scorers)}人 / 最終更新 {last} / {head}")
    return scorers, last, url


def main():
    ap = argparse.ArgumentParser(description="U-16ルーキーリーグの得点ランキングを取得する")
    ap.add_argument("--dry-run", action="store_true", help="取得と検証だけ行い書き込まない")
    ap.add_argument("--only", default="", help="対象division idをカンマ区切りで指定")
    ap.add_argument("--debug", action="store_true", help="取得結果を詳しく出力する")
    args = ap.parse_args()

    # ★gid を持たないリーグは公式に得点ランキングのページが無い
    #   （2026-09-23 に足した四国の 2nd stage 2表）。失敗ではないので静かに飛ばす。
    #   ページ側は render_scorer_compact_html が "" を返すので何も出ない。
    targets = [d for d in DIVISIONS
               if d.get("gid")
               and (not args.only or d["id"] in {x.strip() for x in args.only.split(",")})]
    skipped = [d["id"] for d in DIVISIONS if not d.get("gid")]
    roster = load_roster()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    updated, kept, failed, total = [], [], [], 0
    for spec in targets:
        out = OUT_DIR / f"u16-{spec['id']}.json"
        old = None
        if out.exists():
            try:
                old = json.loads(out.read_text(encoding="utf-8"))
            except Exception:
                old = None
        try:
            scorers, last, url = fetch_one(spec, roster, args.debug)
        except Exception as e:
            failed.append(f"{spec['id']}: {e}")
            continue

        # (6) 退行チェック
        if old and len(old.get("scorers", [])) and \
                len(scorers) * 2 < len(old["scorers"]):
            kept.append(f"{spec['id']}: 掲載人数が半減（"
                        f"{len(old['scorers'])}→{len(scorers)}）→既存維持")
            total += len(old["scorers"])
            continue

        doc = {
            "league": f"{spec['name']} 得点ランキング",
            "season": SEASON,
            "source": url,
            "sourceLabel": "大会公式 得点ランキング",
            "lastUpdated": last,
            "note": NOTE,
            "scorers": scorers,
        }
        total += len(scorers)
        if old and old.get("scorers") == scorers and old.get("lastUpdated") == last:
            continue
        if not args.dry_run:
            out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")
        updated.append(f"{spec['id']}({len(scorers)})")

    print()
    print(f"✅ 更新: {len(updated)}リーグ " + ("、".join(updated) if updated else "（変化なし）"))
    if kept:
        print(f"⏸ 検証NGのため既存維持: {len(kept)}リーグ")
        for k in kept:
            print("   - " + k)
    if failed:
        print(f"— 取得できず既存維持: {len(failed)}リーグ")
        for f in failed:
            print("   - " + f)
    if skipped:
        print(f"ℹ️ 公式に得点ランキングが無いので対象外: {len(skipped)}リーグ "
              + "、".join(skipped))
    print(f"📊 掲載人数の合計: {total}人 / {len(targets)}リーグ")
    if args.dry_run:
        print("（--dry-run のため書き込みはしていません）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:   # 例外は全捕捉（ワークフローを止めない）
        print(f"❌ 想定外のエラー（既存データは変更していません）: {e}")
        sys.exit(0)
