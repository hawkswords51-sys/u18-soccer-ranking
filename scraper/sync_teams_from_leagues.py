#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
teams.json のプレミア・プリンス成績を、リーグJSONの正本から導出して同期する
==========================================================================
2026-09-07 新設。**県1部の sync_teams_from_pref.py（同日午前）と同じ処方**。

なぜ作ったか
------------
`teams.json` が「独立に計算されたもう1つの順位表」になっていた。

  リーグページ上部の順位表 … data/teams.json
  リーグページ下部の戦績表 … data/league_matches/{premier,prince}-*.json

`fetch_jfa.py` は **JFAから取れたリーグしか teams.json を書かない**。プリンス九州1部は
kokoへフォールバック中（JFA消化49 < 現在50 で退行防止が働いた）なので、
**リーグJSONは新しいのに teams.json だけ古い**という状態になっていた。
実際、同一ページ内で飯塚高校が「11pt/9試合（順位表）」と「10試合（戦績表）」に割れていた。

そこで**リーグJSONの official_standings を正本とし、取得元がJFAかkokoかに関係なく
teams.json を導出する**。

leagueRank について
-------------------
⚠️ `normalize_league_ranks.py` は leagueRank を**県ごとに区切って**計算しており、
   全国／地域リーグでは構造的に誤る（24チーム中22チームが壊れる）。
   `cleanup_aliases.py` の renumber_league_ranks() が全国単位で振り直して
   覆い隠していたが、**覆いは「県内順位を全国順位に直す」だけで正しさを保証しない**
   （teams.json 自身の勝点から再計算しており、official_standings.rank を見ていない）。
   → **leagueRank の出どころを official_standings.rank に一本化する。**

安全設計
--------
1. **退行防止はリーグ単位**。リーグJSONの消化数が teams.json 側の合計より少ないリーグは
   まるごとスキップする（出典が遅れているときに古い値で上書きしないため）。
2. 名寄せが全単射にならないリーグもまるごとスキップする。
3. チームの所属・リーグ名は触らない（update.py / fetch_jfa.py の担当のまま）。

使い方
------
  python scraper/sync_teams_from_leagues.py            # 同期する
  python scraper/sync_teams_from_leagues.py --dry-run  # 差分だけ出して書き込まない
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from update_pref_cross_tables import norm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MATCH_DIR = ROOT / "data" / "league_matches"
TEAMS_FILE = ROOT / "data" / "teams.json"

# teams.json の league 表記 → リーグJSONのファイル名
LEAGUE_SLUG = {
    "プレミアリーグEAST": "premier-east",
    "プレミアリーグWEST": "premier-west",
    "プリンスリーグ北海道": "prince-hokkaido",
    "プリンスリーグ東北": "prince-tohoku",
    "プリンスリーグ関東1部": "prince-kanto-1",
    "プリンスリーグ関東2部": "prince-kanto-2",
    "プリンスリーグ北信越1部": "prince-hokushinetsu-1",
    "プリンスリーグ北信越2部": "prince-hokushinetsu-2",
    "プリンスリーグ東海": "prince-tokai",
    "プリンスリーグ関西1部": "prince-kansai-1",
    "プリンスリーグ関西2部": "prince-kansai-2",
    "プリンスリーグ中国": "prince-chugoku",
    "プリンスリーグ四国": "prince-shikoku",
    "プリンスリーグ九州1部": "prince-kyushu-1",
    "プリンスリーグ九州2部": "prince-kyushu-2",
}

# norm() で寄らない表記だけを手で書く。推測で寄せないこと。
# キー＝リーグJSON側の表記 / 値＝teams.json 側の表記。
ALIAS = {
    "prince-kanto-1": {
        # 「流通経済大柏(B)」と「流通経済大学付属柏高校2nd」は略し方が違う
        "流通経済大柏(B)": "流通経済大学付属柏高校2nd",
        # リーグJSONは「市原・」が無い
        "ジェフユナイテッド千葉U-18": "ジェフユナイテッド市原・千葉U-18",
    },
    "prince-hokkaido": {
        "旭川実": "旭川実業高校",
    },
    "prince-kyushu-2": {
        # teams.json 側にアンダースコアが入っており norm() で寄らない
        "サガン鳥栖U-18 2nd": "サガン鳥栖U-18_2nd",
    },
}

