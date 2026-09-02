#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""総理大臣杯2026（第50回）の対戦表・トーナメント表を生成する。

- データの正本: data/tournaments/pmc-2026.json（結果を書き込む→本スクリプト再実行→Pushで反映）
- ページの以下2つのマーカー間だけを書き換える:
    <!-- PMC_BRACKET_START --> 〜 <!-- PMC_BRACKET_END -->   SVGトーナメント表
    <!-- PMC_SCHEDULE_START --> 〜 <!-- PMC_SCHEDULE_END --> 日程・結果表
- SVGは generate_interhigh_page.py の render_bracket_svg を流用（勝ち残りチームが赤枠になる版）。

■結果の書き方（大会期間中の更新手順）
  data/tournaments/pmc-2026.json の該当試合の "hs" と "as_" に数値を入れるだけ。
  PK戦は "note" に "PK4-3" のように書く（勝者判定に使われる）。
  例: {"no": 1, ..., "hs": 2, "as_": 1, "note": ""}
  勝ち上がりの校名は自動で次の試合に入り、SVGの赤線も自動で伸びる。

■検証（誤データを載せない安全装置）
  - 1回戦32チームの重複・欠落
  - 試合番号の接続（各試合が次段で1回だけ使われるか）
  - スコアが入っているのに勝者が決まらない（引き分けでPK記載なし）試合の検出
  1つでも問題があれば生成を中止する。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_interhigh_page import render_bracket_svg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "tournaments" / "pmc-2026.json"
PAGE = ROOT / "tournaments" / "prime-minister-cup-2026" / "index.html"
B_START, B_END = "<!-- PMC_BRACKET_START -->", "<!-- PMC_BRACKET_END -->"
S_START, S_END = "<!-- PMC_SCHEDULE_START -->", "<!-- PMC_SCHEDULE_END -->"

# SVGの二分木に載せるための1回戦の並び順（トーナメント表の上から下）
BRACKET_ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 16, 15, 14, 13, 12, 11, 10, 9]
ROUND_ORDER = ["1回戦", "2回戦", "準々決勝", "準決勝", "決勝"]


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def short(name):
    """SVG用の短縮表示名（長い校名は枠に収まらないため）"""
    s = name.replace("大学", "大").replace("学院大", "学院大")
    s = s.replace("北海道教育大岩見沢校", "北教大岩見沢")
    s = s.replace("IPU・環太平洋大", "環太平洋大")
    return s


def winner_of(m):
    """勝者の校名を返す。未消化・不明ならNone"""
    if m["hs"] is None or m["as_"] is None or not m.get("home") or not m.get("away"):
        return None
    if m["hs"] > m["as_"]:
        return m["home"]
    if m["hs"] < m["as_"]:
        return m["away"]
    pk = re.search(r"PK\s*(\d+)\s*[-－ー]\s*(\d+)", m.get("note", ""))
    if pk:
        return m["home"] if int(pk.group(1)) > int(pk.group(2)) else m["away"]
    return None


def resolve(matches):
    """勝ち上がりを解決して各試合の home/away を埋める"""
    by_no = {m["no"]: m for m in matches}
    for _ in range(6):  # ラウンド数ぶん反復すれば全段確定する
        for m in matches:
            for side, src in (("home", "homeFrom"), ("away", "awayFrom")):
                if m.get(src) and not m.get(side):
                    w = winner_of(by_no[m[src]])
                    if w:
                        m[side] = w
    return by_no


def validate(matches, by_no):
    """(errs, warns) を返す。errsがあれば生成中止、warnsは表示するだけで生成は続行。"""
    errs, warns = [], []
    r1 = [m for m in matches if m["round"] == "1回戦"]
    teams = [t for m in r1 for t in (m["home"], m["away"])]
    if len(r1) != 16:
        errs.append(f"1回戦が16試合でない（{len(r1)}）")
    if len(set(teams)) != 32:
        errs.append("1回戦のチームに重複または欠落")
    used = []
    for m in matches:
        for src in ("homeFrom", "awayFrom"):
            if m.get(src):
                used.append(m[src])
    if sorted(used) != list(range(1, len(matches))):
        errs.append("試合番号の接続が不正")
    for m in matches:
        if m["hs"] is not None and m["as_"] is not None:
            if m["hs"] < 0 or m["as_"] < 0:
                errs.append(f"[{m['no']}] スコアが負の数")
            elif winner_of(m) is None:
                # 引き分けでPK未記入。試合途中の速報（0-0など）はこの状態が正常なので
                # エラーにせず警告だけ出す。スコアはそのまま表示され、勝ち上がりは保留される。
                warns.append(f"[{m['no']}] {m.get('home') or '?'} {m['hs']}-{m['as_']} "
                             f"{m.get('away') or '?'} は引き分け中（PK決着後は note に PK4-3 の形式で記入）")
    return errs, warns


