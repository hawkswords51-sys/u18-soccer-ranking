#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
県予選md × 出典（koko）の突き合わせ見張り
==========================================
2026-09-25 新設。データは一切さわらない（読むだけ）。常に exit 0。

なぜ作ったか
------------
埼玉の選手権予選 md に、仮の名前（合同N）の行・同じ試合の二重・別ラウンドの結果の
紛れ込みが20行あり、**サイトに表示されていたのに何も警告が出ていなかった**。
さらに update_tournament_results.py の「⚠ 要確認」（スコアが出典と不一致など）は
Actions のログに毎回出ているのに、人には届いていなかった（東京の保善×立正大立正）。

⭐️ 照合はボットの照合を**そのまま使う**
-----------------------------------------
照合を別に書き直した試作では、岐阜で略記ゆれ（「岐阜聖徳/恵那」と「岐阜聖徳学園/恵那」）を
見張りだけが別の試合と判定し、誤検出が4組出た。見張りとボットで判定が食い違うと、
見張りは狼少年になる。
→ ここでは update_md(..., dry_run=True, report=...) を呼び、ボットが
  「どの出典の試合とも対応づけなかった md の行」を報告するだけにする。
  ★このファイルに照合ロジックを書かないこと。

出すもの
--------
  出典に無い行      koko にも存在するラウンドの行で、ボットがどの試合にも対応づけなかったもの
                    （koko に無いラウンド＝県公式から先に入れた回戦は対象外）
  別ラウンド        ①の全ラウンド横断照合で、別のラウンドの行と対応づいたもの
  出典にあって md に無い  ボットが追記するはずのカード（定期実行のあとは原則0。
                    0でなければボットが「保留」した試合）
  要確認            ボットの警告（スコア不一致・片チームのみ一致・あいまい など）

行を消す・直す機能は付けない。直すのは出典と照らしてから（埼玉と同じ手順）。

使い方
------
  python scraper/audit_tournament_md.py          # 未終了の大会だけ（定期実行）
  python scraper/audit_tournament_md.py --all    # 「終了」も含める（年1回の点検用）
  python scraper/audit_tournament_md.py --verbose  # 無視指定で手直し済みの行も一覧で出す

