# -*- coding: utf-8 -*-
"""[2026-10-15] 階段状のシード（2回戦以上遅れて登場するシード）を含むトーナメント表(SVG)。

既存の generate_jyouth_page.render_bracket_svg は「全員が同じ段から始まる（シードは1段だけ）」前提で
県予選・インハイ・Jユース等すべての表に使われている。それを触らずに済むよう、
シードが2段以上遅れて入る大会（群馬の選手権など）だけがこの部品を使う。

入力 items（表の上から順）:
  ("match", A, B)     … 土台の回戦の1試合（A・Bとも校名）
  ("seed", 名前, d)   … 土台の回戦より d 回戦あとから登場するシード（d>=1）
並べ方は「左右に分けた表の、左の山の上から→右の山の上から」。隣り合う同じ段の枠どうしが当たる
（シフト・リデュース）ので、公式の組合せ表を上から写せば木が一意に決まる。
"""
import io as _io
import contextlib as _contextlib
import generate_jyouth_page as _J


def _build(items):
    """items → 木。各ノード：leaf={'leaf':名前,'out':段} / match={'kids':[x,y],'round':r,'out':r+1}"""
    stack = []
    for it in items:
        if it[0] == "match":
            node = {"kids": [{"leaf": it[1], "out": 0}, {"leaf": it[2], "out": 0}], "round": 0, "out": 1}
        else:
            node = {"leaf": it[1], "out": int(it[2])}
        stack.append(node)
        while len(stack) >= 2 and stack[-1]["out"] == stack[-2]["out"]:
            b = stack.pop()
            a = stack.pop()
            r = a["out"]
            stack.append({"kids": [a, b], "round": r, "out": r + 1})
    if len(stack) != 1 or "kids" not in stack[0]:
        return None
    return stack[0]


