# -*- coding: utf-8 -*-
"""
リーグ戦績表（クロス表 / 星取り表）セクション生成モジュール
--------------------------------------------------------------
generate_league_pages.py から呼ばれ、各リーグの順位表の直下に
「戦績表（総当たり表）」＋「各チームの戦績」セクションを差し込むためのもの。

設計のポイント（重要）:
  - 試合結果は data/league_matches/<slug>.json に入れる（リーグごとに1ファイル）。
  - そのファイルが無いリーグでは空文字 "" を返す → 既存の他リーグには一切影響しない。
  - 順位(並び順)・通算成績は「消化済みの試合」から自前で計算する。
    （teams.json とは独立。試合データだけで完結する）

データファイルの形（data/league_matches/<slug>.json）:
{
  "league": "高円宮杯 JFA U-18 プレミアリーグ 2026 EAST",
  "lastUpdated": "2026-06-13",
  "source": "https://koko-soccer.com/score/4359",
  "teams": [ {"name": "流通経済大柏", "short": "流経大柏"}, ... ],   # 12チーム
  "matches": [
     {"md":1, "date":"2026-04-05", "home":"前橋育英", "hs":0, "as":2,
      "away":"流通経済大柏", "status":"played"},
     {"md":10,"date":"2026-06-20", "home":"...", "hs":null, "as":null,
      "away":"...", "status":"scheduled"},   # 未実施は hs/as を null・status="scheduled"
     ...
  ]
}
"""
import json
from pathlib import Path

# このファイル(scraper/cross_table.py)の2つ上＝リポジトリのルート。
# その下の data/league_matches/ を試合データの置き場にする。
_MATCH_DIR = Path(__file__).resolve().parent.parent / "data" / "league_matches"


