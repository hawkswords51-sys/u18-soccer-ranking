#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SNS用画像（Instagram・Threads 向け 1080x1350 縦長）を、リポジトリのデータから作る単独スクリプト。

サイトの生成・公開の仕組みには一切つながない（GitHub Actions に入れない・サイトのページは変えない）。
データは読むだけ。PNG はリポジトリの外に書く。

  python3 sns-images/make_sns_images.py                       # 全種類
  python3 sns-images/make_sns_images.py --only premier        # 種類を選ぶ（カンマ区切り）
     種類: senshuken-daihyo（県代表決定カード）／senshuken-ichiran（代表校一覧6枚）／premier（プレミア順位表2枚）
           today-finals（今日の決勝の画像＋投稿文。--date 11/8 で日付指定）
           today-daihyo（今日決まった県代表カード＋投稿文。--date で日付指定）
           senshuken-taiketsu（選手権本大会の対戦カード：1回戦16枚＋相手が決まった2回戦。投稿文 senshuken-taiketsu.txt）
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

if os.environ.get("SNS_DATA_ROOT"):  # 自動実行用：GitHub の最新データを取り出した場所を読む（手元のリポジトリは触らない）
    sp.TDIR = Path(os.environ["SNS_DATA_ROOT"]) / "data" / "tournaments"

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
def official_name(short):
    """REGIONS の短い名前（秋田・東京など）を正式な都道府県名にする。北海道はそのまま。"""
    if short == "北海道":
        return short
    return short + {"東京": "都", "大阪": "府", "京都": "府"}.get(short, "県")


