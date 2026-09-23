#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
チームページの「シーズンデータ」3欄を作る（generate_team_pages.py から呼ばれる）
=========================================================================
  ① 今季の試合結果（＋次の試合）… data/league_matches/{slug}.json から
  ② 基本布陣と先発                … frontmatter の formation ＋ data/team-season/{id}.json
  ③ 登録選手一覧                  … data/team-season/{id}.json

**frontmatter に `jfa_team:` があるチームだけ**に出る。無いチームは空文字を返すので、
160ページのうち書いたチームだけが変わる。

分類は「導出」なので push 起動でも走る（取得は fetch_jfa_team_season.py の担当）。

⚠️ ①は team-season が無くても出せる（リーグJSONだけで作れる）。
⚠️ 警告・退場（カード）は**持っていないし出さない**（未成年の懲罰情報）。
⚠️ 公式記録の GK/DF/MF/FW は**登録ポジション**で、試合中の配置ではない。
   だから布陣の図は frontmatter に手で書いた formation だけから描く（自動で推測しない）。
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from html import escape as html_escape
from pathlib import Path

# ★「今日」は必ず日本時間で取る。date.today() は Actions（UTC）で前日になる（scraper/jst.py 参照）。
#   上の `from datetime import date` は 66行目の曜日計算で使っているので消さないこと。
from jst import today as _jst_today

_WEEK = ("月", "火", "水", "木", "金", "土", "日")

# 図のひな形。上＝相手ゴール側。
# (枠の名前, 図に出す役割名) の行。`wide` の行は左右に広げる。
# frontmatter の formation.shape でどれを使うかを選ぶ。新しい形が要るときはここに足す。
_SHAPES = {
    "4-4-2d": [
        ("", [("FW1", "FW"), ("FW2", "FW")]),
        ("", [("AM", "トップ下")]),
        ("wide", [("LSH", "左SH"), ("RSH", "右SH")]),
        ("", [("DM", "アンカー")]),
        ("", [("LB", "SB"), ("CB1", "CB"), ("CB2", "CB"), ("RB", "SB")]),
        ("", [("GK", "GK")]),
    ],
    "4-4-2": [
        ("", [("FW1", "FW"), ("FW2", "FW")]),
        ("", [("LSH", "左SH"), ("CM1", "ボランチ"), ("CM2", "ボランチ"), ("RSH", "右SH")]),
        ("", [("LB", "SB"), ("CB1", "CB"), ("CB2", "CB"), ("RB", "SB")]),
        ("", [("GK", "GK")]),
    ],
}

_POS_ORDER = {"GK": 0, "DF": 1, "MF": 2, "FW": 3}


def _e(s) -> str:
    return html_escape(str(s if s is not None else ""))


def _md(iso: str) -> str:
    """2026-04-05 → 4/5"""
    y, m, d = iso.split("-")
    return f"{int(m)}/{int(d)}"


def _md_wd(iso: str) -> str:
    """2026-09-26 → 9/26(土)"""
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{m}/{d}({_WEEK[date(y, m, d).weekday()]})"


def _jp_day(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(m)}月{int(d)}日"


def _venue(v: str) -> str:
    """会場名の末尾の「(人工芝)」などを落とす（表示用。データは触らない）"""
    return re.sub(r"[（(][^（()）]*[)）]\s*$", "", v or "").strip()


def _scorers(rows) -> str:
    out = []
    for s in (rows or []):
        name = (s.get("name") or "").strip()
        minute = (s.get("minute") or "").strip()
        if "OG" in name or "オウン" in name:
            name = "OG"
        out.append(f"{_e(minute)}&#x27; {_e(name)}")
    return ", ".join(out)


