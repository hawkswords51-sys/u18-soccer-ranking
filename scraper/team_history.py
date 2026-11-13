#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
チームページの「年度別の成績」（A-1・2026-11-13）
==================================================
プレミア・プリンスの最終順位（data/league_history_full.yml）と、全国大会の成績
（data/tournaments.json・data/premier_final_history.yml）を、1チーム1年1行の表にする。
新しく集めるデータは無い。既存のデータを読むだけ。

  - 対象の年：2016年から、league_history_full.yml にある最新の年まで（上限は書き込まない）
  - セカンドチーム（尚志2nd など）は親のページに別の行で出す
  - 北海道FAリーグは県リーグ1部相当なので出さない（2026-11-13 Kei決定）

使い方
  python scraper/team_history.py --tsv /tmp/a1.tsv   # 全チーム分を期待値TSVと同じ形で書き出す（検証用）
generate_team_pages.py からは render_history_html(meta, base_dir) を呼ぶ。
"""
import argparse
import html
import json
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

FIRST_YEAR = 2016

_SECOND_RE = re.compile(r"\s*(2nd|２nd|セカンド|B|Ｂ)$")
_HS_SUFFIXES = ("高等学校", "高等部", "高校", "高")
_GROUP_DIVS = None  # 2020年のグループ分け（A・B／Ａパート・Ｂパート）＝「1部・2部」以外の div


def norm(name: str) -> str:
    """名前のそろえ方（大会・リーグ・チームページの両方に同じ処理をかける）"""
    s = unicodedata.normalize("NFKC", name or "")
    s = re.sub(r"[\s　]", "", s)
    for x in ("・", "F.C.", "F.C", "FC", "."):
        s = s.replace(x, "")
    s = s.replace("U18", "U-18").replace("附属", "付属")
    for suf in _HS_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    return s


def is_club(name: str) -> bool:
    s = unicodedata.normalize("NFKC", name or "")
    return (("ユース" in s or "U-18" in s or "U18" in s)
            and "高校" not in s and "高等" not in s)


# ---------------------------------------------------------------------------
# データの読み込み（1回だけ）
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _load(base_dir: str):
    base = Path(base_dir)
    hist = yaml.safe_load((base / "data" / "league_history_full.yml").read_text(encoding="utf-8"))
    tourn = json.loads((base / "data" / "tournaments.json").read_text(encoding="utf-8"))["tournaments"]
    finals = yaml.safe_load((base / "data" / "premier_final_history.yml").read_text(encoding="utf-8"))["finals"]
    teams = json.loads((base / "data" / "teams.json").read_text(encoding="utf-8"))

    profiles = []
    for md in sorted((base / "data" / "team-profiles").glob("*.md")):
        parts = md.read_text(encoding="utf-8").split("---", 2)
        if len(parts) < 3:
            continue
        meta = yaml.safe_load(parts[1]) or {}
        if meta.get("id"):
            profiles.append(meta)
    return hist, tourn, finals, teams, profiles


def _team_keys(meta: dict, teams: dict) -> set:
    """チームページの name・short_name・frontmatter aliases・teams.json aliases をそろえたもの"""
    names = [meta.get("name"), meta.get("short_name")] + list(meta.get("aliases") or [])
    pref = (teams.get(meta.get("prefecture") or "") or {})
    for lst in (pref.get("teams") or [], pref.get("division2") or []):
        for t in lst if isinstance(lst, list) else []:
            if t.get("name") == meta.get("name"):
                names += list(t.get("aliases") or [])
    return {norm(n) for n in names if n}


def _season_rows(hist: dict, max_year: int | None = None):
    """(系統キー, label, era, season, row) を2016年以降について返す"""
    for key, sysd in hist.items():
        for era in sysd.get("eras") or []:
            for season in era.get("seasons") or []:
                if season.get("year", 0) < FIRST_YEAR:
                    continue
                for row in season.get("rows") or []:
                    yield key, sysd.get("label", ""), era, season, row


@lru_cache(maxsize=None)
def _second_parents(base_dir: str) -> dict:
    """(系統キー, 表記) → 親チームのid。決まらないものがあれば例外（止めて報告）"""
    hist, _, _, teams, profiles = _load(base_dir)
    linked = {}  # 系統キー → {そろえた名前: {link}}
    for key, sysd in hist.items():
        for era in sysd.get("eras") or []:
            for season in era.get("seasons") or []:
                for row in season.get("rows") or []:
                    for t in row.get("teams") or []:
                        if t.get("link"):
                            linked.setdefault(key, {}).setdefault(norm(t["name"]), set()).add(t["link"])
    prof_keys = [(p["id"], _team_keys(p, teams)) for p in profiles]
    out, bad = {}, []
    for key, label, era, season, row in _season_rows(hist):
        for t in row.get("teams") or []:
            if t.get("link") or not _SECOND_RE.search(t.get("name", "")):
                continue
            base_name = norm(_SECOND_RE.sub("", t["name"]))
            cand = linked.get(key, {}).get(base_name, set())
            if len(cand) != 1:
                cand = {pid for pid, ks in prof_keys if base_name in ks}
            if len(cand) == 1:
                out[(key, t["name"])] = next(iter(cand))
            elif cand:
                bad.append(f"{key} {season['year']} {t['name']} → {sorted(cand)}")
    if bad:
        raise RuntimeError("セカンドチームの親が1つに決まらない: " + " / ".join(bad))
    return out


# ---------------------------------------------------------------------------
# 1チーム分の行を作る
# ---------------------------------------------------------------------------

def _league_text(label, era, season, row, pos, t):
    year = season["year"]
    div = row.get("div")
    title = era.get("title") or ""
    name = label
    if year == 2020:
        m = re.search(r"スーパープリンスリーグ\S+?(?=[）)]|$)", title)
        if m:
            name = m.group(0)
    if div in ("1部", "2部"):
        name += div
    elif div and year == 2020:
        return f"{name}（2020年は特別方式のため順位なし）"
    sub = t.get("sub") or ""
    rank = "優勝" if pos == 1 else f"{pos}位"
    notes = []
    if "位" in sub:
        rank = sub
    elif sub:
        notes.append(sub)
    mark = t.get("mark")
    if mark == "premier":
        notes.append("プレミア昇格")
    elif mark == "playoff":
        notes.append("参入戦出場・昇格ならず")
    elif mark and mark != "final":
        legend = era.get("legend") or {}
        if legend.get(mark):
            notes.append(legend[mark])
    if year == 2020:
        notes.append("2020年は特別方式")
    return name, rank, notes


def _final_suffix(meta, year, keys, finals):
    if year == 2020:
        return ""
    word = "チャンピオンシップ" if year <= 2017 else "ファイナル"
    for f in finals:
        if f.get("year") != year or f.get("cancelled"):   # 2021年はファイナル中止
            continue
        champ = (f.get("champion") or {})
        for side in ("east_winner", "west_winner"):
            w = f.get(side) or {}
            if w.get("pref") == meta.get("prefecture") and norm(w.get("team", "")) in keys:
                won = norm(champ.get("team", "")) == norm(w.get("team", ""))
                return f"・{word}{'優勝' if won else '準優勝'}"
    return ""


def team_rows(meta: dict, base_dir) -> list:
    """[(年度, 種別, リーグ欄, 列1, 列2)]。表を出さないチームは []"""
    base_dir = str(base_dir)
    hist, tourn, finals, teams, _ = _load(base_dir)
    parents = _second_parents(base_dir)
    tid = meta.get("id")
    keys = _team_keys(meta, teams)
    years = sorted({s["year"] for _, _, _, s, _ in _season_rows(hist)}, reverse=True)

    main, second = {}, {}
    for key, label, era, season, row in _season_rows(hist):
        if key == "hokkaido" and row.get("div") == "FAリーグ":
            continue
        for pos, t in enumerate(row.get("teams") or [], 1):
            own = t.get("link") == tid
            sec = (not t.get("link")) and parents.get((key, t["name"])) == tid
            if not (own or sec):
                continue
            r = _league_text(label, era, season, row, pos, t)
            if isinstance(r, str):
                text = r
            else:
                name, rank, notes = r
                if own and key.startswith("premier") and pos == 1:
                    rank += _final_suffix(meta, season["year"], keys, finals)
                text = f"{name} {rank}" + (f"（{'・'.join(notes)}）" if notes else "")
            if own:
                main.setdefault(season["year"], []).append(text)
            else:
                second.setdefault(season["year"], []).append(f"{t['name']}：{text}")

    club = is_club(meta.get("name", ""))
    cols = ("club_youth_u18", "j_youth_cup") if club else ("interhigh", "all_japan_highschool")

    def nat(tkey, year):
        res = (tourn.get(tkey) or {}).get("results") or {}
        if str(year) not in res:
            return "中止" if (tkey == "interhigh" and year == 2020) else ""
        for e in res[str(year)].get("teams") or []:
            if e.get("pref") == meta.get("prefecture") and norm(e.get("team", "")) in keys:
                return "出場" if e.get("result") == "代表" else e.get("result", "")
        return "—"

    out, any_data = [], False
    for y in years:
        lg = " / ".join(main.get(y, [])) or "—"
        c1, c2 = nat(cols[0], y), nat(cols[1], y)
        if lg != "—" or c1 not in ("—", "中止", "") or c2 not in ("—", "中止", ""):
            any_data = True
        out.append((y, "", lg, c1, c2))
        for s in second.get(y, []):
            out.append((y, "セカンド", s, "", ""))
    return out if any_data else []


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def render_history_html(meta: dict, base_dir) -> str:
    rows = team_rows(meta, base_dir)
    if not rows:
        return ""
    club = is_club(meta.get("name", ""))
    h1, h2 = ("クラブユース選手権", "Jユースカップ") if club else ("インターハイ", "選手権")
    esc = html.escape
    body = []
    for y, kind, lg, c1, c2 in rows:
        cls = ' class="th-second"' if kind else ""
        body.append(f"    <tr{cls}><td>{y}</td><td>{esc(lg)}</td><td>{esc(c1)}</td><td>{esc(c2)}</td></tr>")
    notes = ["リーグ欄の「—」は、プレミア・プリンス以外（県リーグなど）に所属していた年です。"]
    if club:
        notes.append("クラブユース選手権・Jユースカップの「—」はベスト8に入っていない年（出場していない年を含む）、"
                     "空欄は当サイトに記録の無い年です（Jユースカップは2024年から）。")
    else:
        notes.append("インターハイ・選手権の「—」は出場していない年です。")
    notes.append("2020年はコロナ禍のため各リーグが特別方式で、インターハイは中止でした。")
    notes.append("出典：JFA公式の最終順位表・大会記録。リーグの順位は2016〜2025年（2020年を除く）をJFA公式と照合済み。")
    return (
        f'<h2>年度別の成績（{FIRST_YEAR}年〜）</h2>\n'
        '<p>プレミアリーグ・プリンスリーグの最終順位と、全国大会の成績を年度ごとにまとめています。</p>\n'
        '<style>.team-history .th-second td{font-size:0.88em;color:var(--text-light,#64748b);}'
        '.th-note{font-size:0.82em;color:var(--text-light,#64748b);line-height:1.7;}</style>\n'
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">\n'
        '<table class="data-table team-history">\n'
        f'  <thead><tr><th>年度</th><th>リーグ（最終順位）</th><th>{h1}</th><th>{h2}</th></tr></thead>\n'
        '  <tbody>\n' + "\n".join(body) + '\n  </tbody>\n</table>\n</div>\n'
        f'<p class="th-note">{"<br>".join(esc(n) for n in notes)}</p>\n'
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv", required=True)
    a = ap.parse_args()
    base = Path(__file__).resolve().parent.parent
    *_, profiles = _load(str(base))
    lines = ["team_id\t年度\t種別\tリーグ（最終順位）\t列1\t列2"]
    for meta in profiles:
        for y, kind, lg, c1, c2 in team_rows(meta, base):
            lines.append(f"{meta['id']}\t{y}\t{kind}\t{lg}\t{c1}\t{c2}")
    Path(a.tsv).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines) - 1} 行（{len({l.split(chr(9))[0] for l in lines[1:]})} チーム）→ {a.tsv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
