#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
プレミア2＋プリンス13の全15リーグを「JFA公式」から更新する
============================================================
2026-09-05 新設（プレミア2リーグ）／2026-09-06 プリンス13リーグに拡張。

なぜ作ったか
------------
順位・戦績はこれまで koko-soccer をスクレイピングしていたが、反映が遅い。
JFA公式の日程・結果ページは JavaScript で表を描くので素のHTMLでは中身が取れないが、
そのページが裏で読んでいる JSON を直接叩けることが分かった。JSONなのでHTML解析は不要で、
requests と json だけで済む。これで「試合当日の夜にサイトへ自動反映」できる。

取りに行く先
------------
プレミア（JSON・2リーグ）
  https://www.jfa.jp/match/takamado_jfa_u18_premier{season}/{side}/match/schedule.json
  https://www.jfa.jp/match/takamado_jfa_u18_premier{season}/{side}/match/fight.json

プリンス（JSON・12リーグ）
  https://www.jfa.jp/match_47fa/{code}/takamado_jfa_u18_prince{season}/[{div}/]match/schedule.json
  https://www.jfa.jp/match_47fa/{code}/takamado_jfa_u18_prince{season}/[{div}/]match/fight.json
  ※ 2部制の地域だけ {div}（kanto1 / kanto2 など）が挟まる。1部制の地域は挟まらない。

プリンス東北（HTMLのみ・1リーグ）
  https://www.jfa.jp/match_47fa/102_tohoku/takamado_jfa_u18_prince{season}/thfa/schedule.html
  https://www.jfa.jp/match_47fa/102_tohoku/takamado_jfa_u18_prince{season}/thfa/ranking.html
  ※ 東北だけJSONが無い。ただしJS描画ではない素のHTMLなので requests で取れる。

  schedule.json / fight.json の中身
    日付・会場・キックオフ時刻・スコア・得点者・公式記録PDFのURL
    fight.json は matchStarMap（星取り表）＋ competitionStanding（順位表）
    ※ プリンスの順位表は teamName を持たず teamAbbreviatedName だけのことがある。

書き出す先
----------
  data/league_matches/{slug}.json … 全試合＋順位表（既存スキーマのまま）
  data/teams.json                 … 該当チームの成績・順位
  data/scorers/premier-*.json     … 得点ランキング（**プレミア2リーグだけ**）

⚠ プリンスの得点ランキングは触らない
------------------------------------
`data/scorers/prince-*.json` は**このスクリプトでは絶対に書き換えない**。
現行のプリンスの得点ランキングはゲキサカ由来で、JFAのJSONの得点者とは表記も
網羅範囲も違う。うっかり上書きすると既存のランキングが壊れる。
（2026-09-06時点でJFA側にも得点者は入っているが、採用するかは別途判断する）

安全設計（いちばん大事なところ）
--------------------------------
「JFA優先＋koko予備」。JFAが取れない・数字が合わないときは **そのリーグには1バイトも
書かずに** 終了する。書かなければ既存データがそのまま残り、その後の update.py /
update_cross_tables.py が従来どおり koko から更新する。つまり落ちてもサイトは止まらない。
**リーグごとに完全に独立**しているので、1リーグが失敗しても他は通常どおり更新される。

検算（1つでも落ちたらそのリーグは書かない）
  1. HTTP・JSON/HTMLのパースが成功しているか
  2. 順位表のチーム数が既存JSONのチーム数と一致するか
  3. 各チームで  試合数 = 勝+分+敗   かつ  勝点 = 勝×3+分
  4. 日程の消化試合から積み上げた 得点/失点/勝分敗/勝点 が、順位表と全項目一致するか
  5. チーム名が data/league_matches と data/teams.json の両方に1対1で名寄せできるか
  6. 今回の消化試合数が、既存JSONの消化試合数より減っていないか（＝退行なら書かない）

未消化試合の日付・時刻・会場は毎回JFAの値で入れ替える（日程変更に追従する）。
ただし **JFA側が空のときだけは既存の値を残す**（空は値ではないので、上書きすると
情報が減るだけ。北信越2部でJFAに日付が無い試合が実在する）。
ただし「すでに結果が入っている試合の日付が動いた」場合だけ [要確認] をログに出す
（出典が別試合と取り違えている等の事故を検知するため。更新自体は止めない）。

「JFAが今日はまだ更新していない」と「JFAが壊れている」は区別しなくてよい。
どちらも「消化試合が増えていないだけ」なので、既存維持で正しく振る舞う。