# ---------------------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------------------
def load(meta: dict, base_dir: Path) -> dict | None:
    """このチームのシーズンデータ一式。jfa_team が無ければ None。"""
    jfa = str(meta.get("jfa_team") or "")
    m = re.fullmatch(r"([a-z0-9-]+)/(\d{2})", jfa)
    if not m:
        return None
    slug = m.group(1)
    league_file = base_dir / "data" / "league_matches" / f"{slug}.json"
    if not league_file.exists():
        return None
    league = json.loads(league_file.read_text(encoding="utf-8"))

    season_file = base_dir / "data" / "team-season" / f"{meta.get('id')}.json"
    season = json.loads(season_file.read_text(encoding="utf-8")) if season_file.exists() else None

    # リーグJSON上の表記を決める（md の name と違うことがある：流通経済大学付属柏高校／流通経済大柏）
    key = (season or {}).get("league_team")
    if not key:
        used = {x.get("home") for x in league["matches"]} | {x.get("away") for x in league["matches"]}
        # ⚠️ 空白と「.」を無視して比べる（広島・福岡は出典どうしで1文字違う）
        def _norm(x):
            return (x or "").replace(" ", "").replace("\u3000", "").replace(".", "").replace("．", "")
        for cand in [meta.get("name", ""), meta.get("short_name", "")]:
            for u in used:
                if cand and _norm(cand) == _norm(u):
                    key = u
                    break
            if key:
                break
    if not key:
        return None
    return dict(slug=slug, league=league, season=season, key=key,
                jfa_num=m.group(2))


# ---------------------------------------------------------------------------
# ① 試合結果
# ---------------------------------------------------------------------------
def _results_html(ctx: dict, short: str, league_label: str) -> str:
    league, key = ctx["league"], ctx["key"]
    st = next((r for r in league.get("official_standings", []) if r.get("team") == key), None)
    mine = [m for m in league["matches"] if key in (m.get("home"), m.get("away"))]
    played = [m for m in mine if m.get("status") == "played"]
    played.sort(key=lambda m: (m.get("md") or 0))

    card = ""
    if st:
        cells = [(f"{st['rank']}位", "現在順位"), (st["played"], "試合"),
                 (f"{st['won']}-{st['drawn']}-{st['lost']}", "勝-分-敗"),
                 (st["pts"], "勝点"), (st["gf"], "得点"), (st["ga"], "失点")]
        card = ('<div class="ts-sum">'
                + "".join(f"<div><b>{_e(v)}</b><span>{_e(l)}</span></div>" for v, l in cells)
                + "</div>")

    rows = []
    for m in played:
        home = m.get("home") == key
        gf, ga = (m.get("hs"), m.get("as")) if home else (m.get("as"), m.get("hs"))
        mark, cls = ("○", "w") if gf > ga else (("●", "l") if gf < ga else ("△", "d"))
        sc = _scorers(m.get("homeScorers") if home else m.get("awayScorers"))
        num = re.search(r"/m(\d+)\.pdf$", m.get("reportUrl") or "")
        link = ""
        if num:
            url = (f"https://www.jfa.jp/match/takamado_jfa_u18_premier2026/"
                   f"{ctx['slug'].split('-')[1]}/match_page/m{num.group(1)}.html")
            link = f'<a href="{_e(url)}" target="_blank" rel="noopener">記録</a>'
        rows.append(
            f'<tr><td class="c">{_e(m.get("md"))}</td>'
            f'<td class="c">{_e(_md(m["date"])) if m.get("date") else ""}</td>'
            f'<td class="c"><span class="ts-ha">{"ホーム" if home else "アウェイ"}</span></td>'
            f'<td>{_e(m.get("away") if home else m.get("home"))}</td>'
            f'<td class="c"><span class="ts-res {cls}">{mark}</span> <b>{_e(gf)}-{_e(ga)}</b></td>'
            f'<td class="ts-sc">{sc}</td><td class="c">{link}</td></tr>')

    # [2026-09-23] 日付が過ぎた未消化試合は「次の試合」に出さない。
    # 延期なのか結果が未反映なのかに関わらず、過去の日付は「次の試合」ではない。
    # 出典（JFA）が延期試合の日付を古いまま持っていることがあり、
    # データ側に dateTbd を手で書いても fetch_jfa.py が毎回作り直すため残らない。
    # 日付は "YYYY-MM-DD" 固定なので文字列比較で足りる。
    _today = _jst_today().isoformat()
    nxt = [m for m in mine
           if m.get("status") != "played" and m.get("date")
           and not m.get("dateTbd") and m["date"] >= _today]
    nxt.sort(key=lambda m: m["date"])
    next_html = ""
    if nxt:
        items = []
        for m in nxt[:2]:
            home = m.get("home") == key
            items.append(
                f'<li><b>第{_e(m.get("md"))}節</b> {_e(_md_wd(m["date"]))} {_e(m.get("kickoff") or "")}'
                f'　{"ホーム" if home else "アウェイ"}　vs <b>{_e(m.get("away") if home else m.get("home"))}</b>'
                f'　<span class="ts-muted">{_e(_venue(m.get("venue") or ""))}</span></li>')
        next_html = f'<div class="ts-next"><b>次の試合</b><ul>{"".join(items)}</ul></div>'

    asof = max((m["date"] for m in played if m.get("date")), default="")
    src = league.get("source") or ""
    src_html = (f'<p class="ts-src">出典：<a href="{_e(src)}" target="_blank" rel="noopener">'
                f'JFA公式 {_e(league.get("league", ""))}</a>'
                f'{f"（{_jp_day(asof)}終了分まで）" if asof else ""}</p>')

    # 見出しは frontmatter の league（プレミアリーグEAST）を使う。
    # ⚠️ リーグJSONの league は「高円宮杯 JFA U-18 プレミアリーグ 2026 EAST」で年が入っており、
    #    season と並べると「2026 …2026 EAST」と2回出る。
    return (f'<h2>{_e(league.get("season", ""))} {_e(league_label)} 試合結果</h2>'
            + card
            + '<div class="ts-tbl"><table><thead><tr><th>節</th><th>日付</th><th></th>'
            + f'<th>対戦相手</th><th>結果</th><th>{_e(short)}の得点者</th><th>公式</th></tr></thead>'
            + f'<tbody>{"".join(rows)}</tbody></table></div>'
            + next_html + src_html)


