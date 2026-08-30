#!/usr/bin/env python3
"""順位表の「昇格圏・降格圏」色分け（data/league_zones.yml 駆動）

使い方（generate_league_pages.py / generate_prefecture_pages.py から）:

    from league_zones import resolve_zones, zone_row_attrs, render_zone_legend_html

    zmap = resolve_zones("premier-east", sorted_teams)   # {順位: zone dict}
    ...
    <tr{zone_row_attrs(zmap.get(rank))}>
    ...
    legend_html = render_zone_legend_html("premier-east", zmap)

安全設計:
  - yml に無いリーグ、zone を書いていないリーグは **空の結果** を返す
    （＝既存ページの見た目は一切変わらない）。
  - yml が壊れている／PyYAML が無い場合も例外を投げず空を返す。

単体テスト:
    python scraper/league_zones.py premier-east
"""
from pathlib import Path
import re

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ZONES_PATH = Path(__file__).parent.parent / "data" / "league_zones.yml"

# type -> (凡例に出す既定ラベル, CSSクラスのサフィックス)
ZONE_TYPES = {
    "final": "final",
    "promotion": "promotion",
    "playoff": "playoff",
    "relegation_playoff": "relegation-playoff",
    "relegation": "relegation",
}

# 凡例の並び順（上位→下位）
TYPE_ORDER = ["final", "promotion", "playoff", "relegation_playoff", "relegation"]

# セカンドチーム判定（"◯◯2nd" / "◯◯3rd" / "◯◯B"）
_SECOND_RE = re.compile(r"(?:[ 　_]*(?:2nd|3rd|セカンド)|\(B\)|（B）)\s*$", re.IGNORECASE)


