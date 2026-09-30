#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
U-15（3種）県リーグ1部の試合と順位表を取り込む（2026-09-30 新設・試作7県＋島根）
=====================================================================
出力：data/u15/pref/u15-{県}-1.json（U-18 の data/league_matches/pref-*.json と同じキー構成）
      → generate_u15_pref_pages.py が /u15/{県}/ を作る。戦績表は cross_table.py を共用する。

⚠️ U-15 のJSONは data/league_matches/ に**置かない**。そこを総なめにする U-18 の見張り
   （audit_match_dates / audit_pref_freshness / check_standings_vs_matches）や
   sync_teams_from_*（U-18 の teams.json を触る）に入り込まないよう、data/u15/pref/ に隔離する。
⚠️ 中学生の選手名（得点者など）は扱わない。チーム単位の情報だけ。

■ 安全装置（リーグごとに独立。NGの県は既存のJSONを残す）
  1. 検算：全試合から計算し直した 勝点・試合・勝・分・敗・得点・失点 が出典の順位表と全チーム一致
     （新潟は公式順位表が無いので 2. 4. の構造検算で代える＝self）
  2. 顔ぶれ：チーム名の集合が既存JSONと完全一致（初回は設定のチーム数と一致）
  3. 退行ガード：消化試合数が既存より減る更新は捨てる
  4. 構造：各組ちょうど2試合、全試合数＝n×(n−1)
  5. 例外はすべて捕まえ、終了コードは常に0（毎朝のワークフローを止めない）

■ 出典ごとの読み方（U-18 の fetch_pref_official.py の読み取り関数は**変えずに**、ここに別に書いた）
  同じプラットフォームでも U-15 では扱いが違う（神奈川は順位表が同じページ・未消化の枠も持つ／
  新潟は幽霊の行 No.0・英字チーム名の空白を消してはいけない など）。U-18 側に分岐を足して共用するより
  別に書くほうが安全、という fetch_pref_official.py の SportsOnline の注記と同じ判断。

使い方:
  python scraper/fetch_u15_pref.py                  # 7県
  python scraper/fetch_u15_pref.py --dry-run        # 書き込まない
  python scraper/fetch_u15_pref.py --only tochigi,gunma
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "data" / "u15" / "pref"

SEASON = "2026"          # ← 年度切り替え（下の PREFS の大会番号・URL も差し替える）
TIMEOUT = 30
RETRIES = 3
SLEEP = 2.0
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; u18-soccer-bot/1.0; +https://u18-soccer.com)"}

_JST = datetime.timezone(datetime.timedelta(hours=9))