年度切り替え
------------
下の SEASON を "2027" に変えるだけで15リーグ全部が切り替わる。
（チーム入れ替えで名寄せが外れた場合はログに [要確認] が出て自動的に koko 側へ回るので、
  サイトが壊れることはない）

使い方
------
  python scraper/fetch_jfa.py                  # 取得して書き込む
  python scraper/fetch_jfa.py --dry-run        # 取得・検算だけして書き込まない（表を出す）
  python scraper/fetch_jfa.py --only prince-tohoku,prince-tokai   # リーグを絞る
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
from bs4 import BeautifulSoup

# ===== 設定 =====
SEASON = "2026"          # ← 年度切り替えはここ1行だけ（15リーグ共通）

_PREMIER_MATCH = "https://www.jfa.jp/match/takamado_jfa_u18_premier{season}/{side}/match/"
_PREMIER_PAGE = "https://www.jfa.jp/match/takamado_jfa_u18_premier{season}/{side}/schedule_result/"
_PRINCE_BASE = "https://www.jfa.jp/match_47fa/{code}/takamado_jfa_u18_prince{season}/"
# 出典として画面に出す人間向けページ（JSONの置き場所は直リンクすると403/404になる）
_PRINCE_PAGE = "https://www.jfa.jp/match/takamado_jfa_u18_prince{season}/{region}/"

# ---- リーグ定義テーブル（ここに1行足せばリーグが増える）----
#   slug     : data/league_matches/{slug}.json のファイル名
#   fmt      : "json"（schedule.json+fight.json） / "html"（東北だけ）
#   code     : 地域コード（プリンスのみ）
#   div      : 2部制の地域だけ入る（kanto1 等）。1部制は無し
#   region   : 出典リンク用の地域名（プリンスのみ）
#   league   : teams.json の league フィールドに入れる値。**プレミアだけ**設定する
#              （プリンスは既存の表記を尊重して触らない）
#   scorers  : True のリーグだけ data/scorers/{slug}.json を書く。**プレミアだけ**
LEAGUES = [
    {"slug": "premier-east", "fmt": "json", "side": "east",
     "league": "プレミアリーグEAST", "scorers": True},
    {"slug": "premier-west", "fmt": "json", "side": "west",
     "league": "プレミアリーグWEST", "scorers": True},

    {"slug": "prince-hokkaido", "fmt": "json", "code": "101_hokkaido", "region": "hokkaido"},
    {"slug": "prince-tohoku", "fmt": "html", "code": "102_tohoku", "dir": "thfa",
     "region": "tohoku"},
    {"slug": "prince-kanto-1", "fmt": "json", "code": "103_kanto", "div": "kanto1",
     "region": "kanto"},
    {"slug": "prince-kanto-2", "fmt": "json", "code": "103_kanto", "div": "kanto2",
     "region": "kanto"},
    {"slug": "prince-hokushinetsu-1", "fmt": "json", "code": "104_hokushinetsu",
     "div": "hokushinetsu1", "region": "hokushinetsu"},
    {"slug": "prince-hokushinetsu-2", "fmt": "json", "code": "104_hokushinetsu",
     "div": "hokushinetsu2", "region": "hokushinetsu"},
    {"slug": "prince-tokai", "fmt": "json", "code": "105_tokai", "region": "tokai"},
    {"slug": "prince-kansai-1", "fmt": "json", "code": "106_kansai", "div": "kansai1",
     "region": "kansai"},
    {"slug": "prince-kansai-2", "fmt": "json", "code": "106_kansai", "div": "kansai2",
     "region": "kansai"},
    {"slug": "prince-chugoku", "fmt": "json", "code": "107_chugoku", "region": "chugoku"},
    {"slug": "prince-shikoku", "fmt": "json", "code": "108_shikoku", "region": "shikoku"},
    {"slug": "prince-kyushu-1", "fmt": "json", "code": "109_kyushu", "div": "kyushu1",
     "region": "kyushu"},
    {"slug": "prince-kyushu-2", "fmt": "json", "code": "109_kyushu", "div": "kyushu2",
     "region": "kyushu"},
]

# update.py がプリンスを「地域まるごと」処理しているので、地域→slug の対応も持っておく。
# その地域のslugが全部JFAで成功したときだけ update.py 側をスキップする。
PRINCE_REGION_SLUGS = {
    "hokkaido": ["prince-hokkaido"],
    "tohoku": ["prince-tohoku"],
    "kanto": ["prince-kanto-1", "prince-kanto-2"],
    "hokushinetsu": ["prince-hokushinetsu-1", "prince-hokushinetsu-2"],
    "tokai": ["prince-tokai"],
    "kansai": ["prince-kansai-1", "prince-kansai-2"],
    "chugoku": ["prince-chugoku"],
    "shikoku": ["prince-shikoku"],
    "kyushu": ["prince-kyushu-1", "prince-kyushu-2"],
}

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
        "(u18-soccer.com league updater)"
    )
}
TIMEOUT = 25
RETRIES = 2  # 初回とあわせて計3回

