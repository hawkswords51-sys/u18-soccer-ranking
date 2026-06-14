# -*- coding: utf-8 -*-
"""
戦績表データ(data/league_matches/*.json)の自動更新スクリプト
============================================================
高校サッカードットコム(koko-soccer)の各リーグページから試合結果・順位表を取得し、
data/league_matches/<slug>.json を更新する。

安全設計（誤データ混入を防ぐ最重要ポイント）:
  1. 取得した「消化試合」から順位表を計算し直し、ページ掲載の順位表と
     全項目一致したときだけ JSON を書き換える。
  2. ページ側の消化数が、今のJSONの消化数より少ない場合は上書きしない
     （= kokoが遅れているリーグ。JFAから手で補完した北海道・東海・関西1部などを保護）。
  3. チーム名がJSONのチームと対応づかない、順位表が無い等の異常時も上書きしない。
  4. 上書きしない場合は「要確認」としてログに出すだけ（データは安全に据え置き）。
  - teams（チーム名・短縮名 short）は既存JSONの設定をそのまま保持する。

依存: pandas, lxml （GitHub Actions側で pip install）
使い方: python scraper/update_cross_tables.py
        終了コード 0=正常（更新0件でも正常）。要確認があっても0で終わる（ログで通知）。
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "league_matches"

# slug -> koko-soccer リーグページURL
KOKO_URL = {
    "premier-east": "https://koko-soccer.com/score/4359",
    "premier-west": "https://koko-soccer.com/score/4360",
    "prince-hokkaido": "https://koko-soccer.com/score/4349",
    "prince-tohoku": "https://koko-soccer.com/score/4348",
    "prince-kanto-1": "https://koko-soccer.com/score/4347",
    "prince-kanto-2": "https://koko-soccer.com/score/4346",
    "prince-hokushinetsu-1": "https://koko-soccer.com/score/4345",
    "prince-hokushinetsu-2": "https://koko-soccer.com/score/4344",
    "prince-tokai": "https://koko-soccer.com/score/4343",
    "prince-kansai-1": "https://koko-soccer.com/score/4342",
    "prince-kansai-2": "https://koko-soccer.com/score/4341",
    "prince-chugoku": "https://koko-soccer.com/score/4340",
    "prince-shikoku": "https://koko-soccer.com/score/4339",
    "prince-kyushu-1": "https://koko-soccer.com/score/4337",
    "prince-kyushu-2": "https://koko-soccer.com/score/4338",
}

UA = {"User-Agent": "Mozilla/5.0 (u18-soccer cross-table updater)"}


def norm(name: str) -> str:
    """チーム名から末尾の（県名）を除いて正規化（内部の空白は保持）"""
    if name is None:
        return ""
    s = str(name)
    s = re.sub(r"[（(][^）)]*[）)]\s*$", "", s)  # 末尾の (県) を除去
    return s.strip()


def parse_score(cell: str):
    """ '3 - 0 試合終了' -> (3,0,'played') / '-' -> (None,None,'scheduled') """
    if cell is None:
        return (None, None, "scheduled")
    m = re.search(r"(\d+)\s*[-ー－]\s*(\d+)", str(cell))
    if m:
        return (int(m.group(1)), int(m.group(2)), "played")
    return (None, None, "scheduled")


def fetch_tables(url: str):
    """ページ内の全テーブルをDataFrameのリストで返す"""
    # pandas が requests 経由で取得（GitHub Actions環境ではネットワーク可）
    return pd.read_html(url, encoding="utf-8")


def extract(url: str):
    """kokoページから (standings, matches) を抽出。失敗時は例外。
    standings: {正規化名: dict(pts,played,won,drawn,lost,gf,ga)}
    matches: [dict(md,date,home,hs,as,away,status)]  home/away は正規化名
    """
    tables = fetch_tables(url)
    standings = {}
    matches = []
    md = 0
    for df in tables:
        cols = [str(c) for c in df.columns]
        joined = " ".join(cols)
        # --- 順位表テーブル ---
        if "勝点" in joined or "順位" in joined:
            for _, row in df.iterrows():
                vals = list(row.values)
                # 列: 順位, チーム名, 勝点, 試合数, 勝数, 敗数, 引分数, 得点, 失点, 得失点差
                try:
                    team = norm(vals[1])
                    pts = int(vals[2]); played = int(vals[3])
                    won = int(vals[4]); lost = int(vals[5]); drawn = int(vals[6])
                    gf = int(vals[7]); ga = int(vals[8])
                except (ValueError, IndexError, TypeError):
                    continue
                if team:
                    standings[team] = dict(pts=pts, played=played, won=won,
                                           drawn=drawn, lost=lost, gf=gf, ga=ga)
            continue
        # --- 試合テーブル（日程/対戦カード） ---
        if "日程" in joined or "対戦" in joined:
            md += 1
            for _, row in df.iterrows():
                vals = [v for v in row.values]
                if len(vals) < 4:
                    continue
                date_raw = str(vals[0])
                home = norm(vals[1])
                hs, as_, status = parse_score(vals[2])
                away = norm(vals[3])
                if not home or not away or home == "nan" or away == "nan":
                    continue
                dm = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", date_raw)
                date = (f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
                        if dm else "")
                matches.append(dict(md=md, date=date, home=home, hs=hs,
                                    **{"as": as_}, away=away, status=status))
    return standings, matches


def recompute(matches, teams_norm):
    st = {t: dict(pts=0, played=0, won=0, drawn=0, lost=0, gf=0, ga=0) for t in teams_norm}

    def add(t, gf, ga):
        if t not in st:
            return False
        s = st[t]; s["played"] += 1; s["gf"] += gf; s["ga"] += ga
        if gf > ga: s["won"] += 1; s["pts"] += 3
        elif gf == ga: s["drawn"] += 1; s["pts"] += 1
        else: s["lost"] += 1
        return True

    ok = True
    for m in matches:
        if m["status"] != "played":
            continue
        ok &= add(m["home"], m["hs"], m["as"])
        ok &= add(m["away"], m["as"], m["hs"])
    return st, ok


def process(slug):
    path = DIR / f"{slug}.json"
    if not path.exists():
        return f"[skip] {slug}: JSONが存在しない"
    data = json.loads(path.read_text(encoding="utf-8"))
    teams = data.get("teams", [])
    # 正規化名 -> 正式名(JSON) の対応
    name_by_norm = {norm(t["name"]): t["name"] for t in teams}
    teams_norm = list(name_by_norm.keys())
    cur_played = len([m for m in data.get("matches", []) if m.get("status") == "played"])

    url = KOKO_URL.get(slug)
    if not url:
        return f"[skip] {slug}: URL未設定"
    try:
        standings, matches = extract(url)
    except Exception as e:
        return f"[要確認] {slug}: 取得/解析に失敗 ({e})"

    # チーム名が全て対応づくか
    parsed_teams = {t for m in matches for t in (m["home"], m["away"])}
    unknown = [t for t in parsed_teams if t not in name_by_norm]
    if unknown:
        return f"[要確認] {slug}: 未知のチーム名 {unknown[:3]} … 名前対応を確認（据え置き）"

    new_played = len([m for m in matches if m["status"] == "played"])
    if new_played < cur_played:
        return f"[据え置き] {slug}: koko消化{new_played} < 現在{cur_played}（kokoが遅れている。JFA分を保護）"

    # 検算: 消化試合から順位を再計算し、ページの順位表と一致するか
    if not standings:
        return f"[要確認] {slug}: ページに順位表が無く検算不可（据え置き）"
    st, mapped_ok = recompute(matches, teams_norm)
    if not mapped_ok:
        return f"[要確認] {slug}: 試合のチームが順位表と対応しない（据え置き）"
    mismatch = []
    for t in teams_norm:
        o = standings.get(t)
        if not o:
            mismatch.append(f"{t}:順位表に無い"); continue
        s = st[t]
        for k in ("played", "won", "drawn", "lost", "gf", "ga", "pts"):
            if s[k] != o[k]:
                mismatch.append(f"{t}.{k} 計算{s[k]}≠掲載{o[k]}")
    if mismatch:
        return f"[要確認] {slug}: 検算不一致 {mismatch[:3]} …（据え置き）"

    # ---- ここまで来たら安全に更新 ----
    out_matches = [dict(md=m["md"], date=m["date"],
                        home=name_by_norm[m["home"]], hs=m["hs"],
                        **{"as": m["as"]}, away=name_by_norm[m["away"]],
                        status=m["status"]) for m in matches]
    out_standings = []
    rank = 1
    for t in sorted(teams_norm, key=lambda n: (-standings[n]["pts"],
                    -(standings[n]["gf"] - standings[n]["ga"]), -standings[n]["gf"])):
        o = standings[t]
        out_standings.append(dict(rank=rank, team=name_by_norm[t], pts=o["pts"],
                                  played=o["played"], won=o["won"], drawn=o["drawn"],
                                  lost=o["lost"], gf=o["gf"], ga=o["ga"],
                                  gd=o["gf"] - o["ga"]))
        rank += 1
    data["matches"] = out_matches
    data["official_standings"] = out_standings
    from datetime import date as _d
    data["lastUpdated"] = _d.today().isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"[更新] {slug}: 消化{new_played}試合に更新（検算一致）"


def main():
    print("=== 戦績表 自動更新 ===")
    results = []
    for slug in KOKO_URL:
        msg = process(slug)
        results.append(msg)
        print(" ", msg)
    # サマリー
    updated = [r for r in results if r.startswith("[更新]")]
    review = [r for r in results if "要確認" in r]
    print(f"\n更新 {len(updated)} 件 / 要確認 {len(review)} 件")
    if review:
        print("※要確認リーグは手動チェックを推奨（データは据え置き済みで安全）:")
        for r in review:
            print("  -", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