# ---------------------------------------------------------------------------
# ② 基本布陣と先発
# ---------------------------------------------------------------------------
def _pitch_html(meta: dict, roster: list[dict], warn: list[str]) -> str:
    f = meta.get("formation") or {}
    shape = _SHAPES.get(f.get("shape"))
    if not shape:
        return ""
    players = f.get("players") or {}
    names = {p["name"] for p in (roster or [])}
    lines = []
    for wide, slots in shape:
        cells = []
        for slot, label in slots:
            who = players.get(slot)
            if who and roster and who not in names:
                warn.append(f"formation の {slot}「{who}」が登録選手一覧に居ない")
            if who:
                cells.append(f'<div class="ts-pl"><span class="ts-num">{_e(label)}</span>'
                             f'<span class="ts-nm">{_e(who)}</span></div>')
            else:
                cells.append(f'<div class="ts-pl empty"><span class="ts-num">{_e(label)}</span>'
                             f'<span class="ts-nm">&nbsp;</span></div>')
        lines.append(f'<div class="ts-line {wide}">{"".join(cells)}</div>')
    note = f.get("note") or ""
    src = ""
    if f.get("source_url"):
        # ⚠️ f文字列の中に同じ種類の引用符を入れない（Python 3.11 では構文エラー。
        #    ローカルは3.12で通るが Actions は3.11。2026-09-20に踏みかけた）
        asof = f.get("asof")
        when = f"（{_e(asof)}時点）" if asof else ""
        src = (f'出典：<a href="{_e(f["source_url"])}" target="_blank" rel="noopener">'
               f'{_e(f.get("source_name") or "出典")}</a>{when}。')
    # [2026-09-20] 出典の記事に無い枠を編集部の判断で埋めることがある（流経大柏の最終ライン3人）。
    #   そのとき既定の一文は事実と合わなくなるので、frontmatter の caption で差し替える。
    #   caption が無いチームはこれまでどおりの一文（横展開の既定値）。
    caption = f.get("caption")
    body = _e(caption) if caption else "記事で名前が挙がった選手だけを配置しています（空欄は記事に記載がありません）。"
    return (f'<div><div class="ts-pitch">{"".join(lines)}</div>'
            f'<p class="ts-caveat">{src}{body}{_e(note)}</p></div>')


