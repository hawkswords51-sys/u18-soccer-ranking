#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""選手権2026特設ページの「1回戦の組み合わせ」に付ける、両校のデータ比較（2026-11-17 新設）。

1回戦の各カードの下に <details>（開くと表）を出し、2校のデータを並べる。
すべてサイト内の既存データから自動で作る（新しく手で調べた値は使わない）:
  - 選手権の出場歴 … senshuken-final-2026.md「## 各県代表」の括弧内（公式表記）
  - 2026年の所属リーグと成績 … data/teams.json（毎日の自動更新と同じ値）
  - 県予選の勝ち上がり … data/tournaments/senshuken-2026/{県}-senshuken-2026.md の結果行
  - インターハイ2026 … data/tournaments/interhigh-final-2026.md（各県代表・各回戦の結果行）
  - プロ内定 … data/pro-signings.yml の status: naitei
名寄せ（校名の書き方ゆれ）は、チームページ（frontmatter の name / short_name / aliases）と
teams.json（name / aliases）を「同じチーム」として束ねて行う。名寄せできない項目は「—」にして
[要確認] を出す（別の学校のデータを載せないため、推測で埋めない）。
"""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SCORE_RE = re.compile(r"^-\s+(?P<a>.+?)\s+(?P<sa>\d+)-(?P<sb>\d+)(?:\s*\(PK(?P<pa>\d+)-(?P<pb>\d+)\))?\s+(?P<b>.+?)\s*$")
HEAD_RE = re.compile(r"^##\s+(?P<key>[^（(]+?)\s*(?:[（(][^）)]*[）)])?\s*$")

warnings = []


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def norm(n):
    n = unicodedata.normalize("NFKC", n or "")
    return n.replace(" ", "").replace("　", "").strip()


def base(n):
    """「高校」等を外した形。表記ゆれ照合の補助（日本大学→日大もそろえる）。"""
    n = norm(n)
    n = re.sub(r"(高等学校|高等部|高校|高)$", "", n)
    return n.replace("日本大学", "日大")


# ---------------------------------------------------------------- 名寄せ
_GROUPS = None  # [set(照合キー)]  1グループ＝1チーム


def _groups():
    global _GROUPS
    if _GROUPS is not None:
        return _GROUPS
    import yaml
    groups = []
    # チームページ
    for md in sorted((DATA / "team-profiles").glob("*.md")):
        try:
            c = md.read_text(encoding="utf-8")
            meta = yaml.safe_load(c.split("---", 2)[1]) or {}
        except Exception:
            continue
        names = [meta.get("name"), meta.get("short_name")]
        al = meta.get("aliases") or []
        if isinstance(al, str):
            al = re.split(r"[／/、,]", al)
        names += list(al)
        keys = set()
        for nm in names:
            if nm and len(str(nm).strip()) >= 2:
                keys |= {norm(str(nm)), base(str(nm))}
        keys.discard("")
        if keys:
            groups.append({"keys": keys, "id": meta.get("id"), "pref": meta.get("prefecture"),
                           "league": meta.get("league")})
    # teams.json（同じ県で名前が重なれば同じグループに足す）
    tj = json.loads((DATA / "teams.json").read_text(encoding="utf-8"))
    for slug, pref in tj.items():
        if not isinstance(pref, dict):
            continue
        for t in (pref.get("teams") or []) + (pref.get("division2") or []):
            ks = set()
            for nm in [t.get("name")] + list(t.get("aliases") or []):
                if nm:
                    ks |= {norm(nm), base(nm)}
            ks.discard("")
            g = next((g for g in groups if g["pref"] == slug and g["keys"] & ks), None)
            if g:
                g["keys"] |= ks
            else:
                groups.append({"keys": ks, "id": None, "pref": slug})
    _GROUPS = groups
    return groups


def keys_of(name, pref_slug=None):
    """校名 → そのチームの照合キー全部。見つからなければ校名自身のキーだけ。"""
    k = {norm(name), base(name)}
    cands = [g for g in _groups() if g["keys"] & k and (pref_slug is None or g["pref"] in (None, pref_slug))]
    out = set(k)
    for g in cands:
        out |= g["keys"]
    return out


def same(name, keys):
    return bool({norm(name), base(name)} & keys)


# ---------------------------------------------------------------- 各データ
def league_record(name, pref_slug):
    """teams.json の所属リーグと成績。{"league","rank","w","d","l","gf","ga","played"} or None"""
    tj = json.loads((DATA / "teams.json").read_text(encoding="utf-8"))
    pref = tj.get(pref_slug) or {}
    ks = keys_of(name, pref_slug)
    for t in pref.get("teams") or []:
        if any(same(nm, ks) for nm in [t.get("name")] + list(t.get("aliases") or []) if nm):
            return {"league": t.get("league"), "rank": t.get("leagueRank"),
                    "w": t.get("won"), "d": t.get("drawn"), "l": t.get("lost"),
                    "gf": t.get("goalsFor"), "ga": t.get("goalsAgainst"), "played": t.get("played")}
    # teams.json に無いリーグ（例：AIE国際＝東播・淡路リーグ）はチームページの league だけ出す（成績なし）
    g = next((g for g in _groups() if g.get("league") and g["pref"] == pref_slug
              and g["keys"] & {norm(name), base(name)}), None)
    if g:
        return {"league": g["league"]}
    warnings.append(f"所属リーグ: 「{name}」（{pref_slug}）が teams.json にもチームページにも見つからない")
    return None


def _rounds(path):
    """md → [(回戦名, [(a, sa, sb, pa, pb, b), ...])]（コメントの中は読まない）"""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    body = parts[2] if len(parts) == 3 and text.startswith("---") else text
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    out, cur = [], None
    for line in body.splitlines():
        h = HEAD_RE.match(line)
        if h:
            cur = (h.group("key").strip(), [])
            out.append(cur)
            continue
        m = SCORE_RE.match(line)
        if m and cur is not None:
            g = m.groupdict()
            cur[1].append((g["a"].strip(), int(g["sa"]), int(g["sb"]),
                           int(g["pa"]) if g["pa"] else None, int(g["pb"]) if g["pb"] else None, g["b"].strip()))
    return out


def _my_games(rounds, ks):
    """そのチームの試合を [(回戦, 相手, 自得点, 自失点, 自PK, 相PK)] で。"""
    games = []
    for rk, ms in rounds:
        for a, sa, sb, pa, pb, b in ms:
            if same(a, ks):
                games.append((rk, b, sa, sb, pa, pb))
            elif same(b, ks):
                games.append((rk, a, sb, sa, pb, pa))
    return games


def _won(g):
    _, _, f, a, pf, pa = g
    return f > a or (f == a and pf is not None and pa is not None and pf > pa)


def _score(g):
    _, _, f, a, pf, pa = g
    return f"{f}-{a}" + (f"(PK{pf}-{pa})" if pf is not None else "")


def pref_qualifying(name, pref_slug):
    """県予選の勝ち上がり。{"n","gf","ga","final"} or None"""
    path = DATA / "tournaments" / "senshuken-2026" / f"{pref_slug}-senshuken-2026.md"
    if not path.exists():
        return None
    games = _my_games(_rounds(path), keys_of(name, pref_slug))
    if not games:
        return None
    last = games[-1]
    if not _won(last):  # 代表校なので最後の試合は勝っているはず。違えば名寄せ違いを疑う
        warnings.append(f"県予選 {pref_slug}: 「{name}」の最後の試合が勝ちになっていない（{last}）→ 県予選欄は出さない")
        return None
    return {"n": len(games), "gf": sum(g[2] for g in games), "ga": sum(g[3] for g in games),
            "final": f"{last[0]} {_score(last)} {last[1]}"}


IH_LABEL = {"1回戦": "1回戦敗退", "2回戦": "2回戦敗退", "3回戦": "ベスト16",
            "準々決勝": "ベスト8", "準決勝": "ベスト4", "決勝": "準優勝"}


def interhigh(name, pref_slug):
    """インターハイ2026の全国成績の文字。出場していなければ "出場なし"。読めなければ None。"""
    path = DATA / "tournaments" / "interhigh-final-2026.md"
    if not path.exists():
        return None
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
    sec = re.search(r"^## 各県代表\s*$(.*?)^## ", text, re.S | re.M)
    if not sec:
        return None
    ks = keys_of(name, pref_slug)
    reps = []
    for ln in sec.group(1).splitlines():
        m = re.match(r"^\s*-\s*[^:：]+[:：]\s*(.+)$", ln)
        if m:
            reps += [re.sub(r"[（(][^（）()]*[）)]\s*$", "", t.strip()).strip() for t in re.split(r"[、,]", m.group(1))]
    if not any(same(r, ks) for r in reps):
        return "出場なし"
    games = [g for g in _my_games(_rounds(path), ks) if g[0] in IH_LABEL]
    if not games:
        return "出場"
    last = games[-1]
    if _won(last):
        return "優勝" if last[0] == "決勝" else None  # 勝ったまま終わっている＝データが途中
    return f"{IH_LABEL[last[0]]}（{last[0]}で{last[1]}に{_score(last)}）"


def naitei(name, pref_slug):
    """プロ内定（status: naitei）。[(選手名, 加入先)]"""
    import yaml
    d = yaml.safe_load((DATA / "pro-signings.yml").read_text(encoding="utf-8")) or {}
    ks = keys_of(name, pref_slug)
    return [(s.get("name"), s.get("dest")) for s in (d.get("signings") or [])
            if s.get("status") == "naitei" and s.get("team") and same(s["team"], ks)]


# ---------------------------------------------------------------- 描画
def _league_cell(r):
    if not r or not r.get("league"):
        return "—"
    s = esc(r["league"])
    if r.get("rank") and r.get("played"):
        s += (f'<br><span class="mu-sub">{r["rank"]}位・{r["w"]}勝{r["d"]}分{r["l"]}敗'
              f'（{r["played"]}試合・得点{r["gf"]} 失点{r["ga"]}）</span>')
    return s


def _q_cell(q):
    if not q:
        return "—"
    return (f'{q["n"]}試合 {q["gf"]}得点 {q["ga"]}失点'
            f'<br><span class="mu-sub">{esc(q["final"])}</span>')


def _naitei_cell(lst):
    if not lst:
        return "—"
    return "<br>".join(f'{esc(n)}<span class="mu-sub">（{esc(d)}）</span>' for n, d in lst)


def school_data(name, pref_slug, note):
    return {
        "note": note or "—",
        "league": league_record(name, pref_slug),
        "qual": pref_qualifying(name, pref_slug),
        "ih": interhigh(name, pref_slug),
        "naitei": naitei(name, pref_slug),
    }


def render_matchup(a_html, b_html, da, db, pref_a, pref_b):
    rows = [
        ("都道府県", esc(pref_a or "—"), esc(pref_b or "—")),
        ("選手権の出場", esc(da["note"]), esc(db["note"])),
        ("2026年の所属リーグ", _league_cell(da["league"]), _league_cell(db["league"])),
        ("今大会の県予選", _q_cell(da["qual"]), _q_cell(db["qual"])),
        ("インターハイ2026", esc(da["ih"] or "—"), esc(db["ih"] or "—")),
        ("プロ内定", _naitei_cell(da["naitei"]), _naitei_cell(db["naitei"])),
    ]
    trs = "".join(f'<tr><th scope="row">{h}</th><td>{x}</td><td>{y}</td></tr>' for h, x, y in rows)
    return ('<details class="mu-details"><summary>両校のデータを比べる</summary>'
            '<div class="mu-wrap"><table class="mu-table">'
            f'<thead><tr><th></th><th scope="col">{a_html}</th><th scope="col">{b_html}</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div></details>')


MU_STYLE = (
    '<style>'
    '.mu-details{margin:6px 0 2px;font-size:0.92em;}'
    '.mu-details>summary{cursor:pointer;color:var(--accent-color,#2563eb);font-size:0.9em;}'
    '.mu-wrap{overflow-x:auto;margin-top:6px;}'
    '.mu-table{width:100%;border-collapse:collapse;table-layout:fixed;min-width:300px;}'
    '.mu-table th,.mu-table td{border:1px solid var(--border-color,#e5e7eb);padding:6px 8px;'
    'vertical-align:top;text-align:left;line-height:1.5;word-break:break-word;}'
    '.mu-table thead th{background:var(--bg-light,#f8fafc);}'
    '.mu-table thead th:first-child{width:7.5em;}.mu-table tbody th{font-weight:600;background:var(--bg-light,#f8fafc);font-size:0.9em;}'
    '.mu-sub{font-size:0.85em;color:var(--text-light,#64748b);}'
    '</style>\n'
)
