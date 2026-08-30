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

TOHOKU_URLS = {
    "michinoku-top": "https://www.jfa.jp/match_47fa/102_tohoku/takamado_jfa_u15_2026/tohoku1/thfa/ranking.html",
    "michinoku-n":   "https://www.jfa.jp/match_47fa/102_tohoku/takamado_jfa_u15_2026/tohoku2/thfa/ranking.html",
    "michinoku-s":   "https://www.jfa.jp/match_47fa/102_tohoku/takamado_jfa_u15_2026/tohoku3/thfa/ranking.html",
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


def _parse_standings_table(table):
    """<table>から [{name,p,w,d,l,gf,ga,pts,rank}] を作る。順位表でなければ None。"""
    rows = table.find_all("tr")
    if len(rows) < 3:
        return None
    header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    if not (set(header) & _H_POINTS) or not (set(header) & _H_PLAYED):
        return None

    idx = {}
    for i, h in enumerate(header):
        h = h.strip()
        for field, kws in _H_MAP:
            if field not in idx and h in kws:
                idx[field] = i
    if not all(k in idx for k in ("pts", "p", "w", "d", "l", "gf", "ga")):
        return None
    # チーム名の列＝Club/チーム、無ければ数値でない最初の列
    name_i = None
    for i, h in enumerate(header):
        if h.strip().lower() in {"club", "チーム", "チーム名", "クラブ"}:
            name_i = i
            break

    out = []
    for tr in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < len(header):
            continue

        def num(field):
            v = cells[idx[field]].strip().lstrip("+")
            return int(v) if re.fullmatch(r"-?\d+", v) else None

        vals = {f: num(f) for f in ("pts", "p", "w", "d", "l", "gf", "ga")}
        if any(v is None for v in vals.values()):
            continue
        if name_i is not None and name_i < len(cells):
            name = cells[name_i]
        else:
            name = next((c for c in cells if c and not re.fullmatch(r"[-+\d\s]+", c)), "")
        # 「▲」「▼」などの増減マークと連勝連敗の記号列を落とす
        name = re.sub(r"^[▲▼△▽\s]+", "", name)
        name = re.sub(r"[\s　]*(勝|敗|分)([\s　]*(勝|敗|分))*[\s　]*>?$", "", name).strip()
        if not name:
            continue
        out.append({"rank": len(out) + 1, "name": name, **vals})
    return out or None


def fetch_kanto():
    """関東の6ブロックを {division_id: teams} で返す"""
    r = requests.get(KANTO_URL, headers=HEAD, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    found = {}
    for table in soup.find_all("table"):
        teams = _parse_standings_table(table)
        if not teams:
            continue
        # 直前の見出し（1部Ａ 等）からディビジョンを判定
        head = table.find_previous(["h1", "h2", "h3", "h4", "h5", "caption"])
        key = None
        if head:
            ht = unicodedata.normalize("NFKC", head.get_text(strip=True)).replace(" ", "")
            for label, did in KANTO_HEADINGS.items():
                if unicodedata.normalize("NFKC", label).replace(" ", "") == ht:
                    key = did
                    break
        if key and key not in found:   # 同じ表がページ下部にも再掲されるので最初だけ採用
            found[key] = teams
    return found


# =====================================================================
# B) 東北（JFAの順位表HTML）
# =====================================================================
def fetch_tohoku():
    out = {}
    for did, url in TOHOKU_URLS.items():
        try:
            r = requests.get(url, headers=HEAD, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            for table in soup.find_all("table"):
                teams = _parse_standings_table(table)
                if teams:
                    out[did] = teams
                    break
        except Exception as e:
            print(f"  [警告] {did} の取得に失敗: {e}")
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


def parse_jfa_pdf(pdf_bytes, want_divisions, aliases_by_div):
    """星取表PDFから {division_id: teams} を作る。
    各ページの各行について「右端に並ぶ集計列（順位・勝点・勝・分・敗・得・失・得失差）」と
    「行の左側にあるチーム名」を拾う。表が複数ある場合はページ順に division を割り当てる。"""
    import pdfplumber

    results = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            block = []
            for ws in _pdf_rows(page):
                texts = [w["text"] for w in ws]
                # 行末から数値を集める（順位…得失差までの8個が必要）
                nums, i = [], len(texts) - 1
                while i >= 0 and re.fullmatch(r"[+\-]?\d+", texts[i]) and len(nums) < 12:
                    nums.append(texts[i])
                    i -= 1
                nums.reverse()
                if len(nums) < 8:
                    continue
                # 集計列は左→右に「順位 勝点 勝利 引分 敗戦 得点 失点 得失差」。
                # 星取マトリクスの数字も末尾の数値列に混ざるため、右端から8個ずつ窓をずらし、
                # 「得点−失点＝得失差」かつ「勝点＝勝×3＋分」を満たす窓だけを採用する。
                rec = None
                for s in range(len(nums) - 8, -1, -1):
                    try:
                        rank, pts, w_, d, l, gf, ga, gd = (
                            int(x.lstrip("+")) for x in nums[s:s + 8])
                    except ValueError:
                        continue
                    if gf - ga == gd and pts == w_ * 3 + d and rank >= 1 and w_ >= 0:
                        rec = {"rank": rank, "p": w_ + d + l, "w": w_, "d": d,
                               "l": l, "gf": gf, "ga": ga, "pts": pts}
                        break
                if rec is None:
                    continue
                name = "".join(t for t in texts[:i + 1]
                               if not re.fullmatch(r"[+\-]?\d+|[○△●★＊*]", t)).strip()
                name = re.sub(r"^[★＊*\s]+", "", name)
                if not name or len(name) < 2:
                    continue
                block.append({"name": name, **rec})
            if len(block) >= 6:
                block.sort(key=lambda t: t["rank"])
                results.append(block)

    out = {}
    for did, teams in zip(want_divisions, results):
        al = aliases_by_div.get(did, {})
        for t in teams:
            key = norm(t["name"])
            for a, real in al.items():
                if norm(a) == key:
                    t["name"] = real
                    break
        out[did] = teams
    return out


def fetch_jfa_pdfs(only=None):
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
            got = parse_jfa_pdf(r.content, src["divisions"], NAME_ALIASES)
            for did in wants:
                if did in got:
                    out[did] = got[did]
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
            fetched.update(fetch_kanto())
    except Exception as e:
        print(f"  [警告] 関東の取得に失敗: {e}")

    print("■ 東北（JFA順位表HTML）")
    try:
        if only is None or any(k.startswith("michinoku-") for k in only):
            fetched.update(fetch_tohoku())
    except Exception as e:
        print(f"  [警告] 東北の取得に失敗: {e}")

    print("■ JFA星取表PDF（北海道・北信越・東海・関西・中国・四国・九州）")
    try:
        fetched.update(fetch_jfa_pdfs(only))
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
