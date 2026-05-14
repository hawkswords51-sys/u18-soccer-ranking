#!/usr/bin/env python3
"""data/tournaments_data.yml を読んで data/tournaments.json を生成する。

スクレイプではなく手入力 YAML が真実のソース。
GitHub Actions で毎回走らせても 1秒で終わる軽い処理。

使い方:
  python scraper/build_tournaments.py
"""

import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("❌ PyYAML が必要です: pip install pyyaml")
    sys.exit(1)

# ===== パス設定 =====
BASE = Path(__file__).parent.parent
YAML_FILE = BASE / "data" / "tournaments_data.yml"
TEAMS_FILE = BASE / "data" / "teams.json"
OUT_FILE = BASE / "data" / "tournaments.json"

# ===== 大会メタ情報 =====
TOURNAMENT_META = {
    "all_japan_highschool": {
        "displayName": "全国高校サッカー選手権大会",
        "shortName":   "高校選手権",
        "category":    "high_school",
    },
    "interhigh": {
        "displayName": "全国高等学校総合体育大会サッカー競技大会",
        "shortName":   "インターハイ",
        "category":    "high_school",
    },
    "club_youth_u18": {
        "displayName": "日本クラブユース選手権(U-18)大会",
        "shortName":   "クラブユース",
        "category":    "club_youth",
    },
    "j_youth_cup": {
        "displayName": "Jユースカップ",
        "shortName":   "Jユース",
        "category":    "j_youth",
    },
}

# ===== ラウンド名 → (表示名, ランク) =====
ROUND_TO_RANK = {
    "優勝":    ("優勝",    1),
    "準優勝":   ("準優勝",   2),
    "ベスト4": ("ベスト4", 4),
    "ベスト8": ("ベスト8", 8),
}


# ===== ユーティリティ =====
def normalize_name(name: str) -> str:
    """teams.json 照合用の正規化"""
    if not name:
        return ""
    n = unicodedata.normalize('NFKC', name)
    n = n.replace(' ', '').replace('\u3000', '')
    return n


def find_team(team_name: str, teams_data: dict) -> tuple[str | None, str | None]:
    """teams.json から (正式名, 都道府県ID) を逆引き。
    name → aliases → 部分一致 の順で探す。
    見つからなければ (None, None)。"""
    target = normalize_name(team_name)
    if not target:
        return None, None
    # 1. name 完全一致
    for pref_id, pref_data in teams_data.items():
        if pref_id == "_meta":
            continue
        for t in pref_data.get("teams", []):
            if normalize_name(t.get("name", "")) == target:
                return t.get("name"), pref_id
    # 2. aliases 完全一致 (新)
    for pref_id, pref_data in teams_data.items():
        if pref_id == "_meta":
            continue
        for t in pref_data.get("teams", []):
            for alias in (t.get("aliases") or []):
                if normalize_name(alias) == target:
                    return t.get("name"), pref_id
    # 3. 部分一致 (例: "前橋育英" → "前橋育英高校")
    for pref_id, pref_data in teams_data.items():
        if pref_id == "_meta":
            continue
        for t in pref_data.get("teams", []):
            existing = normalize_name(t.get("name", ""))
            if existing and (target in existing or existing in target):
                return t.get("name"), pref_id
    return None, None


def find_pref(team_name: str, teams_data: dict) -> str | None:
    """teams.json から所属都道府県IDを逆引き (後方互換用)"""
    _, pref = find_team(team_name, teams_data)
    return pref


def normalize_team_entry(entry, teams_data: dict) -> dict | None:
    """YAML の文字列 or {name,pref} 辞書を {name, pref} に統一。
    teams.json で見つかった場合は正式名 + pref に正規化する。
    ★ 明示的に pref が指定されている場合は teams.json の lookup を skip する
       (find_team の部分一致による誤マッチを防ぐ)"""
    if entry is None:
        return None
    if isinstance(entry, str):
        name = entry.strip()
        if not name:
            return None
        canonical, pref = find_team(name, teams_data)
        return {"name": canonical or name, "pref": pref}
    if isinstance(entry, dict):
        name = (entry.get("name") or "").strip()
        if not name:
            return None
        explicit_pref = entry.get("pref")
        # 明示的に pref が指定されている場合はそれを尊重し、teams.json の lookup を skip
        if explicit_pref:
            return {"name": name, "pref": explicit_pref}
        canonical, pref = find_team(name, teams_data)
        return {
            "name": canonical or name,
            "pref": pref,
        }
    return None