def _lineup_html(ctx: dict, meta: dict, warn: list[str]) -> str:
    season = ctx["season"]
    if not season or not season.get("matches"):
        return ""
    matches = season["matches"]
    roster = season.get("roster") or []
    total = len(matches)
    last_no = max(matches, key=int)
    last = matches[last_no]

    # 直近の試合の相手とスコア（リーグJSONから）
    # ⚠️ reportUrl で突き合わせるだけでは足りない。終わった試合でもJFAが記録PDFを出すまで
    #    reportUrl が空のことがある（2026-09-20の第14節 青森山田×柏）。節番号でも拾う。
    head = f'第{_e(last.get("md"))}節'
    for m in ctx["league"]["matches"]:
        if m.get("status") != "played" or ctx["key"] not in (m.get("home"), m.get("away")):
            continue
        if (re.search(rf"/m{last_no}\.pdf$", m.get("reportUrl") or "")
                or m.get("md") == last.get("md")):
            home = m.get("home") == ctx["key"]
            gf, ga = (m.get("hs"), m.get("as")) if home else (m.get("as"), m.get("hs"))
            head = (f'第{_e(m.get("md"))}節 vs {_e(m.get("away") if home else m.get("home"))}'
                    f' {_e(gf)}-{_e(ga)}')
            break

    by = {}
    for p in last["starters"]:
        by.setdefault(p["pos"], []).append(
            f'{p["no"]} {p["name"]}' + ("（C）" if p.get("captain") else ""))
    xi = "".join(
        f'<li><span class="ts-pos {k.lower()}">{k}</span>{_e("・".join(v))}</li>'
        for k, v in sorted(by.items(), key=lambda kv: _POS_ORDER.get(kv[0], 9)) if v)

    # 先発回数。同数は登録ポジション順（GK→DF→MF→FW）→背番号順
    # ⚠️ [2026-09-20] **いまの登録選手だけ**で数える。シーズン途中で登録を外れた選手が
    #    上位に並ぶと読者が混乱するため（青森山田は先発11回・10回の2人が登録外だった）。
    #    ⚠️ 登録を外れた理由はどこにも書かない（編集方針）。
    #    ⚠️ 試合の先発・得点者の表示には残す（起きた事実なので消さない）。
    # ⚠️ [2026-09-20] 数えるキーは**名前だけ**。試合ページのポジション表記は試合ごとに
    #    変わることがあり（広島の太田 大翔はDF6試合・MF6試合）、(背番号,名前,ポジション)で
    #    数えると同じ人が2行に割れる（6回＋6回。正しくは12回）。
    #    表示する背番号・ポジションは**選手一覧（roster）の値**を使う。
    by_name = {x["name"]: x for x in roster}
    cnt, cap = {}, {}
    for m in matches.values():
        for p in m["starters"]:
            if by_name and p["name"] not in by_name:
                continue
            cnt[p["name"]] = cnt.get(p["name"], 0) + 1
            if p.get("captain"):
                cap[p["name"]] = cap.get(p["name"], 0) + 1

    def _rank_key(item):
        name, c = item
        r = by_name.get(name) or {}
        return (-c, _POS_ORDER.get(r.get("pos"), 9), r.get("no", 999))
    top = sorted(cnt.items(), key=_rank_key)[:11]
    ol = ""
    for name, c in top:
        r = by_name.get(name) or {}
        pos = r.get("pos", "")
        ol += (f'<li><span class="ts-pos {pos.lower()}">{_e(pos)}</span>{_e(name)}'
               f'<span class="ts-cnt">{c}/{total}</span></li>')

    # キャプテン。⚠️ 最多が消化試合の半分に満たないときは「◯試合中◯試合」と書くと
    #   誤解を生む（青森山田は登録選手の最多が3/14）。そのときは直近の試合の主将を出す。
    cap_html = ""
    if cap:
        who, n = max(cap.items(), key=lambda kv: (kv[1], kv[0]))
        if n * 2 >= total:
            cap_html = f'<p class="ts-caveat">キャプテン：{_e(who)}（{total}試合中{n}試合）</p>'
        else:
            last_cap = next((x["name"] for x in last["starters"]
                             if x.get("captain") and (not by_name or x["name"] in by_name)), "")
            if last_cap:
                cap_html = (f'<p class="ts-caveat">直近の試合のキャプテン：{_e(last_cap)}'
                            f'（第{_e(last.get("md"))}節）</p>')

    return (f'<div class="ts-side"><h3>直近の先発（{head}）</h3><ul class="ts-xi">{xi}</ul>'
            f'<p class="ts-caveat">※ GK/DF/MF/FW は<b>公式記録のポジション表記</b>です。'
            f'試合中の実際の配置とは異なることがあります。</p>'
            f'<h3>今季の先発回数（{total}試合中・現在の登録選手のみ）</h3>'
            f'<ol class="ts-cntlist">{ol}</ol>{cap_html}</div>')


