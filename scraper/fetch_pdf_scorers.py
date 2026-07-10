# -*- coding: utf-8 -*-
"""
PDF出典の県別得点ランキング 自動更新（茨城・福井・三重・愛媛）
=============================================================

各県サッカー協会が「PDF 1枚」で公開している県1部の得点ランキングを、
掲載ページから最新PDFリンクを自動発見してダウンロード・解析し、
data/scorers/pref-<id>-1.json を更新する。
fetch_pref_scorers.py の main() から呼ばれる（単体実行も可）。

背景: PDFのファイル名は更新の度に変わる（日付・ハッシュ入り）ため
固定URLでは追えない。→「掲載ページのリンク文言」から毎回発見する。

安全設計（fetch_pref_scorers.py と同じ思想）:
- 取得失敗・0件・検証失敗のときは既存JSONを一切変更しない
- 解析結果は「既知チーム名との照合」「得点の単調性」「順位の整合」で
  検証してから書き込む（既知チーム＝league_matches＋既存scorersのチーム名）
- 例外はすべて捕捉。終了コードは常に0（ワークフローを止めない）

県ごとの癖:
- 茨城: テキストPDF。No/氏名/所属チーム/得点。O.G行は除外。
- 福井: フォント都合で漢字がCJK互換部首で出る＋得点列に迷い数字が混ざる。
        → 部首正規化＋「順位グループから得点を復元」する専用ロジック。
- 三重: 2026-07-11時点で公式サイトがダウンしており実PDF未検証。
        汎用パーサ＋厳格検証（失敗時は既存維持なので実害なし）。
- 愛媛: テキストPDF。順位/チーム名/氏名/得点。上位のみの掲載。
"""
import datetime
import io
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DIR = Path(__file__).resolve().parent.parent / "data" / "scorers"
LM_DIR = Path(__file__).resolve().parent.parent / "data" / "league_matches"
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; u18-soccer-bot/1.0; +https://u18-soccer.com)"}
TIMEOUT = 30
MAX_ROWS = 200
MAX_PDF_BYTES = 8 * 1024 * 1024

_JST = datetime.timezone(datetime.timedelta(hours=9))
SEASON = str(datetime.datetime.now(_JST).year)

# CJK互換部首（NFKCで直らない U+2E80 台）→ 通常漢字
_RAD_SUP = {
    "⻑": "長", "⻄": "西", "⻘": "青", "⻩": "黄", "⼾": "戸", "⻁": "虎",
    "⻣": "骨", "⻤": "鬼", "⻭": "歯", "⻯": "竜", "⻝": "食", "⻟": "食",
    "⻲": "亀", "⻖": "阝", "⻌": "辶", "⻍": "辶", "⻏": "阝", "⻊": "足",
}
_OG_NAMES = {"OG", "オウンゴール"}


def _fix(s: str) -> str:
    """CJK互換部首の補正 + NFKC正規化（半角カナ→全角なども兼ねる）"""
    for a, b in _RAD_SUP.items():
        s = s.replace(a, b)
    return unicodedata.normalize("NFKC", s)


def _despace(s: str) -> str:
    return re.sub(r"[\s　]+", "", s)


def _is_og(name: str) -> bool:
    return name.upper().replace(".", "").replace("・", "").replace(" ", "") in _OG_NAMES


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers=HEAD, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _soup(url: str) -> BeautifulSoup:
    r = _get(url)
    r.encoding = r.apparent_encoding or r.encoding
    return BeautifulSoup(r.text, "lxml")


def _pdf_lines(content: bytes):
    """PDFを行テキストのリストにする（ページ横断・上から順）"""
    import pdfplumber
    lines = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5, y_tolerance=3)
            words.sort(key=lambda w: (w["top"], w["x0"]))
            cur, cur_top = [], None
            for w in words:
                if cur_top is None or abs(w["top"] - cur_top) <= 3:
                    cur.append(w)
                    cur_top = w["top"] if cur_top is None else cur_top
                else:
                    cur.sort(key=lambda x: x["x0"])
                    lines.append(" ".join(x["text"] for x in cur))
                    cur, cur_top = [w], w["top"]
            if cur:
                cur.sort(key=lambda x: x["x0"])
                lines.append(" ".join(x["text"] for x in cur))
    return lines


