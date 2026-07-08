#!/usr/bin/env python3
"""
日本代表（U-16/U-17/U-18）選出選手 — 共有モジュール
=====================================================
このモジュールは2つのスクリプトから import して使う:
  1) generate_national_team_page.py … 専用ページ /national-team/ を生成
  2) generate_team_pages.py         … 各チーム詳細ページのヒーローに「代表選出バッジ」を差し込む

やっていること:
  - data/national-team-players.yml を読む
  - 各選手の「所属(JFA原文)」を、サイト内ページに対応付ける（3段階フォールバック）
        ① data/team-profiles/*.md にヒット → チーム詳細ページ /teams/{id}/ へ直リンク
        ② data/teams.json にヒット        → 県ページ /prefectures/{pref}/ へ
        ③ どちらにも無い                    → リンク無し（テキストのみ）
  - 名寄せ（表記ゆれ吸収）は手順書4-9 load_school_league_map と同じ思想。
    JFAはトップチーム名（例「アビスパ福岡」）で登録することがあるので、
    CLUB_ALIASES でサイトのU-18表記へ寄せる。

依存: pyyaml
"""

import json
import unicodedata
from html import escape as html_escape
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "national-team-players.yml"
PROFILES_DIR = BASE_DIR / "data" / "team-profiles"
TEAMS_JSON = BASE_DIR / "data" / "teams.json"

# JFAがトップチーム名や表記ゆれで登録するケースを、サイトの正式表記へ寄せる。
# 左=JFA原文（正規化後） 右=サイトのチーム名（team-profiles / teams.json 側の表記）
CLUB_ALIASES = {
    "鹿島アントラーズ": "鹿島アントラーズユース",
    "アビスパ福岡": "アビスパ福岡U-18",
    "FC東京": "FC東京U-18",
    "柏レイソル": "柏レイソルU-18",
    "浦和レッドダイヤモンズ": "浦和レッズユース",
    "浦和レッズ": "浦和レッズユース",
    "ヴィッセル神戸": "ヴィッセル神戸U-18",
    "サンフレッチェ広島": "サンフレッチェ広島F.Cユース",
    "サンフレッチェ広島FCユース": "サンフレッチェ広島F.Cユース",
    "ジュビロ磐田": "ジュビロ磐田U-18",
    "横浜F・マリノス": "横浜F・マリノスユース",
    "RB大宮アルディージャ": "RB大宮アルディージャU18",  # JFAはトップ名で登録→サイトのU18表記へ寄せる
    # 川崎フロンターレU-15生田 等の中学年代チームは意図的に寄せない（別チームのため③無リンク）
}


