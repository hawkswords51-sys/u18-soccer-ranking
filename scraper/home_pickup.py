# -*- coding: utf-8 -*-
"""
トップページ「PICK UP GAME」セクション生成モジュール
----------------------------------------------------
index.html の <!-- HOME_PICKUP_START --> 〜 <!-- HOME_PICKUP_END --> の間を
毎日自動で書き換える。「今日のハイライト」(2-2) と同じマーカー方式。

何を出すか（2026-08-29 Keiと決定）:
  - 全15リーグ（プレミア2＋プリンス13）を横断して、**直近に試合が行われた3日間**（＝土日開催の
    1節をひとまとまりに扱う）から「注目カード」を4試合ピックアップする。
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
from datetime import date, timedelta
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
WINDOW_DAYS = 3     # 「直近の1節」とみなす日数（土日開催をひとまとまりに扱う）
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


def _fmt_day(iso: str) -> str:
    """カード内に出す短い日付。'2026-08-30' -> '8/30(日)'"""
    try:
        y, m, d = (int(x) for x in str(iso).split("-")[:3])
        return f"{m}/{d}({_WD[date(y, m, d).weekday()]})"
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
    """(対象にした試合日のリスト, [カード用dict, ...]) を返す。1試合も無ければ ([], [])。

    ⚠️「最新の1日」だけを見てはいけない。日曜に順延分が1試合だけ組まれることがあり
    （2026-08-30 九州2部 鹿児島 vs 九州国際大付が実例）、その1試合だけでトップページの
    PICK UP が埋まってしまう。→ 最新の試合日を含む **直近3日間** をひとまとまり
    （土日開催の1節）として扱い、それでも候補が足りなければ1日ずつ遡る。
    """
    data = {}
    all_matches = []   # (date, slug, match)
    for slug in LEAGUES:
        d = _load(slug)
        if not d:
            continue
        data[slug] = d
        for m in d.get("matches", []):
            if m.get("status") == "played" and m.get("hs") is not None and m.get("date"):
                all_matches.append((str(m["date"]), slug, m))
    if not all_matches:
        return [], []

    dates_desc = sorted({dt for dt, _, _ in all_matches}, reverse=True)
    latest = dates_desc[0]
    try:
        y, mo, dd = (int(x) for x in latest.split("-")[:3])
        floor = (date(y, mo, dd) - timedelta(days=WINDOW_DAYS - 1)).isoformat()
    except Exception:
        floor = latest
    window = [dt for dt in dates_desc if dt >= floor]
    # 直近3日間で足りなければ1日ずつ遡る
    i = len(window)
    while sum(1 for dt, _, _ in all_matches if dt in window) < limit and i < len(dates_desc):
        window.append(dates_desc[i])
        i += 1
    window = set(window)

    cands = []
    for dt, slug, m in all_matches:
        if dt not in window:
            continue
        d = data[slug]
        label, cat = LEAGUES[slug]
        rank = {r["team"]: r["rank"] for r in d.get("official_standings", [])}
        n_teams = max(len(rank), 1)
        rh = rank.get(m["home"], n_teams)
        ra = rank.get(m["away"], n_teams)
        score = rh + ra - (PREMIER_BONUS if cat == "premier" else 0)
        cands.append({
            "slug": slug, "label": label, "cat": cat, "sort": score, "date": dt,
            "goals": (m["hs"] or 0) + (m["as"] or 0),
            "home": m["home"], "hrank": rh, "hs": m["hs"],
            "away": m["away"], "arank": ra, "as": m["as"],
        })
    if not cands:
        return [], []
    latest = sorted(window)

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


# バンド型（2026-08-30 Keiが3案から選択）。紺のグラデ帯で囲って周囲から切り離す。
# 帯そのものはライト/ダーク共通の濃紺（白抜き文字が常に読める）。
# 帯の中のカードだけテーマで切り替えるため、セクション内ローカル変数 --hp-* を使う。
_STYLE = """<style>
.hp-sec{--hp-card-bg:rgba(255,255,255,.97);--hp-card-fg:#1e293b;--hp-lg:#1e3a8a;--hp-sc:#1e3a8a;
  margin:16px 0 26px;border-radius:14px;overflow:hidden;
  background:linear-gradient(135deg,#1e3a8a,#16295f);box-shadow:0 6px 20px rgba(0,0,0,.18);}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]) .hp-sec{--hp-card-bg:rgba(255,255,255,.10);--hp-card-fg:#f1f5f9;
    --hp-lg:#93c5fd;--hp-sc:#fbbf24;}
}
:root[data-theme="dark"] .hp-sec{--hp-card-bg:rgba(255,255,255,.10);--hp-card-fg:#f1f5f9;
  --hp-lg:#93c5fd;--hp-sc:#fbbf24;}
.hp-inner{padding:18px 20px 16px;}
.hp-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 14px;}
.hp-fire{font-size:1.3rem;line-height:1;}
.hp-sec h2{margin:0;font-size:1.35rem;color:#fff;letter-spacing:.04em;border:none;padding:0;}
.hp-date{font-size:.82rem;color:rgba(255,255,255,.75);}
.hp-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;}
.hp-card{display:block;padding:14px 14px 15px;border-radius:11px;background:var(--hp-card-bg);
  color:var(--hp-card-fg);text-decoration:none;transition:transform .15s;}
.hp-card:hover{transform:translateY(-2px);}
.hp-badge{display:block;font-size:.72rem;font-weight:700;letter-spacing:.03em;
  color:var(--hp-lg);margin-bottom:10px;}
.hp-day{font-size:.7rem;opacity:.6;margin-left:7px;font-weight:400;}
.hp-row{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:6px;}
.hp-tm{font-size:1rem;line-height:1.3;}
.hp-tm.hp-h{text-align:right;} .hp-tm.hp-a{text-align:left;}
.hp-rk{display:block;font-size:.66rem;font-weight:600;opacity:.55;}
.hp-sc{font-weight:800;font-size:1.5rem;color:var(--hp-sc);white-space:nowrap;}
.hp-sc i{margin:0 3px;opacity:.45;font-weight:400;font-style:normal;}
.hp-win{font-weight:800;}
.hp-more{margin:14px 0 0;font-size:.86rem;}
.hp-more a{color:rgba(255,255,255,.92);}
@media (max-width:600px){
  .hp-inner{padding:16px 14px 14px;}
  .hp-sec h2{font-size:1.15rem;}
  .hp-grid{grid-template-columns:1fr;}
  .hp-tm{font-size:.95rem;} .hp-sc{font-size:1.35rem;}
}
</style>"""


def render_home_pickup_html(limit: int = 4) -> str:
    played_dates, picks = collect_pickups(limit)
    if not picks:
        return ""
    used = sorted({c["date"] for c in picks})
    if len(used) == 1:
        date_label = f"{_fmt_date(used[0])}の試合から"
    else:
        tail = _fmt_date(used[-1])
        if used[0][:4] == used[-1][:4]:      # 同じ年なら後ろの「2026年」は省く
            tail = tail.split("年", 1)[1]
        date_label = f"{_fmt_date(used[0])}〜{tail}の試合から"
    multiday = len(used) > 1
    cards = []
    for c in picks:
        hw = " hp-win" if c["hs"] > c["as"] else ""
        aw = " hp-win" if c["as"] > c["hs"] else ""
        # 複数日にまたがる回だけ、どの日の試合かをカードに出す
        day = f'<span class="hp-day">{_fmt_day(c["date"])}</span>' if multiday else ""
        cards.append(
            f'    <a class="hp-card" href="/leagues/{c["slug"]}/">'
            f'<span class="hp-badge">{_esc(c["label"])}{day}</span>'
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
        + '  <div class="hp-inner">\n'
        + '  <div class="hp-head"><span class="hp-fire">🔥</span><h2>PICK UP GAME</h2>'
        + f'<span class="hp-date">注目カードの結果 ／ {date_label}</span></div>\n'
        + '  <div class="hp-grid">\n'
        + nl.join(cards) + "\n"
        + "  </div>\n"
        + '  <p class="hp-more"><a href="/leagues/">プレミア・プリンス全15リーグの順位表と全試合結果を見る →</a></p>\n'
        + "  </div>\n"
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
    if html.count(START) > 1 or html.count(END) > 1:
        # マーカーを移動したときに古い方を消し忘れると、空の方だけが更新され
        # 古い内容が下に残り続ける（2026-08-30に一度やらかした）。気づけるように止める。
        print("[PICK UP] マーカーが複数あります。index.html を確認してください（更新中止）")
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
