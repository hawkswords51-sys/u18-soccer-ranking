#!/usr/bin/env python3
"""
U-16 ルーキーリーグ（9地域）順位表の自動更新（2026-09-21 新設）
==============================================================
出典 = 大会公式サイト https://u16-rookie-league.com/{地域}/table/groups/{ID}
robots.txt は `User-agent: * / Disallow:`（全面許可）を 2026-09-21 に確認済み。

★このサイトの最大の特徴：順位表ページは「星取表（総当たり表）」であって、
  勝点・試合数・勝分敗・得失点の**集計列を持っていない**（順位＝「暫定順位」列だけ）。
  したがって**勝点や勝敗数は星取表の全セルから自前で計算する**。
  - セルは行チームから見た結果。`4○1` `1●2` `0△0` の形。
  - **1セルに複数試合が入ることがある**（2回戦総当たりの地域）。区切りは `<br>`。
  - 未消化は `-`。
  - PK決着は `2(5)△(3)2`（PK勝ち）/ `2(3)▲(5)2`（PK負け）。
    → 公式の暫定順位と突き合わせた結果、**勝点は3/1/0でPKは引き分け扱い**で矛盾しない
      （2026-09-21に全20リーグで検証）。PK戦の勝敗は pkw/pkl に記録だけする。
  - ★チーム名に**CJK部首の異体字**が混ざる（例：「⻄武台」の⻄＝U+2EC3）。
    NFKCでは直らない文字があるので RADICAL_FIX で明示的に潰す。

安全設計（誤データを絶対に載せない）
  1. 星取表の鏡面一致（i→j と j→i のスコアが裏返しか）
  2. 勝点＝勝×3＋分／試合数＝勝＋分＋敗／負の値なし
  3. リーグ内の得点合計＝失点合計／勝数合計＝敗数合計
  4. 公式の暫定順位の並びで勝点が単調非増加
  5. 顔ぶれが既存JSONと完全一致（知らないチーム名が来たら丸ごと破棄）
  6. 総試合数が減る更新は退行として破棄
  いずれか1つでも引っかかったら**そのリーグだけ既存維持**。例外は全捕捉して終了コード0。

使い方
  python scraper/fetch_u16_rookie.py                # 通常（毎朝のActionsから）
  python scraper/fetch_u16_rookie.py --dry-run      # 取得と検証だけ
  python scraper/fetch_u16_rookie.py --only kanto-a # 対象を絞る
  python scraper/fetch_u16_rookie.py --bootstrap    # 初回：JSONを新規作成する
"""
import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent.parent
DATA = BASE_DIR / "data" / "u16" / "leagues-2026.json"
ORIGIN = "https://u16-rookie-league.com"
TIMEOUT = 25
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; u18-soccer-bot/1.0; +https://u18-soccer.com)"}