def _formation_html(ctx: dict, meta: dict, warn: list[str]) -> str:
    roster = (ctx["season"] or {}).get("roster") or []
    pitch = _pitch_html(meta, roster, warn)
    side = _lineup_html(ctx, meta, warn)
    if not pitch and not side:
        return ""
    f = meta.get("formation") or {}
    title = f'基本布陣：{f.get("label")}' if pitch and f.get("label") else "先発の記録"
    # ピッチ図が無いチーム（formation 未設定）は2列にすると右半分が空くので1列にする
    cls = "ts-lineup" if pitch else "ts-lineup one"
    return (f'<h2>{_e(title)}</h2><div class="{cls}">{pitch}{side}</div>')


# ---------------------------------------------------------------------------
# 登録選手一覧の「学年・前所属が空欄」を別の公式資料で補う（2026-09-23 新設）
#   JFAのチーム情報には学年・前所属が空欄の選手がいる（東山は14試合920分の主力を含む6人）。
#   ★JFAから取ったデータ（data/team-season/{id}.json）は書き換えない。**表示のときだけ**補う。
#   ★JFAに値が入ったらJFAを優先する（補完は空欄の項目だけ）。
#   ★valid_until を過ぎたらファイルごと使わない（翌シーズンに古い学年を出さないため）。
# ---------------------------------------------------------------------------
_SUP_FILE = "roster_supplement.json"
_sup_cache: dict | None = None


def _load_supplement(base_dir: Path) -> dict:
    """{team_id: {正規化した名前: レコード}} と sources。期限切れ・不正なら空。"""
    global _sup_cache
    if _sup_cache is not None:
        return _sup_cache
    _sup_cache = {"by_team": {}, "sources": {}}
    f = base_dir / "data" / "team-season" / _SUP_FILE
    if not f.exists():
        return _sup_cache
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [要確認] {_SUP_FILE} が読めません: {e}")
        return _sup_cache
    until = d.get("valid_until") or ""
    if until and str(_jst_today()) > until:
        print(f"  [情報] {_SUP_FILE} は {until} で期限切れのため使いません")
        return _sup_cache
    for rec in d.get("players") or []:
        _sup_cache["by_team"].setdefault(rec.get("team_id"), {})[_norm_name(rec.get("name"))] = rec
    _sup_cache["sources"] = d.get("sources") or {}
    return _sup_cache


