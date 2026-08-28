#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大学リーグ順位表の自動更新（GitHub Actions 用・2026-08-28 新設）

data/university/leagues-2026.json を各連盟の公式ページから更新し、
scraper/generate_university_page.py を呼んで /university/ に反映する。

安全設計（update_cross_tables.py と同じ思想）:
- リーグごとに独立して取得・検証。1つでも検算に失敗したリーグは【据え置き】（既存データを残す）。
- 取得したチーム名の集合が既存JSONのチーム名集合と一致しないリーグも【据え置き】
  （名寄せ失敗や別リーグの表を誤って掴んだ場合に誤データを載せないため）。
- 北海道（星取表PDF）・四国（星取表ページ）は自動化の対象外＝常に据え置き（手動更新）。

出典タイプ:
- fss    : football-system.jp の順位表（関東1-3部・中国1-2部・九州1-3部）
- table  : HTMLの順位表テーブル（東北=JFA公式 / 北信越=hufl.info / 東海=連盟WP）
- kansai : 関西学連の結果速報ページの全試合スコアから順位を自前計算（1〜3部）
"""
import json
import re
import subprocess
import sys
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "university" / "leagues-2026.json"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 (u18-soccer.com standings bot)"}
TIMEOUT = 30

# チーム名の読み替え（出典表記 → JSON正式名）。リーグ別。
ALIASES = {
    "hokushinetsu-1": {"医療福祉大学": "新潟医療福祉大学", "医福大": "新潟医療福祉大学",
                       "学院大": "金沢学院大学", "新経大": "新潟経営大学", "新産大": "新潟産業大学",
                       "松本大": "松本大学", "北陸大": "北陸大学", "新潟大": "新潟大学", "金沢大": "金沢大学"},
    "hokushinetsu-2": {"星稜大": "金沢星稜大学", "金沢星稜大": "金沢星稜大学", "福工大": "福井工業大学",
                       "信州大": "信州大学", "富山大": "富山大学", "福井大": "福井大学",
                       "上教大": "上越教育大学", "金工大": "金沢工業大学", "富国大": "富山国際大学",
                       "福県大": "福井県立大学"},
    "tokai-2": {"常葉大学静岡": "常葉大学静岡キャンパス"},
    "kyushu-2": {"東海大学（熊本）": "東海大学熊本"},
}

KANSAI_NAMES = {
    "関学大": "関西学院大学", "阪南大": "阪南大学", "甲南大": "甲南大学", "京産大": "京都産業大学",
    "びわこ大": "びわこ成蹊スポーツ大学", "大商大": "大阪商業大学", "大院大": "大阪学院大学",
    "立命大": "立命館大学", "関西大": "関西大学", "同大": "同志社大学", "桃山大": "桃山学院大学",
    "大体大": "大阪体育大学",
    "京都橘大": "京都橘大学", "京都先端大": "京都先端科学大学", "大経大": "大阪経済大学",
    "大国大": "大阪国際大学", "龍谷大": "龍谷大学", "追大": "追手門学院大学", "大産大": "大阪産業大学",
    "関国大": "関西国際大学", "関福大": "関西福祉大学", "大阪大": "大阪大学", "近畿大": "近畿大学",
    "神院大": "神戸学院大学",
    "大教大": "大阪教育大学", "神国大": "神戸国際大学", "大阪信愛大": "大阪信愛学院大学",
    "神戸大": "神戸大学", "天理大": "天理大学", "関外大": "関西外国語大学", "大阪公立大": "大阪公立大学",
    "京都大": "京都大学", "芦屋大": "芦屋大学", "姫獨大": "姫路獨協大学", "流科大": "流通科学大学",
    "摂南大": "摂南大学",
}

SOURCES = {
    # football-system（lidは連盟サイト掲載の公開URL）
    "kanto-1": ("fss", "https://football-system.jp/fss/pub_teamlank.php?lid=QyXUlC6jQ18="),
    "kanto-2": ("fss", "https://football-system.jp/fss/pub_teamlank.php?lid=rRCQ+uLEvXk="),
    "kanto-3": ("fss", "https://football-system.jp/fss/pub_teamlank.php?lid=0RN09Z2KpN4="),
    "chugoku-1": ("fss", "https://football-system.jp/fss/pub_teamlank.php?lid=UTPVepwV6sw="),
    "chugoku-2": ("fss", "https://football-system.jp/fss/pub_teamlank.php?lid=XIi6FZyy0FQ="),
    "kyushu-1": ("fss", "https://football-system.jp/fss/pub_teamlank.php?lid=aghSuzApo8I="),
    "kyushu-2": ("fss", "https://football-system.jp/fss/pub_teamlank.php?lid=Yv37O48k9Q0="),
    "kyushu-3": ("fss", "https://football-system.jp/fss/pub_teamlank.php?lid=2feoxwgGnk4="),
    # HTMLテーブル
    "tohoku-1": ("table", "https://www.jfa.jp/match_47fa/102_tohoku/2026_university/div1/thfa/ranking.html"),
    "tohoku-2": ("table", "https://www.jfa.jp/match_47fa/102_tohoku/2026_university/div2/thfa/ranking.html"),
    "hokushinetsu-1": ("table", "https://hufl.info/league/"),
    "hokushinetsu-2": ("table", "https://hufl.info/league/"),
    "tokai-1": ("table", "http://jufa.tokai-soccer.gr.jp/?page_id=26371"),
    "tokai-2": ("table", "http://jufa.tokai-soccer.gr.jp/?page_id=26433"),
    # 関西＝全試合スコアから自前計算
    "kansai-1": ("kansai", "https://www.jufa-kansai.jp/taikai/result_26nit_zen-1-1/"),
    "kansai-2": ("kansai", "https://www.jufa-kansai.jp/taikai/result_26nit_zen-2-1/"),
    "kansai-3": ("kansai", "https://www.jufa-kansai.jp/taikai/result_26nit_zen-3-1/"),
    # hokkaido-1 / shikoku-1 / shikoku-2 は手動更新（PDF・画像のため対象外）
}

# 後期ページのURL（存在すれば前期分と合算する。404なら前期のみで計算）
KANSAI_KOUKI = {
    "kansai-1": "https://www.jufa-kansai.jp/taikai/result_26nit_kou-1-1/",
    "kansai-2": "https://www.jufa-kansai.jp/taikai/result_26nit_kou-2-1/",
    "kansai-3": "https://www.jufa-kansai.jp/taikai/result_26nit_kou-3-1/",
}


def today_asof():
    d = date.today()
    return f"{d.month}月{d.day}日 自動更新"


def get(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def norm_header(h):
    return re.sub(r"\s", "", str(h))


def map_columns(cols):
    """ヘッダー名から (rank,name,p,g,w,d,l,gf,ga) の列位置を推定。見つからなければ None"""
    idx = {}
    for i, c in enumerate(cols):
        h = norm_header(c)
        if ("順位" in h or h == "順") and "rank" not in idx: idx["rank"] = i
        elif ("チーム" in h or "大学名" in h) and "name" not in idx: idx["name"] = i
        elif ("勝点" in h or "勝ち点" in h) and "p" not in idx: idx["p"] = i
        elif "試合" in h and "g" not in idx: idx["g"] = i
        elif h in ("勝", "勝数", "勝利") and "w" not in idx: idx["w"] = i
        elif h in ("分", "引分", "分数", "引き分け") and "d" not in idx: idx["d"] = i
        elif h in ("負", "敗", "負数", "敗数", "敗戦") and "l" not in idx: idx["l"] = i
        elif (("得点" in h and "失" not in h and "差" not in h) or h == "得") and "gf" not in idx: idx["gf"] = i
        elif (("失点" in h and "差" not in h) or h == "失") and "ga" not in idx: idx["ga"] = i
    need = ["p", "w", "d", "l", "gf", "ga"]
    if all(k in idx for k in need):
        # チーム名列のヘッダーが空のサイト（北信越hufl等）は先頭列をチーム名とみなす
        if "name" not in idx:
            idx["name"] = 0
        return idx
    return None


def to_int(v):
    m = re.search(r"-?\d+", str(v))
    return int(m.group(0)) if m else None


def parse_standings_tables(html_text):
    """ページ内の全テーブルから順位表らしきものを全部抽出して返す"""
    out = []
    try:
        dfs = pd.read_html(StringIO(html_text))
    except ValueError:
        return out
    for df in dfs:
        # ヘッダーが1行目に入っているケースも試す
        for candidate in (df, df.rename(columns=df.iloc[0]).iloc[1:] if len(df) > 1 else df):
            idx = map_columns(list(candidate.columns))
            if not idx:
                continue
            rows = []
            for _, r in candidate.iterrows():
                vals = list(r.values)
                name = str(vals[idx["name"]]).strip()
                nums = {k: to_int(vals[idx[k]]) for k in ("p", "w", "d", "l", "gf", "ga")}
                if not name or name == "nan" or None in nums.values():
                    continue
                g = to_int(vals[idx["g"]]) if "g" in idx else None
                rank = to_int(vals[idx["rank"]]) if "rank" in idx else None
                rows.append(dict(name=name, rank=rank, g=g, **nums))
            if len(rows) >= 4:
                out.append(rows)
            break
    return out


def parse_kansai_matches(html_text):
    """関西の結果速報ページから (略称, 得点, 得点, 略称) を抽出"""
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = re.sub(r"\s+", " ", text)
    pat = re.compile(r"([\w぀-ヿ一-鿿び]+?大)\s*(\d+)\s*\(\d+\s*[-−]\s*\d+\)\s*(\d+)\s*([\w぀-ヿ一-鿿び]+?大)")
    out = []
    for m in pat.finditer(text):
        out.append((m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)))
    return out


def kansai_shortname(token):
    """抽出トークンをKANSAI_NAMESのキーに正規化（最長一致）"""
    for key in sorted(KANSAI_NAMES, key=len, reverse=True):
        if token.endswith(key):
            return key
    return None


def compute_from_matches(pairs):
    stats = {}
    for h, hs, as_, a in pairs:
        hk, ak = kansai_shortname(h), kansai_shortname(a)
        if not hk or not ak or hk == ak:
            raise ValueError(f"チーム名を解決できない試合: {h} {hs}-{as_} {a}")
        for t in (hk, ak):
            stats.setdefault(t, dict(w=0, d=0, l=0, gf=0, ga=0))
        stats[hk]["gf"] += hs; stats[hk]["ga"] += as_
        stats[ak]["gf"] += as_; stats[ak]["ga"] += hs
        if hs > as_: stats[hk]["w"] += 1; stats[ak]["l"] += 1
        elif hs < as_: stats[ak]["w"] += 1; stats[hk]["l"] += 1
        else: stats[hk]["d"] += 1; stats[ak]["d"] += 1
    rows = []
    for t, s in stats.items():
        rows.append(dict(name=KANSAI_NAMES[t], p=s["w"] * 3 + s["d"], g=s["w"] + s["d"] + s["l"],
                         w=s["w"], d=s["d"], l=s["l"], gf=s["gf"], ga=s["ga"], gd=s["gf"] - s["ga"]))
    rows.sort(key=lambda r: (-r["p"], -r["gd"], -r["gf"], r["name"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def finalize_rows(rows, league_id):
    """名寄せ・g補完・gd計算・順位補完をして teams 形式にする"""
    al = ALIASES.get(league_id, {})
    for r in rows:
        # JFA東北の「八戸学院大学(青森県)」のような都道府県サフィックスを除去
        r["name"] = re.sub(r"[（(][^（()）]{2,5}[都道府県][)）]$", "", r["name"]).strip()
        r["name"] = al.get(r["name"], r["name"])
        if r.get("g") is None or r["g"] != r["w"] + r["d"] + r["l"]:
            if r.get("g") is not None:
                print(f"  [注記] {league_id} {r['name']}: 試合数{r['g']}を勝敗内訳から{r['w']+r['d']+r['l']}に補正")
            r["g"] = r["w"] + r["d"] + r["l"]
        r["gd"] = r["gf"] - r["ga"]
    if any(r.get("rank") is None for r in rows):
        rows.sort(key=lambda r: (-r["p"], -r["gd"], -r["gf"], r["name"]))
        for i, r in enumerate(rows):
            r["rank"] = i + 1
    rows.sort(key=lambda r: r["rank"])
    return [dict(name=r["name"], p=r["p"], g=r["g"], w=r["w"], d=r["d"], l=r["l"],
                 gf=r["gf"], ga=r["ga"], gd=r["gd"], rank=r["rank"]) for r in rows]


def validate(teams):
    errs = []
    for t in teams:
        if t["p"] != t["w"] * 3 + t["d"]: errs.append(f"勝点不一致 {t['name']}")
        if t["g"] != t["w"] + t["d"] + t["l"]: errs.append(f"試合数不一致 {t['name']}")
    pts = [t["p"] for t in teams]
    for i in range(len(pts) - 1):
        if pts[i] < pts[i + 1]: errs.append("勝点が順位順で増加")
    if sum(t["gf"] for t in teams) != sum(t["ga"] for t in teams): errs.append("得点合計≠失点合計")
    if sum(t["w"] for t in teams) != sum(t["l"] for t in teams): errs.append("勝数合計≠敗数合計")
    if sum(t["d"] for t in teams) % 2: errs.append("引分合計が奇数")
    if sum(t["g"] for t in teams) % 2: errs.append("総試合数が奇数")
    return errs


def pick_table_for_league(tables, expected_names, league_id):
    """抽出した複数テーブルから、既存チーム集合と一致するものを選ぶ"""
    for rows in tables:
        teams = finalize_rows([dict(r) for r in rows], league_id)
        if {t["name"] for t in teams} == expected_names:
            return teams
    return None


def fss_asof(html_text):
    m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})\s*現在", html_text)
    if m:
        return f"{int(m.group(2))}月{int(m.group(3))}日現在（公式記録）"
    return today_asof()


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    updated, skipped = [], []
    for lg in data["leagues"]:
        lid = lg["id"]
        if lid not in SOURCES:
            skipped.append(f"{lid}(手動)")
            continue
        typ, url = SOURCES[lid]
        expected = {t["name"] for t in lg["teams"]}
        try:
            if typ == "kansai":
                pairs = parse_kansai_matches(get(url))
                kouki_url = KANSAI_KOUKI.get(lid)
                if kouki_url:
                    try:
                        pairs += parse_kansai_matches(get(kouki_url))
                    except Exception:
                        pass  # 後期ページ未公開なら前期のみ
                if not pairs:
                    raise ValueError("試合が1件も取れない")
                teams = finalize_rows(compute_from_matches(pairs), lid)
                asof = f"{today_asof()}（全{len(pairs)}試合から算出）"
            else:
                html_text = get(url)
                tables = parse_standings_tables(html_text)
                teams = pick_table_for_league(tables, expected, lid)
                if teams is None:
                    raise ValueError(f"既存チーム集合と一致する順位表が見つからない（抽出テーブル{len(tables)}件）")
                asof = fss_asof(html_text) if typ == "fss" else today_asof()
            errs = validate(teams)
            if errs:
                raise ValueError("検算NG: " + "; ".join(errs))
            if {t["name"] for t in teams} != expected:
                raise ValueError("チーム集合が既存データと不一致")
            lg["teams"] = teams
            lg["asof"] = asof
            updated.append(lid)
            print(f"OK  {lid}: 更新（{len(teams)}チーム / {asof}）")
        except Exception as e:
            skipped.append(lid)
            print(f"[要確認] {lid}: 据え置き → {e}")
    data["updated"] = date.today().isoformat()
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n更新 {len(updated)} / 据え置き {len(skipped)}: {', '.join(skipped)}")
    # ページ再生成
    subprocess.run([sys.executable, str(ROOT / "scraper" / "generate_university_page.py")], check=True)


if __name__ == "__main__":
    main()