def _html_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_cross_table_html(slug: str) -> str:
    """リーグ slug の戦績表セクションHTMLを返す。データが無ければ ''（空）。"""
    path = _MATCH_DIR / f"{slug}.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    teams = data.get("teams", [])
    matches = data.get("matches", [])
    if not teams or not matches:
        return ""

    names = [t["name"] for t in teams]
    short = {t["name"]: t.get("short", t["name"]) for t in teams}
    played = [m for m in matches
              if m.get("status") == "played" and m.get("hs") is not None and m.get("as") is not None]
    if not played:
        return ""

    # --- 消化試合から通算成績を集計 ---
    st = {n: dict(pts=0, pl=0, w=0, d=0, l=0, gf=0, ga=0) for n in names}

    def add(team, gf, ga):
        s = st.get(team)
        if s is None:
            return
        s["pl"] += 1
        s["gf"] += gf
        s["ga"] += ga
        if gf > ga:
            s["w"] += 1
            s["pts"] += 3
        elif gf == ga:
            s["d"] += 1
            s["pts"] += 1
        else:
            s["l"] += 1

    result = {}  # (home, away) -> (hs, as)
    for m in played:
        h, a, hs, as_ = m["home"], m["away"], m["hs"], m["as"]
        add(h, hs, as_)
        add(a, as_, hs)
        result[(h, a)] = (hs, as_)

    # 並び順 = 勝点 → 得失差 → 総得点（同点時）
    order = sorted(
        names,
        key=lambda n: (-st[n]["pts"], -(st[n]["gf"] - st[n]["ga"]), -st[n]["gf"], n),
    )

    # --- クロス表の各セル ---
    def cell(row, col):
        if row == col:
            return '<td class="xt-diag"></td>'
        items = []
        if (row, col) in result:                 # row がホームの試合
            hs, as_ = result[(row, col)]
            items.append((hs, as_, "H"))
        if (col, row) in result:                 # row がアウェイの試合
            hs, as_ = result[(col, row)]
            items.append((as_, hs, "A"))          # row 視点へ変換
        if not items:
            return '<td class="xt-np">―</td>'
        # 各段(ホーム戦/アウェイ戦)を独立して色分け
        legs = []
        for gf, ga, ha in items:
            r = "xt-win" if gf > ga else ("xt-draw" if gf == ga else "xt-lose")
            legs.append(f'<span class="xt-leg {r}"><span class="xt-ha">{ha}</span>{gf}-{ga}</span>')
        return '<td class="xt-cell"><div class="xt-cw">' + "".join(legs) + "</div></td>"

    head_cols = "".join(f'<th class="xt-vc"><span>{_html_escape(short[t])}</span></th>' for t in order)
    body_rows = []
    for i, row in enumerate(order, 1):
        tds = "".join(cell(row, col) for col in order)
        body_rows.append(
            f'<tr><th class="xt-rk">{i}</th>'
            f'<th class="xt-tn">{_html_escape(short[row])}</th>{tds}</tr>'
        )

    # --- 各チームの戦績（節順の星取り） ---
    def team_form(team):
        seq = []
        for m in sorted(played, key=lambda x: (x.get("md", 0), x.get("date", ""))):
            if m["home"] == team:
                gf, ga, opp, ha = m["hs"], m["as"], m["away"], "H"
            elif m["away"] == team:
                gf, ga, opp, ha = m["as"], m["hs"], m["home"], "A"
            else:
                continue
            r = "xt-win" if gf > ga else ("xt-draw" if gf == ga else "xt-lose")
            mark = "○" if r == "xt-win" else ("△" if r == "xt-draw" else "●")
            tip = f'第{m.get("md","")}節 {ha} {short.get(opp, opp)} {gf}-{ga}'
            seq.append((mark, r, tip))
        return seq

    form_rows = []
    for i, t in enumerate(order, 1):
        s = st[t]
        chips = "".join(
            f'<span class="xt-chip {r}" data-tip="{_html_escape(tip)}">{mk}</span>'
            for mk, r, tip in team_form(t)
        )
        form_rows.append(
            f'<tr><th class="xt-rk">{i}</th>'
            f'<th class="xt-tn2">{_html_escape(t)}</th>'
            f'<td class="xt-rec">{s["w"]}勝{s["d"]}分{s["l"]}敗</td>'
            f'<td class="xt-form">{chips}</td></tr>'
        )

    n_played = len(played)
    n_total = len([m for m in matches])
    last_updated = _html_escape(data.get("lastUpdated", ""))
    source = data.get("source", "")
    source_html = (f'　出典: <a href="{_html_escape(source)}" rel="nofollow" target="_blank">'
                   f'高校サッカードットコム</a>') if source else ""

    nl = "\n"
    return f"""
      <section class="xt-section" id="cross-table">
        <style>
        /* ===== 共通 ===== */
        .xt-section{{margin:44px 0 14px;}}
        .xt-section h2{{font-size:1.7rem;margin:0 0 6px;border-left:6px solid #1565c0;padding-left:12px;}}
        .xt-meta{{font-size:1rem;color:inherit;opacity:.75;margin:0 0 12px;}}
        .xt-note{{font-size:.95rem;color:inherit;opacity:.75;margin:4px 2px 12px;line-height:1.6;}}
        .xt-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #dfe3e8;border-radius:8px;}}
        .xt-cross{{border-collapse:separate;border-spacing:0;white-space:nowrap;background:#fff;}}
        .xt-cross th,.xt-cross td{{border-right:1px solid #dfe3e8;border-bottom:1px solid #dfe3e8;text-align:center;}}
        .xt-cross thead th{{background:#1565c0;color:#fff;font-weight:600;position:sticky;top:0;z-index:3;}}
        .xt-cross td.xt-diag{{background:#cfd8dc;}}
        .xt-cross td.xt-cell{{padding:0;height:100%;}}
        .xt-cw{{display:flex;flex-direction:column;height:100%;min-height:100%;}}
        .xt-leg{{flex:1 0 auto;display:flex;align-items:center;justify-content:center;}}
        .xt-leg.xt-win{{background:#e8f5e9;color:#2e7d32;font-weight:600;}}
        .xt-leg.xt-lose{{background:#ffebee;color:#c62828;}}
        .xt-leg.xt-draw{{background:#fff8e1;color:#f9a825;}}
        .xt-leg + .xt-leg{{border-top:1px solid #fff;}}
        .xt-cross td.xt-np{{color:#bbb;}}
        .xt-cross .xt-ha{{color:#888;margin-right:3px;font-weight:400;}}
        .xt-legend .xt-win{{background:#e8f5e9;}} .xt-legend .xt-draw{{background:#fff8e1;}} .xt-legend .xt-lose{{background:#ffebee;}}
        /* 左2列(順位・チーム)を横スクロール時に固定 */
        .xt-cross th.xt-rk,.xt-cross th.xt-corner-rk{{position:sticky;left:0;z-index:4;background:#eef2f7;color:#333;}}
        .xt-cross th.xt-tn,.xt-cross th.xt-corner-tn{{position:sticky;z-index:4;background:#eef2f7;color:#333;text-align:left;}}
        .xt-cross th.xt-corner-rk,.xt-cross th.xt-corner-tn{{background:#0d47a1;color:#fff;z-index:5;}}
        .xt-legend{{font-size:16px;color:inherit;opacity:.8;margin:12px 2px 0;}}
        .xt-legend span{{display:inline-block;padding:2px 14px;border-radius:10px;margin-right:8px;}}
        .xt-formwrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;}}
        .xt-formtable{{border-collapse:collapse;margin-top:10px;}}
        .xt-formtable th,.xt-formtable td{{border-bottom:1px solid rgba(128,128,128,.25);text-align:left;}}
        .xt-formtable .xt-rk{{color:inherit;opacity:.6;text-align:center;}}
        .xt-formtable .xt-tn2{{font-weight:600;}}
        .xt-formtable .xt-rec{{color:inherit;opacity:.85;}}
        .xt-formtable .xt-form{{white-space:nowrap;}}
        .xt-chip{{display:inline-flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;}}
        /* ===== デスクトップ(既定) ===== */
        .xt-cross th,.xt-cross td{{padding:11px 15px;font-size:17px;}}
        .xt-cross td.xt-cell{{padding:0;}} .xt-leg{{padding:11px 15px;}}
        .xt-cross th.xt-vc span{{writing-mode:vertical-rl;display:inline-block;min-height:78px;font-size:16px;}}
        .xt-cross th.xt-rk,.xt-cross th.xt-corner-rk{{width:40px;min-width:40px;}}
        .xt-cross th.xt-tn,.xt-cross th.xt-corner-tn{{left:40px;font-size:16px;min-width:98px;}}
        .xt-cross .xt-ha{{font-size:12px;}}
        .xt-formtable th,.xt-formtable td{{padding:12px 10px;font-size:17px;}}
        .xt-formtable .xt-rk{{width:34px;}}
        .xt-formtable .xt-tn2{{min-width:150px;}}
        .xt-formtable .xt-rec{{min-width:120px;}}
        .xt-chip{{width:30px;height:30px;font-size:17px;margin:2px;}}
        /* ===== スマホ(横幅600px以下)だけ小さく ===== */
        @media (max-width:600px){{
          .xt-section h2{{font-size:1.3rem;}}
          .xt-meta{{font-size:.85rem;}}
          .xt-note{{font-size:.82rem;}}
          .xt-cross th,.xt-cross td{{padding:6px 7px;font-size:13px;}}
          .xt-cross td.xt-cell{{padding:0;}} .xt-leg{{padding:6px 7px;}}
          .xt-cross th.xt-vc span{{min-height:52px;font-size:12px;}}
          .xt-cross th.xt-rk,.xt-cross th.xt-corner-rk{{width:28px;min-width:28px;}}
          .xt-cross th.xt-tn,.xt-cross th.xt-corner-tn{{left:28px;font-size:12px;min-width:64px;}}
          .xt-cross .xt-ha{{font-size:9px;}}
          .xt-legend{{font-size:13px;}}
          .xt-formtable th,.xt-formtable td{{padding:8px 6px;font-size:13px;}}
          .xt-formtable .xt-tn2{{min-width:108px;}}
          .xt-formtable .xt-rec{{min-width:78px;}}
          .xt-chip{{width:22px;height:22px;font-size:13px;margin:1px;}}
        }}
        .xt-chip.xt-win{{background:#e8f5e9;color:#2e7d32;}}
        .xt-chip.xt-lose{{background:#ffebee;color:#c62828;}}
        .xt-chip.xt-draw{{background:#fff8e1;color:#f9a825;}}
        </style>
        <h2>⚽ 戦績表（星取り表）</h2>
        <p class="xt-meta">消化 {n_played} / 全 {n_total} 試合　最終更新 {last_updated}{source_html}</p>
        <p class="xt-note">縦のチームから見た対戦結果です。色は 勝(緑)／分(黄)／敗(赤)。
        <span class="xt-ha">H</span>＝ホーム戦、<span class="xt-ha">A</span>＝アウェイ戦。
        往復2試合とも終わったマスは通算成績で色分けしています。「―」はまだ対戦していないカードです。</p>
        <div class="xt-scroll">
          <table class="xt-cross">
            <thead><tr><th class="xt-corner-rk">順</th><th class="xt-corner-tn">チーム＼相手</th>{head_cols}</tr></thead>
            <tbody>
{nl.join(body_rows)}
            </tbody>
          </table>
        </div>
        <div class="xt-legend">
          <span class="xt-win" style="color:#2e7d32">勝</span>
          <span class="xt-draw" style="color:#f9a825">分</span>
          <span class="xt-lose" style="color:#c62828">敗</span>
        </div>

        <h2 style="margin-top:26px;">各チームの戦績</h2>
        <p class="xt-note">○＝勝、△＝分、●＝敗。チップにマウスを乗せる（スマホは長押し）と相手とスコアが出ます。</p>
        <div class="xt-formwrap"><table class="xt-formtable">
          <thead><tr><th class="xt-rk">順</th><th class="xt-tn2">チーム</th><th class="xt-rec">通算</th><th>節順 →</th></tr></thead>
          <tbody>
{nl.join(form_rows)}
          </tbody>
        </table></div>
        <script>
        (function(){{
          if(window.__xtTipInit) return; window.__xtTipInit=true;
          var tip=document.createElement('div');
          tip.style.cssText='position:fixed;z-index:99999;background:#1f2937;color:#fff;'
            +'padding:7px 11px;border-radius:7px;font-size:14px;line-height:1.3;white-space:nowrap;'
            +'pointer-events:none;display:none;box-shadow:0 3px 10px rgba(0,0,0,.35);max-width:90vw;';
          document.body.appendChild(tip);
          function show(el){{
            var t=el.getAttribute('data-tip'); if(!t) return;
            tip.textContent=t; tip.style.display='block';
            var r=el.getBoundingClientRect(), tw=tip.offsetWidth, th=tip.offsetHeight;
            var x=r.left+r.width/2-tw/2;
            x=Math.max(6,Math.min(x,window.innerWidth-tw-6));
            var y=r.top-th-8; if(y<6) y=r.bottom+8;
            tip.style.left=x+'px'; tip.style.top=y+'px';
          }}
          function hide(){{ tip.style.display='none'; }}
          document.addEventListener('pointerover',function(e){{
            var c=e.target.closest && e.target.closest('.xt-chip'); if(c) show(c);
          }});
          document.addEventListener('pointerout',function(e){{
            var c=e.target.closest && e.target.closest('.xt-chip'); if(c) hide();
          }});
          document.addEventListener('click',function(e){{
            var c=e.target.closest && e.target.closest('.xt-chip');
            if(c){{ show(c); e.stopPropagation(); }} else {{ hide(); }}
          }});
          window.addEventListener('scroll',hide,true);
          window.addEventListener('resize',hide);
        }})();
        </script>
      </section>
"""


# 単体テスト用: python cross_table.py premier-east
if __name__ == "__main__":
    import sys
    slug = sys.argv[1] if len(sys.argv) > 1 else "premier-east"
    out = render_cross_table_html(slug)
    print(out if out else f"(データなし: {slug}.json が見つからないか中身が空)")