# ---------------------------------------------------------------------------
# 県ごとの設定（年度切り替えでは大会番号・URL・見出しを手で差し替える）
#   gc-model の大会番号は毎年変わる（長崎は2025年が GoalNote、佐賀は2025年が134）。
# ---------------------------------------------------------------------------
PREFS = {
    "tochigi": dict(
        kind="gcmodel", base="https://gc-model.com/front/tochigi/convention", tid=212, heading="1部リーグ",
        teams=10, prefName="栃木県", region="関東",
        league="2026年度 高円宮杯栃木ユース（U-15）サッカーリーグ 1部リーグ",
        sourceName="栃木U-15リーグ（gc-model）"),
    "gunma": dict(
        kind="gcmodel", base="https://gc-model.com/01/gunma-fa/convention", tid=224, heading="ウルトラリーグ",
        teams=10, prefName="群馬県", region="関東",
        league="高円宮杯 JFA U-15 サッカーリーグ2026群馬 ウルトラリーグ",
        sourceName="群馬県サッカー協会（gc-model）"),
    "saga": dict(
        kind="gcmodel", base="https://gc-model.com/front/saga/convention", tid=223, heading="1部",
        teams=8, prefName="佐賀県", region="九州",
        league="2026高円宮杯 佐賀県U-15サッカーリーグ（サガんリーグU-15） 1部",
        sourceName="佐賀県サッカー協会 3種（gc-model）"),
    "nagasaki": dict(
        kind="gcmodel", base="https://gc-model.com/front/nagasaki/convention", tid=217, heading="1部",
        teams=10, prefName="長崎県", region="九州",
        league="宅島グループ杯 長崎県U-15サッカーリーグ2026 1部",
        sourceName="長崎県サッカー協会（gc-model）"),
    "kanagawa": dict(
        kind="kanagawa", url=f"https://www.kanagawa-fa.gr.jp/cms/u15/competition/u15-1b-{SEASON}/",
        teams=10, prefName="神奈川県", region="関東",
        league=f"{SEASON} 神奈川県U-15リーグ 1部",
        sourceName="神奈川県サッカー協会 3種大会部会",
        retries=6, retry_wait=5.0, timeout=90,        # U-18 神奈川と同じ（大きいページで504が出やすい）
        # 表示だけ直す（照合は出典の表記のまま）。出典はひらがなの「ぺ」
        display={"カルぺソール湘南": "カルペソール湘南"}),
    "hiroshima": dict(
        kind="sportsonline",
        url="http://www.sportsonline.jp/reportv2/PublisherFull/viewdata.aspx?parentid=RX_VW&rallyid=U%5e%5eWV",
        teams=10, prefName="広島県", region="中国",
        league=f"高円宮杯 JFA U-15サッカーリーグ {SEASON} HiFAユースリーグ 1部リーグ",
        sourceName="広島県サッカー協会（SportsOnline）"),
    # 島根（2026-09-30 追補・8県目）。広島と同じ SportsOnline。運営者名がサイト上で確認できないので団体名は書かない
    #   rallyid は Rally.aspx の GameEdit 番号（66300）から計算できる（追補 §3・手順書7章）
    "shimane": dict(
        kind="sportsonline",
        url="http://www.sportsonline.jp/reportv2/PublisherFull/viewdata.aspx?parentid=RX_UX&rallyid=U%5E%5CS_",
        teams=8, prefName="島根県", region="中国",
        league=f"高円宮杯 JFA U-15サッカーリーグ{SEASON}島根 1部リーグ",
        sourceName="SportsOnline（島根U-15リーグ）"),
    "niigata": dict(
        kind="niigata", tid=582, must_contain=f"U-15サッカーリーグ {SEASON}",   # 「リーグ」と年の間に空白
        teams=10, prefName="新潟県", region="北信越",
        league=f"高円宮杯 JFA U-15サッカーリーグ {SEASON} 新潟県 1部",
        sourceName="新潟県サッカー協会 公式",
        # 表記ゆれ（16通り→10チーム）。表示名はCoworkの仮決め（2026-09-30）。どちらが正式かは未確認
        aliases={"AC United": "AC UNITED", "FCLAZO": "FC LAZO", "ROUSE 新潟FC": "ROUSE新潟FC",
                 "ROUSE新潟": "ROUSE新潟FC", "エボルブfc": "エボルブFC", "グランセナ2nd": "グランセナ新潟2nd"}),
}


def today_jst() -> datetime.date:
    return datetime.datetime.now(_JST).date()


class ReadError(Exception):
    """出典が読めなかった（見出しが無い・表の形が違う）。diag に自動診断を入れる。"""
    def __init__(self, msg: str, diag: list[str] | None = None):
        super().__init__(msg)
        self.diag = diag or []


def fetch(url: str, must_contain: str = "", retries: int = RETRIES, wait: float = SLEEP,
          timeout: int = TIMEOUT, encoding: str | None = None) -> str:
    last = None
    for _ in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            r.encoding = encoding or "utf-8"
            text = r.text
            if must_contain and must_contain not in text:
                raise RuntimeError(f"期待した文字列 {must_contain!r} が無い")
            return text
        except Exception as e:          # noqa: BLE001
            last = e
            time.sleep(wait)
    raise ReadError(f"取得失敗 ({last})")


def _int(v):
    s = unicodedata.normalize("NFKC", str(v)).strip().lstrip("+")
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def _clean(s: str) -> str:
    """チーム名：前後の空白を落とし、連続する空白を1つにする。
    ⚠️ 空白を全部消さない（「FC LAZO」「AC UNITED」が「FCLAZO」「ACUNITED」になる）。"""
    return re.sub(r"\s+", " ", (s or "").replace("　", " ")).strip()


def _md_date(mo: int, da: int) -> str:
    return f"{SEASON}-{mo:02d}-{da:02d}"


