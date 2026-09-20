#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
チームごとのシーズンデータ（登録選手・試合ごとの先発/控え/交代）をJFA公式から取る
====================================================================
出力: data/team-season/{team_id}.json

**対象は frontmatter に `jfa_team:` を書いたチームだけ**（2026-09-20は流経大柏のみ）。
書式は `{リーグslug}/{JFAのチーム番号}`（例 `premier-east/07`）。
1行足すだけで横展開できるようにしてある。番号の対応表はJFAの team.html が正本。

【出典】（すべて静的HTML。2026-09-20 実測）
  選手一覧  …/{side}/team_detail/{NN}.html   … table.teamtable#sorter
  試合ページ…/{side}/match_page/m{n}.html    … table.match-result
  試合結果・得点者は**取りに行かない**。既存の data/league_matches/{slug}.json にある。
  ⚠️ `{side}/` や `{side}/team_page/` はディレクトリで403、`{side}/team/` は404。上の2つだけ使う。

【⚠️ 最大の罠：未消化の試合ページは「先発」に登録選手が全員並ぶ】
  第15節（9/26予定）のページを読むと先発の表に30人が出る。
  → **既存JSONで status=="played" の試合だけ**を読み、さらに**先発が11人ちょうど**でなければ捨てる。

【取り直さない】
  終わった試合の先発は変わらないので、保存済みの試合は再取得しない。
  1日のリクエスト＝チーム数 ×（選手一覧1 ＋ 新しく終わった試合の数）。

【検算（G1〜G4）】
  G1 各試合で先発11人・うちGK1人          … 外れた試合はその試合だけ捨てる
  G2 先発＋途中出場の数 ＝ 選手一覧の「試合」… 外れたら**選手一覧だけ据え置き**（試合は保存する）
  G3 選手一覧の得点合計＋一覧外の得点者＋OG ＝ 順位表の得点(GF)
  G4 既消化試合の数 ＝ 順位表の試合数
  G3・G4 が外れたら**そのチームのファイルは1バイトも書かない**（前の内容が残る）。

⚠️ 警告・退場の欄は**読まない・保存しない**（未成年の懲罰情報のため）。

使い方:
    python scraper/fetch_jfa_team_season.py
    python scraper/fetch_jfa_team_season.py --only ryukei-kashiwa
    python scraper/fetch_jfa_team_season.py --dry-run     # 書き込まない
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_status                                    # noqa: E402
from jst import today as _jst_today                    # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = BASE_DIR / "data" / "team-profiles"
MATCH_DIR = BASE_DIR / "data" / "league_matches"
TEAMS_FILE = BASE_DIR / "data" / "teams.json"
OUT_DIR = BASE_DIR / "data" / "team-season"

SEASON = "2026"          # ← 年度切り替えはここ（fetch_jfa.py の SEASON と揃える）
TIMEOUT = 20
SLEEP = 1.0              # 出典サーバへの間隔
RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
        "(u18-soccer.com team season updater)"
    ),
}

_PREMIER_BASE = "https://www.jfa.jp/match/takamado_jfa_u18_premier{season}/{side}"


