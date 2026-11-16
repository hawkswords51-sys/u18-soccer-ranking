# -*- coding: utf-8 -*-
"""チーム詳細ページの「第105回選手権 ◯◯県代表」バッジ（2026-10-28 新設）。

- データの正本: data/tournaments/senshuken-2026/{pref}-senshuken-2026.md（botが毎朝 koko から書き込む）。
  代表の判定は特設ページ（generate_senshuken_page.analyze）と同じ関数を使い、二重実装にしない。
- 代表校 → チームページの対応は、特設ページ・県ページと同じ名寄せ（team-profiles の name/short_name/aliases）。
- 該当しないチームでは空文字を返す＝他のページは1バイトも変わらない。
- 代表が決まったのにチームページが無い校は [要確認] で一覧にする（作るべきページの候補）。
- [2026-11-16] 本大会の組み合わせ（抽選会の結果）が決まったら、同じバッジの2行目に
  「本大会：1回戦（12/29） vs 相手校［県］→ 勝てば2回戦（12/31）で◯◯の勝者と対戦」を出す。
  データの正本は data/tournaments/senshuken-final-2026.md の「## トーナメント表（組み合わせ）」32行。
  判定は特設ページと同じ drawn_bracket()（32行そろい・抽選待ち0のときだけ）。抽選前・途中は2行目を出さない。
  32行の並び＝上から2行ずつが2回戦の1試合（1行目と2行目、3行目と4行目…）。「A vs B」の行＝1回戦、1校だけの行＝シード。
"""
import re
from html import escape as _esc

_CACHE = {}


def badges_by_team_id(base_dir=None) -> dict:
    """{team_id: {"pref": 県名, "label": "Aブロック" or "", "a": 校名, "b": 校名, "winner": 校名, "score": "2-1", "date": "11/1"}}"""
    if _CACHE:
        return dict(_CACHE["map"])
    import generate_senshuken_page as sp
    from generate_interhigh_page import TEAM_MAP, _short_label
    out, missing = {}, []
    for _, prefs in sp.REGIONS:
        for slug, pref_name in prefs:
            info = sp.analyze(slug)
            if not info:
                continue
            for label, a, b, w, score, dates in info.get("final_matches", []):
                if not w or w == "確認中":
                    continue
                tid = TEAM_MAP.get(w) or TEAM_MAP.get(_short_label(w))
                if not tid:
                    for suf in ("高校", "高等学校", "高等部"):
                        tid = TEAM_MAP.get(_short_label(w) + suf)
                        if tid:
                            break
                if not tid:
                    missing.append(f"{pref_name}・{w}")
                    continue
                out.setdefault(tid, {
                    "pref": pref_name, "label": label, "a": a, "b": b, "winner": w, "score": score,
                    "date": "・".join(f"{m}/{d}" for m, d in dates),
                })
    if missing:
        print("[要確認] 選手権2026 代表校だがチームページが無い（作成候補）: " + " / ".join(missing))
    try:
        _attach_draw(out, sp, TEAM_MAP, _short_label)
    except Exception as e:  # 組み合わせの不具合でバッジ（1行目）まで止めない
        print(f"[要確認] 選手権2026 本大会の組み合わせ（チームページのバッジ2行目）で例外 {type(e).__name__}: {e}。2行目は出さない。")
    _CACHE["map"] = out
    return dict(out)


FIRST_ROUND_DAY = "12/29"
SECOND_ROUND_DAY = "12/31"
OPENING_DAY = "12/28・国立"


def _tid_of(name, TEAM_MAP, _short_label):
    """代表校名 → チームページの id（1行目のバッジと同じ名寄せ）。無ければ None。"""
    tid = TEAM_MAP.get(name) or TEAM_MAP.get(_short_label(name))
    if not tid:
        for suf in ("高校", "高等学校", "高等部"):
            tid = TEAM_MAP.get(_short_label(name) + suf)
            if tid:
                break
    return tid