# ---------------------------------------------------------------------------
# gc-model（栃木・群馬・佐賀・長崎）
# ---------------------------------------------------------------------------
_GC_HEAD = {"勝点": "pts", "試合数": "played", "勝": "won", "分": "drawn", "敗": "lost",
            "得点": "gf", "失点": "ga"}
_GC_PLACEHOLDER_VENUES = {"テスト競技場", "未定"}


def read_gcmodel(cfg: dict) -> tuple[dict, list[dict]]:
    heading = cfg["heading"]
    order = BeautifulSoup(fetch(f"{cfg['base']}/order/{cfg['tid']}"), "html.parser")
    time.sleep(SLEEP)
    h3s = [h for h in order.select("main h3") if h.get_text(strip=True) == heading]   # 完全一致
    if len(h3s) != 1:
        raise ReadError(f"順位表ページに見出し「{heading}」が{len(h3s)}個（1個のはず）",
                        ["順位表の見出し: " + " / ".join(h.get_text(strip=True) for h in order.select("main h3"))])
    table = h3s[0].find_next("table")
    rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
    head = rows[0]
    col = {key: head.index(name) for name, key in _GC_HEAD.items() if name in head}   # 見出しの文字で列を決める
    if len(col) != len(_GC_HEAD) or "チーム名" not in head or "順位" not in head:
        raise ReadError("順位表の見出し行が想定と違う", [f"見出し行: {head}"])
    standings = {}
    for r in rows[1:]:
        name = _clean(r[head.index("チーム名")])
        vals = {k: _int(r[i]) for k, i in col.items()}
        vals["rank"] = _int(r[head.index("順位")])
        if not name or any(v is None for v in vals.values()):
            raise ReadError(f"順位表の行が読めない: {r}")
        standings[name] = vals

    sched = BeautifulSoup(fetch(f"{cfg['base']}/schedule/{cfg['tid']}"), "html.parser")
    uls = [u for u in sched.select("ul.convention_schedule_list")
           if u.find("h3") and u.find("h3").get_text(strip=True) == heading]
    if len(uls) != 1:
        raise ReadError(f"日程ページに見出し「{heading}」の一覧が{len(uls)}個（1個のはず）",
                        ["日程の見出し: " + " / ".join(u.find("h3").get_text(strip=True)
                                                    for u in sched.select("ul.convention_schedule_list") if u.find("h3"))])
    matches = []
    for li in uls[0].find_all("li", recursive=False):
        if li.find("h3"):
            continue                                        # 先頭の見出しの行
        home, away = li.select_one(".home_team p"), li.select_one(".away_team p")
        if not home or not away:
            raise ReadError("試合の行の形が想定と違う（チーム名が無い）")
        # ⚠️ 日付と時刻は <br> でつながっている。区切りを入れて取り出す（「4/118:45」を避ける）
        dt = li.select_one(".match_date p")
        dt_txt = dt.get_text(" ", strip=True) if dt else ""
        dm = re.match(r"^(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}:\d{2}))?", dt_txt)
        status = li.select_one(".match_status")
        score = li.select_one(".match_score p")
        sc = re.fullmatch(r"(\d+)-(\d+)", re.sub(r"\s", "", score.get_text("", strip=True))) if score else None
        played = bool(status and status.get_text(strip=True) == "試合終了" and sc)
        venue = li.select_one(".match_place p")
        v = _clean(venue.get_text(" ", strip=True)) if venue else ""
        matches.append(dict(
            md=0, date=_md_date(int(dm.group(1)), int(dm.group(2))) if dm else "",
            home=_clean(home.get_text(" ", strip=True)), away=_clean(away.get_text(" ", strip=True)),
            hs=int(sc.group(1)) if played else None, **{"as": int(sc.group(2)) if played else None},
            venue="" if v in _GC_PLACEHOLDER_VENUES else v,
            kickoff=(dm.group(3) or "") if dm else ""))
    return standings, matches


# ---------------------------------------------------------------------------
# 神奈川（県協会3種・AnWP）：順位表も試合も同じページ
# ---------------------------------------------------------------------------
_KANAGAWA15_HEAD = {"勝点": "pts", "試合": "played", "勝": "won", "分": "drawn", "敗": "lost",
                    "得点": "gf", "失点": "ga", "差": "gd"}


