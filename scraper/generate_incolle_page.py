#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""インカレ2026（第75回 全日本大学サッカー選手権）の組み合わせ・結果・順位表・トーナメント表を生成する。

- データの正本: data/tournaments/incolle-2026.json（全62試合。番号はJUFA日程表のM No.）
- ページの次のマーカーの間だけを書き換える（sitemap など他のファイルには触らない）:
    <!-- INCOLLE_ROUNDS_START --> 〜 <!-- INCOLLE_ROUNDS_END -->
  中身＝大会の流れの図／予選ラウンド／決勝ラウンド（グループの順位表・試合）／
        準々決勝〜決勝（SVGトーナメント表・試合）／強化ラウンド（グループの順位表・試合・準決勝・決勝）
- SVGは generate_interhigh_page.py の render_bracket_svg を流用（総理大臣杯と同じ見た目）。

■結果の書き方（大会期間中の更新手順）
  data/tournaments/incolle-2026.json の該当試合（"no" が日程表の[番号]）の
  "hs"（左のチームの得点）と "as_"（右のチームの得点）に数字を入れて push するだけ。
    例: {"no": 10, ..., "hs": 1, "as_": 2, "note": ""}
  - 予選・準々決勝〜決勝・強化ラウンドの準決勝/決勝で引き分けのときは、"note" に "PK4-3" のように書く
    （延長で決まったときは "延長" と書けば表のスコアの横に出る）。PKが無いと勝ち上がりは保留される。
  - グループの試合は90分で終わり、引き分けはそのまま（PKは無い）。
  勝ち上がりは自動：予選[n]の勝者→決勝ラウンドの「予選[n]勝者」の枠、敗者→強化ラウンドの「予選[n]敗者」の枠。
  決勝ラウンドの各グループの6試合が全部入ると、1位・2位が準々決勝の枠に入り、SVGの赤線も伸びる。

■グループの順位の決め方（開催要項 第13条3項(3)IV・4項(3)III）
  勝点 → 得失点差 → 総得点 → 当該チーム間の対戦成績（勝点→得失点差→総得点）→ 反則ポイント → 抽選。
  このスクリプトは「当該チーム間」までを計算する。それでも並ぶ（反則ポイント・抽選で決まる）ときは
  準々決勝の枠に入れず、[注記] を出す。そのときは JUFA の発表どおりに "groupRank" に書く:
    "groupRank": {"A": ["国士舘大学", "明治大学", "関西大学", "中京大学"]}
  書いた組はその並びが最優先になる（4チームちょうどでないと生成を止める）。強化ラウンドは "1"〜"3"。

■強化ラウンドの準決勝[45][46]は手で書く
  組み合わせ（1位相当 vs ワイルドカード／3位相当 vs 2位相当。開催要項 第19条3項(2)）は
  反則ポイントを使って決まるため計算しない。JUFAの発表を見て [45][46] の "home" "away" に大学名を書く。
  決勝[47]は準決勝の勝者が自動で入る。

■検証（誤データを載せない安全装置）。1つでも問題があれば生成を中止する。
  - 試合が62（予選10・決勝GS24・準々決勝4・準決勝2・決勝1・強化GS18・強化準決勝2・強化決勝1）、番号1〜62の重複・欠落
  - 勝ち上がりの枠（予選の勝者・敗者、グループ順位、前の試合の勝者）が決まった回数だけ使われているか
  - 各グループが4チーム×6試合か、出場28チームの重複・欠落
  - 得点が片方だけ・負の数、groupRank が4チームの並びになっていない、強化準決勝の大学名が強化ラウンドの12チームに無い
  勝ち上がりのある試合が引き分けでPK未記入のときは [注記] だけ出して続ける（試合中の速報0-0を入れられるように。総理大臣杯と同じ）。
