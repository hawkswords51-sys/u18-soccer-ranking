#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
teams.json の県1部の成績を、県1部の戦績表JSONから導出して同期する
====================================================================
2026-09-07 新設。

なぜ作ったか
------------
県ページは**上下で読んでいるデータが違った**。

  上部（所属チーム順位表・AI要約一文） … data/teams.json
  下部（戦績表・直近の試合結果）        … data/league_matches/pref-{県}-1.json

teams.json は `update.py` が junior-soccer から独立に取っていたが、junior-soccer は
2026-07-15以降 GitHub Actions から403で取れない。その結果 **46県中32県・124チームが
7月の値で凍結**し、同じページの上と下で数字が食い違っていた（2026-09-07に計測）。

公式データ源へ移行した県は下部だけが新しくなるので、放置すると食い違いは広がる一方だった。
そこで**県1部の順位の出どころを `pref-{県}-1.json` 1か所に固定する**。
移行していない県も、少なくとも上下が同じ鮮度になる（古いなら両方古い＝自己矛盾しない）。

なお `update.py` 側は「県1部の成績数値を書く処理」だけを止めてある。
**チームの所属とリーグ名の管理は従来どおり** update.py が担当する
（新しいチームの発見やリーグ移動の追従を止めないため）。

安全設計
--------
1. **退行防止は県単位**。1チームでも試合数が減る県は、その県まるごとスキップする。
   一部だけ同期すると上部の表の中で新旧が混ざり、かえって分かりにくくなるため。
2. 名寄せできないチームが1つでもある県もスキップする。
3. プレミア・プリンス所属の行には触らない（`fetch_jfa.py` の担当）。
4. スキップした県は理由をログに出す。

⚠️ 15県が「各チーム1試合ずつ減る」形でスキップされる（2026-09-07時点）。これは
   手順書4-2にある junior-soccer の既知の性質で、**同じ出典の別時点**を見ているため。
   junior-soccer は「順位表だけ先に手入力・個別試合は未入力」の県があり、
   teams.json（順位表ページ由来）が pref JSON（個別試合から再計算・検算ゲートあり）より
   1節ぶん先行することがある。**新しいが未検算 vs 古いが検算済み**なので、
   検算済みを守る＝スキップする判断にしている。

使い方
------
  python scraper/sync_teams_from_pref.py            # 同期する
  python scraper/sync_teams_from_pref.py --dry-run  # 差分だけ出して書き込まない
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_status  # noqa: E402
from update_pref_cross_tables import norm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MATCH_DIR = ROOT / "data" / "league_matches"
TEAMS_FILE = ROOT / "data" / "teams.json"

# ----------------------------------------------------------------------------
# 退行防止の例外
# ----------------------------------------------------------------------------
# 岡山だけは「試合数が減る」ことを許可する。teams.json 側の値が junior-soccer 由来の
# **破損値**だからで、退行ではなく修正にあたる。
#   実例（2026-09-07 サイトに公開されていた）:
#     倉敷高校 岡山県1部 4位 勝点20 26試合 1勝17分8敗 得点4 失点31
#   10チームリーグで26試合は物理的にあり得ず、17分け・得点4も異常。
#   pref-okayama-1.json は10チーム全部が9試合で内部整合が取れており検算も通っている。
# ⚠️ 例外はこの1県だけにすること。他県は必ずガードを通す。
# ※ 同期後も創志学園は19ptのまま（4/12のスコア反転が pref JSON 側に残っているため）。
#   岡山を県協会公式へ移すときに直す。
REGRESSION_EXEMPT = {"okayama"}


def is_pref_league(league: str | None) -> bool:
    """県内リーグか（プレミア・プリンス以外）。

    リーグ名は県によってばらばら（「群馬U-18リーグ」「宮崎県JFAリーグ1部」等）なので、
    **「1部」という文字列では判定しない**。
    ⚠️ 「1部」で絞ると「プリンスリーグ九州1部」を県1部と誤認する（2026-09-07に実際に踏んだ）。
    """
    lg = league or ""
    return bool(lg) and "プレミア" not in lg and "プリンス" not in lg


def resolve(team: dict, official: dict):
    """teams.json のチームを、戦績表JSONの順位表の行に対応づける。
    name と aliases の両方を見る（aliases を見ないと1チームだけ順位が止まる事故になる）。
    """
    for cand in [team.get("name", "")] + list(team.get("aliases") or []):
        row = official.get(norm(cand))
        if row:
            return row
    return None


