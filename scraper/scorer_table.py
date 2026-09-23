# -*- coding: utf-8 -*-
"""
得点ランキング セクション生成モジュール
data/scorers/<slug>.json があればランキングHTMLを返す。無ければ ""（他リーグ無影響）。
データ形: {league, source, lastUpdated, note, scorers:[{rank,name,team,goals}], coverage:[...]}
"""
import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "data" / "scorers"


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_scorer_ranking_html(slug: str, limit: int = 20, min_goals: int = None) -> str:
    path = _DIR / f"{slug}.json"
    if not path.exists():
        return ""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    scorers = d.get("scorers", [])
    # min_goals を指定すると、その得点数以上の選手だけを表示（Jユース等で
    # 1得点の選手が大量にいる大会向け。未指定なら従来どおり全件・limit まで）。
    if min_goals is not None:
        scorers = [s for s in scorers if s.get("goals", 0) >= min_goals]
    if not scorers:
        return ""

    rows = []
    for s in scorers[:limit]:
        medal = ""
        if s["rank"] == 1: medal = "xs-gold"
        elif s["rank"] == 2: medal = "xs-silver"
        elif s["rank"] == 3: medal = "xs-bronze"
        rows.append(
            f'<tr><td class="xs-rk {medal}">{s["rank"]}</td>'
            f'<td class="xs-nm">{_esc(s["name"])}</td>'
            f'<td class="xs-tm">{_esc(s.get("team",""))}</td>'
            f'<td class="xs-go">{s["goals"]}</td></tr>'
        )
    nl = "\n"
    # 未掲載がある場合の注意
    miss = [c for c in d.get("coverage", []) if c.get("missing", 0) > 0]
    cov = ""
    if miss:
        ts = "・".join(f'{_esc(c["team"])}（{c["missing"]}点）' for c in miss)
        cov = (f'<p class="xs-cov">※次のチームは出典に得点者が未掲載の試合があり、'
               f'実際の得点より少なく集計されている可能性があります：{ts}</p>')
    src = d.get("source", "")
    src_label = d.get("sourceLabel") or "高校サッカー専門メディア"
    src_html = (f'　出典: <a href="{_esc(src)}" rel="nofollow" target="_blank">'
                f'{_esc(src_label)}</a>') if src else ""

    return f"""
      <section class="xs-section" id="scorer-ranking">
        <style>
        .xs-section{{margin:40px 0 12px;}}
        .xs-section h2{{font-size:1.5rem;margin:0 0 6px;border-left:6px solid #e67e22;padding-left:12px;}}
        .xs-meta{{font-size:.95rem;color:inherit;opacity:.75;margin:0 0 4px;}}
        .xs-note{{font-size:.85rem;color:inherit;opacity:.7;margin:2px 2px 10px;line-height:1.5;}}
        .xs-cov{{font-size:.8rem;color:#c0392b;margin:0 2px 10px;line-height:1.5;}}
        .xs-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #dfe3e8;border-radius:8px;max-width:560px;}}
        .xs-table{{width:100%;border-collapse:collapse;font-size:15px;background:#fff;color:#222;}}
        .xs-table th,.xs-table td{{border-bottom:1px solid #eee;padding:9px 12px;text-align:left;color:#222;}}
        .xs-table thead th{{background:#e67e22;color:#fff;font-weight:600;}}
        .xs-table .xs-rk{{width:48px;text-align:center;font-weight:700;color:#555;}}
        .xs-table .xs-go{{width:64px;text-align:center;font-weight:700;color:#e67e22;}}
        .xs-table .xs-tm{{color:#555;font-size:14px;}}
        .xs-rk.xs-gold,.xs-rk.xs-silver,.xs-rk.xs-bronze{{color:#fff;}}
        .xs-rk.xs-gold{{color:#fff;background:#f1c40f;border-radius:50%;}}
        .xs-rk.xs-silver{{color:#fff;background:#b0bec5;border-radius:50%;}}
        .xs-rk.xs-bronze{{color:#fff;background:#cd7f32;border-radius:50%;}}
        </style>
        <h2>⚽ 得点ランキング</h2>
        <p class="xs-meta">最終更新 {_esc(d.get('lastUpdated',''))}{src_html}</p>
        <p class="xs-note">{_esc(d.get('note',''))}</p>
        {cov}
        <div class="xs-wrap">
          <table class="xs-table">
            <thead><tr><th class="xs-rk">順</th><th>選手</th><th>チーム</th><th class="xs-go">得点</th></tr></thead>
            <tbody>
{nl.join(rows)}
            </tbody>
          </table>
        </div>
      </section>
"""