def read_kanagawa15(cfg: dict) -> tuple[dict, list[dict]]:
    soup = BeautifulSoup(fetch(cfg["url"], must_contain="anwp-fl-game", retries=cfg.get("retries", RETRIES),
                               wait=cfg.get("retry_wait", SLEEP), timeout=cfg.get("timeout", TIMEOUT)),
                         "html.parser")
    tbls = soup.select(".standing-table")
    if len(tbls) != 1:
        raise ReadError(f"順位表（.standing-table）が{len(tbls)}個（1個のはず）")
    cells = tbls[0].find_all(recursive=False)
    texts = [c.get_text(" ", strip=True) for c in cells]
    if "Club" not in texts:
        raise ReadError("順位表の見出しに Club が無い", [f"先頭のセル: {texts[:14]}"])
    j = texts.index("Club") + 1
    order = []
    while j < len(texts) and texts[j] in _KANAGAWA15_HEAD:
        order.append(_KANAGAWA15_HEAD[texts[j]])
        j += 1
    if set(order) != set(_KANAGAWA15_HEAD.values()):
        raise ReadError("順位表の見出しが想定と違う", [f"見出し: {texts[:j]}"])
    width = 2 + len(order)
    standings = {}
    for k in range(j, len(cells) - width + 1, width):
        row = cells[k:k + width]
        link = row[1].find("a")                   # チーム名セルには直近5試合の勝敗が混ざるので a から取る
        name = _clean(link.get_text(" ", strip=True) if link else row[1].get_text(" ", strip=True))
        vals = {key: _int(row[2 + n].get_text(" ", strip=True)) for n, key in enumerate(order)}
        vals.pop("gd", None)
        vals["rank"] = _int(row[0].get_text(strip=True))
        if not name or any(v is None for v in vals.values()):
            raise ReadError(f"順位表の行が読めない: {[c.get_text(' ', strip=True) for c in row]}")
        standings[name] = vals

    matches = []
    for el in soup.select(".anwp-fl-game"):
        cls = el.get("class") or []
        h = el.select_one(".match-slim__team-home-title")
        a = el.select_one(".match-slim__team-away-title")
        if not (h and a):
            raise ReadError("試合の行の形が想定と違う（チーム名が無い）")
        played = "game-status-1" in cls
        hs = as_ = None
        if played:
            hs = _int(el.select_one(".anwp-fl-game__scores-home").get_text(strip=True))
            as_ = _int(el.select_one(".anwp-fl-game__scores-away").get_text(strip=True))
            if hs is None or as_ is None:
                raise ReadError("消化済みの試合のスコアが読めない")
        kick = el.get("data-fl-game-kickoff") or ""
        # ⚠️ 未消化の枠の kickoff は「-001-11-30T00:00:00+09:18」というゴミ値。正しい形の日付だけ使う
        ok = re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00", kick)
        matches.append(dict(md=0, date=kick[:10] if ok else "",
                            home=_clean(h.get_text(" ", strip=True)), away=_clean(a.get_text(" ", strip=True)),
                            hs=hs, **{"as": as_}, kickoff=kick[11:16] if ok else ""))
    return standings, matches