def _known_teams(slug: str, extra_aliases: dict | None = None) -> dict:
    """既知チーム辞書 {despace形: 表示名}。league_matches→既存scorersの順に読み、
    表示名は既存scorers側の表記を優先する（従来の表示と揃える）。"""
    known = {}
    lm = LM_DIR / f"{slug}.json"
    if lm.exists():
        d = json.loads(lm.read_text(encoding="utf-8"))
        for t in d.get("teams", []):
            name = t if isinstance(t, str) else t.get("name", "")
            if name:
                known[_despace(_fix(name))] = name
    sc = DIR / f"{slug}.json"
    if sc.exists():
        d = json.loads(sc.read_text(encoding="utf-8"))
        for s in d.get("scorers", []):
            if s.get("team"):
                known[_despace(_fix(s["team"]))] = s["team"]
    for k, v in (extra_aliases or {}).items():
        known[_despace(_fix(k))] = v
    return known


def _split_by_team(mid_despaced: str, known: dict, mode: str):
    """既知チームで名前/チームを分離。mode='suffix'（名前が先）/'prefix'（チームが先）。
    最長一致。戻り値 (name, team表示名) or None"""
    for k in sorted(known, key=len, reverse=True):
        if mode == "suffix" and mid_despaced.endswith(k) and len(mid_despaced) > len(k):
            return mid_despaced[: -len(k)], known[k]
        if mode == "prefix" and mid_despaced.startswith(k) and len(mid_despaced) > len(k):
            return mid_despaced[len(k):], known[k]
    return None


def _competition_ranks(rows):
    """[(name,team,goals)]（得点降順ソート済み）→ scorers配列（同点同順位）"""
    scorers, rank, prev = [], 0, None
    for i, (n, t, g) in enumerate(rows, start=1):
        if g != prev:
            rank, prev = i, g
        scorers.append({"rank": rank, "name": n, "team": t, "goals": g})
    return scorers


def _asof_from_pdf_url(pdf_url: str):
    m = re.search(r"/uploads/(\d{4})/(\d{2})/", pdf_url)
    return f"{m.group(1)}-{m.group(2)}" if m else None


# ── 茨城 ──────────────────────────────────────────────────────
IBARAKI_PAGE = "https://www.ibaraki-fa.jp/result/c2-match1/"


def discover_ibaraki():
    soup = _soup(IBARAKI_PAGE)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        fname = href.rsplit("/", 1)[-1].lower()
        if ("goalranking" in fname or "goallanking" in fname) \
                and "history" not in fname and f"{SEASON}_takamado" in fname:
            return urljoin(IBARAKI_PAGE, href), IBARAKI_PAGE
    raise RuntimeError(f"{SEASON}年のゴールランキングPDFリンクが見つからない")


def parse_ibaraki(lines, known):
    rows, asof, bad = [], None, 0
    for ln in lines:
        s = _fix(ln)
        m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日\s*現在", _despace(s))
        if m:
            asof = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        toks = s.split()
        if len(toks) < 2 or not toks[0].isdigit():
            continue
        # 末尾の得点（チーム名に数字が癒着することがある）
        last = toks[-1]
        if last.isdigit():
            goals, mid_toks = int(last), toks[1:-1]
        else:
            mm = re.fullmatch(r"(.+?)(\d+)", last)
            if not mm:
                continue
            goals, mid_toks = int(mm.group(2)), toks[1:-1] + [mm.group(1)]
        mid = _despace("".join(mid_toks))
        if not mid:
            continue
        hit = _split_by_team(mid, known, "suffix")
        if hit is None:
            bad += 1
            continue
        name, team = hit
        rows.append((name, team, goals))
    if len(rows) < 10:
        raise RuntimeError(f"解析行が少なすぎる（{len(rows)}行）")
    if bad > max(3, len(rows) * 0.2):
        raise RuntimeError(f"チーム名を特定できない行が多すぎる（{bad}行）")
    # 掲載順で得点が単調減少していること（誤読の検出）
    for a, b in zip(rows, rows[1:]):
        if b[2] > a[2]:
            raise RuntimeError(f"得点が昇順になっている行がある: {a} -> {b}")
    rows = [r for r in rows if not _is_og(r[0])]
    rows.sort(key=lambda r: -r[2])
    return _competition_ranks(rows), asof