# ---------------------------------------------------------------------
# 対象リーグ（正本）。ここに並べた順が、そのまま地域内の表示順になる。
#   slug … 公式サイトのリージョン部分
#   gid  … /table/groups/{gid}
# ★罠：リージョン部分を別の地域に変えても同じページが開ける（404にならない）ので、
#       URLを手で書くときは必ず正しい地域か確認する。
# ---------------------------------------------------------------------
DIVISIONS = [
    {"id": "hokkaido-1", "region": "北海道", "slug": "hokkaido", "gid": 15,
     "name": "ルーキーリーグU-16 HOKKAIDO 1部"},
    {"id": "hokkaido-2", "region": "北海道", "slug": "hokkaido", "gid": 16,
     "name": "ルーキーリーグU-16 HOKKAIDO 2部"},
    {"id": "hokkaido-3", "region": "北海道", "slug": "hokkaido", "gid": 83,
     "name": "ルーキーリーグU-16 HOKKAIDO 3部"},
    {"id": "tohoku-1", "region": "東北", "slug": "tohoku", "gid": 17,
     "name": "東北U-16 Rookie League 1部"},
    {"id": "tohoku-2", "region": "東北", "slug": "tohoku", "gid": 18,
     "name": "東北U-16 Rookie League 2部"},
    {"id": "kanto-a", "region": "関東", "slug": "kanto", "gid": 23,
     "name": "関東ROOKIE LEAGUE U-16 Aリーグ"},
    {"id": "kanto-b", "region": "関東", "slug": "kanto", "gid": 24,
     "name": "関東ROOKIE LEAGUE U-16 Bリーグ"},
    {"id": "kanto-c", "region": "関東", "slug": "kanto", "gid": 25,
     "name": "関東ROOKIE LEAGUE U-16 Cリーグ"},
    {"id": "hokushinetsu-1", "region": "北信越", "slug": "hokushinetsu", "gid": 19,
     "name": "北信越U-16 ルーキーリーグ 1部"},
    {"id": "hokushinetsu-2", "region": "北信越", "slug": "hokushinetsu", "gid": 20,
     "name": "北信越U-16 ルーキーリーグ 2部"},
    {"id": "toukai-1", "region": "東海", "slug": "toukai", "gid": 21,
     "name": "東海ルーキーリーグU-16 1部"},
    {"id": "toukai-2", "region": "東海", "slug": "toukai", "gid": 22,
     "name": "東海ルーキーリーグU-16 2部"},
    {"id": "kansai-g1", "region": "関西", "slug": "kansai", "gid": 26,
     "name": "関西U-16 ～Groeien～ G1リーグ"},
    {"id": "kansai-g2", "region": "関西", "slug": "kansai", "gid": 27,
     "name": "関西U-16 ～Groeien～ G2リーグ"},
    {"id": "chugoku-n1", "region": "中国", "slug": "chugoku", "gid": 29,
     "name": "中国ルーキーリーグ LIGA NOVA U-16 N1リーグ"},
    {"id": "chugoku-n2", "region": "中国", "slug": "chugoku", "gid": 30,
     "name": "中国ルーキーリーグ LIGA NOVA U-16 N2リーグ"},
    {"id": "shikoku-s1", "region": "四国", "slug": "shikoku", "gid": 31,
     "name": "CLIMB四国U-16 S1リーグ"},
    {"id": "shikoku-s2", "region": "四国", "slug": "shikoku", "gid": 32,
     "name": "CLIMB四国U-16 S2リーグ"},
    {"id": "kyushu-d1", "region": "九州", "slug": "kyushudanji", "gid": 33,
     "name": "球蹴男児U-16リーグ D1リーグ"},
    {"id": "kyushu-d2", "region": "九州", "slug": "kyushudanji", "gid": 34,
     "name": "球蹴男児U-16リーグ D2リーグ"},
]

# 星取表のチーム名に混ざる異体字（NFKCでは直らないCJK部首）
RADICAL_FIX = {
    "⻃": "西", "⻄": "西", "⺡": "長", "⻢": "食",
    "⻡": "食", "⻘": "青", "⻞": "飛", "⺽": "羽",
    "⺩": "面", "⻀": "行",
}


def today_jst():
    return datetime.now(timezone(timedelta(hours=9))).date()


def norm(s: str) -> str:
    """表示用の正規化。全角英数→半角、異体部首→通常漢字、空白除去。"""
    s = unicodedata.normalize("NFKC", s or "")
    for k, v in RADICAL_FIX.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", "", s).strip()


def warn_unfixed(name: str, label: str):
    """潰しきれなかったCJK部首があれば知らせる（次回 RADICAL_FIX に足すため）。"""
    bad = [c for c in name if 0x2E80 <= ord(c) <= 0x2EFF]
    if bad:
        print(f"  [要確認] {label}: 「{name}」に未対応の異体字 "
              + " ".join(f"{c}(U+{ord(c):04X})" for c in bad))


MIRROR_MARK = {"○": {"●"}, "●": {"○"}, "△": {"△", "▲"}, "▲": {"△"}}

CELL_RE = re.compile(r"^(\d+)(?:\((\d+)\))?([○△●▲])(?:\((\d+)\))?(\d+)$")


def split_legs(td) -> list:
    """1セルの中身を試合ごとに分解する。区切りは <br>。"""
    html = td.decode_contents()
    parts = re.split(r"<br\s*/?>", html, flags=re.I)
    out = []
    for p in parts:
        txt = norm(BeautifulSoup(p, "html.parser").get_text().replace("\xa0", ""))
        if txt and txt != "-":
            out.append(txt)
    return out


