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
                           "league": meta.get("league"), "coach": meta.get("head_coach")})
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
def league_finished(league):
    """[2026-11-17 Keiの決定] リーグの全日程が終わったか。終わっていれば「最終順位」と出す。
    次の3つが全部そろったときだけ「終わった」とする（どれか欠けたら「◯試合時点」のまま＝安全側）:
      1) teams.json 全県から同じリーグ名のチームを集め、全チームの試合数が 2×(チーム数−1)（ホーム&アウェイの総当たり）
      2) 全チームの勝ち数の合計＝負け数の合計（チームの取りこぼしが無い＝リーグ全体がそろっている）
      3) 全チームの得点の合計＝失点の合計（同上）
    3回戦制・1回戦制のリーグは 1) を満たさないので、最後まで「◯試合時点」のまま出る。"""
    if not league:
        return False
    tj = json.loads((DATA / "teams.json").read_text(encoding="utf-8"))
    ts = [t for p in tj.values() if isinstance(p, dict) for t in (p.get("teams") or []) if t.get("league") == league]
    n = len(ts)
    if n < 2:
        return False
    try:
        return (all(t.get("played") == 2 * (n - 1) for t in ts)
                and sum(t["won"] for t in ts) == sum(t["lost"] for t in ts)
                and sum(t["goalsFor"] for t in ts) == sum(t["goalsAgainst"] for t in ts))
    except (KeyError, TypeError):
        return False


