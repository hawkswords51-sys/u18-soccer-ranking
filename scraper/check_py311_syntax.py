#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions（Python 3.11）で通らない書き方を、手元の新しい Python（3.12 以降）で見つける（2026-10-12 新設）。

なぜ要るか：
  Actions の Python は 3.11、Mac の Python は 3.12。3.12 から f文字列の書き方がゆるくなった（PEP 701）ので、
  手元では動くのに Actions では SyntaxError で手順が落ちる、ということが起きる（2026-10-12 ce9c88c4e で実際に起きた）。

調べること（3.11 で書けない f文字列）：
  ① f文字列の式の中に、外側と同じ引用符の文字列がある   例: f"{x["a"]}"   （外側が三重引用符 f\"\"\"…\"\"\" なら中の " は可）
  ② f文字列の式の中にバックスラッシュがある             例: f"{'\\n'.join(xs)}"
  あわせて、手元の Python でファイル全体が構文として読めるかも確かめる（py_compile）。

使い方：
  python3 scraper/check_py311_syntax.py            … scraper/*.py と リポジトリ直下の *.py を全部
  python3 scraper/check_py311_syntax.py a.py b.py  … 指定したファイルだけ
  見つかれば 1 で終わる（0件なら 0）。⚠️ 手元の Python が 3.12 以上のときだけ正しく判定できる（3.11 以下なら py_compile で十分）。
"""
import glob
import io
import py_compile
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _quote(tok: str, prefix_chars: str) -> str:
    body = tok.lstrip(prefix_chars)
    return body[:3] if body[:3] in ('"""', "'''") else body[:1]


def _clash(q: str, stack: list[str]) -> bool:
    return any((len(s) == 1 and q[0] == s) or q == s for s in stack)


def check(path: str) -> list[str]:
    out = []
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        return [f"{path}: 手元の Python でも構文エラー: {e.msg}"]
    if sys.version_info < (3, 12):
        return out
    src = Path(path).read_text(encoding="utf-8")
    stack = []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        name = tokenize.tok_name[t.type]
        if name == "FSTRING_START":
            q = _quote(t.string, "rRfFbBuU")
            if stack and _clash(q, stack):
                out.append(f"{path}:{t.start[0]}: f文字列の中に同じ引用符の f文字列（3.11 では SyntaxError）")
            stack.append(q)
        elif name == "FSTRING_END":
            stack.pop()
        elif name == "STRING" and stack:
            if _clash(_quote(t.string, "rRbBuU"), stack):
                out.append(f"{path}:{t.start[0]}: f文字列の式の中に同じ引用符の文字列（3.11 では SyntaxError）")
            if "\\" in t.string:
                out.append(f"{path}:{t.start[0]}: f文字列の式の中にバックスラッシュ（3.11 では SyntaxError）")
    return out


def main() -> int:
    files = sys.argv[1:] or sorted(glob.glob(str(ROOT / "scraper" / "*.py"))) + sorted(glob.glob(str(ROOT / "*.py")))
    found = [msg for f in files for msg in check(f)]
    for msg in found:
        print(msg)
    ver = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info < (3, 12):
        print(f"（手元の Python {ver} は 3.11 以下なので、py_compile だけで判定しました）")
    print(f"{'NG' if found else 'OK'}: {len(files)}ファイル・Python 3.11 で通らない書き方 {len(found)}件（手元 Python {ver}）")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
