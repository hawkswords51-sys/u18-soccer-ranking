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
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

import pdf_source   # PDFの4県（秋田・長野・石川・愛媛）の取得と行への復元（U-18と共用）

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
    # ---- 第3弾：県協会のPDF（2026-10-01）。url は入口ページ（PDFのURLは更新のたびに変わるので毎回ここから拾う）----
    # 秋田：日程表＝試合の正本・星取表＝検算（既定＝全項目一致）。表示名は星取表の表記
    "akita": dict(
        kind="akita_pdf", url="https://fa-akita.net/17086/",
        teams=8, prefName="秋田県", region="東北",
        league=f"高円宮杯JFA U-15サッカーリーグ{SEASON}秋田県すぎっちリーグ（1部）",
        sourceName="秋田県サッカー協会 3種（PDF）"),
    # 長野：試合結果PDF＝正本。星取表は得点・失点に誤りがある（合計342≠339）→ 勝点だけ照合・順位は自前計算
    "nagano": dict(
        kind="nagano_pdf", url="https://www.nagano-fa.or.jp/cat_3",
        teams=10, prefName="長野県", region="北信越",
        league=f"高円宮杯 JFA U-15サッカーリーグ{SEASON} 長野県1部リーグ（県TOP1部）",
        sourceName="長野県サッカー協会 3種（PDF）",
        check_keys=("pts",), info_keys=("gf", "ga"), rank_from="self",
        per_md=5, x_date=(205, 243), x_venue=364,
        # 星取表の表記（照合キー）→ 試合結果PDFの表記（照合キー）。LEGARE は星取表の綴り誤りと思われる
        hoshi_aliases={"アルティスタ浅間": "アルティスタ浅間U-15", "松本山雅FC上伊那": "松本山雅上伊那",
                       "松本山雅FCB": "松本山雅FCU-15B", "LEGARE上田": "LIGARE上田"}),
    # 石川：星取表1枚。順位表は勝点・得点・失点・順位だけ。行と列の左右一致も検算に使う
    "ishikawa": dict(
        kind="ishikawa_pdf", url=f"https://www.ishikawa-fa.or.jp/category-3-{SEASON}",
        teams=8, prefName="石川県", region="北信越",
        league=f"高円宮杯 JFA U-15サッカーリーグ{SEASON} 第19回石川県リーグ（1部）",
        sourceName="石川県サッカー協会 3種（PDF）",
        check_keys=("pts", "gf", "ga"),
        # 行の並び順（＝列の並び順）。見出しは略称・2行割れなので、名前ではなく順番で対応させる
        names=["セブン能登1st", "FC北陸U15 1st", "ツエーゲン金沢2nd", "PateoFC金沢2nd",
               "SOLTILO SEIRYO 1st", "エスポワール白山2nd", "金沢学院大附属中学校", "星稜中学校1st"]),
    # 愛媛：1ページ目＝前期・2ページ目＝後期。左半分＝日程表（正本）・右半分＝星取表（年間成績で検算）
    "ehime": dict(
        kind="ehime_pdf", url="https://efa.jp/meeting/43721.html",
        teams=10, prefName="愛媛県", region="四国",
        league=f"高円宮杯JFA U-15サッカーリーグ{SEASON} 愛媛県プレミアリーグU-15（EPリーグ）Div.1",
        sourceName="愛媛県サッカー協会（PDF）",
        check_keys=("pts", "gf", "ga"), md_per_page=9,
        x=dict(split=510, label=(515, 551), annual=905, md=(66, 82), date=(82, 130), venue=(130, 182),
               home=(205, 253), dash=(285, 297), away=(333, 420))),
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