# ---------------------------------------------------------------------------
# 取得
# ---------------------------------------------------------------------------
def fetch_html(url: str) -> str:
    """HTMLを取る。⚠️ Content-Type に charset が無いので **utf-8 を明示**する
    （requests に任せると ISO-8859-1 と誤判定し、例外を出さずに文字化けする）。"""
    last = None
    for _ in range(RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.content.decode("utf-8")
        except Exception as e:      # noqa: BLE001
            last = e
            time.sleep(SLEEP)
    raise RuntimeError(f"{url} の取得に失敗 ({last})")


def base_url(slug: str) -> str:
    """リーグslug → JFAのそのリーグのURLの根。今はプレミアだけ。

    ⚠️ プリンスは `match_47fa/{code}/...` と体系が違う（東北はそもそもJFAに無い）。
       対応するときは fetch_jfa.py の LEAGUES と同じ作りにすること。
    """
    if slug in ("premier-east", "premier-west"):
        return _PREMIER_BASE.format(season=SEASON, side=slug.split("-")[1])
    raise RuntimeError(f"{slug} はまだ対応していない（今はプレミアだけ）")


# ---------------------------------------------------------------------------
# 選手一覧
# ---------------------------------------------------------------------------
def _clean(s: str) -> str:
    """JFAのHTMLに残っているエスケープの残骸だけ直す。

    ⚠️ 前所属・学年は**JFAの文字列のまま**残すのが約束（半角ｶﾅ「･」や読み仮名も直さない）。
       例外は `AZ(アーゼット)\\'86東京青梅` のバックスラッシュだけ（JFA側の残骸・実測）。
    """
    return s.replace("\\'", "'")


def parse_roster(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.teamtable#sorter")
    if table is None:
        raise RuntimeError("選手一覧の table.teamtable#sorter が無い")
    out = []
    for tr in table.select("tbody tr"):
        # ⚠️ コメントアウトされた古い列 <!--<td ...>--> が混ざっている。
        #    BeautifulSoup は Comment として扱うので find_all("td") には入らない。
        tds = tr.find_all("td")
        if len(tds) != 8:
            raise RuntimeError(f"選手一覧の行が8列でない（{len(tds)}列）: "
                               f"{[td.get_text(' ', strip=True) for td in tds][:4]}")
        v = [_clean(td.get_text(" ", strip=True)) for td in tds]
        no, pos, name, grade, prev, apps, minutes, goals = v
        if not re.fullmatch(r"\d+", no):
            raise RuntimeError(f"選手一覧の背番号が読めない: {no!r}")
        for label, x in (("試合", apps), ("時間", minutes), ("得点", goals)):
            if not re.fullmatch(r"\d+", x):
                raise RuntimeError(f"選手一覧の{label}が読めない: {name} {x!r}")
        out.append(dict(no=int(no), pos=pos, name=name, grade=grade, prev=prev,
                        apps=int(apps), minutes=int(minutes), goals=int(goals)))
    if not out:
        raise RuntimeError("選手一覧が0人")
    return out


# ---------------------------------------------------------------------------
# 試合ページ（先発・控え・交代）
# ---------------------------------------------------------------------------
_CAP_RE = re.compile(r"\s*\(Cap\.\)\s*$")
_SUB_RE = re.compile(r"^(?P<name>.+?)\s*[▼▲]\s*(?P<minute>.+?)\s*(?P<dir>OUT|IN)$")


def _cells(tr):
    return tr.find_all(["td", "th"])


def _cls(c) -> str:
    return (c.get("class") or ["-"])[0]


def parse_match(html: str, team_name: str) -> dict:
    """1試合分から、そのチーム側の先発・控え・交代を取り出す。

    ⚠️ 先発・控えは6列（左3列＝ホーム・右3列＝アウェイ）、交代は4列（左2列＝ホーム）。
       **列の数が違う**ので、行の種類ごとに取り方を変える。
    ⚠️ 「警告・退場」より後は読まない（未成年の懲罰情報は持たない）。
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.match-result")
    if table is None:
        raise RuntimeError("table.match-result が無い")
    rows = table.find_all("tr")
    if not rows:
        raise RuntimeError("table.match-result が空")

    head = [c.get_text(" ", strip=True) for c in _cells(rows[0])]
    if len(head) != 2:
        raise RuntimeError(f"1行目がチーム名2つでない: {head}")
    if team_name == head[0]:
        side = 0
    elif team_name == head[1]:
        side = 1
    else:
        raise RuntimeError(f"このチーム({team_name})が出ていない: {head}")

    section = "starters"
    starters, bench, subs = [], [], []
    pending_out = None
    for tr in rows[1:]:
        cs = _cells(tr)
        kinds = [_cls(c) for c in cs]
        if kinds and kinds[0] == "separate":
            continue
        if kinds and kinds[0] == "header":
            label = cs[0].get_text(" ", strip=True)
            if "控え" in label:
                section = "bench"
            elif "交代" in label:
                section = "subs"
            elif "警告" in label or "退場" in label:
                break          # ⚠️ ここから先は読まない
            else:
                section = "other"
            continue
        if section in ("starters", "bench") and len(cs) == 6:
            pos, no, name = [c.get_text(" ", strip=True) for c in cs[side * 3:side * 3 + 3]]
            if not no or not name:
                continue       # 片側だけ空欄の行（控えの人数が違う試合）
            cap = bool(_CAP_RE.search(name))
            rec = dict(no=int(no), pos=pos, name=_CAP_RE.sub("", name), captain=cap)
            (starters if section == "starters" else bench).append(rec)
        elif section == "subs" and len(cs) == 4:
            no, txt = [c.get_text(" ", strip=True) for c in cs[side * 2:side * 2 + 2]]
            if not no or not txt:
                continue       # 交代数が少ない側の空欄
            m = _SUB_RE.match(txt)
            if not m:
                raise RuntimeError(f"交代の行が読めない: {no} {txt!r}")
            who = f"{no} {_CAP_RE.sub('', m.group('name')).strip()}"
            if m.group("dir") == "OUT":
                pending_out = who
            else:
                subs.append(dict(out=pending_out or "", **{"in": who},
                                 minute=m.group("minute")))
                pending_out = None
        elif section == "other":
            continue           # 監督の行
    return dict(starters=starters, bench=bench, subs=subs)


# ---------------------------------------------------------------------------
# 検算
# ---------------------------------------------------------------------------
def gate_g1(matches: dict) -> list[str]:
    """先発11人・うちGK1人。外れた試合の番号を返す（呼び手がその試合を捨てる）。"""
    bad = []
    for n, m in matches.items():
        st = m["starters"]
        if len(st) != 11 or sum(1 for p in st if p["pos"] == "GK") != 1:
            bad.append(n)
    return bad


def appearances(matches: dict) -> dict[tuple[int, str], int]:
    """先発＋途中出場（▲IN）から数えた出場試合数。キーは (背番号, 名前)。"""
    cnt: dict[tuple[int, str], int] = {}
    for m in matches.values():
        seen = set()
        for p in m["starters"]:
            seen.add((p["no"], p["name"]))
        for s in m["subs"]:
            t = s.get("in", "")
            mm = re.match(r"^(\d+)\s+(.+)$", t)
            if mm:
                seen.add((int(mm.group(1)), mm.group(2)))
        for k in seen:
            cnt[k] = cnt.get(k, 0) + 1
    return cnt


def gate_g2(roster: list[dict], matches: dict) -> list[str]:
    """出場試合数と選手一覧の「試合」が全員一致するか。"""
    cnt = appearances(matches)
    ng = []
    for p in roster:
        got = cnt.get((p["no"], p["name"]), 0)
        if got != p["apps"]:
            ng.append(f"{p['no']} {p['name']}: 一覧{p['apps']} ≠ 出場記録{got}")
    return ng


def gate_g3(roster: list[dict], team_name: str, league: dict, standing: dict) -> str:
    """得点の合計。選手一覧＋一覧に居ない得点者＋オウンゴール ＝ 順位表の得点。"""
    names = {p["name"] for p in roster}
    in_roster = sum(p["goals"] for p in roster)
    outside = og = 0
    for m in league["matches"]:
        if m.get("status") != "played":
            continue
        for key, who in (("homeScorers", m.get("home")), ("awayScorers", m.get("away"))):
            if who != team_name:
                continue
            for s in (m.get(key) or []):
                nm = (s.get("name") or "").strip()
                if "OG" in nm or "オウン" in nm:
                    og += 1
                elif nm not in names:
                    outside += 1
    total = in_roster + outside + og
    if total != standing["gf"]:
        return (f"得点の合計が合わない（一覧{in_roster}＋一覧外{outside}＋OG{og}"
                f"＝{total} ≠ 順位表{standing['gf']}）")
    return ""


def gate_g4(n_played: int, standing: dict) -> str:
    if n_played != standing["played"]:
        return f"消化試合数が合わない（試合一覧{n_played} ≠ 順位表{standing['played']}）"
    return ""


# ---------------------------------------------------------------------------
# 1チーム分
# ---------------------------------------------------------------------------
def team_name_in_league(meta: dict, teams_json: dict) -> str:
    """リーグJSON上の表記を data/teams.json の name/aliases から引く。

    ⚠️ md の `name`（流通経済大学付属柏高校）と、リーグJSON上の表記（流通経済大柏）は違う。
    """
    want = meta.get("name", "")
    pref = teams_json.get(meta.get("prefecture", ""), {})
    for t in pref.get("teams", []):
        if t.get("name") == want:
            return t.get("name")
    for p in teams_json.values():
        if not isinstance(p, dict):
            continue
        for t in p.get("teams", []):
            if t.get("name") == want or want in (t.get("aliases") or []):
                return t.get("name")
    return want


def league_team_key(name: str, aliases: list[str], league: dict) -> str:
    """リーグJSONの中で実際に使われている表記を返す。"""
    used = {m.get("home") for m in league["matches"]} | {m.get("away") for m in league["matches"]}
    for cand in [name] + list(aliases):
        if cand in used:
            return cand
    raise RuntimeError(f"リーグJSONに {name}（別名 {aliases}）が出てこない")


def aliases_of(meta: dict, teams_json: dict) -> list[str]:
    want = meta.get("name", "")
    for p in teams_json.values():
        if not isinstance(p, dict):
            continue
        for t in p.get("teams", []):
            if t.get("name") == want:
                return list(t.get("aliases") or [])
    return []


def process(team_id: str, meta: dict, teams_json: dict, dry_run: bool) -> str:
    jfa = str(meta.get("jfa_team") or "")
    m = re.fullmatch(r"([a-z0-9-]+)/(\d{2})", jfa)
    if not m:
        return f"[要確認] {team_id}: jfa_team の書式が違う（{jfa!r}）"
    slug, num = m.group(1), m.group(2)
    league_file = MATCH_DIR / f"{slug}.json"
    if not league_file.exists():
        return f"[要確認] {team_id}: {league_file.name} が無い"
    league = json.loads(league_file.read_text(encoding="utf-8"))

    name = team_name_in_league(meta, teams_json)
    key = league_team_key(name, aliases_of(meta, teams_json), league)
    standing = next((r for r in league.get("official_standings", []) if r.get("team") == key), None)
    if standing is None:
        return f"[要確認] {team_id}: 順位表に {key} が無い"

    # 既存（保存済みの試合は取り直さない）
    out_file = OUT_DIR / f"{team_id}.json"
    prev = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    matches: dict[str, dict] = dict(prev.get("matches") or {})

    played = [x for x in league["matches"]
              if x.get("status") == "played" and key in (x.get("home"), x.get("away"))]
    base = base_url(slug)
    want_numbers = {}
    for x in played:
        mm = re.search(r"/m(\d+)\.pdf$", x.get("reportUrl") or "")
        if mm:
            want_numbers[mm.group(1)] = x.get("md")

    # JFA公式の正式名（試合ページの1行目に出る名前）。md の name をそのまま使う。
    official = meta.get("name", "")
    fetched = skipped = 0
    for n, md_no in sorted(want_numbers.items(), key=lambda kv: int(kv[0])):
        if n in matches:
            continue
        html = fetch_html(f"{base}/match_page/m{n}.html")
        time.sleep(SLEEP)
        rec = parse_match(html, official)
        # ⚠️ 未消化ページ対策。先発が11人でなければ**入れない**（登録選手が全員並ぶため）
        if len(rec["starters"]) != 11:
            skipped += 1
            continue
        matches[n] = dict(md=md_no, **rec)
        fetched += 1

    bad = gate_g1(matches)
    for n in bad:
        matches.pop(n)
    # 順位表に無い（＝まだ結果が入っていない）試合が残っていたら落とす
    matches = {n: v for n, v in matches.items() if n in want_numbers}

    g4 = gate_g4(len(want_numbers), standing)
    if g4:
        return f"[据え置き] {team_id}: {g4}"

    roster_url = f"{base}/team_detail/{num}.html"
    roster = parse_roster(fetch_html(roster_url))
    time.sleep(SLEEP)

    g3 = gate_g3(roster, key, league, standing)
    if g3:
        return f"[据え置き] {team_id}: {g3}"

    note = ""
    ng2 = gate_g2(roster, matches)
    if ng2:
        # ⚠️ JFAは試合ページと選手一覧の更新時刻がずれることがある。
        #    そのときは**選手一覧だけ据え置き**（試合は保存する）。
        if prev.get("roster"):
            roster = prev["roster"]
            note = f"選手一覧を据え置き（出場試合数が合わない {len(ng2)}件：{ng2[0]}）"
        else:
            return f"[据え置き] {team_id}: 出場試合数が合わない {len(ng2)}件（{ng2[0]}）"

    asof = max((x["date"] for x in played if x.get("date")), default="")
    data = dict(team_id=team_id, jfa_team=jfa, league=slug, league_team=key,
                source_roster=roster_url,
                source_match=f"{base}/match_page/",
                asof=asof, roster=roster,
                matches=dict(sorted(matches.items(), key=lambda kv: int(kv[0]))))
    if dry_run:
        return (f"[DRY RUN] {team_id}: 試合{len(matches)}・選手{len(roster)}"
                f"（新規取得{fetched}・未消化で見送り{skipped}）")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tail = f"／{note}" if note else ""
    return (f"[更新] {team_id}: 試合{len(matches)}・選手{len(roster)}"
            f"（新規取得{fetched}）{tail}")


def classify(msg: str) -> tuple[str, str]:
    body = msg.split(": ", 1)[-1]
    if msg.startswith("[更新]") or msg.startswith("[DRY RUN]"):
        return "ok", body
    if msg.startswith("[据え置き]"):
        return "gate_failed", body
    return "error", body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="jfa_team を書いたチームの登録選手・先発をJFA公式から取る")
    parser.add_argument("--only", default="", help="team_id をカンマ区切りで指定")
    parser.add_argument("--dry-run", action="store_true", help="書き込まない")
    args = parser.parse_args()          # ⚠️ --help はここで終わる（本処理を走らせない）
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    teams_json = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    targets = []
    for md_file in sorted(PROFILES_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        if "jfa_team:" not in text:
            continue
        try:
            meta = yaml.safe_load(text.split("---", 2)[1]) or {}
        except Exception:               # noqa: BLE001
            print(f"  [SKIP] {md_file.name}: frontmatter が読めない")
            continue
        if not meta.get("jfa_team") or not meta.get("id"):
            continue
        if only and meta["id"] not in only:
            continue
        targets.append((meta["id"], meta))

    print(f"=== チームのシーズンデータ（JFA公式）: 対象{len(targets)}チーム ===")
    ok = ng = 0
    for team_id, meta in targets:
        try:
            msg = process(team_id, meta, teams_json, args.dry_run)
        except Exception as e:          # 1チーム失敗しても他は続ける
            msg = f"[要確認] {team_id}: 例外 {type(e).__name__}: {e}"
        print(" ", msg)
        if not args.dry_run:
            fetch_status.set_job_result(f"team_season:{team_id}", *classify(msg))
        if msg.startswith("[更新]") or msg.startswith("[DRY RUN]"):
            ok += 1
        else:
            ng += 1
    print(f"--- 完了: 更新{ok} / 据え置き・要確認{ng} ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
