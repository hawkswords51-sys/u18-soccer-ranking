#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
県1部9県を「県サッカー協会 公式」から更新する
==============================================
2026-09-06 新設。

なぜ作ったか
------------
県1部のこれまでの出典 junior-soccer.jp は **GitHub Actions から403で弾かれる**ように
なり（Cloudflareが送信元IPで遮断）、2026-07-15以降ずっと自動更新が止まっていた。
調べたところ **9県は県協会の公式システムにデータがあり、定形URLの素のHTMLで取れる**。

移行して得られるもの:
  1. 自動更新に戻せる（junior-soccerではないドメインなので403にならない）
  2. 出典の格が上がる（junior-soccer は自ら「公式結果ではありません」と明記するファン投稿型）
  3. 誤りが消える。実例＝愛知は9/5「日福大付 1-0 名古屋」が誤りで公式は 1-2 名古屋の勝ち。
     岩手は同じ試合が2行重複していて順位表も二重計上されていた（29pt/13試合 → 公式26pt/12試合）
  4. 佐賀が初めて自動で取れるようになる（これまで唯一データ源が無かった県）

データ源は2系統
---------------
  GoalNote (6県) https://www.goalnote.net/detail-standings.php?tid={tid}
                 https://www.goalnote.net/detail-schedule.php?tid={tid}
  tecra    (3県) https://{host}/order/1/{season}/all   （順位表）
                 https://{host}/match/1/{season}/all   （試合結果）
                 ※ 2026-09-06に3ドメイン×パスを実測。`/all` の有無で結果は変わらない

安全設計（update_pref_cross_tables.py と同じ思想）
--------------------------------------------------
  1. 公式のチーム名を既存JSONのチーム名へ名寄せし、**1対1（全単射）が取れた県だけ**処理する
  2. 試合一覧から再計算した順位が、公式の順位表と**全項目一致**したときだけ書き込む
  3. 公式の消化試合数が既存より少なければ**据え置き**（退行防止）
  4. どれかに落ちたらそのファイルは1バイトも書かず、理由をログに出す

使い方
------
  python scraper/fetch_pref_official.py             # 取得して書き込む
  python scraper/fetch_pref_official.py --dry-run   # 書き込まず、既存との差分だけ出す
  python scraper/fetch_pref_official.py --only aichi,saga