def _norm_name(s) -> str:
    """名前の比較用。NFKC＋空白を除く。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def _apply_supplement(roster: list, team_id: str, base_dir: Path) -> tuple[list, set]:
    """(補った roster のコピー, 使った source キーの集合) を返す。"""
    sup = _load_supplement(base_dir)
    recs = dict(sup["by_team"].get(team_id) or {})
    if not recs:
        return roster, set()
    used, out, filled = set(), [], 0
    for p in roster:
        rec = recs.pop(_norm_name(p.get("name")), None)
        if not rec:
            out.append(p)
            continue
        q = dict(p)
        hit = False
        for key in ("grade", "prev"):
            if q.get(key):
                # JFA側に値が入った＝もう補う必要がない
                print(f"  [情報] JFAに値が入ったので補完不要: {team_id} {p.get('name')}（{key}）")
                continue
            if rec.get(key):
                q[key] = f'{rec[key]}※'
                hit = True
        if hit:
            used.add(rec.get("source"))
            filled += 1
        out.append(q)
    for left in recs.values():
        print(f"  [要確認] 補完対象が登録一覧に居ない: {team_id} {left.get('name')}")
    if filled:
        _SUP_COUNT[team_id] = filled
    return out, used


_SUP_COUNT: dict = {}


def supplement_summary() -> str:
    """生成の最後に1行で出す集計（generate_team_pages.py から呼ぶ）。"""
    if not _SUP_COUNT:
        return ""
    return "[補完] " + "・".join(f"{k} {v}人" for k, v in _SUP_COUNT.items()) + " を補った"


def _supplement_note(used: set, base_dir: Path) -> str:
    """補った行がある表にだけ足す1行。色は既存の注記と同じCSS変数を使う。"""
    if not used:
        return ""
    sources = _load_supplement(base_dir)["sources"]
    labels = []
    for k in sorted(used):
        s = sources.get(k) or {}
        lab = s.get("label") or k
        asof = s.get("asof")
        labels.append(f'{lab}（{_jp_day(asof)}時点）' if asof else lab)
    return (f'<p class="ts-src">※印は、JFAの登録一覧で空欄の学年・前所属を'
            f'{"・".join(labels)}で補ったものです。</p>')


# ---------------------------------------------------------------------------
# ③ 登録選手一覧
# ---------------------------------------------------------------------------
def _roster_html(ctx: dict, meta: dict, base_dir: Path) -> str:
    season = ctx["season"]
    if not season or not season.get("roster"):
        return ""
    # ★JFAが空欄にしている学年・前所属を、別の公式資料で表示のときだけ補う
    roster, sup_used = _apply_supplement(season["roster"], str(meta.get("id") or ""), base_dir)
    rows = []
    for p in roster:
        goals = f'<b>{p["goals"]}</b>' if p["goals"] else "0"
        rows.append(
            f'<tr><td class="c">{p["no"]}</td>'
            f'<td class="c"><span class="ts-pos {p["pos"].lower()}">{_e(p["pos"])}</span></td>'
            f'<td>{_e(p["name"])}</td><td class="c">{_e(p["grade"] or "—")}</td>'
            f'<td class="ts-prev">{_e(p["prev"] or "—")}</td>'
            f'<td class="c">{p["apps"]}</td><td class="c">{p["minutes"]}</td>'
            f'<td class="c">{goals}</td></tr>')
    asof = season.get("asof") or ""
    src = (f'<p class="ts-src">出典：<a href="{_e(season.get("source_roster"))}" target="_blank" '
           f'rel="noopener">JFA公式 チーム情報</a>'
           f'{f"（{_jp_day(asof)}終了分まで）" if asof else ""}</p>')
    return (f'<h2>{ctx["league"].get("season", "")} 登録選手一覧</h2>'
            f'<div class="ts-tbl"><table><thead><tr><th>No.</th><th>Pos.</th><th>選手名</th>'
            f'<th>学年</th><th>前所属チーム</th><th>試合</th><th>出場時間</th><th>得点</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>{src}'
            f'{_supplement_note(sup_used, base_dir)}')


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def render_sections_html(meta: dict, base_dir: Path) -> str:
    """3欄のHTML。jfa_team が無い／データが足りないときは空文字。"""
    ctx = load(meta, base_dir)
    if ctx is None:
        return ""
    warn: list[str] = []
    short = meta.get("short_name") or meta.get("name") or ""
    label = meta.get("league") or ctx["league"].get("league", "")
    html = (_results_html(ctx, short, label)
            + _formation_html(ctx, meta, warn)
            + _roster_html(ctx, meta, base_dir))
    for w in warn:
        # ⚠️ 卒業・登録変更で formation が古くなったことに気づくため。ページは止めない。
        print(f"  [WARN] {meta.get('id')}: {w}")
    return f'<section class="team-season">{html}</section>' if html else ""