# 得点ランキングに載せる下限（既存の data/scorers/*.json と同じ流儀）
SCORER_MIN_GOALS = 2

# 末尾の括弧を「中身が都道府県名のときだけ」外すための一覧。
# プレミアの順位表は「流通経済大学付属柏高校(千葉県)」と県名が付き、
# 星取り表と schedule.json は括弧なし。東北のHTMLも「専修大北上高校 (岩手県)」形式。
# 一方セカンドチームの「(B)」は絶対に外してはいけないので、中身で判定する。
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

# 全リーグ共通の読み替え。自動の名寄せでは絶対に当たらない組み合わせだけを手で書く。
# キーは _norm() / _core() を通した後のJFA表記、値はこのリポジトリ側の表記。
NAME_OVERRIDES = {
    "流通経済大学付属柏": "流通経済大柏",
}

# リーグ限定の読み替え（update_cross_tables.py の LEAGUE_ALIASES と同じ考え方）。
# 同じ表記が別リーグでは別チームを指すことがあるので、全体の NAME_OVERRIDES には入れない。
# 例:「大津高校2nd」は九州1部だけの読み替え。九州2部には「大津高校3rd」がいる。
# キーは _norm() を通した後のJFA表記（全角Ｂは半角Bになる）。
LEAGUE_ALIASES = {
    "prince-tohoku": {
        "専修大北上高校": "専大北上",
        "青森山田高校セカンド": "青森山田セカンド",
    },
    "prince-kanto-1": {
        "ジェフユナイテッド市原・千葉U-18": "ジェフユナイテッド千葉U-18",
        "流通経済大学付属柏B": "流通経済大柏(B)",
    },
    "prince-kanto-2": {
        "日本体育大学柏高校": "日体大柏",
        "日本大学藤沢高校": "日大藤沢",
    },
    "prince-hokushinetsu-1": {
        "富山U18": "カターレ富山U-18",
        "新潟U18": "アルビレックス新潟U-18",
        "松本U18": "松本山雅FC U-18",
    },
    "prince-hokushinetsu-2": {
        "金沢U18": "ツエーゲン金沢U-18",
        "長野U18": "AC長野パルセイロU-18",
        "開志JSC高等部": "開志学園JSC",
    },
    "prince-kansai-2": {
        "ヴィッセル神戸U-18B": "ヴィッセル神戸U-18(B)",
        "京都橘B": "京都橘(B)",
        "近江B": "近江(B)",
    },
    "prince-chugoku": {
        "立正大学淞南高校": "立正大淞南",
    },
    "prince-kyushu-1": {
        "大津高校2nd": "大津2nd",
    },
    "prince-kyushu-2": {
        "サガン鳥栖U-18_2nd": "サガン鳥栖U-18 2nd",
        "九州国際大学付属高校": "九州国際大付",
        "大津高校3rd": "大津3rd",
        "日章学園高校2nd": "日章学園2nd",
        "長崎総合科学大学附属高校": "長崎総科大附",
    },
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


def _build_resolver(names: list[str], slug: str = ""):
    """JFAのチーム名 → names の中の正式名 に変換する関数を作る。
    当たらなければ None を返す（＝呼び出し側で [要確認] にして書き込まない）。
    """
    index: dict[str, str] = {}
    for n in names:
        index.setdefault(_norm(n), n)
        index.setdefault(_core(n), n)
    league_alias = {_norm(k): v for k, v in LEAGUE_ALIASES.get(slug, {}).items()}

    def resolve(jfa_name: str):
        n = _norm(jfa_name)
        c = _core(jfa_name)
        # リーグ限定の読み替えを最優先（全体の読み替えより強い）
        if n in league_alias:
            return league_alias[n]
        if c in league_alias:
            return league_alias[c]
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
def _fetch(url: str) -> str:
    """本文を文字列で返す。失敗したら例外（呼び出し側で [要確認] にする）。"""
    last = None
    for _ in range(RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:   # 通信エラー・404・タイムアウト すべてここ
            last = e
    raise RuntimeError(f"{url} の取得に失敗 ({last})")


def fetch_json(url: str):
    return json.loads(_fetch(url))


# ============================================================
# URL組み立て
# ============================================================
def urls_of(cfg: dict) -> dict:
    """リーグ定義から実際に叩くURLを組み立てる"""
    if "side" in cfg:      # プレミア
        base = _PREMIER_MATCH.format(season=SEASON, side=cfg["side"])
        return {"base": base,
                "schedule": base + "schedule.json",
                "fight": base + "fight.json",
                "page": _PREMIER_PAGE.format(season=SEASON, side=cfg["side"])}
    root = _PRINCE_BASE.format(code=cfg["code"], season=SEASON)
    page = _PRINCE_PAGE.format(season=SEASON, region=cfg["region"])
    if cfg["fmt"] == "html":   # 東北
        base = root + cfg["dir"] + "/"
        return {"base": base,
                "schedule": base + "schedule.html",
                "fight": base + "ranking.html",
                "page": page}
    base = root + (cfg["div"] + "/" if cfg.get("div") else "") + "match/"
    return {"base": base,
            "schedule": base + "schedule.json",
            "fight": base + "fight.json",
            "page": page}


# ============================================================
# 出典ごとの読み取り（どちらも同じ形の中間データを返す）
#   matches:   [{md, date, kickoff, venue, report, home, away, hs, as, played,
#                homeScorer[], awayScorer[]}]   home/away は**JFAの表記**
#   standings: [{rank, name, pts, games, win, tie, lost, gf, ga}]  name も**JFAの表記**
# ============================================================
def _md_of(text) -> int | None:
    """ '第12節' -> 12 """
    m = re.search(r"(\d+)", str(text or ""))
    return int(m.group(1)) if m else None


def _iso_date(raw: str) -> str:
    """ '2026/09/05' -> '2026-09-05' 。読めなければ空文字。"""
    m = re.match(r"^\s*(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", str(raw or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def read_json_source(u: dict) -> dict:
    """プレミア・プリンス（東北以外）の schedule.json / fight.json を読む"""
    schedule_raw = fetch_json(u["schedule"])
    fight_raw = fetch_json(u["fight"])
    matches_raw = schedule_raw["matchScheduleList"]["matchSchedule"]
    standing_raw = fight_raw["competitionStanding"]["team"]

    matches = []
    for m in matches_raw:
        score = m.get("score") or {}
        hs = str(score.get("homeScore", "")).strip()
        as_ = str(score.get("awayScore", "")).strip()
        # 「試合中」は途中経過が入るので消化扱いにしない（"試合終了" のみ消化）
        played = (m.get("matchStatus") == "試合終了" and hs.isdigit() and as_.isdigit())
        scorer = m.get("scorer") or {}
        matches.append({
            "md": _md_of(m.get("matchTypeName")),
            "date": _iso_date(m.get("matchDate")),
            "kickoff": str(m.get("matchTime") or "").strip(),
            "venue": str(m.get("venueFullName") or m.get("venue") or "").strip(),
            "report": str(m.get("officialReportURL") or "").strip(),
            "home": m.get("homeTeamName", ""),
            "away": m.get("awayTeamName", ""),
            "hs": int(hs) if played else None,
            "as": int(as_) if played else None,
            "played": played,
            "homeScorer": list(scorer.get("homeScorer") or []),
            "awayScorer": list(scorer.get("awayScorer") or []),
        })

    standings = []
    for t in standing_raw:
        # プリンスの順位表は teamName を持たず teamAbbreviatedName だけのことがある
        standings.append({
            "rank": t.get("rank"),
            "name": t.get("teamName") or t.get("teamAbbreviatedName"),
            "pts": t.get("winPoint"), "games": t.get("games"), "win": t.get("win"),
            "tie": t.get("tie"), "lost": t.get("lost"),
            "gf": t.get("getScorePoint"), "ga": t.get("lostScorePoint"),
        })
    return {"matches": matches, "standings": standings}


def read_tohoku_html(u: dict) -> dict:
    """プリンス東北の静的HTMLを読む（JSONが無い唯一のリーグ）

    日程表は「第N節」見出しごとに1テーブル。1行＝
      No / 日程・時間 / 会場 / ホーム(県) / スコア / アウェイ(県) / 試合状況
    日付は `26/ 09/06(日) 11:00` 形式（年は2桁・時刻は同じセル）。未消化のスコアは `-`。
    順位表は 順位 / チーム名(県) / 勝点 / 試合数 / 勝利 / 引分 / 敗戦 / 得点 / 失点 / 得失点差。
    """
    soup = BeautifulSoup(_fetch(u["schedule"]), "html.parser")
    matches = []
    for table in soup.find_all("table"):
        head = table.find_previous(string=re.compile(r"第\s*\d+\s*節"))
        md = _md_of(head) if head else None
        if md is None:
            continue
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) < 6 or not cells[0].strip().isdigit():
                continue   # ヘッダー行などを飛ばす
            dt, venue, home, score, away = cells[1], cells[2], cells[3], cells[4], cells[5]
            dm = re.search(r"(\d{2})/\s*(\d{1,2})/(\d{1,2})", dt)
            date_s = (f"20{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
                      if dm else "")
            tm = re.search(r"(\d{1,2}):(\d{2})", dt)
            kickoff = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else ""
            sm = re.match(r"^\s*(\d+)\s*[-ー－]\s*(\d+)\s*$", score)
            matches.append({
                "md": md, "date": date_s, "kickoff": kickoff, "venue": venue,
                "report": "", "home": home, "away": away,
                "hs": int(sm.group(1)) if sm else None,
                "as": int(sm.group(2)) if sm else None,
                "played": bool(sm),
                "homeScorer": [], "awayScorer": [],
            })

    rank_soup = BeautifulSoup(_fetch(u["fight"]), "html.parser")
    standings = []
    for table in rank_soup.find_all("table"):
        for tr in table.find_all("tr"):
            c = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
            if len(c) < 10 or not c[0].strip().isdigit():
                continue
            standings.append({"rank": c[0], "name": c[1], "pts": c[2], "games": c[3],
                              "win": c[4], "tie": c[5], "lost": c[6],
                              "gf": c[7], "ga": c[8]})
        if standings:
            break
    return {"matches": matches, "standings": standings}


# ============================================================
# 共通処理（名寄せ・検算・出力データの組み立て）
# ============================================================
def _split_scorer(line: str) -> dict | None:
    """ '45+1分 立石 陽向' -> {'minute': '45+1', 'name': '立石 陽向'}
        '12分 オウンゴール' -> {'minute': '12', 'name': 'オウンゴール', 'ownGoal': True}
    形式が違う行は None（集計に混ぜない）。プレミアの表記だけを対象にしている。
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
    update_cross_tables.py の同名関数と同じ考え方。
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


def _as_int(v):
    """'27' や '+14' を int に。読めなければ None。"""
    s = str(v if v is not None else "").strip().lstrip("+")
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def parse_league(cfg: dict, existing: dict) -> tuple[dict | None, str]:
    """1リーグ分を取得・解析・検算する。
    戻り値: (結果dict, メッセージ)。検算に落ちたら (None, 理由)。
    """
    slug = cfg["slug"]
    u = urls_of(cfg)
    try:
        raw = read_tohoku_html(u) if cfg["fmt"] == "html" else read_json_source(u)
    except (KeyError, TypeError) as e:
        return None, f"[要確認] {slug}: JFA公式データの構造が変わっている ({e})"
    except Exception as e:
        return None, f"[要確認] {slug}: JFA公式データを取得できない ({e})"

    src_matches, src_standings = raw["matches"], raw["standings"]
    site_names = [t.get("name", "") for t in existing.get("teams", []) if t.get("name")]
    n_teams = len(site_names)
    if n_teams == 0:
        return None, f"[要確認] {slug}: 既存JSONに teams が無い"
    if len(src_standings) != n_teams:
        return None, (f"[要確認] {slug}: 順位表が{len(src_standings)}チーム"
                      f"（既存JSONは{n_teams}チーム）")

    # --- 名寄せ ---
    resolve = _build_resolver(site_names, slug)
    jfa_names = {s["name"] for s in src_standings}
    for m in src_matches:
        jfa_names.add(m["home"])
        jfa_names.add(m["away"])
    name_map, unknown = {}, []
    for j in sorted(n for n in jfa_names if n):
        hit = resolve(j)
        if hit is None:
            unknown.append(j)
        else:
            name_map[j] = hit
    if unknown:
        return None, f"[要確認] {slug}: 名寄せできないチーム名 {unknown[:4]}（据え置き）"
    if len(set(name_map.values())) != n_teams:
        return None, (f"[要確認] {slug}: チーム名が1対1で対応しない"
                      f"（{len(set(name_map.values()))}/{n_teams}・据え置き）")

    # --- 試合一覧を組み立てる ---
    # [2026-09-06] 出典の値が空のときは既存の値を残す。
    # 「未消化試合は毎回出典で上書きする」原則と矛盾しない（空は値ではない）。
    # 実例: 北信越2部 第13節の2試合は koko が日付を持っているのに JFA が空欄。
    #       素直に上書きすると日付が消えて情報が減るので、既存を温存する。
    prev_by_key: dict = {}
    for m in existing.get("matches", []):
        prev_by_key.setdefault((m.get("md"), m.get("home"), m.get("away")), []).append(m)

    def _keep(rec_key, field):
        """既存の同じ試合が持っている値（無ければ空文字）"""
        cands = prev_by_key.get(rec_key)
        return str((cands[0].get(field) or "")).strip() if cands else ""

    want_scorers = bool(cfg.get("scorers"))
    out_matches = []
    for m in src_matches:
        if m["md"] is None:
            return None, f"[要確認] {slug}: 節番号が読めない試合がある"
        key = (m["md"], name_map[m["home"]], name_map[m["away"]])
        rec = {
            "md": m["md"],
            # 出典の日付が空なら既存の日付を残す（情報を減らさない）
            "date": m["date"] or _keep(key, "date"),
            "home": name_map[m["home"]],
            "hs": m["hs"] if m["played"] else None,
            "as": m["as"] if m["played"] else None,
            "away": name_map[m["away"]],
            "status": "played" if m["played"] else "scheduled",
        }
        # 会場・キックオフ時刻・公式記録PDF
        # （県リーグのJSONには無いフィールド。表示側は存在チェックしてから描くこと）
        # ここも出典が空なら既存の値を残す。
        venue = m["venue"] or _keep(key, "venue")
        if venue:
            rec["venue"] = venue
        kickoff = m["kickoff"] or _keep(key, "kickoff")
        if kickoff:
            rec["kickoff"] = kickoff
        report = urljoin(u["base"], m["report"]) if m["report"] else _keep(key, "reportUrl")
        if report:
            rec["reportUrl"] = report
        # 得点者はプレミアだけ。プリンスは表記も網羅範囲も違うので取り込まない
        if want_scorers and m["played"]:
            rec["homeScorers"] = [x for x in (_split_scorer(s) for s in m["homeScorer"]) if x]
            rec["awayScorers"] = [x for x in (_split_scorer(s) for s in m["awayScorer"]) if x]
        out_matches.append(rec)

    out_matches.sort(key=lambda r: (r["md"], r["date"], r["home"]))

    # --- 消化試合から順位を組み立て直す（検算その1） ---
    calc = {n: dict(pts=0, played=0, won=0, drawn=0, lost=0, gf=0, ga=0)
            for n in set(name_map.values())}
    goals = collections.Counter()
    own_goals = collections.Counter()
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
    for t in src_standings:
        name = name_map[t["name"]]
        vals = {k: _as_int(t[k]) for k in
                ("rank", "pts", "games", "win", "tie", "lost", "gf", "ga")}
        if any(v is None for v in vals.values()):
            return None, f"[要確認] {slug}: 順位表の数値が読めない（{t['name']}）"
        official[name] = dict(rank=vals["rank"], pts=vals["pts"], played=vals["games"],
                              won=vals["win"], drawn=vals["tie"], lost=vals["lost"],
                              gf=vals["gf"], ga=vals["ga"])

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

    out_standings = []
    for name, o in sorted(official.items(), key=lambda kv: kv[1]["rank"]):
        out_standings.append(dict(rank=o["rank"], team=name, pts=o["pts"],
                                  played=o["played"], won=o["won"], drawn=o["drawn"],
                                  lost=o["lost"], gf=o["gf"], ga=o["ga"],
                                  gd=o["gf"] - o["ga"]))

    # --- 得点ランキング（プレミアのみ・検算その4: 選手の得点合計＋OG＝GF） ---
    ranked, coverage = [], []
    if want_scorers:
        short_by_name = {t.get("name", ""): (t.get("short") or t.get("name", ""))
                         for t in existing.get("teams", [])}
        for name, o in official.items():
            counted = sum(v for (t, _), v in goals.items() if t == name) + own_goals[name]
            if counted != o["gf"]:
                coverage.append({"team": short_by_name.get(name, name),
                                 "missing": o["gf"] - counted})
        items = sorted(goals.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
        prev_goals, rank = None, 0
        for i, ((team, player), g) in enumerate(items, 1):
            if g != prev_goals:
                rank, prev_goals = i, g
            if g < SCORER_MIN_GOALS:
                continue
            ranked.append({"rank": rank, "name": player,
                           "team": short_by_name.get(team, team), "goals": g})

    # --- 既存データとの差分件数（ドライラン表示用） ---
    def _key(m):
        return (m.get("md"), m.get("home"), m.get("away"))

    old_by_key: dict = {}
    for m in existing.get("matches", []):
        old_by_key.setdefault(_key(m), []).append(m)
    changed = 0
    for r in out_matches:
        cands = old_by_key.get(_key(r))
        if not cands:
            changed += 1
            continue
        o = cands.pop(0)
        if any(o.get(f) != r.get(f) for f in ("date", "hs", "as", "status")):
            changed += 1

    return {
        "slug": slug,
        "cfg": cfg,
        "matches": out_matches,
        "standings": out_standings,
        "scorers": ranked,
        "coverage": coverage,
        "asof": last_played_date,
        "played": new_played,
        "curPlayed": cur_played,
        "teams": n_teams,
        "changed": changed,
        "page": u["page"],
        "nameMap": name_map,
        "dateWarnings": date_change_warnings(existing.get("matches"), out_matches),
    }, f"[OK] {slug}: 消化{new_played}試合（検算すべて一致）"


# ============================================================
# 書き出し
# ============================================================
def write_league_matches(res: dict, existing: dict) -> None:
    """data/league_matches/<slug>.json を更新する。
    league / teams は既存の設定をそのまま残す（表示側を触らずに済ませるため）。
    """
    data = dict(existing)
    data["season"] = SEASON
    data["source"] = res["page"]
    # 戦績表（星取り表）の「出典: ○○」に出る名前。cross_table.py が読む既存の仕組み。
    data["sourceName"] = "JFA公式"
    data["lastUpdated"] = date.today().isoformat()
    data["matches"] = res["matches"]
    data["official_standings"] = res["standings"]
    order = ["league", "season", "source", "sourceName", "lastUpdated", "teams",
             "official_standings", "matches"]
    ordered = {k: data[k] for k in order if k in data}
    for k, v in data.items():
        ordered.setdefault(k, v)
    path = MATCH_DIR / f"{res['slug']}.json"
    # 既存ファイルに合わせて末尾に改行は付けない（無用な差分を出さないため）
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def write_scorers(res: dict, league_label: str) -> None:
    """data/scorers/<slug>.json を更新する（**プレミアだけ**呼ばれる）"""
    note = (f"{SCORER_MIN_GOALS}得点以上の選手を掲載。"
            "JFA公式の試合記録に載っている得点者を全試合ぶん集計したもの。"
            "オウンゴールは個人の得点に数えていません。")
    out = {
        "league": f"{league_label} 得点ランキング",
        "season": SEASON,
        "source": res["page"],
        "sourceLabel": "JFA公式",
        "lastUpdated": date.today().isoformat(),
        "asof": res["asof"],
        "note": note,
        "scorers": res["scorers"],
        "coverage": res["coverage"],
    }
    (SCORER_DIR / f"{res['slug']}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _scan_teams_json(teams_data: dict, matcher):
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
      1. JFA公式の表記との完全一致
      2. 当サイトの戦績表での表記との完全一致
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


def teams_json_problems(teams_data: dict, res: dict) -> list[str]:
    """teams.json 側で名寄せできないチームを洗い出す（書き込みはしない）"""
    jfa_by_site = {v: k for k, v in res["nameMap"].items()}
    problems = []
    for row in res["standings"]:
        if not _find_team_entry(teams_data, row["team"], jfa_by_site.get(row["team"], "")):
            problems.append(f'{res["slug"]}: teams.json に「{row["team"]}」が1件に絞れない')
    return problems


def update_teams_json(results: list[dict]) -> tuple[bool, list[str]]:
    """data/teams.json の該当チームの成績を更新する。
    1チームでも見つからなければ **1件も書かずに** False を返す（中途半端に書かない）。
    """
    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    plan, problems = [], []
    for res in results:
        jfa_by_site = {v: k for k, v in res["nameMap"].items()}
        for row in res["standings"]:
            found = _find_team_entry(teams_data, row["team"],
                                     jfa_by_site.get(row["team"], ""))
            if not found:
                problems.append(
                    f'{res["slug"]}: teams.json に「{row["team"]}」が1件に絞れない')
                continue
            plan.append((found[1], row, res["cfg"].get("league")))
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
        team["leagueRank"] = row["rank"]
        # league はプレミアだけ設定する。プリンスは既存の表記
        #（「プリンスリーグ関東1部」等）を尊重して触らない。
        if league_name:
            team["league"] = league_name

    # 県内順位（rank / prefectureRank）と leagueRank の振り直しは、この直後に走る
    # update.py・cleanup_aliases.py が従来どおり担当する。ここでやると
    # 無関係な県のチームまで並び替わって差分が読めなくなるため触らない。
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


def jfa_updated_prince_regions() -> set[str]:
    """その地域のプリンス全部門がJFAで更新できた地域キーの集合。
    update.py はプリンスを地域単位で処理するので、全部門そろったときだけスキップする。"""
    ok = jfa_updated_slugs()
    return {r for r, slugs in PRINCE_REGION_SLUGS.items() if ok.issuperset(slugs)}


# ============================================================
# メイン
# ============================================================
def _print_dry_run_table(rows: list[dict]) -> None:
    print()
    print("=" * 104)
    print("ドライラン結果（ファイルは1バイトも書いていません）")
    print("=" * 104)
    print(f"{'リーグ':<22s}{'取得':>4s}{'チーム':>7s}{'消化(JFA)':>11s}{'既存':>6s}"
          f"{'名寄せ不能':>12s}{'差分':>6s}  判定")
    print("-" * 104)
    for r in rows:
        print(f"{r['slug']:<22s}{r['fetch']:>4s}{r['teams']:>7s}{r['played']:>11s}"
              f"{r['cur']:>6s}{r['unmapped']:>12s}{r['changed']:>6s}  {r['verdict']}")
    print("-" * 104)
    ok = [r for r in rows if r["verdict"].startswith("投入可")]
    print(f"投入可 {len(ok)} / {len(rows)} リーグ")


def run(dry_run: bool = False, only: set | None = None) -> list[str]:
    """全リーグを処理し、成功したslugのリストを返す"""
    print(f"=== JFA公式データ取得 ({SEASON}) ===")
    targets = [c for c in LEAGUES if not only or c["slug"] in only]
    results, rows = [], []

    for cfg in targets:
        slug = cfg["slug"]
        path = MATCH_DIR / f"{slug}.json"
        if not path.exists():
            print(f"  [skip] {slug}: {path} が無い")
            continue
        existing = json.loads(path.read_text(encoding="utf-8"))
        res, msg = parse_league(cfg, existing)
        print("  " + msg)

        row = {"slug": slug, "fetch": "×", "teams": "-", "played": "-", "cur": "-",
               "unmapped": "-", "changed": "-",
               "verdict": msg.split(":", 1)[-1].strip()}
        if res:
            results.append((res, existing))
            row.update(fetch="○", teams=str(res["teams"]), played=str(res["played"]),
                       cur=str(res["curPlayed"]), unmapped="0",
                       changed=str(res["changed"]), verdict="投入可")
        rows.append(row)

    # teams.json 側の名寄せも先に検査する（本番は1チームでも欠けたら全部書かない）
    if results:
        teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
        blocked_slugs = set()
        for res, _ in results:
            probs = teams_json_problems(teams_data, res)
            if not probs:
                continue
            blocked_slugs.add(res["slug"])
            for row in rows:
                if row["slug"] == res["slug"]:
                    row["unmapped"] = f"teams {len(probs)}"
                    row["verdict"] = "投入不可（teams.json名寄せ）"
            for p in probs[:5]:
                print(f"  [要確認] {p}")
        results = [(r, e) for r, e in results if r["slug"] not in blocked_slugs]

    if dry_run:
        _print_dry_run_table(rows)
        print("\n[DRY RUN] 書き込みはしていません。")
        return []

    if not results:
        print("\n更新0件。既存データはそのまま（koko側の処理に任せます）。")
        return []

    ok, problems = update_teams_json([r for r, _ in results])
    if not ok:
        for p in problems:
            print(f"  [要確認] {p}")
        print("\ndata/teams.json は更新しませんでした（既存維持）。書き込みを中止します。")
        return []
    print(f"  ✓ data/teams.json を更新（{sum(r['teams'] for r, _ in results)}チーム）")

    ok_slugs = []
    for res, existing in results:
        write_league_matches(res, existing)
        if res["cfg"].get("scorers"):
            write_scorers(res, existing.get("league", res["slug"]))
            print(f"  ✓ data/league_matches/{res['slug']}.json / "
                  f"data/scorers/{res['slug']}.json を更新")
        else:
            print(f"  ✓ data/league_matches/{res['slug']}.json を更新"
                  f"（得点ランキングは触らない）")
        ok_slugs.append(res["slug"])
        for w in res.get("dateWarnings", []):
            print(f"  [要確認] {res['slug']}: {w}")

    write_status(ok_slugs)
    print(f"\n✅ 完了: {len(ok_slugs)} リーグをJFA公式から更新しました")
    return ok_slugs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="プレミア2＋プリンス13リーグをJFA公式から更新する")
    parser.add_argument("--dry-run", action="store_true",
                        help="取得・検算だけして書き込まない（結果を表で出す）")
    parser.add_argument("--only", default="",
                        help="対象リーグをカンマ区切りで指定（例: prince-tohoku,prince-tokai）")
    args = parser.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    run(dry_run=args.dry_run, only=only)
    return 0  # 更新0件でも異常ではないので常に0


if __name__ == "__main__":
    sys.exit(main())