def _attach_draw(out, sp, TEAM_MAP, _short_label):
    """組み合わせ決定後だけ、out[team_id]["draw"] に本大会の対戦相手を入れる。"""
    got = sp.drawn_bracket()
    if not got:
        return
    sections, rows = got
    prefs = sp._rep_prefs(sections.get("各県代表", []))
    opening = sp._opening_pair()
    cells = [[x.strip() for x in re.split(r"\s+vs\s+", ln.strip()[2:].strip()) if x.strip()] for ln in rows]
    if len(cells) % 2 or any(len(c) not in (1, 2) for c in cells):
        print("[要確認] 選手権2026 本大会の組み合わせ: 行の形が想定外（1校 or A vs B）。チームページの2行目は出さない。")
        return

    def side(names):
        return [(n, prefs.get(n, ""), _tid_of(n, TEAM_MAP, _short_label)) for n in names]

    no_page, n_set = [], 0
    for i, cell in enumerate(cells):
        partner = side(cells[i ^ 1])
        for n in cell:
            tid = _tid_of(n, TEAM_MAP, _short_label)
            if not tid:
                no_page.append(n)
                continue
            if len(cell) == 2:
                other = [x for x in cell if x != n]
                if len(other) != 1:
                    continue
                d = {"kind": "first", "opp": side(other), "opening": set(cell) == opening and len(opening) == 2,
                     "next": partner}
            else:
                d = {"kind": "seed", "opp": partner}
            if tid not in out:  # 県予選の判定で代表バッジが作れなかった学校（念のため）
                out[tid] = {"pref": prefs.get(n, ""), "label": "", "a": "", "b": "", "winner": n, "score": "", "date": ""}
            out[tid]["draw"] = d
            n_set += 1
    print(f"選手権2026本大会: チームページのバッジに組み合わせを入れた学校 {n_set}校")
    if no_page:
        print("[要確認] 選手権2026 本大会出場だがチームページが無い（組み合わせを出せない）: " + "、".join(no_page))


def _sides_html(sides):
    """[(校名, 県, team_id)] → 「A高校［県］」または「A高校［県］／B高校［県］の勝者」"""
    parts = []
    for n, pref, tid in sides:
        nm = _esc(n)
        if tid:
            nm = f'<a href="/teams/{_esc(tid)}/" style="color:#7f1d1d;text-decoration:underline">{nm}</a>'
        parts.append(nm + (f"［{_esc(pref)}］" if pref else ""))
    return parts[0] if len(parts) == 1 else "／".join(parts) + " の勝者"


def _draw_html(d):
    link = ('<a href="/tournaments/senshuken-2026/#bracket" style="color:#7f1d1d;font-weight:700;'
            'text-decoration:underline">本大会の組み合わせ</a>')
    if d["kind"] == "seed":
        return f"{link}：2回戦から登場（{SECOND_ROUND_DAY}） vs {_sides_html(d['opp'])}"
    first = f"開幕戦（{OPENING_DAY}）" if d.get("opening") else f"1回戦（{FIRST_ROUND_DAY}）"
    return (f"{link}：{first} vs {_sides_html(d['opp'])}"
            f" → 勝てば2回戦（{SECOND_ROUND_DAY}）で {_sides_html(d['next'])}と対戦")


def render_team_badge_html(team_id: str, badge_map: dict) -> str:
    """ヒーロー直下に置く深紅のバッジ。該当が無ければ空文字。"""
    e = (badge_map or {}).get(team_id)
    if not e:
        return ""
    pref = e["pref"] + {"東京": "都", "北海道": "", "京都": "府", "大阪": "府"}.get(e["pref"], "県")
    head = f"第105回全国高校サッカー選手権大会 {pref}代表" + (f"（{e['label']}）" if e.get("label") else "")
    when = f"・{e['date']}" if e.get("date") else ""
    final = f"決勝 {_esc(e['a'])} {_esc(e['score'])} {_esc(e['b'])}{when}" if e.get("score") else ""
    draw = f"<br>{_draw_html(e['draw'])}" if e.get("draw") else ""
    style = (
        "margin:0 0 14px;padding:12px 16px;background:rgba(255,255,255,0.95);"
        "color:#7f1d1d;border-left:4px solid #b91c1c;border-radius:0 8px 8px 0;"
        "font-size:0.92rem;line-height:1.8;"
    )
    return (
        f'      <p class="ss-badge" style="{style}">'
        f'<i class="fas fa-trophy" style="color:#b91c1c"></i> '
        f'<a href="/tournaments/senshuken-2026/#prefectures" style="color:#7f1d1d;font-weight:700;text-decoration:underline">'
        f'{_esc(head)}</a>　{final}{draw}</p>\n'
    )
