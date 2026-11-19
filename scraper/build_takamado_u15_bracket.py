#!/usr/bin/env python3
"""高円宮杯U-15選手権2026ページのトーナメント表(SVG)を作り直す。

データ：data/u15/takamado-u15-2026-bracket.md（組み合わせ・地域の代表順・各回戦の結果）
書き換え先：tournaments/takamado-u15-2026/index.html の
    <!-- TAKAMADO_BRACKET:START --> 〜 <!-- TAKAMADO_BRACKET:END --> の間だけ。
描画はインターハイ版の render_bracket_svg をそのまま使う（勝ち上がり赤線・勝ち残り赤枠つき）。
sitemap など他のファイルには一切触らない。

使い方：python3 scraper/build_takamado_u15_bracket.py [--check]
  --check … ページを書き換えず、組み合わせとデータの検算だけ行う
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scraper"))
import generate_interhigh_page as ih  # noqa: E402

DATA = os.path.join(ROOT, "data", "u15", "takamado-u15-2026-bracket.md")
PAGE = os.path.join(ROOT, "tournaments", "takamado-u15-2026", "index.html")
START, END = "<!-- TAKAMADO_BRACKET:START -->", "<!-- TAKAMADO_BRACKET:END -->"


def read_sections(path):
    sections, cur = {}, None
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            m = re.match(r"^##\s+(.+?)\s*$", ln)
            if m:
                cur = m.group(1)
                sections[cur] = []
            elif cur:
                sections[cur].append(ln)
    return sections


def check(sections):
    pairs = ih.parse_bracket_pairs(sections["トーナメント表"])
    teams = [t for p in pairs for t in p if t]
    reps = ih.parse_pref_map(sections["地域の代表順"])
    errs = []
    if len(pairs) != 16 or len(teams) != 32 or len(set(teams)) != 32:
        errs.append(f"組み合わせが16試合・32チームになっていません（{len(pairs)}試合・{len(set(teams))}チーム）")
    for t in teams:
        if ih._norm_team(t) not in reps:
            errs.append(f"地域の代表順に無いチーム：{t}")
    if len(reps) != 32:
        errs.append(f"地域の代表順が32チームではありません（{len(reps)}）")
    names = {ih._norm_team(t) for t in teams}
    for sec, lines in sections.items():
        if sec in ("トーナメント表", "地域の代表順"):
            continue
        for key, (a, ga, gb, pk, b) in ih.collect_results({sec: lines}).items():
            for t in (a, b):
                if ih._norm_team(t) not in names:
                    errs.append(f"{sec}の結果に組み合わせに無いチーム名：{t}（書き方を組み合わせと揃えてください）")
            if ga == gb and not pk:
                errs.append(f"{sec}：{a} {ga}-{gb} {b} は引き分けでPK戦の記載がありません")
    return errs


def build(sections):
    loc = {
        "label": lambda n: n,
        "pref": lambda p: p,
        "pref_wrap": ("［", "］"),
        "link": lambda n: "",
        "round_names": lambda k: ["1回戦", "2回戦", "準々決勝", "準決勝", "決勝"][-k:],
        "champion": lambda l: f"🏆 優勝 {l}",
        "aria": "高円宮杯U-15選手権2026 トーナメント表",
        "caption": (
            '<p style="margin:0 0 8px;color:var(--text-light,#666);font-size:0.88em;">'
            '📱 スマホでは表を左右にスクロールできます ／ ［ ］内は地域の代表順 ／ '
            '<span style="color:var(--danger-color,#dc2626);font-weight:700;">赤線</span>＝勝ち上がり ／ '
            '<span style="border:1.5px solid var(--danger-color,#dc2626);border-radius:3px;padding:0 5px;">赤枠</span>＝勝ち残り</p>'),
    }
    # 地域の代表順を「各県代表」と同じ形で渡すと［九州1］のように校名の横に出る
    return ih.render_bracket_svg(sections, sections["地域の代表順"], loc=loc)


def main():
    sections = read_sections(DATA)
    errs = check(sections)
    if errs:
        print("❌ 検算NG：ページは書き換えていません")
        for e in errs:
            print("  -", e)
        return 1
    print("✅ 検算OK：16試合・32チーム、全チームに地域の代表順あり、結果のチーム名もすべて一致")
    if "--check" in sys.argv:
        return 0
    html = build(sections)
    if not html:
        print("❌ トーナメント表を描けませんでした")
        return 1
    with open(PAGE, encoding="utf-8") as f:
        page = f.read()
    if page.count(START) != 1 or page.count(END) != 1:
        print("❌ ページに目印（TAKAMADO_BRACKET:START/END）がちょうど1組ありません")
        return 1
    new = re.sub(re.escape(START) + r".*?" + re.escape(END),
                 lambda _m: START + "\n" + html + "\n" + END, page, count=1, flags=re.S)
    if new == page:
        print("— 変更なし")
        return 0
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(new)
    print("✅ トーナメント表を更新しました：", os.path.relpath(PAGE, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
