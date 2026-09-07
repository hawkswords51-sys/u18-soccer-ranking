#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
県1部の「更新が止まったこと」を見張る
====================================
2026-09-07 新設。データは一切さわらない（読むだけ＋記録を残すだけ）。

なぜ作ったか
------------
2026-07-15に県1部の自動更新が全県で死んだのに、**7週間気づけなかった**。
ワークフローは毎朝動いて緑のままだったからで、「止まったこと」を知らせる仕組みが
無いのが原因だった。しかも2026-09-07に群馬・宮崎・山口という県協会の小さなサイトを
新しい出典として3つ増やしたので、黙って死にうる経路はむしろ増えている。

設計の芯：「データが古いこと」と「取得が壊れたこと」を分ける
-----------------------------------------------------------
      何が起きているか                 打つ手  → 扱い
  X   URL変更・サイト移転・403・パース失敗  ある  → 🔴 赤（3日連続で）
  Y   出典が結果を載せていない・リーグが休み  無い  → 🟡 黄（週次のチャット報告で拾う）

**打つ手があるものだけを赤にする。** Yを赤にすると、直せないものが毎日赤く出続けて、
赤そのものが無視されるようになる。7週間の見逃しより悪い状態になる。

⚠️ 「未消化試合の予定日が過ぎたら赤」という判定は**使えない**。当サイトのJSONは
   未消化試合に日付を持っていない（2026-09-07時点で全46県1,241件すべて `date:""`）。
   未消化の行は総当たり表の空枠で、出典のパーサが未消化行を落としているため。
   出典から予定日を取り込めば使えるようになる（公式14県のみ可能・次段の課題）。

判定
----
  🔴 赤①  公式出典の県で、取得そのものが3日以上続けて失敗している
           （fetch_pref_official.py が自分で書いた result を読む）
  🔴 赤②  全国どこの県でも試合結果が入らなくなった（＝7/15型の全県同時停止）
  🔴 赤③  teams.json を書く導出ジョブ（sync_teams_from_*）が3日以上失敗している
  🟡 黄   個別の県で消化試合数が14日以上増えていない（赤にはしない）
  ⚪️ 情報  構造がおかしい／見張りが黙る状態になっている県

使い方
------
  python scraper/audit_pref_freshness.py            # 判定する（赤にしうる）
  python scraper/audit_pref_freshness.py --report   # 報告だけ。常に終了コード0
