#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""選手権2026特設ページ /tournaments/senshuken-2026/ の自動更新部分を生成する（2026-10-04 新設）。

- データの正本: data/tournaments/senshuken-2026/{pref}-senshuken-2026.md（47ファイル。botが毎日koko-soccerから結果を書き込む）
- tournaments/senshuken-2026/index.html の次の2区間だけを書き換える（それ以外は手書きのまま）:
    <!-- SENSHUKEN_SUMMARY_START --> 〜 <!-- SENSHUKEN_SUMMARY_END -->  H1直下のAI引用向け一文要約
    <!-- SENSHUKEN_PREFS_START -->   〜 <!-- SENSHUKEN_PREFS_END -->    47都道府県の予選状況・代表校の一覧
    <!-- SENSHUKEN_BRACKET_START --> 〜 <!-- SENSHUKEN_BRACKET_END -->  本大会のトーナメント表（2026-10-07 追加）
- 本大会のトーナメント表: data/tournaments/senshuken-final-2026.md の「## トーナメント表（組み合わせ）」が
  ちょうど32行（48代表＝1回戦16試合＋シード16校）のときだけ、インハイと同じ描画関数で SVG を出す。
  0行（抽選前）・md無しは区間を空に。1〜31行／33行以上は書きかけとみなして描かずに [要確認]。
  表の区間は上の2区間と独立して更新する（47県のmdが揃わない等で2区間を止めても、表は止めない。逆も同じ）。
- 背景: 9/11の週次SEOで「8月時点の内容のまま・県ページへのリンク0本・AI要約なし」が見つかった。
  Googleで選手権予選の検索が増える10〜11月に、47県ページへの入口と「どこまで決まったか」を毎日自動で出す。
- 安全装置: 47県のmdが揃わない／マーカーが1組ずつ無い場合はページを書き換えずに [要確認] を出して終わる。
  決勝に結果があるのに勝者を読めない県も [要確認]（その県の代表欄は「確認中」と出す。誤った校名は載せない）。
- 代表の判定: 見出しが「決勝」ちょうどのラウンド（括弧の日付は除く）。東京だけは「Aブロック決勝」「Bブロック決勝」の2つ
  （東京の1次予選の「ブロック決勝」や、群馬の「A〜Hブロック決勝」は代表決定戦ではないので数えない）。
- sitemap には触らない（このURLは generate_interhigh_page.py の static_pages で登録済み）。
- [2026-10-28] 決勝日は md の見出し「## 決勝（11/8）」が無い県でも frontmatter の
  `round_dates: 準々決勝=10/31, 準決勝=11/7, 決勝=11/14`（県ページのトーナメント表と同じ書き方）から補う。
  見出しの日付が優先。どちらも無い県は従来どおり何も出さない。
- [2026-10-28] 47県一覧の先頭に「今週の準決勝・決勝」（今日から7日以内に日付がある準決勝・決勝で、まだ全試合
  終わっていないもの）を日付順に自動で出す。該当が無い日は見出しごと出さない。
- [2026-10-28] 代表校の行に「所属リーグ（teams.json・インハイページと同じ短縮）」「県内総合順位（県ページと同じ
  pref_order の並び）」「直近10大会の出場歴（tournaments_data.yml の都道府県代表 2016〜2025 から
  ◯年連続／◯大会ぶり／直近10大会は出場なし）」を自動で付ける。通算の「◯回目」は10大会分しか無いので書かない
  （JFA公式の「◯年ぶり◯回目」は抽選後に senshuken-final-2026.md の各県代表欄で入れる）。名寄せできない校は校名だけ。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jst import today  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TDIR = ROOT / "data" / "tournaments"
