#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
プリンス13リーグの得点者をゲキサカから取り込む（2026-09-28 新設・分類＝取得）
=========================================================================
  出典：ゲキサカ「[プリンスリーグ◯◯]2026シーズン日程」PICK UP記事
        （本文はサーバのHTMLに入っている＝requests で取れる。robots.txt は /search* 以外を禁止していない）
  設定：data/prince_gekisaka.json（記事ID・チーム表記の対応・得点ランキングの略称・選手名の異表記）
  出力：① data/prince-scorers/{slug}.json … 試合ごとの得点者（チームページの①試合結果の表で使う）
        ② data/scorers/{slug}.json        … 得点ランキング（リーグページ用・従来と同じ形で上書き）

  プリンスは JFA に試合ごとの公式記録が無く、schedule.json の scorer 欄は網羅率5割強で使えない（手順書 3-2）。
  そのため得点者だけゲキサカから取る。**スコアは JFA 公式（data/league_matches）が正本**で、食い違う試合は使わない。

■ 帰属は「並び順」で決める
   得点者行は「ホーム→アウェイ」の順に、得点したチームの分だけ並ぶ（13リーグ432試合で例外0件・2026-09-28実測）。
   行頭の略号 [札] などは誤りがある（北海道 第13節 旭川実0-1札幌U-18 の得点者が [北]）ので、
   行数が合わないときの補助にだけ使う（略号の1文字目が片方のチーム名にだけ含まれるときに限る）。
■ 検算
   - 各側の得点者数（OG含む）＝得点 → complete／＜得点 → partial（「ほか不明」）／0人 → none／＞得点 → その側は捨てて none
■ 書き込みの規則
   - 中身が前回と同じなら書かない（lastUpdated だけ新しくすると鮮度を誤認させる）
   - 設定に無いゲキサカ表記が出たリーグ・取得/解析に失敗したリーグは書かない（前回のファイルを残す）
   - 退行チェック：前回の得点ランキングにいた選手の得点が減ったら、そのリーグのランキングは書かない
     （異体字の分裂や記事の書き換えの見張り。手作業時代の「前回JSONの選手が減っていないか」と同じ）
■ 記録：fetch_status の jobs に prince_scorers:{slug}。**赤にはしない**（補助情報。週末分の掲載は月曜以降になることがある）

使い方:
    python scraper/fetch_prince_scorers.py
    python scraper/fetch_prince_scorers.py --only prince-hokkaido --dry-run
    python scraper/fetch_prince_scorers.py --html-dir <保存済みHTMLのフォルダ> --dry-run   # {slug}.html を読む（検証用）
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

import requests

import fetch_status
from jst import today as _jst_today

ROOT = Path(__file__).resolve().parent.parent
CFG_FILE = ROOT / "data" / "prince_gekisaka.json"
MATCH_DIR = ROOT / "data" / "league_matches"
OUT_DIR = ROOT / "data" / "prince-scorers"
SCORER_DIR = ROOT / "data" / "scorers"

SEASON = "2026"          # ← 年度切り替えはここ（fetch_jfa.py の SEASON と揃える）
TIMEOUT = 30
SLEEP = 2.0              # 出典サーバへの間隔（2秒以上）
MIN_GOALS = 2            # 得点ランキングJSONに入れる下限（表示は generate_league_pages.py が3得点以上に絞る）
TOP_N = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
        "(u18-soccer.com prince scorers updater)"
    ),
}

MATCH = re.compile(r"^(.+?) (\d+)-(\d+) (.+)$")
BRK = re.compile(r"^\[([^\]]*)\](.*)$")


# ---------------------------------------------------------------------------
# 取得
# ---------------------------------------------------------------------------
def fetch(url: str) -> str:
    """1回だけ再試行する。"""
    last = None
    for i in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
            return r.text
        except Exception as e:          # noqa: BLE001
            last = e
            if i == 0:
                time.sleep(SLEEP)
    raise RuntimeError(f"取得失敗: {type(last).__name__}: {last}")


# ---------------------------------------------------------------------------
# 解析（参考実装 2026-09-28 と同じ規則）
# ---------------------------------------------------------------------------
def lines_of(src: str) -> list[str]:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", src, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("　", " ")
    L = [l.strip() for l in t.split("\n") if l.strip()]
    i = next((k for k, l in enumerate(L) if l.startswith("【第1節】")), None)
    j = next((k for k, l in enumerate(L) if l.startswith("▼関連")), None)
    if i is None or j is None or j <= i:
        raise RuntimeError("本文（【第1節】〜▼関連リンク）が見つからない")
    return L[i:j]