def _norm(s: str) -> str:
    """正規化: NFKC → 空白/中黒の揺れ吸収 → 前後空白除去"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    # 空白・ピリオド（F.C. / F.C / FC の揺れ）を除去して比較する
    s = s.replace(" ", "").replace("　", "").replace(".", "").replace("．", "").replace("。", "")
    return s.strip()


def _candidates(club: str):
    """1つの所属名から、照合に使う候補キーを複数生成する"""
    base = _norm(club)
    cands = {base}
    # トップ↔ユースの別名
    for k, v in CLUB_ALIASES.items():
        if _norm(k) == base:
            cands.add(_norm(v))
    # 「高」と「高校」の揺れ
    if base.endswith("高") and not base.endswith("高校"):
        cands.add(base + "校")
    if base.endswith("高校"):
        cands.add(base[:-1])  # 高校→高
    return cands


# ---------------------------------------------------------------------
# 索引づくり
# ---------------------------------------------------------------------

def build_profile_index(base_dir: Path = BASE_DIR) -> dict:
    """team-profiles/*.md を走査し {正規化名 → {id,name,pref,league}} を返す"""
    idx = {}
    pdir = base_dir / "data" / "team-profiles"
    if not pdir.exists():
        return idx
    for md in sorted(pdir.glob("*.md")):
        txt = md.read_text(encoding="utf-8")
        if not txt.startswith("---"):
            continue
        try:
            meta = yaml.safe_load(txt.split("---", 2)[1]) or {}
        except yaml.YAMLError:
            continue
        tid = meta.get("id")
        if not tid:
            continue
        entry = {
            "id": tid,
            "name": meta.get("name", ""),
            "pref": meta.get("prefecture", ""),
            "pref_name": meta.get("prefecture_name", ""),
            "league": meta.get("league", ""),
        }
        keys = [meta.get("name"), meta.get("short_name"), meta.get("nickname")]
        aliases = meta.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        keys += list(aliases)
        for k in keys:
            if k:
                for part in str(k).split("／"):
                    idx[_norm(part)] = entry
    return idx


def build_teams_index(base_dir: Path = BASE_DIR) -> dict:
    """teams.json を走査し {正規化名 → {pref,pref_name,league}} を返す（県ページ用）"""
    idx = {}
    tj = base_dir / "data" / "teams.json"
    if not tj.exists():
        return idx
    try:
        data = json.load(open(tj, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return idx
    for pref_id, pref in data.items():
        if not isinstance(pref, dict):
            continue
        pref_name = pref.get("name", "")
        lists = []
        if isinstance(pref.get("teams"), list):
            lists.append(pref["teams"])
        if isinstance(pref.get("division2"), list):
            lists.append(pref["division2"])
        for lst in lists:
            for t in lst:
                if not isinstance(t, dict):
                    continue
                entry = {"pref": pref_id, "pref_name": pref_name, "league": t.get("league", "")}
                keys = [t.get("name")]
                al = t.get("aliases") or []
                if isinstance(al, str):
                    al = [al]
                keys += list(al)
                for k in keys:
                    if k:
                        idx.setdefault(_norm(k), entry)
    return idx


# ---------------------------------------------------------------------
# 対応付け
# ---------------------------------------------------------------------

def resolve_club(club: str, profile_index: dict, teams_index: dict) -> dict:
    """所属名 → {tier, url, label, team_id?}
       tier: 'team'（詳細ページ）/ 'pref'（県ページ）/ None（リンク無し）"""
    for key in _candidates(club):
        if key in profile_index:
            e = profile_index[key]
            return {"tier": "team", "url": f"/teams/{e['id']}/", "team_id": e["id"], "label": e["name"]}
    for key in _candidates(club):
        if key in teams_index:
            e = teams_index[key]
            return {"tier": "pref", "url": f"/prefectures/{e['pref']}/", "label": e.get("pref_name", "")}
    return {"tier": None, "url": None, "label": ""}


# ---------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------

def load_categories(base_dir: Path = BASE_DIR) -> dict:
    """yml を読み、各選手に resolve 結果を付与して返す"""
    df = base_dir / "data" / "national-team-players.yml"
    if not df.exists():
        return {"updated": "", "categories": []}
    data = yaml.safe_load(df.read_text(encoding="utf-8")) or {}
    pidx = build_profile_index(base_dir)
    tidx = build_teams_index(base_dir)
    for cat in data.get("categories", []):
        for p in cat.get("players", []):
            # origin（出身U-18チーム）があればそれをリンク先にする。
            # これによりバッジも出身チーム側に付く（例: 増田大空→流経大柏、ジュビロ磐田U-18には付かない）
            link_name = p.get("origin") or p.get("club", "")
            p["_resolved"] = resolve_club(link_name, pidx, tidx)
    return data


# ---------------------------------------------------------------------
# チーム詳細ページ用バッジ
# ---------------------------------------------------------------------

def badges_by_team_id(base_dir: Path = BASE_DIR) -> dict:
    """{team_id: [ {cat_label, no, pos, name}... ]} を返す（チームページのバッジ用）"""
    data = load_categories(base_dir)
    out = {}
    for cat in data.get("categories", []):
        for p in cat.get("players", []):
            r = p.get("_resolved") or {}
            if r.get("tier") == "team":
                out.setdefault(r["team_id"], []).append(
                    {"cat": cat.get("label", ""), "no": p.get("no"), "pos": p.get("pos"), "name": p.get("name")}
                )
    return out


def render_team_badge_html(team_id: str, badge_map: dict) -> str:
    """チーム詳細ページのヒーロー直下に置く「代表選出選手」バッジHTML。
       該当が無ければ空文字（＝何も出ない）。"""
    players = badge_map.get(team_id)
    if not players:
        return ""
    # カテゴリごとにまとめる
    by_cat = {}
    for p in players:
        by_cat.setdefault(p["cat"], []).append(p)
    lines = []
    for cat, ps in by_cat.items():
        names = "、".join(f'{html_escape(p["name"])}（{html_escape(p["pos"])}）' for p in ps)
        lines.append(f'<strong>{html_escape(cat)}</strong>：{names}')
    inner = "<br>".join(lines)
    style = (
        "margin:0 0 14px;padding:12px 16px;background:rgba(255,255,255,0.95);"
        "color:#16264a;border-left:4px solid #d4af37;border-radius:0 8px 8px 0;"
        "font-size:0.92rem;line-height:1.8;"
    )
    return (
        f'      <p class="nt-badge" style="{style}">'
        f'<i class="fas fa-flag" style="color:#d4af37"></i> '
        f'<a href="/national-team/" style="color:#16264a;font-weight:700;text-decoration:underline">'
        f'日本代表選出選手</a>　{inner}</p>\n'
    )


if __name__ == "__main__":
    # 単体テスト: 対応付け結果を一覧表示（repoルートで実行）
    data = load_categories()
    print(f"updated: {data.get('updated')}")
    for cat in data.get("categories", []):
        print(f"\n=== {cat['label']} ({cat.get('event')}) ===")
        for p in cat.get("players", []):
            r = p["_resolved"]
            tier = r["tier"] or "—(無リンク)"
            print(f"  {p['pos']:<2} {p['name']:<16} {p['club']:<28} → {tier} {r['url'] or ''}")
