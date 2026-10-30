#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SNS用画像（Instagram・Threads 向け 1080x1350 縦長）を、リポジトリのデータから作る単独スクリプト。

サイトの生成・公開の仕組みには一切つながない（GitHub Actions に入れない・サイトのページは変えない）。
データは読むだけ。PNG はリポジトリの外に書く。

  python3 sns-images/make_sns_images.py                       # 全種類
  python3 sns-images/make_sns_images.py --only premier        # 種類を選ぶ（カンマ区切り）
     種類: senshuken-daihyo（県代表決定カード）／senshuken-ichiran（代表校一覧6枚）／premier（プレミア順位表2枚）
  OUT_DIR=/どこか python3 sns-images/make_sns_images.py       # 出力先を変える

出力先の既定: ~/Documents/Claude/Projects/u18-soccer.com運営/SNS画像/YYYY-MM-DD/（JSTの実行日）
"""

import json
import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow（画像を作る部品）が入っていません。")
    print("入れるには: python3 -m pip install --user Pillow")
    print("（勝手には入れません。入れてよいかKeiに確認してください）")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
import generate_senshuken_page as sp  # noqa: E402  代表の判定は特設ページと同じ analyze() を使う（二重実装にしない）
from jst import today  # noqa: E402

W, H = 1080, 1350
SAFE_Y = 90            # Instagram の一覧で上下が切られる分。大事な文字はこの内側
SIDE = 80              # 左右の余白
TEXT_W = W - SIDE * 2  # 文字を置ける幅

BG_TOP = (0x1e, 0x3a, 0x8a)   # 深紺（サイトの配色・手順書 4-19）
BG_BOT = (0x16, 0x29, 0x5f)
GREEN = (0x2e, 0x8b, 0x57)    # 芝グリーン（細い線だけに使う）
WHITE = (255, 255, 255)
GRAY = (203, 213, 225)        # ごく薄い灰色
DIM = (148, 163, 184)

FONT_BOLD = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/Library/Fonts/NotoSansCJKjp-Bold.otf",
    "/opt/homebrew/share/fonts/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]
FONT_REG = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
    "/Library/Fonts/NotoSansCJKjp-Regular.otf",
    "/opt/homebrew/share/fonts/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def _find_font(cands, kind):
    for p in cands:
        if os.path.exists(p):
            return p
    print(f"日本語の{kind}フォントが見つかりません（文字化けを防ぐため止めます）。探した場所:")
    for p in cands:
        print("  ", p)
    sys.exit(1)


BOLD = _find_font(FONT_BOLD, "太字")
REG = _find_font(FONT_REG, "細字")
_cache = {}


def font(size, bold=True):
    key = (size, bold)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(BOLD if bold else REG, size)
    return _cache[key]


def text_w(d, s, f):
    return d.textlength(s, font=f)


def fit(d, s, maxw, size, minsize, bold=True):
    """枠（maxw）に収まるまで文字を小さくする。最小でも収まらなければ止める（切れたまま出さない）。"""
    while size >= minsize:
        f = font(size, bold)
        if text_w(d, s, f) <= maxw:
            return f
        size -= 2
    raise SystemExit(f"文字が枠に収まりません（最小 {minsize}px でも幅 {maxw}px を超える）: {s}")


def canvas():
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))
    return img, d


def footer(d):
    y = H - SAFE_Y - 70
    d.line([(SIDE, y), (W - SIDE, y)], fill=GREEN, width=3)
    d.text((W // 2, y + 38), "u18-soccer.com", font=font(34), fill=GRAY, anchor="mm")


def heading(d, y, s, size=56, color=WHITE, underline=True):
    f = fit(d, s, TEXT_W, size, 28)
    d.text((W // 2, y), s, font=f, fill=color, anchor="mm")
    if underline:
        uw = min(text_w(d, s, f), TEXT_W) * 0.5
        d.line([(W // 2 - uw / 2, y + size * 0.75), (W // 2 + uw / 2, y + size * 0.75)], fill=GREEN, width=4)


def md(dates):
    return "・".join(f"{m}/{dd}" for m, dd in dates)


def flip_score(score):
    """「a-b」「a-b(PKx-y)」を逆向きにする（代表校を左に置くため）。"""
    main, _, pk = score.partition("(")
    x, y = main.split("-")
    out = f"{y}-{x}"
    if pk:
        p = pk.rstrip(")").replace("PK", "")
        px, py = p.split("-")
        out += f"(PK{py}-{px})"
    return out


def save(img, out, name, made):
    p = out / name
    img.save(p, "PNG")
    made.append(p)


# ----------------------------------------------------------------- A. 県代表決定カード
def make_daihyo(out, made, notes):
    skipped = 0
    for _region, prefs in sp.REGIONS:
        for slug, name in prefs:
            info = sp.analyze(slug)
            fms = [fm for fm in (info or {}).get("final_matches", []) if fm[3] and fm[3] != "確認中"]
            if not fms:
                skipped += 1
                continue
            for label, a, b, w, score, dates in fms:
                opp = b if w == a else a
                sc = score if w == a else flip_score(score)
                img, d = canvas()
                d.text((W // 2, SAFE_Y + 80), "第105回全国高校サッカー選手権", font=fit(d, "第105回全国高校サッカー選手権", TEXT_W, 44, 28, False), fill=GRAY, anchor="mm")
                heading(d, SAFE_Y + 170, f"{name}代表" + (f"（{label}）" if label else ""), 64)
                f = fit(d, w, TEXT_W, 190, 40)
                d.text((W // 2, 610), w, font=f, fill=WHITE, anchor="mm")
                line = f"決勝 {w} {sc} {opp}"
                d.text((W // 2, 850), line, font=fit(d, line, TEXT_W, 50, 26), fill=GRAY, anchor="mm")
                if dates:
                    d.text((W // 2, 930), md(dates), font=font(42, False), fill=DIM, anchor="mm")
                footer(d)
                suffix = ""
                if label:
                    suffix = "-" + ("a" if label.startswith("A") else "b" if label.startswith("B") else label)
                save(img, out, f"senshuken-daihyo-{slug}{suffix}.png", made)
    notes.append(f"県代表カード：代表未定で作らなかった県 {skipped}")


# ----------------------------------------------------------------- B. 代表校一覧（6枚）
SHEETS = [
    ("1-hokkaido-tohoku", ["北海道", "東北"]),
    ("2-kanto", ["関東"]),
    ("3-hokushinetsu-tokai", ["北信越", "東海"]),
    ("4-kansai", ["関西"]),
    ("5-chugoku-shikoku", ["中国", "四国"]),
    ("6-kyushu", ["九州"]),
]


def rep_text(slug, info):
    reps = (info or {}).get("reps", [])
    if slug == "tokyo":  # 東京は A/B ブロックで2校
        got = {lab[:1]: w for lab, w in reps}
        return "　".join(f"{k} {got.get(k, '未定')}" for k in ("A", "B")), all(
            got.get(k) not in (None, "確認中") for k in ("A", "B"))
    if not reps:
        return "未定", False
    w = reps[0][1]
    return w, w != "確認中"


def make_ichiran(out, made, notes):
    regions = dict(sp.REGIONS)
    rows_all = {}
    decided = 0
    for _r, prefs in sp.REGIONS:
        for slug, name in prefs:
            txt, ok = rep_text(slug, sp.analyze(slug))
            rows_all[slug] = (name, txt, ok)
            decided += ok
    t = today()
    for i, (key, regs) in enumerate(SHEETS):
        img, d = canvas()
        heading(d, SAFE_Y + 70, "・".join(regs), 64)
        d.text((W // 2, SAFE_Y + 150), "第105回全国高校サッカー選手権　県代表", font=font(36, False), fill=GRAY, anchor="mm")
        top = SAFE_Y + 200
        if i == 0:
            s = f"{decided}/47 県で代表決定（{t.month}/{t.day}時点）"
            d.text((W // 2, top + 20), s, font=fit(d, s, TEXT_W, 40, 26), fill=WHITE, anchor="mm")
            top += 70
        bottom = H - SAFE_Y - 100
        n_rows = sum(len(regions[r]) for r in regs)
        n_head = len(regs) if len(regs) > 1 else 0
        unit = (bottom - top) / (n_rows + 0.8 * n_head)
        row_h = min(unit, 96)
        y = top
        for r in regs:
            if n_head:
                d.text((SIDE, y + row_h * 0.4), r, font=font(30), fill=DIM, anchor="lm")
                y += row_h * 0.8
            for slug, _n in regions[r]:
                name, txt, ok = rows_all[slug]
                cy = y + row_h / 2
                d.line([(SIDE, y + row_h), (W - SIDE, y + row_h)], fill=(0x33, 0x4f, 0x9a), width=1)
                d.text((SIDE + 10, cy), name, font=font(40), fill=GRAY, anchor="lm")
                fx = SIDE + 200
                d.text((fx, cy), txt, font=fit(d, txt, W - SIDE - fx, 46, 22),
                       fill=WHITE if ok else DIM, anchor="lm")
                y += row_h
        footer(d)
        save(img, out, f"senshuken-ichiran-{key}.png", made)
    notes.append(f"代表校一覧：{decided}/47 県で代表決定")


# ----------------------------------------------------------------- C. プレミア順位表
def make_premier(out, made, notes):
    for key, label in (("east", "EAST"), ("west", "WEST")):
        data = json.loads((ROOT / "data" / "league_matches" / f"premier-{key}.json").read_text(encoding="utf-8"))
        rows = sorted(data["official_standings"], key=lambda r: r["rank"])
        m, dd = map(int, data["lastUpdated"].split("-")[1:3])
        img, d = canvas()
        d.text((W // 2, SAFE_Y + 60), "高円宮杯 U-18プレミアリーグ2026", font=fit(d, "高円宮杯 U-18プレミアリーグ2026", TEXT_W, 44, 28, False), fill=GRAY, anchor="mm")
        heading(d, SAFE_Y + 140, label, 72)
        d.text((W // 2, SAFE_Y + 225), f"{m}/{dd}時点", font=font(34, False), fill=DIM, anchor="mm")
        x_rank, x_team, x_pl, x_pts, x_gd = SIDE + 30, SIDE + 90, 760, 870, W - SIDE
        top = SAFE_Y + 280
        hf = font(28, False)
        d.text((x_rank, top), "順位", font=hf, fill=DIM, anchor="mm")
        d.text((x_team, top), "チーム", font=hf, fill=DIM, anchor="lm")
        d.text((x_pl, top), "試合", font=hf, fill=DIM, anchor="mm")
        d.text((x_pts, top), "勝点", font=hf, fill=DIM, anchor="mm")
        d.text((x_gd, top), "得失差", font=font(22, False), fill=DIM, anchor="rm")
        y0 = top + 30
        bottom = H - SAFE_Y - 100
        row_h = (bottom - y0) / len(rows)
        for i, r in enumerate(rows):
            y = y0 + i * row_h
            cy = y + row_h / 2
            if i % 2 == 0:
                d.rectangle([(SIDE, y), (W - SIDE, y + row_h)], fill=(0x24, 0x44, 0x96))
            d.text((x_rank, cy), str(r["rank"]), font=font(38), fill=WHITE, anchor="mm")
            d.text((x_team, cy), r["team"], font=fit(d, r["team"], x_pl - 50 - x_team, 38, 20), fill=WHITE, anchor="lm")
            d.text((x_pl, cy), str(r["played"]), font=font(36, False), fill=GRAY, anchor="mm")
            d.text((x_pts, cy), str(r["pts"]), font=font(42), fill=WHITE, anchor="mm")
            gd = r["gd"]
            d.text((x_gd, cy), f"{gd:+d}" if gd else "0", font=font(26, False), fill=DIM, anchor="rm")
        footer(d)
        save(img, out, f"premier-{key}.png", made)
        notes.append(f"プレミア{label}：{len(rows)}チーム（{m}/{dd}時点）")


KINDS = {
    "senshuken-daihyo": make_daihyo,
    "senshuken-ichiran": make_ichiran,
    "premier": make_premier,
}


def main():
    args = sys.argv[1:]
    only = list(KINDS)
    if "--only" in args:
        only = [k.strip() for k in args[args.index("--only") + 1].split(",") if k.strip()]
        bad = [k for k in only if k not in KINDS]
        if bad:
            raise SystemExit(f"知らない種類: {', '.join(bad)}（使えるのは {', '.join(KINDS)}）")
    default = Path.home() / "Documents/Claude/Projects/u18-soccer.com運営/SNS画像" / today().isoformat()
    out = Path(os.environ.get("OUT_DIR") or default).expanduser()
    if out.resolve() == ROOT or ROOT in out.resolve().parents:
        raise SystemExit(f"出力先がリポジトリの中です（PNGはリポジトリに置かない）: {out}")
    out.mkdir(parents=True, exist_ok=True)
    made, notes = [], []
    for k in only:
        KINDS[k](out, made, notes)
    print(f"出力先: {out}")
    for p in made:
        print("  ", p.name)
    print(f"作った枚数: {len(made)}")
    for n in notes:
        print("  ・", n)


if __name__ == "__main__":
    main()
