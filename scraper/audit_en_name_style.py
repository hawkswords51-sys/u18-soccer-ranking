#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
英語チームページの選手名の書き方のずれを数えて一覧にするだけのスクリプト
========================================================================
2026-09-26 新設。

**このスクリプトは1バイトも書き込みません。** 見るだけです。終了コードは常に0。

サイトの決まり:
  英語ページの選手名は「姓を大文字・名はそのまま」（例 KUBO Takefusa）。
  正しい表記の一覧は data/en/player_names_en.json の players の各 "en"。
  姓（最初の語）がすべて大文字のものだけを対象にする。

探す「崩れた形」（KUBO Takefusa の場合）:
  ① 姓だけ先頭大文字   Kubo Takefusa
  ② 名→姓の順          Takefusa Kubo
  ③ 名→大文字の姓の順  Takefusa KUBO
  大文字・小文字は区別して探す（正しい KUBO Takefusa は当たらない）。
  単語の途中で当たらないよう、前後が英数字でない所だけを拾う
  （\\b と同じ考え方。名前が "Jr." のように記号で終わっても正しく区切れる）。

対象:
  data/en/teams/*.md の全行（frontmatter の description なども含む）。
  行番号はファイル先頭（--- の行）を1行目として数える。

使い方:
  python scraper/audit_en_name_style.py
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES_JSON = ROOT / "data" / "en" / "player_names_en.json"
TEAMS_DIR = ROOT / "data" / "en" / "teams"

KINDS = {1: "①姓だけ先頭大文字", 2: "②名→姓", 3: "③名→大文字の姓"}


def cap(word):
    """KUBO → Kubo（ハイフンつきの姓は MORI-TA → Mori-Ta）"""
    return "-".join(p[:1] + p[1:].lower() for p in word.split("-"))


def build_patterns(names_json):
    data = json.loads(names_json.read_text(encoding="utf-8"))
    correct_forms = sorted({v["en"].strip() for v in data["players"].values()
                            if isinstance(v, dict) and v.get("en")})
    patterns = []   # (正規表現, 種類, 正しい形)
    for en in correct_forms:
        words = en.split()
        if len(words) < 2:
            continue
        surname, given = words[0], " ".join(words[1:])
        if not surname.isupper():
            continue
        wrong = {
            1: f"{cap(surname)} {given}",
            2: f"{given} {cap(surname)}",
            3: f"{given} {surname}",
        }
        for kind, form in wrong.items():
            if form == en:
                continue
            rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(form).replace(r"\ ", r"\s+")
                            + r"(?![A-Za-z0-9])")
            patterns.append((rx, kind, en))
    return correct_forms, patterns


def main():
    ap = argparse.ArgumentParser(description="英語ページの選手名表記のずれを点検（読むだけ）")
    ap.add_argument("--teams-dir", default=str(TEAMS_DIR), help="点検する md のフォルダ")
    ap.add_argument("--names", default=str(NAMES_JSON), help="正しい表記の一覧（JSON）")
    args = ap.parse_args()

    correct_forms, patterns = build_patterns(Path(args.names))
    md_files = sorted(Path(args.teams_dir).glob("*.md"))
    print(f"正しい表記: {len(correct_forms)} 種類 / 点検した md: {len(md_files)} 件")
    print()

    total = 0
    for md in md_files:
        lines = md.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            hits = []
            for rx, kind, en in patterns:
                for m in rx.finditer(line):
                    hits.append((m.start(), m.group(0), kind, en))
            for _, found, kind, en in sorted(hits):
                total += 1
                print(f"{md.name}:{lineno}  {KINDS[kind]}  「{found}」 → 正しくは 「{en}」")

    if total:
        print()
    print(f"ずれ {total} 件")
    return 0


if __name__ == "__main__":
    try:
        main()
    except SystemExit:                    # オプションの打ち間違い等も0で終える
        pass
    except Exception as e:                # 点検用なので何があっても0で終える
        print(f"[エラー] {e}", file=sys.stderr)
    sys.exit(0)