PAGE = ROOT / "tournaments" / "senshuken-2026" / "index.html"
S_START, S_END = "<!-- SENSHUKEN_SUMMARY_START -->", "<!-- SENSHUKEN_SUMMARY_END -->"
P_START, P_END = "<!-- SENSHUKEN_PREFS_START -->", "<!-- SENSHUKEN_PREFS_END -->"
B_START, B_END = "<!-- SENSHUKEN_BRACKET_START -->", "<!-- SENSHUKEN_BRACKET_END -->"
FINAL_MD = TDIR / "senshuken-final-2026.md"
BRACKET_ROWS = 32  # 48代表＝1回戦16試合（開幕戦を含む）＋シード16校

# 地域順（9地域）。(地域, [(slug, 表示名), ...])
REGIONS = [
    ("北海道", [("hokkaido", "北海道")]),
    ("東北", [("aomori", "青森"), ("iwate", "岩手"), ("miyagi", "宮城"), ("akita", "秋田"),
              ("yamagata", "山形"), ("fukushima", "福島")]),
    ("関東", [("ibaraki", "茨城"), ("tochigi", "栃木"), ("gunma", "群馬"), ("saitama", "埼玉"),
              ("chiba", "千葉"), ("tokyo", "東京"), ("kanagawa", "神奈川"), ("yamanashi", "山梨")]),
    ("北信越", [("niigata", "新潟"), ("toyama", "富山"), ("ishikawa", "石川"), ("fukui", "福井"),
                ("nagano", "長野")]),
    ("東海", [("shizuoka", "静岡"), ("aichi", "愛知"), ("mie", "三重"), ("gifu", "岐阜")]),
    ("関西", [("shiga", "滋賀"), ("kyoto", "京都"), ("osaka", "大阪"), ("hyogo", "兵庫"),
              ("nara", "奈良"), ("wakayama", "和歌山")]),
    ("中国", [("tottori", "鳥取"), ("shimane", "島根"), ("okayama", "岡山"), ("hiroshima", "広島"),
              ("yamaguchi", "山口")]),
    ("四国", [("tokushima", "徳島"), ("kagawa", "香川"), ("ehime", "愛媛"), ("kochi", "高知")]),
    ("九州", [("fukuoka", "福岡"), ("saga", "佐賀"), ("nagasaki", "長崎"), ("kumamoto", "熊本"),
              ("oita", "大分"), ("miyazaki", "宮崎"), ("kagoshima", "鹿児島"), ("okinawa", "沖縄")]),
]
TOTAL_REPS = 48  # 47都道府県＋東京2

HEAD_RE = re.compile(r"^##\s+(?P<key>[^（(]+?)\s*(?:[（(](?P<dates>[^）)]*)[）)])?\s*$")
SCORE_RE = re.compile(r"^-\s+(?P<a>.+?)\s+(?P<sa>\d+)-(?P<sb>\d+)(?:\(PK(?P<pa>\d+)-(?P<pb>\d+)\))?\s+(?P<b>.+?)\s*$")
VS_RE = re.compile(r"^-\s+.+\s+vs\s+.+$")
MD_RE = re.compile(r"(\d{1,2})/(\d{1,2})")

warnings = []


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def parse_md(path):
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for ln in parts[1].splitlines():
                if ":" in ln and not ln.startswith(" "):
                    k, v = ln.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = parts[2]
    rounds = []  # [{key, dates:[(m,d)], played:[(a,b,winner)], pending:int}]
    cur = None
    for raw in body.splitlines():
        s = raw.strip()
        m = HEAD_RE.match(s)
        if m:
            dates = [(int(a), int(b)) for a, b in MD_RE.findall(m.group("dates") or "")]
            cur = {"key": m.group("key").strip(), "dates": dates, "played": [], "pending": 0}
            rounds.append(cur)
            continue
        if cur is None or not s.startswith("- "):
            continue
        sm = SCORE_RE.match(s)
        if sm:
            sa, sb = int(sm.group("sa")), int(sm.group("sb"))
            winner = None
            if sa != sb:
                winner = sm.group("a") if sa > sb else sm.group("b")
            elif sm.group("pa") is not None:
                pa, pb = int(sm.group("pa")), int(sm.group("pb"))
                if pa != pb:
                    winner = sm.group("a") if pa > pb else sm.group("b")
            cur["played"].append((sm.group("a"), sm.group("b"), winner))
        elif VS_RE.match(s):
            cur["pending"] += 1
    return meta, rounds