def league_record(name, pref_slug):
    """teams.json の所属リーグと成績。{"league","rank","w","d","l","gf","ga","played"} or None"""
    tj = json.loads((DATA / "teams.json").read_text(encoding="utf-8"))
    pref = tj.get(pref_slug) or {}
    ks = keys_of(name, pref_slug)
    for t in pref.get("teams") or []:
        if any(same(nm, ks) for nm in [t.get("name")] + list(t.get("aliases") or []) if nm):
            return {"league": t.get("league"), "rank": t.get("leagueRank"), "final": league_finished(t.get("league")),
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


_EXTRA = None


def _extra():
    """[2026-11-17 第2段階] data/tournaments/senshuken-2026-matchup.yml（手で確認した最高成績・直接対決）。無ければ空。"""
    global _EXTRA
    if _EXTRA is None:
        import yaml
        p = DATA / "tournaments" / "senshuken-2026-matchup.yml"
        try:
            _EXTRA = yaml.safe_load(p.read_text(encoding="utf-8")) or {} if p.exists() else {}
        except Exception as e:
            warnings.append(f"senshuken-2026-matchup.yml が読めない（最高成績・直接対決なしで続行）: {type(e).__name__}: {e}")
            _EXTRA = {}
    return _EXTRA


def best_result(name):
    """選手権の最高成績の文字。データに無ければ None（行は「—」）。校名は代表の正式名で引く（表記ゆれは base で吸収）。"""
    for k, v in ((_extra().get("best") or {}).items()):
        if base(k) == base(name) and isinstance(v, dict):
            return v.get("text")
    return None


def head_to_head(a, b):
    """全国大会での直接対決。(期間の文字, [試合の文字...]) を返す。調べていない組み合わせは None。
    調べて対戦が無ければ (期間, [])。"""
    ex = _extra()
    key = {base(a), base(b)}
    checked = any({base(x) for x in pair} == key for pair in (ex.get("checked") or []) if len(pair) == 2)
    games = []
    for h in ex.get("head_to_head") or []:
        if {base(x) for x in h.get("teams") or []} == key:
            games = list(h.get("games") or [])
            checked = True
    if not checked:
        return None
    return ex.get("period") or "全国大会", games


def _from_yml(section, name):
    for k, v in ((_extra().get(section) or {}).items()):
        if base(k) == base(name):
            return v
    return None


def head_coach(name, pref_slug):
    """[2026-11-18] 監督（チームページ frontmatter の head_coach）。"""
    k = {norm(name), base(name)}
    g = next((g for g in _groups() if g.get("coach") and g["pref"] == pref_slug and g["keys"] & k), None)
    return str(g["coach"]) if g else None


_REGION = {"北海道": "hokkaido", "東北": "tohoku", "関東": "kanto", "北信越": "hokushinetsu", "東海": "tokai",
           "関西": "kansai", "中国": "chugoku", "四国": "shikoku", "九州": "kyushu"}


def _league_file(league, pref_slug):
    """teams.json の league → data/scorers/ のファイル。プレミア・プリンスは地域と部から、県リーグは pref-{県}-1.json。"""
    import re as _re
    lg = league or ""
    if "プレミア" in lg:
        return "premier-east.json" if "EAST" in lg.upper() else "premier-west.json" if "WEST" in lg.upper() else None
    if "プリンス" in lg:
        reg = next((v for k, v in _REGION.items() if k in lg), None)
        if not reg:
            return None
        m = _re.search(r"(\d)部", lg)
        return f"prince-{reg}-{m.group(1)}.json" if m else f"prince-{reg}.json"
    return f"pref-{pref_slug}-1.json" if pref_slug else None


def _abbr_match(abbr, name_keys):
    """得点ランキングの略称（静学・日大藤・富山一・長崎総附 など）が校名の「文字の並び」に含まれるか。
    2文字以上・セカンドチーム（2nd/3rd/B/U18 など英数字を含む略称）は対象外。同じリーグの中だけで使う。"""
    import re as _re
    a = norm(abbr)
    if len(a) < 2 or _re.search(r"[0-9A-Za-zＡ-Ｚａ-ｚ]", a):
        return False
    for k in name_keys:
        if a in k:  # 学芸館＝岡山学芸館、淞南＝立正大学淞南
            return True
        it = iter(k)
        if a[0] == k[:1] and all(ch in it for ch in a):  # 静学＝静岡学園、富山一＝富山第一
            return True
    return False


def top_scorer(name, pref_slug):
    """[2026-11-18] 今季のリーグ戦の得点源。その校のリーグの得点ランキング（data/scorers/、上位20人ほど）に
    載っている選手のうち最多得点の人。載っていなければ None。(選手名, 得点, 順位)"""
    rec = league_record(name, pref_slug)
    fn = _league_file((rec or {}).get("league"), pref_slug)
    if not fn or not (DATA / "scorers" / fn).exists():
        return None
    try:
        d = json.loads((DATA / "scorers" / fn).read_text(encoding="utf-8"))
    except Exception:
        return None
    ks = keys_of(name, pref_slug)
    best = None
    for sc in d.get("scorers") or []:
        t = sc.get("team") or ""
        if not isinstance(sc.get("goals"), int) or not (same(t, ks) or _abbr_match(t, ks)):
            continue
        if best is None or sc["goals"] > best[1]:
            best = (sc.get("name"), sc["goals"], sc.get("rank"))
    return best


_NAT = None


def national_players(name, pref_slug):
    """[2026-11-18] data/national-team-players.yml から（現役の年代別代表, 日本代表OB）。
    現役＝U-16〜U-21の各カテゴリで club がこの校の選手。OB＝SAMURAI BLUE で u18 がこの校の選手。"""
    global _NAT
    if _NAT is None:
        import yaml
        try:
            _NAT = yaml.safe_load((DATA / "national-team-players.yml").read_text(encoding="utf-8")) or {}
        except Exception:
            _NAT = {}
    ks = keys_of(name, pref_slug)
    now, ob = [], []
    for c in _NAT.get("categories") or []:
        lab = str(c.get("label") or "")
        short = lab.split("（")[0]
        for p in c.get("players") or []:
            nm = p.get("name")
            if not nm:
                continue
            if lab.startswith("SAMURAI BLUE"):
                if p.get("u18") and same(str(p["u18"]), ks):
                    ob.append(nm)
            elif p.get("club") and same(str(p["club"]), ks):
                now.append(f"{nm}（{short}）")
    return now, ob


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
        if r.get("final"):  # 全日程終了＝最終順位
            s += (f'<br><span class="mu-sub">最終順位 {r["rank"]}位・{r["w"]}勝{r["d"]}分{r["l"]}敗'
                  f'（得点{r["gf"]} 失点{r["ga"]}）</span>')
        else:
            s += (f'<br><span class="mu-sub">{r["rank"]}位・{r["w"]}勝{r["d"]}分{r["l"]}敗'
                  f'（{r["played"]}試合時点・得点{r["gf"]} 失点{r["ga"]}）</span>')
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


def nm_for_best(name):
    return name


def school_data(name, pref_slug, note):
    return {
        "note": note or "—",
        "best": best_result(nm_for_best(name)),
        "league": league_record(name, pref_slug),
        "qual": pref_qualifying(name, pref_slug),
        "ih": interhigh(name, pref_slug),
        "naitei": naitei(name, pref_slug),
        "coach": head_coach(name, pref_slug),
        "prev": _from_yml("prev", name),
        "scorer": top_scorer(name, pref_slug),
        "national": national_players(name, pref_slug),
        "players": _from_yml("players", name) or [],
    }


def _scorer_cell(sc):
    if not sc:
        return "—"
    nm, g, rk = sc
    return f'{esc(nm)} {g}点' + (f'<br><span class="mu-sub">リーグ得点ランキング{rk}位</span>' if rk else "")


def _national_cell(nat):
    now, ob = nat or ([], [])
    parts = [esc(x) for x in now] + [f'<span class="mu-sub">日本代表OB：</span>{esc("、".join(ob))}'] * bool(ob)
    return "<br>".join(parts) or "—"


def _players_cell(lst):
    return "<br>".join(esc(x) for x in lst) or "—"


def render_matchup(a_html, b_html, da, db, pref_a, pref_b, names=None):
    rows = [
        ("都道府県", esc(pref_a or "—"), esc(pref_b or "—")),
        ("監督", esc(da.get("coach") or "—"), esc(db.get("coach") or "—")),
        ("選手権の出場", esc(da["note"]), esc(db["note"])),
        ("選手権の最高成績", esc(da.get("best") or "—"), esc(db.get("best") or "—")),
        ("前回大会（2025年度）", esc(da.get("prev") or "—"), esc(db.get("prev") or "—")),
        ("2026年の所属リーグ", _league_cell(da["league"]), _league_cell(db["league"])),
        ("今大会の県予選", _q_cell(da["qual"]), _q_cell(db["qual"])),
        ("インターハイ2026", esc(da["ih"] or "—"), esc(db["ih"] or "—")),
        ("今季の得点源（リーグ戦）", _scorer_cell(da.get("scorer")), _scorer_cell(db.get("scorer"))),
        ("プロ内定", _naitei_cell(da["naitei"]), _naitei_cell(db["naitei"])),
        ("代表選手", _national_cell(da.get("national")), _national_cell(db.get("national"))),
        ("注目選手", _players_cell(da.get("players") or []), _players_cell(db.get("players") or [])),
    ]
    trs = "".join(f'<tr><th scope="row">{h}</th><td>{x}</td><td>{y}</td></tr>' for h, x, y in rows)
    # [2026-11-17 第2段階] 直接対決（調べた組み合わせだけ。2列ぶち抜きの1行）
    hh = head_to_head(*names) if names else None
    if hh:
        period, games = hh
        body = "<br>".join(esc(g) for g in games) if games else "対戦なし"
        trs += (f'<tr><th scope="row">直接対決</th><td colspan="2">{body}'
                f'<br><span class="mu-sub">（{esc(period)}）</span></td></tr>')
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