# ---------------------------------------------------------------------------
# 広島（SportsOnline）：順位表の列は「勝数・負数・引分」の順（位置で読むと敗と分が入れ替わる）
# ---------------------------------------------------------------------------
_SO_HEAD = {"勝数": "won", "負数": "lost", "引分": "drawn", "勝点": "pts", "得点": "gf", "失点": "ga"}
_SO_PLAYED = re.compile(r"^(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)$")
_SO_SCHED = re.compile(r"^(.+?)\s+-\s+(.+)$")
_SO_DATE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def read_sportsonline15(cfg: dict) -> tuple[dict, list[dict]]:
    soup = BeautifulSoup(fetch(cfg["url"], must_contain="得失差"), "html.parser")
    tables = soup.find_all("table")
    standings = {}
    for table in tables:
        texts = [c.get_text(" ", strip=True) for c in table.find_all(["td", "th"])]
        if "得失差" not in texts or "勝点" not in texts:
            continue
        width = texts.index("得失差") + 1           # 1行に潰れた順位表を見出しの幅で切り直す
        head = texts[:width]
        col = {key: head.index(name) for name, key in _SO_HEAD.items() if name in head}
        if len(col) != len(_SO_HEAD):
            raise ReadError("順位表の見出しが想定と違う", [f"見出し: {head}"])
        rows = [texts[i:i + width] for i in range(width, len(texts), width)]
        if len(rows) != cfg["teams"] or any(len(r) != width for r in rows):
            raise ReadError(f"順位表の復元行数 {len(rows)} がチーム数 {cfg['teams']} と一致しない")
        for r in rows:
            vals = {k: _int(r[i]) for k, i in col.items()}
            if any(v is None for v in vals.values()):
                raise ReadError(f"順位表の行が読めない: {r}")
            vals["played"] = vals["won"] + vals["drawn"] + vals["lost"]
            vals["rank"] = _int(r[0])
            standings[_clean(r[1])] = vals
        break
    if not standings:
        raise ReadError("順位表（得失差・勝点のある表）が見つからない")

    matches = []
    for table in tables:
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
        head = next((r for r in rows if len(r) >= 4 and "組み合わせ" in r[0]), None)
        if not head:
            continue
        for r in rows[rows.index(head) + 1:]:
            if len(r) < 4:
                continue                             # 「Away」の区切り行
            dm = _SO_DATE.search(r[1])
            date = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else ""
            venue = (r[4] if len(r) > 4 else "").replace("??芝", "人工芝")    # 文字化け（元は「人工芝」）
            if venue == "未定":
                venue = ""                           # 仮の値（島根で9試合）。会場名としては出さない
            if "試合終了" in r[3]:
                m = _SO_PLAYED.match(r[0])
                if not m:
                    raise ReadError(f"消化済みの試合の行が読めない: {r[0]!r}")
                matches.append(dict(md=0, date=date, home=_clean(m.group(1)), away=_clean(m.group(4)),
                                    hs=int(m.group(2)), **{"as": int(m.group(3))},
                                    venue=venue, kickoff=r[2].strip()))
            else:
                m = _SO_SCHED.match(r[0])
                if not m:
                    raise ReadError(f"未消化の試合の行が読めない: {r[0]!r}（状況 {r[3]!r}）")
                matches.append(dict(md=0, date=date, home=_clean(m.group(1)), away=_clean(m.group(2)),
                                    hs=None, **{"as": None}, venue=venue, kickoff=r[2].strip()))
        break
    if not matches:
        raise ReadError("試合一覧（組み合わせの表）が見つからない")
    return standings, matches


# ---------------------------------------------------------------------------
# 新潟（県協会の結果システム）：公式順位表は無い＝自前計算
# ---------------------------------------------------------------------------
_NI_DATE = re.compile(r"^(\d{2})\.(\d{2})$")
_NI_SCORE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def read_niigata15(cfg: dict) -> tuple[dict, list[dict]]:
    url = f"https://www.niigata-fa.or.jp/result/contest/tournament_id/{cfg['tid']}"
    soup = BeautifulSoup(fetch(url, must_contain=cfg["must_contain"]), "html.parser")
    n = cfg["teams"]
    matches, ghosts = [], 0
    for b in soup.select("div.p-result__tournament"):
        md_p, date_p, side = b.select(".type p"), b.select(".date p"), b.select(".score > p")
        if len(md_p) < 2 or not date_p or len(side) < 3:
            raise ReadError("試合ブロックの形が想定と違う")
        if md_p[0].get_text(strip=True) == "No.0":
            ghosts += 1                              # 延期された試合の元の枠が残った「幽霊の行」
            continue
        dm = _NI_DATE.match(date_p[0].get_text(strip=True))
        if not dm:
            raise ReadError(f"日付が読めない: {date_p[0].get_text(strip=True)!r}")
        mid = re.sub(r"\s+", " ", side[1].get_text(" ", strip=True))
        sm = _NI_SCORE.match(mid)
        if not sm and mid != "試合予定":
            raise ReadError(f"スコア欄が読めない: {mid!r}")
        lab = md_p[1].get_text(strip=True)
        mdm = re.search(r"\d+", lab)
        md = int(mdm.group()) if mdm else (2 * (n - 1) if lab == "最終節" else 0)
        matches.append(dict(md=md, date=_md_date(int(dm.group(1)), int(dm.group(2))),
                            home=_clean(side[0].get_text(" ", strip=True)),
                            away=_clean(side[-1].get_text(" ", strip=True)),
                            hs=int(sm.group(1)) if sm else None, **{"as": int(sm.group(2)) if sm else None}))
    if ghosts:
        print(f"    （新潟: No.0 の幽霊の行を{ghosts}件捨てた）")
    return {}, matches