def parse_round_dates(meta):
    """frontmatter `round_dates: 準々決勝=10/31・11/1, 準決勝=11/8, 決勝=11/14` → {回戦名: [(m,d),...]}
    （generate_prefecture_pages._parse_round_dates と同じ区切り方。日付の読み方だけ MD_RE に合わせる）"""
    out = {}
    for part in (meta.get("round_dates") or "").split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        dates = [(int(a), int(b)) for a, b in MD_RE.findall(v)]
        if k.strip() and dates:
            out[k.strip()] = dates
    return out


UPCOMING_DAYS = 7  # 「今週の準決勝・決勝」に出す範囲（今日から何日先まで）


def is_semi(key):
    return key.startswith("準決勝")


def season_key(md):
    """予選は6月〜翌1月にまたがらないが、念のため 1〜5月は翌年扱いにして並べる"""
    m, d = md
    return (m + 12 if m <= 5 else m, d)


def is_final(slug, key):
    if key == "決勝":
        return True
    return slug == "tokyo" and re.fullmatch(r"[AB]ブロック決勝", key) is not None


def fmt_dates(dates):
    return "・".join(f"{m}/{d}" for m, d in dates)


def rep_link(name):
    """代表校名。チーム詳細ページがあれば /teams/{id}/ へリンク（県ページ・インハイと同じ名寄せ＝team-profiles の name/short_name/aliases）。"""
    from generate_interhigh_page import team_link  # noqa: E402  import時は読むだけで書き込まない
    if name == "確認中":
        return esc(name)
    return team_link(name)


# ---- [2026-10-28] 代表校の付記（所属リーグ・県内総合順位・直近10大会の出場歴） ----
_REP_INFO_CACHE = {}


def _norm(n):
    import unicodedata
    n = unicodedata.normalize("NFKC", n or "")
    return n.replace(" ", "").replace("\u3000", "")


def _name_keys(name):
    """照合用：そのまま＋「高校」等を外した形。"""
    n = _norm(name)
    base = re.sub(r"(高等学校|高等部|高校|高)$", "", n)
    return {n, base} if base else {n}


def _load_rep_info():
    """{ 'rank': {slug: {照合名: 県内順位}}, 'history': {照合名: set(年)} , 'years': [年...] }"""
    if _REP_INFO_CACHE:
        return _REP_INFO_CACHE
    import json
    rank = {}
    try:
        from pref_order import pref_sort_key  # 県内総合順位の並べ替え（正本）
        teams_data = json.loads((ROOT / "data" / "teams.json").read_text(encoding="utf-8"))
        for slug, pref in teams_data.items():
            if not isinstance(pref, dict) or "teams" not in pref:
                continue
            m = {}
            for i, t in enumerate(sorted(pref["teams"], key=pref_sort_key), 1):
                for nm in [t.get("name")] + list(t.get("aliases") or []):
                    for k in _name_keys(nm or ""):
                        m.setdefault(k, i)
            rank[slug] = m
    except Exception as e:  # 付記が作れなくても特設ページ本体は止めない
        warnings.append(f"県内順位の読み込みに失敗（付記なしで続行）: {type(e).__name__}: {e}")
    history, years = {}, []
    try:
        import yaml
        d = yaml.safe_load((ROOT / "data" / "tournaments_data.yml").read_text(encoding="utf-8"))
        for y, info in (d.get("all_japan_highschool") or {}).items():
            reps = (info or {}).get("都道府県代表") or []
            if not reps:
                continue
            years.append(int(y))
            for r in reps:
                nm = r.get("name") if isinstance(r, dict) else r
                for k in _name_keys(nm or ""):
                    history.setdefault(k, set()).add(int(y))
    except Exception as e:
        warnings.append(f"歴代代表（tournaments_data.yml）の読み込みに失敗（出場歴なしで続行）: {type(e).__name__}: {e}")
    _REP_INFO_CACHE.update({"rank": rank, "history": history, "years": sorted(years)})
    return _REP_INFO_CACHE


