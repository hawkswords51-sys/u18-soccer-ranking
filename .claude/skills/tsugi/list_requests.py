#!/usr/bin/env python3
"""運営フォルダの依頼文・指示書のうち、まだ「済」印の無いものを一覧にする。

使い方:
  python3 list_requests.py              # 直近14日に作られた未処理だけ（ふだんはこれ）
  python3 list_requests.py --days 30    # 日数を変える
  python3 list_requests.py --all        # 全期間（古い未記録も含む）
  python3 list_requests.py --mark <ファイル名> 済 <コミット番号> [ひとこと]
  python3 list_requests.py --mark <ファイル名> 見送り - <理由>

印は1行目に入る:  > 済 2026-10-30 c30bb2555（Claude Code）ひとこと
                    > 見送り 2026-10-30（Claude Code）理由
--mark 以外は読むだけ。--mark も1行足すだけで、ほかの行は変えない。
"""
import datetime as dt
import pathlib
import re
import sys

FOLDER = pathlib.Path.home() / "Documents/Claude/Projects/u18-soccer.com運営"
NAME_RE = re.compile(r"(依頼|指示書)")
DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")
MARK_RE = re.compile(r"^> (済|見送り) (20\d\d-\d\d-\d\d)")


def docs():
    for p in sorted(FOLDER.glob("*.md")):
        if NAME_RE.search(p.name) and not p.name.startswith("Cowork"):  # Cowork宛ては Cowork の仕事
            m = DATE_RE.search(p.name)
            yield p, (dt.date.fromisoformat(m.group(1)) if m else None)


def mark_of(p):
    with p.open(encoding="utf-8") as f:
        first = [next(f, "") for _ in range(3)]
    for line in first:
        m = MARK_RE.match(line)
        if m:
            return line.strip()
    return None


def title_of(p):
    for line in p.open(encoding="utf-8"):
        if line.startswith("#"):
            return line.lstrip("# ").strip()[:70]
    return ""


def do_mark(args):
    name, kind, commit, *note = args
    if kind not in ("済", "見送り"):
        sys.exit("種類は「済」か「見送り」")
    p = FOLDER / name
    if not p.is_file() or not NAME_RE.search(p.name):
        sys.exit(f"見つかりません: {p}")
    if mark_of(p):
        sys.exit(f"もう印があります: {mark_of(p)}")
    today = dt.date.today().isoformat()
    ref = f" {commit}" if commit not in ("-", "") else ""
    line = f"> {kind} {today}{ref}（Claude Code）{' '.join(note)}".rstrip() + "\n\n"
    p.write_text(line + p.read_text(encoding="utf-8"), encoding="utf-8")
    print("印を付けました:", line.strip(), "→", p.name)


def main():
    a = sys.argv[1:]
    if a[:1] == ["--mark"]:
        return do_mark(a[1:])
    days = None if "--all" in a else int(a[a.index("--days") + 1]) if "--days" in a else 14
    since = None if days is None else dt.date.today() - dt.timedelta(days=days)
    todo, done, old = [], 0, 0
    for p, d in docs():
        if mark_of(p):
            done += 1
            continue
        if since and (d is None or d < since):
            old += 1
            continue
        todo.append((d, p))
    todo.sort(key=lambda x: (x[0] or dt.date.min), reverse=True)
    rng = "全期間" if since is None else f"{since}以降"
    print(f"未処理（{rng}）{len(todo)}本 ／ 済・見送りの印あり {done}本 ／ 範囲外で印なし {old}本")
    for d, p in todo:
        print(f"  {d}  {p.name}\n              └ {title_of(p)}")


if __name__ == "__main__":
    main()
