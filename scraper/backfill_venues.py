#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
フォールバック中のリーグに、JFA公式から「会場」だけを補う
==========================================================
2026-09-08 新設。

なぜ必要か
----------
JFAが使えずkoko予備に落ちたリーグは、**全試合の会場が空になる**。
kokoは会場を持っていないため、サイトの表示が「11:00 キックオフ」だけになり、
どこでやるのかが読者に出ない（2026-09-08のプリンス九州1部が実例）。
フォールバック自体は今後も起きるので、**九州1部固有の対処ではなく一般の仕組み**にする。

★この仕組みの原則：**空欄を埋めるだけ。すでに値があるものは上書きしない。**
----------------------------------------------------------------------------
会場だけを補い、**キックオフ時刻には触らない**。
理由：同じ試合でJFAとkokoの時刻が食い違うことがあり（2026-09-08の実測で九州1部に2件。
9/5 FC琉球U-18 vs 飯塚 が koko 11:00 ↔ JFA 16:00、国見 vs 東福岡 が koko 10:30 ↔ JFA 16:00）、
**どちらが正しいか判定する材料が無い**。判定できないものは触らないのが安全。
会場は「空 vs 値あり」なので判定の必要がなく、間違えようがない。

  - スコア・時刻・節番号・日付には**一切触らない**
  - `venue` に既に値がある試合には触らない
  - チーム名の名寄せは fetch_jfa の既存エイリアスをそのまま使う
    （名寄せできない試合はスキップして件数だけ出す。書き間違えるより出さない方を選ぶ）

実行の位置
----------
**update_cross_tables.py（koko取得）より後**に走らせること。
先に走らせるとkoko側の書き込みで会場が消える。

使い方
------
  python scraper/backfill_venues.py            # 補完する
  python scraper/backfill_venues.py --dry-run  # 何件補完されるかだけ見る
終了コード: 常に0（失敗してもサイト更新を止めない。件数はログに出す）
"""
import argparse
import json
import sys

import fetch_jfa
import fetch_status


def _load_site(slug: str):
    path = fetch_jfa.MATCH_DIR / f"{slug}.json"
    if not path.exists():
        return None, None
    return json.loads(path.read_text(encoding="utf-8")), path


def _fallback_slugs() -> list[str]:
    """出典がJFA以外になったリーグのslug一覧（記録が無ければ空）"""
    leagues = fetch_status.load().get("leagues", {})
    out = []
    for slug, e in leagues.items():
        # actual が空（＝どの経路も確定しなかった）ときも、会場だけは補ってよい
        if e.get("actual") != e.get("expected", "jfa"):
            out.append(slug)
    return out


def backfill_league(cfg: dict, dry_run: bool = False) -> tuple[int, int]:
    """1リーグ分の会場を補う。戻り値 (補完した件数, 名寄せできず飛ばした件数)"""
    slug = cfg["slug"]
    site, path = _load_site(slug)
    if not site:
        print(f"  [skip] {slug}: data/league_matches/{slug}.json が無い")
        return 0, 0

    u = fetch_jfa.urls_of(cfg)
    try:
        raw = (fetch_jfa.read_tohoku_html(u) if cfg["fmt"] == "html"
               else fetch_jfa.read_json_source(u))
    except Exception as e:
        print(f"  [skip] {slug}: JFA公式データを取得できない ({e})")
        return 0, 0

    site_names = [t.get("name", "") for t in site.get("teams", []) if t.get("name")]
    if not site_names:
        print(f"  [skip] {slug}: 既存JSONに teams が無い")
        return 0, 0
    resolve = fetch_jfa._build_resolver(site_names, slug)

    # JFA側を (日付, ホーム, アウェイ) で引けるようにする。名寄せできない試合は入れない。
    jfa_by_key, jfa_by_pair, unresolved = {}, {}, 0
    for m in raw["matches"]:
        home, away = resolve(m.get("home", "")), resolve(m.get("away", ""))
        if not home or not away:
            unresolved += 1
            continue
        if m.get("date"):
            jfa_by_key.setdefault((m["date"], home, away), m)
        jfa_by_pair.setdefault((home, away), []).append(m)

    # 出典どうしで日付が食い違っている試合のための予備の突き合わせ。
    # 二重総当たりのリーグでは「ホームAとアウェイB」の組み合わせは**シーズンに1回だけ**なので、
    # 両側で1件ずつに絞れるときに限り、日付が違っても同じ試合とみなしてよい。
    # （2026-09-08の九州1部で、koko 7/11 ↔ JFA 6/27 のように日付だけずれた試合が2件あった）
    site_pair_count = {}
    for m in site.get("matches", []):
        k = (m.get("home"), m.get("away"))
        site_pair_count[k] = site_pair_count.get(k, 0) + 1

    filled, by_pair, skipped = 0, 0, 0
    for m in site.get("matches", []):
        if m.get("venue"):
            continue                       # ★すでに値があるものは触らない
        hit = jfa_by_key.get((m.get("date"), m.get("home"), m.get("away")))
        matched_by_pair = False
        if hit is None:
            pair = (m.get("home"), m.get("away"))
            cands = jfa_by_pair.get(pair) or []
            if len(cands) == 1 and site_pair_count.get(pair) == 1:
                hit = cands[0]
                matched_by_pair = True
        if hit is None:
            skipped += 1
            continue
        venue = str(hit.get("venue") or "").strip()
        if not venue:
            continue                       # JFA側も「未定」。無いものは書かない
        m["venue"] = venue                 # ★会場だけ。時刻・スコアには触らない
        filled += 1
        if matched_by_pair:
            by_pair += 1
            print(f"    [日付ずれ] {slug}: {m.get('date')} {m.get('home')} vs "
                  f"{m.get('away')} は出典どうしで日付が違うため組み合わせで突き合わせた"
                  f"（JFA側は {hit.get('date')}）")

    if filled and not dry_run:
        path.write_text(json.dumps(site, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  venue補完: {slug} {filled}件"
          + (f"（うち日付ずれを組み合わせで突き合わせ: {by_pair}件）" if by_pair else "")
          + (f"（対応する試合が見つからず飛ばした: {skipped}件）" if skipped else "")
          + (f"（JFA側で名寄せできず: {unresolved}件）" if unresolved else "")
          + ("  ※dry-run のため書き込んでいません" if dry_run and filled else ""))
    return filled, skipped


def main() -> int:
    ap = argparse.ArgumentParser(
        description="フォールバック中のリーグにJFAの会場だけを補う")
    ap.add_argument("--dry-run", action="store_true", help="書き込まずに件数だけ出す")
    ap.add_argument("--only", default="", help="対象リーグをカンマ区切りで指定")
    args = ap.parse_args()

    targets = set(args.only.split(",")) if args.only else set(_fallback_slugs())
    print("=== 会場の補完（JFA以外から入ったリーグだけ）===")
    if not targets:
        print("  フォールバック中のリーグはありません。何もしません。")
        return 0

    total = 0
    for cfg in fetch_jfa.LEAGUES:
        if cfg["slug"] not in targets:
            continue
        filled, _ = backfill_league(cfg, dry_run=args.dry_run)
        total += filled
    print(f"合計 {total} 件の会場を補いました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