def rep_note(slug, name):
    """代表校の後ろに付ける小さな付記のHTML。何も分からなければ空文字。"""
    if not name or name == "確認中":
        return ""
    info = _load_rep_info()
    parts = []
    # 所属リーグ（インハイページと同じ表・同じ短縮名。県名は行頭にあるので省く）
    try:
        from generate_interhigh_page import SCHOOL_LEAGUE_MAP, _norm_team
        meta = SCHOOL_LEAGUE_MAP.get(_norm_team(name))
        if meta:
            lg, url = meta[1], (meta[2] if len(meta) > 2 else "")
            parts.append(f'<a href="{esc(url)}" style="text-decoration:none;">{esc(lg)}</a>' if url else esc(lg))
    except Exception:
        pass
    # 県内総合順位
    r = None
    for k in _name_keys(name):
        r = info["rank"].get(slug, {}).get(k)
        if r:
            break
    if r and r < 99:
        parts.append(f"県内{r}位")
    # 直近10大会の出場歴（tournaments_data.yml にある年だけで判定）
    years = info["years"]
    if years:
        app = set()
        for k in _name_keys(name):
            app |= info["history"].get(k, set())
        last = years[-1]
        n = len(years)
        if last in app:
            streak = 1
            y = last
            while y - 1 in years and y - 1 in app:
                streak += 1
                y -= 1
            parts.append(f"{streak + 1}年連続")
        elif app:
            parts.append(f"{SEASON_YEAR - max(app)}大会ぶり")
        else:
            parts.append(f"直近{n}大会は出場なし")
    if not parts:
        return ""
    return ('<span style="font-size:0.82em;font-weight:400;color:var(--text-light,#64748b);white-space:nowrap;">'
            + "（" + "・".join(parts) + "）</span>")


SEASON_YEAR = 2026  # 第105回＝2026年度


def analyze(slug):
    path = TDIR / "senshuken-2026" / f"{slug}-senshuken-2026.md"  # [2026-10-10] 大会フォルダへ移動
    if not path.exists():
        return None
    meta, rounds = parse_md(path)
    finals = [r for r in rounds if is_final(slug, r["key"])]
    reps = []  # [(label, winner or None)]
    for r in finals:
        label = r["key"].replace("決勝", "") if slug == "tokyo" else ""
        if r["played"]:
            w = r["played"][0][2]
            if w is None:
                warnings.append(f"{slug}: 「{r['key']}」に結果があるが勝者を判定できない → 代表欄は「確認中」")
            reps.append((label, w if w else "確認中"))
    played_rounds = [r for r in rounds if r["played"]]
    n_played = sum(len(r["played"]) for r in rounds)
    latest = None
    if played_rounds:
        # 日付が分かるラウンドは日付の新しい方、日付が無ければファイル内で後ろの方
        latest = max(enumerate(played_rounds),
                     key=lambda t: (max((season_key(x) for x in t[1]["dates"]), default=(0, 0)), t[0]))[1]["key"]
    final_dates = sorted({d for r in finals for d in r["dates"]}, key=season_key)
    rd = parse_round_dates(meta)
    if not final_dates and rd.get("決勝"):
        final_dates = sorted(set(rd["決勝"]), key=season_key)  # [2026-10-28] 見出しが無ければ round_dates で補う
    first_dates = sorted({d for r in rounds for d in r["dates"]}, key=season_key)
    # [2026-10-28] 「今週の準決勝・決勝」用：まだ全試合終わっていない準決勝・決勝とその日付
    upcoming = []  # [(dates, label, pending_or_None)]
    seen = set()
    for r in rounds:
        if not (is_final(slug, r["key"]) or is_semi(r["key"])):
            continue
        label = "準決勝" if is_semi(r["key"]) else r["key"]
        dates = r["dates"] or rd.get("準決勝" if is_semi(r["key"]) else "決勝") or []
        done = bool(r["played"]) and r["pending"] == 0
        if dates and not done:
            upcoming.append((dates, label))
            seen.add(label)
    # 見出し自体がまだ無い県は round_dates だけで出す（決勝の見出しは直前にしか作られない県が多い）
    for name in ("準決勝", "決勝"):
        if name in seen or not rd.get(name):
            continue
        if name == "決勝" and slug == "tokyo":
            continue  # 東京は A/Bブロック決勝の見出しで数える
        upcoming.append((rd[name], name))
    return {
        "upcoming": upcoming,
        "status": meta.get("status", ""),
        "n_played": n_played,
        "latest": latest,
        "reps": reps,
        "final_dates": final_dates,
        "first_date": first_dates[0] if first_dates else None,
        "has_final_heading": bool(finals),
    }


