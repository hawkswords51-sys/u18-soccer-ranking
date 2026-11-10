# -*- coding: utf-8 -*-
"""
トップページ「注目カード」帯の上段＝選手権予選の注目試合（2026-10-28 Keiと決定）
--------------------------------------------------------------------------
home_pickup.py（紺の帯）から呼ばれ、帯の中の上段に差し込む HTML を返す。
強い色の帯は1つだけ（2026-10-22方針）を守るため、独立のセクションは作らない。

何を出すか（Keiが3つの質問に回答して決定）:
  - 置き場所：紺の帯の中の上段（下段＝従来のリーグ注目カード）
  - 中身：今週末のカード（まだ試合前＝「vs」）＋直近の結果（スコア）。試合が終われば
    毎朝の自動更新で県予選mdにスコアが入り、勝手にスコア表示へ切り替わる。
  - 選び方：決勝は全部。準決勝はプレミア/プリンス所属校が出る試合だけ。
    対象の期間は「今日の4日前〜7日後」（土日の結果を木曜まで残し、次の週末を予告する）。
    多い日は最大 MAX_CARDS 試合（決勝優先→所属リーグが上の組→日付が近い順）。
  - 対戦相手が未確定（「A/B vs C/D」）のカードは出さない。

データ：data/tournaments/senshuken-<年>/<県>-senshuken-<年>.md（毎朝 koko から自動更新）。
所属リーグ：generate_interhigh_page.SCHOOL_LEAGUE_MAP（特設ページの代表校表示と同じ表）。

⚠️ 回戦名は県ごとに違う（「決勝」「決勝戦」「決勝トーナメント決勝」「2次予選決勝」、
   東京は「A/Bブロック決勝」）。「ブロック決勝」（広島・兵庫などの1次ラウンド）は決勝ではない。

[2026-11-10] インターハイ予選にも広げた（Kei依頼「来年度のインハイ県予選も同様にトップの見出しに」）。
  - 大会は TOURNAMENTS で切り替える。同じ md の形（data/tournaments/interhigh-<年>/<県>-interhigh-<年>.md）。
  - 年は「今日の年」を使う（インハイ予選は4〜6月、選手権予選は8〜11月で、どちらも年をまたがない）。
    → 毎年 YEAR を書き換える作業は不要になった。
  - インハイは代表2校の県（東京・神奈川・大阪・開催県）がある。その県は準決勝の勝者で代表が決まるので、
    準決勝を所属リーグに関係なく全部出し、勝者に「代表決定」を付ける（決勝には付けない）。
    どの県が2校かは interhigh-final-<年>.md の slots: 行（「〇〇は2チーム」）から読む。
  - 「47都道府県の〜」リンクは特設ページ（/tournaments/<大会>-<年>/）が実在するときだけ出す。
"""
import re
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TDIR = _ROOT / "data" / "tournaments"

# 大会ごとの設定。並び順＝帯に出す順（同時期に重なることは通常ない）
TOURNAMENTS = [
    {"key": "interhigh", "title": "インターハイ予選",
     "more": "47都道府県の予選結果と代表校一覧"},
    {"key": "senshuken", "title": "選手権予選",
     "more": "47都道府県の予選の状況と代表校一覧"},
]
DEFAULT_TWO_SLOT = {"tokyo", "kanagawa", "osaka"}   # インハイで代表2校の常連（開催県は年ごとに追加）
BACK_DAYS = 4          # 結果を残す日数（日曜の結果を木曜まで）
AHEAD_DAYS = 7         # 予告する日数
MAX_CARDS = 8

_WD = ("月", "火", "水", "木", "金", "土", "日")
_HEAD_RE = re.compile(r"^##\s+(?P<key>[^（(]+?)\s*(?:[（(](?P<dates>[^）)]*)[）)])?\s*$")
_SCORE_RE = re.compile(r"^-\s+(?P<a>.+?)\s+(?P<sa>\d+)-(?P<sb>\d+)(?:\(PK(?P<pa>\d+)-(?P<pb>\d+)\))?\s+(?P<b>.+?)\s*$")
_VS_RE = re.compile(r"^-\s+(?P<a>.+?)\s+vs\s+(?P<b>.+?)\s*$")
_MD_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
_PREFIX = r"(?:決勝トーナメント|決勝ラウンド|2次予選|2次トーナメント)?"
_FINAL_RE = re.compile(_PREFIX + r"\s*決勝戦?")     # 「2次予選 決勝」のように空白が入る県がある（インハイ神奈川・東京）
_SEMI_RE = re.compile(_PREFIX + r"\s*準決勝")