無視指定で手直し済みの行（2026-09-25）
--------------------------------------
出典の誤記を人が直した行は、直下の <!-- 無視: koko表記 --> でボットに取り込ませていない。
ボットから見ると「どのカードとも対応しない」ので、そのままでは毎日「出典に無い行」に出てしまう。
→ 同じラウンドの無視指定とチームが共通する行は「出典に無い行」から外し、件数だけ出す。
"""
import argparse
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_tournament_results as utr  # noqa: E402
from jst import now as _jst_now          # noqa: E402


def targets(include_finished=False):
    """update_tournament_results.main() と同じ選び方"""
    out = []
    for md_path in sorted(utr.TOURNAMENT_DIR.glob("*.md")):
        fm, _ = utr.split_frontmatter(md_path.read_text(encoding="utf-8"))
        if fm is None:
            continue
        meta = utr.parse_meta(fm)
        srcs = meta.get("sources") or meta.get("source", "")
        if isinstance(srcs, str):
            srcs = [srcs] if srcs else []
        srcs = [u for u in srcs if "koko-soccer.com" in u]
        if not srcs:
            continue
        if meta.get("status") == "終了" and not include_finished:
            continue
        out.append((md_path, srcs))
    return out


def hint(md_path, round_key, line):
    """同じラウンドに、片方のチームが同じ行があれば「※」の手がかりを返す（表示だけ）"""
    parsed = utr.parse_md_line(line)
    if not parsed:
        return ""
    a, b = utr.canon(parsed[0]), utr.canon(parsed[1])
    _, body = utr.split_frontmatter(md_path.read_text(encoding="utf-8"))
    lines = body.split("\n")
    for r in utr._rescan_rounds(lines):
        if r["key"] != round_key:
            continue
        for i in r["match_idxs"]:
            if lines[i].strip() == line:
                continue
            p = utr.parse_md_line(lines[i])
            if not p:
                continue
            c, d = utr.canon(p[0]), utr.canon(p[1])
            for mine, other_mine, x, y in ((b, a, d, c), (b, a, c, d), (a, b, c, d), (a, b, d, c)):
                if mine == x and other_mine != y:
                    return f"  ※同じラウンドに「{p[1] if y == d else p[0]}」と同じ相手の行あり"
    return ""


def audit_file(md_path, urls):
    """(結果dict or None, 取得失敗?) を返す。ボットのログは飲み込む"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        koko_rounds, failures = utr.fetch_and_merge(urls)
    hard = [f for f in failures if "取得失敗" in f[1]]
    if not koko_rounds:
        return None, bool(hard)
    fm, _ = utr.split_frontmatter(md_path.read_text(encoding="utf-8"))
    pref = utr.parse_meta(fm).get("prefecture", "")
    report = {}
    with contextlib.redirect_stdout(buf):
        _, _, _, warnings = utr.update_md(
            md_path, koko_rounds, utr.build_name_map(pref), dry_run=True, report=report)
    report["warnings"] = sorted(set(warnings))
    return report, bool(hard)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="status が「終了」の大会も含める")
    ap.add_argument("--verbose", action="store_true", help="無視指定で手直し済みの行も一覧で出す")
    args = ap.parse_args()

    ts = _jst_now().strftime("%Y-%m-%d %H:%M")
    results, n_checked, n_failed = [], 0, 0
    for md_path, urls in targets(args.all):
        try:
            rep, failed = audit_file(md_path, urls)
        except Exception as e:  # 見張りは止まらない
            rep, failed = None, True
            print(f"  ℹ {md_path.name}: 点検中に例外 {type(e).__name__}: {e}")
        if failed:
            n_failed += 1
        if rep is None:
            continue
        n_checked += 1
        results.append((md_path, rep))

    n_un = sum(len(r["unconsumed"]) for _, r in results)
    n_cross = sum(len(r["cross_round"]) for _, r in results)
    n_add = sum(len(r["would_add"]) for _, r in results)
    n_warn = sum(len(r["warnings"]) for _, r in results)
    n_cov = sum(len(r.get("covered_by_ignore", [])) for _, r in results)

    print(f"=== 県予選md × 出典の突き合わせ（{ts} JST）===")
    print(f"  照合 {n_checked} ファイル／出典取得失敗 {n_failed}")
    print(f"  ⚠ 出典に無い行        {n_un}")
    print(f"  ⚠ 別ラウンドで照合     {n_cross}")
    print(f"  ⚠ 出典にあって md に無い {n_add}   ← 定期実行のあとは原則0。0でなければボットが「保留」した試合")
    print(f"  ⚠ ボットの要確認       {n_warn}   ← スコア不一致・片チームのみ一致・あいまい など")
    print(f"  ✓ 無視指定で手直し済みの行  {n_cov}   ← 表示だけ。対応不要")

    for md_path, r in results:
        cov = r.get("covered_by_ignore", []) if args.verbose else []
        if not (r["unconsumed"] or r["cross_round"] or r["would_add"] or r["warnings"] or cov):
            continue  # 何も出ないファイルは出さない（狼少年にしない）
        print()
        print(f"[{md_path.name}]")
        for rk, line in cov:
            print(f"  ✓ 無視指定で手直し済み   {rk} 「{line}」")
        for rk, line in r["unconsumed"]:
            print(f"  出典に無い行   {rk} 「{line}」{hint(md_path, rk, line)}")
        for kk, mk, line in r["cross_round"]:
            print(f"  別ラウンド     {mk} 「{line}」 → 出典では{kk}")
        for kk, line in r["would_add"]:
            print(f"  出典にあって md に無い   {kk} 「{line}」")
        for w in r["warnings"]:
            print(f"  要確認   {w.removeprefix('要確認: ')}")

    print()
    print(f"合計 ⚠ {n_un + n_cross + n_add + n_warn} 件")
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # どんな場合も job を赤にしない
        print(f"ℹ 見張りが途中で止まりました: {type(e).__name__}: {e}")
    sys.exit(0)
