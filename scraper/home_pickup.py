# -*- coding: utf-8 -*-
"""
トップページ「PICK UP GAME」セクション生成モジュール
----------------------------------------------------
index.html の <!-- HOME_PICKUP_START --> 〜 <!-- HOME_PICKUP_END --> の間を
毎日自動で書き換える。「今日のハイライト」(2-2) と同じマーカー方式。

何を出すか（2026-08-29 Keiと決定）:
  - 全15リーグ（プレミア2＋プリンス13）を横断して、**直近に試合が行われた日**を1日決め、
    その日の試合から「注目カード」を4試合ピックアップする。
  - 試合がない日（平日）は切り替えない。次の試合が行われるまで直近の結果が出続ける。
  - 選定基準は機械的に：**対戦した2チームの順位の合計が小さい順**（＝上位対決）。
    プレミアは -3 の優遇。同点なら総得点が多い試合を上に。
    1リーグから最大1試合まで（同じ地域で埋まらないように）。動いたリーグが4つ未満の日は
    穴埋めで同じリーグの2試合目以降も拾う。

データは data/league_matches/<slug>.json（戦績表・リーグページ直近結果と共用）。
マーカーが無ければ何もしない（INFOを出してスキップ）。
"""
import json
import re
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MATCH_DIR = _ROOT / "data" / "league_matches"

START = "<!-- HOME_PICKUP_START -->"
END = "<!-- HOME_PICKUP_END -->"

_WD = ("月", "火", "水", "木", "金", "土", "日")

# slug -> (トップに出す短いリーグ名, カテゴリ)
LEAGUES = {
    "premier-east": ("プレミアEAST", "premier"),
    "premier-west": ("プレミアWEST", "premier"),
    "prince-hokkaido": ("プリンス北海道", "prince"),
    "prince-tohoku": ("プリンス東北", "prince"),
    "prince-kanto-1": ("プリンス関東1部", "prince"),
    "prince-kanto-2": ("プリンス関東2部", "prince"),
    "prince-hokushinetsu-1": ("プリンス北信越1部", "prince"),
    "prince-hokushinetsu-2": ("プリンス北信越2部", "prince"),
    "prince-tokai": ("プリンス東海", "prince"),
    "prince-kansai-1": ("プリンス関西1部", "prince"),
    "prince-kansai-2": ("プリンス関西2部", "prince"),
    "prince-chugoku": ("プリンス中国", "prince"),
    "prince-shikoku": ("プリンス四国", "prince"),
    "prince-kyushu-1": ("プリンス九州1部", "prince"),
    "prince-kyushu-2": ("プリンス九州2部", "prince"),
}

PREMIER_BONUS = 3   # プレミアは順位合計をこの分だけ良く扱う
MAX_PER_LEAGUE = 1  # 同じリーグから拾う上限（全国サイトなので地域を散らす。
                    # 動いたリーグが少ない日は下の穴埋めで2試合目以降も拾う）


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_date(iso: str) -> str:
    try:
        y, m, d = (int(x) for x in str(iso).split("-")[:3])
        return f"{y}年{m}月{d}日({_WD[date(y, m, d).weekday()]})"
    except Exception:
        return str(iso)


def _load(slug):
    p = _MATCH_DIR / f"{slug}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def collect_pickups(limit: int = 4):
    """(試合日, [カード用dict, ...]) を返す。1試合も無ければ (None, [])。"""
    data = {}
    latest = ""
    for slug in LEAGUES:
        d = _load(slug)
        if not d:
            continue
        data[slug] = d
        for m in d.get("matches", []):
            if m.get("status") == "played" and m.get("hs") is not None:
                dt = str(m.get("date") or "")
                if dt > latest:
                    latest = dt
    if not latest:
        return None, []

    cands = []
    for slug, d in data.items():
        label, cat = LEAGUES[slug]
        rank = {r["team"]: r["rank"] for r in d.get("official_standings", [])}
        n_teams = max(len(rank), 1)
        for m in d.get("matches", []):
            if m.get("status") != "played" or m.get("hs") is None:
                continue
            if str(m.get("date") or "") != latest:
                continue
            rh = rank.get(m["home"], n_teams)
            ra = rank.get(m["away"], n_teams)
            score = rh + ra - (PREMIER_BONUS if cat == "premier" else 0)
            cands.append({
                "slug": slug, "label": label, "cat": cat, "sort": score,
                "goals": (m["hs"] or 0) + (m["as"] or 0),
                "home": m["home"], "hrank": rh, "hs": m["hs"],
                "away": m["away"], "arank": ra, "as": m["as"],
            })
    if not cands:
        return None, []

    cands.sort(key=lambda c: (c["sort"], -c["goals"], c["slug"]))
    picked, per = [], {}
    for c in cands:
        if per.get(c["slug"], 0) >= MAX_PER_LEAGUE:
            continue
        picked.append(c)
        per[c["slug"]] = per.get(c["slug"], 0) + 1
        if len(picked) >= limit:
            break
    # 上限で拾いきれなかった場合の穴埋め（1リーグしか動いていない日など）
    if len(picked) < limit:
        for c in cands:
            if c not in picked:
                picked.append(c)
            if len(picked) >= limit:
                break
    return latest, picked


