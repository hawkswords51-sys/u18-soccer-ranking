# -*- coding: utf-8 -*-
"""
U-15（3種）地域リーグ順位表の自動更新
=====================================

data/u15/leagues-2026.json の各ディビジョンの順位表を、公式出典から取得して更新する。
毎朝のワークフロー（update_rankings.yml）から呼ばれる。単体実行も可。

出典は3系統：
  A) 関東 …… 関東クラブユースサッカー連盟/関東サッカー協会クレジットの結果サイト（HTML）
              1ページに1部A/B・2部A〜Dの6ブロック分の順位表が入っている。
  B) 東北 …… JFAの順位表HTML（プリンス東北と同じ形式）。TOP/チャレンジ北/南の3つ。
  C) その他7地域 …… JFA公式の「星取表PDF」。HTMLの順位表が存在しないため、
              PDFを pdfplumber の座標付き単語抽出（extract_words）で読む。

★安全設計（既存の fetch_pref_scorers.py / update_cross_tables.py と同じ思想）
  - 取得失敗・解析0件・検証NG のときは **そのディビジョンのJSONを一切変更しない**（既存維持）
  - 検証＝(1)勝点=勝×3+分 (2)試合数=勝+分+敗 (3)リーグ内の得点合計=失点合計
          (4)勝数合計=敗数合計 (5)チーム名が既存JSONの顔ぶれと一致（増減なし）
  - 「試合数が減る」更新は退行とみなして破棄（出典の一時的な巻き戻し対策）
  - 例外は全て捕捉し、終了コードは常に0（ワークフローを止めない）

使い方:
    python scraper/fetch_u15_leagues.py            # 取得して書き込み
    python scraper/fetch_u15_leagues.py --dry-run  # 取得と検証だけ（書き込まない）
    python scraper/fetch_u15_leagues.py --only kanto-1a,tohoku-top
"""
import argparse
import datetime
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
DATA = BASE_DIR / "data" / "u15" / "leagues-2026.json"
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; u18-soccer-bot/1.0; +https://u18-soccer.com)"}
TIMEOUT = 30
MAX_PDF_BYTES = 12 * 1024 * 1024

_JST = datetime.timezone(datetime.timedelta(hours=9))


def today_jst():
    return datetime.datetime.now(_JST).date()