"""
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_interhigh_page import render_bracket_svg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "tournaments" / "incolle-2026.json"
PAGE = ROOT / "tournaments" / "incolle-2026" / "index.html"
START, END = "<!-- INCOLLE_ROUNDS_START -->", "<!-- INCOLLE_ROUNDS_END -->"

STAGE_COUNT = {"予選": 10, "決勝GS": 24, "準々決勝": 4, "準決勝": 2, "決勝": 1,
               "強化GS": 18, "強化準決勝": 2, "強化決勝": 1}
KO_STAGES = ("予選", "準々決勝", "準決勝", "決勝", "強化準決勝", "強化決勝")
FINAL_GROUPS = {"A": "東京・神奈川", "B": "福岡・大分", "C": "愛知", "D": "大阪"}
STRENGTH_GROUPS = {"1": "フクダ電子フィールドA面", "2": "フクダ電子フィールドB面", "3": "フクダ電子スクエア"}
BRACKET_ORDER = [56, 57, 58, 59]   # 左の山＝[56][57]→準決勝[60]、右の山＝[58][59]→準決勝[61]


def esc(s):
    return html.escape(str(s), quote=True)


def short(name):
    return (name or "").replace("大学", "大")


# ---------------------------------------------------------------------------
# 勝ち上がりの解決
# ---------------------------------------------------------------------------

def scored(m):
    return m["hs"] is not None and m["as_"] is not None


def winner_of(m):
    if not scored(m) or not m.get("home") or not m.get("away"):
        return None
    if m["hs"] > m["as_"]:
        return m["home"]
    if m["hs"] < m["as_"]:
        return m["away"]
    pk = re.search(r"PK\s*(\d+)\s*[-－ー]\s*(\d+)", m.get("note", ""))
    if pk and int(pk.group(1)) != int(pk.group(2)):
        return m["home"] if int(pk.group(1)) > int(pk.group(2)) else m["away"]
    return None


def loser_of(m):
    w = winner_of(m)
    if not w:
        return None
    return m["away"] if w == m["home"] else m["home"]


def group_members(matches, stage, g):
    """グループの4チーム（決まっていれば大学名、まだなら枠の記号）を登場順に"""
    out = []
    for m in matches:
        if m["stage"] == stage and m.get("group") == g:
            for side in ("home", "away"):
                k = m.get(side) or m.get(side + "From")
                if k not in out:
                    out.append(k)
    # シードの大学（最初から名前が決まっている）を先に、予選の枠は番号順に（組み合わせ表と同じ並び）
    slot_no = {k: int(m.get(s + "From")[1:]) for m in matches for s in ("home", "away")
               if m["stage"] == stage and m.get("group") == g and m.get(s + "From") and m.get(s) == k}
    return sorted(out, key=lambda k: (k in slot_no or (k[:1] in "WL" and k[1:].isdigit()),
                                      slot_no.get(k, int(k[1:]) if k[:1] in "WL" and k[1:].isdigit() else 0)))


def standings(matches, stage, g, data):
    """(rows, status) を返す。rows=[{key,name,p,w,d,l,gf,ga,gd,pts,tied}]（順位順）
    status: "empty"（0試合）/"live"（途中）/"done"（6試合終了・順位確定）/"tie"（終了したが反則ポイント等で決まる並びが残る）/"official"（groupRank）"""
    ms = [m for m in matches if m["stage"] == stage and m.get("group") == g]
    keys = group_members(matches, stage, g)
    name_of = {}
    for m in ms:
        for side in ("home", "away"):
            k = m.get(side) or m.get(side + "From")
            if m.get(side):
                name_of[k] = m[side]
    st = {k: {"key": k, "name": name_of.get(k), "p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0} for k in keys}
    played = [m for m in ms if scored(m) and m.get("home") and m.get("away")]
    for m in played:
        h, a = st[m["home"]], st[m["away"]]
        for r, f, ag in ((h, m["hs"], m["as_"]), (a, m["as_"], m["hs"])):
            r["p"] += 1
            r["gf"] += f
            r["ga"] += ag
            r["w" if f > ag else "d" if f == ag else "l"] += 1
    for r in st.values():
        r["gd"] = r["gf"] - r["ga"]
        r["pts"] = 3 * r["w"] + r["d"]
        r["tied"] = False

    rows = list(st.values())
    off = (data.get("groupRank") or {}).get(g if stage == "決勝GS" else str(g))
    if off:
        order = {n: i for i, n in enumerate(off)}
        rows.sort(key=lambda r: order.get(r["name"], 99))
        return rows, "official"
    if not played:
        return rows, "empty"

    def base(r):
        return (r["pts"], r["gd"], r["gf"])
    rows.sort(key=base, reverse=True)
    # 勝点・得失点差・総得点が並んだチームだけで、当該チーム間の対戦成績を見る
    out, i = [], 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and base(rows[j + 1]) == base(rows[i]):
            j += 1
        cl = rows[i:j + 1]
        if len(cl) > 1:
            names = {r["name"] for r in cl if r["name"]}
            mini = {r["name"]: [0, 0, 0] for r in cl}
            for m in played:
                if m["home"] in names and m["away"] in names:
                    for n, f, ag in ((m["home"], m["hs"], m["as_"]), (m["away"], m["as_"], m["hs"])):
                        mini[n][0] += 3 if f > ag else 1 if f == ag else 0
                        mini[n][1] += f - ag
                        mini[n][2] += f
            cl.sort(key=lambda r: tuple(mini.get(r["name"], [0, 0, 0])), reverse=True)
            for a in range(len(cl)):
                for b in range(len(cl)):
                    if a != b and mini.get(cl[a]["name"]) == mini.get(cl[b]["name"]):
                        cl[a]["tied"] = True
        out += cl
        i = j + 1
    done = len(played) == 6
    if not done:
        return out, "live"
    return out, ("tie" if any(r["tied"] for r in out) else "done")


def group_slot(matches, data, g, rank):
    """決勝ラウンド「Aグループ1位」の大学名。まだ決まらなければ None"""
    rows, status = standings(matches, "決勝GS", g, data)
    if status == "official":
        return rows[rank - 1]["name"]
    if status in ("done", "tie"):
        r = rows[rank - 1]
        return None if r["tied"] else r["name"]
    return None


def resolve(matches, data):
    by_no = {m["no"]: m for m in matches}
    for _ in range(8):
        for m in matches:
            for side in ("home", "away"):
                src = m.get(side + "From")
                if not src or m.get(side):
                    continue
                if src[0] in "WL" and src[1:].isdigit():
                    prev = by_no[int(src[1:])]
                    v = winner_of(prev) if src[0] == "W" else loser_of(prev)
                else:
                    v = group_slot(matches, data, src[0], int(src[1]))
                if v:
                    m[side] = v
    return by_no


# ---------------------------------------------------------------------------
# 検証
# ---------------------------------------------------------------------------

def validate(raw_matches, data):
    errs, warns = [], []
    nos = sorted(m["no"] for m in raw_matches)
    if nos != list(range(1, 63)):
        errs.append("試合番号が1〜62になっていない（重複または欠落）")
    for st, n in STAGE_COUNT.items():
        c = sum(1 for m in raw_matches if m["stage"] == st)
        if c != n:
            errs.append(f"{st}が{n}試合でない（{c}）")
    want = {}
    for i in range(1, 11):
        want[f"W{i}"] = 3
        want[f"L{i}"] = 3
    for g in "ABCD":
        want[f"{g}1"] = want[f"{g}2"] = 1
    for n in (45, 46, 56, 57, 58, 59, 60, 61):
        want[f"W{n}"] = 1
    used = {}
    for m in raw_matches:
        for side in ("home", "away"):
            f = m.get(side + "From")
            if f:
                used[f] = used.get(f, 0) + 1
    if used != want:
        diff = sorted(set(used) ^ set(want)) + sorted(k for k in used if k in want and used[k] != want[k])
        errs.append("勝ち上がりの枠のつながりが不正: " + "、".join(diff))
    for stage, groups in (("決勝GS", FINAL_GROUPS), ("強化GS", STRENGTH_GROUPS)):
        for g in groups:
            ms = [m for m in raw_matches if m["stage"] == stage and m.get("group") == g]
            mem = group_members(raw_matches, stage, g)
            cnt = {k: 0 for k in mem}
            for m in ms:
                for side in ("home", "away"):
                    cnt[m.get(side) or m.get(side + "From")] += 1
            if len(ms) != 6 or len(mem) != 4 or set(cnt.values()) != {3}:
                errs.append(f"{stage} {g}グループが4チーム×6試合になっていない")
    named = [m[s] for m in raw_matches if m["stage"] in ("予選", "決勝GS", "強化GS")
             for s in ("home", "away") if m.get(s) and not m.get(s + "From")]
    seeds = set(named)
    if len(seeds) != 28:
        errs.append(f"出場チームが28でない（{len(seeds)}）")
    miss = sorted(seeds - set(data.get("reps", {})))
    if miss:
        errs.append("reps（代表枠）に無い大学: " + "、".join(miss))
    for m in raw_matches:
        if (m["hs"] is None) != (m["as_"] is None):
            errs.append(f"[{m['no']}] 得点が片方だけ入っている")
        elif scored(m):
            if not all(isinstance(x, int) and x >= 0 for x in (m["hs"], m["as_"])):
                errs.append(f"[{m['no']}] 得点が0以上の整数でない")
    for g, lst in (data.get("groupRank") or {}).items():
        stage = "決勝GS" if g in FINAL_GROUPS else "強化GS" if g in STRENGTH_GROUPS else None
        if not stage:
            errs.append(f"groupRank の組「{g}」が無い")
    return errs, warns


def validate_resolved(matches, data, errs, warns):
    for g, lst in (data.get("groupRank") or {}).items():
        stage = "決勝GS" if g in FINAL_GROUPS else "強化GS"
        rows = standings_names(matches, stage, g)
        if sorted(lst) != sorted(rows):
            errs.append(f"groupRank の{g}組が、その組の4チーム（{'・'.join(rows)}）の並びになっていない")
    strength = set()
    for g in STRENGTH_GROUPS:
        strength |= set(standings_names(matches, "強化GS", g))
    for no in (45, 46):
        m = next(x for x in matches if x["no"] == no)
        for side in ("home", "away"):
            if m.get(side) and m[side] not in strength:
                errs.append(f"[{no}] {m[side]} は強化ラウンドの12チームに無い")
    for m in matches:
        if m["stage"] in KO_STAGES and scored(m) and m.get("home") and m.get("away") and winner_of(m) is None:
            warns.append(f"[{m['no']}] {m['home']} {m['hs']}-{m['as_']} {m['away']} は引き分け中"
                         "（PK決着後は note に PK4-3 の形式で記入）")


def standings_names(matches, stage, g):
    out = []
    for m in matches:
        if m["stage"] == stage and m.get("group") == g:
            for side in ("home", "away"):
                if m.get(side) and m[side] not in out:
                    out.append(m[side])
    return out


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def slot_label(m, side, by_no, compact=False):
    """まだ決まっていない枠の書き方"""
    if m.get(side + "Label"):
        return m[side + "Label"]
    f = m.get(side + "From") or ""
    if f[:1] in "WL" and f[1:].isdigit():
        n = int(f[1:])
        p = by_no[n]
        if n <= 10:
            word = "勝者" if f[0] == "W" else "敗者"
            if compact:
                return f"予選[{n}]{word}"
            return f"予選[{n}]{word}（{short(p['home'])}／{short(p['away'])}）"
        return f"[{n}]の勝者"
    if len(f) == 2:
        return f"{f[0]}組{f[1]}位" if compact else f"{f[0]}グループ{f[1]}位"
    return "未定"


def team_html(m, side, by_no, reps):
    if not m.get(side):
        return f'<span class="inc-tbd">{esc(slot_label(m, side, by_no))}</span>'
    n = m[side]
    if m["stage"] in KO_STAGES:
        w = winner_of(m)
    elif scored(m) and m["hs"] != m["as_"]:
        w = m["home"] if m["hs"] > m["as_"] else m["away"]
    else:
        w = None
    name = f'<span class="match-winner">{esc(n)}</span>' if w == n else esc(n)
    rep = f'<span class="inc-rep">{esc(reps[n])}</span>' if n in reps and m["stage"] in ("予選", "決勝GS", "強化GS") else ""
    return name + rep


def score_html(m):
    if scored(m):
        tag = f'<span class="inc-pk">{esc(m["note"])}</span>' if m.get("note") else ""
        return f'<strong>{m["hs"]} - {m["as_"]}</strong>{tag}'
    return f'<span class="inc-time">{esc(m["time"])}</span>'


def match_table(ms, by_no, reps, show_date=True):
    rows = []
    for m in ms:
        d = f'<td class="inc-date">{esc(m["date"])}</td>' if show_date else ""
        rows.append(
            f'            <tr><td class="inc-no">[{m["no"]}]</td>{d}'
            f'<td class="inc-home">{team_html(m, "home", by_no, reps)}</td>'
            f'<td class="inc-score">{score_html(m)}</td>'
            f'<td class="inc-away">{team_html(m, "away", by_no, reps)}</td>'
            f'<td class="inc-venue">{esc(m["venue"])}</td></tr>')
    dh = "<th>日付</th>" if show_date else ""
    return ('        <div class="univ-scroll">\n        <table class="inc-table">\n'
            f'          <thead><tr><th>No.</th>{dh}<th style="text-align:right;">チーム</th><th>スコア</th>'
            '<th style="text-align:left;">チーム</th><th>会場</th></tr></thead>\n          <tbody>\n'
            + "\n".join(rows) + "\n          </tbody>\n        </table>\n        </div>")


STATUS_NOTE = {
    "empty": "まだ試合がありません。",
    "live": "途中経過です（6試合が終わると順位が確定します）。",
    "done": "全6試合が終わり、順位が確定しました。",
    "tie": "全6試合が終わりましたが、勝点・得失点差・総得点・当該チーム間の成績まで並んだチームがあります。反則ポイントか抽選で決まるため、JUFAの発表を待って載せます。",
    "official": "JUFAの発表どおりの順位です。",
}


def standings_table(matches, stage, g, data, by_no, adv):
    rows, status = standings(matches, stage, g, data)
    body = []
    for i, r in enumerate(rows, 1):
        if r["name"]:
            nm = esc(r["name"])
        else:
            fake = {"home": None, "homeFrom": r["key"]}
            nm = f'<span class="inc-tbd">{esc(slot_label(fake, "home", by_no))}</span>'
        mark = status == "tie" and r["tied"]
        rk = "–" if status == "empty" else (f"{i}" + ("※" if mark else ""))
        cls = ' class="inc-adv"' if status in ("done", "official", "tie") and i <= adv and not mark else ""
        body.append(f'            <tr{cls}><td>{rk}</td><td class="inc-team">{nm}</td><td>{r["p"]}</td><td>{r["w"]}</td>'
                    f'<td>{r["d"]}</td><td>{r["l"]}</td><td>{r["gf"]}</td><td>{r["ga"]}</td>'
                    f'<td>{r["gd"]:+d}</td><td><strong>{r["pts"]}</strong></td></tr>'.replace(">+0<", ">0<"))
    return ('        <div class="univ-scroll">\n        <table class="inc-table inc-standings">\n'
            '          <thead><tr><th>順位</th><th style="text-align:left;">大学</th><th>試合</th><th>勝</th><th>分</th>'
            '<th>負</th><th>得点</th><th>失点</th><th>得失点差</th><th>勝点</th></tr></thead>\n          <tbody>\n'
            + "\n".join(body) + "\n          </tbody>\n        </table>\n        </div>\n"
            f'        <p class="inc-st-note">{esc(STATUS_NOTE[status])}</p>')


FLOW = """        <div class="inc-flow" aria-label="大会の流れ">
          <div class="inc-step"><strong>予選ラウンド</strong>11月28日（土）／20チーム・10試合（1試合の勝ち抜き）</div>
          <div class="inc-split">
            <div class="inc-branch">
              <div class="inc-arrow">↓ 勝った10チーム</div>
              <div class="inc-step inc-main"><strong>決勝ラウンド</strong>＋シードの6チーム＝16チーム<br>グループステージ（4組の総当たり・12月2日〜6日）<br>↓ 各組の上位2チーム<br>準々決勝・準決勝・決勝（12月13日〜19日）</div>
            </div>
            <div class="inc-branch">
              <div class="inc-arrow">↓ 負けた10チーム</div>
              <div class="inc-step"><strong>強化ラウンド</strong>＋推薦の2チーム＝12チーム<br>グループステージ（3組の総当たり・12月1日〜3日）<br>↓ 各組1位とワイルドカード1チーム<br>準決勝・決勝（12月4日・5日）</div>
            </div>
          </div>
        </div>"""


def render(matches, by_no, data):
    reps = data.get("reps", {})
    out = ['        <h3 style="margin:18px 0 6px;">大会の流れ</h3>', FLOW]

    # 予選
    out.append('        <h3 style="margin:22px 0 6px;">予選ラウンド（プレーオフ）　11月28日（土）</h3>')
    out.append('        <p class="univ-note">20チームが1試合だけの勝ち抜き戦を行い、勝った10チームが決勝ラウンド、'
               '負けた10チームが強化ラウンドへ進みます。全国9会場（栃木の会場で2試合）。'
               '90分で決着しなければ延長30分とPK戦。勝ったチームは色つきで表示し、次のラウンドの表に自動で入ります。</p>')
    out.append(match_table([m for m in matches if m["stage"] == "予選"], by_no, reps, show_date=False))

    # 決勝ラウンド GS
    out.append('        <h3 style="margin:26px 0 6px;">決勝ラウンド グループステージ　12月2日・4日・6日</h3>')
    out.append('        <p class="univ-note">16チームを4グループに分けた総当たり（90分で決着しなければ引き分け）。'
               '各グループ上位2チームが準々決勝へ進みます。順位は勝点（勝ち3・引き分け1）→得失点差→総得点→当該チーム間の対戦成績の順で決まります'
               '（それでも並ぶときは反則ポイント・抽選。開催要項 第13条）。「予選[1]勝者（仙台大／早稲田大）」は上の予選ラウンド[1]の勝者で、結果が入ると大学名に変わります。</p>')
    for g, area in FINAL_GROUPS.items():
        out.append(f'        <h4 class="inc-group">{g}グループ<span>会場：{esc(area)}</span></h4>')
        out.append(standings_table(matches, "決勝GS", g, data, by_no, adv=2))
        out.append(match_table([m for m in matches if m["stage"] == "決勝GS" and m["group"] == g], by_no, reps))

    # 準々決勝〜決勝
    out.append('        <h3 style="margin:26px 0 6px;">決勝ラウンド ノックアウトステージ（準々決勝〜決勝）</h3>')
    out.append('        <p class="univ-note">準々決勝からは神奈川と東京で開催。90分で決着しなければ延長30分とPK戦。'
               '3位決定戦は行わず、準決勝で敗れた2チームが3位です。グループの順位が決まるまでは「A組1位」のような枠の名前で表示し、'
               '決まると大学名に変わります。勝ち上がったチームは赤枠・赤線で表示されます。</p>')
    out.append(render_ko_svg(matches, by_no))
    ko = [m for m in matches if m["stage"] in ("準々決勝", "準決勝", "決勝")]
    out.append(match_table(ko, by_no, reps))

    # 強化ラウンド
    out.append('        <h3 style="margin:26px 0 6px;">強化ラウンド　12月1日〜5日（千葉）</h3>')
    out.append('        <p class="univ-note">予選ラウンドで敗れた10チームに、<strong>八戸学院大学</strong>（東北第2）と'
               '<strong>高知大学</strong>（四国第2）を加えた12チームが、3グループの総当たりを行います。'
               '各グループ1位と、2位のうち最も成績のよい1チーム（ワイルドカード）が準決勝（12月4日・フクダ電子フィールドA面/B面）へ進み、'
               '決勝は12月5日（土）12:00、稲毛海浜公園球技場です。準決勝の組み合わせは「1位相当 vs ワイルドカード」「3位相当 vs 2位相当」で、'
               '反則ポイントも使って決まるため、JUFAの発表後に載せます。強化ラウンドの優勝チームが出た地域には、翌年の予選ラウンドの出場枠が1つ増えます。</p>')
    for g, place in STRENGTH_GROUPS.items():
        out.append(f'        <h4 class="inc-group">グループ{g}<span>会場：{esc(place)}</span></h4>')
        out.append(standings_table(matches, "強化GS", g, data, by_no, adv=1))
        out.append(match_table([m for m in matches if m["stage"] == "強化GS" and m["group"] == g], by_no, reps))
    out.append('        <h4 class="inc-group">準決勝・決勝</h4>')
    out.append(match_table([m for m in matches if m["stage"] in ("強化準決勝", "強化決勝")], by_no, reps))
    return "\n".join(out)


def render_ko_svg(matches, by_no):
    pairs = []
    for no in BRACKET_ORDER:
        m = by_no[no]
        h = short(m["home"]) if m.get("home") else slot_label(m, "home", by_no, compact=True)
        a = short(m["away"]) if m.get("away") else slot_label(m, "away", by_no, compact=True)
        pairs.append(f"- {h} vs {a}")
    sections = {"トーナメント表（組み合わせ）": pairs}
    for rnd in ("準々決勝", "準決勝", "決勝"):
        lines = []
        for m in matches:
            if m["stage"] != rnd or not scored(m) or not m.get("home") or not m.get("away"):
                continue
            pk = ""
            mm = re.search(r"PK\s*\d+\s*[-－ー]\s*\d+", m.get("note", ""))
            if mm:
                pk = f'({mm.group(0).replace(" ", "")})'
            lines.append(f'- {short(m["home"])} {m["hs"]}-{m["as_"]}{pk} {short(m["away"])}')
        if lines:
            sections[rnd] = lines
    svg = render_bracket_svg(sections, [])
    if not svg:
        print("[エラー] SVGトーナメント表の生成に失敗しました")
        sys.exit(1)
    # 「勝ち残り」の赤枠は、まだ大学が決まっていない枠（D組1位など）には付けない
    #   （枠は名前の文字と同じ高さ・左右に4の余白で描かれている。位置で突き合わせて消す）
    slots = [(float(x), float(y), anc) for x, y, anc in re.findall(
        r'<text x="([\d.]+)" y="([\d.]+)" text-anchor="(start|end)"[^>]*>[A-D]組[12]位</text>', svg)]

    def _drop(mm):
        rx, ry, rw = float(mm.group(1)), float(mm.group(2)), float(mm.group(3))
        for tx, ty, anc in slots:
            edge = rx if anc == "start" else rx + rw
            want = tx - 4 if anc == "start" else tx + 4
            if abs(ry + 11.5 - ty) < 0.2 and abs(edge - want) < 1.5:
                return ""
        return mm.group(0)
    svg = re.sub(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)"[^>]*/>', _drop, svg)
    return svg.replace("トーナメント表", "インカレ2026 決勝ラウンド トーナメント表")


def replace_block(src, body):
    if START not in src or END not in src:
        print("[エラー] ページに INCOLLE_ROUNDS のマーカーが見つかりません")
        sys.exit(1)
    pre, rest = src.split(START, 1)
    _, post = rest.split(END, 1)
    return pre + START + "\n" + body + "\n" + END + post


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    matches = data["matches"]
    errs, warns = validate(matches, data)
    if errs:
        print("[エラー] 検証NGのため生成を中止:")
        for e in errs:
            print("  -", e)
        sys.exit(1)
    by_no = resolve(matches, data)
    validate_resolved(matches, data, errs, warns)
    if errs:
        print("[エラー] 検証NGのため生成を中止:")
        for e in errs:
            print("  -", e)
        sys.exit(1)
    for w in warns:
        print("[注記]", w)
    for g in FINAL_GROUPS:
        rows, status = standings(matches, "決勝GS", g, data)
        if status == "tie":
            print(f"[注記] 決勝ラウンド {g}グループは反則ポイント・抽選で決まる並びがあります。"
                  f"JUFAの発表どおりに groupRank の \"{g}\" に4チームを書いてください")
    for g in STRENGTH_GROUPS:
        rows, status = standings(matches, "強化GS", g, data)
        if status == "tie":
            print(f"[注記] 強化ラウンド グループ{g}は反則ポイント・抽選で決まる並びがあります（groupRank の \"{g}\"）")

    src = PAGE.read_text(encoding="utf-8")
    new = replace_block(src, render(matches, by_no, data))
    if new != src:
        PAGE.write_text(new, encoding="utf-8")
    played = sum(1 for m in matches if scored(m))
    print(f"OK: 全{len(matches)}試合（結果あり{played}）")


if __name__ == "__main__":
    main()