def split_top(s: str) -> list[str]:
    """括弧の外の「、」で区切る。"""
    parts, buf, depth = [], "", 0
    for ch in s:
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        if ch == "、" and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def goals_of(body: str) -> list[tuple[str, str]]:
    """'織田琉叶4(7分、8分、13分、90+1分)、斎藤悠翔(30分)' → [(name, minute), ...]"""
    out = []
    body = re.sub(r"[(（]{2,}", "(", body)             # 「中野琉允2((25分、32分)」
    if not re.search(r"[(（]", body):
        # 得点時間が書かれていない行（「[近]東野夏磨、山岡凌陽3、池内堂進」）。時間は空で数だけ取る。
        # ⚠️ 括弧のある行の中の括弧なし項目（「松本瑛太(33分)、音」の「音」）は途中で切れた字なので、ここには来させない
        for tok in split_top(body):
            m = re.fullmatch(r"(.+?)(\d*)", re.sub(r"\s", "", tok))
            for _ in range(int(m.group(2) or 1)):
                out.append((m.group(1), ""))
        return out
    for tok in split_top(body):
        m = re.match(r"^(.*?)(\d*)[(（]+(.*?)[)）]*$", tok)
        if not m:
            continue                          # 分の無い項目（途中で切れた「音」等）は数えない＝その側は partial
        name = re.sub(r"[{}()（）\s]", "", m.group(1))
        mins = [x.strip().rstrip("分").strip("()（）") for x in re.split("[、,]", m.group(3)) if x.strip()]
        mins = [x for x in mins if x]
        if not name or not mins or not all(re.fullmatch(r"\d+(\+\d+)?", x) for x in mins):
            continue                          # 「万福唯翔(82分、堅木晴太郎(85分))」のような崩れは数えない
        if m.group(2) and int(m.group(2)) != len(mins):
            continue
        for mi in mins:
            out.append((name, mi))
    return out


def parse(src: str) -> list[dict]:
    md = date_ = None
    res, cur, last_scorer = [], None, False
    for l in lines_of(src):
        m = re.match(r"^【第(\d+)節】", l)
        if m:
            md, cur = int(m.group(1)), None
            continue
        m = re.match(r"^\((\d+)月(\d+)日", l)
        if m:
            date_ = f"{SEASON}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            continue
        # 前の得点者行の続き（「毛利貴大」/「(69分)」のように改行で割れている）
        if cur is not None and last_scorer and re.match(r"^[(（][^)）]*分", l):
            cur["lines"][-1] += l
            continue
        m = BRK.match(l)
        if m:
            last_scorer = False
            # 得点者行＝「]」の後ろに中身がある行。会場行は「[J-GREEN堺S2]」のように後ろが空。
            # ⚠️ 「分」の有無で見分けない（時間の書かれていない得点者行がある）
            if cur is not None and m.group(2).strip():
                cur["lines"].append(m.group(2))
                cur["labels"].append(m.group(1))
                last_scorer = True
            continue
        m = MATCH.match(l)
        if m:
            cur = dict(md=md, date=date_, home=m.group(1).strip(), hs=int(m.group(2)),
                       as_=int(m.group(3)), away=m.group(4).strip(), lines=[], labels=[])
            res.append(cur)
            last_scorer = False
            continue
        last_scorer = False
    return res


def _minute_key(x: dict):
    mm = re.fullmatch(r"(\d+)(?:\+(\d+))?", x["minute"])
    return (0, int(mm.group(1)), int(mm.group(2) or 0)) if mm else (1, 0, 0)


def assign(g: dict, aliases: dict) -> dict:
    """→ {'h': (list, status), 'a': (list, status)}  status: complete / partial / none"""
    sides = [s for s, n in (("h", g["hs"]), ("a", g["as_"])) if n > 0]
    out = {"h": ([], "complete" if g["hs"] == 0 else "none"),
           "a": ([], "complete" if g["as_"] == 0 else "none")}
    if len(g["lines"]) == len(sides):
        pairs = list(zip(sides, g["lines"]))
    else:
        # 行数が合わないときだけ、略号で決める（1文字目が片方のチーム名にだけ含まれるとき）
        pairs, seen = [], set()
        for lab, body in zip(g["labels"], g["lines"]):
            hit = [s_ for s_, t in (("h", g["home"]), ("a", g["away"])) if lab and lab[0] in t]
            if len(hit) == 1 and hit[0] in sides and hit[0] not in seen:
                pairs.append((hit[0], body))
                seen.add(hit[0])
            else:
                return out
    for s, body in pairs:
        n = g["hs"] if s == "h" else g["as_"]
        gl = goals_of(body)
        if len(gl) > n:
            continue                          # 得点より多い＝その側は捨てて none
        lst = [dict(minute=mi, name=("オウンゴール" if "オウン" in nm else aliases.get(nm, nm))) for nm, mi in gl]
        lst.sort(key=_minute_key)             # ゲキサカは選手ごとにまとめて書くので時間順に並べ直す
        out[s] = (lst, "complete" if len(gl) == n else ("partial" if gl else "none"))
    return out