def state_label(info):
    need = 2 if info.get("tokyo") else 1
    decided = [w for _, w in info["reps"] if w and w != "確認中"]
    if len(decided) >= need:
        return "代表決定", "done"
    if info["n_played"] == 0:
        if info["first_date"]:
            m, d = info["first_date"]
            td = today()
            if season_key((m, d)) <= season_key((td.month, td.day)):
                # 開幕日は過ぎたが、koko側にまだスコアが無い（翌日以降の自動更新で入る）
                return f"結果反映待ち（{m}/{d}開幕）", "pre"
            return f"開幕前（{m}/{d}〜）", "pre"
        return "開幕前", "pre"
    return f"{info['latest']}まで終了", "live"


def render_upcoming(all_info):
    """今日から UPCOMING_DAYS 日以内に日付がある準決勝・決勝を日付順に。該当なしなら空文字。"""
    td = today()
    lo = season_key((td.month, td.day))
    import datetime as _dt
    end = _dt.date(td.year, td.month, td.day) + _dt.timedelta(days=UPCOMING_DAYS)
    hi = season_key((end.month, end.day))
    by_date = {}  # (m,d) -> [(name, label)]
    for _, prefs in REGIONS:
        for slug, name in prefs:
            for dates, label in all_info[slug].get("upcoming", []):
                for d in dates:
                    if lo <= season_key(d) <= hi:
                        by_date.setdefault(d, []).append((slug, name, label))
    if not by_date:
        return ""
    out = ['      <div class="senshuken-upcoming" style="margin:0 0 18px;padding:10px 14px;'
           'border:1px solid var(--border-color,#e2e8f0);border-radius:6px;">',
           f'        <p style="margin:0 0 6px;font-weight:700;">今週の準決勝・決勝（{td.month}/{td.day}から{UPCOMING_DAYS}日以内）</p>',
           '        <ul style="list-style:none;padding:0;margin:0;font-size:0.92em;line-height:1.9;">']
    for d in sorted(by_date, key=season_key):
        finals = [(s_, n) for s_, n, lb in by_date[d] if lb != "準決勝"]
        semis = [(s_, n) for s_, n, lb in by_date[d] if lb == "準決勝"]
        parts = []
        if finals:
            parts.append("決勝：" + "・".join(f'<a href="/prefectures/{s_}/">{n}</a>' for s_, n in finals))
        if semis:
            parts.append("準決勝：" + "・".join(f'<a href="/prefectures/{s_}/">{n}</a>' for s_, n in semis))
        out.append(f'          <li><span style="font-weight:600;min-width:3.2em;display:inline-block;">{d[0]}/{d[1]}</span>'
                   + "　".join(parts) + '</li>')
    out.append('        </ul>')
    out.append('      </div>')
    return "\n".join(out)


