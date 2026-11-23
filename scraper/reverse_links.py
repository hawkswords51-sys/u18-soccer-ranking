#!/usr/bin/env python3
"""
【試作】チームページへの逆リンク自動生成

チームページ（teams/{id}/）の本文末尾（関連リンクの直前）に、
データから自動生成する2種類の導線を差し込むためのモジュール。

  1. 卒業生のプロ内定（大学経由）
     data/university/pro-signings-{2027,2028,2029}.json の各選手の
     U18出身校（u18 フィールド）がこのチームに一致するものを一覧にし、
     大卒プロ内定一覧ページへのリンクを付ける。
     （従来は内定ページ→チームページの一方向リンクしかなかった）
  2. U-16ルーキーリーグ
     data/u16/leagues-2026.json の出場チームにこのチームが含まれれば、
     /u16/ へのリンクを付ける。

学校名の照合は generate_university_signings.py の load_team_links /
team_link と同じ方式（frontmatter の name / aliases / short_name を
norm_team で正規化し、「高校」の付け外しフォールバックあり）。

該当データが無いチームでは空文字を返すので、ページは1バイトも変わらない
（team_season.py / team_history.py と同じ流儀）。
"""

import json
import re
from html import escape as esc
from pathlib import Path

_CACHE = None

SIGNING_YEARS = (2029, 2028, 2027)  # 新しい年度から表示


def _norm(s):
    """generate_university_signings.norm_team と同一の正規化"""
    s = re.sub(r"\s", "", s or "")
    return s.replace("高等学校", "高校").replace("髙", "高")


def _name_to_slug(base_dir):
    """team-profiles の frontmatter name/aliases/short_name → slug の対応表"""
    links = {}
    profiles = base_dir / "data" / "team-profiles"
    if not profiles.is_dir():
        return links
    for md in sorted(profiles.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not m:
            continue
        fm = m.group(1)
        names = []
        for key in ("name", "short_name"):
            nm = re.search(rf"^{key}:\s*[\"']?([^\"'\n]+)", fm, re.M)
            if nm:
                names.append(nm.group(1).strip())
        am = re.search(r"^aliases:\s*\n((?:\s*-\s*.+\n?)+)", fm, re.M)
        if am:
            names += [re.sub(r"^\s*-\s*", "", ln).strip().strip("\"'")
                      for ln in am.group(1).strip().splitlines()]
        for n in names:
            if n:
                links[_norm(n)] = md.stem
    return links


def _build(base_dir):
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    slug_by_name = _name_to_slug(base_dir)

    def resolve(name):
        """generate_university_signings.team_link と同じフォールバックで slug を引く"""
        key = _norm(name)
        if not key:
            return None
        slug = slug_by_name.get(key)
        if not slug and not key.endswith("高校"):
            slug = slug_by_name.get(key + "高校")
        if not slug and key.endswith("高校"):
            slug = slug_by_name.get(key[:-2])
        return slug

    # slug -> {年度: [選手,...]}
    signings = {}
    for year in SIGNING_YEARS:
        p = base_dir / "data" / "university" / f"pro-signings-{year}.json"
        if not p.exists():
            continue
        try:
            players = json.loads(p.read_text(encoding="utf-8")).get("players", [])
        except Exception:
            continue
        for pl in players:
            slug = resolve(pl.get("u18", ""))
            if slug:
                signings.setdefault(slug, {}).setdefault(year, []).append(pl)

    # slug -> [ディビジョン名,...]（重複なし・登場順）
    u16 = {}
    p = base_dir / "data" / "u16" / "leagues-2026.json"
    if p.exists():
        try:
            divisions = json.loads(p.read_text(encoding="utf-8")).get("divisions", [])
        except Exception:
            divisions = []
        for div in divisions:
            for t in div.get("teams", []):
                slug = resolve(t.get("name", ""))
                if slug:
                    lst = u16.setdefault(slug, [])
                    if div.get("name") and div["name"] not in lst:
                        lst.append(div["name"])

    _CACHE = (signings, u16)
    return _CACHE


def render_reverse_links_html(meta, base_dir):
    """チームページ本文の末尾（関連リンクの直前）に差し込む HTML。
    該当が無ければ空文字。"""
    signings, u16 = _build(base_dir)
    slug = meta.get("id", "")
    if not slug:
        return ""
    parts = []

    by_year = signings.get(slug)
    if by_year:
        parts.append("<h2>卒業生のプロ内定（大学経由）</h2>\n")
        parts.append(
            f"<p>{esc(meta.get('name', ''))}の卒業生で、大学を経てプロ入りが"
            "内定した選手です（当サイトの大卒プロ内定一覧より）。</p>\n"
        )
        parts.append("<ul>\n")
        for year in SIGNING_YEARS:
            for pl in by_year.get(year, []):
                parts.append(
                    f"<li>{esc(pl.get('name', ''))}"
                    f"（{esc(pl.get('univ', ''))} → {esc(pl.get('club', ''))}、"
                    f"{year}年加入）</li>\n"
                )
        parts.append("</ul>\n")
        for year in SIGNING_YEARS:
            if by_year.get(year):
                parts.append(
                    f'<p>→ <a href="/university/pro-signings-{year}/">'
                    f"大卒プロ内定一覧（{year}年加入）</a></p>\n"
                )

    divs = u16.get(slug)
    if divs:
        div_text = "、".join(divs)
        parts.append("<h2>U-16ルーキーリーグ</h2>\n")
        parts.append(
            f"<p>{esc(meta.get('short_name') or meta.get('name', ''))}は、"
            f"高校1年生年代のU-16ルーキーリーグ2026（{esc(div_text)}）に"
            "出場しています。</p>\n"
        )
        parts.append(
            '<p>→ <a href="/u16/">U-16ルーキーリーグ2026 順位表</a></p>\n'
        )

    return "".join(parts)
