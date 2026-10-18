"""県ページのトーナメント表（SVG）に出ている校名を数える検証用スクリプト。
使い方: python3 check_bracket.py 生成後のprefectures/<県>/index.html [生成前の同じファイル]
  1つ目だけ → 大会ごとに「表があるか・校名の数・校名一覧」を出す。
  2つ目も渡す → 表の校名の増減と、全試合一覧（<li>）が変わっていないかも出す。
"""
import html
import re
import sys

NAME_RE = re.compile(r'<text[^>]*class="bk-(?:won|team|acc)"[^>]*>([^<]+)'
                     r'(?:<tspan class="bk-rank"[^>]*>([^<]*)</tspan>)?</text>')


def sections(path):
    s = open(path, encoding="utf-8").read()
    out = {}
    for sec in re.findall(r'<section class="lp-section tournament-section.*?</section>', s, re.S):
        t = re.search(r'<h2>(.*?)</h2>', sec, re.S)
        title = re.sub(r'<[^>]+>', '', t.group(1)).strip() if t else "?"
        names = [html.unescape(n).strip() + (f"（{r}）" if r else "") for n, r in NAME_RE.findall(sec)]
        lis = sorted(re.findall(r'<li(?:\s[^>]*)?>.*?</li>', sec, re.S))
        out[title] = {"svg": "<svg" in sec, "names": names, "li": lis}
    return out


after = sections(sys.argv[1])
before = sections(sys.argv[2]) if len(sys.argv) > 2 else None
for title, a in after.items():
    print(f"■ {title[:50]}  表={'あり' if a['svg'] else 'なし'}  校名{len(a['names'])}")
    if before is None:
        print("   " + " / ".join(a["names"]))
        continue
    b = before.get(title, {"svg": False, "names": [], "li": []})
    gone = sorted(set(b["names"]) - set(a["names"]))
    new = sorted(set(a["names"]) - set(b["names"]))
    if gone or new:
        print(f"   消えた: {gone}\n   増えた: {new}")
    print(f"   全試合一覧(<li>): {'変化なし' if a['li'] == b['li'] else '★変化あり'}")