def render_prefs(all_info):
    out = []
    up = render_upcoming(all_info)
    if up:
        out.append(up)
    out.append('      <div class="senshuken-prefs">')
    for region, prefs in REGIONS:
        out.append(f'        <h3 style="margin:22px 0 8px;font-size:1.02rem;">{region}</h3>')
        out.append('        <ul style="list-style:none;padding:0;margin:0;">')
        for slug, name in prefs:
            info = all_info[slug]
            label, kind = state_label(info)
            # 2026-10-24 色つきの丸いバッジをやめ、文字だけにした（KeiがAIっぽいと判断）。代表決定だけ文字を濃くする
            color = {"done": "var(--text-color,#1f2937)", "live": "var(--text-light,#64748b)", "pre": "var(--text-light,#64748b)"}[kind]
            if info["reps"] and any(w for _, w in info["reps"]):
                rep_txt = " ／ ".join(
                    (f"{lb}：" if lb else "") + rep_link(w) + rep_note(slug, w) for lb, w in info["reps"] if w)
                rep_html = f'<span style="font-weight:700;">代表：{rep_txt}</span>'
            elif info["final_dates"]:
                rep_html = f'<span style="font-size:0.85em;color:var(--text-light,#64748b);">決勝 {fmt_dates(info["final_dates"])}</span>'
            else:
                rep_html = ""
            out.append(
                '          <li style="display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;'
                'padding:7px 2px;border-bottom:1px solid var(--border-color,#e2e8f0);">'
                # 1行に収める（スマホで47行×2段になると4,000px超になったため、右端の文字リンクは「›」だけにした）
                f'<a href="/prefectures/{slug}/" style="font-weight:600;min-width:5.5em;">{name}予選</a>'
                f'<span style="font-size:0.85em;color:{color};">{esc(label)}</span>'
                f'{rep_html}'
                f'<a href="/prefectures/{slug}/" aria-label="{name}のトーナメント表・県内順位" style="margin-left:auto;text-decoration:none;">›</a>'
                '</li>')
        out.append('        </ul>')
    out.append('      </div>')
    return "\n".join(out)


def render_summary(all_info, n_reps, n_started, rep_list):
    t = today()
    stamp = f"{t.month}月{t.day}日現在、"
    if n_reps == 0:
        # ⚠️「最初の県決勝は◯日」とは書かない：決勝の見出しがmdに入っているのは一部の県だけで、
        #    それより早い決勝の県があっても分からないため（誤った断定をAIに引用させない）。
        status = f"47都道府県のうち{n_started}都道府県で試合結果が出ており、代表はまだ決まっていません。"
    else:
        shown = "、".join(rep_list[:6]) + ("など" if len(rep_list) > 6 else "")
        status = f"出場48代表のうち{n_reps}校が決まりました（{shown}）。"
    text = ("第105回全国高校サッカー選手権大会（2026年度）は2026年12月28日開幕・2027年1月11日決勝。"
            f"{stamp}{status}各都道府県の予選の進み具合と代表校は、下の一覧で毎日更新しています。"
            "前回第104回は神村学園（鹿児島）が初優勝し、インターハイとの夏冬2冠を達成しました。")
    return ('      <p class="blog-article__summary" style="margin:0 0 24px;padding:2px 0 2px 14px;'
            'border-left:2px solid var(--border-color,#cbd5e1);font-size:0.97rem;line-height:1.85;">\n'
            f'        {esc(text)}\n      </p>')


def replace_between(html, start, end, inner):
    if html.count(start) != 1 or html.count(end) != 1:
        return None
    a = html.index(start) + len(start)
    b = html.index(end)
    if a > b:
        return None
    return html[:a] + "\n" + inner + "\n      " + html[b:]


def parse_sections(path):
    """md を「## 見出し」ごとの行リストにする（generate_interhigh_page.parse_source と同じ分け方）。"""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    body = parts[2] if len(parts) == 3 and text.startswith("---") else text
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    sections, cur = {}, None
    for line in body.splitlines():
        h = re.match(r"^##\s+(.*)$", line)
        if h:
            cur = h.group(1).strip()
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(line)
    return sections


