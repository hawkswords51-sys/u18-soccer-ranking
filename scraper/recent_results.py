# -*- coding: utf-8 -*-
"""
リーグページ「直近の試合結果 / 次節の日程」セクション生成モジュール
------------------------------------------------------------------
generate_league_pages.py から呼ばれ、各リーグの順位表の直上に
「直近の試合結果（第N節）」＋「次節の日程」を差し込むためのもの。

設計のポイント（cross_table.py と同じ思想）:
  - データは data/league_matches/<slug>.json（戦績表と同じファイル）を再利用する。
    → 新しいデータ入力は不要。毎朝の自動更新にそのまま乗る。
  - そのファイルが無い／中身が空のリーグでは空文字 "" を返す → 既存ページに一切影響しない。
  - 「直近節」＝結果が入っている試合のうち最大の md（節）。
    次の節の結果が入るまで、その節の結果が出続ける（＝Keiの要望どおり）。
  - 「次節」＝直近節より後で、まだ結果が入っていない最小の md。
    全日程が終わっていれば次節ブロックは出さない。
  - 配色は CSS 変数（var(--bg-white) 等）を使うのでダークモードでも崩れない。
"""
import json
from datetime import date
from pathlib import Path

_MATCH_DIR = Path(__file__).resolve().parent.parent / "data" / "league_matches"

_WD = ("月", "火", "水", "木", "金", "土", "日")