def make_daihyo(out, made, notes, day=None, done=None):
    """day=(月,日) を渡すと、その日に決勝があった県だけ作る（夜の自動用）。done には (県名, ブロック, 代表, スコア, 相手) を足す。"""
    skipped = 0
    for _region, prefs in sp.REGIONS:
        for slug, name in prefs:
            info = sp.analyze(slug)
            fms = [fm for fm in (info or {}).get("final_matches", []) if fm[3] and fm[3] != "確認中"]
            if day is not None:
                fms = [fm for fm in fms if day in fm[5]]
            if not fms:
                skipped += 1
                continue
            for label, a, b, w, score, dates in fms:
                opp = b if w == a else a
                sc = score if w == a else flip_score(score)
                img, d = canvas()
                d.text((W // 2, SAFE_Y + 80), "第105回全国高校サッカー選手権", font=fit(d, "第105回全国高校サッカー選手権", TEXT_W, 44, 28, False), fill=GRAY, anchor="mm")
                heading(d, SAFE_Y + 170, f"{official_name(name)}代表" + (f"（{label}）" if label else ""), 64)
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
                if done is not None:
                    done.append((name, label, w, sc, opp))
    if day is None:
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
        d.text((W // 2, SAFE_Y + 150), "第105回全国高校サッカー選手権　都道府県代表", font=font(36, False), fill=GRAY, anchor="mm")
        top = SAFE_Y + 200
        if i == 0:
            s = f"{decided}/47 都道府県で代表決定（{t.month}/{t.day}時点）"
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
    (out / "senshuken-ichiran.txt").write_text(
        "■ Instagram フィード（6枚を、めくって見る1つの投稿にまとめる）\n\n"
        f"第105回全国高校サッカー選手権の都道府県代表、{t.month}/{t.day}時点で{decided}/47 都道府県が決まりました。\n"
        "地域別に6枚にまとめています。\n\n"
        "各都道府県の予選結果は、プロフィールのリンクから見られます。\n\n"
        "#高校サッカー #高校サッカー選手権 #選手権予選\n",
        encoding="utf-8")
    made.append(out / "senshuken-ichiran.txt")
    notes.append(f"代表校一覧：{decided}/47 都道府県で代表決定")


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


# ----------------------------------------------------------------- D. 今日の決勝（朝のストーリーズ・Threads 用）
SITE_URL = "https://u18-soccer.com/tournaments/senshuken-2026/"
FINALS_PER_SHEET = 8   # 1枚に並べる決勝の数（これを超えたら2枚目に分ける）


def area_word(names):
    """短い名前の並び → 「県」「府県」「都道府県」など、含まれる分だけの呼び方。"""
    got = {official_name(n)[-1] for n in names}
    return "".join(c for c in "都道府県" if c in got) or "県"


def target_day():
    """--date 11/8 で日付を指定（試し用）。無ければ今日（JST）。"""
    args = sys.argv[1:]
    if "--date" in args:
        m, dd = map(int, args[args.index("--date") + 1].split("/"))
        return (m, dd)
    t = today()
    return (t.month, t.day)


def day_matches(day):
    """その日の決勝（まだ結果の無い組み合わせ）と、決勝以外で試合のある県。
    回戦の日付は見出しの（10/22）、無ければ frontmatter の round_dates を使う（特設ページと同じ）。"""
    finals, others, missing = [], [], []
    for _r, prefs in sp.REGIONS:
        for slug, name in prefs:
            path = sp.TDIR / "senshuken-2026" / f"{slug}-senshuken-2026.md"
            if not path.exists():
                continue
            meta, rounds = sp.parse_md(path)
            rd = sp.parse_round_dates(meta)
            pairs, cur = {}, None   # 回戦名 → [(a, b)]（まだ結果の無い行）
            for raw in path.read_text(encoding="utf-8").split("---", 2)[-1].splitlines():
                s = raw.strip()
                m = sp.HEAD_RE.match(s)
                if m:
                    cur = m.group("key").strip()
                    continue
                if cur and sp.VS_RE.match(s):
                    a, b = s[2:].split(" vs ", 1)
                    pairs.setdefault(cur, []).append((a.strip(), b.strip()))
            other_here = False
            for r in rounds:
                fin = sp.is_final(slug, r["key"])
                dates = r["dates"] or rd.get("決勝" if fin else r["key"], [])
                if day not in dates or not r["pending"]:
                    continue
                if fin:
                    label = r["key"].replace("決勝", "") if slug == "tokyo" else ""
                    for a, b in pairs.get(r["key"], []):
                        if "/" in a or "/" in b:   # 「旭川実/クラーク記念国際」＝準決勝がまだで相手が決まっていない
                            missing.append(name + label)
                        else:
                            finals.append((name, label, a, b))
                else:
                    other_here = True
            if (not any(sp.is_final(slug, r["key"]) for r in rounds) and slug != "tokyo"
                    and day in rd.get("決勝", [])):
                missing.append(name)   # 決勝の日なのに、組み合わせの見出しがまだ無い
            if other_here and name not in [f[0] for f in finals] and not any(x.startswith(name) for x in missing):
                others.append(name)
    return finals, others, missing


def make_today(out, made, notes):
    day = target_day()
    m, dd = day
    finals, others, missing = day_matches(day)
    if missing:
        notes.append(f"今日の決勝：{'・'.join(missing)} は決勝の日ですが、組み合わせがまだ決まっていない（データに無い）ので入れていません")
    if not finals:
        notes.append(f"今日の決勝：{m}/{dd} に決勝はありません（画像は作りません）")
        return
    prefs = list(dict.fromkeys(f[0] for f in finals))
    n_reps = len(finals)
    word = area_word(prefs)
    sheets = [finals[i:i + FINALS_PER_SHEET] for i in range(0, len(finals), FINALS_PER_SHEET)]
    for si, rows in enumerate(sheets):
        img, d = canvas()
        d.text((W // 2, SAFE_Y + 80), "第105回全国高校サッカー選手権",
               font=fit(d, "第105回全国高校サッカー選手権", TEXT_W, 40, 28, False), fill=GRAY, anchor="mm")
        heading(d, SAFE_Y + 165, f"{m}/{dd} 都道府県予選 決勝", 64)
        sub = f"今日、{len(prefs)}{word}の代表が決まります" if n_reps == len(prefs) else \
            f"今日、{len(prefs)}{word}で{n_reps}校の代表が決まります"
        if len(sheets) > 1:
            sub += f"（{si + 1}/{len(sheets)}）"
        d.text((W // 2, SAFE_Y + 270), sub, font=fit(d, sub, TEXT_W, 38, 26, False), fill=GRAY, anchor="mm")
        top, bottom = SAFE_Y + 320, H - SAFE_Y - 200
        row_h = min(118, (bottom - top) / len(rows))
        size = 46 if row_h >= 100 else 40
        line_c = (0x33, 0x4f, 0x9a)
        d.line([(SIDE, top), (W - SIDE, top)], fill=line_c, width=1)
        for i, (name, label, a, b) in enumerate(rows):
            y = top + i * row_h
            cy = y + row_h / 2
            d.text((SIDE + 10, cy), name + label.replace("ブロック", ""), font=font(size - 6), fill=GRAY, anchor="lm")
            fx = SIDE + 140
            s = f"{a}  vs  {b}"
            d.text((fx, cy), s, font=fit(d, s, W - SIDE - fx, size, 24), fill=WHITE, anchor="lm")
            d.line([(SIDE, y + row_h), (W - SIDE, y + row_h)], fill=line_c, width=1)
        if others and si == len(sheets) - 1:
            s = f"このほか{len(others)}{area_word(others)}で準決勝などの試合があります"
            d.text((W // 2, bottom + 45), s, font=fit(d, s, TEXT_W, 34, 24, False), fill=DIM, anchor="mm")
        footer(d)
        save(img, out, f"today-finals-{m:02d}{dd:02d}" + (f"-{si + 1}" if len(sheets) > 1 else "") + ".png", made)

    # 投稿文（Threads）とストーリーズのリンク
    lines = [f"今日{m}/{dd}は、選手権予選の決勝が{len(prefs)}{word}であります。"]
    for name, label, a, b in finals:
        lines.append(f"{name}{'（' + label + '）' if label else ''}：{a} vs {b}")
    lines += ["各県の予選結果はこちら", SITE_URL + "?utm_source=threads&utm_medium=social&utm_campaign=today"]
    threads = "\n".join(lines)
    story = SITE_URL + "?utm_source=instagram&utm_medium=social&utm_campaign=story"
    txt = out / f"today-finals-{m:02d}{dd:02d}.txt"
    txt.write_text(
        "■ ストーリーズ（朝8〜9時ごろ）\n画像を選び、スタンプの「リンク」に次のURLを入れる\n" + story + "\n\n"
        "■ Threads（同じ画像を付ける。トピックは「高校サッカー」）\n" + threads + "\n\n"
        f"（Threadsの文は{len(threads)}字。500字まで1つの投稿に入ります）\n"
        "※ 組み合わせはサイトのデータ（直近の自動更新の分）から写しています。キックオフ時刻はデータに無いので入れていません。\n",
        encoding="utf-8")
    made.append(txt)
    notes.append(f"今日の決勝：{m}/{dd} 決勝 {n_reps}試合（{'・'.join(prefs)}）／ほかに試合のある{area_word(others) if others else '県'} {len(others)}")


# ----------------------------------------------------------------- E. 今日決まった県代表（夜の Instagram フィード用）
def hashtag(name):
    return "#" + "".join(c for c in name if c.isalnum())


def make_today_daihyo(out, made, notes):
    day = target_day()
    m, dd = day
    done = []
    make_daihyo(out, made, notes, day=day, done=done)
    finals, _others, _missing = day_matches(day)   # まだ結果の入っていない今日の決勝
    if not done:
        notes.append(f"今日の県代表：{m}/{dd} に決まった代表はまだデータにありません"
                     + (f"（結果待ち {len(finals)}試合）" if finals else ""))
        return
    prefs = list(dict.fromkeys(x[0] for x in done))
    word = area_word(prefs)
    lines = [f"{m}/{dd}、選手権予選の決勝で{len(prefs)}{word}の代表が決まりました。", ""]
    for name, label, w, sc, opp in done:
        lines.append(f"{official_name(name)}{'（' + label + '）' if label else ''}：{w}（決勝 {sc} {opp}）")
    lines += ["", "各都道府県の予選結果は、プロフィールのリンクから見られます。", ""]
    schools = [x[2] for x in done]
    lines.append(" ".join(["#高校サッカー", "#高校サッカー選手権"] + [hashtag(w) for w in schools[:3]]))
    caption = "\n".join(lines)
    txt = out / f"today-daihyo-{m:02d}{dd:02d}.txt"
    txt.write_text(
        "■ Instagram フィード（夜19〜21時ごろ）\n"
        f"県代表カード {len(done)}枚（senshuken-daihyo-〇〇.png）を、めくって見る1つの投稿にまとめる\n\n"
        + caption + "\n\n"
        + (f"※ ハッシュタグは5個まで。校名は最初の3校を入れています（{len(schools)}校のうち）。入れ替えてもかまいません。\n" if len(schools) > 3 else "")
        + (f"※ まだ結果がデータに入っていない今日の決勝が {len(finals)}試合あります（{'・'.join(dict.fromkeys(f[0] for f in finals))}）。\n" if finals else "")
        + "※ 「〇年連続〇回目」などの出場記録は入れていません（データに無いため）。\n",
        encoding="utf-8")
    made.append(txt)

    # Threads 用の結果の一言（決勝ごとに1つの投稿）
    posts = []
    for name, label, w, sc, opp in done:
        where = name + (label if label else "")
        main, _, pk = sc.partition("(")
        if pk:
            body = f"{w}が{opp}と{main}、{pk.rstrip(')')}で勝ち"
        else:
            body = f"{w}が{opp}を{main}で破り"
        posts.append(f"{where}は、{body}、代表に決まりました。")
    th = out / f"today-daihyo-threads-{m:02d}{dd:02d}.txt"
    th.write_text(
        "■ Threads（結果の一言。1行を1つの投稿に。トピックは「高校サッカー」）\n\n"
        + "\n\n".join(posts) + "\n\n"
        "※ 「〇年連続〇回目」などの出場記録は入れていません（データに無いため）。足すときは確かめてから。\n",
        encoding="utf-8")
    made.append(th)
    notes.append(f"今日の県代表：{m}/{dd} {len(done)}校（{'・'.join(prefs)}）"
                 + (f"／結果待ち {len(finals)}試合" if finals else ""))



# ----------------------------------------------------------------- F. 選手権本大会 対戦カードの「両校のデータ」（2026-11-17 新設）
def _school_short(nm):
    import re as _re
    return _re.sub(r"(高等学校|高等部|高校)$", "", nm or "")


def _taiketsu_values(nm, pref, note):
    """1校分の表示用テキスト（各項目 1〜2行のリスト）。中身は特設ページの比較表と同じ senshuken_matchup。"""
    import senshuken_matchup as mu
    from generate_interhigh_page import _short_league
    slug = sp.PREF_SLUG_BY_NAME.get(pref)
    d = mu.school_data(nm, slug, note)
    lg = d["league"]
    if lg and lg.get("league"):
        l1 = _short_league(lg["league"]) or lg["league"]
        if lg.get("rank") and lg.get("played"):
            rec = f"{lg['w']}勝{lg['d']}分{lg['l']}敗"
            l2 = f"最終{lg['rank']}位 {rec}" if lg.get("final") else f"{lg['rank']}位 {rec}（{lg['played']}試合時点）"
            league = [l1, l2]
        else:
            league = [l1]
    else:
        league = ["—"]
    q = d["qual"]
    qual = [f"{q['n']}試合 {q['gf']}得点{q['ga']}失点", q["final"]] if q else ["—"]
    ih = d["ih"] or "—"
    if "（" in ih:
        head, _, rest = ih.partition("（")
        ih_lines = [head, rest.rstrip("）")]
    else:
        ih_lines = [ih]
    nai = [f"{n}（{dst}）" for n, dst in d["naitei"]] or ["—"]
    return [("選手権の出場", [d["note"]]), ("選手権の最高成績", [d.get("best") or "—"]),
            ("2026年の所属リーグ", league), ("今大会の県予選", qual),
            ("インターハイ2026", ih_lines), ("プロ内定", nai[:2] + ([f"ほか{len(nai) - 2}人"] if len(nai) > 2 else []))]


def _taiketsu_page2(nm, pref):
    """[2026-11-18] 2枚目（人と履歴）：監督・前回大会・今季の得点源・代表選手・注目選手。
    各項目は [(文字, 種類)]。種類 b=太字（白）, s=小さい灰色。"""
    import senshuken_matchup as mu
    slug = sp.PREF_SLUG_BY_NAME.get(pref)
    d = mu.school_data(nm, slug, None)
    coach = d.get("coach") or "—"
    coach_lines = [(coach.split("（")[0].split("／")[0].strip(), "b")]  # 画像は名前だけ（経歴は特設ページの表に）
    prev = d.get("prev") or "—"
    prev_lines = [(prev.split("（")[0], "b")] + ([("（" + prev.split("（", 1)[1], "s")] if "（" in prev else [])
    sc = d.get("scorer")
    sc_lines = [(f"{sc[0]} {sc[1]}点", "b")] + ([(f"リーグ得点ランキング{sc[2]}位", "s")] if sc[2] else []) if sc else [("—", "b")]
    now, ob = d.get("national") or ([], [])
    nat_lines = []
    for x in now[:2]:
        n_, _, c_ = x.partition("（")
        nat_lines += [(n_, "b"), ("（" + c_, "s")]
    if ob:
        nat_lines += [("日本代表OB：" + "、".join(ob), "s")]
    pl_lines = []
    for x in (d.get("players") or [])[:3]:
        n_, _, c_ = x.partition("（")
        pl_lines += [(n_, "b")] + ([("（" + c_, "s")] if c_ else [])
    return [("監督", coach_lines), ("前回大会（2025年度）", prev_lines), ("今季の得点源（リーグ戦）", sc_lines),
            ("代表選手（現役の年代別代表・日本代表OB）", nat_lines or [("—", "b")]), ("注目選手", pl_lines or [("—", "b")])]


def make_taiketsu(out, made, notes):
    """1回戦16試合＋2回戦（両校が決まった試合）の対戦カード。1枚＝1試合。投稿文 taiketsu.txt も作る。"""
    import re as _re
    import senshuken_schedule as ss
    import senshuken_matchup as mu
    from generate_interhigh_page import collect_results
    sections = sp.parse_sections(sp.FINAL_MD)
    key = next((k for k in sections if k.startswith("トーナメント表")), None)
    rows = [l for l in sections.get(key, []) if l.strip().startswith("- ")] if key else []
    sched = sp._load_schedule(sections, rows) if len(rows) == sp.BRACKET_ROWS else None
    if not sched:
        notes.append("対戦カード：トーナメント表か日程と会場が読めないので作らなかった")
        return
    prefs = sp._rep_prefs(sections.get("各県代表", []))
    info = sp._load_rep_info()
    results = collect_results(sections)
    cells = [[x.strip() for x in _re.split(r"\s+vs\s+", ln.strip()[2:].strip()) if x.strip()] for ln in rows]
    drows = ss.draw_rows()
    same_row = {}
    for n, r in drows.items():
        same_row.setdefault(r, []).append(n)

    def name_of(side):
        kind, n = side
        if kind == "draw":
            r = drows[n]
            ns = sorted(same_row[r])
            return r, (cells[r][ns.index(n)] if len(cells[r]) == len(ns) else None)
        prev = sched[n]
        r = min(prev["rows"])
        if prev["round"] != "1回戦" and not prev["round"].startswith("開幕"):
            return r, None
        if len(cells[r]) != 2:
            return r, None
        return r, sp.first_round_winner(cells[r][0], cells[r][1], prefs, results) if hasattr(sp, "first_round_winner") else None

    caps, skipped = [], 0
    for mt in sorted(sched.values(), key=lambda m: m["no"]):
        if mt["round"] not in ("1回戦", "開幕戦（1回戦）", "2回戦"):
            continue
        sides = sorted((name_of(s) for s in mt["sides"]), key=lambda t: t[0])
        a, b = sides[0][1], sides[1][1]
        if not a or not b:
            skipped += 1
            continue
        pa, pb = prefs.get(a, ""), prefs.get(b, "")
        va = _taiketsu_values(a, pa, sp._official_note(info, sp.PREF_SLUG_BY_NAME.get(pa), a))
        vb = _taiketsu_values(b, pb, sp._official_note(info, sp.PREF_SLUG_BY_NAME.get(pb), b))
        rnd = "2回戦" if mt["round"] == "2回戦" else ("開幕戦" if mt["round"].startswith("開幕") else "1回戦")

        img, d = canvas()
        top = "第105回全国高校サッカー選手権"
        d.text((W // 2, SAFE_Y + 40), top, font=fit(d, top, TEXT_W, 38, 26, False), fill=GRAY, anchor="mm")
        sub = f"{rnd}【{mt['no']}】 {ss.when(mt)}"
        d.text((W // 2, SAFE_Y + 95), sub, font=fit(d, sub, TEXT_W, 40, 24), fill=WHITE, anchor="mm")
        # 校名（左右）と vs
        colw = (TEXT_W - 90) // 2
        lx, rx = SIDE + colw // 2, W - SIDE - colw // 2
        y_name = SAFE_Y + 190
        for x, nm, pf in ((lx, a, pa), (rx, b, pb)):
            s = _school_short(nm)
            d.text((x, y_name), s, font=fit(d, s, colw, 64, 30), fill=WHITE, anchor="mm")
            d.text((x, y_name + 62), f"（{pf}）", font=font(34, False), fill=GRAY, anchor="mm")
        d.text((W // 2, y_name + 10), "vs", font=font(40), fill=DIM, anchor="mm")
        y = y_name + 108
        d.line([(SIDE, y), (W - SIDE, y)], fill=GREEN, width=3)
        y += 14
        # 項目ごと：見出し（中央・薄い色）→ 左右の値
        for (label, la), (_, lb) in zip(va, vb):
            d.text((W // 2, y + 14), label, font=font(25, False), fill=DIM, anchor="mm")
            y += 32
            n = max(len(la), len(lb))
            for i in range(n):
                size = 34 if i == 0 else 27
                color = WHITE if i == 0 else GRAY
                if label == "プロ内定":  # 名前の並びは全部同じ扱い
                    size, color = 28, WHITE  # 偶数から始める（2pxずつ下げて最小18pxまで試すため）
                for x, vals in ((lx, la), (rx, lb)):
                    if i < len(vals):
                        s = vals[i]
                        d.text((x, y + size // 2), s, font=fit(d, s, colw, size, 18, i == 0), fill=color, anchor="mm")
                y += size + 6
            y += 7
            d.line([(SIDE + 40, y), (W - SIDE - 40, y)], fill=(0x33, 0x4a, 0x85), width=1)
            y += 8
        # [2026-11-17 第2段階] 直接対決（調べた組み合わせだけ）
        hh = mu.head_to_head(a, b)
        if hh:
            period, games = hh
            d.text((W // 2, y + 14), f"直接対決（{period}）", font=font(25, False), fill=DIM, anchor="mm")
            y += 32
            for g in (games or ["対戦なし"]):
                d.text((W // 2, y + 17), g, font=fit(d, g, TEXT_W, 30, 20), fill=WHITE, anchor="mm")
                y += 38
        if y > H - SAFE_Y - 120:
            raise SystemExit(f"対戦カード【{mt['no']}】が下にはみ出す（y={y}）")
        note = "所属リーグの順位は作成日時点。出典：u18-soccer.com の各データ"
        d.text((W // 2, H - SAFE_Y - 100), note, font=fit(d, note, TEXT_W, 24, 18, False), fill=DIM, anchor="mm")
        footer(d)
        save(img, out, f"senshuken-taiketsu-{mt['no']:02d}.png", made)

        # ---- 2枚目（人と履歴）[2026-11-18] ----
        pa2, pb2 = _taiketsu_page2(a, pa), _taiketsu_page2(b, pb)
        img, d = canvas()
        d.text((W // 2, SAFE_Y + 40), top, font=fit(d, top, TEXT_W, 38, 26, False), fill=GRAY, anchor="mm")
        d.text((W // 2, SAFE_Y + 95), sub, font=fit(d, sub, TEXT_W, 40, 24), fill=WHITE, anchor="mm")
        y_n = SAFE_Y + 175
        for x, nm in ((lx, a), (rx, b)):
            s_ = _school_short(nm)
            d.text((x, y_n), s_, font=fit(d, s_, colw, 50, 26), fill=WHITE, anchor="mm")
        d.text((W // 2, y_n), "vs", font=font(34), fill=DIM, anchor="mm")
        y = y_n + 50
        d.line([(SIDE, y), (W - SIDE, y)], fill=GREEN, width=3)
        y += 12
        for (label, la), (_, lb) in zip(pa2, pb2):
            d.text((W // 2, y + 14), label, font=font(24, False), fill=DIM, anchor="mm")
            y += 32
            for i in range(max(len(la), len(lb))):
                hstep = 0
                for x, vals in ((lx, la), (rx, lb)):
                    if i < len(vals):
                        t_, kind = vals[i]
                        size, color, bold = (30, WHITE, True) if kind == "b" else (22, GRAY, False)
                        d.text((x, y + size // 2), t_, font=fit(d, t_, colw, size, 14, bold), fill=color, anchor="mm")
                        hstep = max(hstep, size + 6)
                y += hstep
            y += 6
            d.line([(SIDE + 40, y), (W - SIDE - 40, y)], fill=(0x33, 0x4a, 0x85), width=1)
            y += 8
        if y > H - SAFE_Y - 120:
            raise SystemExit(f"対戦カード【{mt['no']}】の2枚目が下にはみ出す（y={y}）")
        note2 = "注目選手は各校のチームページから。前回大会はJFA公式。出典：u18-soccer.com"
        d.text((W // 2, H - SAFE_Y - 100), note2, font=fit(d, note2, TEXT_W, 24, 16, False), fill=DIM, anchor="mm")
        footer(d)
        save(img, out, f"senshuken-taiketsu-{mt['no']:02d}-2.png", made)
        sa, sb = _school_short(a), _school_short(b)
        caps.append(f"【{mt['no']}】{rnd} {ss.when(mt)}\n{sa}（{pa}）vs {sb}（{pb}）\n"
                    f"両校のデータを並べました。所属リーグ・県予選の勝ち上がり・インターハイの成績など。\n"
                    f"組み合わせと日程は u18-soccer.com の選手権特設ページで。\n"
                    f"#高校サッカー #選手権 #{sa} #{sb}\n")
    (out / "senshuken-taiketsu.txt").write_text("\n".join(caps), encoding="utf-8")
    made.append(out / "senshuken-taiketsu.txt")
    notes.append(f"対戦カード：{len(caps)}試合（相手が決まっていないので作らなかった2回戦 {skipped}）")


KINDS = {
    "senshuken-daihyo": make_daihyo,
    "senshuken-ichiran": make_ichiran,
    "premier": make_premier,
    "today-finals": make_today,
    "today-daihyo": make_today_daihyo,
    "senshuken-taiketsu": make_taiketsu,
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