_STYLE = """<style>
.hp-sec{margin:18px 0 24px;}
.hp-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 10px;}
.hp-head h2{font-size:1.05rem;margin:0;}
.hp-date{font-size:.85rem;color:var(--text-light);}
.hp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;}
.hp-card{display:block;padding:13px 15px;border:1px solid var(--border-color);border-radius:10px;
  background:var(--bg-white);text-decoration:none;color:var(--text-dark);transition:border-color .15s;}
.hp-card:hover{border-color:var(--accent-color);}
.hp-badge{display:inline-block;font-size:.72rem;font-weight:700;letter-spacing:.03em;
  padding:2px 9px;border-radius:999px;margin-bottom:9px;
  background:var(--primary-hover-bg);color:var(--accent-color);}
.hp-badge.hp-premier{background:rgba(212,175,55,.16);color:#b8860b;}
.hp-row{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;}
.hp-tm{font-size:.95rem;line-height:1.35;}
.hp-tm.hp-h{text-align:right;} .hp-tm.hp-a{text-align:left;}
.hp-rk{display:block;font-size:.7rem;color:var(--text-light);}
.hp-sc{font-weight:700;font-size:1.15rem;color:var(--accent-color);white-space:nowrap;}
.hp-sc i{margin:0 4px;opacity:.55;font-weight:400;font-style:normal;}
.hp-win{font-weight:700;}
.hp-more{margin:10px 0 0;font-size:.88rem;}
@media (max-width:600px){
  .hp-grid{grid-template-columns:1fr;}
  .hp-tm{font-size:.9rem;}
}
[data-theme="dark"] .hp-badge.hp-premier{background:rgba(212,175,55,.2);color:#e3c766;}
</style>"""


def render_home_pickup_html(limit: int = 4) -> str:
    played_date, picks = collect_pickups(limit)
    if not picks:
        return ""
    cards = []
    for c in picks:
        hw = " hp-win" if c["hs"] > c["as"] else ""
        aw = " hp-win" if c["as"] > c["hs"] else ""
        badge = "hp-badge hp-premier" if c["cat"] == "premier" else "hp-badge"
        cards.append(
            f'    <a class="hp-card" href="/leagues/{c["slug"]}/">'
            f'<span class="{badge}">{_esc(c["label"])}</span>'
            f'<span class="hp-row">'
            f'<span class="hp-tm hp-h{hw}"><span class="hp-rk">{c["hrank"]}位</span>{_esc(c["home"])}</span>'
            f'<span class="hp-sc">{c["hs"]}<i>-</i>{c["as"]}</span>'
            f'<span class="hp-tm hp-a{aw}"><span class="hp-rk">{c["arank"]}位</span>{_esc(c["away"])}</span>'
            f"</span></a>"
        )
    nl = "\n"
    return (
        '<section class="hp-sec" aria-label="注目試合の結果">\n'
        + _STYLE + "\n"
        + '  <div class="hp-head"><h2>🔥 PICK UP GAME — 注目カードの結果</h2>'
        + f'<span class="hp-date">{_fmt_date(played_date)}の試合から</span></div>\n'
        + '  <div class="hp-grid">\n'
        + nl.join(cards) + "\n"
        + "  </div>\n"
        + '  <p class="hp-more"><a href="/leagues/">▶ プレミア・プリンス全15リーグの順位表と全試合結果を見る</a></p>\n'
        + "</section>"
    )


def update_home_pickup(index_path: Path = None, limit: int = 4) -> bool:
    """index.html のマーカー間を書き換える。書き換えたら True。"""
    path = Path(index_path) if index_path else (_ROOT / "index.html")
    if not path.exists():
        print("[PICK UP] index.html が見つからないのでスキップ")
        return False
    html = path.read_text(encoding="utf-8")
    if START not in html or END not in html:
        print("[PICK UP] マーカーが無いのでスキップ（HOME_PICKUP_START/END）")
        return False
    body = render_home_pickup_html(limit)
    if not body:
        print("[PICK UP] 出せる試合が無いのでスキップ")
        return False
    new = re.sub(
        re.escape(START) + r".*?" + re.escape(END),
        START + "\n" + body + "\n" + END,
        html, flags=re.S,
    )
    if new != html:
        path.write_text(new, encoding="utf-8")
        print(f"[PICK UP] index.html を更新（{limit}試合）")
        return True
    print("[PICK UP] 変更なし")
    return False


if __name__ == "__main__":
    print(render_home_pickup_html())
