#!/usr/bin/env python3
"""
プロ内定・2種登録選手 — 共有モジュール
=====================================================
日本代表ページ（national_team.py）と同じ思想で、選手の「現所属チーム」を
サイト内ページに対応付ける（3段階フォールバック）。対応付けロジックは
national_team.py を import して再利用する（名寄せ表 CLUB_ALIASES も共用）。

使い方（2スクリプトから import）:
  1) generate_pro_signings_page.py … 専用ページ /pro-signings/ を生成
  2) generate_team_pages.py         … 各チーム詳細ページのヒーローに「プロ内定/2種登録」バッジを差し込む

対応付け（national_team.resolve_club と同じ）:
  ① data/team-profiles/*.md にヒット → チーム詳細ページ /teams/{id}/ へ直リンク
  ② data/teams.json にヒット        → 県ページ /prefectures/{pref}/ へ
  ③ どちらにも無い                    → リンク無し（テキストのみ）

依存: pyyaml, 同ディレクトリの national_team.py
"""

from html import escape as html_escape
from pathlib import Path

import yaml

import national_team as nt  # 対応付け・名寄せ（CLUB_ALIASES）を共用

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "pro-signings.yml"


def load_signings(base_dir: Path = BASE_DIR) -> dict:
    """pro-signings.yml を読み、各選手に「現所属チーム」の対応付け結果を付与して返す。
       返り値: {updated, season, source_hub, source_asof,
                signings:[...], second_category:[...]}（各選手に _resolved 追加）"""
    df = base_dir / "data" / "pro-signings.yml"
    if not df.exists():
        return {"signings": [], "second_category": []}
    data = yaml.safe_load(df.read_text(encoding="utf-8")) or {}

    # 対応付け用の索引は national_team のものをそのまま使う（team-profiles / teams.json）
    pidx = nt.build_profile_index(base_dir)
    tidx = nt.build_teams_index(base_dir)

    for key in ("signings", "second_category"):
        for p in data.get(key) or []:
            p["_resolved"] = nt.resolve_club(p.get("team", ""), pidx, tidx)
    return data


def group_by_team(players: list) -> list:
    """選手リストを「現所属チーム」ごとにまとめる（出現順を保持）。
       返り値: [ {team, resolved, players:[...]} , ... ]"""
    order = []
    groups = {}
    for p in players or []:
        team = p.get("team", "")
        if team not in groups:
            groups[team] = {"team": team, "resolved": p.get("_resolved") or {}, "players": []}
            order.append(team)
        groups[team]["players"].append(p)
    return [groups[t] for t in order]


# ---------------------------------------------------------------------
# チーム詳細ページ用バッジ
# ---------------------------------------------------------------------

def badges_by_team_id(base_dir: Path = BASE_DIR) -> dict:
    """{team_id: {"naitei":[...], "pro":[...]}} を返す（チームページのバッジ用）。
       team詳細ページに直リンクできる（tier=team）選手だけを対象にする。
       status で「これから加入する内定者」と「すでにプロ契約済み」を分ける。"""
    data = load_signings(base_dir)
    out = {}
    for p in data.get("signings") or []:
        r = p.get("_resolved") or {}
        if r.get("tier") != "team":
            continue
        kind = "pro" if p.get("status") == "pro" else "naitei"
        out.setdefault(r["team_id"], {"naitei": [], "pro": []})
        out[r["team_id"]][kind].append(
            {"name": p.get("name"), "pos": p.get("pos"), "dest": p.get("dest"),
             "timing": p.get("timing"), "type2": bool(p.get("type2"))}
        )
    return out


def render_team_badge_html(team_id: str, badge_map: dict) -> str:
    """チーム詳細ページのヒーロー直下に置く「プロ内定/プロ契約」バッジHTML（緑）。
       該当が無ければ空文字（＝何も出ない）。日本代表バッジ（金）と併存可。"""
    entry = badge_map.get(team_id)
    if not entry:
        return ""

    def _names(players, with_dest=True):
        parts = []
        for p in players:
            tag = "・2種登録" if p.get("type2") else ""
            when = f'／{html_escape(str(p["timing"]))}' if p.get("timing") else ""
            dest = f'→{html_escape(p["dest"])}' if (with_dest and p.get("dest")) else ""
            parts.append(f'{html_escape(p["name"])}（{html_escape(p["pos"])}{dest}{when}{tag}）')
        return "、".join(parts)

    lines = []
    if entry.get("naitei"):
        lines.append(f'<strong>プロ内定</strong>：{_names(entry["naitei"])}')
    if entry.get("pro"):
        lines.append(f'<strong>プロ契約済み</strong>：{_names(entry["pro"])}')
    inner = "<br>".join(lines)
    style = (
        "margin:0 0 14px;padding:12px 16px;background:rgba(255,255,255,0.95);"
        "color:#14532d;border-left:4px solid #16a34a;border-radius:0 8px 8px 0;"
        "font-size:0.92rem;line-height:1.8;"
    )
    return (
        f'      <p class="ps-badge" style="{style}">'
        f'<i class="fas fa-star" style="color:#16a34a"></i> '
        f'<a href="/pro-signings/" style="color:#14532d;font-weight:700;text-decoration:underline">'
        f'プロ内定・プロ契約</a>　{inner}</p>\n'
    )


if __name__ == "__main__":
    # 単体テスト: 対応付け結果を一覧表示（repoルートで実行）
    data = load_signings()
    print(f"updated: {data.get('updated')} / season: {data.get('season')}")
    for st, title in (("naitei", "① これから加入する内定者"), ("pro", "② すでにプロ契約済み")):
        rows = [p for p in (data.get("signings") or [])
                if (p.get("status") == "pro") == (st == "pro")]
        print(f"\n=== {title}（{len(rows)}名） ===")
        for p in rows:
            r = p["_resolved"]
            tier = r["tier"] or "—(無リンク)"
            dest = f'→{p.get("dest")}' if p.get("dest") else ""
            when = p.get("timing") or ""
            print(f"  {p['pos']:<2} {p['name']:<16} [{p['team']:<24}] {dest:<16} {when:<16} → {tier} {r['url'] or ''}")
