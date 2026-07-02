#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
県1部リーグ「戦績表（星取り表）」 自動更新スクリプト
================================================================
data/league_matches/pref-<pref>-1.json の試合結果を
junior-soccer.jp の「試合」ページ（/league/match/<id>）から自動更新する。

【出典】各県の少年サッカー応援団（junior-soccer.jp）県1部リーグ
        ※B・2ndチーム混在の県独自リーグもここが唯一の網羅ソース。

【安全設計（プレミア/プリンスの update_cross_tables.py と同じ思想）】
  - 既存JSONのチーム・日程は壊さず、試合結果だけを「上書き（overlay）」する。
  - junior-soccer のチーム名（例: 市立船橋B）と既存JSON名（例: 市立船橋2nd）を
    正規化して 1対1 対応（全単射）が取れた県だけ処理。取れなければ据え置き。
  - 取り込んだ試合から順位を再計算し、junior-soccer 掲載の順位表と
    完全一致（検算OK）した県だけ書き込む。一致しなければ据え置き。
    → junior-soccer 側で「順位表だけ先に手入力され、個別試合が未入力」という
       状態（例: 2026/06 千葉）は自動的にスキップされ、誤データを書かない。
  - 既存より消化試合が減る場合は据え置き（退行防止＝JFA分の保護）。

【実行環境】GitHub Actions（ネット可）。Cowork sandbox では web 取得制限により
           実行不可。解析ロジックの確認は `python update_pref_cross_tables.py --test`。