def render_assist_ranking_html(slug: str, limit: int = 300, min_assists: int = None) -> str:
    """アシストランキング セクション。

    data/scorers/<slug>.json に "assists" 配列があるときだけ描画し、無ければ ""。
    データ形: assists:[{rank,name,team,assists}] / 説明文は "assistNote"。
    この関数を呼ばない既存ページ（インターハイ・県・リーグ等）は一切影響を受けない。
    """
    path = _DIR / f"{slug}.json"
    if not path.exists():
        return ""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    recs = d.get("assists", [])
    if min_assists is not None:
        recs = [s for s in recs if s.get("assists", 0) >= min_assists]
    if not recs:
        return ""

    rows = []
    for s in recs[:limit]:
        medal = ""
        if s["rank"] == 1: medal = "xa-gold"
        elif s["rank"] == 2: medal = "xa-silver"
        elif s["rank"] == 3: medal = "xa-bronze"
        rows.append(
            f'<tr><td class="xa-rk {medal}">{s["rank"]}</td>'
            f'<td class="xa-nm">{_esc(s["name"])}</td>'
            f'<td class="xa-tm">{_esc(s.get("team",""))}</td>'
            f'<td class="xa-as">{s["assists"]}</td></tr>'
        )
    nl = "\n"
    src = d.get("source", "")
    src_label = d.get("sourceLabel") or "大会公式記録"
    src_html = (f'　出典: <a href="{_esc(src)}" rel="nofollow" target="_blank">'
                f'{_esc(src_label)}</a>') if src else ""

    return f"""
      <section class="xa-section" id="assist-ranking">
        <style>
        .xa-section{{margin:40px 0 12px;}}
        .xa-section h2{{font-size:1.5rem;margin:0 0 6px;border-left:6px solid #2980b9;padding-left:12px;}}
        .xa-meta{{font-size:.95rem;color:inherit;opacity:.75;margin:0 0 4px;}}
        .xa-note{{font-size:.85rem;color:inherit;opacity:.7;margin:2px 2px 10px;line-height:1.5;}}
        .xa-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #dfe3e8;border-radius:8px;max-width:560px;}}
        .xa-table{{width:100%;border-collapse:collapse;font-size:15px;background:#fff;color:#222;}}
        .xa-table th,.xa-table td{{border-bottom:1px solid #eee;padding:9px 12px;text-align:left;color:#222;}}
        .xa-table thead th{{background:#2980b9;color:#fff;font-weight:600;}}
        .xa-table .xa-rk{{width:48px;text-align:center;font-weight:700;color:#555;}}
        .xa-table .xa-as{{width:64px;text-align:center;font-weight:700;color:#2980b9;}}
        .xa-table .xa-tm{{color:#555;font-size:14px;}}
        .xa-rk.xa-gold,.xa-rk.xa-silver,.xa-rk.xa-bronze{{color:#fff;}}
        .xa-rk.xa-gold{{color:#fff;background:#f1c40f;border-radius:50%;}}
        .xa-rk.xa-silver{{color:#fff;background:#b0bec5;border-radius:50%;}}
        .xa-rk.xa-bronze{{color:#fff;background:#cd7f32;border-radius:50%;}}
        </style>
        <h2>🅰 アシストランキング</h2>
        <p class="xa-meta">最終更新 {_esc(d.get('lastUpdated',''))}{src_html}</p>
        <p class="xa-note">{_esc(d.get('assistNote',''))}</p>
        <div class="xa-wrap">
          <table class="xa-table">
            <thead><tr><th class="xa-rk">順</th><th>選手</th><th>チーム</th><th class="xa-as">AS</th></tr></thead>
            <tbody>
{nl.join(rows)}
            </tbody>
          </table>
        </div>
      </section>
"""


def render_scorer_compact_html(slug: str, top_n: int = 10) -> str:
    """1ページに何枚も並べる用の小さい得点ランキング（2026-09-23 新設）。

    既存の render_scorer_ranking_html() は「1ページに1つ」の前提で、
    <style> と id="scorer-ranking" と <h2> を吐く。/u16/ のように20枚並べると
    id が20回重複してしまうので、こちらを使う。

      - <style> も <h2> も id も出さない（スタイルは呼び出し側が1回だけ置く）
      - 上位 top_n 人＋同点は全員（dense rank なので rank<=N では切らない）
      - データが無ければ "" を返すので、揃っていないリーグがあってもページは壊れない

    ★色は必ずテーマ変数で書く（手順書 4-19b）。--text-primary / --text-secondary は
      **存在しない**変数で、使うとダークモードで文字が消える。
    """
    path = _DIR / f"{slug}.json"
    if not path.exists():
        return ""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    scorers = d.get("scorers", [])
    if not scorers:
        return ""

    # 上位 top_n 人＋同点は全員（出典側で既に切ってあっても、ここでも同じ規則で守る）
    cut = min(top_n, len(scorers))
    while cut < len(scorers) and scorers[cut].get("rank") == scorers[cut - 1].get("rank"):
        cut += 1

    rows = "\n".join(
        f'<tr><td class="xsc-rk">{s["rank"]}</td>'
        f'<td class="xsc-nm">{_esc(s["name"])}</td>'
        f'<td class="xsc-tm">{_esc(s.get("team", ""))}</td>'
        f'<td class="xsc-go">{s["goals"]}</td></tr>'
        for s in scorers[:cut]
    )
    src = d.get("source", "")
    src_label = d.get("sourceLabel") or "出典"
    src_html = (f'　出典：<a href="{_esc(src)}" rel="nofollow noopener" target="_blank">'
                f'{_esc(src_label)}</a>') if src else ""
    note = _esc(d.get("note", ""))

    return f"""
            <div class="xsc-box">
              <h4 class="xsc-h">⚽ 得点ランキング</h4>
              <p class="xsc-meta">最終更新 {_esc(d.get('lastUpdated', ''))}{src_html}</p>
              <div class="xsc-scroll">
              <table class="xsc-table">
                <thead><tr><th class="xsc-rk">順</th><th>選手</th><th>チーム</th><th class="xsc-go">得点</th></tr></thead>
                <tbody>
{rows}
                </tbody>
              </table>
              </div>
              <p class="xsc-note">{note}</p>
            </div>"""


if __name__ == "__main__":
    import sys
    print(render_scorer_ranking_html(sys.argv[1] if len(sys.argv) > 1 else "prince-hokkaido"))
