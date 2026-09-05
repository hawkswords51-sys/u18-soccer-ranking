#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
プレミアリーグ EAST/WEST を「JFA公式JSON」から更新する
==========================================================
2026-09-05 新設。

なぜ作ったか
------------
プレミアの順位・戦績はこれまで koko-soccer をスクレイピングしていたが、反映が遅い。
JFA公式の日程・結果ページは JavaScript で表を描くので素のHTMLでは中身が取れないが、
そのページが裏で読んでいる JSON を直接叩けることが分かった。JSONなのでHTML解析は不要で、
requests と json だけで済む。これで「試合当日の夜にサイトへ自動反映」できる。

取りに行く先（{season} と {side} を入れ替えるだけ）
  https://www.jfa.jp/match/takamado_jfa_u18_premier{season}/{side}/match/schedule.json
      … 全132試合。日付・会場・キックオフ時刻・スコア・得点者・公式記録PDFのURL
  https://www.jfa.jp/match/takamado_jfa_u18_premier{season}/{side}/match/fight.json
      … 順位表（competitionStanding）と星取り表（matchStarMap）

書き出す先
  data/league_matches/premier-{east,west}.json … 全試合＋順位表（既存スキーマのまま）
  data/scorers/premier-{east,west}.json        … 得点ランキング（得点者を自前で集計）
  data/teams.json                              … プレミア24チームの成績・順位

安全設計（いちばん大事なところ）
--------------------------------
「JFA優先＋koko予備」。JFAが取れない・数字が合わないときは **1バイトも書かずに** 終了する。
書かなければ既存データがそのまま残り、その後の update.py / update_cross_tables.py が
従来どおり koko から更新する。つまり落ちてもサイトは止まらない。

検算（1つでも落ちたらそのリーグは書かない）
  1. HTTP・JSONパースが成功しているか
  2. 順位表が12チームちょうどか
  3. 各チームで  試合数 = 勝+分+敗   かつ  勝点 = 勝×3+分
  4. schedule.json の消化試合から積み上げた 得点/失点/勝分敗/勝点 が、順位表と全項目一致するか
  5. チーム名が data/league_matches と data/teams.json の両方に1対1で名寄せできるか
  6. 今回の消化試合数が、既存JSONの消化試合数より減っていないか（＝退行なら書かない）

未消化試合の日付・時刻・会場は毎回JFAの値で入れ替える（日程変更に追従する）。
ただし「すでに結果が入っている試合の日付が動いた」場合だけ [要確認] をログに出す
（出典が別試合と取り違えている等の事故を検知するため。更新自体は止めない）。

「JFAが今日はまだ更新していない」と「JFAが壊れている」は区別しなくてよい。
どちらも「消化試合が増えていないだけ」なので、既存維持で正しく振る舞う。

年度切り替え
------------
下の SEASON を "2027" に変えるだけ。（チーム入れ替えで名寄せが外れた場合は
ログに [要確認] が出て自動的に koko 側へ回るので、サイトが壊れることはない）

使い方
------
  python scraper/fetch_jfa_premier.py            # 取得して書き込む
  python scraper/fetch_jfa_premier.py --dry-run  # 取得・検算だけして書き込まない