FIELDS = (("points", "pts"), ("played", "played"), ("won", "won"),
          ("drawn", "drawn"), ("lost", "lost"),
          ("goalsFor", "gf"), ("goalsAgainst", "ga"))


def load_official(slug: str) -> list[dict]:
    path = MATCH_DIR / f"{slug}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("official_standings", [])


def collect(teams_data: dict) -> dict:
    """league 表記 → [teams.json のチーム辞書] を集める（県をまたぐ）。"""
    out = {}
    for pref_id, pref in teams_data.items():
        if not isinstance(pref, dict) or "teams" not in pref:
            continue
        for t in pref.get("teams", []):
            lg = (t.get("league") or "").strip()
            if "プレミア" in lg or "プリンス" in lg:
                out.setdefault(lg, []).append((pref_id, t))
    return out


def plan_league(lg: str, entries: list, dry: bool) -> tuple[str, list]:
    """1リーグぶん。戻り値は (ログ1行, [(pref, team, row)])"""
    slug = LEAGUE_SLUG.get(lg)
    if not slug:
        return f"[skip] {lg}: リーグJSONの対応が未登録", []
    rows = load_official(slug)
    if not rows:
        return f"[skip] {lg}: {slug}.json に順位表が無い", []

    alias = {norm(k): v for k, v in ALIAS.get(slug, {}).items()}
    by_name = {}
    for r in rows:
        n = norm(r["team"])
        by_name[norm(alias[n]) if n in alias else n] = r

    plan, unknown = [], []
    for pref_id, t in entries:
        row = None
        for cand in [t.get("name", "")] + list(t.get("aliases") or []):
            row = by_name.get(norm(cand))
            if row:
                break
        if row is None:
            unknown.append(t.get("name", ""))
            continue
        plan.append((pref_id, t, row))

    if unknown:
        return (f"[要確認] {lg}: 名寄せできないチーム {unknown[:3]}"
                f"（{len(unknown)}件・リーグまるごと据え置き）", [])
    if len(rows) != len(entries):
        return (f"[要確認] {lg}: チーム数が違う（リーグJSON {len(rows)} / "
                f"teams.json {len(entries)}・据え置き）", [])

    # 退行防止：リーグJSONの消化数が teams.json 側より少ないなら据え置く
    new_played = sum(r["played"] for r in rows)
    cur_played = sum(t.get("played") or 0 for _, t in entries)
    if new_played < cur_played:
        return (f"[skip] {lg}: リーグJSONの消化合計{new_played} < "
                f"teams.json {cur_played}（出典が遅れている。退行防止）", [])

    changed = sum(1 for _, t, r in plan
                  if any(t.get(a) != r[b] for a, b in FIELDS)
                  or t.get("leagueRank") != r["rank"])
    return (f"[{'DRY' if dry else '同期'}] {lg}: {len(plan)}チーム"
            f"（うち値が変わる {changed}）", plan)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="teams.json のプレミア・プリンス成績をリーグJSONから同期する")
    parser.add_argument("--dry-run", action="store_true",
                        help="差分だけ出して書き込まない")
    args = parser.parse_args()

    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    groups = collect(teams_data)

    print("=== teams.json のリーグ成績をリーグJSONから同期 ===")
    synced = skipped = 0
    all_plan, skips = [], []
    for lg in sorted(groups):
        msg, plan = plan_league(lg, groups[lg], args.dry_run)
        if plan:
            synced += 1
            all_plan.append((lg, plan))
            print("  " + msg)
        else:
            skipped += 1
            skips.append(msg)
    if skips:
        print("\n  --- 同期しなかったリーグ ---")
        for m in skips:
            print("  " + m)

    if args.dry_run:
        print(f"\n[DRY RUN] 同期対象 {synced} リーグ / スキップ {skipped}。書き込みなし。")
        return 0

    for lg, plan in all_plan:
        for _pref, t, r in plan:
            for a, b in FIELDS:
                t[a] = r[b]
            if "goalDiff" in t:
                t["goalDiff"] = r["gf"] - r["ga"]
            t["leagueRank"] = r["rank"]

    TEAMS_FILE.write_text(json.dumps(teams_data, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"\n✅ 完了: {synced} リーグを同期 / {skipped} リーグはスキップ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
