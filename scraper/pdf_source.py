#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF出典の「下ごしらえ」共通層（2026-09-14 新設）
================================================

県協会がPDFで公開しているリーグ戦データを読むための共通部分。
**共通にするのは次の4つまで**（2026-09-14 Kei方針）:

  1. 入口ページからPDFのURLを辿る（URL固定は禁止。ハッシュ名・版ごとに変わる）
  2. PDFを取得する（リトライ）
  3. 版日付（`2026/9/13` など）を取り出す
  4. pdfplumber で開いて「行」または「表」に復元する

**「どの列が何か」「節と日付をどう結ぶか」「1部をどう切り出すか」は県ごとのパーサに書く。**
これまでのPDF県は形がそれぞれ違う（岡山=左右段組み／大分=3段重ねの星取表／
秋田=結合セルの表）ので、読み取りまで共通化すると1県の都合で他県が壊れる。

⚠️ ここを変えたら、使っている県（岡山・秋田）の出力が変わらないことを
   /tmp で生成物 diff して確かめること（構文チェックでは足りない）。
"""
import io
import re
import time

import requests

_VERSION_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


# ---------------------------------------------------------------------------
# 1. 入口ページからPDFのURLを辿る
# ---------------------------------------------------------------------------
def pdf_link_after_heading(soup, heading: str) -> str:
    """見出しテキストの直後に出てくる最初のPDFリンク（岡山方式）。"""
    node = soup.find(string=re.compile(re.escape(heading)))
    if node is None:
        raise RuntimeError(f"入口ページに見出し {heading!r} が無い")
    for a in node.parent.find_all_next("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            return a["href"]
    raise RuntimeError("見出しの後にPDFリンクが無い")


def pdf_link_by_text(soup, predicate, label: str) -> str:
    """リンク文字（空白を詰めたもの）が predicate を満たすPDFリンク。ちょうど1件でなければ失敗。"""
    hits = []
    for a in soup.find_all("a", href=True):
        if not a["href"].lower().endswith(".pdf"):
            continue
        text = re.sub(r"\s+", "", a.get_text())
        if predicate(text):
            hits.append(a["href"])
    hits = list(dict.fromkeys(hits))
    if len(hits) != 1:
        raise RuntimeError(f"入口ページに{label}のPDFリンクが{len(hits)}件（1件のはず）")
    return hits[0]


# ---------------------------------------------------------------------------
# 2. 取得
# ---------------------------------------------------------------------------
def fetch_pdf(url: str, headers: dict, timeout: int, retries: int = 3, wait: float = 1.5) -> bytes:
    last = None
    for _ in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            last = e
            time.sleep(wait)
    raise RuntimeError(f"{url} の取得に失敗 ({last})")


def open_pdf(content: bytes):
    """pdfplumber で開く（with 文で使う）"""
    import pdfplumber
    return pdfplumber.open(io.BytesIO(content))


# ---------------------------------------------------------------------------
# 3. 版日付
# ---------------------------------------------------------------------------
def version_date(text: str) -> str | None:
    """テキスト中の最初の `YYYY/M/D` を `YYYY-MM-DD` で返す。無ければ None。
    ✅ 版日付ガード（版日付より後の日付を持つ消化済み試合があれば据え置く）に使う。"""
    m = _VERSION_RE.search(text or "")
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


_LABEL_YMD_RE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_LABEL_MD_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})(?!\d)")


def version_from_label(text: str, season_year: int | str | None = None) -> str | None:
    """ファイル名やリンク文字に埋め込まれた版日付を `YYYY-MM-DD` で返す（2026-09-15追加）。

      `t20260913.pdf`（徳島）            … 年入り8桁 → そのまま確定
      `0913-U-18県リーグ….pdf`（兵庫）   … 4桁の月日 → season_year を補う
      `2026_日程…(0913更新)`（秋田）     … 同上
    年入り8桁を優先し、無ければ（season_year が渡されたときだけ）4桁の月日を探す。
    月日として成り立たない数字（`2026` など）は読み飛ばす。見つからなければ None。
    ⚠️ 年なしの月日は「シーズン年のもの」とみなしている。年をまたぐリーグでは県側で補正すること。"""
    s = text or ""
    for m in _LABEL_YMD_RE.finditer(s):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y}-{mo:02d}-{d:02d}"
    if season_year is None:
        return None
    for m in _LABEL_MD_RE.finditer(s):
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{int(season_year)}-{mo:02d}-{d:02d}"
    return None


# ---------------------------------------------------------------------------
# 4. 行・表への復元
# ---------------------------------------------------------------------------
def page_rows(page, row_tol: float, x_max: float | None = None,
              top_min: float | None = None) -> list[list[tuple[float, str]]]:
    """単語を top の許容差でクラスタして行にし、各行を [(x0, text), …]（x順）で返す。

    x_max   … x0 がこれ未満の単語だけ使う（段組みの左段だけ取る）
    top_min … top がこれより大きい単語だけ使う（ページ上部の見出しを除く）
    ⚠️ クラスタの基準は「その行の最初の単語の top」（岡山の実装と同じ。変えると岡山の出力が変わる）。
    ⚠️ 文字列に潰さずに x を返すのは、行によって列の有無が変わるPDF（会場・当番が入る行／入らない行）で
       列を判定できるようにするため。"""
    ws = [w for w in page.extract_words()
          if (x_max is None or w["x0"] < x_max) and (top_min is None or w["top"] > top_min)]
    ws.sort(key=lambda w: (w["top"], w["x0"]))
    groups, cur, base = [], [], None
    for w in ws:
        if base is None or abs(w["top"] - base) <= row_tol:
            cur.append(w)
            base = w["top"] if base is None else base
        else:
            groups.append(cur)
            cur, base = [w], w["top"]
    if cur:
        groups.append(cur)
    return [[(x["x0"], x["text"]) for x in sorted(g, key=lambda y: y["x0"])] for g in groups]


def page_row_texts(page, row_tol: float, x_max: float | None = None,
                   top_min: float | None = None) -> list[str]:
    """page_rows を1行＝1文字列（空白区切り）にした薄いラッパー。"""
    return [" ".join(t for _x, t in row) for row in page_rows(page, row_tol, x_max, top_min)]


def page_tables(page) -> list[list[list]]:
    """罫線から表を復元する（pdfplumber の extract_tables）。
    ✅ 結合セルの値は**結合範囲の先頭行**に入り、以降の行は None になる。
       文字の y 座標は結合セルの縦中央に来るので、座標で前方補完するより確実（秋田で実測）。"""
    return page.extract_tables()
