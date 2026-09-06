#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「どのリーグがどの出典から入ったか」を毎回記録する仕組み
========================================================
2026-09-06 新設。

なぜ作ったか
------------
2026-09-05〜06の1日で、リーグが静かにkoko予備に落ちる／止まる事故が4件起きた。
うち2件は自前のバグ（改名の取り残し・JFAの不正なJSON）だったが、**4件とも
GitHub Actions は緑のまま流れた**。フォールバックが事故を隠してしまい、人が
数字を見ていなければ何日も気づかなかった。

そこで「本来どこから入るはずか（expected）」と「実際にどこから入ったか（actual）」を
毎回 data/fetch_status.json に書き、食い違いを目立たせる。

書き出すもの（1リーグ1件）
--------------------------
  expected                そのリーグが本来どこから入るか（今は全15リーグ "jfa"）
  actual                  今回実際に使った出典 "jfa" / "koko" / "held"（据え置き）
                          空文字は「まだ決まっていない＝どの経路も記録しなかった」
  reason                  jfa以外だったときの理由（人が読める日本語）
  matchesPlayed           消化試合数
  venueCount              会場を持つ試合数。事故#1（会場が全消失）の唯一の手がかりだった
  venueCountPrev          前回の venueCount（半減の検出に使う）
  consecutiveFallback     何回連続で jfa 以外だったか（jfaに戻ったら0）
  consecutiveFallbackPrev 前回の連続回数

役割分担
--------
  このモジュール      … 記録するだけ。成否の判定はしない
  check_fetch_status.py … 連続回数を確定し、赤／緑を判定する

実行の流れ
----------
  1. fetch_jfa.py が start_run() で枠を作り、リーグごとに set_result() する
     （JFAが使えなかったリーグは actual を空のままにして理由だけ残す）
  2. update_cross_tables.py が koko で処理したリーグの actual を確定する
  3. check_fetch_status.py が連続回数を計算し、ログを出し、赤／緑を決める
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_PATH = ROOT / "data" / "fetch_status.json"

JST = timezone(timedelta(hours=9))


def load() -> dict:
    """現在の記録を読む。無ければ空の形を返す。"""
    try:
        d = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"updatedAt": "", "leagues": {}, "pref_leagues": {}}
    if not isinstance(d, dict) or not isinstance(d.get("leagues"), dict):
        return {"updatedAt": "", "leagues": {}, "pref_leagues": {}}
    if not isinstance(d.get("pref_leagues"), dict):
        d["pref_leagues"] = {}
    return d


def save(d: dict) -> None:
    d["updatedAt"] = datetime.now(JST).isoformat(timespec="seconds")
    STATUS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")


def start_run(expected: dict) -> None:
    """新しい実行を始める。前回の値を Prev として引き継いだ枠を作る。

    expected は {slug: "jfa"} の形。ここで全リーグ分の枠を作るので、
    途中で例外が出て記録されなかったリーグは actual が空のまま残り、
    「記録なし」として検出できる。
    """
    old = load().get("leagues", {})
    leagues = {}
    for slug, exp in expected.items():
        prev = old.get(slug, {})
        leagues[slug] = {
            "expected": exp,
            "actual": "",
            "reason": "",
            "matchesPlayed": 0,
            "venueCount": 0,
            "venueCountPrev": int(prev.get("venueCount") or 0),
            "consecutiveFallback": 0,
            "consecutiveFallbackPrev": int(prev.get("consecutiveFallback") or 0),
        }
    # ⚠️ pref_leagues（県1部の記録）を巻き込んで消さないこと。
    #    start_run() は fetch_jfa.py がワークフローの早い段階で呼ぶので、
    #    ここで丸ごと書き換えると県1部の last_change の履歴が毎回消える。
    d = load()
    d["leagues"] = leagues
    save(d)


def set_result(slug: str, actual: str = "", reason: str = None,
               matches_played: int = None, venue_count: int = None) -> None:
    """1リーグ分の結果を記録する。渡した項目だけを書き換える。

    actual に空文字を渡すと「まだ確定していない」の意味になる
    （JFAが使えず、この後 koko が処理する予定のリーグ）。
    連続回数はここでは計算しない（check_fetch_status.py が確定させる）。
    """
    d = load()
    entry = d.setdefault("leagues", {}).setdefault(slug, {
        "expected": "jfa", "actual": "", "reason": "",
        "matchesPlayed": 0, "venueCount": 0,
        "venueCountPrev": 0, "consecutiveFallback": 0,
        "consecutiveFallbackPrev": 0,
    })
    if actual:
        entry["actual"] = actual
    if reason is not None:
        entry["reason"] = reason
    if matches_played is not None:
        entry["matchesPlayed"] = int(matches_played)
    if venue_count is not None:
        entry["venueCount"] = int(venue_count)
    save(d)


def count_venues(matches) -> int:
    """会場を持つ試合数（記録用の共通ヘルパー）"""
    return sum(1 for m in (matches or []) if m.get("venue"))


def count_played(matches) -> int:
    """消化試合数（記録用の共通ヘルパー）"""
    return sum(1 for m in (matches or []) if m.get("status") == "played")


# ---------------------------------------------------------------------------
# 県1部（pref_leagues）— 2026-09-07 追加
# ---------------------------------------------------------------------------
# fetch_pref_official.py が「自分がその県をどう処理したか」だけを書く。
# 赤にするかどうかの判定は持ち込まない（audit_pref_freshness.py の担当）。
#
# なぜ要るか: 県1部の見張りはデータの鮮度から「止まっていること」を推定するが、
# 鮮度だけでは「出典が休みなのか、こちらの取得が壊れたのか」を区別できない。
# 取得スクリプト自身に成否を書かせれば、URL変更やサイト移転を3日で捕まえられる。
RESULTS = ("ok", "fetch_error", "parse_empty", "verify_failed", "alias_failed")


def set_pref_result(pref: str, result: str, note: str = "") -> None:
    """1県分の取得結果を記録する。result は RESULTS のいずれか。"""
    d = load()
    entry = d.setdefault("pref_leagues", {}).setdefault(pref, {})
    entry["result"] = result
    entry["result_note"] = note
    # いつ記録したか。これが古いままなら「スクリプトが走っていない」と分かる。
    entry["result_date"] = datetime.now(JST).date().isoformat()
    save(d)