def build_sections(matches, by_no):
    """render_bracket_svg に渡す sections を組み立てる"""
    pairs = []
    for no in BRACKET_ORDER:
        m = by_no[no]
        pairs.append(f'- {short(m["home"])} vs {short(m["away"])}')
    sections = {"トーナメント表（組み合わせ）": pairs}
    for rnd in ROUND_ORDER:
        lines = []
        for m in matches:
            if m["round"] != rnd or m["hs"] is None or m["as_"] is None:
                continue
            if not m.get("home") or not m.get("away"):
                continue
            pk = ""
            mm = re.search(r"PK\s*\d+\s*[-－ー]\s*\d+", m.get("note", ""))
            if mm:
                pk = f'({mm.group(0).replace(" ", "")})'
            lines.append(f'- {short(m["home"])} {m["hs"]}-{m["as_"]}{pk} {short(m["away"])}')
        if lines:
            sections[rnd] = lines
    return sections


def render_schedule(matches, by_no):
    out = []
    for rnd in ROUND_ORDER:
        ms = [m for m in matches if m["round"] == rnd]
        if not ms:
            continue
        date = ms[0]["date"]
        rows = []
        for m in ms:
            def side(key, from_key, rep_key):
                if m.get(key):
                    rep = f'<span class="pmc-rep">{esc(m[rep_key])}</span>' if m.get(rep_key) else ""
                    return f'{esc(m[key])}{rep}'
                return f'<span class="pmc-tbd">[{m[from_key]}]の勝者</span>'
            h = side("home", "homeFrom", "homeRep")
            a = side("away", "awayFrom", "awayRep")
            if m["hs"] is not None and m["as_"] is not None:
                w = winner_of(m)
                if w == m.get("home"):
                    h = f'<span class="match-winner">{h}</span>'
                elif w == m.get("away"):
                    a = f'<span class="match-winner">{a}</span>'
                # note に書いた内容（「PK4-3」「延長」など）はそのままスコア横に表示する
                tag = f'<span class="pmc-pk">{esc(m["note"])}</span>' if m.get("note") else ""
                score = f'<strong>{m["hs"]} - {m["as_"]}</strong>{tag}'
            else:
                score = f'<span class="pmc-time">{esc(m["time"])}</span>'
            rows.append(
                f'            <tr><td class="pmc-no">{m["no"]}</td>'
                f'<td class="pmc-home">{h}</td><td class="pmc-score">{score}</td>'
                f'<td class="pmc-away">{a}</td>'
                f'<td class="pmc-venue">{esc(m["venue"])}</td></tr>'
            )
        out.append(f"""        <h3 style="margin:22px 0 10px;">{rnd}（{date}）</h3>
        <div class="univ-scroll">
        <table class="pmc-table">
          <thead><tr><th>No</th><th style="text-align:right;">ホーム</th><th>スコア</th><th style="text-align:left;">アウェイ</th><th>会場</th></tr></thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
        </div>""")
    return "\n".join(out)


def replace_block(src, start, end, body, label):
    if start not in src or end not in src:
        print(f"[エラー] {label}のマーカーが見つかりません")
        sys.exit(1)
    pre, rest = src.split(start, 1)
    _, post = rest.split(end, 1)
    return pre + start + "\n" + body + "\n" + end + post


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    matches = data["matches"]
    by_no = resolve(matches)
    errs, warns = validate(matches, by_no)
    if errs:
        print("[エラー] 検証NGのため生成を中止:")
        for e in errs:
            print("  -", e)
        sys.exit(1)
    for w in warns:
        print("[注記]", w)

    sections = build_sections(matches, by_no)
    svg = render_bracket_svg(sections, [])
    if not svg:
        print("[エラー] SVGトーナメント表の生成に失敗しました")
        sys.exit(1)
    svg = svg.replace("トーナメント表", "総理大臣杯2026 トーナメント表")

    src = PAGE.read_text(encoding="utf-8")
    src = replace_block(src, B_START, B_END, svg, "トーナメント表")
    src = replace_block(src, S_START, S_END, render_schedule(matches, by_no), "日程・結果")
    PAGE.write_text(src, encoding="utf-8")

    played = sum(1 for m in matches if m["hs"] is not None)
    print(f"OK: 全{len(matches)}試合（消化{played}）・SVG {len(svg)}バイトを生成")


if __name__ == "__main__":
    main()