# ── 福井 ──────────────────────────────────────────────────────
FUKUI_LIST = "https://www.fukui-fa.com/author/high-school/"


def discover_fukui():
    soup = _soup(FUKUI_LIST)
    page_url = None
    for a in soup.find_all("a", href=True):
        if f"リーグ{SEASON}福井" in _fix(a.get_text()):
            page_url = urljoin(FUKUI_LIST, a["href"])
            break
    if not page_url:
        raise RuntimeError(f"{SEASON}年のリーグページが見つからない")
    soup2 = _soup(page_url)
    for a in soup2.find_all("a", href=True):
        t = _despace(_fix(a.get_text()))
        if "F1" in t and "得点" in t:
            return urljoin(page_url, a["href"]), page_url
    raise RuntimeError("F1得点ランキングPDFリンクが見つからない")


def parse_fukui(lines, known):
    """得点列に迷い数字が混ざるため、順位グループから得点を復元する。
    各行の末尾数字列から候補集合を作り、グループ内全行の共通値のうち
    「下位グループの得点より大きい最小値」を採用。順位の等差も検証。"""
    groups = {}
    for ln in lines:
        d = _despace(_fix(ln))
        m = re.fullmatch(r"(\d+)([^\d]+?)(\d+)", d)
        if not m:
            continue
        rank, body, run = int(m.group(1)), m.group(2), m.group(3)
        hit = _split_by_team(body, known, "suffix")
        if hit is None:
            continue
        name, team = hit
        if _is_og(name):
            continue
        groups.setdefault(rank, []).append((name, team, run))
    if not groups or sum(len(v) for v in groups.values()) < 10:
        raise RuntimeError(f"解析行が少なすぎる（{sum(len(v) for v in groups.values())}行）")
    ranks = sorted(groups)
    if ranks[0] != 1:
        raise RuntimeError(f"先頭グループの順位が1でない: {ranks[0]}")
    for i, r in enumerate(ranks[:-1]):
        if r + len(groups[r]) != ranks[i + 1]:
            raise RuntimeError(f"順位グループの人数が不整合: rank{r}({len(groups[r])}人)の次がrank{ranks[i+1]}")
    goals_of, lower = {}, 0
    for r in reversed(ranks):
        cands = None
        for (_n, _t, run) in groups[r]:
            cs = {int(run)}
            if len(run) >= 2:
                cs.add(int(run[-1]))
                cs.add(int(run[-2:]))
            cands = cs if cands is None else (cands & cs)
        valid = sorted(v for v in cands if v > lower)
        if not valid:
            raise RuntimeError(f"rank{r}の得点を復元できない（候補{sorted(cands)}・下位={lower}）")
        goals_of[r] = valid[0]
        lower = valid[0]
    scorers = []
    for r in ranks:
        for (name, team, _run) in groups[r]:
            scorers.append({"rank": r, "name": name, "team": team, "goals": goals_of[r]})
    return scorers, None


# ── 三重 ──────────────────────────────────────────────────────
MIE_PAGE = "https://www.fa-mie.jp/category2/"
MIE_ALIASES = {
    "四中工": "四日市中央工業", "四日市中央工": "四日市中央工業",
    "四日市工": "四日市工業", "宇治山田商": "宇治山田商業",
    "三重②": "三重2nd", "三重高2nd": "三重2nd",
}


def discover_mie():
    soup = _soup(MIE_PAGE)
    best = None
    for a in soup.find_all("a", href=True):
        if ".pdf" not in a["href"].lower():
            continue
        text = _fix(a.get_text())
        ctx = _fix(a.find_parent("tr").get_text(" ")) if a.find_parent("tr") else text
        if "得点" not in text and "得点" not in ctx:
            continue
        score = 0
        if "1部" in text or "１部" in text:
            score = 3
        elif "1部" in ctx or "１部" in ctx:
            score = 2
        elif "得点" in text:
            score = 1
        if f"/{SEASON}/" in a["href"]:
            score += 1
        if best is None or score > best[0]:
            best = (score, urljoin(MIE_PAGE, a["href"]))
    if best is None or best[0] < 2:
        raise RuntimeError("1部の得点ランキングPDFリンクが見つからない")
    return best[1], MIE_PAGE


