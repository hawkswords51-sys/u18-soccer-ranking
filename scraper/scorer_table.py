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


if __name__ == "__main__":
    import sys
    print(render_scorer_ranking_html(sys.argv[1] if len(sys.argv) > 1 else "prince-hokkaido"))
