#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""選手権2026本大会の「日程と会場」（全47試合のマッチナンバー・日付・時刻・会場）を読む（2026-11-17 新設）。

- 正本: data/tournaments/senshuken-final-2026.md の「## 日程と会場（マッチナンバー）」47行
    - 【3】12/29 12:05 とどろき：5 vs 6        … 数字＝抽選番号（1〜48）
    - 【18】12/31 12:05 とどろき：【2】 vs 【3】 … 【数字】＝その試合の勝者
- 抽選番号と「## トーナメント表（組み合わせ）」32行の対応は第104回と同じ型（8行×A〜D）:
    1 / 2 / 3vs4 / 5vs6 / 7vs8 / 9vs10 / 11 / 12（＋12ずつ）
- 安全装置: 47試合そろい・番号の重複なし・どの試合もトーナメント表の山（隣どうしの枠）と一致、の全部を満たすときだけ
  日程を返す。1つでも食い違えば None を返して [要確認]（日程は出さない＝間違った会場を載せない）。
- 使う側: generate_senshuken_page.py（特設ページの全試合日程と1回戦カードの印）、senshuken_badge.py（チームページ）。
"""
import re

VENUES = {
    "国立": "MUFGスタジアム（国立競技場）",
    "駒沢": "駒沢陸上競技場",
    "西が丘": "味の素フィールド西が丘",
    "とどろき": "Uvanceとどろきスタジアム by Fujitsu",
    "三ツ沢": "ニッパツ三ツ沢球技場",
    "埼玉スタジアム": "埼玉スタジアム２００２",
    "NACK5": "NACK5スタジアム大宮",
    "フクダ電子アリーナ": "フクダ電子アリーナ",
    "柏の葉": "県立柏の葉公園総合競技場",
}
DAYS = [  # (日付, 曜日, 回戦)
    ("12/28", "月", "開幕戦（1回戦）"),
    ("12/29", "火", "1回戦"),
    ("12/31", "木", "2回戦"),
    ("1/2", "土", "3回戦"),
    ("1/4", "月", "準々決勝"),
    ("1/9", "土", "準決勝"),
    ("1/11", "月・祝", "決勝"),
]
DAY_INFO = {d: (w, r) for d, w, r in DAYS}
N_MATCHES = 47
LINE_RE = re.compile(r"^\s*-\s*【(\d+)】\s*(\d{1,2}/\d{1,2})\s+(\d{1,2}:\d{2})\s+(.+?)\s*[:：]\s*(\S+)\s+vs\s+(\S+)\s*$")


def draw_rows():
    """抽選番号 → トーナメント表の行番号（0〜31）。"""
    out = {}
    for k in range(4):
        base, r0 = 12 * k, 8 * k
        layout = [[1], [2], [3, 4], [5, 6], [7, 8], [9, 10], [11], [12]]
        for j, nums in enumerate(layout):
            for n in nums:
                out[base + n] = r0 + j
    return out


def _side(tok):
    m = re.fullmatch(r"【(\d+)】", tok)
    if m:
        return ("win", int(m.group(1)))
    if tok.isdigit():
        return ("draw", int(tok))
    return None


def load(sections, rows):
    """(matches, problems)。matches＝{番号: dict}。problems が1つでもあれば matches は None。
    dict: no, day, wday, round, time, venue, venue_full, sides=[("draw",n)|("win",m)]×2, rows=覆う行の集合"""
    key = next((k for k in sections if k.startswith("日程と会場")), None)
    if key is None:
        return None, []  # まだ書いていない＝黙って出さない
    probs, matches = [], {}
    for ln in sections[key]:
        if not ln.strip().startswith("- "):
            continue
        m = LINE_RE.match(ln)
        if not m:
            probs.append(f"読めない行: {ln.strip()}")
            continue
        no, day, tm, venue, a, b = m.groups()
        no = int(no)
        sides = [_side(a), _side(b)]
        if None in sides:
            probs.append(f"【{no}】の対戦が読めない: {a} vs {b}")
            continue
        if day not in DAY_INFO:
            probs.append(f"【{no}】の日付 {day} が大会日程に無い")
            continue
        if venue not in VENUES:
            probs.append(f"【{no}】の会場「{venue}」が会場一覧に無い")
            continue
        if no in matches:
            probs.append(f"【{no}】が2回ある")
            continue
        matches[no] = {"no": no, "day": day, "wday": DAY_INFO[day][0], "round": DAY_INFO[day][1], "time": tm,
                       "venue": venue, "venue_full": VENUES[venue], "sides": sides}
    if sorted(matches) != list(range(1, N_MATCHES + 1)):
        probs.append(f"試合が{len(matches)}件（【1】〜【{N_MATCHES}】がそろっていない）")
    drows = draw_rows()
    used_draw = [s[1] for mt in matches.values() for s in mt["sides"] if s[0] == "draw"]
    used_win = [s[1] for mt in matches.values() for s in mt["sides"] if s[0] == "win"]
    if sorted(used_draw) != list(range(1, 49)):
        probs.append("抽選番号1〜48がちょうど1回ずつ出てこない")
    if sorted(used_win) != list(range(1, N_MATCHES)):
        probs.append("勝者の参照【1】〜【46】がちょうど1回ずつ出てこない")
    if probs:
        return None, probs

    cells = [[x.strip() for x in re.split(r"\s+vs\s+", ln.strip()[2:].strip()) if x.strip()] for ln in rows]

    def cover(side, seen=()):
        kind, n = side
        if kind == "draw":
            return {drows[n]}
        if n in seen or n not in matches:
            raise ValueError(f"【{n}】の参照が循環・欠落")
        mt = matches[n]
        return cover(mt["sides"][0], seen + (n,)) | cover(mt["sides"][1], seen + (n,))

    for no in sorted(matches):
        mt = matches[no]
        try:
            A, B = cover(mt["sides"][0]), cover(mt["sides"][1])
        except ValueError as e:
            probs.append(str(e))
            continue
        if all(s[0] == "draw" for s in mt["sides"]) and A == B:
            r = next(iter(A))
            if len(cells[r]) != 2:
                probs.append(f"【{no}】は1回戦なのに、トーナメント表の{r + 1}行目が「A vs B」でない")
            ok = True
        else:
            ok = (len(A) == len(B) and max(A) - min(A) + 1 == len(A) and max(B) - min(B) + 1 == len(B)
                  and min(min(A), min(B)) % (2 * len(A)) == 0 and abs(min(A) - min(B)) == len(A))
        if not ok:
            probs.append(f"【{no}】の対戦がトーナメント表の山と合わない")
        mt["rows"] = A | B
    if probs:
        return None, probs
    return matches, []


def by_row(matches, rows):
    """(1回戦: {行: 試合}, 2回戦: {行: 試合})。2回戦の辞書はその試合に出る2行どちらからも引ける。"""
    first, second = {}, {}
    for mt in matches.values():
        rs = sorted(mt["rows"])
        if len(rs) == 1:
            first[rs[0]] = mt
        elif len(rs) == 2:
            for r in rs:
                second[r] = mt
    return first, second


def when(mt, venue=True):
    """「12/29（火）12:05・とどろき」"""
    s = f"{mt['day']}（{mt['wday']}）{mt['time']}"
    return f"{s}・{mt['venue']}" if venue else s