def _load():
    if yaml is None or not ZONES_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(ZONES_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:  # pragma: no cover
        print(f"[warn] league_zones.yml を読めませんでした: {e}")
        return {}
    return data if isinstance(data, dict) else {}


_DATA = _load()
META = _DATA.get("_meta", {}) or {}
_LEAGUES = _DATA.get("leagues", {}) or {}


def is_second_team(name):
    """チーム名がセカンド／サードチームか"""
    return bool(_SECOND_RE.search(name or ""))


def _base_team_name(name):
    return _SECOND_RE.sub("", name or "").strip()


def _premier_team_names(all_teams):
    """プレミアリーグ所属チーム名の集合（参入戦の除外判定用）"""
    out = set()
    for t in all_teams or []:
        lg = (t.get("league") or "")
        if "プレミア" in lg:
            out.add((t.get("name") or "").strip())
    return out


def resolve_zones(slug, sorted_teams, all_teams=None):
    """順位 -> zone(dict) の対応を返す。

    slug         : "premier-east" 等。yml の leagues キー
    sorted_teams : 順位順に並んだチームdictのリスト（1位が先頭）
    all_teams    : teams.json 全チーム（セカンドチーム除外の判定に使う。省略可）

    戻り値: {rank(int): {"type","label","confidence","cls"}}
    """
    cfg = _LEAGUES.get(slug)
    if not cfg:
        return {}
    zones = cfg.get("zones") or []
    n = len(sorted_teams)
    if n == 0:
        return {}

    premier_names = _premier_team_names(all_teams) if all_teams else None
    result = {}

    def _ineligible_for_playoff(team):
        """プレミア所属チームのセカンドチームは参入戦に出られない"""
        name = (team.get("name") or "").strip()
        if not is_second_team(name):
            return False
        if premier_names is None:
            # teams.json を渡されなかった場合は、セカンドチーム全般を除外扱いにしない
            return False
        return _base_team_name(name) in premier_names

    for z in zones:
        ztype = z.get("type")
        if ztype not in ZONE_TYPES:
            continue
        entry = {
            "type": ztype,
            "label": z.get("label") or "",
            "confidence": z.get("confidence") or "standard",
            "cls": ZONE_TYPES[ztype],
            "skip": bool(z.get("skipSecondTeams")),
        }
        ranks = z.get("ranks")
        if ranks:
            for r in ranks:
                if isinstance(r, int) and 1 <= r <= n:
                    result.setdefault(r, entry)
            continue

        slots = z.get("slots")
        if not isinstance(slots, int) or slots <= 0:
            continue
        from_ = (z.get("from") or "top").lower()
        skip_second = bool(z.get("skipSecondTeams"))
        order = range(1, n + 1) if from_ == "top" else range(n, 0, -1)
        filled = 0
        for r in order:
            if filled >= slots:
                break
            team = sorted_teams[r - 1]
            if skip_second and _ineligible_for_playoff(team):
                continue  # 枠は次順位へ繰り下がる
            result.setdefault(r, entry)
            filled += 1

    return result


def zone_row_attrs(zone):
    """<tr> に付ける属性文字列（先頭にスペース1つ）。zone が None なら空文字。"""
    if not zone:
        return ""
    label = zone.get("label") or ""
    return f' class="zone-row zone-{zone["cls"]}" data-zone-label="{_esc(label)}"'


def zone_marker_html(zone):
    """順位セルの中に置く小さなマーカー（スクリーンリーダー用のテキスト付き）"""
    if not zone:
        return ""
    return f'<span class="zone-dot zone-dot-{zone["cls"]}" aria-hidden="true"></span>'


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_zone_legend_html(slug, zmap):
    """順位表の下に出す凡例。zmap が空なら空文字（＝何も出ない）。"""
    if not zmap:
        return ""
    cfg = _LEAGUES.get(slug) or {}

    # type ごとに1件へまとめ、順位範囲を添える
    by_type = {}
    for rank, z in zmap.items():
        key = (z["type"], z["label"])
        by_type.setdefault(key, {"zone": z, "ranks": []})
        by_type[key]["ranks"].append(rank)

    items = []
    has_standard = False
    has_playoff = False
    for key in sorted(by_type, key=lambda k: (TYPE_ORDER.index(k[0]) if k[0] in TYPE_ORDER else 99, k[1])):
        info = by_type[key]
        z = info["zone"]
        ranks = sorted(info["ranks"])
        rng = _format_ranks(ranks)
        star = ""
        if z.get("confidence") == "standard":
            has_standard = True
            star = '<span class="zone-legend__star">※</span>'
        if z.get("skip"):
            has_playoff = True
        items.append(
            f'<li class="zone-legend__item">'
            f'<span class="zone-legend__swatch zone-{z["cls"]}"></span>'
            f'<span class="zone-legend__rank">{rng}</span>'
            f'<span class="zone-legend__label">{_esc(z["label"])}{star}</span>'
            f'</li>'
        )

    notes = []
    if has_playoff and META.get("playoff_note"):
        notes.append(_esc(META["playoff_note"]))
    if has_standard:
        note_txt = cfg.get("note") or META.get("relegation_note")
        if note_txt:
            notes.append("※ " + _esc(note_txt))
    src = cfg.get("source")
    src_url = cfg.get("sourceUrl")
    if src:
        if src_url:
            notes.append(
                f'出典：<a href="{_esc(src_url)}" target="_blank" rel="noopener noreferrer">'
                f'{_esc(src)}</a>'
            )
        else:
            notes.append("出典：" + _esc(src))

    notes_html = "".join(f'<p class="zone-legend__note">{t}</p>' for t in notes)
    return (
        '      <div class="zone-legend">\n'
        '        <ul class="zone-legend__list">' + "".join(items) + '</ul>\n'
        f'        {notes_html}\n'
        '      </div>\n'
    )


def _format_ranks(ranks):
    """[1] -> '1位' / [11,12] -> '11-12位' / [1,3,5] -> '1・3・5位'"""
    if not ranks:
        return ""
    if len(ranks) == 1:
        return f"{ranks[0]}位"
    if ranks == list(range(ranks[0], ranks[-1] + 1)):
        return f"{ranks[0]}-{ranks[-1]}位"
    return "・".join(str(r) for r in ranks) + "位"


def has_zones(slug):
    return bool(_LEAGUES.get(slug, {}).get("zones"))


if __name__ == "__main__":  # 単体テスト
    import sys, json
    slug = sys.argv[1] if len(sys.argv) > 1 else "premier-east"
    teams_path = Path(__file__).parent.parent / "data" / "teams.json"
    data = json.loads(teams_path.read_text(encoding="utf-8"))
    all_teams, target = [], []
    for pid, info in data.items():
        if pid == "_meta":
            continue
        for t in info.get("teams", []):
            all_teams.append(t)
    label_map = {v[0]: k for k, v in {}.items()}  # noqa
    # slug -> league名 は generate_league_pages 側の LEAGUE_DEFS が正だが、
    # ここでは簡易に「slugからリーグ名を推測せず」全チームから該当スラッグ分を抽出できないため
    # generate_league_pages を import して使う
    sys.path.insert(0, str(Path(__file__).parent))
    from generate_league_pages import LEAGUE_DEFS  # noqa
    league_name = next((k for k, v in LEAGUE_DEFS.items() if v[0] == slug), None)
    if not league_name:
        print(f"unknown slug: {slug}")
        sys.exit(1)
    target = [t for t in all_teams if t.get("league") == league_name]
    target.sort(key=lambda t: t.get("leagueRank") or t.get("rank") or 99)
    zmap = resolve_zones(slug, target, all_teams)
    for i, t in enumerate(target, 1):
        z = zmap.get(i)
        tag = f'  <- {z["type"]}: {z["label"]}' if z else ""
        print(f"{i:2d} {t.get('name')}{tag}")
    print()
    print(render_zone_legend_html(slug, zmap))