def process(pref: str, teams_data: dict, dry_run: bool) -> tuple[str, list]:
    """1県ぶん。戻り値は (ログ1行, 反映予定の [(team, row)])"""
    path = MATCH_DIR / f"pref-{pref}-1.json"
    if not path.exists():
        return f"[skip] {pref}: 戦績表JSONが無い", []
    lm = json.loads(path.read_text(encoding="utf-8"))
    official = {}
    for row in lm.get("official_standings", []):
        official.setdefault(norm(row["team"]), row)
    if not official:
        return f"[skip] {pref}: 順位表が空", []

    targets = [t for t in teams_data.get(pref, {}).get("teams", [])
               if is_pref_league(t.get("league"))]
    if not targets:
        return f"[skip] {pref}: teams.json に県1部のチームが無い", []

    plan, unknown, regress = [], [], []
    for t in targets:
        row = resolve(t, official)
        if not row:
            unknown.append(t.get("name", ""))
            continue
        if (row["played"] < (t.get("played") or 0)
                and pref not in REGRESSION_EXEMPT):
            regress.append(f"{t['name']} {t.get('played')}→{row['played']}試合")
        plan.append((t, row))

    if unknown:
        return (f"[skip] {pref}: 名寄せできないチーム {unknown[:3]}"
                f"（{len(unknown)}件）", [])
    if regress:
        return (f"[skip] {pref}: 試合数が減るチームがある {regress[:3]}"
                f"（{len(regress)}件・退行防止で県まるごと据え置き）", [])

    changed = sum(1 for t, r in plan
                  if (t.get("points"), t.get("played")) != (r["points"], r["played"]))
    note = "（★破損値の修正・退行防止の例外）" if pref in REGRESSION_EXEMPT else ""
    return (f"[{'DRY' if dry_run else '同期'}] {pref}: {len(plan)}チーム"
            f"（うち値が変わる {changed}）{note}", plan)


def _run_and_record(fn, job: str) -> int:
    """本体を走らせ、成否を fetch_status.json に記録する。

    ⚠️ ワークフローではこのステップに continue-on-error: true が付いている。
       **外してはいけない**（コミットより前なので、赤くするとその日のサイト更新が
       丸ごと止まる）。代わりにここで成否を記録し、コミット・デプロイより後にいる
       audit_pref_freshness.py が赤にする。**握りつぶすが、必ず表に出す。**
    """
    try:
        rc = fn()
    except Exception as e:
        fetch_status.set_job_result(job, type(e).__name__, str(e))
        raise
    fetch_status.set_job_result(job, "ok" if rc == 0 else "nonzero_exit",
                                "" if rc == 0 else f"終了コード {rc}")
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="teams.json の県1部成績を戦績表JSONから導出して同期する")
    parser.add_argument("--dry-run", action="store_true",
                        help="差分だけ出して書き込まない")
    args = parser.parse_args()

    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    prefs = sorted(p for p in teams_data if p != "_meta")

    print("=== teams.json の県1部成績を戦績表JSONから同期 ===")
    synced = skipped = 0
    all_plan = []
    skip_msgs = []
    for pref in prefs:
        msg, plan = process(pref, teams_data, args.dry_run)
        if plan:
            synced += 1
            all_plan.append((pref, plan))
            print("  " + msg)
        else:
            skipped += 1
            skip_msgs.append(msg)

    if skip_msgs:
        print("\n  --- 同期しなかった県 ---")
        for m in skip_msgs:
            print("  " + m)

    if args.dry_run:
        print(f"\n[DRY RUN] 同期対象 {synced} 県 / スキップ {skipped} 県。書き込みなし。")
        return 0

    for pref, plan in all_plan:
        for t, row in plan:
            t["points"] = row["points"]
            t["played"] = row["played"]
            t["won"] = row["won"]
            t["drawn"] = row["drawn"]
            t["lost"] = row["lost"]
            t["goalsFor"] = row["gf"]
            t["goalsAgainst"] = row["ga"]
            if "goalDiff" in t:
                t["goalDiff"] = row["gf"] - row["ga"]
            t["leagueRank"] = row["rank"]

    teams_data["_meta"] = {
        **teams_data.get("_meta", {}),
        "lastUpdated": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
    }
    TEAMS_FILE.write_text(json.dumps(teams_data, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"\n✅ 完了: {synced} 県を同期 / {skipped} 県はスキップ")
    return 0


if __name__ == "__main__":
    # --dry-run は書き込まないので記録もしない（本番の成否だけを見張りに渡す）
    if "--dry-run" in sys.argv:
        sys.exit(main())
    sys.exit(_run_and_record(main, "sync_teams_from_pref"))
