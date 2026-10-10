"""data/tournaments/ の大会mdの「置き場所」を1か所で決める（2026-10-10 新設）。

2026-10-10 に、県予選のmdを大会ごとのフォルダに分けた:
    data/tournaments/senshuken-2026/{pref}-senshuken-2026.md   （47ファイル）
    data/tournaments/interhigh-2026/{pref}-interhigh-2026.md   （47ファイル）
ファイル名は変えていない（県ページの並び順・ログ・無視指定はファイル名に依存しているため）。

⚠️ 以前は各スクリプトが `data/tournaments/*.md`（すぐ下だけ）を直接読んでいた。
   フォルダに分けるとそれらは**エラーも出さずに0件になる**（取り込み・県ページ・見張りが黙る）。
   大会mdを読むときは必ずここの関数を使うこと。

- 来年は senshuken-2027/ などのフォルダを足すだけでよい（コードの変更は不要）。
- `_` で始まるフォルダ（_archive・_templates）と regional/ は対象外（従来どおり）。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOURNAMENT_DIR = ROOT / "data" / "tournaments"

# 大会mdとして読まないサブフォルダ（regional は generate_regional_page.py が別に読む）
EXCLUDED_SUBDIRS = {"regional"}


def iter_tournament_mds(base: Path = None):
    """大会mdを全部返す（直下＋大会フォルダの中）。並びはファイル名順。"""
    base = base or TOURNAMENT_DIR
    if not base.exists():
        return []
    files = list(base.glob("*.md"))
    for d in base.iterdir():
        if d.is_dir() and not d.name.startswith("_") and d.name not in EXCLUDED_SUBDIRS:
            files.extend(d.glob("*.md"))
    return sorted(files, key=lambda p: p.name)


def pref_md_path(slug: str, kind: str, year, base: Path = None) -> Path:
    """県予選mdの場所。例: pref_md_path("aichi", "senshuken", 2026)
    → data/tournaments/senshuken-2026/aichi-senshuken-2026.md"""
    base = base or TOURNAMENT_DIR
    return base / f"{kind}-{year}" / f"{slug}-{kind}-{year}.md"