"""
import argparse
import collections
import json
import re
import sys
import time
import unicodedata
from datetime import date as _date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 既存の県1部スクリプトから、名寄せ・検算・JSON組み立てをそのまま流用する。
# 同じ関数を使うことで、出力スキーマと検算の厳しさが junior-soccer 版と完全に揃う。
from update_pref_cross_tables import (  # noqa: E402
    SEASON_YEAR, build_from_source, norm,
)

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "league_matches"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36")
}
TIMEOUT = 25
RETRIES = 3
SLEEP = 1.5      # 相手のサーバに優しく（1リクエストごとに待つ）

# ----------------------------------------------------------------------------
# 対象9県
#   goalnote … tid を差し替えるだけ
#   tecra    … 県ごとに独自ドメイン
# ⚠️ 鳥取は「1部リーグ前期」でtidが分かれている。後期が始まったらtidの追加が要る。
#    年度が変わったら全tidを新年度のものに差し替えること（年度切り替えチェックリスト参照）。
# ----------------------------------------------------------------------------
PREF_OFFICIAL = {
    "chiba":    {"platform": "goalnote", "tid": "18441", "label": "千葉県サッカー協会 公式（GoalNote）"},
    "aichi":    {"platform": "goalnote", "tid": "18269", "label": "愛知県サッカー協会 公式（GoalNote）"},
    "iwate":    {"platform": "goalnote", "tid": "18702", "label": "岩手県サッカー協会 公式（GoalNote）"},
    "nagasaki": {"platform": "goalnote", "tid": "18526", "label": "長崎県サッカー協会 公式（GoalNote）"},
    # 鳥取は前期(18541・8チーム1回戦総当たり・7/24完了)と後期(19293・上位4/下位4の
    # グループ分け・9/5開幕)が**別大会として登録**されている。試合は両方から集め、
    # 順位表は後期のもの（＝通年通算になっている）を使う。
    # 後期はグループ分けなので総当たり枠を作らない（round_robin: False）。
    "tottori":  {"platform": "goalnote", "tid": "19293", "extra_tids": ["18541"],
                 "standings_from": "19293", "round_robin": False,
                 "label": "鳥取県サッカー協会 公式（GoalNote）"},
    "kagawa":   {"platform": "goalnote", "tid": "18633", "label": "香川県サッカー協会 公式（GoalNote）"},
    "yamagata": {"platform": "goalnote", "tid": "18649", "label": "山形県サッカー協会 公式（GoalNote）"},
    "ibaraki":  {"platform": "goalnote", "tid": "18463", "label": "茨城県サッカー協会 公式（GoalNote）"},
    "shiga":    {"platform": "tecra", "host": "shiga-fa-u18.com", "label": "滋賀県サッカー協会 公式"},
    "fukuoka":  {"platform": "tecra", "host": "fukuoka-fa-u18.com", "label": "福岡県サッカー協会 公式"},
    "saga":     {"platform": "tecra", "host": "saga-fa-u18.com", "label": "佐賀県サッカー協会 公式"},

    # ここから下は県ごとの独自システム。共通プラットフォームではないので
    # パース仕様・検算ゲート・節番号の有無がそれぞれ違う（2026-09-07追加）。
    "gunma":     {"platform": "gunma", "tid": "173",
                  "source": "https://gunma-fa.com/post-694/",
                  "label": "群馬県サッカー協会 公式"},
    "miyazaki":  {"platform": "miyazaki",
                  "url": f"https://miyazaki-fa-u18.net/schedule/{SEASON_YEAR}/U-18-1.htm",
                  "source": f"https://miyazaki-fa-u18.net/schedule/{SEASON_YEAR}/U-18-1.htm",
                  "label": "宮崎県サッカー協会 公式（U-18リーグ）",
                  # 公式順位表が画像PDFなので、順位表との突き合わせができない。
                  # 代わりに self_check ゲート（process内）で守る。
                  "standings_gate": "self"},
    "yamaguchi": {"platform": "yamaguchi",
                  "url": ("https://www.sportsonline.jp/reportv2/PublisherFull/"
                          "viewdata.aspx?parentid=RX%5eS%5d&rallyid=U%5eZ%5b%5b"),
                  "source": "https://yamaguchi-fa.com/archives/16620",
                  "label": "山口県サッカー協会 公式（SportsOnline）",
                  # 出典に実日付が無い。既存JSONの同じ対戦から date を引き継ぐ。
                  "inherit_dates": True},
}

# norm() で寄らない表記だけを手で書く。
# ⚠️ norm() が吸収するもの（セカンド→2nd、B→2nd、高校の除去 等）は**書かないこと**。
#    不要なエイリアスは将来の誤対応の種になる。
PREF_ALIAS = {
    # 2026-09-06に9県ぶんを実測し、norm() で寄らなかった7件だけを登録した。
    # いずれも「既存で余っているチームが1つだけ」の状態で対応先が確定している。
    "aichi": {
        "名古屋グランパスB": "グランパスB",
        "日本福祉大学付属": "日福大付",
    },
    "iwate": {
        "G盛岡ユース": "グルージャ",      # グルージャ盛岡ユース
        "盛大附": "盛岡大附",             # 盛岡大学附属
    },
    "nagasaki": {
        "長崎総大附B": "長崎総附2nd",     # 長崎総合科学大学附属のセカンド
    },
    "kagawa": {
        "四国学院大学香川西高等学校": "香川西",
    },
    "fukuoka": {
        # norm() は「U-18 B」の空白のせいで末尾のBを2ndと解釈できない
        "アビスパ福岡U-18 B": "アビスパ福岡B",
    },
    # 群馬は10チームすべて公式表記＝既存JSONの表記なのでALIAS不要
    "miyazaki": {
        "宮崎日本大学": "宮崎日大",
        "テゲバジャーロ宮崎U-18": "テゲバジャーロ",
        "ヴェロスクロノス都農U-18": "ヴェロスクロノス",
    },
    "yamaguchi": {
        "小野田工": "小野田工業",
        "宇部工": "宇部工業",
    },
}

_SCORE_RE = re.compile(r"(\d+)\s*[-ー－―]\s*(\d+)")
_GN_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
_TECRA_DATE_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


# ============================================================
# 取得
# ============================================================
def fetch_html(url: str, encoding: str | None = None) -> str:
    """HTMLを取得する。encoding を渡すとその文字コードで読む
    （出典が Content-Type に charset を書いていない場合に使う）。"""
    last = None
    for _ in range(RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = encoding or resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as e:
            last = e
            time.sleep(SLEEP)
    raise RuntimeError(f"{url} の取得に失敗 ({last})")


def _rows(table) -> list[list[str]]:
    return [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            for tr in table.find_all("tr")]


def _to_int(v):
    s = unicodedata.normalize("NFKC", str(v)).strip().lstrip("+")
    return int(s) if re.fullmatch(r"-?\d+", s) else None


# ============================================================
# GoalNote
#   順位表: 1行目がヘッダ（先頭セルは大会名）。以降 [順位, チーム名, 勝点, 試合数,
#           勝利, 引分, 敗戦, 得点, 失点, 得失差]
#   日程  : 節ごとにテーブルが分かれる。試合行は
#           [番号, YYYY/MM/DD, HH:MM, ホーム, "1-2 [試合終了]", アウェイ, 会場, 詳細]
#           未消化の行は [試合終了] を持たない
# ============================================================
def read_goalnote_all(cfg: dict) -> tuple[dict, list[dict]]:
    """1県ぶんを読む。extra_tids があれば試合を合算する。

    鳥取のように**前期と後期が別大会として登録**されている県がある。
    その場合は試合を両方から集め、順位表は "standings_from" で指定した
    大会（後期＝通年通算）のものだけを使う。
    """
    main_tid = cfg["tid"]
    st_tid = cfg.get("standings_from", main_tid)
    standings, matches = {}, []
    for tid in [main_tid] + list(cfg.get("extra_tids") or []):
        st, ms = read_goalnote({"tid": tid})
        matches += ms
        if tid == st_tid:
            standings = st
    return standings, matches


def read_goalnote(cfg: dict) -> tuple[dict, list[dict]]:
    tid = cfg["tid"]
    soup = BeautifulSoup(
        fetch_html(f"https://www.goalnote.net/detail-standings.php?tid={tid}"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    for table in soup.find_all("table"):
        rows = _rows(table)
        if not rows:
            continue
        head = rows[0]
        if "勝点" not in "".join(head):
            continue
        col = {}
        for i, c in enumerate(head):
            for key, names in (("pts", ("勝点",)), ("played", ("試合数",)),
                               ("won", ("勝利", "勝数")), ("drawn", ("引分",)),
                               ("lost", ("敗戦", "敗数")), ("gf", ("得点",)),
                               ("ga", ("失点",))):
                if key not in col and any(n in c for n in names):
                    col[key] = i
        if len(col) < 7:
            continue
        # ⚠️ GoalNoteのヘッダ行は先頭セルが大会名で、本文の「順位」「チーム名」2列ぶんを
        #    1セルで占める。そのため本文はヘッダより1列多く、列位置が右へずれる。
        #    ずれ幅は行の長さの差から求める（決め打ちにしない）。
        body = [r for r in rows[1:] if len(r) > len(head)]
        offset = (len(body[0]) - len(head)) if body else 0
        for r in rows[1:]:
            if len(r) <= max(col.values()) + offset:
                continue
            team = r[1].strip() if offset else r[0].strip()
            vals = {k: _to_int(r[i + offset]) for k, i in col.items()}
            if team and all(v is not None for v in vals.values()):
                standings[team] = vals
        # ⚠️ ここで break しない。鳥取の後期リーグのように**グループA・Bで表が分かれる**
        #    大会があり、最初の表だけ読むと片方のグループしか取れない（実測で確認）。
        #    見つかった順位表をすべて合算して1つのロスターとして扱う。

    soup2 = BeautifulSoup(
        fetch_html(f"https://www.goalnote.net/detail-schedule.php?tid={tid}"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    for table in soup2.find_all("table"):
        for r in _rows(table):
            if len(r) < 6:
                continue
            joined = " ".join(r)
            if "試合終了" not in joined:
                continue      # 未消化の行はスコアが確定していないので取らない
            dm = _GN_DATE_RE.search(joined)
            if not dm:
                continue
            # スコアと前後のチーム名を位置で拾う
            si = next((i for i, c in enumerate(r) if "試合終了" in c), None)
            if si is None or si < 1 or si + 1 >= len(r):
                continue
            sm = _SCORE_RE.search(unicodedata.normalize("NFKC", r[si]))
            if not sm:
                continue
            home, away = r[si - 1].strip(), r[si + 1].strip()
            if not home or not away:
                continue
            matches.append(dict(
                date=f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}",
                home=home, hs=int(sm.group(1)), **{"as": int(sm.group(2))}, away=away))
    return standings, matches


# ============================================================
# tecra（{県}-fa-u18.com）
#   順位表: [順位, チーム名, 勝点, 試合数, 勝数, 引分(数), 敗数, 得点, 失点, 得失点差(, FPP)]
#           ※ 滋賀だけ末尾に FPP 列がある → 列名で位置を決める
#   試合  : [MM/DD（曜）, ホーム, "2 - 3 試合終了", アウェイ, 会場]
#           年が入っていないので SEASON_YEAR から補う（1月は翌年＝県リーグは年をまたぐ）
# ============================================================
def read_tecra(cfg: dict) -> tuple[dict, list[dict]]:
    host = cfg["host"]
    soup = BeautifulSoup(
        fetch_html(f"https://{host}/order/1/{SEASON_YEAR}/all"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    for table in soup.find_all("table"):
        rows = _rows(table)
        if not rows or "勝点" not in "".join(rows[0]):
            continue
        head = rows[0]
        col = {}
        for i, c in enumerate(head):
            for key, names in (("pts", ("勝点",)), ("played", ("試合数",)),
                               ("won", ("勝数", "勝利")), ("drawn", ("引分",)),
                               ("lost", ("敗数", "敗戦")), ("gf", ("得点",)),
                               ("ga", ("失点",))):
                if key not in col and any(n in c for n in names):
                    col[key] = i
        if len(col) < 7:
            continue
        for r in rows[1:]:
            if len(r) <= max(col.values()):
                continue
            team = r[1].strip()
            vals = {k: _to_int(r[i]) for k, i in col.items()}
            if team and all(v is not None for v in vals.values()):
                standings[team] = vals
        if standings:
            break

    soup2 = BeautifulSoup(
        fetch_html(f"https://{host}/match/1/{SEASON_YEAR}/all"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    for table in soup2.find_all("table"):
        for r in _rows(table):
            if len(r) < 4 or "試合終了" not in " ".join(r):
                continue
            si = next((i for i, c in enumerate(r) if "試合終了" in c), None)
            if si is None or si < 1 or si + 1 >= len(r):
                continue
            sm = _SCORE_RE.search(unicodedata.normalize("NFKC", r[si]))
            if not sm:
                continue
            dm = _TECRA_DATE_RE.search(unicodedata.normalize("NFKC", r[0]))
            if not dm:
                continue
            mo, da = int(dm.group(1)), int(dm.group(2))
            # 既存 update_pref_cross_tables.py と同じ規則。県リーグは年をまたぐので、
            # 1月の試合だけ翌年になる（2月以降＝今シーズンの年）。
            yr = SEASON_YEAR if mo >= 2 else SEASON_YEAR + 1
            home, away = r[si - 1].strip(), r[si + 1].strip()
            if not home or not away:
                continue
            matches.append(dict(date=f"{yr}-{mo:02d}-{da:02d}", home=home,
                                hs=int(sm.group(1)), **{"as": int(sm.group(2))},
                                away=away))
    return standings, matches


# ============================================================
# 群馬（management.gunma-fa.com）— 県協会の独自リーグ管理システム
#   順位表 /api/table/{tid} … <h2>1部リーグ</h2> のセクションの2つ目のtable
#                             列: 順位|チーム名|勝点|試合数|勝数|引分数|敗数|得点|失点|得失点差
#   試合   /api/match/{tid} … 同セクションのtable（91行＝ヘッダ1＋全90試合）
#                             1行6セル: 節|キックオフ|HOME|スコア/状況|AWAY|会場
# ⚠️ スコアは必ず `.point .pt` の1つ目と2つ目を取る。セルのテキスト全体から数字を拾うと
#    前後半スコア（"0 0-2 0-1 3"）を巻き込んで壊れる。
# ⚠️ セクションは id で決め打ちしない。h2 のテキストが厳密に「1部リーグ」の要素から辿る。
# ⚠️ 1〜3部が1ページに入っているので、必ず1部だけ抜き出してから処理する。
# 年度切り替え: https://gunma-fa.com/post-694/ から新年度の大会IDを取る（2026=173）
# ============================================================
_GUNMA_MD_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


def _gunma_section(html: str, heading: str = "1部リーグ"):
    """h2 が厳密に heading のセクション（tableを含む親）を返す"""
    soup = BeautifulSoup(html, "html.parser")
    for h2 in soup.find_all("h2"):
        if h2.get_text(strip=True) != heading:
            continue
        sec = h2.find_parent(["section", "div"])
        while sec is not None and not sec.find_all("table"):
            sec = sec.find_parent(["section", "div"])
        if sec is not None:
            return sec
    return None


def read_gunma(cfg: dict) -> tuple[dict, list[dict]]:
    tid = cfg["tid"]
    base = "https://management.gunma-fa.com/api"

    # --- 順位表 ---
    sec = _gunma_section(fetch_html(f"{base}/table/{tid}"))
    time.sleep(SLEEP)
    standings = {}
    if sec is not None:
        tables = sec.find_all("table")
        # 1つ目は星取表、2つ目が順位表
        for table in tables[1:]:
            rows = _rows(table)
            if not rows or "勝点" not in "".join(rows[0]):
                continue
            col = {}
            for i, c in enumerate(rows[0]):
                for key, names in (("pts", ("勝点",)), ("played", ("試合数",)),
                                   ("won", ("勝数",)), ("drawn", ("引分",)),
                                   ("lost", ("敗数",)), ("gf", ("得点",)),
                                   ("ga", ("失点",))):
                    if key not in col and any(n in c for n in names):
                        col[key] = i
            if len(col) < 7:
                continue
            for r in rows[1:]:
                if len(r) <= max(col.values()):
                    continue
                team = r[1].strip()
                vals = {k: _to_int(r[i]) for k, i in col.items()}
                if team and all(v is not None for v in vals.values()):
                    standings[team] = vals
            if standings:
                break
        m = re.search(r"最終更新日[:：]\s*([\d\-]+\s[\d:]+)",
                      sec.get_text(" ", strip=True))
        if m:
            print(f"       （群馬 出典の最終更新日: {m.group(1)}）")

    # --- 試合 ---
    sec2 = _gunma_section(fetch_html(f"{base}/match/{tid}"))
    time.sleep(SLEEP)
    matches = []
    if sec2 is not None:
        for tr in sec2.find_all("table")[0].find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) < 6:
                continue
            status = cells[3].get_text(" ", strip=True)
            if "試合終了" not in status:
                continue          # 未消化。枠は generate_fixtures 側が作る
            pts = cells[3].select(".point .pt")
            if len(pts) < 2:
                continue
            hs, as_ = _to_int(pts[0].get_text(strip=True)), _to_int(pts[1].get_text(strip=True))
            if hs is None or as_ is None:
                continue
            home = cells[2].get_text(" ", strip=True)
            away = cells[4].get_text(" ", strip=True)
            if not home or not away:
                continue
            dm = _GUNMA_MD_RE.search(cells[1].get_text(" ", strip=True))
            date = ""
            if dm:
                mo, da = int(dm.group(1)), int(dm.group(2))
                # 大会期間は 2026-03-07〜2026-12-05。年をまたがないので SEASON_YEAR 固定。
                date = f"{SEASON_YEAR}-{mo:02d}-{da:02d}"
            matches.append(dict(date=date, home=home, hs=hs,
                                **{"as": as_}, away=away))
    return standings, matches


# ============================================================
# 宮崎（miyazaki-fa-u18.net）— 県協会のU-18リーグ専用サイト
#   /schedule/{年}/U-18-1.htm の3つ目のtable（93行）。先頭3行は見出し。
#   9セル … 節|期日|会場|KickOff|HOME|HOME得点|－|AWAY得点|AWAY
#   8セル … 節が省略（セル結合）。直前の節を引き継ぐ
# ⚠️ 指示書には Shift_JIS とあるが、実物は UTF-8（HTML内の宣言も charset=UTF-8）。
#    shift_jis を明示するとデコードに失敗する（2026-09-07 実測）。
# ⚠️ 全角数字が混在するので NFKC で正規化してから数値化する。
# ⚠️ 公式の順位表は画像PDFで機械可読でないため、順位表は取得せず自前計算する
#    （検算は別ゲート。process() 側を参照）
# 年度切り替え: URLの年を差し替える
# ============================================================
_MIYAZAKI_DATE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")
_MIYAZAKI_MD_RE = re.compile(r"第(\d+)節")


def read_miyazaki(cfg: dict) -> tuple[dict, list[dict]]:
    html = fetch_html(cfg["url"], encoding="utf-8")
    time.sleep(SLEEP)
    tables = BeautifulSoup(html, "html.parser").find_all("table")
    if len(tables) < 3:
        return {}, []
    matches = []
    md = 0
    for r in _rows(tables[2]):
        z = [unicodedata.normalize("NFKC", c) for c in r]
        if len(z) == 9:
            mm = _MIYAZAKI_MD_RE.search(z[0])
            if mm:
                md = int(mm.group(1))
            z = z[1:]              # 以降は8セルと同じ並びにそろえる
        if len(z) != 8:
            continue
        date_raw, _venue, _ko, home, hs, _dash, as_, away = z
        home, away = home.strip(), away.strip()
        if not home or not away:
            continue
        # 得点が空＝未消化。宮崎は出典が第18節まで節番号を持っているので、
        # 未消化の行も hs/as を None のまま返して**節番号だけ**を活かす。
        # ⚠️ 未消化行を検算に流すと壊れる（build_from_source は渡された試合を
        #    全部「消化済み」として順位を再計算するため）。呼び出し側で
        #    「消化ぶんだけ検算に渡す → 枠が組み上がってから節番号を入れる」順序にしている。
        # 参考: 同じ節に消化と未消化が混在することがある。
        #   第12節 … 延期2件が未消化のまま残っている
        #   第14節 … 8/30に1試合だけ前倒し実施、残り4試合は9/19（延期ではない）
        hs, as_ = _to_int(hs), _to_int(as_)
        dm = _MIYAZAKI_DATE_RE.search(date_raw)
        # 1部は4/4〜11/29で年をまたがない。
        # 日付が読めない行（`月日（）＋延期` の第12節2件）は空のまま。
        date = (f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
                if dm else "")
        matches.append(dict(date=date, home=home, hs=hs,
                            **{"as": as_}, away=away, md=md))
    return {}, matches            # 順位表は公式に機械可読なものが無い


# ============================================================
# 山口（sportsonline.jp）— 県協会が公式に案内する速報システム
#   viewdata.aspx 1ページに 星取表＋順位表 と 全試合一覧 が入っている（GET1本）
# ⚠️ 順位表のHTMLが不正で、2行目以降の <tr> が欠落している（td が1つの tr に
#    ぶら下がる）。行では読めないので、**ヘッダの列数で区切って行を復元**する
#    （2026-09-07 実測。td 153個 ÷ 17列 = 9行）。
# ⚠️ 全試合の 開始日 が `2026/04/04` のダミー、開始時刻は空、会場は「県内各地」。
#    出典に実日付が存在しないので **date は空で入れ、既存JSONの同じ対戦から引き継ぐ**
#    （process() 側で処理）。ダミー日付は絶対に採用しない。
#    → 山口の lastUpdated は「出典を確認した日」であって試合日ではない。
# 年度切り替え: SportsOnline の子大会一覧から新しい rallyid を取る
# ============================================================
_YAMAGUCHI_SCORE_RE = re.compile(r"^(.+?)\s+(\d+)\s*[-ー－―]\s*(\d+)\s+(.+?)$")


def read_yamaguchi(cfg: dict) -> tuple[dict, list[dict]]:
    soup = BeautifulSoup(fetch_html(cfg["url"]), "html.parser")
    time.sleep(SLEEP)
    tables = soup.find_all("table")

    # --- 順位表（壊れたHTMLを列数で復元する） ---
    standings = {}
    for table in tables:
        cells = [c.get_text(" ", strip=True) for c in table.find_all("td")]
        if not cells or "勝点" not in "".join(cells[:40]):
            continue
        # ヘッダは「順位 … 勝数 負数 引分 勝点 得点 失点 得失差」で終わる。
        # 「得失差」までをヘッダ幅とみなす（列数を決め打ちしない）。
        try:
            width = cells.index("得失差") + 1
        except ValueError:
            continue
        head = cells[:width]
        col = {}
        for i, c in enumerate(head):
            for key, names in (("pts", ("勝点",)), ("won", ("勝数",)),
                               ("drawn", ("引分",)), ("lost", ("負数",)),
                               ("gf", ("得点",)), ("ga", ("失点",))):
                if key not in col and c == names[0]:
                    col[key] = i
        if len(col) < 6:
            continue
        for i in range(width, len(cells) - width + 1, width):
            row = cells[i:i + width]
            if len(row) < width:
                break
            team = row[1].strip()
            vals = {k: _to_int(row[j]) for k, j in col.items()}
            if team and all(v is not None for v in vals.values()):
                vals["played"] = vals["won"] + vals["drawn"] + vals["lost"]
                standings[team] = vals
        if standings:
            break

    # --- 全試合一覧 ---
    matches = []
    for table in tables:
        rows = _rows(table)
        if not rows or "組み合わせ" not in "".join(rows[0]):
            continue
        for r in rows[1:]:
            if len(r) < 4:
                continue          # 「Away」の区切り行など
            if "試合終了" not in r[3]:
                continue
            m = _YAMAGUCHI_SCORE_RE.match(unicodedata.normalize("NFKC", r[0]).strip())
            if not m:
                continue
            # date は入れない（出典のダミー日付は採用しない）
            matches.append(dict(date="", home=m.group(1).strip(),
                                hs=int(m.group(2)), **{"as": int(m.group(3))},
                                away=m.group(4).strip()))
        if matches:
            break
    return standings, matches


# ============================================================
# 名寄せ（公式表記 → 既存JSONのチーム名）
# ============================================================
def build_name_map(official_names, site_names, pref) -> tuple[dict, list]:
    """1対1（全単射）が取れたら (対応表, []) を、取れなければ (部分表, 未対応リスト) を返す。"""
    alias = PREF_ALIAS.get(pref, {})
    by_norm = {}
    for n in site_names:
        by_norm.setdefault(norm(n), n)
    name_map, unknown = {}, []
    for o in sorted(official_names):
        if o in alias:
            name_map[o] = alias[o]
            continue
        hit = by_norm.get(norm(o))
        if hit:
            name_map[o] = hit
        else:
            unknown.append(o)
    return name_map, unknown


# ============================================================
# 宮崎専用の検算ゲート（2026-09-07新設）
# ------------------------------------------------------------
# 宮崎の公式順位表は**画像PDFしか無く機械では読めない**ので、
# 「試合から再計算した順位＝公式順位表」という通常の検算ができない。
# 代わりに次の5つを全部通ったときだけ書き込む。
#   1. チーム数が既存JSONと同じ
#   2. 各チームの試合数の合計 ＝ 消化試合数 × 2
#   3. 勝点 ＝ 勝×3 ＋ 分（全チーム）
#   4. 消化試合数が既存より減っていない（退行防止・呼び出し側で確認）
#   5. 既存JSONと重なる試合のスコアが全部一致する
#      ※初回は既知の差分（公式にだけある2試合）があるので、
#        「既存にあって公式に無い試合がゼロ」であることを確認する
# ============================================================
def self_check_gate(existing: dict, standings: dict, matches: list[dict],
                    site_names: list[str]) -> list[str]:
    """通れば空リスト、落ちたら理由のリストを返す"""
    ng = []
    if len(standings) != len(site_names):
        ng.append(f"チーム数 {len(standings)} が既存の {len(site_names)} と違う")
    total = sum(v["played"] for v in standings.values())
    if total != len(matches) * 2:
        ng.append(f"試合数の合計 {total} ≠ 消化 {len(matches)} × 2")
    for t, v in standings.items():
        if v["pts"] != v["won"] * 3 + v["drawn"]:
            ng.append(f"{t}: 勝点{v['pts']} ≠ 勝×3+分")
        if v["played"] != v["won"] + v["drawn"] + v["lost"]:
            ng.append(f"{t}: 試合数{v['played']} ≠ 勝分敗の合計")

    # 既存にあって公式に無い試合（＝公式が取りこぼしている）が無いこと。
    # ⚠️ 出典の「左右」はホーム/アウェイとは限らないので、**向きを問わない**キーで
    #    照合する。向きだけ違う同じ試合を「消えた試合」と誤判定すると、
    #    正常な移行が止まってしまう（2026-09-07 宮崎で実際に4件誤検出した）。
    def key(m):
        h, a, hs, as_ = m.get("home"), m.get("away"), m.get("hs"), m.get("as")
        if h > a:                       # 並びを正規化して向きの違いを吸収する
            h, a, hs, as_ = a, h, as_, hs
        return (h, a, hs, as_)

    new_keys = collections.Counter(key(m) for m in matches)
    missing = []
    for m in existing.get("matches", []):
        if m.get("status") != "played" or m.get("hs") is None:
            continue
        k = key(m)
        if new_keys.get(k):
            new_keys[k] -= 1
        else:
            missing.append(m)
    if missing:
        ng.append(f"既存にあって公式に無い試合が{len(missing)}件"
                  f"（例: {missing[0].get('home')} {missing[0].get('hs')}-"
                  f"{missing[0].get('as')} {missing[0].get('away')}）")
    return ng


def standings_from_matches(matches: list[dict], teams: list[str]) -> dict:
    """試合一覧から順位表を自前計算する（公式順位表が機械可読でない県用）"""
    st = {t: dict(pts=0, played=0, won=0, drawn=0, lost=0, gf=0, ga=0) for t in teams}
    for m in matches:
        h, a, hs, as_ = m["home"], m["away"], m["hs"], m["as"]
        if h not in st or a not in st:
            continue
        for t, gf, ga in ((h, hs, as_), (a, as_, hs)):
            v = st[t]
            v["played"] += 1
            v["gf"] += gf
            v["ga"] += ga
            if gf > ga:
                v["won"] += 1
                v["pts"] += 3
            elif gf == ga:
                v["drawn"] += 1
                v["pts"] += 1
            else:
                v["lost"] += 1
    return st


# ============================================================
# 既存データとの差分（何が直ったかの記録用）
# ============================================================
def diff_against_existing(existing: dict, new_matches: list[dict]) -> dict:
    """既存JSON（junior-soccer由来）と、公式から作った試合一覧を突き合わせる。

    突き合わせは段階的に行う。いきなり「ホーム＋アウェイ」で対応づけると、
    香川・佐賀のように**同じ組み合わせで2回対戦する**リーグで取り違える。
      1. ホーム＋アウェイ＋日付が一致  … 同じ試合。スコアが違えば「結果が違う」
      2. 残りをホーム＋アウェイで一致  … 「日付ズレ」（スコアも違えば結果も併記）
      3. 残りを{2チーム}＋日付で一致   … 「ホーム/アウェイが逆」
      4. それでも残ったもの            … 公式にだけ有／旧にだけ有
    """
    def played(ms):
        return [m for m in ms
                if m.get("status") == "played" and m.get("hs") is not None]

    old = played(existing.get("matches", []))
    new = played(new_matches)
    old_n, new_n = len(old), len(new)

    def take(pool, keyfn):
        d = {}
        for m in pool:
            d.setdefault(keyfn(m), []).append(m)
        return d

    score_diff, date_diff, swapped = [], [], []

    # 1. ホーム＋アウェイ＋日付
    idx = take(old, lambda m: (m.get("home"), m.get("away"), m.get("date")))
    rest_new = []
    for nm in new:
        k = (nm.get("home"), nm.get("away"), nm.get("date"))
        if idx.get(k):
            om = idx[k].pop(0)
            if (om.get("hs"), om.get("as")) != (nm.get("hs"), nm.get("as")):
                score_diff.append((om, nm))
        else:
            rest_new.append(nm)
    rest_old = [m for v in idx.values() for m in v]

    # 2. ホーム＋アウェイ（日付だけ違う）
    idx2 = take(rest_old, lambda m: (m.get("home"), m.get("away")))
    rest_new2 = []
    for nm in rest_new:
        k = (nm.get("home"), nm.get("away"))
        if idx2.get(k):
            om = idx2[k].pop(0)
            date_diff.append((om, nm))
        else:
            rest_new2.append(nm)
    rest_old2 = [m for v in idx2.values() for m in v]

    # 3. ホーム/アウェイが逆（日付が同じ）
    idx3 = take(rest_old2, lambda m: (frozenset((m.get("home"), m.get("away"))),
                                      m.get("date")))
    added = []
    for nm in rest_new2:
        k = (frozenset((nm.get("home"), nm.get("away"))), nm.get("date"))
        if idx3.get(k):
            swapped.append((idx3[k].pop(0), nm))
        else:
            added.append(nm)
    removed = [m for v in idx3.values() for m in v]

    return {"oldPlayed": old_n, "newPlayed": new_n,
            "score": score_diff, "date": date_diff, "swapped": swapped,
            "added": added, "removed": removed}


def _fmt(m):
    return f"{m.get('date','')} {m.get('home')} {m.get('hs')}-{m.get('as')} {m.get('away')}"


def print_diff(pref: str, d: dict) -> None:
    n = (len(d["score"]) + len(d["date"]) + len(d["swapped"])
         + len(d["added"]) + len(d["removed"]))
    delta = d["newPlayed"] - d["oldPlayed"]
    print(f"  \u2500\u2500 {pref}: 消化 {d['oldPlayed']} \u2192 {d['newPlayed']} "
          f"({delta:+d})\u3000差分 {n} 件")
    for om, nm in d["score"]:
        print(f"       \u2605結果が違う  旧 {_fmt(om)}  \u2192  公式 {_fmt(nm)}")
    for om, nm in d["date"]:
        extra = ("" if (om.get("hs"), om.get("as")) == (nm.get("hs"), nm.get("as"))
                 else f"（スコアも {om.get('hs')}-{om.get('as')} \u2192 "
                      f"{nm.get('hs')}-{nm.get('as')}）")
        print(f"       日付ズレ     旧 {om.get('date')} \u2192 公式 {nm.get('date')}"
              f"  {nm.get('home')} vs {nm.get('away')}{extra}")
    for om, nm in d["swapped"]:
        print(f"       ホーム逆     旧 {_fmt(om)}  \u2192  公式 {_fmt(nm)}")
    for m in d["added"]:
        print(f"       公式にだけ有 {_fmt(m)}")
    for m in d["removed"]:
        print(f"       旧にだけ有   {_fmt(m)}")


# ============================================================
# 1県の処理
# ============================================================
def process(pref: str, cfg: dict, dry_run: bool) -> str:
    slug = f"pref-{pref}-1"
    path = DIR / f"{slug}.json"
    if not path.exists():
        return f"[skip] {slug}: JSONなし"
    data = json.loads(path.read_text(encoding="utf-8"))
    existing_total = len(data.get("matches", []))
    cur_played = len([m for m in data.get("matches", [])
                      if m.get("status") == "played" and m.get("hs") is not None])

    try:
        if cfg["platform"] == "goalnote":
            standings, matches = read_goalnote_all(cfg)
            src = ("https://www.goalnote.net/detail-standings.php?tid="
                   f"{cfg.get('standings_from', cfg['tid'])}")
        elif cfg["platform"] == "tecra":
            standings, matches = read_tecra(cfg)
            src = f"https://{cfg['host']}/order/1/{SEASON_YEAR}/all"
        else:
            # 県ごとの独自システム。読者に見せる公式ページを source にする。
            reader = {"gunma": read_gunma, "miyazaki": read_miyazaki,
                      "yamaguchi": read_yamaguchi}[cfg["platform"]]
            standings, matches = reader(cfg)
            src = cfg["source"]
    except Exception as e:
        return f"[要確認] {slug}: 取得失敗 ({e})"

    # 宮崎のように公式順位表が機械可読でない県は、順位表を試合から自前計算する
    # （standings_gate: "self"）。その県では順位表が空でも異常ではない。
    if not standings and cfg.get("standings_gate") != "self":
        return f"[要確認] {slug}: 順位表を解析できず（据え置き）"
    if not matches:
        return f"[要確認] {slug}: 試合一覧を解析できず（据え置き）"

    # --- 名寄せ（公式表記 → 既存JSONのチーム名） ---
    site_names = [t["name"] for t in data.get("teams", []) if t.get("name")]
    official_names = (set(standings) | {m["home"] for m in matches}
                      | {m["away"] for m in matches})
    name_map, unknown = build_name_map(official_names, site_names, pref)
    if unknown:
        return f"[要確認] {slug}: 名寄せできないチーム名 {unknown[:4]}（据え置き）"
    if len(set(name_map.values())) != len(site_names):
        return (f"[要確認] {slug}: チーム名が1対1で対応しない"
                f"（公式{len(set(name_map.values()))}／既存{len(site_names)}・据え置き）")

    standings = {name_map[k]: v for k, v in standings.items()}
    matches = [dict(m, home=name_map[m["home"]], away=name_map[m["away"]]) for m in matches]

    # --- 出典に日付が無い県は、既存JSONの同じ対戦から date を引き継ぐ（山口） ---
    # 出典のダミー日付（山口は全試合 2026/04/04）は絶対に採用しない。
    # 新しく増える試合は日付なしのままになる＝県ページの「直近の試合結果」には出ない。
    if cfg.get("inherit_dates"):
        prev = {}
        for m in data.get("matches", []):
            if m.get("date"):
                prev.setdefault((m.get("home"), m.get("away")), []).append(m["date"])
                # 出典の左右はホーム/アウェイと限らないので逆向きも見る
                prev.setdefault((m.get("away"), m.get("home")), []).append(m["date"])
        for m in matches:
            got = prev.get((m["home"], m["away"]))
            if got:
                m["date"] = got.pop(0)

    # --- 消化と未消化を分ける ---
    # 未消化の行を返すのは宮崎だけ（節番号を活かすため）。他県は空になる。
    upcoming = [m for m in matches if m.get("hs") is None or m.get("as") is None]
    matches = [m for m in matches if m.get("hs") is not None and m.get("as") is not None]

    # --- 宮崎は公式順位表が画像PDFなので、順位表を自前計算して代替ゲートで守る ---
    if cfg.get("standings_gate") == "self":
        standings = standings_from_matches(matches, site_names)
        ng = self_check_gate(data, standings, matches, site_names)
        if ng:
            return f"[据え置き] {slug}: 検算不一致 {ng[:2]} …"

    # --- 検算とJSON組み立て（junior-soccer版と同じ関数を使う） ---
    # round_robin: False のリーグは総当たり枠を作らない。
    # 鳥取の後期のようにグループ分けのリーグでは、8チームの総当たり（56枠）を
    # 機械的に作ると**存在しない試合枠が大量に出る**。出典の試合一覧をそのまま枠にする。
    res = build_from_source(standings, matches, existing_total,
                            round_robin=cfg.get("round_robin", True))
    if isinstance(res, str):
        return f"[据え置き] {slug}: {res}"
    team_objs, fixtures, meta = res

    # 未消化試合にも出典の節番号を入れる（宮崎は第15〜18節が未消化）。
    # 「次節」を出すときに効くので、取れる県では入れておく。
    if upcoming:
        slots = {}
        for f in fixtures:
            if f.get("status") != "played":
                slots.setdefault((f["home"], f["away"]), []).append(f)
                slots.setdefault((f["away"], f["home"]), []).append(f)
        for m in upcoming:
            if not m.get("md"):
                continue
            got = slots.get((m["home"], m["away"]))
            while got:
                f = got.pop(0)
                if not f.get("md"):
                    f["md"] = m["md"]
                    break

    # 書き込む内容が公式の消化数と一致しているか（試合が落ちていないかの最終確認）
    written = sum(1 for f in fixtures if f.get("status") == "played")
    if written != meta["played"]:
        return (f"[要確認] {slug}: 組み立て後の消化{written}件が公式{meta['played']}件と"
                f"合わない（試合が落ちている・据え置き）")

    new_played = meta["played"]
    if new_played < cur_played:
        return (f"[据え置き] {slug}: 公式消化{new_played} < 現在{cur_played}"
                f"（公式側が遅れている。退行防止）")

    diff = diff_against_existing(data, fixtures)
    if dry_run:
        print_diff(pref, diff)
        return f"[DRY RUN] {slug}: 消化{new_played}試合（検算一致・書き込みなし）"

    print_diff(pref, diff)
    data["teams"] = team_objs
    data["matches"] = fixtures
    data["official_standings"] = meta["official"]
    data["source"] = src
    data["sourceName"] = cfg["label"]
    data["lastUpdated"] = _date.today().isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"[更新] {slug}: 消化{new_played}試合に更新（検算一致）"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="県1部9県を県協会公式（GoalNote / tecra）から更新する")
    parser.add_argument("--dry-run", action="store_true",
                        help="書き込まず、既存との差分だけ出す")
    parser.add_argument("--only", default="", help="県idをカンマ区切りで指定")
    args = parser.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    print("=== 県1部 戦績表 自動更新（県協会公式：GoalNote / tecra）===")
    updated = held = warn = 0
    for pref, cfg in PREF_OFFICIAL.items():
        if only and pref not in only:
            continue
        try:
            msg = process(pref, cfg, args.dry_run)
        except Exception as e:      # 想定外でも他県は止めない
            msg = f"[要確認] pref-{pref}-1: 例外 {e}"
        print(" ", msg)
        if msg.startswith("[更新]"):
            updated += 1
        elif msg.startswith("[据え置き]"):
            held += 1
        elif msg.startswith("[要確認]"):
            warn += 1
    print(f"--- 完了: 更新{updated} / 据え置き{held} / 要確認{warn} ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