def render_staircase_bracket_svg(items, result_lines, round_names, rank_of=None, round_dates=None):
    # [2026-10-18] rank_of を渡すと校名の横に県内順位を出す（県ページ用）。渡さなければ従来と同一の出力。
    # [2026-10-19] round_dates＝列名のリスト→列ごとの日付のリストを返す関数（県ページ用）。列見出しの下に日付を出す。
    root = _build(items)
    if root is None:
        return ""
    R = root["round"] + 1                     # 回戦の数（決勝まで）
    if len(round_names) != R:
        return ""
    results = _J.collect_results({"_結果": result_lines})

    def winner_of(n):
        return n.get("leaf") or n.get("winner")

    def solve(n):
        if "leaf" in n:
            return
        for k in n["kids"]:
            solve(k)
        a, b = winner_of(n["kids"][0]), winner_of(n["kids"][1])
        n["a"], n["b"], n["score"], n["winner"] = a, b, None, None
        if a and b:
            r = results.get(frozenset((_J._norm_team(a), _J._norm_team(b))))
            if r:
                ra, ga, gb, pk, rb = r
                if _J._norm_team(ra) != _J._norm_team(a):
                    ga, gb, pk = gb, ga, ((pk[1], pk[0]) if pk else None)
                n["score"] = f"{ga}-{gb}" + (f"(PK{pk[0]}-{pk[1]})" if pk else "")
                if ga != gb:
                    n["winner"] = a if ga > gb else b
                elif pk:
                    n["winner"] = a if pk[0] > pk[1] else b
    solve(root)

    LABEL_W, LVL_W, ROW_H, TOP, CENTER_GAP = 190, 72, 28, 60, 168
    dates = list(round_dates(round_names)) if round_dates else []
    has_dates = any(dates)
    if has_dates:
        TOP += _J.DATE_ROW_H                 # 日付行を出すときだけ表を下げる
    wing_levels = R - 1
    width = 2 * (LABEL_W + wing_levels * LVL_W) + CENTER_GAP
    cx = width / 2
    xsL = [LABEL_W + (k + 1) * LVL_W for k in range(wing_levels)]
    GRAY, RED = "#94a3b8", "var(--danger-color,#dc2626)"
    SUB, ACC = "var(--text-light,#6b7280)", "var(--accent-color,#2563eb)"
    S = []
    rank_used = set()

    def line(x1, y1, x2, y2, c, w=1.6):
        S.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{c}" '
                 f'stroke-width="{w}" stroke-linecap="round"/>')

    def text(x, y, s, anchor, size=10.5, color=SUB, weight=""):
        w = f' font-weight="{weight}"' if weight else ""
        S.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="{size}" '
                 f'fill="{color}"{w}>{_J.html_escape(s)}</text>')

    def team_text(x, y, name, anchor, won=False):
        tid = _J.team_id_for(name)
        cls = "bk-won" if won else ("bk-acc" if tid else "bk-team")
        weight = ' font-weight="700"' if won else (' font-weight="600"' if tid else "")
        body = (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="12.5" '
                f'class="{cls}"{weight}>{_J.html_escape(_J._short_label(name))}'
                f'{_J.rank_tspan(name, rank_of, rank_used)}</text>')
        if tid:
            body = f'<a href="/teams/{tid}/">{body}</a>'
        S.append(body)

    # 行の割り当て（葉＝1行）と、各ノードの高さ yj
    def place(n, y):
        if "leaf" in n:
            n["yj"] = y + ROW_H / 2
            return y + ROW_H
        for k in n["kids"]:
            y = place(k, y)
        n["yj"] = (n["kids"][0]["yj"] + n["kids"][1]["yj"]) / 2
        return y

    semiL, semiR = root["kids"]
    endL = place(semiL, TOP)
    endR = place(semiR, TOP)
    # 左右の準決勝の高さをそろえる（短い側を下げる）
    d = semiL["yj"] - semiR["yj"]

    def shift(n, dy):
        n["yj"] += dy
        for k in n.get("kids", []):
            shift(k, dy)
    if d > 0:
        shift(semiR, d); endR += d
    elif d < 0:
        shift(semiL, -d); endL += -d
    height = max(endL, endR) + 28

    def draw(n, side, parent_round, won_parent):
        """n を描き、n から parent_round の縦線まで横線を引く"""
        sign = 1 if side == "L" else -1
        xs = xsL if side == "L" else [width - x for x in xsL]
        x_edge = LABEL_W if side == "L" else width - LABEL_W
        x_to = xs[parent_round] if parent_round < wing_levels else cx - sign * 10
        if "leaf" in n:
            team_text(x_edge - 5 * sign, n["yj"] + 3.5, n["leaf"], "end" if side == "L" else "start", won=won_parent)
            line(x_edge, n["yj"], x_to, n["yj"], RED if won_parent else GRAY, 2.4 if won_parent else 1.6)
            return
        r = n["round"]
        x = xs[r]
        k1, k2 = n["kids"]
        for k in (k1, k2):
            draw(k, side, r, bool(n["score"]) and n["winner"] == winner_of(k))
        line(x, k1["yj"], x, k2["yj"], GRAY)
        if n["score"] and n["winner"]:
            wk = k1 if n["winner"] == winner_of(k1) else k2
            line(x, wk["yj"], x, n["yj"], RED, 2.4)
            text(x + 3 * sign, n["yj"] - 4, n["score"], "start" if side == "L" else "end", 10.5, ACC, "700")
        red = bool(n["score"]) and bool(n["winner"]) and (parent_round < wing_levels or won_parent)
        line(x, n["yj"], x_to, n["yj"], RED if red else GRAY, 2.4 if red else 1.6)

    champ = root.get("winner") if root.get("score") else None
    draw(semiL, "L", wing_levels, bool(champ) and champ == winner_of(semiL))
    draw(semiR, "R", wing_levels, bool(champ) and champ == winner_of(semiR))

    for k in range(wing_levels):
        x0 = LABEL_W if k == 0 else xsL[k - 1]
        text((x0 + xsL[k]) / 2 + LVL_W / 2 - 8, 36, round_names[k], "middle", 12, SUB, "600")
        text(width - ((x0 + xsL[k]) / 2 + LVL_W / 2 - 8), 36, round_names[k], "middle", 12, SUB, "600")
    text(cx, 36, round_names[-1], "middle", 13, SUB, "700")
    if has_dates:
        for k in range(wing_levels):
            if dates[k]:
                x0 = LABEL_W if k == 0 else xsL[k - 1]
                text((x0 + xsL[k]) / 2 + LVL_W / 2 - 8, 51, dates[k], "middle", 10, SUB, "400")
                text(width - ((x0 + xsL[k]) / 2 + LVL_W / 2 - 8), 51, dates[k], "middle", 10, SUB, "400")
        if dates[-1]:
            text(cx, 51, dates[-1], "middle", 10, SUB, "400")

    ymid = (semiL["yj"] + semiR["yj"]) / 2
    lr = bool(champ) and champ == winner_of(semiL)
    rr = bool(champ) and champ == winner_of(semiR)
    line(cx - 10, semiL["yj"], cx - 10, ymid, RED if lr else GRAY, 2.4 if lr else 1.6)
    line(cx - 10, ymid, cx, ymid, RED if lr else GRAY, 2.4 if lr else 1.6)
    line(cx + 10, semiR["yj"], cx + 10, ymid, RED if rr else GRAY, 2.4 if rr else 1.6)
    line(cx, ymid, cx + 10, ymid, RED if rr else GRAY, 2.4 if rr else 1.6)
    if root.get("score"):
        text(cx, ymid + 16, root["score"], "middle", 13, ACC, "700")
    if champ:
        line(cx, ymid, cx, ymid - 30, RED, 2.4)
        text(cx, ymid - 38, f"🏆 {_J._short_label(champ)}", "middle", 15, RED, "700")

    svg = (f'<svg viewBox="0 0 {width:.0f} {height:.0f}" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="トーナメント表" preserveAspectRatio="xMidYMid meet" '
           f'style="display:block;width:100%;min-width:{width:.0f}px;height:auto;font-family:inherit;">'
           + "".join(S) + '</svg>')
    # 外枠・注記・文字色の切替は既存の表と同じものを使う（見た目をそろえる）
    return _J.wrap_bracket_svg(svg, rank_used)