def parse_mie(lines, known):
    """構造が未確認のため汎用パーサ。行=順位/（氏名・チーム）/得点 を想定し、
    氏名・チームの並び順は既知チーム照合の成功数が多い向きを採用する。"""
    cand = []
    asof = None
    for ln in lines:
        s = _fix(ln)
        m = re.search(r"第\s*(\d+)\s*節", s)
        if m:
            asof = f"第{m.group(1)}節終了時点"
        toks = s.split()
        if len(toks) < 3 or not toks[0].isdigit() or not toks[-1].isdigit():
            continue
        cand.append((int(toks[0]), _despace("".join(toks[1:-1])), int(toks[-1])))
    if len(cand) < 8:
        raise RuntimeError(f"解析行が少なすぎる（{len(cand)}行）")
    results = {}
    for mode in ("suffix", "prefix"):
        rows = []
        for (rank, mid, goals) in cand:
            hit = _split_by_team(mid, known, mode)
            if hit:
                name, team = hit
                rows.append((rank, name, team, goals))
        results[mode] = rows
    mode = max(results, key=lambda k: len(results[k]))
    rows = results[mode]
    if len(rows) < max(8, len(cand) * 0.8):
        raise RuntimeError(f"チーム名を特定できる行が少ない（{len(rows)}/{len(cand)}行・mode={mode}）")
    for a, b in zip(rows, rows[1:]):
        if b[3] > a[3] or b[0] < a[0]:
            raise RuntimeError(f"順位・得点の並びが不正: {a} -> {b}")
    out = [(n, t, g) for (_r, n, t, g) in rows if not _is_og(n)]
    out.sort(key=lambda r: -r[2])
    return _competition_ranks(out), asof


# ── 愛媛 ──────────────────────────────────────────────────────
EHIME_LIST = f"https://efa.jp/meeting/second/?y={SEASON}"


def discover_ehime():
    soup = _soup(EHIME_LIST)
    page_url = None
    for a in soup.find_all("a", href=True):
        if f"リーグ{SEASON}愛媛" in _fix(a.get_text()):
            page_url = urljoin(EHIME_LIST, a["href"])
            break
    if not page_url:
        raise RuntimeError(f"{SEASON}年のEリーグページが見つからない")
    soup2 = _soup(page_url)
    for a in soup2.find_all("a", href=True):
        t = _despace(_fix(a.get_text()))
        if t.startswith("E1得点王") or ("E1" in t and "得点" in t):
            return urljoin(page_url, a["href"]), page_url
    raise RuntimeError("E1得点王PDFリンクが見つからない")


def parse_ehime(lines, known):
    rows, asof = [], None
    for ln in lines:
        s = _fix(ln)
        m = re.search(r"(\d{1,2})月\s*(\d{1,2})日\s*現在", _despace(s))
        if m:
            asof = f"{SEASON}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        mm = re.match(r"^\s*(\d+)\s*位\s+(.+?)\s+(\d+)\s*$", s)
        if not mm:
            continue
        rank, mid, goals = int(mm.group(1)), _despace(mm.group(2)), int(mm.group(3))
        hit = _split_by_team(mid, known, "prefix")  # チーム名が先
        if hit is None:
            continue
        name, team = hit
        if _is_og(name):
            continue
        rows.append((rank, name, team, goals))
    if not rows:
        raise RuntimeError("解析行が0件")
    rows.sort(key=lambda r: (r[0], -r[3]))
    out = _competition_ranks([(n, t, g) for (_r, n, t, g) in sorted(rows, key=lambda r: -r[3])])
    # 掲載順位と再計算順位の一致を検証（上位のみ掲載の小さな表なので厳格に）
    pdf_ranks = [r for (r, _n, _t, _g) in sorted(rows, key=lambda r: (-r[3], r[0]))]
    if pdf_ranks != [s["rank"] for s in out]:
        raise RuntimeError(f"順位の再計算が掲載と一致しない: {pdf_ranks}")
    return out, asof


