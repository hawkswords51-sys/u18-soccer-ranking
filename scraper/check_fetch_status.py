#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
取得元の見張り：JFA以外から入ったリーグを報告し、必要なら赤にする
==================================================================
2026-09-06 新設。data/fetch_status.json を読んで判定するだけで、
順位や戦績のデータは一切さわらない。

なぜ必要か
----------
2026-09-05〜06の1日でリーグが静かに止まる事故が4件あったが、**4件とも
GitHub Actions は緑のまま流れた**。フォールバックがあるとサイトは動き続けるので、
誰も見ていなければ何日も気づかない。そこで「気づける仕組み」を用意する。

赤（ジョブ失敗）にする条件
--------------------------
  1. **3回連続以上** JFA以外から入っているリーグがある
     出典側の一時的な遅れなら3回（＝1日半）で直るはず。直らないなら自前のバグを疑う
  2. **venueCount（会場を持つ試合数）が前回の半分未満**に落ちたリーグがある
     2026-09-06の事故#1（改名の取り残しで会場・時刻・得点者が全消失）を一発で捕まえる
  3. どの経路でも記録されなかったリーグがある（actual が空＝途中で落ちた可能性）

1〜2回のフォールバックは**緑のまま**にして `[要注意]` をログに出すだけにする。
出典側の遅れは日常的に起きるので、毎回赤にすると誰も見なくなる。

使い方
------
  python scraper/check_fetch_status.py          # 判定する（赤にしうる）
  python scraper/check_fetch_status.py --report # 報告だけ。常に終了コード0
終了コード 0=問題なし / 1=赤にすべき問題あり
"""
import argparse
import sys

import fetch_status

# 何回連続でJFA以外だったら赤にするか
FALLBACK_LIMIT = 3


def finalize(status: dict) -> dict:
    """連続回数を確定させる（jfaに戻ったら0、それ以外は前回＋1）"""
    for entry in status.get("leagues", {}).values():
        prev = int(entry.get("consecutiveFallbackPrev") or 0)
        if entry.get("actual") == entry.get("expected"):
            entry["consecutiveFallback"] = 0
        else:
            entry["consecutiveFallback"] = prev + 1
    return status


def main() -> int:
    parser = argparse.ArgumentParser(
        description="どのリーグがどの出典から入ったかを点検する")
    parser.add_argument("--report", action="store_true",
                        help="報告だけして常に成功で終わる（赤にしない）")
    args = parser.parse_args()

    status = fetch_status.load()
    leagues = status.get("leagues", {})
    if not leagues:
        print("data/fetch_status.json がまだありません。点検をスキップします。")
        return 0

    status = finalize(status)
    fetch_status.save(status)

    odd = {s: e for s, e in leagues.items() if e.get("actual") != e.get("expected")}
    print(f"=== 取得元の点検（全{len(leagues)}リーグ）===")
    if not odd:
        print("  全リーグが予定どおりの出典（JFA公式）から入っています。")

    problems = []
    if odd:
        print(f"[要注意] JFAで入るはずのリーグが{len(odd)}件、別経路になりました")
        for slug, e in sorted(odd.items()):
            actual = e.get("actual") or "記録なし"
            streak = e.get("consecutiveFallback", 0)
            print(f"  {slug:24s} {actual:5s} ({streak}回目)  {e.get('reason','')}")
            if not e.get("actual"):
                problems.append(f"{slug}: どの経路でも記録されなかった"
                                f"（途中で処理が落ちた可能性）")
            elif streak >= FALLBACK_LIMIT:
                problems.append(f"{slug}: {streak}回連続で{actual}から入っている"
                                f"（{e.get('reason','')}）")

    # 会場を持つ試合数が前回の半分未満に落ちていないか（データ消失の一発検出）
    for slug, e in sorted(leagues.items()):
        prev = int(e.get("venueCountPrev") or 0)
        now = int(e.get("venueCount") or 0)
        if prev > 0 and now * 2 < prev:
            problems.append(f"{slug}: 会場を持つ試合が {prev} → {now} に激減した"
                            f"（データが消えた疑い）")

    if problems:
        print()
        print("=" * 70)
        print("❌ 以下は自動では直りません。確認してください。")
        for p in problems:
            print(f"  - {p}")
        print("=" * 70)
        if args.report:
            return 0
        return 1

    if odd:
        print()
        print(f"※ {FALLBACK_LIMIT}回連続になるまでは緑のままにします"
              f"（出典側の一時的な遅れは日常的に起きるため）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
