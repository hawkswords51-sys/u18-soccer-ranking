#!/usr/bin/env python3
"""data/tournaments_data.yml を読んで data/tournaments.json を生成する。

スクレイプではなく手入力 YAML が真実のソース。
GitHub Actions で毎回走らせても 1秒で終わる軽い処理。

使い方:
  python scraper/build_tournaments.py
"""

import json
import re
import sys
import unicodedata
from datetime import datetime
from jst import now as _jst_now
from pathlib import Path

import fetch_status

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

# ===== 県不明（pref null）を許す学校（2026-09-27 新設） =====
# pref が null の学校はどの県ページにも出ない。以前は警告1行だけで緑のまま通り、
# 38件近くが気づかれずに残っていた（福岡2024IH 福大若葉 が県ページから抜けていた）。
# → ここに無い県不明が1件でもあれば失敗として記録し、audit_pref_freshness.py が赤にする
#   （NO_RETRY_JOBS＝初回から赤）。tournaments.json は保存するのでサイトの更新は止めない。
# 直し方は、YAML の該当行を { name: "...", pref: xxx } 形式にして県を明示する。
# キー＝(大会ID, 年, 学校名)。理由を必ず書く。
PREF_UNKNOWN_ALLOWED = {
    ("club_youth_u18", "2016", "JFAアカデミー福島"):
        "拠点が静岡と福島で移っているため、どちらの県にも入れず意図的に据え置き（2026-09-27）",
}


# ===== ユーティリティ =====
def normalize_name(name: str) -> str:
    """teams.json 照合用の正規化"""
    if not name:
        return ""
    n = unicodedata.normalize('NFKC', name)
    n = n.replace(' ', '').replace('\u3000', '')
    return n


def _strip_hs(n: str) -> str:
    """末尾の「高等学校」「高校」を1つだけ外す（別名の照合用）"""
    for suffix in ("高等学校", "高校"):
        if n.endswith(suffix) and len(n) > len(suffix):
            return n[:-len(suffix)]
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
    #    [2026-09-27] 両方の末尾の「高校」「高等学校」を外して比べる
    #    （YAML「福大若葉高校」が別名「福大若葉」に一致せず pref null になっていた）。
    #    「高等部」は対象外。部分一致（3.）には入れない。
    target_core = _strip_hs(target)
    for pref_id, pref_data in teams_data.items():
        if pref_id == "_meta":
            continue
        for t in pref_data.get("teams", []):
            for alias in (t.get("aliases") or []):
                if _strip_hs(normalize_name(alias)) == target_core:
                    return t.get("name"), pref_id
    # 3. 部分一致 (例: "前橋育英" → "前橋育英高校")
    #    ただし "○○高校2nd" のような控えチームへの誤マッチを避ける
    #    （例: "徳島商業高校" が "徳島商業高校2nd" に化けるのを防止）
    reserve_re = re.compile(r"^(2nd|3rd|ii|iii|b|c|セカンド|サード)$", re.I)
    pref_only = None
    for pref_id, pref_data in teams_data.items():
        if pref_id == "_meta":
            continue
        for t in pref_data.get("teams", []):
            existing = normalize_name(t.get("name", ""))
            if not existing:
                continue
            if target in existing:
                extra = existing.replace(target, "", 1)
                if extra and reserve_re.match(extra):
                    # 控えチーム(2nd等)。名前は採用せず、pref手がかりだけ残して継続
                    if pref_only is None:
                        pref_only = pref_id
                    continue
                return t.get("name"), pref_id
            if existing in target:
                return t.get("name"), pref_id
    # 正規チームが見つからず控えチームのみ一致した場合：名前は入力のまま、prefだけ採用
    if pref_only:
        return None, pref_only
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
            # JSTで書く。UTCのままだと日付が1日ずれる（jst.py参照）。
            # 形は従来どおり（+09:00 は付けない）＝既存の値と見た目を変えない。
            "lastUpdated":   _jst_now().strftime('%Y-%m-%dT%H:%M:%S'),
            "schemaVersion": 1,
            "source":        "manual_yaml",
        },
        "tournaments": {},
    }

    warnings: list[str] = []
    unknown_pref: list[tuple[str, str, str]] = []   # (大会ID, 年, 学校名)
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
                        unknown_pref.append((tid, year_str, norm["name"]))
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
                            unknown_pref.append((tid, year_str, norm["name"]))
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

    # 県不明の判定（PREF_UNKNOWN_ALLOWED 参照）。保存は済んでいるのでサイトは更新される
    global _fail_note
    for key in PREF_UNKNOWN_ALLOWED:
        if key not in unknown_pref:
            print(f"⚪ PREF_UNKNOWN_ALLOWED の {key} は県が解決できるようになりました。この行はもう不要です。消してください")
    bad = [u for u in unknown_pref if u not in PREF_UNKNOWN_ALLOWED]
    if bad:
        _fail_note = f"県不明 {len(bad)}件: " + "、".join(f"{n}（{t} {y}）" for t, y, n in bad)
        print()
        print(f"❌ {_fail_note}")
        print("   → tournaments_data.yml の該当行を { name: \"...\", pref: xxx } 形式にして県を明示する"
              "（意図的な例外なら PREF_UNKNOWN_ALLOWED に理由つきで足す）")
        return 2

    return 0


_fail_note = ""   # build() が失敗の中身を入れる（fetch_status の note 用）


def _run_and_record(job: str = "build_tournaments") -> int:
    """build() を走らせ、成否を fetch_status.json に記録する（2026-09-08追加）。

    ⚠️ ワークフローではこのステップに continue-on-error: true が付いている。
       **外してはいけない**（コミットより前のステップなので、赤くすると
       YAMLの打ち間違い1つでその日のサイト更新が丸ごと止まる）。
       ただし握りつぶしたままだと、**data/tournaments_data.yml を直して push →
       Actionsは緑 → サイトは変わらない**、という一番わかりにくい形になる
       （このYAMLは push起動の対象パスなので、編集直後に必ずこの経路を通る）。
       失敗しても data/tournaments.json は前回の内容が残るため、ページは
       古いまま静かに公開され続ける。
       → **握りつぶすが、必ず表に出す。** ここで成否を記録し、コミット・デプロイより
         後にいる audit_pref_freshness.py が赤にする（sync_teams_from_* と同じ形）。
    """
    try:
        rc = build()
    except Exception as e:
        fetch_status.set_job_result(job, type(e).__name__, str(e))
        raise
    fetch_status.set_job_result(job, "ok" if rc == 0 else "nonzero_exit",
                                "" if rc == 0 else (_fail_note or f"終了コード {rc}"))
    return rc


if __name__ == "__main__":
    sys.exit(_run_and_record())