# ── 設定と実行 ────────────────────────────────────────────────
PDF_PREFS = {
    "pref-ibaraki-1": dict(
        discover=discover_ibaraki, parse=parse_ibaraki, aliases=None,
        league=f"高円宮杯 JFA U-18 サッカーリーグ{SEASON} 茨城（IFAリーグ）1部 得点ランキング",
        label="茨城県サッカー協会 公式（PDF）",
        note="茨城県サッカー協会公式の得点者ランキング（PDF）より掲載しています。"),
    "pref-fukui-1": dict(
        discover=discover_fukui, parse=parse_fukui, aliases={"丸岡": "丸岡"},
        league=f"高円宮杯 JFA U-18 サッカーリーグ{SEASON} 福井（F1リーグ）1部 得点ランキング",
        label="福井県サッカー協会 公式（PDF）",
        note="福井県サッカー協会公式のF1リーグ得点ランキング（PDF）より掲載しています。"),
    "pref-mie-1": dict(
        discover=discover_mie, parse=parse_mie, aliases=MIE_ALIASES,
        league=f"高円宮杯 JFA U-18 サッカーリーグ{SEASON} 三重 1部 得点ランキング",
        label="三重県サッカー協会 公式（PDF）",
        note="三重県サッカー協会公式の［1部］得点ランキング（PDF）より掲載しています。"),
    "pref-ehime-1": dict(
        discover=discover_ehime, parse=parse_ehime, aliases=None,
        league=f"高円宮杯 JFA U-18 サッカーリーグ{SEASON} 愛媛（E1リーグ）1部 得点王",
        label="愛媛県サッカー協会 公式（PDF）",
        note="愛媛県サッカー協会公式の「E1リーグ得点王」（PDF）掲載分です。上位のみの掲載です。"),
}


def _update_pdf_one(slug: str, cfg: dict, today: str) -> str:
    path = DIR / f"{slug}.json"
    try:
        pdf_url, page_url = cfg["discover"]()
        r = _get(pdf_url)
        if len(r.content) > MAX_PDF_BYTES:
            raise RuntimeError(f"PDFが大きすぎる（{len(r.content)}バイト）")
        known = _known_teams(slug, cfg.get("aliases"))
        if not known:
            raise RuntimeError("既知チーム辞書が空（league_matches/scorersが読めない）")
        scorers, asof = cfg["parse"](_pdf_lines(r.content), known)
    except Exception as e:
        return f"  {slug}: 取得/解析失敗のためスキップ（既存維持）: {e}"
    if not scorers:
        return f"  {slug}: 得点者0件のためスキップ（既存維持）"
    obj = {
        "league": cfg["league"],
        "season": SEASON,
        "source": page_url,
        "sourceLabel": cfg["label"],
        "lastUpdated": asof or _asof_from_pdf_url(pdf_url) or today,
        "note": cfg["note"],
        "scorers": scorers[:MAX_ROWS],
    }
    new = json.dumps(obj, ensure_ascii=False, indent=2)
    if path.exists() and path.read_text(encoding="utf-8") == new:
        return f"  {slug}: 変更なし（{len(scorers)}名）"
    path.write_text(new, encoding="utf-8")
    top = scorers[0]
    return (f"  {slug}: 更新 {len(scorers)}名 1位={top['name']}({top['goals']}) "
            f"PDF={pdf_url.rsplit('/', 1)[-1]}")


def run(today: str):
    only = sys.argv[1:] if __name__ == "__main__" and len(sys.argv) > 1 else None
    msgs = []
    for slug, cfg in PDF_PREFS.items():
        if only and slug not in only:
            continue
        msgs.append(_update_pdf_one(slug, cfg, today))
    return msgs


def main():
    today = datetime.datetime.now(_JST).strftime("%Y-%m-%d")
    print("PDF県 得点ランキング 自動更新（茨城・福井・三重・愛媛）")
    for m in run(today):
        print(m)


if __name__ == "__main__":
    main()
