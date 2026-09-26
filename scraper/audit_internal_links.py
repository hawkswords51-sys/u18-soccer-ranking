#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
サイト内リンクの「リンク切れ」を数えて一覧にするだけのスクリプト
==================================================================
2026-09-26 新設。

**このスクリプトは1バイトも書き込みません。** 見るだけです。終了コードは常に0。

やること:
  リポジトリ内の全 index.html を読み、href="/..." のサイト内リンクについて
  行き先のファイルがリポジトリに存在するかを確かめる。
    /x/y/        → x/y/index.html があればOK
    /x/y.html    → x/y.html があればOK
    /x/y         → x/y そのもの、x/y/index.html、x/y.html のどれかがあればOK
                   （GitHub Pages はこのどれでも表示できるため）
  ?や#以降は無視する。%エンコードされた日本語などは元の文字に戻して探す。

対象外:
  - 外部サイト（http:// https:// や //example.com のような書き方）
  - # だけのリンク（ページ内移動）
  - href="/..." 以外（相対パス・mailto: など）
  - HTMLのコメント <!-- ... --> の中に書かれた例文

使い方:
  python scraper/audit_internal_links.py            # 件数＋上位20件（行き先ごと）
  python scraper/audit_internal_links.py --all      # 全件を表示
  python scraper/audit_internal_links.py --top 50   # 上位50件

読み方:
  「行き先」ごとに、そのリンクを含むページ数・リンク数を多い順に並べる。
  最後の「リンク切れ N 件」の N は、リンク（href）1本ずつを数えた合計。
"""
import argparse
import collections
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent

# 読まないフォルダ（Git の中身や依存パッケージ）
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__"}

HREF_RE = re.compile(r"""href\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
# <!-- ... --> の中は説明文（例: href="/prefectures/○○/"）なので読み飛ばす
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def iter_index_files():
    for path in sorted(ROOT.rglob("index.html")):
        rel_parts = path.relative_to(ROOT).parts
        if any(p in SKIP_DIRS for p in rel_parts[:-1]):
            continue
        yield path


def normalize(href):
    """対象のサイト内リンクなら ?/# を除いたパスを返す。対象外なら None。"""
    href = href.strip()
    if not href.startswith("/") or href.startswith("//"):
        return None                       # 外部・相対・mailto: 等は対象外
    path = re.split(r"[?#]", href, maxsplit=1)[0]
    return path or None


def target_exists(path):
    rel = unquote(path).lstrip("/")
    if rel == "" or rel.endswith("/"):
        return (ROOT / rel / "index.html").is_file()
    cand = ROOT / rel
    return (cand.is_file()
            or (cand / "index.html").is_file()
            or (ROOT / (rel + ".html")).is_file())


def main():
    ap = argparse.ArgumentParser(description="サイト内リンク切れの点検（読むだけ）")
    ap.add_argument("--top", type=int, default=20, help="表示する行き先の件数（既定20）")
    ap.add_argument("--all", action="store_true", help="全件表示")
    args = ap.parse_args()

    pages = 0
    links_checked = 0
    broken_total = 0
    exists_cache = {}
    by_target = collections.defaultdict(list)   # 行き先 → [リンク元ページ,...]

    for page in iter_index_files():
        pages += 1
        try:
            html = page.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[読めない] {page.relative_to(ROOT)}: {e}")
            continue
        parent = page.relative_to(ROOT).parent.as_posix()
        src = "/" if parent == "." else f"/{parent}/"
        html = COMMENT_RE.sub("", html)
        for m in HREF_RE.finditer(html):
            path = normalize(m.group(2))
            if path is None:
                continue
            links_checked += 1
            if path not in exists_cache:
                exists_cache[path] = target_exists(path)
            if not exists_cache[path]:
                broken_total += 1
                by_target[path].append(src)

    print(f"点検したページ: {pages} 件 / サイト内リンク: {links_checked} 本")
    print(f"切れている行き先: {len(by_target)} 種類")
    print()

    ranked = sorted(by_target.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    shown = ranked if args.all else ranked[:args.top]
    if shown:
        print(f"{'リンク数':>6} {'ページ数':>6}  行き先  （リンク元の例）")
        for target, srcs in shown:
            uniq = sorted(set(srcs))
            example = uniq[0] + (f" ほか{len(uniq) - 1}" if len(uniq) > 1 else "")
            print(f"{len(srcs):>6} {len(uniq):>6}  {target}  （{example}）")
        if len(ranked) > len(shown):
            print(f"  …ほか {len(ranked) - len(shown)} 種類（--all で全件）")
        print()

    print(f"リンク切れ {broken_total} 件")
    return 0


if __name__ == "__main__":
    try:
        main()
    except SystemExit:                    # オプションの打ち間違い等も0で終える
        pass
    except Exception as e:                # 点検用なので何があっても0で終える
        print(f"[エラー] {e}", file=sys.stderr)
    sys.exit(0)