終了コード 0=問題なし / 1=赤にすべき問題あり
"""
import argparse
import collections
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_status                                   # noqa: E402
from jst import today as jst_today                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MATCH_DIR = ROOT / "data" / "league_matches"

# ---------------------------------------------------------------------------
# しきい値
# ---------------------------------------------------------------------------
# 赤②の日数。**推測ではなく実測で決めた**（2026-09-07）。
# 2026年3〜12月の全消化試合の日付を集め、「どの県でも試合が無かった最長の空白」を
# 測ると 25日（2026-07-25〜08-18のインターハイ・お盆の中断）だった。それ＋7日。
# ⚠️ 実測に使ったデータ自身が7/15以降の取り込み停止の影響を受けているため、
#    本当の空白はこれより短い可能性がある（＝この32日は安全側に長めの見積り）。
#    出典の取り込みが正常化した年で測り直すこと。
NATIONAL_STALE_DAYS = 32

# 黄。個別の県の消化数がこれだけ増えていなければ停滞とみなす。
PREF_STALE_DAYS = 14

# 赤①。取得失敗が何日続いたら赤にするか。
# ⚠️ 「回数」ではなく「日数」で見る。ワークフローは1日2回（7:00/22:00）走るので、
#    回数で3にすると1日半で赤になってしまう。
FETCH_FAIL_DAYS = 3

# オフシーズン。この月は赤を出さない（情報としては出す）。
OFFSEASON_MONTHS = (12, 1, 2)


def current_season(today: date) -> str:
    """シーズン年。2月開幕なので1月は前年シーズン扱い（既存の年補完ルールに合わせる）。"""
    return str(today.year if today.month >= 2 else today.year - 1)


def official_prefs() -> dict:
    """fetch_pref_official.py が担当している県 → 表示名。

    担当外（junior-soccer・Mac実行）の県は赤①の対象にしない。Actionsでは走らないので
    書き込む人がおらず、対象にすると全県が「記録なし＝赤」になってしまう。
    """
    try:
        import fetch_pref_official as F
        return {p: c.get("label", "") for p, c in F.PREF_OFFICIAL.items()}
    except Exception as e:
        print(f"  ※ fetch_pref_official を読めませんでした（{e}）。赤①は判定しません。")
        return {}


# ---------------------------------------------------------------------------
# 1県分を読む
# ---------------------------------------------------------------------------
def read_pref(path: Path) -> dict:
    pref = path.name[len("pref-"):-len("-1.json")]
    d = json.loads(path.read_text(encoding="utf-8"))
    ms = d.get("matches", [])
    played = [m for m in ms if m.get("status") == "played"]
    teams = len(d.get("official_standings") or d.get("teams") or [])

    # 同じ対戦カードが2回以上出てくるか（向きは問わない）
    pairs = collections.Counter(frozenset((m.get("home"), m.get("away"))) for m in ms)
    dup = sum(1 for v in pairs.values() if v >= 2)

    return {
        "pref": pref,
        "season": str(d.get("season") or ""),
        "teams": teams,
        "played": len(played),
        "total": len(ms),
        "latest_match": max((m["date"] for m in played if m.get("date")), default=""),
        "played_without_date": sum(1 for m in played if not m.get("date")),
        "dup_pairs": dup,
        # 1回戦制の枠か（10チームなら45・8チームなら28）
        "single_round": bool(teams) and len(ms) == teams * (teams - 1) // 2,
        "complete": bool(ms) and len(played) == len(ms),
        "sourceName": d.get("sourceName") or "",
    }


def days_between(a: str, b: date) -> int | None:
    """a（YYYY-MM-DD）から b までの日数。a が空なら None。"""
    if not a:
        return None
    try:
        return (b - date.fromisoformat(a)).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 記録の更新（played が変わった日＝last_change を保つのが肝）
# ---------------------------------------------------------------------------
def update_record(rec: dict, cur: dict, today: date, is_official: bool) -> dict:
    """前回の記録 rec を、今回の実測 cur で更新して返す。"""
    out = dict(rec)
    prev_played = rec.get("played")
    out.update({
        "played": cur["played"], "total": cur["total"], "teams": cur["teams"],
        "latest_match": cur["latest_match"],
        "source": "official" if is_official else "junior-soccer (manual)",
        "sourceName": cur["sourceName"],
    })

    # last_change は played が変わったときだけ書き換える（毎日上書きしない）。
    if prev_played is None:
        # 初回は履歴が無い。最終試合日を「最後に動いた日」の代わりに置く。
        # 実際に played が動いた日はこれ以降のはずなので、停滞を過大評価しうるが、
        # 次回以降は本当の値に置き換わる。
        out["last_change"] = cur["latest_match"] or today.isoformat()
        out["last_change_note"] = "初回のため最終試合日で代用"
    elif prev_played != cur["played"]:
        out["last_change"] = today.isoformat()
        out.pop("last_change_note", None)
    else:
        out.setdefault("last_change", cur["latest_match"] or today.isoformat())

    # 赤①用。取得結果の連続日数を確定させる。
    # result は fetch_pref_official.py が書く。判定だけここで行う。
    result = rec.get("result", "")
    if not is_official or not result:
        out["result_since"] = ""
        out["result_streak"] = 0
    elif result == "ok":
        out["result_since"] = ""
        out["result_streak"] = 0
    else:
        # 失敗が始まった日。すでに失敗中なら引き継ぐ。
        out["result_since"] = rec.get("result_since") or rec.get("result_date") \
            or today.isoformat()
        out["result_streak"] = int(rec.get("result_streak") or 0) + 1
    return out


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def judge(records: dict, today: date, official: dict, jobs: dict) -> dict:
    """赤・黄・情報・正常などをまとめて返す。"""
    offseason = today.month in OFFSEASON_MONTHS
    red, yellow, info, ok = [], [], [], []
    unrecorded, done = [], []

    # --- 赤① 取得そのものが壊れている（公式県のみ） ---
    for pref in sorted(official):
        r = records.get(pref)
        if not r:
            continue
        result = r.get("result", "")
        if not result:
            unrecorded.append(pref)
            continue
        if result != "ok":
            n = days_between(r.get("result_since", ""), today)
            line = (f"{pref:12s} 取得が失敗しています: {result}"
                    f"（{r.get('result_since', '?')} から{n if n is not None else '?'}日）"
                    f" {r.get('result_note', '')[:60]}")
            if n is not None and n >= FETCH_FAIL_DAYS and not offseason:
                red.append(line)
            else:
                yellow.append(line + f"  ※{FETCH_FAIL_DAYS}日続いたら赤")
            continue
        # result は ok だが、その記録自体が古い＝スクリプトが走っていない
        n = days_between(r.get("result_date", ""), today)
        if n is not None and n >= FETCH_FAIL_DAYS and not offseason:
            red.append(f"{pref:12s} 取得結果が{n}日更新されていません"
                       f"（{r.get('result_date')} が最後。ワークフローで走っていない疑い）")

    # --- 赤③ teams.json を書く導出ジョブが失敗している（2026-09-07追加） ---
    # sync_teams_from_leagues / sync_teams_from_pref には continue-on-error: true が
    # 付いている（コミットより前のステップなので、赤くするとその日のサイト更新が
    # 丸ごと止まる）。握りつぶしたままだと、同期が失敗しても緑のまま古い teams.json で
    # ページが作られ、「県ページ・リーグページの上下が食い違う」状態が公開される。
    # → **握りつぶすが、必ず表に出す。** ここで拾って赤にする。
    #   この見張りはコミット・デプロイより後の最終ステップにいるので、
    #   赤にしてもサイトの更新は止まらない。
    for job in ("sync_teams_from_leagues", "sync_teams_from_pref"):
        e = jobs.get(job)
        if not e:
            info.append(f"{job:12s} まだ一度も記録されていません（初回実行前）")
            continue
        if e.get("result") != "ok":
            n = days_between(e.get("since", ""), today)
            line = (f"{job:12s} 失敗しています: {e.get('result')}"
                    f"（{e.get('since', '?')} から{n if n is not None else '?'}日）"
                    f" {str(e.get('note', ''))[:60]}")
            if n is not None and n >= FETCH_FAIL_DAYS and not offseason:
                red.append(line)
            else:
                yellow.append(line + f"  ※{FETCH_FAIL_DAYS}日続いたら赤")
            continue
        # ok だが記録自体が古い＝ステップが走っていない
        n = days_between(e.get("date", ""), today)
        if n is not None and n >= FETCH_FAIL_DAYS and not offseason:
            red.append(f"{job:12s} 記録が{n}日更新されていません"
                       f"（{e.get('date')} が最後。ワークフローで走っていない疑い）")

    # --- 赤② 全国同時停止 ---
    national = max((r.get("latest_match", "") for r in records.values()), default="")
    n = days_between(national, today)
    if n is not None and n >= NATIONAL_STALE_DAYS and not offseason:
        red.append(f"{'（全国）':12s} どの県でも試合結果が{n}日入っていません"
                   f"（最新 {national}／基準 {NATIONAL_STALE_DAYS}日）")

    # --- 黄 個別の県の停滞 ---
    season = current_season(today)
    for pref in sorted(records):
        r = records[pref]
        if r.get("season") and r["season"] != season:
            continue                       # 旧シーズンのファイル
        if r.get("complete"):
            done.append(pref)              # 全試合消化済み（情報行では出す）
            continue
        n = days_between(r.get("last_change", ""), today)
        if n is not None and n >= PREF_STALE_DAYS:
            yellow.append(f"{pref:12s} 消化数が{n}日変わっていません"
                          f"（{r['played']}/{r['total']}・最終試合 {r.get('latest_match') or '—'}"
                          f"・{r.get('sourceName') or '出典不明'}）")
        else:
            ok.append(pref)

    # --- ⚪️ 情報 ---
    for pref in sorted(records):
        r = records[pref]
        # (1) 1回戦制の枠のままなのに、同じ対戦が2回記録されている
        #     ＝2回戦制が始まったのに枠が増えていない。
        #     枠数そのもの（10チームなら90 or 45）で判定してはいけない。
        #     鳥取は後期がグループ分けで8チーム32枠だが、これは設計どおり。
        if r.get("single_round") and r.get("dup_pairs"):
            info.append(f"{pref:12s} 枠が1回戦制（{r['total']}）のまま、同じ対戦が"
                        f"{r['dup_pairs']}組で2回以上ある＝枠が足りていない疑い")
        # (2) 全試合消化済み＝黄の対象外。見張りが黙るので必ず目に見えるようにする。
        if r.get("complete"):
            info.append(f"{pref:12s} 全試合消化済み（{r['played']}/{r['total']}・"
                        f"最終 {r.get('latest_match') or '—'}）として見張りの対象外です"
                        f"{'／枠が1回戦制なので、2回戦制に入っていないか要確認' if r.get('single_round') else ''}")
        # (3) 消化済みなのに日付が無い試合がある（出典が試合日を公開していない県）
        if r.get("played_without_date"):
            info.append(f"{pref:12s} 消化済みなのに試合日が無い試合が"
                        f"{r['played_without_date']}件（出典が試合日を公開していない）")

    return {"red": red, "yellow": yellow, "info": info, "ok": ok,
            "unrecorded": unrecorded, "done": done}


def main() -> int:
    parser = argparse.ArgumentParser(description="県1部の更新が止まっていないか点検する")
    parser.add_argument("--report", action="store_true",
                        help="報告だけして常に成功で終わる（赤にしない）")
    parser.add_argument("--no-save", action="store_true",
                        help="data/fetch_status.json に書き込まない")
    args = parser.parse_args()

    today = jst_today()
    official = official_prefs()

    paths = sorted(MATCH_DIR.glob("pref-*-1.json"))
    if not paths:
        print("data/league_matches/pref-*-1.json が見つかりません。点検をスキップします。")
        return 0

    status = fetch_status.load()
    prev = status.get("pref_leagues", {})
    records = {}
    for p in paths:
        cur = read_pref(p)
        pref = cur["pref"]
        rec = dict(prev.get(pref, {}))
        rec.update({"season": cur["season"], "complete": cur["complete"],
                    "single_round": cur["single_round"], "dup_pairs": cur["dup_pairs"],
                    "played_without_date": cur["played_without_date"]})
        records[pref] = update_record(rec, cur, today, pref in official)

    j = judge(records, today, official, status.get("jobs", {}))
    red, yellow, info, ok = j["red"], j["yellow"], j["info"], j["ok"]

    national = max((r.get("latest_match", "") for r in records.values()), default="")
    print(f"=== 県1部 鮮度チェック（{today.isoformat()} JST）===")
    print(f"  対象 {len(records)}県 ／ 全国基準日（どこかの県で試合があった最新日）{national}")
    if today.month in OFFSEASON_MONTHS:
        print(f"  ※ {today.month}月はオフシーズンのため赤にしません（情報としては出します）")
    print()
    print(f"🔴 要対応 {len(red)}件")
    for line in red:
        print("   " + line)
    print(f"🟡 情報（打つ手が無いもの・赤にしない） {len(yellow)}件")
    for line in yellow:
        print("   " + line)
    print(f"⚪️ 構造の確認 {len(info)}件")
    for line in info:
        print("   " + line)
    if j["unrecorded"]:
        print(f"   ※ 取得結果がまだ記録されていない公式県 {len(j['unrecorded'])}件"
              f"（fetch_pref_official.py の初回実行前）: {', '.join(j['unrecorded'])}")
    print(f"✅ 正常 {len(ok)}県"
          f"（ほかに全試合消化済みで対象外 {len(j['done'])}県: "
          f"{', '.join(j['done']) if j['done'] else 'なし'}）")

    if not args.no_save:
        for pref, r in records.items():
            r["status"] = ("alert" if any(pref in line for line in red)
                           else "warn" if any(pref in line for line in yellow) else "ok")
        status["pref_leagues"] = dict(sorted(records.items()))
        status["pref_leagues"]["_meta"] = {
            "checked": today.isoformat(),
            "national_latest": national,
            "nationalStaleDays": NATIONAL_STALE_DAYS,
            "prefStaleDays": PREF_STALE_DAYS,
            "fetchFailDays": FETCH_FAIL_DAYS,
        }
        fetch_status.save(status)

    if red:
        print()
        print("=" * 70)
        print("❌ 取得が壊れている可能性があります。確認してください。")
        print("   （出典が休みなだけの県は🟡にとどめてあります）")
        print("=" * 70)
        return 0 if args.report else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