def parse_cross_table(html: str, label: str):
    """星取表を読んで (teams, ranks, cells) を返す。cells[(i,j)] = ['4○1', ...]"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ValueError("表が見つからない（入替戦・プレーオフのページかもしれない）")
    rows = table.find_all("tr")
    if len(rows) < 2:
        raise ValueError("行が足りない")

    head = [norm(c.get_text()) for c in rows[0].find_all(["th", "td"])]
    if not head or head[-1] not in ("暫定順位", "順位"):
        raise ValueError(f"最終列が順位ではない（実際:{head[-1] if head else '空'}）")
    teams = head[1:-1]
    if len(teams) < 2:
        raise ValueError("チーム数が2未満")
    for t in teams:
        warn_unfixed(t, label)

    ranks, cells = [], {}
    body = rows[1:]
    if len(body) != len(teams):
        raise ValueError(f"行数{len(body)}とチーム数{len(teams)}が不一致")
    for i, tr in enumerate(body):
        tds = tr.find_all(["th", "td"])
        if len(tds) != len(teams) + 2:
            raise ValueError(f"{i+1}行目の列数が不正（{len(tds)}）")
        if norm(tds[0].get_text()) != teams[i]:
            raise ValueError(f"{i+1}行目の行見出し「{norm(tds[0].get_text())}」が"
                             f"列見出し「{teams[i]}」と不一致")
        rk = norm(tds[-1].get_text())
        if not rk.isdigit():
            raise ValueError(f"{teams[i]}の暫定順位が数値でない（{rk}）")
        ranks.append(int(rk))
        for j in range(len(teams)):
            if i == j:
                continue
            cells[(i, j)] = split_legs(tds[j + 1])
    return teams, ranks, cells


def check_mirror(teams, cells):
    """星取表の鏡面一致（i→j と j→i が裏返しか）。"""
    problems = []
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            a, b = cells.get((i, j), []), cells.get((j, i), [])
            if len(a) != len(b):
                problems.append(f"{teams[i]}×{teams[j]}: 試合数が表の上下で違う（{len(a)}/{len(b)}）")
                continue
            for k in range(len(a)):
                ma, mb = CELL_RE.match(a[k]), CELL_RE.match(b[k])
                if not ma or not mb:
                    problems.append(f"{teams[i]}×{teams[j]}: 読めないセル（{a[k]}/{b[k]}）")
                    continue
                if ma.group(1) != mb.group(5) or ma.group(5) != mb.group(1):
                    problems.append(f"{teams[i]}×{teams[j]}: スコアが裏返しでない"
                                    f"（{a[k]}/{b[k]}）")
                # 勝敗記号も裏返しか（○↔●、引き分け系↔引き分け系）
                if mb.group(3) not in MIRROR_MARK.get(ma.group(3), set()):
                    problems.append(f"{teams[i]}×{teams[j]}: 勝敗記号が裏返しでない"
                                    f"（{a[k]}/{b[k]}）")
    return problems


def build_standings(teams, ranks, cells, label):
    """星取表から順位表を組み立てる。勝点は3/1/0、PKは引き分け扱い。"""
    st = []
    pk_notes = []
    for i, name in enumerate(teams):
        w = d = l = gf = ga = pkw = pkl = 0
        for j in range(len(teams)):
            if i == j:
                continue
            for leg in cells.get((i, j), []):
                m = CELL_RE.match(leg)
                if not m:
                    raise ValueError(f"{label}: 読めないセル「{leg}」（{name}×{teams[j]}）")
                gf += int(m.group(1))
                ga += int(m.group(5))
                mark = m.group(3)
                if mark == "○":
                    w += 1
                elif mark == "●":
                    l += 1
                else:
                    d += 1
                    if mark == "△" and m.group(2):
                        pkw += 1
                    elif mark == "▲":
                        pkl += 1
        if pkw or pkl:
            pk_notes.append(f"{name}(PK {pkw}勝{pkl}敗)")
        st.append({"name": name, "pts": w * 3 + d, "gf": gf, "ga": ga,
                   "rank": ranks[i], "w": w, "d": d, "l": l, "p": w + d + l})
    st.sort(key=lambda t: t["rank"])
    return st, pk_notes


def verify(teams, old_teams):
    """順位表が妥当か検証。問題があれば理由のリストを返す（空なら健全）。"""
    problems = []
    if not teams:
        return ["0チーム（取得できていない）"]
    for t in teams:
        if t["pts"] != t["w"] * 3 + t["d"]:
            problems.append(f"{t['name']}: 勝点{t['pts']}≠勝{t['w']}×3+分{t['d']}")
        if t["p"] != t["w"] + t["d"] + t["l"]:
            problems.append(f"{t['name']}: 試合数{t['p']}≠勝分敗の合計")
        if min(t["p"], t["w"], t["d"], t["l"], t["gf"], t["ga"], t["pts"]) < 0:
            problems.append(f"{t['name']}: 負の値")
    if sum(t["gf"] for t in teams) != sum(t["ga"] for t in teams):
        problems.append(f"得点合計{sum(t['gf'] for t in teams)}≠失点合計{sum(t['ga'] for t in teams)}")
    if sum(t["w"] for t in teams) != sum(t["l"] for t in teams):
        problems.append(f"勝数合計{sum(t['w'] for t in teams)}≠敗数合計{sum(t['l'] for t in teams)}")
    prev = None
    for t in teams:
        if prev is not None and t["pts"] > prev:
            problems.append(f"{t['name']}: 公式の順位の並びで勝点が増えている")
        prev = t["pts"]
    if old_teams:
        old_names = {t["name"] for t in old_teams}
        new_names = {t["name"] for t in teams}
        if old_names != new_names:
            problems.append(f"顔ぶれが変わった（消えた:{sorted(old_names - new_names)[:3]} "
                            f"増えた:{sorted(new_names - old_names)[:3]}）")
        if sum(t["p"] for t in teams) < sum(t["p"] for t in old_teams):
            problems.append(f"総試合数が減少（{sum(t['p'] for t in old_teams)}→"
                            f"{sum(t['p'] for t in teams)}）")
    return problems


def fetch_division(spec, debug=False):
    url = f"{ORIGIN}/{spec['slug']}/table/groups/{spec['gid']}"
    r = requests.get(url, headers=HEAD, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "utf-8"          # ★自動判定に任せない（JFA系で文字化けした前例あり）
    teams, ranks, cells = parse_cross_table(r.text, spec["id"])
    mirror = check_mirror(teams, cells)
    if mirror:
        raise ValueError("星取表の鏡面不一致: " + " / ".join(mirror[:2]))
    st, pk_notes = build_standings(teams, ranks, cells, spec["id"])
    if debug:
        print(f"  [debug] {spec['id']}: {len(st)}チーム / "
              + ", ".join(f"{t['rank']}.{t['name']}({t['pts']})" for t in st))
    return st, pk_notes, url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="取得と検証だけ行い書き込まない")
    ap.add_argument("--only", default="", help="対象division idをカンマ区切りで指定")
    ap.add_argument("--debug", action="store_true", help="取得結果を詳しく出力する")
    ap.add_argument("--bootstrap", action="store_true",
                    help="初回：JSONを新規作成する（顔ぶれ照合を行わない）")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None

    if DATA.exists():
        data = json.loads(DATA.read_text(encoding="utf-8"))
    elif args.bootstrap:
        data = {"season": 2026, "updated": today_jst().isoformat(),
                "note": "大会公式サイト（u16-rookie-league.com）の星取表から自動集計。",
                "divisions": []}
        print("■ 初回作成モード（--bootstrap）")
    else:
        print(f"❌ データがありません: {DATA}（初回は --bootstrap を付けて実行してください）")
        return 0

    by_id = {d["id"]: d for d in data["divisions"]}
    updated, kept, failed = [], [], []

    for spec in DIVISIONS:
        if only and spec["id"] not in only:
            continue
        try:
            teams, pk_notes, url = fetch_division(spec, debug=args.debug)
        except Exception as e:
            failed.append(f"{spec['id']}: {e}")
            continue

        div = by_id.get(spec["id"])
        problems = verify(teams, div.get("teams") if div else None)
        if problems:
            kept.append(f"{spec['id']}: " + " / ".join(problems[:2]))
            continue

        note = ""
        if pk_notes:
            note = "PK決着の試合を含みます（勝点は引き分け扱い）：" + "、".join(pk_notes)
        if div is None:
            div = {"id": spec["id"], "region": spec["region"], "name": spec["name"],
                   "teams": [], "note": ""}
            data["divisions"].append(div)
            by_id[spec["id"]] = div
        div["region"] = spec["region"]
        div["name"] = spec["name"]
        div["sourceLabel"] = "大会公式 星取表"
        div["sourceUrl"] = url
        div["note"] = note
        if div["teams"] == teams:
            continue                       # 変化なし
        div["teams"] = teams
        div["asof"] = f"{today_jst():%Y年%-m月%-d日}時点（自動更新）"
        updated.append(spec["id"])

    # DIVISIONS の並び順を正本にして並べ替える（表示順がぶれないように）
    order = {s["id"]: i for i, s in enumerate(DIVISIONS)}
    data["divisions"].sort(key=lambda d: order.get(d["id"], 999))

    print()
    print(f"✅ 更新: {len(updated)}リーグ " + (", ".join(updated) if updated else "（変化なし）"))
    if kept:
        print(f"⏸ 検証NGのため既存維持: {len(kept)}リーグ")
        for k in kept:
            print("   - " + k)
    if failed:
        print(f"— 取得できず既存維持: {len(failed)}リーグ")
        for f in failed:
            print("   - " + f)

    if not args.dry_run and (updated or args.bootstrap):
        data["updated"] = today_jst().isoformat()
        DATA.parent.mkdir(parents=True, exist_ok=True)
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"💾 {DATA.relative_to(BASE_DIR)} を更新しました"
              f"（{len(data['divisions'])}リーグ・"
              f"{sum(len(d['teams']) for d in data['divisions'])}チーム）")
    elif args.dry_run:
        print("（--dry-run のため書き込みはしていません）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:             # ワークフローを止めない
        print(f"❌ 想定外のエラー（既存データは変更していません）: {e}")
        sys.exit(0)