def norm(s: str) -> str:
    """チーム名照合用の正規化（全角半角・空白・記号ゆれを吸収）"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace(" ", "").replace("　", "")
    s = s.replace("･", "・").replace(".", "").replace("／", "/")
    return s.strip()


# =====================================================================
# 出典定義
# =====================================================================
KANTO_URL = "https://myo-ga.sakura.ne.jp/wop/competition/kanto-u15-2026/"

# 関東ページ内の見出し（順位表の直前に出る）→ division id
KANTO_HEADINGS = {
    "1部A": "kanto-1a", "１部Ａ": "kanto-1a",
    "1部B": "kanto-1b", "１部Ｂ": "kanto-1b",
    "2部A": "kanto-2a", "２部Ａ": "kanto-2a",
    "2部B": "kanto-2b", "２部Ｂ": "kanto-2b",
    "2部C": "kanto-2c", "２部Ｃ": "kanto-2c",
    "2部D": "kanto-2d", "２部Ｄ": "kanto-2d",
}

# 東北は同じ形式のページが3つ。★チャレンジ北(tohoku2)だけ順位表が読めないことがあるため
# 予備URLを順に試す（最初に読めたものを採用する）。
_THFA = "https://www.jfa.jp/match_47fa/102_tohoku/takamado_jfa_u15_2026"
TOHOKU_URLS = {
    "michinoku-top": [f"{_THFA}/tohoku1/thfa/ranking.html"],
    "michinoku-n":   [f"{_THFA}/tohoku2/thfa/ranking.html",
                      f"{_THFA}/tohoku2/schedule_result/ranking.html",
                      f"{_THFA}/tohoku2/thfa/",
                      f"{_THFA}/tohoku2/"],
    "michinoku-s":   [f"{_THFA}/tohoku3/thfa/ranking.html"],
}

# JFA星取表PDF。1つのPDFに複数ディビジョンが入る場合は divisions を順に割り当てる
JFA_PDF = [
    {"url": "https://www.jfa.jp/match_47fa/101_hokkaido/takamado_jfa_u15_2026/hokkaido1/schedule_result/pdf/League.pdf",
     "divisions": ["hokkaido-1"]},
    {"url": "https://www.jfa.jp/match_47fa/101_hokkaido/takamado_jfa_u15_2026/hokkaido2/schedule_result/pdf/League.pdf",
     "divisions": ["hokkaido-2"]},
    {"url": "https://www.jfa.jp/match_47fa/104_hokushinetsu/takamado_jfa_u15_2026/schedule_result/pdf/League.pdf",
     "divisions": ["hokushinetsu"]},
    {"url": "https://www.jfa.jp/match_47fa/105_tokai/takamado_jfa_u15_2026/schedule_result/pdf/League.pdf",
     "divisions": ["tokai"]},
    {"url": "https://www.jfa.jp/match_47fa/106_kansai/takamado_jfa_u15_2026/kansai1/schedule_result/pdf/League.pdf",
     "divisions": ["kansai-1"]},
    {"url": "https://www.jfa.jp/match_47fa/106_kansai/takamado_jfa_u15_2026/kansai2A/schedule_result/pdf/League.pdf",
     "divisions": ["kansai-2a"]},
    {"url": "https://www.jfa.jp/match_47fa/106_kansai/takamado_jfa_u15_2026/kansai2B/schedule_result/pdf/League.pdf",
     "divisions": ["kansai-2b"]},
    {"url": "https://www.jfa.jp/match_47fa/107_chugoku/takamado_jfa_u15_2026/chugoku1/schedule_result/pdf/League.pdf",
     "divisions": ["chugoku-1"]},
    {"url": "https://www.jfa.jp/match_47fa/107_chugoku/takamado_jfa_u15_2026/chugoku2/schedule_result/pdf/League.pdf",
     "divisions": ["chugoku-2"]},
    {"url": "https://www.jfa.jp/match_47fa/108_shikoku/takamado_jfa_u15_2026/schedule_result/pdf/League.pdf",
     "divisions": ["shikoku"]},
    # 九州は1つのPDFに1部・2部が入る（1部の表が欠けている年があるため、取れた分だけ使う）
    {"url": "https://www.jfa.jp/match_47fa/109_kyushu/takamado_jfa_u15_2026/kyushu_1_2/schedule_result/pdf/League.pdf",
     "divisions": ["kyushu-1", "kyushu-2"]},
]

# PDFの略称 → 掲載名（サイト表記）。四国のPDFは略称のみのため必須。
NAME_ALIASES = {
    "shikoku": {
        "徳島V": "徳島ヴォルティス", "愛媛FC": "愛媛FC", "高知U": "高知ユナイテッドSC",
        "FC今治": "FC今治", "FCLivent": "FC Livent", "カマタマーレ讃岐": "カマタマーレ讃岐",
        "FCコーマラント": "F.C.コーマラント", "愛媛FC新居浜": "愛媛FC新居浜",
        "CSP": "CSP", "ソレアーダ高知": "ソレアーダ高知",
    },
}


# =====================================================================
# 検証（ここを通らないデータは絶対に書き込まない）
# =====================================================================
def verify(teams, old_teams, label):
    """新しい順位表が妥当か検証。問題があれば理由のリストを返す（空なら健全）。"""
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
            problems.append(f"{t['name']}: 順位の並びで勝点が増えている")
        prev = t["pts"]

    if old_teams:
        old_names = {norm(t["name"]) for t in old_teams}
        new_names = {norm(t["name"]) for t in teams}
        if old_names != new_names:
            miss = old_names - new_names
            extra = new_names - old_names
            problems.append(f"顔ぶれが変わった（消えた:{sorted(miss)[:3]} 増えた:{sorted(extra)[:3]}）")
        # 退行防止：総試合数が減る更新は捨てる
        if sum(t["p"] for t in teams) < sum(t["p"] for t in old_teams):
            problems.append(f"総試合数が減少（{sum(t['p'] for t in old_teams)}→{sum(t['p'] for t in teams)}）")
    return problems


# =====================================================================
# A) 関東（HTML・1ページに6ブロック）
# =====================================================================
_H_POINTS = {"勝点", "勝ち点", "pts"}
_H_PLAYED = {"試合", "試合数"}
_H_MAP = [
    ("pts", {"勝点", "勝ち点"}),
    ("p",   {"試合", "試合数"}),
    ("w",   {"勝", "勝利"}),
    ("d",   {"分", "引分", "引き分け"}),
    ("l",   {"敗", "負", "敗戦"}),
    ("gf",  {"得", "得点"}),
    ("ga",  {"失", "失点"}),
]


def _parse_standings_table(table, debug=False):
    """<table>から [{name,p,w,d,l,gf,ga,pts,rank}] を作る。順位表でなければ None。

    ★列ズレ対策（2026-08-30・実ログで発覚）
      関東のサイトは <th> が10個なのにデータ行は11セルある（Clubの直後に
      「勝 勝 分 勝 敗 >」という連勝連敗の欄が入るがヘッダーが無い）。
      ヘッダーの位置で数値を読むと1列ずれて全行が捨てられ、リーグごと取得0件になる。
      → **集計列（勝点〜得失差）はヘッダーの「右端からの位置」で読む**。
        集計列は必ず行の末尾に並ぶので、途中に無名の列が挟まってもズレない。
        さらに行ごとに「勝点=勝×3+分」で自己検査し、合わない行は捨てる。
    """
    rows = table.find_all("tr")
    if len(rows) < 3:
        return None
    header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    if not (set(header) & _H_POINTS) or not (set(header) & _H_PLAYED):
        return None

    # フィールド → 「ヘッダー末尾から数えた位置」
    from_end = {}
    for i, h in enumerate(header):
        h = h.strip()
        for field, kws in _H_MAP:
            if field not in from_end and h in kws:
                from_end[field] = len(header) - i
    if not all(k in from_end for k in ("pts", "p", "w", "d", "l", "gf", "ga")):
        return None

    # チーム名は行の「左から」探す（左側に無名列が入ることは無い）
    name_i = None
    for i, h in enumerate(header):
        if h.strip().lower() in {"club", "チーム", "チーム名", "クラブ"}:
            name_i = i
            break

    out, dropped = [], 0
    for tr in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < len(header):
            continue

        def num(field):
            j = len(cells) - from_end[field]
            if j < 0 or j >= len(cells):
                return None
            v = cells[j].strip().lstrip("+").replace("−", "-")
            return int(v) if re.fullmatch(r"-?\d+", v) else None

        vals = {f: num(f) for f in ("pts", "p", "w", "d", "l", "gf", "ga")}
        if any(v is None for v in vals.values()):
            dropped += 1
            continue
        # 自己検査：列の対応が正しければ必ず成り立つ
        if vals["pts"] != vals["w"] * 3 + vals["d"] or vals["p"] != vals["w"] + vals["d"] + vals["l"]:
            dropped += 1
            continue

        name = cells[name_i] if (name_i is not None and name_i < len(cells)) else ""
        if not name or re.fullmatch(r"[-+\d\s]+", name):
            name = next((c for c in cells
                         if c and not re.fullmatch(r"[-+\d\s]+", c) and len(c) >= 2), "")
        name = _clean_team_name(name)
        if not name:
            dropped += 1
            continue
        out.append({"rank": len(out) + 1, "name": name, **vals})

    if debug:
        print(f"      表: ヘッダー{len(header)}列 {header} → 採用{len(out)}行 / 捨てた{dropped}行")
    return out or None


def _clean_team_name(name: str) -> str:
    """順位表セルから拾った文字列をチーム名だけにする。
      - 先頭の昇降格マーク（▲▼）
      - 末尾の連勝連敗（勝 勝 分 勝 敗 >）
      - 末尾の（宮城県）などの県名 …… ★JFA東北の表はチーム名に県名が付く（実ログで発覚）
    """
    name = re.sub(r"^[▲▼△▽\s　]+", "", name or "")
    name = re.sub(r"[\s　]*(勝|敗|分)([\s　]*(勝|敗|分))*[\s　]*>?$", "", name)
    name = re.sub(r"[（(][^（）()]{1,8}[県都道府]?[）)]\s*$", "", name)
    return name.strip()


def fetch_kanto(debug=False):
    """関東の6ブロックを {division_id: teams} で返す。

    ★2026-08-30の実ログでわかったこと
      このページの <table> は**星取表（対戦表）6個だけ**で、順位表はテーブル要素ではない。
      そのため表を探す方式では0件になる。→ **ページ本文のテキストから読む**方式に変更した。
      本文は「# Club 勝点 試合 勝 分 敗 得 失 差」に続いて
      「順位 [▲▼] チーム名 勝 勝 分 勝 敗 > 勝点 試合 勝 分 敗 得 失 差」が並ぶ規則的な形。
    """
    r = requests.get(KANTO_URL, headers=HEAD, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    text = unicodedata.normalize("NFKC", BeautifulSoup(r.text, "html.parser").get_text(" "))
    text = re.sub(r"[\u3000\s]+", " ", text)

    header_re = re.compile(r"#\s*Club\s*勝点\s*試合\s*勝\s*分\s*敗\s*得\s*失\s*差")
    row_re = re.compile(
        r"(\d{1,2})\s+(?:[▲▼△▽]\s*)?(.+?)\s+"          # 順位・(昇降格マーク)・チーム名
        r"(?:(?:勝|分|敗)\s+)*>\s+"                        # 直近成績「勝 勝 分 勝 敗 >」
        r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([-−]?\d+)")
    labels = {unicodedata.normalize("NFKC", k): v for k, v in KANTO_HEADINGS.items()}

    starts = [m.start() for m in header_re.finditer(text)]
    print(f"  順位表の見出しを{len(starts)}個検出")
    found = {}
    for i, st in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunk = text[st:nxt]
        # 直前240文字の中に出てくる最後のブロック名（1部A 等）を採用
        before = text[max(0, st - 240):st]
        best_pos, did = -1, None
        for label, d in labels.items():          # 直前に一番近いブロック名を採用
            pos = before.rfind(label)
            if pos > best_pos:
                best_pos, did = pos, d
        teams = []
        for m in row_re.finditer(chunk):
            name = _clean_team_name(m.group(2))
            pts, p, w, d_, l, gf, ga, gd = (int(x.replace("−", "-")) for x in m.groups()[2:])
            if pts != w * 3 + d_ or p != w + d_ + l or gf - ga != gd:
                continue                      # 自己検査に通った行だけ採用
            if not name:
                continue
            teams.append({"rank": len(teams) + 1, "name": name, "p": p, "w": w,
                          "d": d_, "l": l, "gf": gf, "ga": ga, "pts": pts})
        if debug:
            print(f"      ブロック{did or '?'}: {len(teams)}チーム")
        if teams and did and did not in found:
            found[did] = teams

    print(f"  ブロック確定: {sorted(found)}")
    if not found:
        print("  [自動診断] 本文から順位表を読めませんでした。見出し周辺の本文:")
        m = header_re.search(text)
        if m:
            print("      " + text[m.start():m.start() + 240])
    return found


# =====================================================================
# B) 東北（JFAの順位表HTML）
# =====================================================================
def fetch_tohoku(debug=False):
    out = {}
    for did, urls in TOHOKU_URLS.items():
        tried = []
        for url in urls:
            try:
                r = requests.get(url, headers=HEAD, timeout=TIMEOUT)
                r.raise_for_status()
                r.encoding = r.apparent_encoding or "utf-8"
                soup = BeautifulSoup(r.text, "html.parser")
                tables = soup.find_all("table")
                for table in tables:
                    teams = _parse_standings_table(table, debug=debug)
                    if teams:
                        out[did] = teams
                        break
                tried.append(f"{url.split('/')[-2]}/{url.split('/')[-1] or '(index)'}:表{len(tables)}個")
                if did in out:
                    print(f"  {did}: {len(out[did])}チーム（1位 {out[did][0]['name']}）")
                    break
            except Exception as e:
                tried.append(f"{url.split('/')[-1] or '(index)'}:失敗({type(e).__name__})")
        if did not in out:
            print(f"  [注意] {did}: 順位表を読めなかった → 試したURL {tried}")
    return out


# =====================================================================
# C) JFA星取表PDF（座標ベースで読む）
# =====================================================================
def _pdf_rows(page):
    """extract_words の結果を y座標で行にまとめる（左→右に並べ替え）"""
    words = page.extract_words(x_tolerance=1.5, y_tolerance=2.5, keep_blank_chars=False)
    rows = {}
    for w in words:
        key = round(w["top"] / 4.0)          # 4pt刻みで同じ行とみなす
        rows.setdefault(key, []).append(w)
    out = []
    for key in sorted(rows):
        ws = sorted(rows[key], key=lambda w: w["x0"])
        out.append(ws)
    return out


def parse_jfa_pdf(pdf_bytes, want_divisions, aliases_by_div, debug=False):
    """星取表PDFから {division_id: teams} を作る。

    ★2026-08-30の実ログでわかったPDFの構造
      集計列は **「勝点・得点・失点・得失・順位」の5つだけ**で、勝/分/敗の列は無い。
      チームごとに1行、次の形で並ぶ：  チーム名 | 勝点 | 得点 | 失点 | 得失 | 順位
      勝敗数は星取マトリクスの ○（勝）△（分）●（敗）を数えて求める。
      印はチーム行の上下2行に折り返して置かれるため、**各印を最も近いチーム行に割り当てる**。

    安全のため、全チームで「勝点＝○×3＋△」が成り立ったときだけ採用する
    （成り立たなければそのリーグは更新しない＝既存維持）。
    """
    import pdfplumber

    MARKS = {"○": "w", "◯": "w", "△": "d", "▲": "d", "●": "l", "×": "l"}
    results = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2.5)
            if not words:
                continue
            lines = {}
            for w in words:
                lines.setdefault(round(w["top"] / 4.0), []).append(w)

            # ① チーム行（末尾5つが 勝点・得点・失点・得失・順位）を拾う
            teams = []
            for key in sorted(lines):
                ws = sorted(lines[key], key=lambda w: w["x0"])
                texts = [w["text"] for w in ws]
                if len(texts) < 6:
                    continue
                tail = texts[-5:]
                if not all(re.fullmatch(r"[+\-−]?\d+", t) for t in tail):
                    continue
                pts, gf, ga, gd, rank = (int(t.replace("−", "-").lstrip("+")) for t in tail)
                if gf - ga != gd or not (1 <= rank <= 30):
                    continue
                name = "".join(t for t in texts[:-5]
                               if not re.fullmatch(r"[+\-−]?\d+|[○◯△▲●×\-]", t)).strip()
                name = re.sub(r"^[★＊*\s]+", "", name)
                if len(name) < 2:
                    continue
                y = sum(w["top"] for w in ws) / len(ws)
                teams.append({"name": name, "pts": pts, "gf": gf, "ga": ga,
                              "rank": rank, "_y": y})
            if len(teams) < 6:
                continue

            # ② 星取記号を、最も近いチーム行に割り当てて 勝/分/敗 を数える
            for t in teams:
                t["w"] = t["d"] = t["l"] = 0
            ys = [t["_y"] for t in teams]
            span = (max(ys) - min(ys)) / max(1, len(teams) - 1)      # 行の間隔
            for w in words:
                field = MARKS.get(w["text"])
                if not field:
                    continue
                near = min(teams, key=lambda t: abs(t["_y"] - w["top"]))
                if abs(near["_y"] - w["top"]) <= span * 0.9:
                    near[field] += 1

            ok = True
            for t in teams:
                t["p"] = t["w"] + t["d"] + t["l"]
                if t["pts"] != t["w"] * 3 + t["d"]:
                    ok = False
            if not ok:
                if debug:
                    bad = [f"{t['name']}(勝点{t['pts']}／○{t['w']}△{t['d']}●{t['l']})"
                           for t in teams if t["pts"] != t["w"] * 3 + t["d"]][:3]
                    print(f"      PDF {pno}ページ目: 勝敗数と勝点が合わないので不採用 {bad}")
                continue

            title = " ".join(w["text"] for w in sorted(
                lines[min(lines)], key=lambda w: w["x0"]))
            for t in teams:
                t.pop("_y", None)
            teams.sort(key=lambda t: t["rank"])
            results.append({"title": title, "teams": teams})

    if not results:
        print("      [自動診断] 表として成立する行がありませんでした。1ページ目の先頭行:")
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if pdf.pages:
                for ws in _pdf_rows(pdf.pages[0])[:5]:
                    print("        raw:", " | ".join(w["text"] for w in ws)[:160])

    # ③ ディビジョンへの割り当て（1PDFに複数ある場合はタイトルの「1部/2部」で判定）
    out = {}
    remain = list(results)
    for did in want_divisions:
        hint = None
        if did.endswith("-1"):
            hint = "1部"
        elif did.endswith("-2"):
            hint = "2部"
        pick = None
        if hint:
            pick = next((r for r in remain if hint in r["title"].replace(" ", "")), None)
        if pick is None and len(want_divisions) == 1 and remain:
            pick = remain[0]
        if pick is None:
            continue
        remain.remove(pick)
        al = aliases_by_div.get(did, {})
        for t in pick["teams"]:
            for a, real in al.items():
                if norm(a) == norm(t["name"]):
                    t["name"] = real
                    break
        out[did] = pick["teams"]
    return out


def fetch_jfa_pdfs(only=None, debug=False):
    out = {}
    for src in JFA_PDF:
        wants = [d for d in src["divisions"] if (only is None or d in only)]
        if not wants:
            continue
        try:
            r = requests.get(src["url"], headers=HEAD, timeout=TIMEOUT)
            r.raise_for_status()
            if len(r.content) > MAX_PDF_BYTES:
                print(f"  [警告] PDFが大きすぎます: {src['url']}")
                continue
            got = parse_jfa_pdf(r.content, src["divisions"], NAME_ALIASES, debug=debug)
            tag = src["divisions"][0]
            if not got:
                print(f"  [注意] {tag}: PDF({len(r.content)//1024}KB)から順位表を読めなかった")
            for did in wants:
                if did in got:
                    out[did] = got[did]
                    print(f"  {did}: {len(got[did])}チーム（1位 {got[did][0]['name']}）")
        except Exception as e:
            print(f"  [警告] PDF取得/解析に失敗 {src['url']}: {e}")
    return out


# =====================================================================
# main
# =====================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="取得と検証だけ行い書き込まない")
    ap.add_argument("--only", default="", help="対象division idをカンマ区切りで指定")
    ap.add_argument("--debug", action="store_true", help="表やPDFの中身を詳しく出力する")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None

    if not DATA.exists():
        print(f"❌ データがありません: {DATA}")
        return 0
    data = json.loads(DATA.read_text(encoding="utf-8"))
    by_id = {d["id"]: d for d in data["divisions"]}

    fetched = {}
    print("■ 関東（連盟公式の結果サイト）")
    try:
        if only is None or any(k.startswith("kanto-") for k in only):
            fetched.update(fetch_kanto(debug=args.debug))
    except Exception as e:
        print(f"  [警告] 関東の取得に失敗: {e}")

    print("■ 東北（JFA順位表HTML）")
    try:
        if only is None or any(k.startswith("michinoku-") for k in only):
            fetched.update(fetch_tohoku(debug=args.debug))
    except Exception as e:
        print(f"  [警告] 東北の取得に失敗: {e}")

    print("■ JFA星取表PDF（北海道・北信越・東海・関西・中国・四国・九州）")
    try:
        fetched.update(fetch_jfa_pdfs(only, debug=args.debug))
    except Exception as e:
        print(f"  [警告] PDF群の取得に失敗: {e}")

    updated, kept, skipped = [], [], []
    for did, teams in sorted(fetched.items()):
        if only and did not in only:
            continue
        div = by_id.get(did)
        if not div:
            skipped.append(f"{did}(JSONに未登録)")
            continue
        problems = verify(teams, div.get("teams"), did)
        if problems:
            kept.append(f"{did}: " + " / ".join(problems[:2]))
            continue
        if teams == div["teams"]:
            continue                      # 変化なし
        div["teams"] = teams
        div["asof"] = f"{today_jst():%Y年%-m月%-d日}時点（自動更新）"
        updated.append(did)

    for did in sorted(set(by_id) - set(fetched)):
        if only is None or did in only:
            skipped.append(did)

    print()
    print(f"✅ 更新: {len(updated)}リーグ " + (", ".join(updated) if updated else "（変化なし）"))
    if kept:
        print(f"⏸ 検証NGのため既存維持: {len(kept)}リーグ")
        for k in kept:
            print("   - " + k)
    if skipped:
        print(f"— 取得できず既存維持: {len(skipped)}リーグ（{', '.join(skipped[:8])}"
              + (" ほか" if len(skipped) > 8 else "") + "）")

    if updated and not args.dry_run:
        data["updated"] = f"{today_jst():%Y-%m-%d}"
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"💾 {DATA.relative_to(BASE_DIR)} を更新しました")
    elif args.dry_run:
        print("（--dry-run のため書き込みはしていません）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:            # ワークフローを止めない
        print(f"❌ 想定外のエラー（既存データは変更していません）: {e}")
        sys.exit(0)