def render_bracket():
    """本大会トーナメント表の区間の中身。描かない（抽選前・書きかけ）ときは空文字。"""
    if not FINAL_MD.exists():
        return ""
    sections = parse_sections(FINAL_MD)
    key = next((k for k in sections if k.startswith("トーナメント表")), None)
    rows = [l for l in sections.get(key, []) if l.strip().startswith("- ")] if key else []
    if not rows:
        return ""
    if len(rows) != BRACKET_ROWS:
        print(f"[要確認] 選手権2026本大会: トーナメント表が{len(rows)}行（{BRACKET_ROWS}行のときだけ描く）。表は出さない。")
        return ""
    # 描くときだけ読み込む（import 時に team-profiles 等を読むが、書き込みはしない）
    from generate_interhigh_page import render_bracket_svg  # noqa: E402
    svg = render_bracket_svg(sections, sections.get("各県代表", []))
    if not svg:
        print("[要確認] 選手権2026本大会: トーナメント表を描けなかった。表は出さない。")
        return ""
    return ('      <section class="lp-section" id="bracket">\n'
            '        <h2><i class="fas fa-network-wired"></i> 本大会トーナメント表（組み合わせ）</h2>\n'
            f'        {svg}\n'
            '      </section>')


def update_prefs(html):
    """要約・47県一覧の2区間を書き換えた html を返す。安全装置で止めるときは None。"""
    all_info = {}
    missing = []
    for _, prefs in REGIONS:
        for slug, name in prefs:
            info = analyze(slug)
            if info is None:
                missing.append(slug)
                continue
            info["tokyo"] = slug == "tokyo"
            all_info[slug] = info
    if missing or len(all_info) != 47:
        print(f"[要確認] 選手権2026: mdが揃っていない（不足: {', '.join(missing)}）。要約・47県一覧は書き換えない。")
        return None
    n_reps = 0
    rep_list = []
    for _, prefs in REGIONS:
        for slug, name in prefs:
            for lb, w in all_info[slug]["reps"]:
                if w and w != "確認中":
                    n_reps += 1
                    rep_list.append(f"{name}{lb}・{w}" if lb else f"{name}・{w}")
    n_started = sum(1 for i in all_info.values() if i["n_played"] > 0)
    if n_reps > TOTAL_REPS:
        print(f"[要確認] 選手権2026: 代表が{n_reps}校と48を超えた。要約・47県一覧は書き換えない。")
        return None

    new = replace_between(html, S_START, S_END, render_summary(all_info, n_reps, n_started, rep_list))
    new = replace_between(new, P_START, P_END, render_prefs(all_info)) if new else None
    if new is None:
        print("[要確認] 選手権2026: 要約・47県一覧のマーカーが1組ずつ見つからない。この2区間は書き換えない。")
        return None
    for w in warnings:
        print(f"[要確認] {w}")
    print(f"選手権2026: 結果あり{n_started}都道府県・代表{n_reps}/{TOTAL_REPS}")
    return new


def main():
    html = PAGE.read_text(encoding="utf-8")
    new = html
    # 本大会トーナメント表（独立。失敗しても下の2区間は止めない）
    try:
        b = replace_between(new, B_START, B_END, render_bracket())
    except Exception as e:  # 表の不具合で毎日の更新全体を止めない
        print(f"[要確認] 選手権2026本大会: トーナメント表の生成で例外 {type(e).__name__}: {e}。表は出さない。")
        b = replace_between(new, B_START, B_END, "")
    if b is None:
        print("[要確認] 選手権2026: トーナメント表のマーカーが1組ずつ見つからない。表の区間は書き換えない。")
    else:
        new = b
    p = update_prefs(new)
    if p is not None:
        new = p
    if new != html:
        PAGE.write_text(new, encoding="utf-8")
        print("選手権2026特設ページを更新")
    else:
        print("選手権2026特設ページ: 変更なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