READERS = {"gcmodel": read_gcmodel, "kanagawa": read_kanagawa15,
           "sportsonline": read_sportsonline15, "niigata": read_niigata15}


# ---------------------------------------------------------------------------
# 検算と組み立て
# ---------------------------------------------------------------------------
def tally(teams: set, matches: list[dict]) -> dict:
    t = {n: dict(pts=0, played=0, won=0, drawn=0, lost=0, gf=0, ga=0) for n in teams}
    for m in matches:
        if m["hs"] is None:
            continue
        for me, gf, ga in ((m["home"], m["hs"], m["as"]), (m["away"], m["as"], m["hs"])):
            s = t[me]
            s["played"] += 1
            s["gf"] += gf
            s["ga"] += ga
            s["won"] += gf > ga
            s["drawn"] += gf == ga
            s["lost"] += gf < ga
            s["pts"] += 3 if gf > ga else 1 if gf == ga else 0
    return t


def build(key: str, cfg: dict, standings: dict, matches: list[dict], old: dict | None) -> dict:
    """検算を通れば書き込むJSONを返す。通らなければ ValueError（理由つき）。"""
    n = cfg["teams"]
    alias = cfg.get("aliases") or {}
    for m in matches:
        m["home"], m["away"] = alias.get(m["home"], m["home"]), alias.get(m["away"], m["away"])
    teams = {m["home"] for m in matches} | {m["away"] for m in matches}
    if len(teams) != n:
        raise ValueError(f"チーム数{len(teams)}（{n}のはず）: {sorted(teams)}")
    if len(matches) != n * (n - 1):
        raise ValueError(f"試合数{len(matches)}（2回戦総当たりの{n * (n - 1)}のはず）")
    pairs = {}
    for m in matches:
        if m["home"] == m["away"]:
            raise ValueError(f"同じチーム同士の試合がある: {m['home']}")
        pairs.setdefault(frozenset((m["home"], m["away"])), []).append(m)
    bad = [sorted(p) for p, v in pairs.items() if len(v) != 2]
    if len(pairs) != n * (n - 1) // 2 or bad:
        raise ValueError(f"対戦の組が{len(pairs)}（{n * (n - 1) // 2}のはず）・2試合でない組 {bad[:3]}")

    mine = tally(teams, matches)
    if standings:
        if set(standings) != teams:
            raise ValueError(f"順位表と試合のチーム名が合わない: 順位表だけ {sorted(set(standings) - teams)}"
                             f"／試合だけ {sorted(teams - set(standings))}")
        diff = [f"{t}.{k} 表{standings[t][k]}≠試合{mine[t][k]}"
                for t in sorted(teams) for k in mine[t] if standings[t][k] != mine[t][k]]
        if diff:
            raise ValueError("検算不一致 " + "; ".join(diff[:4]) + (" …" if len(diff) > 4 else ""))

    disp = cfg.get("display") or {}
    dn = lambda x: disp.get(x, x)          # noqa: E731  表示名（照合は済んでいる）
    if old and old.get("teams"):
        before = {t["name"] for t in old["teams"]}
        if before != {dn(t) for t in teams}:
            raise ValueError(f"顔ぶれが既存JSONと違う: 新規 {sorted({dn(t) for t in teams} - before)}"
                             f"／消えた {sorted(before - {dn(t) for t in teams})}")
    played_now = sum(1 for m in matches if m["hs"] is not None)
    played_old = sum(1 for m in (old or {}).get("matches", []) if m.get("status") == "played")
    if played_now < played_old:
        raise ValueError(f"消化試合数が減る（既存{played_old}→今回{played_now}）")

    if standings:
        order = sorted(teams, key=lambda t: (standings[t]["rank"], t))
        rank = {t: standings[t]["rank"] for t in teams}
    else:   # 自前計算：勝点→得失点差→得点（新潟）
        kf = lambda t: (-mine[t]["pts"], -(mine[t]["gf"] - mine[t]["ga"]), -mine[t]["gf"])   # noqa: E731
        order = sorted(teams, key=lambda t: (kf(t), t))
        rank, prev = {}, None
        for i, t in enumerate(order, 1):
            rank[t] = rank[prev] if prev is not None and kf(prev) == kf(t) else i
            prev = t
    official = [dict(rank=rank[t], team=dn(t), points=mine[t]["pts"], played=mine[t]["played"],
                     won=mine[t]["won"], drawn=mine[t]["drawn"], lost=mine[t]["lost"],
                     gf=mine[t]["gf"], ga=mine[t]["ga"], gd=mine[t]["gf"] - mine[t]["ga"]) for t in order]
    out_matches = []
    for m in sorted(matches, key=lambda m: (m["date"] or "9999", m["md"], m["home"])):
        row = dict(md=m["md"], date=m["date"], home=dn(m["home"]), hs=m["hs"], **{"as": m["as"]},
                   away=dn(m["away"]), status="played" if m["hs"] is not None else "scheduled")
        if m.get("venue"):
            row["venue"] = m["venue"]
        out_matches.append(row)
    out = dict(league=cfg["league"], season=SEASON, pref=key, prefName=cfg["prefName"], region=cfg["region"],
               source=_source_url(cfg), sourceName=cfg["sourceName"], lastUpdated=today_jst().isoformat(),
               teams=[dict(name=dn(t), short=dn(t)) for t in order],
               official_standings=official, matches=out_matches)
    if not standings:
        out["standings_source"] = "self"
    return out


