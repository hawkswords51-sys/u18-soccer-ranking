# -*- coding: utf-8 -*-
"""チーム詳細ページの「第105回選手権 ◯◯県代表」バッジ（2026-10-28 新設）。

- データの正本: data/tournaments/senshuken-2026/{pref}-senshuken-2026.md（botが毎朝 koko から書き込む）。
  代表の判定は特設ページ（generate_senshuken_page.analyze）と同じ関数を使い、二重実装にしない。
- 代表校 → チームページの対応は、特設ページ・県ページと同じ名寄せ（team-profiles の name/short_name/aliases）。
- 該当しないチームでは空文字を返す＝他のページは1バイトも変わらない。
- 代表が決まったのにチームページが無い校は [要確認] で一覧にする（作るべきページの候補）。
"""
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
    _CACHE["map"] = out
    return dict(out)


def render_team_badge_html(team_id: str, badge_map: dict) -> str:
    """ヒーロー直下に置く深紅のバッジ。該当が無ければ空文字。"""
    e = (badge_map or {}).get(team_id)
    if not e:
        return ""
    pref = e["pref"] + {"東京": "都", "北海道": "", "京都": "府", "大阪": "府"}.get(e["pref"], "県")
    head = f"第105回全国高校サッカー選手権大会 {pref}代表" + (f"（{e['label']}）" if e.get("label") else "")
    when = f"・{e['date']}" if e.get("date") else ""
    final = f"決勝 {_esc(e['a'])} {_esc(e['score'])} {_esc(e['b'])}{when}"
    style = (
        "margin:0 0 14px;padding:12px 16px;background:rgba(255,255,255,0.95);"
        "color:#7f1d1d;border-left:4px solid #b91c1c;border-radius:0 8px 8px 0;"
        "font-size:0.92rem;line-height:1.8;"
    )
    return (
        f'      <p class="ss-badge" style="{style}">'
        f'<i class="fas fa-trophy" style="color:#b91c1c"></i> '
        f'<a href="/tournaments/senshuken-2026/#prefectures" style="color:#7f1d1d;font-weight:700;text-decoration:underline">'
        f'{_esc(head)}</a>　{final}</p>\n'
    )