# slug -> 県名（表示用）。特設ページと同じ並び・表記
PREFS = [
    ("hokkaido", "北海道"), ("aomori", "青森"), ("iwate", "岩手"), ("miyagi", "宮城"),
    ("akita", "秋田"), ("yamagata", "山形"), ("fukushima", "福島"), ("ibaraki", "茨城"),
    ("tochigi", "栃木"), ("gunma", "群馬"), ("saitama", "埼玉"), ("chiba", "千葉"),
    ("tokyo", "東京"), ("kanagawa", "神奈川"), ("yamanashi", "山梨"), ("niigata", "新潟"),
    ("nagano", "長野"), ("toyama", "富山"), ("ishikawa", "石川"), ("fukui", "福井"),
    ("shizuoka", "静岡"), ("aichi", "愛知"), ("mie", "三重"), ("gifu", "岐阜"),
    ("shiga", "滋賀"), ("kyoto", "京都"), ("osaka", "大阪"), ("hyogo", "兵庫"),
    ("nara", "奈良"), ("wakayama", "和歌山"), ("tottori", "鳥取"), ("shimane", "島根"),
    ("okayama", "岡山"), ("hiroshima", "広島"), ("yamaguchi", "山口"), ("tokushima", "徳島"),
    ("kagawa", "香川"), ("ehime", "愛媛"), ("kochi", "高知"), ("fukuoka", "福岡"),
    ("saga", "佐賀"), ("nagasaki", "長崎"), ("kumamoto", "熊本"), ("oita", "大分"),
    ("miyazaki", "宮崎"), ("kagoshima", "鹿児島"), ("okinawa", "沖縄"),
]


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def round_kind(slug, key):
    """'final' / 'semi' / None。東京の A/Bブロック決勝は決勝扱い。"""
    k = key.strip()
    if slug == "tokyo" and re.fullmatch(r"[AB]ブロック決勝", k):
        return "final"
    if _FINAL_RE.fullmatch(k):
        return "final"
    if _SEMI_RE.fullmatch(k):
        return "semi"
    return None


def _to_date(md, year):
    m, d = md
    try:
        return date(year if m >= 4 else year + 1, m, d)   # 1〜3月は翌年（本大会の年明け）
    except ValueError:
        return None