def _similar(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


# ---------------------------------------------------------------------------
# 1リーグ分
# ---------------------------------------------------------------------------
def build(slug: str, c: dict, src: str, today: str) -> dict:
    """解析と集計。書き込みはしない。{'ps','sc','stat','warn','error'} を返す。"""
    if f"[{c['title']}]{SEASON}シーズン日程" not in re.sub(r"\s", "", html.unescape(
            (re.search(r"<title>(.*?)</title>", src, re.S) or [None, ""])[1])):
        return dict(error=f"<title> に「[{c['title']}]{SEASON}シーズン日程」が無い（別の記事の疑い）")
    J = json.loads((MATCH_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    idx = {(m["home"], m["away"]): m for m in J["matches"]}
    G = parse(src)
    unknown = sorted({x for g in G for x in (g["home"], g["away"])} - set(c["teams"]))
    if unknown:
        return dict(error=f"設定に無いゲキサカ表記 {unknown}（data/prince_gekisaka.json の teams に足す）")

    stat = {"complete": 0, "partial": 0, "none": 0, "score_mismatch": 0, "unplayed_in_jfa": 0}
    rows, players, og = [], {}, {}
    for g in G:
        h, a = c["teams"][g["home"]], c["teams"][g["away"]]
        m = idx.get((h, a))
        if not m or m.get("status") != "played":
            stat["unplayed_in_jfa"] += 1
            continue
        if (m["hs"], m["as"]) != (g["hs"], g["as_"]):
            stat["score_mismatch"] += 1
            continue
        res = assign(g, c.get("aliases") or {})
        (hl, hst), (al, ast) = res["h"], res["a"]
        stat[hst] += 1
        stat[ast] += 1
        rows.append(dict(md=m["md"], date=m.get("date"), home=h, away=a, hs=m["hs"], **{"as": m["as"]},
                         homeScorers=hl, awayScorers=al, homeStatus=hst, awayStatus=ast))
        for team, lst in ((g["home"], hl), (g["away"], al)):
            for x in lst:
                if x["name"] == "オウンゴール":
                    og[team] = og.get(team, 0) + 1
                else:
                    players[(team, x["name"])] = players.get((team, x["name"]), 0) + 1

    warn = []
    by_team = {}
    for (t, nm) in players:
        by_team.setdefault(t, []).append(nm)
    for t, names in by_team.items():
        names = sorted(names)
        for i, x in enumerate(names):
            for y in names[i + 1:]:
                if _similar(x, y):
                    warn.append(f"似た名前 {c['display'].get(t, t)}：{x}（{players[(t, x)]}）／{y}（{players[(t, y)]}）"
                                f"→ JFA公式の表記を確かめて aliases に足す")

    ps = dict(league=J["league"], source=c["url"], sourceName="ゲキサカ", lastUpdated=today, matches=rows)

    # 得点ランキング（従来の parse_scorers.py と同じ形・同じ規則：2得点以上・上位20・同点同順位）
    gf = {}
    for g in G:
        gf[g["home"]] = gf.get(g["home"], 0) + g["hs"]
        gf[g["away"]] = gf.get(g["away"], 0) + g["as_"]
    att = {}
    for (t, _), n in players.items():
        att[t] = att.get(t, 0) + n
    for t, n in og.items():
        att[t] = att.get(t, 0) + n
    ranked = sorted(players.items(), key=lambda kv: (-kv[1], kv[0][0]))
    picked = [(t, nm, n) for (t, nm), n in ranked if n >= MIN_GOALS][:TOP_N]
    sc, prev, rank = [], None, 0
    for i, (t, nm, n) in enumerate(picked, 1):
        if n != prev:
            rank, prev = i, n
        sc.append(dict(rank=rank, name=nm, team=c["display"][t], goals=n))
    cov = [dict(team=c["display"][t], attributed=att.get(t, 0), gf=gf[t], missing=gf[t] - att.get(t, 0))
           for t in sorted(gf, key=lambda x: -gf[x]) if gf[t] - att.get(t, 0) > 0]
    old_file = SCORER_DIR / f"{slug}.json"
    old = json.loads(old_file.read_text(encoding="utf-8")) if old_file.exists() else {}
    sc_out = dict(league=old.get("league") or f"{J['league']} 得点ランキング", season=SEASON, source=c["url"],
                  lastUpdated=today, note=old.get("note", ""), scorers=sc, coverage=cov)

    # 退行チェック：前回のランキングにいた選手の、今回の通算得点（上位20に入っていなくても数える）
    goals_now = {(c["display"][t], nm): n for (t, nm), n in players.items()}
    regress = [f"{s['team']} {s['name']} {s['goals']}→{goals_now.get((s['team'], s['name']), 0)}"
               for s in old.get("scorers", []) if goals_now.get((s["team"], s["name"]), 0) < s["goals"]]
    return dict(ps=ps, sc=sc_out, stat=stat, warn=warn, regress=regress, old_sc=old, error=None)


def _same(a: dict, b: dict, keys) -> bool:
    return all(a.get(k) == b.get(k) for k in keys)


def _write(path: Path, data: dict, indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="プリンス13リーグの得点者をゲキサカから取り込む")
    ap.add_argument("--only", default="", help="slug をカンマ区切りで指定")
    ap.add_argument("--dry-run", action="store_true", help="書き込まない")
    ap.add_argument("--html-dir", default="", help="取得せずに {slug}.html を読む（検証用）")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    cfg = json.loads(CFG_FILE.read_text(encoding="utf-8"))
    today = _jst_today().isoformat()
    print(f"=== プリンス得点者（ゲキサカ）{'【DRY RUN】' if args.dry_run else ''} ===")
    first = True
    for slug, c in cfg["leagues"].items():
        if only and slug not in only:
            continue
        c = dict(c, title=c.get("title") or _title_of(slug))
        try:
            if args.html_dir:
                src = (Path(args.html_dir) / f"{slug}.html").read_text(encoding="utf-8", errors="replace")
            else:
                if not first:
                    time.sleep(SLEEP)
                first = False
                src = fetch(c["url"])
            r = build(slug, c, src, today)
        except Exception as e:          # noqa: BLE001  1リーグ失敗しても他は続ける
            r = dict(error=f"{type(e).__name__}: {e}")
        if r.get("error"):
            print(f"  [要確認] {slug}: {r['error']} → このリーグは書かない（前回のファイルを残す）")
            if not args.dry_run:
                fetch_status.set_job_result(f"prince_scorers:{slug}", "error", r["error"])
            continue

        st = r["stat"]
        n = len(r["ps"]["matches"])
        print(f"  {slug}: 試合{n}・complete {st['complete']}・partial {st['partial']}・none {st['none']}"
              f"・スコア不一致 {st['score_mismatch']}")
        for w in r["warn"]:
            print(f"    ⚠要確認 {w}")

        notes = []
        # ① 試合ごとの得点者
        ps_file = OUT_DIR / f"{slug}.json"
        old_ps = json.loads(ps_file.read_text(encoding="utf-8")) if ps_file.exists() else {}
        if _same(old_ps, r["ps"], ("league", "source", "sourceName", "matches")):
            notes.append("試合の得点者は変化なし")
        else:
            notes.append(f"試合の得点者を更新（{n}試合）")
            if not args.dry_run:
                _write(ps_file, r["ps"], 1)
        # ② 得点ランキング
        if r["regress"]:
            msg = "得点が減った選手あり（異体字の分裂・記事の書き換えの疑い）: " + "／".join(r["regress"][:5])
            print(f"    ⚠ {msg} → ランキングは書かない")
            notes.append("ランキングは退行のため据え置き")
        elif _same(r["old_sc"], r["sc"], ("league", "source", "note", "scorers", "coverage")):
            notes.append("ランキングは変化なし")
        else:
            notes.append("ランキングを更新")
            if not args.dry_run:
                _write(SCORER_DIR / f"{slug}.json", r["sc"], 2)
        print(f"    → {'／'.join(notes)}")
        if not args.dry_run:
            result = "ok" if not r["regress"] else "regressed"
            fetch_status.set_job_result(
                f"prince_scorers:{slug}", result,
                f"試合{n}・partial{st['partial']}・none{st['none']}・スコア不一致{st['score_mismatch']}"
                + (f"・退行{len(r['regress'])}" if r["regress"] else ""))
    return 0


def _title_of(slug: str) -> str:
    """記事タイトルの [ ] の中（プリンスリーグ北海道 など）。"""
    names = {"hokkaido": "北海道", "tohoku": "東北", "kanto-1": "関東1部", "kanto-2": "関東2部",
             "hokushinetsu-1": "北信越1部", "hokushinetsu-2": "北信越2部", "tokai": "東海",
             "kansai-1": "関西1部", "kansai-2": "関西2部", "chugoku": "中国", "shikoku": "四国",
             "kyushu-1": "九州1部", "kyushu-2": "九州2部"}
    return "プリンスリーグ" + names[slug.removeprefix("prince-")]


if __name__ == "__main__":
    sys.exit(main())
