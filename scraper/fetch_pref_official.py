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
    "tottori":  {"platform": "goalnote", "tid": "18541", "label": "鳥取県サッカー協会 公式（GoalNote）"},
    "kagawa":   {"platform": "goalnote", "tid": "18633", "label": "香川県サッカー協会 公式（GoalNote）"},
    "shiga":    {"platform": "tecra", "host": "shiga-fa-u18.com", "label": "滋賀県サッカー協会 公式"},
    "fukuoka":  {"platform": "tecra", "host": "fukuoka-fa-u18.com", "label": "福岡県サッカー協会 公式"},
    "saga":     {"platform": "tecra", "host": "saga-fa-u18.com", "label": "佐賀県サッカー協会 公式"},
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
}

_SCORE_RE = re.compile(r"(\d+)\s*[-ー－―]\s*(\d+)")
_GN_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
_TECRA_DATE_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


# ============================================================
# 取得
# ============================================================
def fetch_html(url: str) -> str:
    last = None
    for _ in range(RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
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
        if standings:
            break

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
            standings, matches = read_goalnote(cfg)
            src = f"https://www.goalnote.net/detail-standings.php?tid={cfg['tid']}"
        else:
            standings, matches = read_tecra(cfg)
            src = f"https://{cfg['host']}/order/1/{SEASON_YEAR}/all"
    except Exception as e:
        return f"[要確認] {slug}: 取得失敗 ({e})"

    if not standings:
        return f"[要確認] {slug}: 順位表を解析できず（据え置き）"
    if not matches:
        return f"[要確認] {slug}: 試合一覧を解析できず（据え置き）"

    # --- 名寄せ（公式表記 → 既存JSONのチーム名） ---
    site_names = [t["name"] for t in data.get("teams", []) if t.get("name")]
    official_names = set(standings) | {m["home"] for m in matches} | {m["away"] for m in matches}
    name_map, unknown = build_name_map(official_names, site_names, pref)
    if unknown:
        return f"[要確認] {slug}: 名寄せできないチーム名 {unknown[:4]}（据え置き）"
    if len(set(name_map.values())) != len(site_names):
        return (f"[要確認] {slug}: チーム名が1対1で対応しない"
                f"（公式{len(set(name_map.values()))}／既存{len(site_names)}・据え置き）")

    standings = {name_map[k]: v for k, v in standings.items()}
    matches = [dict(m, home=name_map[m["home"]], away=name_map[m["away"]]) for m in matches]

    # --- 検算とJSON組み立て（junior-soccer版と同じ関数を使う） ---
    res = build_from_source(standings, matches, existing_total)
    if isinstance(res, str):
        return f"[据え置き] {slug}: {res}"
    team_objs, fixtures, meta = res

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