# ---------------------------------------------------------------------------
# PDFの4県（秋田・長野・石川・愛媛）2026-10-01 第3弾
#   PDFの取得と行への復元は pdf_source（U-18と共用）。**読み取りは県ごとに書く**（U-18と同じ方針）。
#   URLは毎回入口ページから拾う（ファイル名がハッシュ・版番号・日付で更新のたびに変わる）。
# ---------------------------------------------------------------------------
def _nk(s: str) -> str:
    """照合用：NFKC＋空白をすべて除く（表示には使わない）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def _entry_pdf_links(cfg: dict, pred) -> list[str]:
    """入口ページのPDFリンクのうち pred(リンク文字NFKC空白なし, 絶対URL) を満たすもの（重複URLは1つ）。"""
    soup = BeautifulSoup(fetch(cfg["url"]), "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        url = urljoin(cfg["url"], a["href"].strip())
        if url.lower().endswith(".pdf") and url not in out and pred(_nk(a.get_text()), unquote(url)):
            out.append(url)
    return out


def _one_link(cfg: dict, pred, label: str) -> str:
    hits = _entry_pdf_links(cfg, pred)
    if len(hits) != 1:
        raise ReadError(f"入口ページに{label}のPDFリンクが{len(hits)}件（1件のはず）", [unquote(u) for u in hits])
    time.sleep(SLEEP)
    print(f"    {label}: {unquote(hits[0])}")
    return hits[0]


def _open(url: str):
    return pdf_source.open_pdf(pdf_source.fetch_pdf(url, HEADERS, TIMEOUT, RETRIES, SLEEP))


def _team_prefix(text: str, names: dict) -> tuple[str, str] | None:
    """text の先頭にあるチーム名（照合キー nk → 表示名 の names から一番長く一致するもの）と残りの文字。"""
    t = _nk(text)
    best = max((k for k in names if t.startswith(k)), key=len, default=None)
    return (names[best], t[len(best):]) if best else None


def _after_name(text: str, name: str) -> str:
    """text の先頭からチーム名（照合キーの文字数ぶん）を読み飛ばした残り（会場など）。"""
    key, k, i = _nk(name), 0, 0
    while i < len(text) and k < len(key):
        k += len(_nk(text[i]))
        i += 1
    return text[i:].strip()


def _lines(chars: list[dict], tol: float = 1.6, gap: float = 2.0) -> list[dict]:
    """文字を top の近さで行にまとめる（x順・隙間が gap を超えたら空白を入れる）。
    返り値 [{y(文字の縦中央), text, chars}]"""
    chars = sorted(chars, key=lambda c: c["top"])
    rows, cur, base = [], [], None
    for c in chars:
        if base is None or abs(c["top"] - base) <= tol:
            cur.append(c)
            base = c["top"] if base is None else base
        else:
            rows.append(cur)
            cur, base = [c], c["top"]
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        r.sort(key=lambda c: c["x0"])
        s, prev = "", None
        for c in r:
            if prev is not None and c["x0"] - prev["x1"] > gap:
                s += " "
            s += c["text"]
            prev = c
        out.append(dict(y=sum((c["top"] + c["bottom"]) / 2 for c in r) / len(r), text=s.strip(), chars=r))
    return out


def _in_x(chars: list[dict], x0: float, x1: float) -> list[dict]:
    return [c for c in chars if x0 <= c["x0"] < x1]


def _merged_cell(chars: list[dict], rules: list[float], y: float, x0: float, x1: float, pat: str) -> str | None:
    """結合セル：y を含む罫線の区間の中、x0〜x1 にある行のうち pat に合うものを返す。
    区間の中に複数あれば y に一番近い行（1つのセルに日付が2つ書かれた枠がある＝長野・愛媛）。無ければ None。"""
    lo = max((r for r in rules if r <= y), default=None)
    hi = min((r for r in rules if r > y), default=None)
    if lo is None or hi is None:
        return None
    cs = [c for c in _in_x(chars, x0, x1) if lo < (c["top"] + c["bottom"]) / 2 < hi]
    cand = [ln for ln in _lines(cs) if re.search(pat, ln["text"])]
    return min(cand, key=lambda ln: abs(ln["y"] - y))["text"] if cand else None


def _dedup_chars(page) -> list[dict]:
    """同じ文字が同じ位置に2回描かれているPDF（長野）の重複を落とす。"""
    kept = []
    for c in sorted(page.chars, key=lambda c: (round(c["top"]), c["x0"])):
        if any(k["text"] == c["text"] and abs(k["x0"] - c["x0"]) < 1.2 and abs(k["top"] - c["top"]) < 1.2
               for k in kept[-40:]):
            continue
        kept.append(c)
    return kept


def _date_from(text: str | None, pat: str = r"(\d{1,2})\s*月\s*(\d{1,2})\s*日") -> str | None:
    m = re.search(pat, unicodedata.normalize("NFKC", text or ""))
    return _md_date(int(m.group(1)), int(m.group(2))) if m else None


# ---- 秋田（日程表PDF＝試合の正本・星取表PDF＝検算） --------------------------------
_AK_MARK = r"[〇○●△]"


def read_akita15(cfg: dict) -> tuple[dict, list[dict]]:
    sched_url = _one_link(cfg, lambda t, u: "U-15すぎっちリーグ日程表" in t, "日程表")
    hoshi_url = _one_link(cfg, lambda t, u: "U-15すぎっちリーグ星取表" in t, "星取表")

    with _open(hoshi_url) as pdf:
        rows = pdf_source.page_row_texts(pdf.pages[0], 2.5)
    if not any("（1部）" in r for r in rows[:3]):
        raise ReadError("星取表の1ページ目が1部ではない", rows[:3])
    standings, names = {}, {}
    for r in rows:
        m = re.fullmatch(r"(\d+) (.+?) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (-?\d+) (\d+)", r)
        if not m:
            continue
        name = _clean(m.group(2))
        w, d, l, pts, gf, ga, gd, rank = (int(m.group(i)) for i in range(3, 11))
        if gf - ga != gd or w * 3 + d != pts:
            raise ReadError(f"星取表の行が自己矛盾: {r}")
        standings[name] = dict(pts=pts, played=w + d + l, won=w, drawn=d, lost=l, gf=gf, ga=ga, rank=rank)
        names[_nk(name)] = name
    time.sleep(SLEEP)

    with _open(sched_url) as pdf:
        rows = pdf_source.page_row_texts(pdf.pages[0], 2.5)
    if not any("（1部）" in r for r in rows[:3]):
        raise ReadError("日程表の1ページ目が1部ではない", rows[:3])
    matches, labels = [], []
    for r in rows:
        lab = re.fullmatch(r"第(\d+)節", r)
        if lab:
            labels.append((int(lab.group(1)), len(matches)))
            continue
        m = re.match(r"(\d{1,2})月(\d{1,2})日 (\S+) (.+)$", r)
        if not m or " vs " not in m.group(4):
            continue
        left, right = m.group(4).split(" vs ", 1)
        ls = re.fullmatch(rf"(.+?)(?: {_AK_MARK})? (\d+)", left)       # 勝敗の印は使わない（数字で決める）
        rs = re.match(rf"(\d+)(?: {_AK_MARK})? (.+)$", right)
        if bool(ls) != bool(rs):
            raise ReadError(f"日程表の行でスコアが片側だけ: {r}")
        home = names.get(_nk(ls.group(1) if ls else left))
        tail = _team_prefix(rs.group(2) if rs else right, names)
        if not home or not tail:
            raise ReadError(f"日程表のチーム名が星取表と対応しない: {r}", [f"星取表のチーム: {list(names.values())}"])
        venue = _after_name(rs.group(2) if rs else right, tail[0])
        matches.append(dict(md=0, date=_md_date(int(m.group(1)), int(m.group(2))), home=home, away=tail[0],
                            hs=int(ls.group(2)) if ls else None, **{"as": int(rs.group(1)) if rs else None},
                            venue="" if venue == "未定" else venue))
    # 節：4試合ごとのかたまりの2試合目の後ろに「第N節」が出る。位置が合わなければ読み違い
    n_md = len(matches) // 4
    if len(matches) % 4 or [x[0] for x in labels] != list(range(1, n_md + 1)) \
            or any(pos != 4 * (md - 1) + 2 for md, pos in labels):
        raise ReadError("日程表の節の並びが想定（4試合ずつ・2試合目の後ろに節の見出し）と違う",
                        [f"試合{len(matches)}件・見出し {labels[:6]}"])
    for i, mt in enumerate(matches):
        mt["md"] = i // 4 + 1
    return standings, matches


# ---- 長野（試合結果PDF＝正本・星取表PDF＝勝点だけ照合） ------------------------------
#   ⚠️ どちらのPDFも同じ文字が同じ位置に2回描かれている → _dedup_chars で落としてから読む
#   ⚠️ 日付・会場は結合セル（グループの真ん中あたりに1回だけ）→ 罫線の区間で割り当てる（U-18奈良と同じ型）
_NG_RE = re.compile(r"(\d{1,2}:\d{2}|未定) (.+?) (?:(\d+) - (\d+)|-|(延期)) (.+)")


def read_nagano15(cfg: dict) -> tuple[dict, list[dict]]:
    res_url = _one_link(cfg, lambda t, u: re.search(r"/\d{4}_U15_ken1(-\d+)?\.pdf$", u), "試合結果")
    hoshi_url = _one_link(cfg, lambda t, u: re.search(r"/\d{4}_U15_ken1_hoshi(-\d+)?\.pdf$", u), "星取表")

    # 星取表：見出しの文字の x で列を決める。行見出し（チーム名）は2〜3行に割れるので縦の帯でまとめる
    with _open(hoshi_url) as pdf:
        pg = pdf.pages[0]
        chars = _dedup_chars(pg)
    lines = _lines(chars)
    if not any("１部" in ln["text"] or "1部" in ln["text"] for ln in lines[:3]):
        raise ReadError("星取表の見出しに「1部」が無い", [ln["text"] for ln in lines[:3]])
    head = {}
    words = [w for ln in lines for w in _words(ln["chars"])]
    for w in words:
        if w["text"] in ("勝点", "得点", "失点", "順位") and w["text"] not in head:
            head[w["text"]] = w["x0"]
    if len(head) != 4:
        raise ReadError("星取表の見出し（勝点・得点・失点・順位）が揃わない", [str(head)])
    col = lambda w, h: abs(w["x0"] - head[h]) < 10 and re.fullmatch(r"\d+", w["text"])   # noqa: E731
    top = min(w["top"] for w in words if w["text"] == "勝点")
    prow = sorted((w for w in words if w["top"] > top + 5 and col(w, "勝点")), key=lambda w: w["top"])
    ys = [w["top"] for w in prow]
    standings = {}
    alias = cfg.get("hoshi_aliases") or {}
    for i, pw in enumerate(prow):
        lo = (ys[i - 1] + ys[i]) / 2 if i else ys[i] - 25
        hi = (ys[i] + ys[i + 1]) / 2 if i + 1 < len(ys) else ys[i] + 25
        label = "".join(w["text"] for w in sorted((w for w in words if w["x1"] < 135 and lo <= w["top"] < hi),
                                                   key=lambda w: w["top"]))
        same = lambda h: [w for w in words if col(w, h) and abs(w["top"] - pw["top"]) < 3]   # noqa: E731
        vals = {h: same(h) for h in ("得点", "失点", "順位")}
        if not label or any(len(v) != 1 for v in vals.values()):
            raise ReadError(f"星取表の{i + 1}行目が読めない（{label!r}）")
        standings[alias.get(_nk(label), _nk(label))] = dict(
            pts=int(pw["text"]), gf=int(vals["得点"][0]["text"]), ga=int(vals["失点"][0]["text"]),
            rank=int(vals["順位"][0]["text"]))
    time.sleep(SLEEP)

    with _open(res_url) as pdf:
        pg = pdf.pages[0]
        chars = _dedup_chars(pg)
        date_rules = pdf_source.page_hrules(pg, cfg["x_date"][0] + 2, cfg["x_date"][1] - 3)
        venue_rules = pdf_source.page_hrules(pg, cfg["x_venue"] + 1, cfg["x_venue"] + 7)
    lines = _lines(chars)
    if not any("1部" in _nk(ln["text"]) for ln in lines[:3]):
        raise ReadError("試合結果PDFの見出しに「1部」が無い", [ln["text"] for ln in lines[:3]])
    matches, disp = [], {}
    for ln in lines:
        body = " ".join(ln2["text"] for ln2 in _lines(_in_x(ln["chars"], cfg["x_date"][1], cfg["x_venue"])))
        m = _NG_RE.fullmatch(body)
        if not m:
            continue
        home, away = _clean(m.group(2)), _clean(m.group(6))
        for t in (home, away):
            if disp.setdefault(_nk(t), t) != t:
                raise ReadError(f"同じチームの表記が行ごとに違う: {disp[_nk(t)]!r} / {t!r}")
        date = None if m.group(1) == "未定" and m.group(5) else \
            _date_from(_merged_cell(chars, date_rules, ln["y"], *cfg["x_date"], r"\d+月\d+日"))
        venue = _merged_cell(chars, venue_rules, ln["y"], cfg["x_venue"], 9999, r"\S")
        matches.append(dict(md=len(matches) // cfg["per_md"] + 1, date=date, home=home, away=away,
                            hs=int(m.group(3)) if m.group(3) else None,
                            **{"as": int(m.group(4)) if m.group(4) else None},
                            venue="" if not venue or venue == "未定" else venue))
    # 照合キーを試合結果PDFの表記にそろえる
    by_nk = {_nk(t): t for t in disp.values()}
    if set(standings) != set(by_nk):
        raise ReadError("星取表と試合結果のチーム名が対応しない",
                        [f"星取表だけ {sorted(set(standings) - set(by_nk))}", f"試合結果だけ {sorted(set(by_nk) - set(standings))}"])
    return {by_nk[k]: v for k, v in standings.items()}, matches


def _words(chars: list[dict], gap: float = 2.0) -> list[dict]:
    """1行ぶんの文字を、隙間が gap を超えるところで単語に割る（x0, x1, top, text）。"""
    out = []
    for c in sorted(chars, key=lambda c: c["x0"]):
        if out and c["x0"] - out[-1]["x1"] <= gap and abs(c["top"] - out[-1]["top"]) < 2:
            out[-1]["text"] += c["text"]
            out[-1]["x1"] = c["x1"]
        else:
            out.append(dict(text=c["text"], x0=c["x0"], x1=c["x1"], top=c["top"]))
    for w in out:
        w["text"] = w["text"].strip()
    return [w for w in out if w["text"]]


# ---- 石川（星取表1枚がすべて。座標で読む） ------------------------------------------
#   チーム1行＝1巡目・2巡目の2段。各段は「スコア（○△●つき）」「前半」「後半」「日付」「会場」の5行。
#   段の位置は「日付の行」（M/D が並ぶ行）を錨にして決める。列（対戦相手）は前半・後半の「-」の x で決める。
#   ⚠️ 列見出しは略称・行見出しは2行に割れる → 名前ではなく「行・列とも並び順が同じ」ことで対応させる
def read_ishikawa15(cfg: dict) -> tuple[dict, list[dict], list[str]]:
    url = _one_link(cfg, lambda t, u: "【1部】" in u.rsplit("/", 1)[-1], "1部の星取表")
    with _open(url) as pdf:
        if len(pdf.pages) != 1:
            raise ReadError(f"ページ数が{len(pdf.pages)}（1のはず）")
        pg = pdf.pages[0]
        words = pg.extract_words(x_tolerance=1.5)
    names, n = cfg["names"], cfg["teams"]
    if not any(w["text"] == "１部" for w in words if w["top"] < 80):
        raise ReadError("見出しに「１部」が無い")
    head = {w["text"]: w for w in words if w["text"] in ("勝点", "得点", "失点", "順位") and w["top"] < 80}
    if len(head) != 4:
        raise ReadError("順位表の見出し（勝点・得点・失点・順位）が揃わない", [str(sorted(head))])
    x_grid = head["勝点"]["x0"] - 5                      # ここより右は順位表
    anchors = []
    for w in sorted((w for w in words if re.fullmatch(r"\d{1,2}/\d{1,2}", w["text"]) and 90 < w["x0"] < x_grid),
                    key=lambda w: w["top"]):
        if anchors and abs(w["top"] - anchors[-1]) < 3:
            continue
        anchors.append(w["top"])
    if len(anchors) != 2 * n:
        raise ReadError(f"日付の行が{len(anchors)}本（{2 * n}本のはず）")
    dash = []
    for w in sorted((w for w in words if w["text"] == "-" and 90 < w["x0"] < x_grid), key=lambda w: w["x0"]):
        if not dash or w["x0"] - dash[-1][-1] > 10:
            dash.append([w["x0"]])
        else:
            dash[-1].append(w["x0"])
    cx = [sum(d) / len(d) + 2 for d in dash]              # 列の中心
    if len(cx) != n:
        raise ReadError(f"対戦相手の列が{len(cx)}本（{n}本のはず）")
    half = (cx[1] - cx[0]) / 2

    def cell(y0, y1, j, pat=r"\S+"):
        ws = [w for w in words if y0 <= w["top"] < y1 and abs((w["x0"] + w["x1"]) / 2 - cx[j]) < half
              and re.fullmatch(pat, w["text"])]
        return sorted(ws, key=lambda w: w["x0"])

    grid = {}                  # (行i, 列j, 巡r) -> dict(s=(a,b)|None, date, venue)
    errors = []
    for k, ya in enumerate(anchors):
        i, r = divmod(k, 2)
        for j in range(n):
            sc = [int(w["text"]) for w in cell(ya - 32, ya - 21, j, r"\d+")]
            h1 = [int(w["text"]) for w in cell(ya - 21, ya - 12, j, r"\d+")]
            h2 = [int(w["text"]) for w in cell(ya - 12, ya - 3, j, r"\d+")]
            dt = cell(ya - 3, ya + 3, j, r"\d{1,2}/\d{1,2}")
            vn = " ".join(w["text"] for w in cell(ya + 3, ya + 15, j))
            if j == i:
                if sc or dt:
                    raise ReadError(f"{names[i]} の自分自身の枠に文字がある")
                continue
            if len(sc) not in (0, 2) or len(dt) != 1:
                raise ReadError(f"{names[i]} 対 {names[j]}（{r + 1}巡目）の枠が読めない: スコア{sc} 日付{[w['text'] for w in dt]}")
            if sc and len(h1) == 2 and len(h2) == 2 and (h1[0] + h2[0], h1[1] + h2[1]) != tuple(sc):
                errors.append(f"{names[i]}対{names[j]}（{r + 1}巡目）前半{h1}＋後半{h2}≠{sc}")
            mo, da = dt[0]["text"].split("/")
            grid[(i, j, r)] = dict(s=tuple(sc) if sc else None, date=_md_date(int(mo), int(da)), venue=vn)
    # 石川独自の検算：同じ試合が行（A対B）と列（B対A）の2か所にある → 左右反転で一致すること
    matches = []
    for i in range(n):
        for j in range(i + 1, n):
            for r in range(2):
                a, b = grid[(i, j, r)], grid[(j, i, r)]
                same = (a["s"] is None and b["s"] is None) or (a["s"] and b["s"] and a["s"] == b["s"][::-1])
                if not same or a["date"] != b["date"]:
                    errors.append(f"左右不一致 {names[i]}対{names[j]}（{r + 1}巡目）"
                                  f"{a['s']}・{a['date']} ／ 反対側 {b['s']}・{b['date']}")
                    continue
                matches.append(dict(md=0, date=a["date"], home=names[i], away=names[j],
                                    hs=a["s"][0] if a["s"] else None, **{"as": a["s"][1] if a["s"] else None},
                                    venue=a["venue"]))
    # 順位表（勝点・得点・失点・順位だけ。勝分敗の列は無い）：勝点の列の数字を上から n 行
    col = lambda h: sorted((w for w in words if abs(w["x0"] - head[h]["x0"]) < 10 and w["top"] > head[h]["bottom"]  # noqa: E731
                            and re.fullmatch(r"\d+", w["text"])), key=lambda w: w["top"])
    pts = col("勝点")
    if len(pts) != n:
        raise ReadError(f"順位表の勝点が{len(pts)}行（{n}のはず）")
    standings = {}
    for i, pw in enumerate(pts):
        if not anchors[2 * i] - 45 < pw["top"] < anchors[2 * i + 1]:
            raise ReadError(f"順位表の{i + 1}行目が {names[i]} の段の高さに無い")
        get = lambda h: [int(w["text"]) for w in col(h) if abs(w["top"] - pw["top"]) < 6]   # noqa: E731
        gf, ga, rk = get("得点"), get("失点"), get("順位")
        if len(gf) != 1 or len(ga) != 1 or len(rk) != 1:
            raise ReadError(f"順位表の{i + 1}行目（{names[i]}）が読めない")
        standings[names[i]] = dict(pts=int(pw["text"]), gf=gf[0], ga=ga[0], rank=rk[0])
    return standings, matches, errors


# ---- 愛媛（1ページ目＝前期・2ページ目＝後期。左半分が日程表・右半分が星取表） ------------
#   ⚠️ 同じ高さの行に日程表と星取表の文字が混ざる → x でページを左右に分けてから読む
#   日程表の1試合：ホーム 前半 後半 計 － 計 前半 後半 アウェイ 主審 副審… 「計」の2つがスコア。
#   ⚠️ 主審・副審の欄にもチーム名（審判担当）が入る → アウェイは「チーム名が先頭から一致する」で切る
def read_ehime15(cfg: dict) -> tuple[dict, list[dict], list[str]]:
    url = _one_link(cfg, lambda t, u: t.startswith("Div.1"), "Div.1")
    X = cfg["x"]
    with _open(url) as pdf:
        if len(pdf.pages) != 2:
            raise ReadError(f"ページ数が{len(pdf.pages)}（2のはず）")
        pages = []
        for pg in pdf.pages:
            pages.append(dict(chars=list(pg.chars), words=pg.extract_words(x_tolerance=1.5),
                              blocks=pdf_source.page_hrules(pg, X["home"][0], X["away"][1] - 10),
                              date_rules=pdf_source.page_hrules(pg, X["date"][0] + 6, X["date"][1] - 2),
                              venue_rules=pdf_source.page_hrules(pg, X["venue"][0] + 5, X["venue"][1] - 6)))
    # チーム名：2ページ目の星取表の行見出し（右半分の左端）。年間成績は同じ高さの右端
    p2 = pages[1]
    lab = [ln for ln in _lines(_in_x(p2["chars"], *X["label"]), tol=3) if ln["y"] > 90]
    names = {_nk(ln["text"]): _clean(ln["text"]) for ln in lab}
    if len(names) != cfg["teams"]:
        raise ReadError(f"星取表の行見出しが{len(names)}個（{cfg['teams']}のはず）", [ln["text"] for ln in lab])
    heads = [w for w in p2["words"] if w["x0"] > X["annual"] and w["top"] < 90]
    head = {h: [w for w in heads if w["text"] == h] for h in ("勝ち点", "得点", "失点", "順位")}
    if any(len(v) != 1 for v in head.values()):
        raise ReadError("年間成績の見出し（勝ち点・得点・失点・順位）が揃わない")
    col = lambda h: [w for w in p2["words"] if abs(w["x0"] - head[h][0]["x0"]) < 5 and w["top"] > 90  # noqa: E731
                     and re.fullmatch(r"\d+", w["text"])]
    standings = {}
    for pw in col("勝ち点"):
        row = [ln for ln in lab if abs(ln["y"] - (pw["top"] + pw["bottom"]) / 2) < 10]
        get = lambda h: [int(w["text"]) for w in col(h) if abs(w["top"] - pw["top"]) < 4]   # noqa: E731
        gf, ga, rk = get("得点"), get("失点"), get("順位")
        if len(row) != 1 or len(gf) != 1 or len(ga) != 1 or len(rk) != 1:
            print(f"    （愛媛: 年間成績の {pw['top']:.0f} の行が読めないので照合から外す）")
            continue
        standings[_clean(row[0]["text"])] = dict(pts=int(pw["text"]), gf=gf[0], ga=ga[0], rank=rk[0])

    matches, errors = [], []
    for pi, p in enumerate(pages):
        left = _in_x(p["chars"], 0, X["split"])
        title = " ".join(ln["text"] for ln in _lines(left)[:2])
        if "Div.1" not in title or "日程表" not in title:
            raise ReadError(f"{pi + 1}ページ目の見出しが Div.1 の日程表ではない", [title])
        dashes = sorted((c for c in left if c["text"] == "－" and X["dash"][0] <= c["x0"] < X["dash"][1]),
                        key=lambda c: c["top"])
        blocks = p["blocks"]
        if len(blocks) != cfg["md_per_page"] + 1:
            raise ReadError(f"{pi + 1}ページ目の節の区切りが{len(blocks) - 1}個（{cfg['md_per_page']}のはず）")
        for d in dashes:
            y = (d["top"] + d["bottom"]) / 2
            if y < blocks[0]:
                continue                                      # 見出しの「（40－10－40）」
            row = [c for c in left if abs((c["top"] + c["bottom"]) / 2 - y) < 3]
            home_t = "".join(c["text"] for c in _in_x(row, *X["home"]))
            nums = [w for w in _words(_in_x(row, X["home"][1], X["away"][0])) if w["text"] != "－"]
            away = _team_prefix("".join(c["text"] for c in _in_x(row, *X["away"])), names)
            home = names.get(_nk(home_t))
            if not home or not away:
                raise ReadError(f"{pi + 1}ページ目 y={y:.0f} のチーム名が読めない: {home_t!r}")
            if len(nums) not in (0, 6) or not all(w["text"].isdigit() for w in nums):
                raise ReadError(f"{home} 対 {away[0]} のスコアの欄が読めない: {[w['text'] for w in nums]}")
            v = [int(w["text"]) for w in nums]
            if v and (v[0] + v[1] != v[2] or v[4] + v[5] != v[3]):
                errors.append(f"{home}対{away[0]} 前半＋後半≠計 {v}")
            md = pi * cfg["md_per_page"] + sum(1 for b in blocks if b < y)
            label = _merged_cell(left, blocks, y, *X["md"], r"^\d+$")
            if label and int(label) != md:
                raise ReadError(f"{home}対{away[0]} の節の見出し {label} が位置からの計算 {md} と違う")
            venue = _merged_cell(left, p["venue_rules"], y, *X["venue"], r"\S")
            matches.append(dict(md=md, home=home, away=away[0], hs=v[2] if v else None, **{"as": v[3] if v else None},
                                date=_date_from(_merged_cell(left, p["date_rules"], y, *X["date"], r"月.*日")),
                                venue="" if (venue or "").replace(" ", "") in ("", "未定", "調整中")
                                else venue.replace(" ", "")))
    return standings, matches, errors


READERS = {"gcmodel": read_gcmodel, "kanagawa": read_kanagawa15,
           "sportsonline": read_sportsonline15, "niigata": read_niigata15,
           "akita_pdf": read_akita15, "nagano_pdf": read_nagano15,
           "ishikawa_pdf": read_ishikawa15, "ehime_pdf": read_ehime15}


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


def build(key: str, cfg: dict, standings: dict, matches: list[dict], old: dict | None,
          pre_errors: list[str] | None = None, info: list[str] | None = None) -> dict:
    """検算を通れば書き込むJSONを返す。通らなければ ValueError（理由つき）。
    pre_errors … 読み取り側の検算（石川の左右一致・前半＋後半＝計）の不一致。1件でもあればNG
    info       … ⚪情報（NGにはしない）を書き足すリスト"""
    if pre_errors:
        raise ValueError(f"出典の中の検算が不一致 {len(pre_errors)}件: " + "; ".join(pre_errors[:3])
                         + (" …" if len(pre_errors) > 3 else ""))
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
    check = cfg.get("check_keys") or tuple(next(iter(mine.values())))    # 既定＝全項目
    if standings:
        # 愛媛は年間成績の行が読めないチームを照合から外すことがある＝順位表側は部分集合でよい設定
        if set(standings) != teams and not (cfg["kind"] == "ehime_pdf" and set(standings) <= teams):
            raise ValueError(f"順位表と試合のチーム名が合わない: 順位表だけ {sorted(set(standings) - teams)}"
                             f"／試合だけ {sorted(teams - set(standings))}")
        diff = [f"{t}.{k} 表{standings[t][k]}≠試合{mine[t][k]}"
                for t in sorted(standings) for k in check if standings[t][k] != mine[t][k]]
        if diff:
            raise ValueError("検算不一致 " + "; ".join(diff[:4]) + (" …" if len(diff) > 4 else ""))
        # ⚪情報：照合しない項目の食い違い（長野の星取表の得点・失点）。更新は止めない
        for t in sorted(standings):
            d = [f"{k} 表{standings[t][k]}≠試合{mine[t][k]}" for k in cfg.get("info_keys", ())
                 if standings[t][k] != mine[t][k]]
            if d and info is not None:
                info.append(f"{t}（{'・'.join(d)}）")

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

    own_rank = not standings or cfg.get("rank_from") == "self" or set(standings) != teams
    if not own_rank:
        order = sorted(teams, key=lambda t: (standings[t]["rank"], t))
        rank = {t: standings[t]["rank"] for t in teams}
    else:   # 自前計算：勝点→得失点差→得点（新潟・長野）
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
    elif own_rank:
        out["standings_source"] = "self_pts"      # 出典の順位表とは勝点だけ一致を確かめた自前計算（長野）
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
    ap = argparse.ArgumentParser(description="U-15県リーグ1部を取り込む")
    ap.add_argument("--dry-run", action="store_true", help="取得と検算だけ行い書き込まない")
    ap.add_argument("--only", default="", help="県（tochigi など）をカンマ区切りで指定")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    print(f"=== U-15県1部（{len(PREFS)}県）{'【DRY RUN】' if args.dry_run else ''} ===")
    summary = []
    for key, cfg in PREFS.items():
        if only and key not in only:
            continue
        slug = f"u15-{key}-1"
        path = OUT_DIR / f"{slug}.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        print(f"■ {cfg['prefName']}（{slug}）")
        try:
            standings, matches, *rest = READERS[cfg["kind"]](cfg)
        except Exception as e:          # noqa: BLE001
            print(f"    読めなかった: {e}")
            for d in getattr(e, "diag", []):
                print(f"    [診断] {d}")
            summary.append(f"— {cfg['prefName']}: 取得できず（{_source_url(cfg)}）")
            continue
        finally:
            time.sleep(SLEEP)
        info = []
        try:
            out = build(key, cfg, standings, matches, old, rest[0] if rest else None, info)
        except Exception as e:          # noqa: BLE001
            summary.append(f"⏸ {cfg['prefName']}: 検証NG（{e}）")
            continue
        if info:
            msg = (f"⚪ {cfg['prefName']}: 出典の順位表の {'・'.join(cfg.get('info_keys', ()))} が試合結果からの計算と"
                   f"{len(info)}チームで違う（照合対象外・更新は続ける）: " + "; ".join(info))
            print(f"    {msg}")
            summary.append(msg)
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