# ===== メイン =====
def build() -> int:
    # 入力チェック
    if not YAML_FILE.exists():
        print(f"❌ {YAML_FILE} が見つかりません")
        return 1
    if not TEAMS_FILE.exists():
        print(f"❌ {TEAMS_FILE} が見つかりません")
        return 1

    # YAML 読み込み
    with open(YAML_FILE, encoding='utf-8') as f:
        yml = yaml.safe_load(f) or {}

    # teams.json 読み込み (チーム→pref 照合用)
    with open(TEAMS_FILE, encoding='utf-8') as f:
        teams_data = json.load(f)

    output = {
        "_meta": {
            "lastUpdated":   datetime.now().isoformat(timespec='seconds'),
            "schemaVersion": 1,
            "source":        "manual_yaml",
        },
        "tournaments": {},
    }

    warnings: list[str] = []
    summary: list[tuple[str, int, int]] = []

    for tid, meta in TOURNAMENT_META.items():
        out = {
            "displayName": meta["displayName"],
            "shortName":   meta["shortName"],
            "category":    meta["category"],
            "results":     {},
        }
        yaml_data = yml.get(tid)
        if not yaml_data:
            output["tournaments"][tid] = out
            summary.append((meta["shortName"], 0, 0))
            continue

        for year, year_data in yaml_data.items():
            year_str = str(year)
            if not year_data:
                continue
            teams_list: list[dict] = []
            seen_names: set[str] = set()

            # 上位8チーム (優勝→準優勝→ベスト4→ベスト8)
            for round_label, (result_name, rank) in ROUND_TO_RANK.items():
                value = year_data.get(round_label)
                if value is None:
                    continue
                if isinstance(value, str):
                    value = [value] if value.strip() else []
                elif isinstance(value, dict):
                    # フロー記法 { name: "...", pref: ... } 単独値をリスト化
                    # (優勝/準優勝 フィールドで使われる)
                    value = [value]
                if not isinstance(value, list):
                    continue
                for entry in value:
                    norm = normalize_team_entry(entry, teams_data)
                    if norm is None:
                        continue
                    key = normalize_name(norm["name"])
                    if key in seen_names:
                        continue
                    seen_names.add(key)
                    if norm["pref"] is None:
                        warnings.append(
                            f"⚠ [{tid} {year_str}] {norm['name']} の都道府県不明 "
                            f"(teams.json 未登録 / pref 未指定)"
                        )
                    teams_list.append({
                        "team":   norm["name"],
                        "pref":   norm["pref"],
                        "result": result_name,
                        "rank":   rank,
                    })

            # 都道府県代表 (high_school カテゴリのみ)
            if meta["category"] == "high_school":
                reps = year_data.get("都道府県代表") or []
                if isinstance(reps, dict):
                    # 旧形式 (pref → list) にも一応対応
                    flat = []
                    for pid, names in reps.items():
                        if not names:
                            continue
                        for n in names:
                            flat.append({"name": n, "pref": pid})
                    reps = flat
                if isinstance(reps, list):
                    for entry in reps:
                        norm = normalize_team_entry(entry, teams_data)
                        if norm is None:
                            continue
                        key = normalize_name(norm["name"])
                        if key in seen_names:
                            continue   # ベスト8以上で記録済み
                        seen_names.add(key)
                        if norm["pref"] is None:
                            warnings.append(
                                f"⚠ [{tid} {year_str}] 代表校 {norm['name']} の "
                                f"都道府県不明"
                            )
                        teams_list.append({
                            "team":   norm["name"],
                            "pref":   norm["pref"],
                            "result": "代表",
                            "rank":   None,
                        })

            if teams_list:
                out["results"][year_str] = {"teams": teams_list}

        output["tournaments"][tid] = out
        years_count = len(out["results"])
        teams_count = sum(len(v["teams"]) for v in out["results"].values())
        summary.append((meta["shortName"], years_count, teams_count))

    # 保存
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # サマリ表示
    print(f"✅ 保存: {OUT_FILE}")
    print()
    print("📊 集計:")
    for sn, ys, ts in summary:
        print(f"  {sn:14s} {ys}年分 / {ts}チーム")
    print()
    if warnings:
        print(f"⚠ 警告 {len(warnings)}件:")
        for w in warnings[:30]:
            print(f"  {w}")
        if len(warnings) > 30:
            print(f"  ... 他 {len(warnings) - 30}件")
    else:
        print("⚠ 警告なし (全チームの都道府県を解決)")

    return 0


if __name__ == "__main__":
    sys.exit(build())
