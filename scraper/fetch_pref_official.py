#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
県1部を「県サッカー協会 公式」から更新する
==============================================
2026-09-06 新設。

なぜ作ったか
------------
県1部のこれまでの出典 junior-soccer.jp は **GitHub Actions から403で弾かれる**ように
なり（Cloudflareが送信元IPで遮断）、2026-07-15以降ずっと自動更新が止まっていた。
調べたところ **一部の県は県協会の公式システムにデータがあり、定形URLの素のHTMLで取れる**。
対象は増えていくので、**実数は下の PREF_OFFICIAL を数えること**（2026-09-07時点で14県）。

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
from jst import today as _jst_today
import fetch_status
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
# 対象の県。**件数は増える。文章中の県数より、この表の実数が正**（2026-09-07時点で14県）。
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
    # 2026-09-07 追加の5県。ここも県ごとの独自システムで、共通化していない。
    "tokyo":     {"platform": "tokyo", "dt": "1", "ltno": "16",
                  "source": f"https://www.tleague-u18.com/schedule.php"
                            f"?dy={SEASON_YEAR}&dt=1&ltno=16",
                  "label": "東京都U-18サッカーリーグ 公式"},
    # ⚠️ 神奈川は610KBのページで504が頻発する。この県だけリトライを長くする
    #    （全県で増やすと他県の小さなサーバに無用な負荷がかかる）。
    "kanagawa":  {"platform": "kanagawa",
                  "base": f"https://www.kanagawa-fa.gr.jp/cms/u18-league/{SEASON_YEAR}/div1/",
                  "source": f"https://www.kanagawa-fa.gr.jp/cms/u18-league/{SEASON_YEAR}/div1/",
                  "label": "神奈川県サッカー協会 公式（2種大会部会）",
                  "retries": 6, "retry_wait": 5.0},
    "toyama":    {"platform": "toyama", "tid": "82",
                  "source": "https://www.taikai-go.com/tournaments/82/schedule",
                  "label": "富山県サッカー協会 公式（大会GO）"},
    "kumamoto":  {"platform": "kumamoto", "id": "1006",
                  "source": "https://kumamoto-fa.net/league/competition/gamelist/?id=1006",
                  "label": "熊本県サッカー協会 公式"},
    # 星取表が勝点・得点・失点・順位しか持たない（勝分敗が無い）ため専用ゲート。
    "okinawa":   {"platform": "okinawa", "tid": "161",
                  "source": "http://www.okinawa-soccer-habu.com/scores/table/161",
                  "label": "沖縄県サッカー協会 公式（波布リーグ）",
                  "standings_gate": "okinawa"},
                  # ✅ known_bad_existing は 2026-09-07 の移行完了後に削除済み。
                  #    junior-soccer が 2026-04-29「那覇西 vs 那覇」を 1-2（那覇の勝ち）と
                  #    していたが公式は 1-1（引分）で、これ1件で「那覇は試合が増えるのに
                  #    勝点が減る」が説明できた。移行で公式値に置き換わったため、
                  #    設定を残すと毎回「known_bad に書いた試合が見つからない」で
                  #    verify_failed になり、3日続けば赤①が鳴る。設計どおりの後始末。

    # 2026-09-07 追加の2県。どちらも**枠を作り直す**（double_round）。
    # 1回戦制の枠のまま止まっていたため、島根は「完了」と誤認されて見張りも黙っていた。
    "shimane":   {"platform": "shimane",
                  "url": "https://www.sportsonline.jp/reportv2/PublisherFull/"
                         "viewdata.aspx?parentid=RX%5ER%5B&rallyid=U%5EYQ%5E",
                  "source": "https://www.sportsonline.jp/reportv2/PublisherFull/"
                            "viewdata.aspx?parentid=RX%5ER%5B&rallyid=U%5EYQ%5E",
                  "label": "島根県サッカー協会 公式（SportsOnline）",
                  "double_round": True},
    "okayama":   {"platform": "okayama",
                  "entry": "http://okayama-fa.or.jp/2022/2-2",
                  "heading": "高円宮杯 JFA U-18 サッカーリーグ OKAYAMA",
                  "source": "http://okayama-fa.or.jp/2022/2-2",
                  "label": "岡山県サッカー協会 公式",
                  "double_round": True,
                  # 公式順位表が存在しないので、順位表は試合から自前計算して代替ゲートで守る
                  "standings_gate": "self"},
                  # ✅ known_bad_existing は 2026-09-07 の移行完了後に削除済み。
                  #    junior-soccer が 2026-04-12「創志学園 vs 倉敷古城池」を 1-0 と
                  #    していたが公式PDFは 0-1（勝敗が逆）。
                  #    ⚠️ この型（スコア反転）は検算では絶対に検出できない。両チームの勝点が
                  #       3ずつ入れ替わるだけで、リーグ全体の合計勝点が変わらないため。
                  #    移行で公式値に置き換わったため設定を削除（残すと毎回 verify_failed）。

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
    # 2026-09-06に当時の9県ぶんを実測し、norm() で寄らなかった7件だけを登録した。
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
    # 東京は10チームすべて公式表記＝既存JSONの表記なのでALIAS不要
    "kanagawa": {
        # 公式は正式名称＋全角Ａ/Ｂ。既存JSONは略称＋半角A/B。
        # ⚠️ 「湘南工科大附Ａ」だけ既存JSONが全角Ａ。既存の表記を勝手に揃えない。
        "湘南ベルマーレU-18･Ａ": "湘南ベルマーレA",
        "東海大学付属相模高校Ａ": "東海大相模A",
        "桐光学園高校Ｂ": "桐光学園B",
        "横浜創英高校Ａ": "横浜創英A",
        "法政大学第二高校Ａ": "法政二A",
        "湘南工科大学附属高校Ａ": "湘南工科大附Ａ",
        "桐蔭学園高校Ｂ": "桐蔭学園B",
        "川崎市立橘高校Ａ": "川崎橘A",
        "日本大学藤沢高校Ｂ": "日大藤沢B",
        "相洋高校Ａ": "相洋A",
    },
    "toyama": {
        "富一2nd": "富山第一2nd",
    },
    "kumamoto": {
        # 試合表側の表記から寄せる（順位表の正式名称は名寄せに使わない）
        "熊本商業高校": "熊本商業",
    },
    "okinawa": {
        "沖縄SV Ｕ-18": "沖縄SV",
        "FC琉球OKINAWA U-18 2nd": "FC琉球OKINAWA 2nd",
    },
    # 島根は norm() が全角Ｂ→半角B を吸収するので ALIAS 不要（全単射を実測で確認）
    "okayama": {
        # PDFは略称。全角空白は読み取り側で除去済み。
        "学芸館B": "岡山学芸館B",
        "ファジB": "ファジ岡山U-18B",
        "光南B": "玉野光南B",
        "古城池": "倉敷古城池",
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
def fetch_html(url: str, encoding: str | None = None,
               retries: int = RETRIES, wait: float = SLEEP,
               timeout: int = TIMEOUT, must_contain: str = "") -> str:
    """HTMLを取得する。

    encoding      … その文字コードで読む。出典が Content-Type に charset を
                    書いていないとき必須（書かないと requests が ISO-8859-1 を
                    仮定し、**例外を出さずに静かに文字化けする**。宮崎・沖縄がこれ）
    retries/wait  … 県ごとに変える。神奈川は610KBのページで504が頻発するため
                    長めにする。**全県のリトライを増やすと他県の小さなサーバに
                    無用な負荷がかかる**ので、必要な県だけに効かせること
    must_contain  … デコード結果にこの文字列が無ければ失敗扱いにする。
                    文字化けを黙って通さないためのガード
    """
    last = None
    for _ in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = encoding or resp.apparent_encoding or "utf-8"
            text = resp.text
            if must_contain and must_contain not in text:
                raise RuntimeError(f"期待した文字列 {must_contain!r} が無い"
                                   f"（文字コードの取り違えの可能性）")
            return text
        except Exception as e:
            last = e
            time.sleep(wait)
    raise RuntimeError(f"{url} の取得に失敗 ({last})")


def fetch_json(url: str, retries: int = RETRIES, wait: float = SLEEP):
    """JSONを取得する。パースもリトライの中で行う
    （途中で切れたレスポンスを1回で諦めないため）。"""
    last = None
    for _ in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return json.loads(resp.text, strict=False)
        except Exception as e:
            last = e
            time.sleep(wait)
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
# ============================================================
# 東京（tleague-u18.com）— 東京都U-18サッカーリーグ公式
#   順位表 rank.php / 試合 schedule.php。どちらも素のHTML・UTF-8・table 1つ。
# ⚠️ **順位表の列は「勝・敗・引」の順**。他県によくある「勝・分・敗」ではない。
#    ここを取り違えると勝点は合うのに勝分敗だけズレる（検算をすり抜けない＝気づける）。
# ⚠️ 1行目は「<<スワイプでご覧いただけます>>」の注記。2行目がヘッダ。
#    列名で引くので、注記行が増減しても壊れない。
# 年度切り替え: URLの dy を差し替える
# ============================================================
_TOKYO_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
_TOKYO_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _tokyo_cols(header: list[str]) -> dict:
    """ヘッダ行から列の位置を決める。「引」と「勝」の取り違えを防ぐため完全一致で引く。"""
    want = {"team": ("チーム名",), "pts": ("勝点",), "played": ("試合数",),
            "won": ("勝",), "lost": ("敗",), "drawn": ("引",),
            "gf": ("得点",), "ga": ("失点",)}
    col = {}
    for i, c in enumerate(header):
        t = c.strip()
        for key, names in want.items():
            if key not in col and t in names:
                col[key] = i
    return col


def read_tokyo(cfg: dict) -> tuple[dict, list[dict]]:
    base = "https://tleague-u18.com"
    q = f"dy={SEASON_YEAR}&dt={cfg['dt']}&ltno={cfg['ltno']}"

    # --- 順位表 ---
    soup = BeautifulSoup(fetch_html(f"{base}/rank.php?{q}"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    for table in soup.find_all("table"):
        rows = _rows(table)
        head = next((r for r in rows if "勝点" in r and "チーム名" in r), None)
        if not head:
            continue
        col = _tokyo_cols(head)
        if len(col) < 8:
            continue
        for r in rows[rows.index(head) + 1:]:
            if len(r) <= max(col.values()):
                continue
            team = r[col["team"]].strip()
            vals = {k: _to_int(r[i]) for k, i in col.items() if k != "team"}
            if team and all(v is not None for v in vals.values()):
                standings[team] = vals
        if standings:
            break

    # --- 試合 ---
    soup2 = BeautifulSoup(fetch_html(f"{base}/schedule.php?{q}"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    for table in soup2.find_all("table"):
        rows = _rows(table)
        head = next((r for r in rows if "ホームチーム" in r), None)
        if not head:
            continue
        idx = {name: head.index(name) for name in
               ("節", "日時", "ホームチーム", "スコア", "アウェイチーム", "会場")
               if name in head}
        if len(idx) < 5:
            continue
        for r in rows[rows.index(head) + 1:]:
            if len(r) <= max(idx.values()):
                continue
            home = r[idx["ホームチーム"]].strip()
            away = r[idx["アウェイチーム"]].strip()
            if not home or not away:
                continue
            sc = r[idx["スコア"]].strip()
            m = re.match(r"^(\d+)\s*-\s*(\d+)$", sc)
            # 未消化はスコア欄が空。枠は generate_fixtures 側が作る。
            if not m:
                continue
            raw = r[idx["日時"]]
            # 日時未定は「--/-- :」。年は無いので SEASON_YEAR を補う。
            dm = _TOKYO_DATE_RE.search(raw)
            date = f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}" if dm else ""
            tm = _TOKYO_TIME_RE.search(raw)
            matches.append(dict(
                date=date, home=home, hs=int(m.group(1)),
                **{"as": int(m.group(2))}, away=away,
                md=_to_int(r[idx["節"]]) or 0,
                kickoff=f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "",
                venue=r[idx["会場"]].strip() if "会場" in idx else "",
            ))
        if matches:
            break
    return standings, matches


# ============================================================
# 富山（taikai-go.com「大会GO」）— 順位表と試合がJSONで取れる
#   /api/tournaments/{id}/standings … data[0].teams[] に順位表
#   /api/tournaments/{id}/results   … data[0].teams[]（id→名前）と matches[]
#   /tournaments/{id}/schedule      … 日付・時刻・会場はこのHTMLにしかない
# ⚠️ /api/tournaments/{id}/matches は 401（要認証）。使うのは results のほう。
# ⚠️ results の試合に日付が無いので、match_code（M1, M3…）をキーに schedule と join する。
# ⚠️ schedule のHTMLはレスポンシブ対応でテキストが二重に出る。textContent を
#    そのまま使わず要素単位で取ること。
# 年度切り替え: /api/tournaments/public-groups/7 で新年度のT1のIDを取る
# ============================================================
_TOYAMA_CODE_RE = re.compile(r"\bM\d+\b")
_TOYAMA_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")


def _toyama_schedule(tid: str) -> dict:
    """/schedule のHTMLから {match_code: (日付, 時刻, 会場)} を作る。

    行の中に M番号 と 日付が両方あるものだけを拾う。二重テキスト対策として、
    同じ match_code が複数回出てきたら最初の1件だけを採用する。
    """
    soup = BeautifulSoup(fetch_html(f"https://www.taikai-go.com/tournaments/{tid}/schedule"),
                         "html.parser")
    time.sleep(SLEEP)
    out = {}
    cur_date = ""
    for el in soup.find_all(["tr", "li", "div", "section", "article"]):
        # 子要素を持たない末端に近いものだけ見る（親を見ると全文が入る）
        txt = el.get_text(" ", strip=True)
        if len(txt) > 200:
            continue
        dm = _TOYAMA_DATE_RE.search(txt)
        if dm and not _TOYAMA_CODE_RE.search(txt):
            cur_date = f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
            continue
        cm = _TOYAMA_CODE_RE.search(txt)
        if not cm:
            continue
        code = cm.group(0)
        if code in out:
            continue
        date = cur_date
        if dm:
            date = f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
        tm = re.search(r"(\d{1,2}):(\d{2})", txt)
        out[code] = (date, f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "")
    return out


def read_toyama(cfg: dict) -> tuple[dict, list[dict]]:
    tid = cfg["tid"]
    api = "https://www.taikai-go.com/api/tournaments"

    st = fetch_json(f"{api}/{tid}/standings")
    time.sleep(SLEEP)
    standings = {}
    for blk in (st.get("data") or []):
        for t in (blk.get("teams") or []):
            name = (t.get("team_name") or "").strip()
            if not name:
                continue
            standings[name] = dict(
                pts=t.get("points"), played=t.get("matches_played"),
                won=t.get("wins"), drawn=t.get("draws"), lost=t.get("losses"),
                gf=t.get("goals_for"), ga=t.get("goals_against"))

    res = fetch_json(f"{api}/{tid}/results")
    time.sleep(SLEEP)
    sched = _toyama_schedule(tid)
    matches = []
    for blk in (res.get("data") or []):
        id2name = {t.get("team_id"): (t.get("team_name") or "").strip()
                   for t in (blk.get("teams") or [])}
        for m in (blk.get("matches") or []):
            # completed だけを消化として扱う。scheduled の枠は generate_fixtures が作る。
            if m.get("match_status") != "completed":
                continue
            home = id2name.get(m.get("team1_id"), "")
            away = id2name.get(m.get("team2_id"), "")
            hs, as_ = m.get("team1_goals"), m.get("team2_goals")
            if not home or not away or hs is None or as_ is None:
                continue
            date, kick = sched.get(m.get("match_code") or "", ("", ""))
            matches.append(dict(date=date, home=home, hs=int(hs),
                                **{"as": int(as_)}, away=away, kickoff=kick))
    return standings, matches


# ============================================================
# 熊本（kumamoto-fa.net）— 県協会のリーグシステム。得点者まで公開している
#   試合 gamelist/?id= … table 1つ・182行＝ヘッダ2＋90試合×2行
#     ホーム行(12セル): 編集|節|対戦日時|試合会場|チーム|前半|後半|合計|得点者|アシスト|警告|退場
#     アウェイ行(8セル): チーム|前半|後半|合計|得点者|アシスト|警告|退場
#     → ホーム得点＝ホーム行[7]（合計）／アウェイ得点＝アウェイ行[3]（合計）
#   順位表 ranking/?id= … 順位|チーム名|試合|勝点|勝|分|敗|得点|失点|得失
# ⚠️ **順位表と試合表でチーム名の表記が違う**（順位表＝熊本県立熊本商業高等学校 /
#    試合表＝熊本商業高校）。JSONに入れるのは試合表側の略称にし、
#    順位表とは**順位の並び**で対応づける（process の standings は試合表の名前で作る）。
# 年度切り替え: kumamoto-fa.net/league/ の一覧から新年度の1部の id を取る
# ============================================================
_KUMAMOTO_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
_KUMAMOTO_MD_RE = re.compile(r"第\s*(\d+)\s*節")


def read_kumamoto(cfg: dict) -> tuple[dict, list[dict]]:
    tid = cfg["id"]
    base = "https://kumamoto-fa.net/league/competition"

    # --- 試合（こちらが名前の正本） ---
    soup = BeautifulSoup(fetch_html(f"{base}/gamelist/?id={tid}"), "html.parser")
    time.sleep(SLEEP)
    table = max(soup.find_all("table"), key=lambda t: len(t.find_all("tr")), default=None)
    matches, order = [], []
    if table is not None:
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        i = 0
        while i < len(rows) - 1:
            h, a = rows[i], rows[i + 1]
            if len(h) != 12 or len(a) != 8:
                i += 1
                continue
            home, away = h[4].strip(), a[0].strip()
            for n in (home, away):
                if n and n not in order:
                    order.append(n)
            hs, as_ = _to_int(h[7]), _to_int(a[3])       # 「合計」列。未消化は "-"
            if home and away and hs is not None and as_ is not None:
                dm = _KUMAMOTO_DATE_RE.search(h[2])
                tm = re.search(r"(\d{1,2}):(\d{2})", h[2])
                mm = _KUMAMOTO_MD_RE.search(h[1])
                matches.append(dict(
                    date=(f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
                          if dm else ""),
                    home=home, hs=hs, **{"as": as_}, away=away,
                    md=int(mm.group(1)) if mm else 0,
                    kickoff=f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "",
                    venue=h[3].strip()))
            i += 2

    # --- 順位表（正式名称。順位の並びで試合表の名前に対応づける） ---
    soup2 = BeautifulSoup(fetch_html(f"{base}/ranking/?id={tid}"), "html.parser")
    time.sleep(SLEEP)
    ranked = []
    for table in soup2.find_all("table"):
        rows = _rows(table)
        head = next((r for r in rows if "勝点" in r and "順位" in r), None)
        if not head:
            continue
        col = {}
        for i, c in enumerate(head):
            for key, names in (("pts", ("勝点",)), ("played", ("試合",)),
                               ("won", ("勝",)), ("drawn", ("分",)), ("lost", ("敗",)),
                               ("gf", ("得点",)), ("ga", ("失点",))):
                if key not in col and c.strip() in names:
                    col[key] = i
        if len(col) < 7:
            continue
        for r in rows[rows.index(head) + 1:]:
            if len(r) <= max(col.values()):
                continue
            rank = _to_int(r[0])
            vals = {k: _to_int(r[i]) for k, i in col.items()}
            if rank is not None and all(v is not None for v in vals.values()):
                ranked.append((rank, vals))
        if ranked:
            break
    ranked.sort(key=lambda x: x[0])

    # 公式順位表（正式名称）を、試合表の名前（略称）に載せ替える。
    # ⚠️ 「順位の並びで対応づける」方式は、公式と当方で同着の並べ方が違うと
    #    静かにズレる。ここでは**成績(勝点・試合数・得失点)の完全一致**で
    #    対応づけ、1対1にならなければ空を返して据え置きにする（fail closed）。
    standings = {}
    if ranked and order:
        mine = standings_from_matches(matches, order)
        used = set()
        for _, vals in ranked:
            hit = [t for t in order
                   if t not in used
                   and mine[t]["pts"] == vals["pts"]
                   and mine[t]["played"] == vals["played"]
                   and mine[t]["gf"] == vals["gf"]
                   and mine[t]["ga"] == vals["ga"]]
            if len(hit) != 1:
                print(f"       [要確認] 熊本: 公式順位表の行 {vals} に対応する"
                      f"チームが{len(hit)}件（1件でない）。据え置きます。")
                return {}, matches
            standings[hit[0]] = vals
            used.add(hit[0])
    return standings, matches


# ============================================================
# 神奈川（kanagawa-fa.gr.jp）— 県協会2種大会部会。WordPress + AnWP Football Leagues
#   試合 /div1/       … **<table> ではない**。div.anwp-fl-game が90個
#   順位表 /div1/group-1/ … これも div。.standing-table の直下に
#                          ヘッダ10個 → 各チーム10個 が平らに並ぶ
# ⚠️ **610KBのページで504が頻発する**（実測：初回504・2回目200）。
#    この県だけリトライ回数と待ち時間を長くしている。
# ⚠️ 日付は **data-fl-game-kickoff（ISO8601・JST付き）が正本**。
#    画面の日本語表記をパースしないこと。
# ⚠️ 順位表のデータセルは意味クラス（standing-table__won 等）を持っているが、
#    **ヘッダの並びから列の意味を決めて位置で拾う**ようにしている。
#    プラグインの版が変わってクラスが落ちても壊れないため。
# 年度切り替え: パスの 2026 を差し替える
# ============================================================
_KANAGAWA_HEAD = {"勝点": "pts", "試合": "played", "勝": "won", "分": "drawn",
                  "敗": "lost", "得": "gf", "失": "ga", "差": "gd"}


def read_kanagawa(cfg: dict) -> tuple[dict, list[dict]]:
    base = cfg["base"]
    rt, wt = cfg.get("retries", RETRIES), cfg.get("retry_wait", SLEEP)

    # --- 順位表 ---
    soup = BeautifulSoup(fetch_html(f"{base}group-1/", retries=rt, wait=wt,
                                    timeout=90, must_contain="Club"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    tbl = soup.select_one(".standing-table")
    if tbl is not None:
        cells = [c for c in tbl.find_all(recursive=False)]
        texts = [c.get_text(" ", strip=True) for c in cells]
        # ヘッダは「# Club 勝点 試合 …」。Club の次から数値列が始まる。
        try:
            club_i = texts.index("Club")
        except ValueError:
            club_i = -1
        if club_i >= 0:
            order = []                      # 数値列の意味を左から並べる
            j = club_i + 1
            while j < len(texts) and texts[j] in _KANAGAWA_HEAD:
                order.append(_KANAGAWA_HEAD[texts[j]])
                j += 1
            width = 2 + len(order)          # 順位 + チーム名 + 数値列
            for k in range(j, len(cells) - width + 1, width):
                row = cells[k:k + width]
                # チーム名セルには直近5試合の ○●△ が混ざるので a 要素から取る
                link = row[1].find("a")
                name = (link.get_text(" ", strip=True) if link
                        else row[1].get_text(" ", strip=True)).strip()
                vals = {}
                for n, key in enumerate(order):
                    vals[key] = _to_int(row[2 + n].get_text(" ", strip=True))
                vals.pop("gd", None)        # 得失差は得点-失点から出るので持たない
                if name and all(v is not None for v in vals.values()):
                    standings[name] = vals

    # --- 試合 ---
    soup2 = BeautifulSoup(fetch_html(base, retries=rt, wait=wt, timeout=90,
                                     must_contain="anwp-fl-game"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    md = 0
    for el in soup2.find_all(True):
        cls = el.get("class") or []
        if "competition__stage-title" in cls:
            m = re.search(r"(\d+)", el.get_text(" ", strip=True))
            if m:
                md = int(m.group(1))
            continue
        if "anwp-fl-game" not in cls:
            continue
        # game-status-1 が消化。枠は generate_fixtures 側が作る。
        if "game-status-1" not in cls:
            continue
        h = el.select_one(".match-slim__team-home-title")
        a = el.select_one(".match-slim__team-away-title")
        hs = el.select_one(".anwp-fl-game__scores-home")
        as_ = el.select_one(".anwp-fl-game__scores-away")
        if not (h and a and hs and as_):
            continue
        hv, av = _to_int(hs.get_text(strip=True)), _to_int(as_.get_text(strip=True))
        if hv is None or av is None:
            continue
        kick = el.get("data-fl-game-kickoff") or ""     # 2026-03-07T12:00:00+09:00
        matches.append(dict(
            date=kick[:10], home=h.get_text(" ", strip=True),
            hs=hv, **{"as": av}, away=a.get_text(" ", strip=True),
            md=md, kickoff=kick[11:16]))
    return standings, matches


# ============================================================
# 沖縄（okinawa-soccer-habu.com）— 県協会2種委員会「波布リーグ」
#   試合 /scores/table/161 … table 1つ・57行。日程と会場に rowspan がかかるので
#     行によってセル数が 8/10/11/12 と変わる。**列番号で取ってはいけない。**
#     td.all_score を基準に、2つ前=ホーム名/1つ前=ホーム得点/1つ後=アウェイ得点/
#     2つ後=アウェイ名 で取る。
#   星取表 /scores/sheet/161 … 勝ち点・得点・失点・得失差・順位
# ⚠️ **星取表のHTMLが不正**。<tr> 開始9個に対し </tr> の閉じが1個しかなく、
#    パースすると全チームが1行に潰れる（山口は逆に閉じのほうが多かった。壊れ方が違う）。
#    → セルを平らに並べ、ヘッダ幅（「順位」の位置+1＝12）で切り直す。
#    切ったあとデータ行がちょうどチーム数になることを必ず確認する。
# ⚠️ **HTTPヘッダに charset が無い**（meta は UTF-8）。明示しないと requests が
#    ISO-8859-1 を仮定して静かに文字化けする。宮崎とまったく同じ罠。
# ⚠️ 得点/失点は1セルに見えるが <span> が3つ（得点・失点・得失差）。
#    get_text() をそのまま使うと "17710" に連結される。区切りを指定して分ける。
# 得点者・警告退場も取れる（将来の県別得点ランキング用。いまは使わない）
# 年度切り替え: /scores/table/ の番号を差し替える（県協会サイトからは辿れない）
# ============================================================
_OKINAWA_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")


def read_okinawa(cfg: dict) -> tuple[dict, list[dict]]:
    base = f"http://www.okinawa-soccer-habu.com/scores"
    tid = cfg["tid"]

    # --- 星取表（順位表として使う） ---
    soup = BeautifulSoup(fetch_html(f"{base}/sheet/{tid}", encoding="utf-8",
                                    must_contain="勝ち点"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    tbl = max(soup.find_all("table"),
              key=lambda t: len(t.find_all(["td", "th"])), default=None)
    if tbl is not None:
        cells = tbl.find_all(["td", "th"])
        texts = [c.get_text("|", strip=True) for c in cells]
        if "順位" in texts:
            width = texts.index("順位") + 1
            rows = [cells[i:i + width] for i in range(width, len(cells), width)]
            rows = [r for r in rows if len(r) == width]
            for r in rows:
                name = r[0].get_text(" ", strip=True).strip()
                pts = _to_int(r[-3].get_text(strip=True))
                # 得失点セルは <span>得点</span><span>失点</span><span>差</span>
                gs = [x for x in r[-2].get_text("|", strip=True).split("|") if x != ""]
                rank = _to_int(r[-1].get_text(strip=True))
                if name and pts is not None and rank is not None and len(gs) >= 2:
                    standings[name] = dict(pts=pts, gf=_to_int(gs[0]),
                                           ga=_to_int(gs[1]), rank=rank)

    # --- 試合 ---
    soup2 = BeautifulSoup(fetch_html(f"{base}/table/{tid}", encoding="utf-8",
                                     must_contain="得点者"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    tbl2 = max(soup2.find_all("table"),
               key=lambda t: len(t.find_all("tr")), default=None)
    cur_date = ""
    if tbl2 is not None:
        for tr in tbl2.find_all("tr"):
            cs = tr.find_all(["td", "th"])
            if not cs:
                continue
            # 日程は rowspan で複数行にまたがる。現れたら以降の行に引き継ぐ。
            first = cs[0]
            if first.get("rowspan") and _OKINAWA_DATE_RE.search(first.get_text()):
                dm = _OKINAWA_DATE_RE.search(first.get_text())
                cur_date = (f"{SEASON_YEAR}-{int(dm.group(1)):02d}-"
                            f"{int(dm.group(2)):02d}")
            sc = tr.find("td", class_="all_score")
            if sc is None or sc not in cs:
                continue
            i = cs.index(sc)
            if i < 2 or i + 2 >= len(cs):
                continue
            home = cs[i - 2].get_text(" ", strip=True).strip()
            away = cs[i + 2].get_text(" ", strip=True).strip()
            hs = _to_int(cs[i - 1].get_text(strip=True))
            as_ = _to_int(cs[i + 1].get_text(strip=True))
            if not home or not away or hs is None or as_ is None:
                continue      # 未消化。枠は generate_fixtures 側が作る
            tm = re.search(r"(\d{1,2}):(\d{2})", " ".join(
                c.get_text(" ", strip=True) for c in cs[:i - 2]))
            matches.append(dict(date=cur_date, home=home, hs=hs,
                                **{"as": as_}, away=away,
                                kickoff=f"{int(tm.group(1)):02d}:{tm.group(2)}"
                                if tm else ""))
    return standings, matches


# ============================================================
# 島根（SportsOnline）— 山口・広島と同じ仕組みだが**壊れ方が違う**
#   viewdata.aspx 1本で順位表と全試合が取れる（POST・ViewState・cookie 不要）。
#   table[2] = 星取表＋順位表 … 順位|チーム名|8チーム列|勝数|負数|引分|勝点|得点|失点|得失差
#   table[3] = 全試合一覧     … 組み合わせ|開始日|開始時刻|進行状況|会場|審判|ユニフォーム
# ⚠️ **山口のパーサを流用しないこと。** 同じ SportsOnline でも壊れ方が逆で
#    （山口は `</tr>` が多い／島根は `<tr>` が多い）、表の位置も列の並びも違う。
#    「同じ仕組みだから」で共通化すると静かにズレる。
# ⚠️ 順位表のHTMLが不正で全チームが1行に潰れる（実測 tr開始122 / 閉じ130）。
#    ヘッダ幅（「得失差」の位置+1＝17）で切り直し、**行数がチーム数と一致するか必ず確認**する。
# ⚠️ 山口と違い **実際の試合日が入っている**（最新 2026/09/06）ので
#    NO_RECENT_RESULTS には入れない。
# ⚠️ **1回戦制28枠のまま「完了」と誤認されて7/15から止まっていた県**（2026-09-07判明）。
#    枠を56に作り直す（cfg の double_round）。
# 年度切り替え: parentid / rallyid を差し替える（Rally.aspx の子大会一覧から）
# ============================================================
_SHIMANE_SCORE_RE = re.compile(r"^(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)$")
_SHIMANE_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def read_shimane(cfg: dict) -> tuple[dict, list[dict]]:
    soup = BeautifulSoup(fetch_html(cfg["url"], encoding="utf-8",
                                    must_contain="得失差"), "html.parser")
    time.sleep(SLEEP)
    tables = soup.find_all("table")

    # --- 順位表（潰れた1行を列数で切り直す） ---
    standings = {}
    for table in tables:
        cells = table.find_all(["td", "th"])
        texts = [c.get_text(" ", strip=True) for c in cells]
        if "得失差" not in texts or "勝点" not in texts:
            continue
        width = texts.index("得失差") + 1
        head = texts[:width]
        col = {}
        for i, c in enumerate(head):
            for key, name in (("won", "勝数"), ("lost", "負数"), ("drawn", "引分"),
                              ("pts", "勝点"), ("gf", "得点"), ("ga", "失点")):
                if key not in col and c == name:
                    col[key] = i
        if len(col) < 6:
            continue
        rows = [texts[i:i + width] for i in range(width, len(texts), width)]
        rows = [r for r in rows if len(r) == width]
        for r in rows:
            team = r[1].strip()
            vals = {k: _to_int(r[i]) for k, i in col.items()}
            vals["played"] = sum(v for k, v in vals.items()
                                 if k in ("won", "drawn", "lost") and v is not None)
            if team and all(v is not None for v in vals.values()):
                standings[team] = vals
        if standings:
            break

    # --- 試合一覧 ---
    matches = []
    for table in tables:
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        head = next((r for r in rows if len(r) >= 4 and "組み合わせ" in r[0]), None)
        if not head:
            continue
        for r in rows[rows.index(head) + 1:]:
            # 途中に「Away」などの区切り行が入る。セル数で弾く。
            if len(r) < 4:
                continue
            if "試合終了" not in r[3]:
                continue          # 未消化。枠は generate_fixtures 側が作る
            m = _SHIMANE_SCORE_RE.match(r[0])
            if not m:
                continue
            dm = _SHIMANE_DATE_RE.search(r[1])
            matches.append(dict(
                date=(f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
                      if dm else ""),
                home=m.group(1).strip(), hs=int(m.group(2)),
                **{"as": int(m.group(3))}, away=m.group(4).strip(),
                kickoff=r[2].strip() if len(r) > 2 else "",
                venue=r[4].strip() if len(r) > 4 else ""))
        if matches:
            break
    return standings, matches


# ============================================================
# 岡山（okayama-fa.or.jp）— 県協会のテキストPDF
# ⚠️ **PDFのURLは更新のたびに変わる**（2026-09-07に1日で /2026/06/ → /2026/09/ に変わった）。
#    URLを固定で書かず、**入口ページから毎回辿る**こと。
#    同じページに `➡2026` が3つある（高校総体・OKAYAMA・チャレンジリーグ）ので、
#    **見出し「高円宮杯 JFA U-18 サッカーリーグ OKAYAMA」の直後**のリンクを取る。
# ⚠️ **1ページに県1部（左段）と県2部（右段）が並ぶ。** テキスト抽出すると1行に両方出るので、
#    **座標（extract_words）で x < 430 の左段だけを取る**。こうすると2部がそもそも入ってこない
#    （`光南B`(1部) と `光南C`(2部) の取り違えが構造的に起きない）。
#    チーム名の集合による絞り込みは保険として残す。
# ⚠️ 単語の top は1試合の中で数px ばらつく（チーム名が少し上に出る）ので、
#    許容差4pxでクラスタしてから x 順に並べる。
# ⚠️ 節と日付：**ページ末尾に一覧は無い**。各節ブロックの中の行に埋め込まれている。
#    - `1 4月4日 就実 9:00 3 ファジB 3 - 0 就 実 B 8` … 行頭に「節 月日」
#    - `2 理大 12:30 3 …` ＋ 独立行 `4月11日`        … 節2だけ番号と日付が別の行
#    - `4月12日 創志赤坂 12:30 1 …`                  … その節の既定日と違う日＝行頭日付を優先
#    試合行は**節ごとに5試合ずつ節番号の順**に並ぶので、5件ずつ区切って節番号を振る。
# ⚠️ チーム名に全角空白が入る（`光 南 B` `古 城 池`）ので除去してから名寄せする。
# ⚠️ **公式順位表は存在しない。** 順位表は試合から自前計算し、代替ゲートで守る（宮崎と同じ）。
# ✅ **版日付ガード**：PDF冒頭の版日付（`2026/9/7`）より後の日付を持つ「消化済み」試合を
#    作っていたら、日付の割り当てが壊れている。**据え置きにする。**
#    これは「取れなくなったこと」ではなく「静かに間違ったものを取り始めたこと」を捕まえる
#    仕掛けで、鮮度チェック（4-2c）では拾えない種類の事故に効く。
# 年度切り替え: 入口URLは固定。見出し直下の新年度リンクを自動で辿る
# ============================================================
_OKAYAMA_SPLIT_X = 430          # 県1部（左段）と県2部（右段）の境界
_OKAYAMA_ROW_TOL = 4            # 同じ行とみなす top の許容差(px)
_OKAYAMA_MATCH_RE = re.compile(
    r"(\d{1,2}:\d{2})\s+(\d{1,2})\s+(.+?)\s+(?:(\d+)\s*-\s*(\d+)|-)\s+(.+?)\s+(\d{1,2})\s*$")
_OKAYAMA_HEAD_MD_DATE = re.compile(r"^(\d{1,2})\s+(\d{1,2})月(\d{1,2})日")
_OKAYAMA_HEAD_DATE = re.compile(r"^(\d{1,2})月(\d{1,2})日")
_OKAYAMA_ONLY_DATE = re.compile(r"^(\d{1,2})月(\d{1,2})日$")
_OKAYAMA_VERSION_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def _okayama_pdf_url(cfg: dict) -> str:
    """入口ページから、その年度のリーグ戦PDFのURLを辿る。"""
    soup = BeautifulSoup(fetch_html(cfg["entry"], encoding="utf-8",
                                    must_contain=cfg["heading"]), "html.parser")
    time.sleep(SLEEP)
    node = soup.find(string=re.compile(re.escape(cfg["heading"])))
    if node is None:
        raise RuntimeError(f"入口ページに見出し {cfg['heading']!r} が無い")
    for a in node.parent.find_all_next("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            return a["href"]
    raise RuntimeError("見出しの後にPDFリンクが無い")


def _okayama_rows(page) -> list[str]:
    """左段（県1部）だけを、1試合＝1行の文字列にして返す。"""
    ws = [w for w in page.extract_words()
          if w["x0"] < _OKAYAMA_SPLIT_X and w["top"] > 75]
    ws.sort(key=lambda w: (w["top"], w["x0"]))
    groups, cur, base = [], [], None
    for w in ws:
        if base is None or abs(w["top"] - base) <= _OKAYAMA_ROW_TOL:
            cur.append(w)
            base = w["top"] if base is None else base
        else:
            groups.append(cur)
            cur, base = [w], w["top"]
    if cur:
        groups.append(cur)
    return [" ".join(x["text"] for x in sorted(g, key=lambda y: y["x0"]))
            for g in groups]


def read_okayama(cfg: dict) -> tuple[dict, list[dict]]:
    import io
    import pdfplumber

    url = _okayama_pdf_url(cfg)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    time.sleep(SLEEP)

    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        lines = [ln for pg in pdf.pages for ln in _okayama_rows(pg)]
        vm = _OKAYAMA_VERSION_RE.search(pdf.pages[0].extract_text() or "")
    if not vm:
        raise RuntimeError("PDF冒頭の版日付が読めない")
    version = f"{vm.group(1)}-{int(vm.group(2)):02d}-{int(vm.group(3)):02d}"

    matches, md_date = [], {}
    for line in lines:
        m = _OKAYAMA_MATCH_RE.search(line)
        if not m:
            # 節2のように、節の既定日だけが独立行で出ることがある
            d = _OKAYAMA_ONLY_DATE.match(line.strip())
            if d:
                md_date[len(matches) // 5 + 1] = \
                    f"{SEASON_YEAR}-{int(d.group(1)):02d}-{int(d.group(2)):02d}"
            continue
        pre = line[:m.start()].strip()
        own = ""
        hm = _OKAYAMA_HEAD_MD_DATE.match(pre)
        if hm:
            md_date[int(hm.group(1))] = \
                f"{SEASON_YEAR}-{int(hm.group(2)):02d}-{int(hm.group(3)):02d}"
        else:
            hd = _OKAYAMA_HEAD_DATE.match(pre)
            if hd:      # その節の既定日と違う日に行われた試合。行頭の日付を優先する
                own = f"{SEASON_YEAR}-{int(hd.group(1)):02d}-{int(hd.group(2)):02d}"
        matches.append(dict(
            md=len(matches) // 5 + 1, _own=own,
            home=m.group(3).replace(" ", "").replace("　", ""),
            away=m.group(6).replace(" ", "").replace("　", ""),
            hs=int(m.group(4)) if m.group(4) else None,
            **{"as": int(m.group(5)) if m.group(5) else None},
            kickoff=m.group(1)))

    for x in matches:
        x["date"] = x.pop("_own") or md_date.get(x["md"], "")

    # ✅ 版日付ガード。日付の割り当てが壊れたことを検知する唯一の手がかり。
    future = [x for x in matches
              if x["hs"] is not None and x["date"] and x["date"] > version]
    if future:
        raise RuntimeError(
            f"版日付({version})より後の日付を持つ消化済み試合が{len(future)}件ある"
            f"（例: {future[0]['date']} {future[0]['home']} vs {future[0]['away']}）。"
            f"節と日付の割り当てが壊れている疑い")
    blank = [x for x in matches if x["hs"] is not None and not x["date"]]
    if blank:
        raise RuntimeError(f"日付を割り当てられなかった消化済み試合が{len(blank)}件ある")

    # 公式順位表は存在しない。process 側で試合から自前計算する（standings_gate: self）。
    return {}, matches


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
                    site_names: list[str], known_bad: list[dict] | None = None) -> list[str]:
    """通れば空リスト、落ちたら理由のリストを返す

    known_bad … **既存JSON側が誤っていると確認済みの試合**を除外する。
    移行の初回だけ効く。junior-soccer のスコア誤りが1件でもあると
    「既存にあって公式に無い試合」として弾かれ、正しい移行が止まるため。
    ⚠️ 日付・両チーム・スコアまで完全一致で指定する。件数を書くだけの
       ゆるい除外にすると、本物の取りこぼしまで通してしまう。
    """
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
    bad_keys = collections.Counter(key(b) for b in (known_bad or []))
    missing = []
    for m in existing.get("matches", []):
        if m.get("status") != "played" or m.get("hs") is None:
            continue
        k = key(m)
        if new_keys.get(k):
            new_keys[k] -= 1
        elif bad_keys.get(k):
            bad_keys[k] -= 1          # 既存側が誤っていると確認済み。除外する
        else:
            missing.append(m)
    for k, n in bad_keys.items():
        if n:
            ng.append(f"known_bad に書いた試合 {k} が既存JSONに見つからない"
                      f"（すでに直っている？ 設定を見直すこと）")
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
                      "yamaguchi": read_yamaguchi, "tokyo": read_tokyo,
                      "kanagawa": read_kanagawa, "toyama": read_toyama,
                      "kumamoto": read_kumamoto, "okinawa": read_okinawa,
                      "shimane": read_shimane,
                      "okayama": read_okayama}[cfg["platform"]]
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
        ng = self_check_gate(data, standings, matches, site_names,
                             cfg.get("known_bad_existing"))
        if ng:
            return f"[据え置き] {slug}: 検算不一致 {ng[:2]} …"

    # --- 沖縄は星取表が勝点・得点・失点・順位しか持たない（勝分敗が無い）ので、
    #     順位表を自前計算し、公式の4項目と突き合わせる代替ゲートで守る ---
    if cfg.get("standings_gate") == "okinawa":
        official = {name_map.get(k, k): v for k, v in standings.items()}
        standings = standings_from_matches(matches, site_names)
        ng = self_check_gate(data, standings, matches, site_names,
                             cfg.get("known_bad_existing"))
        mine_rank = sorted(site_names,
                           key=lambda t: (-standings[t]["pts"],
                                          -(standings[t]["gf"] - standings[t]["ga"]),
                                          -standings[t]["gf"]))
        for team, off in official.items():
            got = standings.get(team)
            if got is None:
                ng.append(f"{team}: 星取表にあるが試合から作れない")
                continue
            for key, label in (("pts", "勝点"), ("gf", "得点"), ("ga", "失点")):
                if off.get(key) is not None and got[key] != off[key]:
                    ng.append(f"{team}: {label} 公式{off[key]} ≠ 試合から{got[key]}")
            if off.get("rank") and team in mine_rank:
                # 同着があると並べ方で前後しうるので、勝点が同じ相手との入れ替わりは許す
                mine_i = mine_rank.index(team) + 1
                if mine_i != off["rank"]:
                    same = [t for t in site_names
                            if standings[t]["pts"] == got["pts"]]
                    if len(same) < 2:
                        ng.append(f"{team}: 順位 公式{off['rank']} ≠ 試合から{mine_i}")
        if ng:
            return f"[据え置き] {slug}: 検算不一致 {ng[:2]} …"

    # --- 検算とJSON組み立て（junior-soccer版と同じ関数を使う） ---
    # round_robin: False のリーグは総当たり枠を作らない。
    # 鳥取の後期のようにグループ分けのリーグでは、8チームの総当たり（56枠）を
    # 機械的に作ると**存在しない試合枠が大量に出る**。出典の試合一覧をそのまま枠にする。
    # 枠を2回戦制で作り直す県（島根28→56・岡山45→90）。
    # build_from_source は既存の枠数から1回戦制/2回戦制を推定するので、
    # 1回戦制の枠のまま止まっていた県はヒントを与えないと枠が増えない。
    # ⚠️ 退行防止は**枠数ではなく消化試合数**で見る（下の new_played < cur_played）。
    total_hint = existing_total
    if cfg.get("double_round"):
        n = len(site_names)
        total_hint = n * (n - 1)
    res = build_from_source(standings, matches, total_hint,
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
    data["lastUpdated"] = _jst_today().isoformat()   # UTCだと1日ずれる（jst.py参照）
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"[更新] {slug}: 消化{new_played}試合に更新（検算一致）"


# ---------------------------------------------------------------------------
# 取得結果の記録（2026-09-07 追加）
# ---------------------------------------------------------------------------
# process() が返したメッセージを、見張り用の結果コードに読み替えるだけ。
# **判定（赤にするか）はここでは行わない** — audit_pref_freshness.py の担当。
# process() 本体には一切手を入れていないので、更新処理の挙動は変わらない。
def classify(msg: str) -> tuple[str, str]:
    """process() の戻り値 → (結果コード, 説明)"""
    body = msg.split(": ", 1)[-1]
    if msg.startswith("[更新]"):
        return "ok", body
    # 公式側の消化数がこちらより少ない＝出典が遅れているだけ。取得は成功している。
    # ここを失敗にすると、出典が休みの県が毎日赤くなる（打つ手が無いものは赤にしない）。
    if "退行防止" in msg:
        return "ok", body
    if "取得失敗" in msg or "例外" in msg:
        return "fetch_error", body
    if "解析できず" in msg:
        return "parse_empty", body
    if "名寄せ" in msg or "1対1で対応しない" in msg:
        return "alias_failed", body
    return "verify_failed", body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="県1部を県協会公式（GoalNote / tecra ほか）から更新する")
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
        if not args.dry_run:
            fetch_status.set_pref_result(pref, *classify(msg))
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