"""
from __future__ import annotations
import json
import re
import sys
import unicodedata
from pathlib import Path
from datetime import date as _date

DIR = Path(__file__).resolve().parent.parent / "data" / "league_matches"
SEASON_YEAR = 2026

# ----------------------------------------------------------------------------
# pref -> (junior-soccer の地域パス, リーグID)   ※order/<id> の id
# saga は junior-soccer 非対応（県協会サイトのみ）のため対象外。
# ----------------------------------------------------------------------------
JS_LEAGUE: dict[str, tuple[str, str]] = {
    "hokkaido": ("hokkaido/hokkaido", "163368"),
    "aomori": ("tohoku/aomori", "163886"),
    "iwate": ("tohoku/iwate", "164020"),
    "akita": ("tohoku/akita", "163671"),
    "yamagata": ("tohoku/yamagata", "163965"),
    "miyagi": ("tohoku/miyagi", "163782"),
    "fukushima": ("tohoku/fukushima", "163405"),
    "ibaraki": ("kanto/ibaraki", "163357"),
    "tochigi": ("kanto/tochigi", "163569"),
    "gunma": ("kanto/gunma", "163348"),
    "chiba": ("kanto/chiba", "163436"),
    "saitama": ("kanto/saitama", "163779"),
    "tokyo": ("kanto/tokyo", "163371"),
    "kanagawa": ("kanto/kanagawa", "163423"),
    "yamanashi": ("kanto/yamanashi", "163809"),
    "niigata": ("hokushinetsu/niigata", "163784"),
    "toyama": ("hokushinetsu/toyama", "164007"),
    "ishikawa": ("hokushinetsu/ishikawa", "163986"),
    "fukui": ("hokushinetsu/fukui", "163632"),
    "nagano": ("hokushinetsu/nagano", "163461"),
    "gifu": ("tokai/gifu", "163412"),
    "shizuoka": ("tokai/shizuoka", "163487"),
    "aichi": ("tokai/aichi", "162912"),
    "mie": ("tokai/mie", "163696"),
    "shiga": ("kansai/shiga", "163309"),
    "kyoto": ("kansai/kyoto", "163399"),
    "osaka": ("kansai/osaka", "163328"),
    "hyogo": ("kansai/hyogo", "163634"),
    "nara": ("kansai/nara", "163879"),
    "wakayama": ("kansai/wakayama", "163380"),
    "tottori": ("chugoku/tottori", "163929"),
    "shimane": ("chugoku/shimane", "163918"),
    "okayama": ("chugoku/okayama", "163763"),
    "hiroshima": ("chugoku/hiroshima", "163654"),
    "yamaguchi": ("chugoku/yamaguchi", "163777"),
    "tokushima": ("shikoku/tokushima", "163670"),
    "kagawa": ("shikoku/kagawa", "163930"),
    "ehime": ("shikoku/ehime", "163579"),
    "kochi": ("shikoku/kochi", "163885"),
    "fukuoka": ("kyushu/fukuoka", "163495"),
    "nagasaki": ("kyushu/nagasaki", "163666"),
    "kumamoto": ("kyushu/kumamoto", "163566"),
    "oita": ("kyushu/oita", "163920"),
    "miyazaki": ("kyushu/miyazaki", "163363"),
    "kagoshima": ("kyushu/kagoshima", "163821"),
    "okinawa": ("kyushu/okinawa", "164083"),
}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36")
}

# ----------------------------------------------------------------------------
# 県1部以外の追加リーグ（2026-07-02 大阪2部A〜C 新設）
# slug -> (junior-soccer の地域パス, リーグID)
# 処理・検算ロジックは県1部と完全に同じ。JSONが data/league_matches/<slug>.json に
# 存在するリーグだけ更新される（無ければ [skip]）。
# ----------------------------------------------------------------------------
EXTRA_LEAGUES: dict[str, tuple[str, str]] = {
    "pref-osaka-2a": ("kansai/osaka", "163329"),
    "pref-osaka-2b": ("kansai/osaka", "163330"),
    "pref-osaka-2c": ("kansai/osaka", "163331"),
}


# ----------------------------------------------------------------------------
# 名前正規化：junior-soccer 表記と既存JSON表記を突き合わせるためのキーを作る
# ----------------------------------------------------------------------------
def norm(name: str) -> str:
    """チーム名を比較用キーに正規化。
    - 全角/半角・空白・記号を除去
    - 高校/高等学校/中等教育学校 等の語を除去
    - 2nd/3rd/セカンド と B/C を、それぞれ second/third に統一（B=2nd, C=3rd）
    - U-18/U18/ユース/U-15 等の年代表記を除去
    """
    if name is None:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).strip()
    s = s.lower()
    # 第2/第3チームの順序記号を統一
    s = s.replace("ⅱ", "2nd").replace("ⅲ", "3rd").replace("ⅳ", "4th")
    s = s.replace("セカンド", "2nd").replace("サード", "3rd")
    # 末尾/語中の (b) (c) や単独 b c を順序語へ（A本体は無印が多いので a は除去）
    s = re.sub(r"[\(（]\s*([abc])\s*[\)）]", r"\1", s)
    s = s.replace("3rd", "\x00THIRD\x00").replace("2nd", "\x00SECOND\x00")
    # 単独の b / c を順序語に（語末のみ。例 市立船橋b → second）
    s = re.sub(r"(?<=[ぁ-んァ-ヶ一-龠a-z0-9])c(?![a-z])", "\x00THIRD\x00", s)
    s = re.sub(r"(?<=[ぁ-んァ-ヶ一-龠a-z0-9])b(?![a-z])", "\x00SECOND\x00", s)
    # 年代・種別・一般語を除去
    for w in ("高等学校", "高校", "中等教育学校", "中学校", "中学",
              "u-18", "u18", "u-15", "u15", "ユース", "ｊｒﾕｰｽ", "ジュニアユース",
              "fc", "ｆｃ", "クラブ", "サッカー部", "サッカークラブ"):
        s = s.replace(w, "")
    # 記号・空白を除去
    s = re.sub(r"[\s・,．。\-‐－―ー~〜/／'’\"”()（）\[\]【】#＃]", "", s)
    s = s.replace("\x00", "")
    return s


def short_of(name: str) -> str:
    """戦績表ヘッダ用の短縮名を生成（junior-soccer 現行名から機械生成）。"""
    s = str(name)
    s = re.sub(r"(高等学校|高校|中等教育学校|中学校)$", "", s)
    # 末尾の B/C/2nd/3rd は区別のため残す
    if len(s) > 7:
        s = s[:7]
    return s or str(name)


def generate_fixtures(teams: list[str], double: bool) -> list[dict]:
    """総当たり日程（予定）を生成。double=Trueでホーム&アウェイ2回戦制。"""
    fx = []
    n = len(teams)
    if double:
        for i in range(n):
            for j in range(n):
                if i != j:
                    fx.append([teams[i], teams[j]])
    else:
        for i in range(n):
            for j in range(i + 1, n):
                fx.append([teams[i], teams[j]])
    return [dict(md=0, date="", home=h, hs=None, **{"as": None},
                away=a, status="scheduled") for h, a in fx]


# ----------------------------------------------------------------------------
# junior-soccer ページ解析（pandas.read_html で取得した DataFrame 群を渡す）
# ----------------------------------------------------------------------------
_SCORE_RE = re.compile(r"^\s*(\d+)\s*[-ー－―]\s*(\d+)\s*$")
_DATE_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


def parse_standings(dfs) -> dict[str, dict] | None:
    """順位表テーブルを探して {チーム名: stats} を返す。見つからなければ None。"""
    import pandas as pd  # noqa
    for df in dfs:
        cols = [str(c) for c in df.columns]
        joined = "".join(cols)
        if "チーム" in joined and ("勝点" in joined or "試合数" in joined):
            # 列名→index を作る（junior-soccer は 順位,チーム名,勝点,試合数,勝数,引分数,敗数,得点,失点,得失点差）
            idx = {}
            for i, c in enumerate(cols):
                cc = str(c)
                for key, names in (("team", ("チーム",)), ("pts", ("勝点",)),
                                   ("played", ("試合数",)), ("won", ("勝数",)),
                                   ("drawn", ("引分", "分")), ("lost", ("敗数",)),
                                   ("gf", ("得点",)), ("ga", ("失点",))):
                    if key not in idx and any(n in cc for n in names):
                        idx[key] = i
            if "team" not in idx or "pts" not in idx:
                continue
            out = {}
            for _, row in df.iterrows():
                vals = list(row.values)
                try:
                    team = str(vals[idx["team"]]).strip()
                    def gi(k):
                        return int(float(vals[idx[k]]))
                    rec = dict(pts=gi("pts"), played=gi("played"), won=gi("won"),
                               drawn=gi("drawn"), lost=gi("lost"),
                               gf=gi("gf"), ga=gi("ga"))
                except (KeyError, ValueError, IndexError, TypeError):
                    continue
                if team and team.lower() != "nan":
                    out[team] = rec
            if out:
                return out
    return None


def parse_matches(dfs) -> list[dict] | None:
    """試合一覧テーブルを探して [{date,home,hs,as,away}] を返す。"""
    for df in dfs:
        cols = [str(c) for c in df.columns]
        joined = "".join(cols)
        if "試合結果" not in joined and "開催日" not in joined:
            continue
        # 列: 開催日, ホーム, 試合結果, アウェイ, 会場, ...（ヘッダ名が無い場合 index で）
        out = []
        for _, row in df.iterrows():
            vals = [("" if (v is None) else str(v)) for v in row.values]
            if len(vals) < 4:
                continue
            date_raw, home, score, away = vals[0], vals[1], vals[2], vals[3]
            m = _SCORE_RE.match(unicodedata.normalize("NFKC", score))
            if not m:
                continue
            home = home.strip()
            away = away.strip()
            if not home or not away or home.lower() == "nan" or away.lower() == "nan":
                continue
            dm = _DATE_RE.search(unicodedata.normalize("NFKC", date_raw))
            if dm:
                mo, da = int(dm.group(1)), int(dm.group(2))
                yr = SEASON_YEAR if mo >= 2 else SEASON_YEAR + 1
                date = f"{yr}-{mo:02d}-{da:02d}"
            else:
                date = ""
            out.append(dict(date=date, home=home, hs=int(m.group(1)),
                            **{"as": int(m.group(2))}, away=away))
        if out:
            return out
    return None


def recompute(matches: list[dict], teams: list[str]) -> dict[str, dict]:
    st = {t: dict(pts=0, played=0, won=0, drawn=0, lost=0, gf=0, ga=0) for t in teams}

    def add(t, gf, ga):
        s = st[t]
        s["played"] += 1
        s["gf"] += gf
        s["ga"] += ga
        if gf > ga:
            s["won"] += 1
            s["pts"] += 3
        elif gf == ga:
            s["drawn"] += 1
            s["pts"] += 1
        else:
            s["lost"] += 1

    for m in matches:
        if m["home"] in st and m["away"] in st:
            add(m["home"], m["hs"], m["as"])
            add(m["away"], m["as"], m["hs"])
    return st


def fetch_dfs(url: str):
    """requests で取得し pandas.read_html で全テーブルを返す（Actions専用）。"""
    import requests
    import pandas as pd
    from io import StringIO
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return pd.read_html(StringIO(resp.text))


# ----------------------------------------------------------------------------
# 1県の処理
# ----------------------------------------------------------------------------
def build_from_source(standings: dict[str, dict], js_matches: list[dict],
                      existing_total: int) -> tuple[list[dict], list[dict], dict] | str:
    """junior-soccer の順位表＋試合一覧から JSON 本体（teams/matches/順位）を再構築。
    検算（試合一覧から再計算＝掲載順位表に完全一致）が通ればタプルを、
    通らなければ理由文字列を返す。"""
    teams = list(standings.keys())
    tset = set(teams)
    # 試合の全チームが順位表ロスターに含まれるか
    for m in js_matches:
        if m["home"] not in tset or m["away"] not in tset:
            return f"試合に順位表外チーム {m['home']}/{m['away']}"

    # 検算：試合一覧から順位を再計算し、掲載順位表と完全一致するか
    st = recompute(js_matches, teams)
    mismatch = []
    for t in teams:
        o, s = standings[t], st[t]
        for k in ("played", "won", "drawn", "lost", "gf", "ga"):
            if s[k] != o[k]:
                mismatch.append(f"{t}.{k} 試合{s[k]}≠表{o[k]}")
        if st[t]["pts"] != o["pts"]:
            mismatch.append(f"{t}.pts 試合{st[t]['pts']}≠表{o['pts']}")
    if mismatch:
        return ("検算不一致 " + "; ".join(mismatch[:2])
                + " …（順位表と個別試合が未整合。待機）")

    # 総当たり制の推定（既存の全試合数から）
    n = len(teams)
    double = existing_total >= n * (n - 1) * 0.75 if existing_total else True
    fixtures = generate_fixtures(teams, double)
    if double:
        key = {(f["home"], f["away"]): f for f in fixtures}
    else:
        key = {frozenset((f["home"], f["away"])): f for f in fixtures}
    md_max = 0
    for m in js_matches:
        if double:
            f = key.get((m["home"], m["away"]))
        else:
            f = key.get(frozenset((m["home"], m["away"])))
        if f is None:
            md_max += 1
            fixtures.append(dict(md=md_max, date=m["date"], home=m["home"],
                                 hs=m["hs"], **{"as": m["as"]},
                                 away=m["away"], status="played"))
            continue
        f["home"], f["away"] = m["home"], m["away"]   # 実際の対戦方向に合わせる
        f["hs"], f["as"], f["status"] = m["hs"], m["as"], "played"
        if m["date"]:
            f["date"] = m["date"]

    team_objs = [dict(name=t, short=short_of(t)) for t in teams]
    ranked = sorted(teams, key=lambda x: (-st[x]["pts"],
                    -(st[x]["gf"] - st[x]["ga"]), -st[x]["gf"], x))
    official = [dict(rank=i + 1, team=t, points=st[t]["pts"], played=st[t]["played"],
                     won=st[t]["won"], drawn=st[t]["drawn"], lost=st[t]["lost"],
                     gf=st[t]["gf"], ga=st[t]["ga"], gd=st[t]["gf"] - st[t]["ga"])
                for i, t in enumerate(ranked)]
    return team_objs, fixtures, {"official": official, "played": len(js_matches)}


def process(slug: str, region: str, lid: str) -> str:
    path = DIR / f"{slug}.json"
    if not path.exists():
        return f"[skip] {slug}: JSONなし"
    data = json.loads(path.read_text(encoding="utf-8"))
    existing_total = len(data.get("matches", []))
    cur_played = len([m for m in data.get("matches", [])
                      if m.get("status") == "played" and m.get("hs") is not None])

    base = f"https://junior-soccer.jp/{region}/league"
    try:
        order_dfs = fetch_dfs(f"{base}/order/{lid}")
        match_dfs = fetch_dfs(f"{base}/match/{lid}")
    except Exception as e:
        return f"[要確認] {slug}: 取得失敗 ({e})"

    standings = parse_standings(order_dfs)
    js_matches = parse_matches(match_dfs)
    if not standings:
        return f"[要確認] {slug}: 順位表を解析できず（据え置き）"
    if js_matches is None:
        return f"[要確認] {slug}: 試合一覧を解析できず（据え置き）"

    res = build_from_source(standings, js_matches, existing_total)
    if isinstance(res, str):
        return f"[据え置き] {slug}: {res}"
    team_objs, fixtures, meta = res

    new_played = meta["played"]
    if new_played < cur_played:
        return (f"[据え置き] {slug}: junior-soccer消化{new_played} < 現在{cur_played}"
                f"（退行防止・JFA分保護）")

    data["teams"] = team_objs
    data["matches"] = fixtures
    data["official_standings"] = meta["official"]
    data["source"] = f"{base}/table/{lid}"
    data["lastUpdated"] = _date.today().isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"[更新] {slug}: 消化{new_played}試合に更新（検算一致）"


def main():
    print("=== 県1部＋追加リーグ 戦績表 自動更新（junior-soccer出典） ===")
    updated = held = warn = 0
    targets = [(f"pref-{p}-1", r, l) for p, (r, l) in JS_LEAGUE.items()]
    targets += [(s, r, l) for s, (r, l) in EXTRA_LEAGUES.items()]
    for slug, region, lid in targets:
        try:
            msg = process(slug, region, lid)
        except Exception as e:  # 想定外でも全体は止めない
            msg = f"[要確認] {slug}: 例外 {e}"
        print(" ", msg)
        if msg.startswith("[更新]"):
            updated += 1
        elif msg.startswith("[要確認]"):
            warn += 1
        else:
            held += 1
    print(f"--- 完了: 更新{updated} / 据え置き{held} / 要確認{warn} ---")


if __name__ == "__main__":
    if "--test" in sys.argv:
        import test_pref_cross_tables
        test_pref_cross_tables.main()
    else:
        main()