def _html_escape(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fmt_date(iso: str, style: str = "slash", with_year: bool = False) -> str:
    """'2026-08-29' -> '8/29(土)'（slash）/ '8月29日(土)'（kanji）。
    with_year=True なら先頭に '2026年' を付ける。パースできなければ元の文字列を返す。"""
    if not iso:
        return ""
    try:
        y, m, d = (int(x) for x in str(iso).split("-")[:3])
        wd = _WD[date(y, m, d).weekday()]
    except Exception:
        return _html_escape(iso)
    head = f"{y}年" if with_year else ""
    body = f"{m}月{d}日" if style == "kanji" else f"{m}/{d}"
    return f"{head}{body}({wd})"


def _is_played(m: dict) -> bool:
    return (
        m.get("status") == "played"
        and m.get("hs") is not None
        and m.get("as") is not None
    )


def _md_of(m: dict):
    try:
        return int(m.get("md"))
    except Exception:
        return None


def _match_row(m: dict, link_fn, played: bool) -> str:
    home = m.get("home", "")
    away = m.get("away", "")
    hn = link_fn(home) if link_fn else _html_escape(home)
    an = link_fn(away) if link_fn else _html_escape(away)
    dt = _fmt_date(m.get("date", ""))

    if played:
        hs, a_s = m.get("hs"), m.get("as")
        h_cls = " rr-win" if hs > a_s else ""
        a_cls = " rr-win" if a_s > hs else ""
        center = f'<span class="rr-score">{hs}<span class="rr-dash">-</span>{a_s}</span>'
    else:
        h_cls = a_cls = ""
        center = '<span class="rr-vs">vs</span>'

    return (
        '<li class="rr-row">'
        f'<span class="rr-date">{dt}</span>'
        f'<span class="rr-team rr-home{h_cls}">{hn}</span>'
        f"{center}"
        f'<span class="rr-team rr-away{a_cls}">{an}</span>'
        "</li>"
    )


_STYLE = """<style>
.rr-section{margin:28px 0;}
.rr-section h2.section-title-lp{margin:0 0 8px;}
.rr-meta{font-size:.9rem;color:var(--text-light);margin:0 0 12px;}
.rr-list{list-style:none;margin:0 0 4px;padding:0;border:1px solid var(--border-color);
  border-radius:10px;overflow:hidden;background:var(--bg-white);}
.rr-row{display:grid;grid-template-columns:76px 1fr auto 1fr;align-items:center;gap:8px;
  padding:11px 14px;border-bottom:1px solid var(--border-color);}
.rr-list .rr-row:last-child{border-bottom:none;}
.rr-date{font-size:.85rem;color:var(--text-light);white-space:nowrap;}
.rr-team{font-size:1rem;color:var(--text-dark);line-height:1.35;}
.rr-home{text-align:right;}
.rr-away{text-align:left;}
.rr-team a{color:var(--text-dark);text-decoration:none;border-bottom:1px dotted var(--border-color);}
.rr-team a:hover{color:var(--accent-color);}
.rr-win{font-weight:700;}
.rr-score{font-weight:700;font-size:1.12rem;color:var(--accent-color);white-space:nowrap;
  min-width:62px;text-align:center;}
.rr-score .rr-dash{margin:0 5px;opacity:.6;font-weight:400;}
.rr-vs{font-size:.85rem;color:var(--text-light);min-width:62px;text-align:center;}
.rr-next-h{margin:20px 0 6px;font-size:1.05rem;font-weight:700;color:var(--text-dark);
  display:flex;align-items:center;gap:8px;}
.rr-next-h .rr-badge{font-size:.72rem;font-weight:700;letter-spacing:.04em;padding:3px 9px;
  border-radius:999px;background:var(--primary-hover-bg);color:var(--accent-color);}
.rr-done{font-size:.92rem;color:var(--text-light);margin-top:14px;}
.rr-src{font-size:.82rem;color:var(--text-light);margin:8px 0 0;}
.rr-src a{color:var(--text-light);}
@media (max-width:600px){
  .rr-row{grid-template-columns:1fr auto 1fr;gap:6px;padding:10px 10px 9px;
    row-gap:2px;}
  .rr-date{grid-column:1 / -1;order:-1;font-size:.78rem;}
  .rr-team{font-size:.92rem;}
  .rr-score{font-size:1.02rem;min-width:52px;}
  .rr-vs{min-width:52px;}
}
</style>"""


def render_recent_results_html(slug: str, label: str = "", link_fn=None) -> str:
    """リーグ slug の「直近の試合結果＋次節」セクションHTMLを返す。
    データが無い / 1試合も消化していない場合は ''（空文字）。

    link_fn: チーム名 -> 表示用HTML（チーム詳細ページへのリンク付き）に変換する関数。
             省略時はエスケープしたテキストのみ。
    """
    path = _MATCH_DIR / f"{slug}.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    matches = [m for m in data.get("matches", []) if _md_of(m) is not None]
    if not matches:
        return ""

    played = [m for m in matches if _is_played(m)]
    if not played:
        return ""

    # --- 直近節の決め方（ここが肝） ---
    # ① 節番号(md)の大きさでは決められない。プリンス東北のように「延期分を第18節として
    #    4月に消化する」等、mdが日付順に並ばないリーグが実在する（2026-08-29確認）。
    # ② 「いちばん新しい試合日」でも決められない。プレミアWESTや北信越2部のように、
    #    古い節の延期分が1試合だけ後日に組まれることがあり、その1試合に引きずられる。
    # → 各節の「代表日＝消化済み試合の日付の中央値」で比較する。延期分は少数派なので
    #    中央値には影響せず、節が本来行われた日で正しく比較できる。
    md_dates = {}
    for m in played:
        md_dates.setdefault(_md_of(m), []).append(str(m.get("date") or ""))

    def _rep(md):
        ds = sorted(md_dates[md])
        return ds[len(ds) // 2]

    last_md = max(md_dates, key=lambda md: (_rep(md), len(md_dates[md]), md))
    last_rep_date = _rep(last_md)
    last_matches = sorted(
        [m for m in matches if _md_of(m) == last_md],
        key=lambda m: (str(m.get("date") or ""), str(m.get("home") or "")),
    )
    last_played = [m for m in last_matches if _is_played(m)]
    if not last_played:
        return ""

    dates = sorted({str(m.get("date")) for m in last_played if m.get("date")})
    if len(dates) == 1:
        date_label = _fmt_date(dates[0], "kanji", with_year=True)
    elif dates:
        date_label = f'{_fmt_date(dates[0], "kanji", with_year=True)}〜{_fmt_date(dates[-1], "kanji")}'
    else:
        date_label = ""

    rows = [_match_row(m, link_fn, True) for m in last_played]
    pending = [m for m in last_matches if not _is_played(m)]
    for m in pending:
        rows.append(_match_row(m, link_fn, False))

    label_txt = _html_escape(label).strip()
    meta_bits = []
    if date_label:
        meta_bits.append(date_label)
    meta_bits.append(f"{len(last_played)}試合")
    if pending:
        meta_bits.append(f"未実施{len(pending)}試合")
    meta = "　".join(meta_bits)

    nl = "\n"
    html = [
        '      <section class="lp-section rr-section" id="recent-results">',
        _STYLE,
        f'        <h2 class="section-title-lp"><i class="fas fa-bolt"></i> '
        f"{label_txt}直近の試合結果（第{last_md}節）</h2>",
        f'        <p class="rr-meta">{meta}</p>',
        '        <ul class="rr-list">',
        nl.join("          " + r for r in rows),
        "        </ul>",
    ]

    # --- 次節 = 直近節より後に予定されていて、まだ結果が入っていない最も早い節 ---
    # 直近節と同じく、各節の代表日（未消化試合の日付の中央値）で比較する。
    nmd_dates = {}
    for m in matches:
        if _is_played(m) or _md_of(m) == last_md:
            continue
        nmd_dates.setdefault(_md_of(m), []).append(str(m.get("date") or ""))

    def _nrep(md):
        ds = sorted(nmd_dates[md])
        return ds[len(ds) // 2]

    cands = [md for md in nmd_dates if _nrep(md) > last_rep_date]
    next_md = min(cands, key=lambda md: (_nrep(md), md)) if cands else None
    if next_md is not None:
        next_matches = sorted(
            [m for m in matches if _md_of(m) == next_md],
            key=lambda m: (str(m.get("date") or ""), str(m.get("home") or "")),
        )
        ndates = sorted({str(m.get("date")) for m in next_matches if m.get("date")})
        if len(ndates) == 1:
            nlabel = _fmt_date(ndates[0], "kanji", with_year=True)
        elif ndates:
            nlabel = f'{_fmt_date(ndates[0], "kanji", with_year=True)}〜{_fmt_date(ndates[-1], "kanji")}'
        else:
            nlabel = "日程未定"
        nrows = [_match_row(m, link_fn, _is_played(m)) for m in next_matches]
        html += [
            f'        <h3 class="rr-next-h"><span class="rr-badge">NEXT</span>'
            f"次節 第{next_md}節　{nlabel}</h3>",
            '        <ul class="rr-list">',
            nl.join("          " + r for r in nrows),
            "        </ul>",
        ]
    else:
        html.append(
            '        <p class="rr-done">全日程が終了しました。最終順位は下の順位表をご覧ください。</p>'
        )

    src = data.get("source", "")
    last_updated = data.get("lastUpdated", "")
    src_bits = []
    if last_updated:
        src_bits.append(f"最終更新 {_html_escape(last_updated)}")
    if src:
        src_bits.append(f'出典 <a href="{_html_escape(src)}" target="_blank" rel="nofollow noopener">koko-soccer.com</a>')
    if src_bits:
        html.append('        <p class="rr-src">' + "　".join(src_bits) + "</p>")

    html.append("      </section>")
    return nl.join(html) + nl


# 単体テスト用: python recent_results.py prince-hokkaido
if __name__ == "__main__":
    import sys
    s = sys.argv[1] if len(sys.argv) > 1 else "premier-east"
    out = render_recent_results_html(s, label="")
    print(out if out else f"(データなし: {s}.json)")