def _round_dates(meta_line):
    out = {}
    for part in (meta_line or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            ds = [(int(a), int(b)) for a, b in _MD_RE.findall(v)]
            if k.strip() and ds:
                out[k.strip()] = ds
    return out


_LEAGUE_MAP = None


def _league(name):
    """校名 → 短縮リーグ名（'プレミアEAST' 等）。分からなければ ''。
    県予選mdは「帝京大学可児」、teams.json は「帝京大学可児高校」のように語尾がずれるので数通り試す。"""
    global _LEAGUE_MAP
    if _LEAGUE_MAP is None:
        try:
            import generate_interhigh_page as ih
            _LEAGUE_MAP = (ih.SCHOOL_LEAGUE_MAP, ih._norm_team)
        except Exception as e:  # 表が読めなくても帯は出す（リーグ表示なし・準決勝は出ない）
            print(f"[PICK UP 選手権] 所属リーグ表を読めません: {e}")
            _LEAGUE_MAP = ({}, lambda s: s)
    mp, norm = _LEAGUE_MAP
    base = norm(name)
    for v in (base, base + "高校", base + "高等学校", re.sub(r"^(県立|市立)", "", base),
              re.sub(r"(高校|高等学校)$", "", base)):
        if v in mp:
            return mp[v][1]
    return ""


def _tier(lg):
    return 0 if "プレミア" in lg else 1 if "プリンス" in lg else 2


def _two_slot_prefs(year):
    """インハイで代表2校の県の slug 集合。interhigh-final-<年>.md の slots: 行から読む。"""
    p = _TDIR / f"interhigh-final-{year}.md"
    try:
        line = next((ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("slots:")), "")
    except OSError:
        line = ""
    out = set()
    for seg in re.findall(r"[^。、，,]*?は\s*2\s*チーム", line):
        for slug, pref in PREFS:
            if pref in seg:
                out.add(slug)
    return out or set(DEFAULT_TWO_SLOT)


def collect(today=None, tkey="senshuken"):
    """注目試合のカード用 dict のリスト（表示順）。無ければ []。tkey＝'senshuken' / 'interhigh'"""
    if today is None:
        from jst import today as _t
        today = _t()
    YEAR = today.year
    lo, hi = today - timedelta(days=BACK_DAYS), today + timedelta(days=AHEAD_DAYS)
    folder = _TDIR / f"{tkey}-{YEAR}"
    two_slot = _two_slot_prefs(YEAR) if tkey == "interhigh" else set()
    cands = []
    for slug, pref in PREFS:
        p = folder / f"{slug}-{tkey}-{YEAR}.md"
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        meta = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for ln in parts[1].splitlines():
                    if ":" in ln and not ln.startswith(" "):
                        k, v = ln.split(":", 1)
                        meta[k.strip()] = v.strip()
                body = parts[2]
        try:
            year = int(meta.get("year") or YEAR)
        except ValueError:
            year = YEAR
        rd = _round_dates(meta.get("round_dates"))
        kind = key = None
        mds = []
        last_card = None   # 直前の「- 」行から作ったカード（勝者指定の印を結びつける先）
        for raw in body.splitlines():
            s = raw.strip()
            if s.startswith("- "):
                last_card = None
            h = _HEAD_RE.match(s)
            if h:
                key = h.group("key").strip()
                kind = round_kind(slug, key)
                mds = [(int(a), int(b)) for a, b in _MD_RE.findall(h.group("dates") or "")]
                if not mds and kind:
                    mds = rd.get("決勝" if kind == "final" else "準決勝", [])
                continue
            if s.startswith("<!-- 勝者"):
                # [2026-10-29] 試合行の直下の「<!-- 勝者: 校名 -->」＝進出校の手動指定（主催者判断など）
                om = re.match(r"<!--\s*勝者\s*[:：]\s*(.+?)\s*-->", s)
                if om and last_card is not None:
                    w = om.group(1).strip()
                    c = last_card
                    c["win"] = "a" if c["a"] == w else ("b" if c["b"] == w else c["win"])
                continue
            if not kind or not s.startswith("- "):
                continue
            days = [d for d in (_to_date(x, year) for x in mds) if d]
            if not days or not any(lo <= d <= hi for d in days):
                continue
            sm = _SCORE_RE.match(s)
            if sm:
                a, b = sm.group("a"), sm.group("b")
                sa, sb = int(sm.group("sa")), int(sm.group("sb"))
                pk = None
                win = None
                if sa != sb:
                    win = "a" if sa > sb else "b"
                elif sm.group("pa") is not None:
                    pk = (int(sm.group("pa")), int(sm.group("pb")))
                    if pk[0] != pk[1]:
                        win = "a" if pk[0] > pk[1] else "b"
                played = True
            else:
                vm = _VS_RE.match(s)
                if not vm:
                    continue
                a, b = vm.group("a"), vm.group("b")
                if "/" in a or "/" in b:
                    continue   # 相手が未確定
                sa = sb = pk = win = None
                played = False
            la, lb = _league(a), _league(b)
            decider = (kind == "semi") if slug in two_slot else (kind == "final")   # 代表が決まる試合
            if kind == "semi" and not decider and _tier(la) > 1 and _tier(lb) > 1:
                continue   # 準決勝はプレミア/プリンス校が出る試合だけ（代表2校の県の準決勝は全部出す）
            label = key if slug == "tokyo" and kind == "final" else ("決勝" if kind == "final" else "準決勝")
            cands.append({
                "slug": slug, "pref": pref, "kind": kind, "label": label,
                "days": days, "first": min(days), "played": played,
                "a": a, "b": b, "la": la, "lb": lb, "sa": sa, "sb": sb, "pk": pk, "win": win,
                "tier": min(_tier(la), _tier(lb)) * 3 + max(_tier(la), _tier(lb)),
                "decider": decider,
            })
            last_card = cands[-1]
    if not cands:
        return []
    # 選ぶ順：代表が決まる試合（ふつうは決勝。インハイ代表2校の県は準決勝）→ 所属リーグが上の組 → 今日に近い日
    pri = sorted(cands, key=lambda c: (not c["decider"], c["tier"],
                                       abs((c["first"] - today).days), c["slug"]))
    picked = pri[:MAX_CARDS]
    # 並べる順：日付 → 決勝が先 → 所属リーグが上の組
    picked.sort(key=lambda c: (c["first"], c["kind"] != "final", c["tier"], c["slug"]))
    return picked


def _fmt_days(days):
    ds = sorted(set(days))
    return "・".join(f"{d.month}/{d.day}" for d in ds) + f"({_WD[ds[0].weekday()]})" if len(ds) == 1 \
        else "・".join(f"{d.month}/{d.day}" for d in ds)


def render_block(today=None):
    """帯の上段に入れる HTML（インハイ予選・選手権予選のうち、出す試合がある大会だけ）。
    どちらも無ければ ''（＝帯は従来どおりリーグだけ）。"""
    if today is None:
        from jst import today as _t
        today = _t()
    return "".join(_render_one(t, today) for t in TOURNAMENTS)


def _render_one(t, today):
    cards = collect(today, t["key"])
    if not cards:
        return ""
    YEAR = today.year
    all_days = sorted({c["first"] for c in cards})
    span = f"{all_days[0].month}/{all_days[0].day}"
    if len(all_days) > 1:
        span += f"〜{all_days[-1].month}/{all_days[-1].day}"
    out = []
    for c in cards:
        aw = " hp-win" if c["win"] == "a" else ""
        bw = " hp-win" if c["win"] == "b" else ""
        tag = ""
        if c["played"] and c["decider"] and c["win"]:
            tag = '<span class="hp-day hp-rep">代表決定</span>'
        if c["played"]:
            pk = f'<small class="hp-pk">PK{c["pk"][0]}-{c["pk"][1]}</small>' if c["pk"] else ""
            mid = f'<span class="hp-sc">{c["sa"]}<i>-</i>{c["sb"]}{pk}</span>'
        else:
            mid = '<span class="hp-sc hp-vs">vs</span>'
        la = _esc(c["la"]) if c["la"] else "&nbsp;"
        lb = _esc(c["lb"]) if c["lb"] else "&nbsp;"
        out.append(
            f'    <a class="hp-card" href="/prefectures/{c["slug"]}/">'
            f'<span class="hp-badge">{_esc(c["pref"])} {_esc(c["label"])}'
            f'<span class="hp-day">{_fmt_days(c["days"])}</span>{tag}</span>'
            f'<span class="hp-row">'
            f'<span class="hp-tm hp-h{aw}"><span class="hp-rk">{la}</span>{_esc(c["a"])}</span>'
            f'{mid}'
            f'<span class="hp-tm hp-a{bw}"><span class="hp-rk">{lb}</span>{_esc(c["b"])}</span>'
            f"</span></a>"
        )
    nl = "\n"
    url = f"/tournaments/{t['key']}-{YEAR}/"
    more = ""
    if (_ROOT / url.strip("/") / "index.html").exists():   # 特設ページがまだ無い年はリンクを出さない
        more = f'  <p class="hp-more"><a href="{url}">{t["more"]}</a></p>\n'
    return (
        f'  <div class="hp-head"><h2>{t["title"]}</h2>'
        f'<span class="hp-date">{span}の準決勝・決勝から</span></div>\n'
        '  <div class="hp-grid">\n'
        + nl.join(out) + "\n"
        "  </div>\n"
        + more
    )


if __name__ == "__main__":
    import sys
    t = None
    if len(sys.argv) > 1:   # 例: python scraper/home_senshuken.py 2026-11-02 [interhigh]
        y, m, d = (int(x) for x in sys.argv[1].split("-"))
        t = date(y, m, d)
    for c in collect(t, sys.argv[2] if len(sys.argv) > 2 else "senshuken"):
        sc = f'{c["sa"]}-{c["sb"]}' + (f'(PK{c["pk"][0]}-{c["pk"][1]})' if c["pk"] else "") if c["played"] else "vs"
        print(c["first"], c["pref"], c["label"], f'{c["a"]}[{c["la"]}] {sc} {c["b"]}[{c["lb"]}]')