def _source_url(cfg: dict) -> str:
    if cfg["kind"] == "gcmodel":
        return f"{cfg['base']}/order/{cfg['tid']}"
    if cfg["kind"] == "niigata":
        return f"https://www.niigata-fa.or.jp/result/contest/tournament_id/{cfg['tid']}"
    return cfg["url"]


def _same(a: dict, b: dict) -> bool:
    keys = set(a) | set(b)
    keys.discard("lastUpdated")
    return all(a.get(k) == b.get(k) for k in keys)


def main() -> int:
    ap = argparse.ArgumentParser(description="U-15県リーグ1部（試作7県）を取り込む")
    ap.add_argument("--dry-run", action="store_true", help="取得と検算だけ行い書き込まない")
    ap.add_argument("--only", default="", help="県（tochigi など）をカンマ区切りで指定")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    print(f"=== U-15県1部（試作{len(PREFS)}県）{'【DRY RUN】' if args.dry_run else ''} ===")
    summary = []
    for key, cfg in PREFS.items():
        if only and key not in only:
            continue
        slug = f"u15-{key}-1"
        path = OUT_DIR / f"{slug}.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        print(f"■ {cfg['prefName']}（{slug}）")
        try:
            standings, matches = READERS[cfg["kind"]](cfg)
        except Exception as e:          # noqa: BLE001
            print(f"    読めなかった: {e}")
            for d in getattr(e, "diag", []):
                print(f"    [診断] {d}")
            summary.append(f"— {cfg['prefName']}: 取得できず（{_source_url(cfg)}）")
            continue
        finally:
            time.sleep(SLEEP)
        try:
            out = build(key, cfg, standings, matches, old)
        except Exception as e:          # noqa: BLE001
            summary.append(f"⏸ {cfg['prefName']}: 検証NG（{e}）")
            continue
        played = sum(1 for m in out["matches"] if m["status"] == "played")
        top = out["official_standings"][0]
        info = f"消化{played}／{len(out['matches'])}・首位 {top['team']}（{top['points']}）"
        if old and _same(old, out):
            summary.append(f"✅ {cfg['prefName']}: 変化なし（{info}）")
            continue
        if not args.dry_run:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        summary.append(f"✅ {cfg['prefName']}: 更新（{info}）{'【DRY RUN・書き込みなし】' if args.dry_run else ''}")
    print()
    for s in summary:
        print(s)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:            # ワークフローを止めない
        print(f"❌ 想定外のエラー（既存データは変更していません）: {e}")
        sys.exit(0)
