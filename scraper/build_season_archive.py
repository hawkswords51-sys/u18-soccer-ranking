#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年別アーカイブ（県47＋リーグ15＝62枚）を作る（2026-11-13）
==========================================================
12月のシーズン凍結の日に、手で1回だけ走らせる。自動更新（GitHub Actions）には組み込まない。

その日の現行ページ（prefectures/{id}/index.html・leagues/{slug}/index.html）から
  ① 順位表 ② 戦績表（#cross-table）③ 得点ランキング（#scorer-ranking・あるページだけ）
を切り出して、保存用の枠に入れる。描画をやり直さないので、その日にサイトに出ていた表がそのまま残る。

使い方
  python scraper/build_season_archive.py --year 2026 --report        # 書かずに一覧だけ出す
  python scraper/build_season_archive.py --year 2026                 # 62枚を書く
  python scraper/build_season_archive.py --year 2026 --freeze-data   # 上に加えて data/archive/2026/ を作る
  --force を付けたときだけ、既にある保存ページを上書きする（保存ページは一度作ったら変えない）。
"""
import argparse
import html
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOMAIN = "https://u18-soccer.com"
JST = timezone(timedelta(hours=9))

LEAGUES = [  # (slug, 表示名) ※ leagues/prince-kansai/ は移転案内なので対象外
    ("premier-east", "プレミアリーグEAST"), ("premier-west", "プレミアリーグWEST"),
    ("prince-hokkaido", "プリンスリーグ北海道"), ("prince-tohoku", "プリンスリーグ東北"),
    ("prince-kanto-1", "プリンスリーグ関東1部"), ("prince-kanto-2", "プリンスリーグ関東2部"),
    ("prince-hokushinetsu-1", "プリンスリーグ北信越1部"), ("prince-hokushinetsu-2", "プリンスリーグ北信越2部"),
    ("prince-tokai", "プリンスリーグ東海"),
    ("prince-kansai-1", "プリンスリーグ関西1部"), ("prince-kansai-2", "プリンスリーグ関西2部"),
    ("prince-chugoku", "プリンスリーグ中国"), ("prince-shikoku", "プリンスリーグ四国"),
    ("prince-kyushu-1", "プリンスリーグ九州1部"), ("prince-kyushu-2", "プリンスリーグ九州2部"),
]
FREEZE_DIRS = ["teams.json", "league_matches", "scorers", "prince-scorers"]


class ExtractError(Exception):
    pass


# ---------------------------------------------------------------------------
# 切り出し
# ---------------------------------------------------------------------------

def _section_by_id(t: str, sid: str) -> str:
    """<section … id="sid"> を入れ子を数えて丸ごと返す。無ければ空文字"""
    m = re.search(r'<section\b[^>]*\bid="%s"[^>]*>' % re.escape(sid), t)
    if not m:
        return ""
    depth, pos = 0, m.start()
    for tag in re.finditer(r"<(/?)section\b[^>]*>", t[m.start():]):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return t[m.start(): m.start() + tag.end()]
    raise ExtractError(f"section#{sid} の終わりが見つからない")


def _standings(t: str) -> tuple:
    """①順位表：「…順位表」の h2 から、その後の最初の </table> を閉じる </div> まで"""
    for m in re.finditer(r'<h2 class="section-title-lp">(.*?)</h2>', t, re.S):
        if re.sub(r"<[^>]+>|\s+", "", m.group(1)).endswith("順位表"):
            j = t.find("</table>", m.end())
            k = t.find("</div>", j) if j >= 0 else -1
            if k < 0:
                raise ExtractError("順位表の </table> か </div> が見つからない")
            block = t[m.start(): k + len("</div>")]
            rows = len(re.findall(r"<tr\b", block[block.find("<tbody"):])) if "<tbody" in block else 0
            return block, rows
    raise ExtractError("「…順位表」の見出しが見つからない")


def extract(page: Path) -> dict:
    t = page.read_text(encoding="utf-8")
    st, rows = _standings(t)
    xt = _section_by_id(t, "cross-table")
    if not xt:
        raise ExtractError("戦績表（#cross-table）が無い")
    return {"html": t, "standings": st, "rows": rows, "cross": xt, "scorers": _section_by_id(t, "scorer-ranking")}


# ---------------------------------------------------------------------------
# 対象ページと未消化の数
# ---------------------------------------------------------------------------

def targets():
    teams = json.loads((ROOT / "data" / "teams.json").read_text(encoding="utf-8"))
    out = []
    for pid, pref in teams.items():
        if (ROOT / "prefectures" / pid / "index.html").exists():
            files = sorted((ROOT / "data" / "league_matches").glob(f"pref-{pid}-*.json"))
            out.append({"kind": "pref", "id": pid, "name": pref.get("name", pid),
                        "dir": f"prefectures/{pid}", "files": files})
    for slug, name in LEAGUES:
        out.append({"kind": "league", "id": slug, "name": name, "dir": f"leagues/{slug}",
                    "files": [ROOT / "data" / "league_matches" / f"{slug}.json"]})
    return out


def unplayed(files) -> int:
    n = 0
    for f in files:
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        ms = d.get("matches") if isinstance(d, dict) else d
        n += sum(1 for m in ms or [] if m.get("hs") is None)
    return n


# ---------------------------------------------------------------------------
# 保存ページ
# ---------------------------------------------------------------------------

def _texts(tg, year, n_un, has_sc):
    final = n_un == 0
    if tg["kind"] == "pref":
        title = (f"{tg['name']} 高校サッカーリーグ{year} " + ("最終結果・順位" if final else "結果・順位（シーズン記録）")
                 + "｜U-18")
    else:
        title = f"{tg['name']} {year} " + ("最終結果・順位" if final else "結果・順位（シーズン記録）") + "｜高円宮杯U-18"
    h1 = title.split("｜")[0]
    return title, h1, final


def build_page(tg, ex, year, saved_on, n_un):
    esc = html.escape
    t = ex["html"]
    title, h1, final = _texts(tg, year, n_un, bool(ex["scorers"]))
    url = f"{DOMAIN}/{tg['dir']}/{year}/"
    cur = f"/{tg['dir']}/"
    desc = (f"{tg['name']}の{year}年シーズンの{'最終順位' if final else '順位'}・戦績表（星取表）"
            f"{'・得点ランキング' if ex['scorers'] else ''}。{saved_on}時点の記録。")

    head_end = t.find("</head>")
    head, rest = t[:head_end], t[head_end:]
    head = re.sub(r"<title>.*?</title>", f"<title>{esc(title)}</title>", head, count=1, flags=re.S)
    for attr, key, val in (("name", "description", desc), ("property", "og:title", title),
                           ("property", "og:description", desc), ("property", "og:url", url)):
        head = re.sub(r'(<meta\s+%s="%s"\s+content=")[^"]*(")' % (attr, re.escape(key)),
                      lambda m, v=val: m.group(1) + esc(v, quote=True) + m.group(2), head, count=1)
    head = re.sub(r'(<link\s+rel="canonical"\s+href=")[^"]*(")', lambda m: m.group(1) + url + m.group(2), head, count=1)
    head = re.sub(r'\s*<script type="application/ld\+json">.*?</script>', "", head, flags=re.S)
    if tg["kind"] == "pref":
        crumbs = [("ホーム", f"{DOMAIN}/"), (tg["name"], f"{DOMAIN}{cur}"), (f"{year}年", url)]
    else:
        crumbs = [("ホーム", f"{DOMAIN}/"), ("リーグ一覧", f"{DOMAIN}/leagues/"),
                  (tg["name"], f"{DOMAIN}{cur}"), (f"{year}年", url)]
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList",
          "itemListElement": [{"@type": "ListItem", "position": i, "name": n, "item": u}
                              for i, (n, u) in enumerate(crumbs, 1)]}
    head += ('\n  <script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>\n")

    sep = '\n        <span class="breadcrumb__sep">›</span>\n        '
    links = [f'<a href="{u.replace(DOMAIN, "")}">{esc(n)}</a>' for n, u in crumbs[:-1]]
    nav = ('      <nav class="breadcrumb" aria-label="パンくずリスト">\n        '
           + sep.join(links + [f'<span aria-current="page">{year}年</span>']) + "\n      </nav>\n")
    band = (f"この記録は{year}年シーズンの{'最終結果' if final else '結果'}です（{saved_on}に保存。以後は更新しません）。"
            f'最新のシーズンは → <a href="{cur}">{esc(tg["name"])}の最新の順位</a>')
    if n_un:
        band += f"<br>{n_un}試合は、保存した時点で当サイトの出典に結果がありませんでした。"
    style = ("margin:0 0 18px;padding:12px 16px;background:var(--bg-light,#f1f5fb);"
             "border-left:4px solid var(--primary-color,#1e40af);border-radius:0 8px 8px 0;"
             "font-size:0.95rem;line-height:1.8;")
    lead = ('      <p style="line-height:1.8;">県内のチームを、所属リーグの格とリーグ内の順位で並べた'
            '当サイト独自の県内総合順位です。</p>\n') if tg["kind"] == "pref" else ""
    main = ('<main class="main-content">\n    <div class="container">\n' + nav
            + f'\n      <h1 class="lp-title">{esc(h1)}</h1>\n'
            + f'      <p class="archive-band" style="{style}">{band}</p>\n\n'
            + lead + "      " + ex["standings"] + "\n\n" + ex["cross"] + "\n"
            + (("\n" + ex["scorers"] + "\n") if ex["scorers"] else "")
            + f'\n      <p style="margin:24px 0;"><a href="{cur}">最新シーズンの順位はこちら → {esc(tg["name"])}</a></p>\n'
            + "    </div>\n  </main>")
    mi, me = rest.find("<main"), rest.find("</main>")
    if mi < 0 or me < 0:
        raise ExtractError("<main> が見つからない")
    return head + rest[:mi] + main + rest[me + len("</main>"):], title


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--freeze-data", action="store_true")
    a = ap.parse_args()
    now = datetime.now(JST)
    saved_on = f"{now.year}年{now.month}月{now.day}日"

    plan, errors = [], []
    for tg in targets():
        try:
            ex = extract(ROOT / tg["dir"] / "index.html")
        except (ExtractError, OSError) as e:
            errors.append(f"{tg['dir']}: {e}")
            continue
        plan.append((tg, ex, unplayed(tg["files"])))
    if errors:
        print("⚠ 切り出せなかったページ（作らずに止めます）：\n  " + "\n  ".join(errors))
        return 1

    if a.report:
        n_final = 0
        for tg, ex, n_un in plan:
            n_final += n_un == 0
            print(f"{tg['dir']:32s} 未消化 {n_un:3d}  {'最終結果    ' if n_un == 0 else 'シーズン記録'}"
                  f"  得点ランキング {'あり' if ex['scorers'] else 'なし'}  順位表 {ex['rows']}行")
        print(f"\n合計 {len(plan)} 枚（最終結果 {n_final}・シーズン記録 {len(plan) - n_final}・"
              f"得点ランキングあり {sum(1 for _, ex, _ in plan if ex['scorers'])}）")
        return 0

    exists = [tg["dir"] for tg, _, _ in plan if (ROOT / tg["dir"] / str(a.year) / "index.html").exists()]
    if exists and not a.force:
        print(f"⚠ 保存ページが既に {len(exists)} 枚あります（例：{exists[0]}/{a.year}/）。上書きしません。"
              "作り直すときだけ --force を付けてください。")
        return 1
    for tg, ex, n_un in plan:
        page, _ = build_page(tg, ex, a.year, saved_on, n_un)
        dest = ROOT / tg["dir"] / str(a.year) / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page, encoding="utf-8")
    print(f"{len(plan)} 枚の保存ページを書きました（{saved_on}）")

    if a.freeze_data:
        dst = ROOT / "data" / "archive" / str(a.year)
        if dst.exists() and not a.force:
            print(f"⚠ {dst.relative_to(ROOT)} が既にあります。上書きしません。")
            return 1
        dst.mkdir(parents=True, exist_ok=True)
        for name in FREEZE_DIRS:
            src = ROOT / "data" / name
            if src.is_dir():
                shutil.copytree(src, dst / name, dirs_exist_ok=True)
            elif src.exists():
                shutil.copy2(src, dst / name)
        print(f"データを凍結コピーしました → {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
