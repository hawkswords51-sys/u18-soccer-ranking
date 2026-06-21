#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""update_pref_cross_tables.py の解析・再構築・検算ロジックの合成テスト
（実HTTPを使わず、HTML文字列を pandas.read_html に通して検証）"""
from io import StringIO
import pandas as pd
import update_pref_cross_tables as U

STAND_HTML = """
<table>
<tr><th>順位</th><th>チーム名</th><th>勝点</th><th>試合数</th><th>勝数</th>
<th>引分数</th><th>敗数</th><th>得点</th><th>失点</th><th>得失点差</th></tr>
<tr><td>1</td><td>A高校</td><td>7</td><td>3</td><td>2</td><td>1</td><td>0</td><td>6</td><td>2</td><td>4</td></tr>
<tr><td>2</td><td>C学院</td><td>5</td><td>3</td><td>1</td><td>2</td><td>0</td><td>4</td><td>3</td><td>1</td></tr>
<tr><td>3</td><td>D実業</td><td>3</td><td>3</td><td>1</td><td>0</td><td>2</td><td>2</td><td>4</td><td>-2</td></tr>
<tr><td>4</td><td>B工業</td><td>1</td><td>3</td><td>0</td><td>1</td><td>2</td><td>2</td><td>5</td><td>-3</td></tr>
</table>"""

MATCH_HTML = """
<table>
<tr><th>開催日</th><th>ホーム</th><th>試合結果</th><th>アウェイ</th><th>会場</th></tr>
<tr><td>03/28 ( 土 )</td><td>A高校</td><td>2 - 0</td><td>B工業</td><td></td></tr>
<tr><td>03/29 ( 日 )</td><td>A高校</td><td>1 - 1</td><td>C学院</td><td></td></tr>
<tr><td>04/04 ( 土 )</td><td>A高校</td><td>3 - 1</td><td>D実業</td><td></td></tr>
<tr><td>04/05 ( 日 )</td><td>B工業</td><td>2 - 2</td><td>C学院</td><td></td></tr>
<tr><td>04/11 ( 土 )</td><td>B工業</td><td>0 - 1</td><td>D実業</td><td></td></tr>
<tr><td>04/12 ( 日 )</td><td>C学院</td><td>1 - 0</td><td>D実業</td><td></td></tr>
</table>"""

# 検算不一致版（A高校の試合数を1水増しした順位表）
STAND_BAD = STAND_HTML.replace(
    "<td>1</td><td>A高校</td><td>7</td><td>3</td>",
    "<td>1</td><td>A高校</td><td>10</td><td>4</td>")


def dfs(html):
    return pd.read_html(StringIO(html))


def main():
    ok = True

    # 1. 解析
    standings = U.parse_standings(dfs(STAND_HTML))
    matches = U.parse_matches(dfs(MATCH_HTML))
    assert standings and len(standings) == 4, standings
    assert matches and len(matches) == 6, matches
    a = standings["A高校"]
    assert (a["played"], a["won"], a["drawn"], a["gf"], a["ga"], a["pts"]) == (3, 2, 1, 6, 2, 7), a
    m0 = matches[0]
    assert (m0["home"], m0["hs"], m0["as"], m0["away"]) == ("A高校", 2, 0, "B工業"), m0
    assert m0["date"] == "2026-03-28", m0
    print("✓ 1. 順位表・試合一覧の解析 OK")

    # 2. 正常系：検算一致 → 再構築タプル
    res = U.build_from_source(standings, matches, existing_total=6)
    assert not isinstance(res, str), f"検算で誤って据え置き: {res}"
    teams, fixtures, meta = res
    assert len(teams) == 4
    assert meta["played"] == 6
    played = [f for f in fixtures if f["status"] == "played"]
    assert len(played) == 6, len(played)
    assert len(fixtures) == 6, f"単round-robinなら全6試合: {len(fixtures)}"
    # ヘッダ短縮名（高校除去）
    assert any(t["short"] == "A" for t in teams), teams
    print(f"✓ 2. 検算一致→再構築 OK（teams={len(teams)} 全{len(fixtures)} 消化{len(played)}）")

    # 3. 2回戦制の総当たり生成（existing_total=12 → double）
    res2 = U.build_from_source(standings, matches, existing_total=12)
    teams2, fixtures2, meta2 = res2
    assert len(fixtures2) == 12, f"2回戦制なら全12試合: {len(fixtures2)}"
    print(f"✓ 3. 2回戦制の全対戦生成 OK（全{len(fixtures2)}）")

    # 4. 異常系：検算不一致（順位表が試合一覧より進んでいる＝千葉現象）→ 据え置き
    bad = U.parse_standings(dfs(STAND_BAD))
    res3 = U.build_from_source(bad, matches, existing_total=6)
    assert isinstance(res3, str) and "検算不一致" in res3, res3
    print(f"✓ 4. 検算不一致は安全に据え置き OK → {res3[:40]}…")

    print("\n=== 全テスト合格 ===")
    return ok


if __name__ == "__main__":
    main()
