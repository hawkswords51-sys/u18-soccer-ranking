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

★期限つきの既知原因（2026-09-08 追加）
--------------------------------------
出典（JFA）側が原因で、こちらでは直しようがない赤がある。
2026-09-08の prince-kyushu-1 がそれで、**JFAが直すまで毎回赤になる**。
**消せない赤は、じきに誰も見なくなる。** そこで
`data/fetch_watch_exceptions.json` に「原因は分かっている。この日まで黄色で見る」を
人が手で書けるようにした（`REGRESSION_EXEMPT` と同じ考え方）。

  - 期限内 → 🟡黄（緑のまま）。理由を毎回ログに出す
  - 期限切れ → 🔴赤。「原因が続いているか再確認してください」
  - 例外はあるが問題が消えた → ⚪️情報「もう要らないので消してください」
  - **期限の上限は2週間**（addedOn から）。それより先の日付は例外として認めない
  - **直せるものを例外に入れない。** 直せるバグを黙らせ始めた時点でこの仕組みは腐る

使い方
------
  python scraper/check_fetch_status.py          # 判定する（赤にしうる）
  python scraper/check_fetch_status.py --report # 報告だけ。常に終了コード0
終了コード 0=問題なし / 1=赤にすべき問題あり
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import fetch_status

# 何回連続でJFA以外だったら赤にするか
FALLBACK_LIMIT = 3

ROOT = Path(__file__).resolve().parent.parent
EXCEPTIONS_PATH = ROOT / "data" / "fetch_watch_exceptions.json"

# 例外を認める最長期間（addedOn からの日数）。これ以上必要なら、そのとき延長を判断する。
MAX_EXCEPTION_DAYS = 14

JST = timezone(timedelta(hours=9))


def today_jst() -> date:
    """UTCで動くGitHub Actionsでも日本時間の日付で判定する"""
    return datetime.now(JST).date()


def _parse_date(text):
    try:
        return date.fromisoformat(str(text).strip())
    except Exception:
        return None


def load_exceptions() -> dict:
    """期限つきの既知原因を読む。ファイルが無くても落ちない（空扱い）。"""
    try:
        d = json.loads(EXCEPTIONS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[要注意] {EXCEPTIONS_PATH.name} が読めません（例外なしとして続けます）: {e}")
        return {}
    return d if isinstance(d, dict) else {}


def classify_exception(entry: dict, today: date) -> tuple[str, str]:
    """例外1件の状態を返す (state, 説明)。
    state: "active"（期限内）/ "expired"（期限切れ）/ "invalid"（書き方が不正）
    """
    if not isinstance(entry, dict):
        return "invalid", "中身が辞書ではありません"
    until = _parse_date(entry.get("until"))
    added = _parse_date(entry.get("addedOn"))
    if until is None:
        return "invalid", "until が YYYY-MM-DD ではありません"
    if added is None:
        return "invalid", "addedOn が YYYY-MM-DD ではありません"
    if not str(entry.get("reason") or "").strip():
        return "invalid", "reason が空です（何を待っているのか書いてください）"
    limit = added + timedelta(days=MAX_EXCEPTION_DAYS)
    if until > limit:
        return "invalid", (f"期限が長すぎます（上限は addedOn+{MAX_EXCEPTION_DAYS}日 = "
                           f"{limit.isoformat()}）。短くしてください")
    if today > until:
        return "expired", f"{until.isoformat()} で切れています"
    return "active", f"〜{until.isoformat()}（残り{(until - today).days}日）"


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

    # 問題は (リーグ, 説明) の形で集める。あとで例外と突き合わせるため。
    problems: list[tuple[str, str]] = []
    if odd:
        print(f"[要注意] JFAで入るはずのリーグが{len(odd)}件、別経路になりました")
        for slug, e in sorted(odd.items()):
            actual = e.get("actual") or "記録なし"
            streak = e.get("consecutiveFallback", 0)
            print(f"  {slug:24s} {actual:5s} ({streak}回目)  {e.get('reason','')}")
            if not e.get("actual"):
                problems.append((slug, "どの経路でも記録されなかった"
                                       "（途中で処理が落ちた可能性）"))
            elif streak >= FALLBACK_LIMIT:
                problems.append((slug, f"{streak}回連続で{actual}から入っている"
                                       f"（{e.get('reason','')}）"))

    # 会場を持つ試合数が前回の半分未満に落ちていないか（データ消失の一発検出）
    for slug, e in sorted(leagues.items()):
        prev = int(e.get("venueCountPrev") or 0)
        now = int(e.get("venueCount") or 0)
        if prev > 0 and now * 2 < prev:
            problems.append((slug, f"会場を持つ試合が {prev} → {now} に激減した"
                                   f"（データが消えた疑い）"))

    # ---- 期限つきの既知原因と突き合わせる（2026-09-08 追加）----
    today = today_jst()
    exceptions = load_exceptions()
    states = {slug: classify_exception(entry, today)
              for slug, entry in exceptions.items()}

    known, remaining = [], []
    for slug, text in problems:
        state, note = states.get(slug, ("none", ""))
        if state == "active":
            known.append((slug, text, note, exceptions[slug].get("reason", "")))
        elif state == "expired":
            remaining.append((slug, f"[例外の期限切れ {exceptions[slug].get('until')}] "
                                    f"{text} … 原因が続いているか再確認してください"))
        elif state == "invalid":
            remaining.append((slug, f"[例外の書き方が不正: {note}] {text}"))
        else:
            remaining.append((slug, text))

    if known:
        print()
        print("🟡 既知の原因として扱っている問題（赤にはしません）")
        for slug, text, note, reason in known:
            print(f"  [既知 {note}] {slug}: {text}")
            print(f"      理由: {reason}")

    # 期限内の例外は毎回一覧で出す（黙ると存在を忘れるため）
    active = [(s, n) for s, (st, n) in states.items() if st == "active"]
    if active:
        print()
        print(f"⚪️ 期限つき例外の一覧（{EXCEPTIONS_PATH.relative_to(ROOT)}）")
        for slug, note in sorted(active):
            print(f"  {slug:24s} {note}  登録 {exceptions[slug].get('addedOn','?')}")

    # 問題が消えたのに例外だけ残っているものを知らせる
    problem_slugs = {s for s, _ in problems}
    for slug, (state, note) in sorted(states.items()):
        if state in ("active", "expired") and slug not in problem_slugs:
            print(f"⚪️ [解消済み] {slug} の例外は不要になりました。"
                  f"{EXCEPTIONS_PATH.relative_to(ROOT)} から削除してください。")

    if remaining:
        print()
        print("=" * 70)
        print("❌ 以下は自動では直りません。確認してください。")
        for slug, text in remaining:
            print(f"  - {slug}: {text}")
        print("=" * 70)
        if args.report:
            return 0
        return 1

    # 「あと何回で赤か」の注記は、まだ赤の一歩手前にいるリーグがあるときだけ出す
    # （既知の原因として黄にしたリーグしか無い日にこれを出すと、話がねじれる）
    if any(int(e.get("consecutiveFallback") or 0) < FALLBACK_LIMIT for e in odd.values()):
        print()
        print(f"※ {FALLBACK_LIMIT}回連続になるまでは緑のままにします"
              f"（出典側の一時的な遅れは日常的に起きるため）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