終了コードは常に0（更新0件でも正常。要確認はログで通知する）。
"""
import argparse
import collections
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

# ===== 設定 =====
SEASON = "2026"          # ← 年度切り替えはここ1行だけ

BASE = "https://www.jfa.jp/match/takamado_jfa_u18_premier{season}/{side}/match/"
# サイトに「出典」として出す人間向けページ（JSONではなく日程・結果ページ）
PAGE = "https://www.jfa.jp/match/takamado_jfa_u18_premier{season}/{side}/schedule_result/"

SIDES = {"east": "premier-east", "west": "premier-west"}
LEAGUE_NAMES = {"premier-east": "プレミアリーグEAST", "premier-west": "プレミアリーグWEST"}

ROOT = Path(__file__).resolve().parent.parent
MATCH_DIR = ROOT / "data" / "league_matches"
SCORER_DIR = ROOT / "data" / "scorers"
TEAMS_FILE = ROOT / "data" / "teams.json"

# JFAが成功したリーグを update.py / update_cross_tables.py に伝えるメモ。
# gitには入れない（.gitignore 済み）。同じ日付のものだけ有効とみなす。
STATUS_FILE = ROOT / ".jfa_premier_status.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
        "(u18-soccer.com premier updater)"
    )
}
TIMEOUT = 20
RETRIES = 2  # 初回とあわせて計3回

# 得点ランキングに載せる下限（既存の data/scorers/prince-*.json と同じ流儀）
SCORER_MIN_GOALS = 2

# 末尾の括弧を「中身が都道府県名のときだけ」外すための一覧。
# fight.json の順位表だけ「流通経済大学付属柏高校(千葉県)」と県名が付き、
# 星取り表と schedule.json は括弧なしなので、ここで表記を揃える。
# （update_cross_tables.py の norm() と同じ考え方）
PREFECTURES = {
    "北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島",
    "茨城", "栃木", "群馬", "埼玉", "千葉", "東京", "神奈川",
    "新潟", "富山", "石川", "福井", "山梨", "長野", "岐阜", "静岡", "愛知",
    "三重", "滋賀", "京都", "大阪", "兵庫", "奈良", "和歌山",
    "鳥取", "島根", "岡山", "広島", "山口",
    "徳島", "香川", "愛媛", "高知",
    "福岡", "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島", "沖縄",
}

# 自動の名寄せでは絶対に当たらない組み合わせだけを手で書く。
# キーは _norm() / _core() を通した後のJFA表記、値はこのリポジトリ側の表記。
# 例: JFA「流通経済大学付属柏高校」↔ 当サイト「流通経済大柏」は共通部分が無く、
#     部分一致でも類似判定でも当たらない。
NAME_OVERRIDES = {
    "流通経済大学付属柏": "流通経済大柏",
}


# ============================================================
# チーム名の正規化・名寄せ
# ============================================================
def _is_prefecture(text: str) -> bool:
    """括弧の中身が都道府県名か（「東京都」「大阪府」「千葉県」表記も許容）"""
    raw = str(text).strip()
    return raw in PREFECTURES or re.sub(r"(都|道|府|県)$", "", raw) in PREFECTURES


def _norm(name: str) -> str:
    """比較用の正規化。末尾の（県名）を外し、全角半角・空白・ピリオドの差を吸収する。"""
    s = unicodedata.normalize("NFKC", str(name or "")).strip()
    m = re.search(r"[（(]([^（()）]*)[）)]\s*$", s)
    if m and _is_prefecture(m.group(1)):
        s = s[:m.start()].strip()
    return s.replace(" ", "").replace("　", "").replace(".", "")


def _core(name: str) -> str:
    """さらに「高校/高等学校/高等部」を落とした芯の部分を返す（大津高校 ↔ 大津）"""
    s = _norm(name)
    for suffix in ("高等学校", "高等部", "高校"):
        if s.endswith(suffix):
            return s[:-len(suffix)]
    return s


def _build_resolver(names: list[str]):
    """JFAのチーム名 → names の中の正式名 に変換する関数を作る。
    当たらなければ None を返す（＝呼び出し側で [要確認] にして書き込まない）。
    """
    index: dict[str, str] = {}
    for n in names:
        index.setdefault(_norm(n), n)
        index.setdefault(_core(n), n)

    def resolve(jfa_name: str):
        n = _norm(jfa_name)
        c = _core(jfa_name)
        if n in NAME_OVERRIDES:
            return NAME_OVERRIDES[n]
        if c in NAME_OVERRIDES:
            return NAME_OVERRIDES[c]
        hit = index.get(n) or index.get(c)
        if hit:
            return hit
        # 最後の手段: 芯の部分の包含。候補が1つに絞れるときだけ採用する。
        cand = sorted({x for x in names if _core(x) in c or c in _core(x)})
        return cand[0] if len(cand) == 1 else None

    return resolve


# ============================================================
# 取得
# ============================================================
def fetch_json(url: str):
    """JSONを取得する。失敗したら例外を投げる（呼び出し側で [要確認] にする）。"""
    last = None
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return json.loads(resp.text)
        except Exception as e:   # 通信エラー・404・JSON壊れ すべてここ
            last = e
    raise RuntimeError(f"{url} の取得に失敗 ({last})")


# ============================================================
# 解析
# ============================================================
def _split_scorer(line: str) -> dict | None:
    """ '45+1分 立石 陽向' -> {'minute': '45+1', 'name': '立石 陽向'}
        '12分 オウンゴール' -> {'minute': '12', 'name': 'オウンゴール', 'ownGoal': True}
    形式が違う行は None（集計に混ぜない）。
    """
    s = str(line or "").strip()
    m = re.match(r"^(\d+(?:\+\d+)?)\s*分\s*(.+)$", s)
    if not m:
        return None
    minute, name = m.group(1), m.group(2).strip()
    if not name:
        return None
    if "オウンゴール" in name:
        return {"minute": minute, "name": name, "ownGoal": True}
    return {"minute": minute, "name": name}


def date_change_warnings(old_matches, new_matches) -> list[str]:
    """[2026-09-05 新設] 出典側の事故を検知するための照合。

    日付が変わること自体は正常（日程変更・延期は普通に起きる）。異常なのは
    **すでに結果が確定している試合の日付が動く**ケースで、出典が別の試合と
    取り違えている等のサイン。見つけたら警告文を返す（更新自体は止めない。
    止めると日程変更が永久に反映されなくなる）。
    update_cross_tables.py の同名関数と同じ考え方。プレミアはそちらを通らなく
    なったので、こちらにも同じ見張りを置いている。
    """
    prev = {}
    for m in old_matches or []:
        if m.get("status") == "played" and m.get("date"):
            prev[(m.get("md"), m.get("home"), m.get("away"))] = m["date"]
    warns = []
    for m in new_matches:
        if m.get("status") != "played":
            continue
        before = prev.get((m.get("md"), m.get("home"), m.get("away")))
        after = m.get("date") or ""
        if before and after and after != before:
            warns.append(f"第{m['md']}節 {m['home']} vs {m['away']} の日付が "
                         f"{before}→{after} に変化")
    return warns


def _md_of(match_type_name: str):
    """ '第12節' -> 12 """
    m = re.search(r"(\d+)", str(match_type_name or ""))
    return int(m.group(1)) if m else None


def _iso_date(raw: str) -> str:
    """ '2026/09/05' -> '2026-09-05' 。読めなければ空文字。"""
    m = re.match(r"^\s*(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", str(raw or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def parse_side(side: str, slug: str, existing: dict) -> tuple[dict | None, str]:
    """east / west 1つ分を取得・解析・検算する。
    戻り値: (結果dict, メッセージ)。検算に落ちたら (None, 理由)。
    """
    base = BASE.format(season=SEASON, side=side)
    try:
        schedule_raw = fetch_json(base + "schedule.json")
        fight_raw = fetch_json(base + "fight.json")
    except Exception as e:
        return None, f"[要確認] {slug}: JFA公式JSONを取得できない ({e})"

    try:
        matches_raw = schedule_raw["matchScheduleList"]["matchSchedule"]
        standing_raw = fight_raw["competitionStanding"]["team"]
    except (KeyError, TypeError) as e:
        return None, f"[要確認] {slug}: JFA公式JSONの構造が変わっている ({e})"

    if len(standing_raw) != 12:
        return None, f"[要確認] {slug}: 順位表が{len(standing_raw)}チーム（12でない）"

    # --- 名寄せ表を作る（このリーグのJSONに書いてあるチーム名が正） ---
    site_names = [t.get("name", "") for t in existing.get("teams", []) if t.get("name")]
    if len(site_names) != 12:
        return None, f"[要確認] {slug}: 既存JSONのteamsが{len(site_names)}件（12でない）"
    resolve = _build_resolver(site_names)

    jfa_names = {t.get("teamName", "") for t in standing_raw}
    for m in matches_raw:
        jfa_names.add(m.get("homeTeamName", ""))
        jfa_names.add(m.get("awayTeamName", ""))
    name_map: dict[str, str] = {}
    unknown = []
    for j in sorted(jfa_names):
        hit = resolve(j)
        if hit is None:
            unknown.append(j)
        else:
            name_map[j] = hit
    if unknown:
        return None, f"[要確認] {slug}: 名寄せできないチーム名 {unknown[:3]}（据え置き）"
    if len(set(name_map.values())) != 12:
        return None, f"[要確認] {slug}: チーム名が1対1で対応しない（据え置き）"

    # --- 試合一覧を組み立てる ---
    out_matches = []
    for m in matches_raw:
        md = _md_of(m.get("matchTypeName"))
        if md is None:
            return None, f"[要確認] {slug}: 節番号が読めない試合がある（{m.get('matchTypeName')}）"
        home = name_map[m.get("homeTeamName", "")]
        away = name_map[m.get("awayTeamName", "")]
        score = m.get("score") or {}
        hs_raw = str(score.get("homeScore", "")).strip()
        as_raw = str(score.get("awayScore", "")).strip()
        played = (m.get("matchStatus") == "試合終了"
                  and hs_raw.isdigit() and as_raw.isdigit())

        rec = {
            "md": md,
            "date": _iso_date(m.get("matchDate")),
            "home": home,
            "hs": int(hs_raw) if played else None,
            "as": int(as_raw) if played else None,
            "away": away,
            "status": "played" if played else "scheduled",
        }
        # 会場・キックオフ時刻・公式記録PDF（プリンス・県リーグには無いフィールド。
        # 表示側は存在チェックしてから描くこと）
        venue = str(m.get("venueFullName") or m.get("venue") or "").strip()
        if venue:
            rec["venue"] = venue
        kickoff = str(m.get("matchTime") or "").strip()
        if kickoff:
            rec["kickoff"] = kickoff
        report = str(m.get("officialReportURL") or "").strip()
        if report:
            rec["reportUrl"] = urljoin(base, report)
        # 得点者（時間帯別得点などの企画に使えるよう、分も残す）
        if played:
            scorer = m.get("scorer") or {}
            hsc = [x for x in (_split_scorer(s) for s in scorer.get("homeScorer") or []) if x]
            asc = [x for x in (_split_scorer(s) for s in scorer.get("awayScorer") or []) if x]
            rec["homeScorers"] = hsc
            rec["awayScorers"] = asc
        out_matches.append(rec)

    out_matches.sort(key=lambda r: (r["md"], r["date"], r["home"]))

    # --- 消化試合から順位を組み立て直す（検算その1） ---
    calc = {n: dict(pts=0, played=0, won=0, drawn=0, lost=0, gf=0, ga=0)
            for n in set(name_map.values())}
    goals = collections.Counter()      # (チーム, 選手) -> 得点
    own_goals = collections.Counter()  # チーム -> もらったオウンゴール数
    last_played_date = ""
    for r in out_matches:
        if r["status"] != "played":
            continue
        h, a, hs, a_s = r["home"], r["away"], r["hs"], r["as"]
        for t, gf, ga in ((h, hs, a_s), (a, a_s, hs)):
            s = calc[t]
            s["played"] += 1
            s["gf"] += gf
            s["ga"] += ga
            if gf > ga:
                s["won"] += 1
                s["pts"] += 3
            elif gf == ga:
                s["drawn"] += 1
                s["pts"] += 1
            else:
                s["lost"] += 1
        for team, key in ((h, "homeScorers"), (a, "awayScorers")):
            for sc in r.get(key, []):
                if sc.get("ownGoal"):
                    own_goals[team] += 1
                else:
                    goals[(team, sc["name"])] += 1
        if r["date"] > last_played_date:
            last_played_date = r["date"]

    # --- JFA掲載の順位表を読む（検算その2・その3） ---
    official = {}
    for t in standing_raw:
        name = name_map[t.get("teamName", "")]
        try:
            official[name] = dict(
                rank=int(t["rank"]),
                pts=int(t["winPoint"]),
                played=int(t["games"]),
                won=int(t["win"]),
                drawn=int(t["tie"]),
                lost=int(t["lost"]),
                gf=int(t["getScorePoint"]),
                ga=int(t["lostScorePoint"]),
            )
        except (KeyError, ValueError, TypeError) as e:
            return None, f"[要確認] {slug}: 順位表の数値が読めない（{t.get('teamName')} / {e}）"

    mismatch = []
    for name, o in official.items():
        if o["played"] != o["won"] + o["drawn"] + o["lost"]:
            mismatch.append(f"{name}: 試合数{o['played']}≠勝分敗の合計")
        if o["pts"] != o["won"] * 3 + o["drawn"]:
            mismatch.append(f"{name}: 勝点{o['pts']}≠勝×3+分")
        c = calc[name]
        for k, label in (("played", "試合"), ("won", "勝"), ("drawn", "分"),
                         ("lost", "敗"), ("gf", "得点"), ("ga", "失点"), ("pts", "勝点")):
            if c[k] != o[k]:
                mismatch.append(f"{name}.{label} 日程から計算{c[k]}≠順位表{o[k]}")
    if mismatch:
        return None, f"[要確認] {slug}: 検算不一致 {mismatch[:3]} …（据え置き）"

    # --- 退行チェック: 既存より消化試合が減っていたら書かない ---
    new_played = sum(1 for r in out_matches if r["status"] == "played")
    cur_played = sum(1 for m in existing.get("matches", []) if m.get("status") == "played")
    if new_played < cur_played:
        return None, (f"[据え置き] {slug}: JFA消化{new_played} < 現在{cur_played}"
                      f"（減っているので上書きしない）")

    # --- 順位表を書き出し用に並べる（JFA掲載の順位をそのまま使う） ---
    out_standings = []
    for name, o in sorted(official.items(), key=lambda kv: kv[1]["rank"]):
        out_standings.append(dict(rank=o["rank"], team=name, pts=o["pts"],
                                  played=o["played"], won=o["won"], drawn=o["drawn"],
                                  lost=o["lost"], gf=o["gf"], ga=o["ga"],
                                  gd=o["gf"] - o["ga"]))

    # --- 得点ランキング（検算その4: 選手の得点合計＋OG＝GF） ---
    short_by_name = {t.get("name", ""): (t.get("short") or t.get("name", ""))
                     for t in existing.get("teams", [])}
    coverage = []
    for name, o in official.items():
        counted = sum(v for (t, _), v in goals.items() if t == name) + own_goals[name]
        if counted != o["gf"]:
            coverage.append({"team": short_by_name.get(name, name),
                             "missing": o["gf"] - counted})

    ranked = []
    items = sorted(goals.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
    prev_goals = None
    rank = 0
    for i, ((team, player), g) in enumerate(items, 1):
        if g != prev_goals:
            rank = i
            prev_goals = g
        if g < SCORER_MIN_GOALS:
            continue
        ranked.append({"rank": rank, "name": player,
                       "team": short_by_name.get(team, team), "goals": g})

    # teams.json を探すときに使う「当サイト表記 → JFA公式表記」の対応
    jfa_name_by_site = {v: k for k, v in name_map.items()}

    return {
        "slug": slug,
        "jfaNameBySite": jfa_name_by_site,
        "dateWarnings": date_change_warnings(existing.get("matches"), out_matches),
        "matches": out_matches,
        "standings": out_standings,
        "official": official,
        "scorers": ranked,
        "coverage": coverage,
        "asof": last_played_date,
        "played": new_played,
        "page": PAGE.format(season=SEASON, side=side),
    }, f"[OK] {slug}: 消化{new_played}試合（検算すべて一致）"


# ============================================================
# 書き出し
# ============================================================
def write_league_matches(res: dict, existing: dict) -> None:
    """data/league_matches/<slug>.json を更新する。
    league / season / teams は既存の設定をそのまま残す（表示側を触らずに済ませるため）。
    """
    data = dict(existing)
    data["season"] = SEASON
    data["source"] = res["page"]
    # 戦績表（星取り表）の「出典: ○○」に出る名前。cross_table.py が読む既存の仕組み。
    data["sourceName"] = "JFA公式"
    data["lastUpdated"] = date.today().isoformat()
    data["matches"] = res["matches"]
    data["official_standings"] = res["standings"]
    # キーの並びを既存ファイルと同じにする（差分を読みやすくするため）
    order = ["league", "season", "source", "sourceName", "lastUpdated", "teams",
             "official_standings", "matches"]
    ordered = {k: data[k] for k in order if k in data}
    for k, v in data.items():
        ordered.setdefault(k, v)
    path = MATCH_DIR / f"{res['slug']}.json"
    # 既存ファイルに合わせて末尾に改行は付けない（無用な差分を出さないため）
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def write_scorers(res: dict, existing_league_label: str) -> None:
    """data/scorers/<slug>.json を更新する（得点者はJFA公式の試合記録を自前で集計）"""
    note = (f"{SCORER_MIN_GOALS}得点以上の選手を掲載。"
            "JFA公式の試合記録に載っている得点者を全試合ぶん集計したもの。"
            "オウンゴールは個人の得点に数えていません。")
    out = {
        "league": f"{existing_league_label} 得点ランキング",
        "season": SEASON,
        "source": res["page"],
        "sourceLabel": "JFA公式",
        "lastUpdated": date.today().isoformat(),
        "asof": res["asof"],
        "note": note,
        "scorers": res["scorers"],
        "coverage": res["coverage"],
    }
    path = SCORER_DIR / f"{res['slug']}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _scan_teams_json(teams_data: dict, matcher):
    """teams.json 全体を走査し、matcher(チーム名とaliasesのリスト) が真になるチームを集める"""
    hits = []
    for pref_id, pref_data in teams_data.items():
        if pref_id == "_meta":
            continue
        for team in pref_data.get("teams", []):
            names = [team.get("name", "")] + list(team.get("aliases") or [])
            if matcher([n for n in names if n]):
                hits.append((pref_id, team))
    return hits


def _find_team_entry(teams_data: dict, site_name: str, jfa_name: str = ""):
    """teams.json 全体からこのチームを1件だけ探す。
    見つからない・複数当たる場合は None（＝書き込まずに [要確認]）。

    照合の順番:
      1. JFA公式の表記との完全一致（teams.json は「前橋育英高校」等、JFA表記に近い）
      2. 当サイトの戦績表での表記との完全一致（「流通経済大柏」等）
      3. 「高校/高等学校/高等部」を落とした芯での一致（候補が1つに絞れるときだけ）
    aliases も必ず見る（過去に aliases を見ずに1チームだけ順位が止まる事故があった）。
    """
    for target in (_norm(jfa_name), _norm(site_name)):
        if not target:
            continue
        hits = _scan_teams_json(teams_data, lambda ns: any(_norm(n) == target for n in ns))
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None
    target = _core(jfa_name or site_name)
    if target:
        hits = _scan_teams_json(teams_data, lambda ns: any(_core(n) == target for n in ns))
        if len(hits) == 1:
            return hits[0]
    return None


def update_teams_json(results: list[dict]) -> tuple[bool, list[str]]:
    """data/teams.json のプレミア該当チームの成績を更新する。
    1チームでも見つからなければ **1件も書かずに** False を返す（中途半端に書かない）。
    """
    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))

    plan = []       # (team_dict, stats) の予定表。全部そろってから一気に適用する
    problems = []
    for res in results:
        league_name = LEAGUE_NAMES[res["slug"]]
        for row in res["standings"]:
            jfa_name = res.get("jfaNameBySite", {}).get(row["team"], "")
            found = _find_team_entry(teams_data, row["team"], jfa_name)
            if not found:
                problems.append(f"{res['slug']}: teams.json に「{row['team']}」が1件に絞れない")
                continue
            _pref_id, team = found
            plan.append((team, row, league_name))

    if problems:
        return False, problems

    for team, row, league_name in plan:
        team["points"] = row["pts"]
        team["played"] = row["played"]
        team["won"] = row["won"]
        team["drawn"] = row["drawn"]
        team["lost"] = row["lost"]
        team["goalsFor"] = row["gf"]
        team["goalsAgainst"] = row["ga"]
        team["goalDiff"] = row["gd"]
        team["league"] = league_name
        team["leagueRank"] = row["rank"]

    # 県内順位（rank / prefectureRank）と leagueRank の振り直しは、この直後に走る
    # update.py・normalize_league_ranks.py が従来どおり担当する。ここでやると
    # プレミアと無関係な県のチームまで並び替わって差分が読めなくなるため触らない。
    teams_data["_meta"] = {
        **teams_data.get("_meta", {}),
        "lastUpdated": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
    }
    TEAMS_FILE.write_text(json.dumps(teams_data, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return True, []


def write_status(ok_slugs: list[str]) -> None:
    """成功したリーグを書き残す。update.py / update_cross_tables.py がこれを見て
    「JFAで更新済みのリーグは koko で上書きしない」と判断する。"""
    STATUS_FILE.write_text(json.dumps(
        {"date": date.today().isoformat(), "season": SEASON, "ok": sorted(ok_slugs)},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def jfa_updated_slugs() -> set[str]:
    """今日JFAから更新できたリーグのslug集合を返す（他スクリプトから呼ぶ用）。
    メモが無い・日付が今日でない場合は空集合＝「JFAは使えていない」とみなす。"""
    try:
        d = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if d.get("date") != date.today().isoformat():
        return set()
    return set(d.get("ok") or [])


# ============================================================
# メイン
# ============================================================
def run(dry_run: bool = False) -> list[str]:
    """east/west を処理し、成功したslugのリストを返す"""
    print(f"=== プレミアリーグ JFA公式JSON取得 ({SEASON}) ===")
    results = []
    messages = []
    for side, slug in SIDES.items():
        path = MATCH_DIR / f"{slug}.json"
        if not path.exists():
            messages.append(f"[skip] {slug}: {path} が無い")
            print(" ", messages[-1])
            continue
        existing = json.loads(path.read_text(encoding="utf-8"))
        res, msg = parse_side(side, slug, existing)
        messages.append(msg)
        print(" ", msg)
        if res:
            results.append((res, existing))

    if not results:
        print("\n更新0件。既存データはそのまま（koko側の処理に任せます）。")
        return []

    if dry_run:
        for res, _ in results:
            print(f"  [DRY RUN] {res['slug']}: "
                  f"順位{len(res['standings'])}チーム / 試合{len(res['matches'])}件 / "
                  f"得点ランキング{len(res['scorers'])}人 / 最終試合日 {res['asof']}")
        print("\n[DRY RUN] 書き込みはしていません。")
        return []

    # teams.json は east/west まとめて（1チームでも名寄せできなければ全部書かない）
    ok, problems = update_teams_json([r for r, _ in results])
    if not ok:
        for p in problems:
            print(f"  [要確認] {p}")
        print("\ndata/teams.json は更新しませんでした（既存維持）。"
              "戦績表・得点ランキングも書き込みを中止します。")
        return []
    print(f"  ✓ data/teams.json を更新（{sum(len(r['standings']) for r, _ in results)}チーム）")

    ok_slugs = []
    for res, existing in results:
        write_league_matches(res, existing)
        write_scorers(res, existing.get("league", res["slug"]))
        ok_slugs.append(res["slug"])
        print(f"  ✓ data/league_matches/{res['slug']}.json / "
              f"data/scorers/{res['slug']}.json を更新")
        for w in res.get("dateWarnings", []):
            print(f"  [要確認] {res['slug']}: {w}")

    write_status(ok_slugs)
    print(f"\n✅ 完了: {len(ok_slugs)} リーグをJFA公式JSONから更新しました")
    return ok_slugs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="プレミアリーグをJFA公式JSONから更新する")
    parser.add_argument("--dry-run", action="store_true",
                        help="取得・検算だけして書き込まない")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
    return 0  # 更新0件でも異常ではないので常に0


if __name__ == "__main__":
    sys.exit(main())
