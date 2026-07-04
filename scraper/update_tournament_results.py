# -*- coding: utf-8 -*-
"""
県予選トーナメント（選手権・インターハイ等）の自動更新スクリプト
================================================================
高校サッカードットコム(koko-soccer)の大会ページから対戦カード・結果を取得し、
data/tournaments/*.md に組み合わせとスコアを自動で追記する。

対象ファイルの条件:
  - frontmatter に `source: https://koko-soccer.com/score/XXXX` がある
  - frontmatter の `status:` が「終了」でない

安全設計（誤データ混入を防ぐ最重要ポイント）:
  1. 既にスコアが書かれた行は絶対に上書きしない（手動修正を保護）。
  2. スコアを書くのは koko 側に「試合終了」ラベルが付いた試合だけ。
  3. 取得失敗・解析0件のときは何も書き換えない（据え置き）。
  4. チーム名は teams.json の表記（県内ランキング表記）へ名寄せする。
     名寄せできない名前は koko の表記のままで追記し、ログに記録する
     （下位校は順位表に載らないため正常。強豪校で出たら要エイリアス追加）。
  5. 「決勝」に結果が入ったら status を自動で「終了」に更新（前進のみ）。

使い方:
  python scraper/update_tournament_results.py                  # 本番（対象全ファイル）
  python scraper/update_tournament_results.py --dry-run        # 変更内容の表示のみ
  python scraper/update_tournament_results.py --dry-run \
      --file data/tournaments/shizuoka-interhigh-2026.md \
      --url https://koko-soccer.com/score/4393                 # 単体テスト（status無視）

終了コード: 常に 0（失敗はログで通知。既存データは安全に据え置き）。
依存: requests, beautifulsoup4, lxml（GitHub Actions で導入済み）
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
TOURNAMENT_DIR = ROOT / "data" / "tournaments"
TEAMS_JSON = ROOT / "data" / "teams.json"

UA = {"User-Agent": "Mozilla/5.0 (u18-soccer tournament updater)"}
TIMEOUT = 30

# よくある学校名の省略形（koko表記 → 正式表記側の末尾）を相互登録するための規則
ABBREV_SUFFIX = [
    ("商業", "商"),
    ("工業", "工"),
    ("農業", "農"),
    ("水産", "水"),
]

# ラウンド名の正規化順序（新ラウンド見出しを挿入する位置の決定に使用）
ROUND_ORDER = [
    "1回戦", "2回戦", "3回戦", "4回戦", "5回戦",
    "ベスト16", "4回戦", "準々決勝", "準決勝", "代表決定戦", "3位決定戦", "決勝",
]


def log(msg):
    print(msg, flush=True)


def canon(name: str) -> str:
    """チーム名の照合用正規化（NFKC・空白除去・末尾の高校/高等学校等を除去）"""
    n = unicodedata.normalize("NFKC", name or "").strip()
    n = n.replace("　", "").replace(" ", "")
    n = re.sub(r"[（(][^）)]*[）)]$", "", n)  # 末尾の（県名）を除去
    for suf in ("高等学校", "高校", "中等教育学校", "高等部"):
        if n.endswith(suf) and len(n) > len(suf):
            n = n[: -len(suf)]
            break
    return n


def _is_subseq(short: str, long_: str) -> bool:
    """short が long_ の「文字順を保った部分列」か（青翠⊂渋川青翠、関学附⊂関東学園大附）"""
    it = iter(long_)
    return all(c in it for c in short)


def is_abbrev_variant(a: str, b: str) -> bool:
    """a と b が同一校の略記ゆれとみなせるか。
    合同チーム（・区切り）は区切りごとに対応づけて判定する。
    「磐田東」vs「磐田南」のような別校は False（部分列にならない）。"""
    a, b = canon(a), canon(b)
    if not a or not b or a == b:
        return a == b and bool(a)
    # 区切り記号の有無だけの違い（北鷹・能代・大館桂桜 ＝ 北鷹・能代大館桂桜）
    if re.sub(r"[・･]", "", a) == re.sub(r"[・･]", "", b):
        return True
    seg_a = [s for s in re.split(r"[・･]", a) if s]
    seg_b = [s for s in re.split(r"[・･]", b) if s]
    if len(seg_a) != len(seg_b):
        return False

    def seg_match(x, y):
        if x == y:
            return True
        s, l = (x, y) if len(x) < len(y) else (y, x)
        return len(s) >= 2 and _is_subseq(s, l)

    # 各セグメントを1対1で対応づけ（順不同・重複使用なし）
    used = [False] * len(seg_b)
    for sa in seg_a:
        hit = False
        for i, sb in enumerate(seg_b):
            if not used[i] and seg_match(sa, sb):
                used[i] = True
                hit = True
                break
        if not hit:
            return False
    return True


def round_key(heading: str) -> str:
    """ラウンド見出しの照合キー（「2回戦（5/17・シード登場）」→「2回戦」）"""
    h = unicodedata.normalize("NFKC", heading or "").strip()
    h = re.split(r"[（(]", h)[0]
    return h.strip()


# ---------------------------------------------------------------------------
# 名寄せマップ（teams.json の県内ランキング表記へ揃える）
# ---------------------------------------------------------------------------

def build_name_map(pref_id: str) -> dict:
    """{照合キー: 表示名} を返す。表示名は teams.json の name から
    高校/高等学校サフィックスを除いた「県内ランキング表記」。"""
    try:
        data = json.loads(TEAMS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"  ⚠ teams.json 読込失敗: {e}")
        return {}
    pref = data.get(pref_id) or {}
    name_map = {}

    def register(key, display):
        k = canon(key)
        if k and k not in name_map:
            name_map[k] = display

    def register_with_abbrevs(raw_name, display):
        register(raw_name, display)
        c = canon(raw_name)
        for long_suf, short_suf in ABBREV_SUFFIX:
            if c.endswith(long_suf):
                register(c[: -len(long_suf)] + short_suf, display)
            elif c.endswith(short_suf):
                register(c[: -len(short_suf)] + long_suf, display)

    team_lists = [pref.get("teams") or []]
    if isinstance(pref.get("division2"), list):  # 東京T2
        team_lists.append(pref["division2"])
    for teams in team_lists:
        for t in teams:
            name = t.get("name", "")
            if not name:
                continue
            display = canon(name) or name
            register_with_abbrevs(name, display)
            for alias in (t.get("aliases") or []):
                register_with_abbrevs(alias, display)
    return name_map


# ---------------------------------------------------------------------------
# koko-soccer ページの解析
# ---------------------------------------------------------------------------

def parse_score_cell(text: str):
    """スコアセル文字列 → (スコア表記, 終了フラグ)
    '2 - 1 試合終了' -> ('2-1', True)
    '1 - 1PK 5 - 4 試合終了' -> ('1-1(PK5-4)', True)
    '- 試合前' -> (None, False)
    """
    t = unicodedata.normalize("NFKC", text or "")
    finished = "試合終了" in t
    m = re.search(
        r"(\d+)\s*[-ー－]\s*(\d+)(?:\s*PK\s*(\d+)\s*[-ー－]\s*(\d+))?", t
    )
    if not m:
        return None, finished
    sc = f"{m.group(1)}-{m.group(2)}"
    if m.group(3) is not None:
        sc += f"(PK{m.group(3)}-{m.group(4)})"
    return sc, finished


def fetch_koko_rounds(url: str):
    """kokoページを取得し [{'name','matches':[{'home','away','score','finished','date'}]}] を返す。
    失敗時は例外を送出。"""
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    rounds = []
    for h in soup.select("h4.index-title"):
        rname = h.get_text(strip=True)
        table = h.find_next_sibling("table")
        if table is None or "table-game" not in (table.get("class") or []):
            continue
        matches = []
        for tr in table.select("tr"):
            home_td = tr.select_one("td.home")
            away_td = tr.select_one("td.away")
            score_td = tr.select_one("td.score")
            if home_td is None or away_td is None:
                continue
            # チーム名（<a>の中。（県）spanは除外）
            home_a = home_td.find("a")
            away_a = away_td.find("a")
            home = (home_a.get_text(strip=True) if home_a
                    else re.sub(r"（[^）]*）", "", home_td.get_text(strip=True)))
            away = (away_a.get_text(strip=True) if away_a
                    else re.sub(r"（[^）]*）", "", away_td.get_text(strip=True)))
            if not home or not away:
                continue
            score, finished = parse_score_cell(
                score_td.get_text(" ", strip=True) if score_td else ""
            )
            date_td = tr.select_one("td.date")
            date = ""
            if date_td:
                dm = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})",
                               date_td.get_text(" ", strip=True))
                if dm:
                    date = f"{int(dm.group(2))}/{int(dm.group(3))}"
            matches.append({
                "home": home, "away": away,
                "score": score, "finished": finished, "date": date,
            })
        if matches:
            rounds.append({"name": rname, "matches": matches})
    return rounds


# ---------------------------------------------------------------------------
# md ファイルの解析と書き換え
# ---------------------------------------------------------------------------

def split_frontmatter(content: str):
    if not content.startswith("---"):
        return None, None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, None
    return parts[1], parts[2]


def parse_meta(frontmatter_str: str) -> dict:
    meta = {}
    for line in frontmatter_str.strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


MATCH_LINE_RE = re.compile(
    r"^- (.+?)\s+(\d+\s*-\s*\d+(?:\s*\(\s*(?:PK)?\s*\d+\s*-\s*\d+\s*\))?)\s+(.+)$"
)
VS_LINE_RE = re.compile(r"^- (.+?)\s+vs\s+(.+)$", re.IGNORECASE)


def parse_md_line(line: str):
    """md の1行 → (teamA, teamB, has_score) / 該当しない行は None
    全角カッコ・全角スペース等はNFKCで吸収する。"""
    s = unicodedata.normalize("NFKC", line.strip())
    m = MATCH_LINE_RE.match(s)
    if m:
        return m.group(1).strip(), m.group(3).strip(), True
    m = VS_LINE_RE.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip(), False
    return None


def md_score_norm(line: str):
    """md行のスコアを正規化して返す（'2-2（3-4）'→'2-2(PK3-4)'）。スコア行でなければ None"""
    s = unicodedata.normalize("NFKC", line.strip())
    m = MATCH_LINE_RE.match(s)
    if not m:
        return None
    sc = re.sub(r"\s", "", m.group(2))
    sc = re.sub(r"\((\d)", r"(PK\1", sc)
    return sc


def flip_score(sc: str) -> str:
    """'1-3(PK4-2)' → '3-1(PK2-4)'（ホーム/アウェイ反転）"""
    m = re.match(r"^(\d+)-(\d+)(?:\(PK(\d+)-(\d+)\))?$", sc or "")
    if not m:
        return sc or ""
    out = f"{m.group(2)}-{m.group(1)}"
    if m.group(3) is not None:
        out += f"(PK{m.group(4)}-{m.group(3)})"
    return out


def rev_matches_score(md_sc: str, koko_sc: str, fwd: bool) -> bool:
    """md行のスコアとkokoのスコアが向きを考慮して一致するか"""
    if md_sc is None or not koko_sc:
        return False
    md_n = re.sub(r"\s", "", md_sc)
    ko_n = re.sub(r"\s", "", koko_sc)
    return md_n == (ko_n if fwd else flip_score(ko_n))


def draw_without_pk(sc: str) -> bool:
    """引き分けスコアなのにPK表記が無い（ノックアウトでは出典の誤記の可能性大）"""
    m = re.match(r"^(\d+)-(\d+)$", sc or "")
    return bool(m) and m.group(1) == m.group(2)


def round_sort_pos(name: str) -> int:
    k = round_key(name)
    for i, r in enumerate(ROUND_ORDER):
        if k == r:
            return i
    # 「◯回戦」の数値をひろう
    m = re.match(r"(\d+)回戦", k)
    if m:
        return int(m.group(1)) - 1
    return 50  # 不明ラウンドは末尾寄り（決勝より前には入れない）


def update_md(md_path: Path, koko_rounds, name_map, dry_run=False):
    """mdへ結果を反映。(変更あり?, 記入数, 追加数, 警告リスト) を返す"""
    content = md_path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(content)
    if fm is None:
        return False, 0, 0, [f"frontmatterが無いためスキップ: {md_path.name}"]

    warnings = []
    extra_aliases = {}  # 略記ゆれの学習結果 {canon(md表記): 照合キー}

    def mapped(name):
        c = canon(name)
        if c in name_map:
            return name_map[c]
        return c  # 名寄せ不可 → koko表記（正規化のみ）をそのまま使う

    def match_key(name):
        """照合キー: 名寄せ後の正規化名（md側・koko側の両方に適用する）"""
        c = canon(name)
        if c in extra_aliases:
            return extra_aliases[c]
        return canon(mapped(name))

    body_lines = body.split("\n")

    # md内で既に使われている表記を優先するためのマップ {照合キー: md表記}
    usage = {}
    for line in body_lines:
        parsed = parse_md_line(line)
        if parsed:
            ta, tb, _ = parsed
            usage.setdefault(match_key(ta), ta)
            usage.setdefault(match_key(tb), tb)

    def display(name):
        """新規行に書く表記: md内の既存表記 > ランキング表記 > koko表記"""
        return usage.get(match_key(name)) or mapped(name)

    filled = 0
    added = 0
    modified = False
    consumed = set()  # 対応づいたmd行（行の中身で管理すると挿入でずれるためidxはその都度再計算）

    def rounds_now():
        return _rescan_rounds(body_lines)

    def side_ok(md_name, koko_name):
        return (match_key(md_name) == match_key(koko_name)
                or is_abbrev_variant(md_name, koko_name))

    def fill_line(idx, km, kkey):
        """スコア未記入の行に結果を記入。スコア付き行は上書きせず、不一致なら警告。"""
        nonlocal filled, modified
        parsed = parse_md_line(body_lines[idx])
        if not parsed:
            return
        ta, tb, has_score = parsed
        fwd = side_ok(ta, km["home"])
        if has_score:
            # 既存スコアは絶対に上書きしない。ただしkokoと食い違うなら警告。
            if km["finished"] and km["score"]:
                md_sc = md_score_norm(body_lines[idx])
                if md_sc and not rev_matches_score(md_sc, km["score"], fwd):
                    warnings.append(
                        f"要確認: {kkey} の「{ta} / {tb}」のスコアが出典と不一致"
                        f"（md={md_sc} / koko={km['score'] if fwd else flip_score(km['score'])}）"
                        f"→ 上書きせず据え置き")
            return
        if km["finished"] and km["score"]:
            if draw_without_pk(km["score"]):
                warnings.append(
                    f"要確認: {kkey}「{km['home']} {km['score']} {km['away']}」が"
                    f"引き分けのままPK表記なし（出典の誤記の可能性）")
            if fwd:
                newline = f"- {ta} {km['score']} {tb}"
            else:
                newline = f"- {tb} {km['score']} {ta}"
            if body_lines[idx].strip() != newline:
                body_lines[idx] = newline
                filled += 1
                modified = True

    def learn_alias(parsed, km):
        """略記ゆれを学習（以降のラウンドで md 表記を優先使用）"""
        for md_name, koko_name in ((parsed[0], km["home"]), (parsed[1], km["away"]),
                                   (parsed[0], km["away"]), (parsed[1], km["home"])):
            if is_abbrev_variant(md_name, koko_name) and canon(md_name) != canon(koko_name):
                usage.setdefault(match_key(koko_name), md_name)
                extra_aliases[canon(md_name)] = match_key(koko_name)

    def ensure_round(kkey, kr):
        """ラウンド見出しを（無ければ）作って target を返す"""
        nonlocal modified, consumed
        target = next((r for r in rounds_now() if r["key"] == kkey), None)
        if target:
            return target
        dates = sorted({m["date"] for m in kr["matches"] if m["date"]},
                       key=lambda d: [int(x) for x in d.split("/")])
        date_str = f"（{'・'.join(dates)}）" if dates else ""
        heading = f"## {kkey}{date_str}"
        pos = None
        for r in rounds_now():
            if round_sort_pos(r["key"]) > round_sort_pos(kkey):
                pos = r["heading_idx"]
                break
        if pos is None:
            while body_lines and body_lines[-1].strip() == "":
                body_lines.pop()
            body_lines.extend(["", heading, ""])
        else:
            body_lines[pos:pos] = [heading, "", ""]
            consumed = {i + 3 if i >= pos else i for i in consumed}
        modified = True
        return next(r for r in rounds_now() if r["key"] == kkey)

    for kr in koko_rounds:
        kkey = round_key(kr["name"])
        target = next((r for r in rounds_now() if r["key"] == kkey), None)

        # 出典異常検知: 同一校が同ラウンドに複数回登場していないか（ノックアウトではあり得ない）
        team_counts = {}
        for km in kr["matches"]:
            for nm in (km["home"], km["away"]):
                k = match_key(nm)
                team_counts[k] = team_counts.get(k, 0) + 1

        pending = []

        # ① 完全一致（まず同名ラウンド内 → 見つからなければ全ラウンド横断。
        #    ノックアウトでは同一カードは1大会1回しか無いので横断照合は安全）
        for km in kr["matches"]:
            pair = {match_key(km["home"]), match_key(km["away"])}
            hit = None
            search_spaces = []
            if target:
                search_spaces.append(target["match_idxs"])
            search_spaces.append(
                [i for r in rounds_now() for i in r["match_idxs"]])
            for space in search_spaces:
                for idx in space:
                    if idx in consumed:
                        continue
                    parsed = parse_md_line(body_lines[idx])
                    if parsed and {match_key(parsed[0]), match_key(parsed[1])} == pair:
                        hit = idx
                        break
                if hit is not None:
                    break
            if hit is not None:
                consumed.add(hit)
                fill_line(hit, km, kkey)
            else:
                pending.append(km)

        # ② 略記ゆれ吸収（同名ラウンド内のみ・1対1対応が一意に決まるときだけ）
        still_pending = []
        for km in pending:
            candidates = []
            for idx in (target["match_idxs"] if target else []):
                if idx in consumed:
                    continue
                parsed = parse_md_line(body_lines[idx])
                if not parsed:
                    continue
                ta, tb, has_score = parsed
                fwd = side_ok(ta, km["home"]) and side_ok(tb, km["away"])
                rev = side_ok(ta, km["away"]) and side_ok(tb, km["home"])
                if not (fwd or rev):
                    continue
                # スコア付き既存行は、スコアも一致するときだけ同一試合とみなす
                if has_score and km["score"]:
                    if not rev_matches_score(md_score_norm(body_lines[idx]),
                                             km["score"], fwd):
                        continue
                candidates.append((idx, parsed))

            if len(candidates) == 1:
                idx, parsed = candidates[0]
                consumed.add(idx)
                learn_alias(parsed, km)
                fill_line(idx, km, kkey)
            elif len(candidates) > 1:
                warnings.append(
                    f"要確認: {kkey} の「{km['home']} vs {km['away']}」に対応しうる既存行が複数"
                    f"（あいまいなため据え置き）")
            else:
                still_pending.append(km)

        # ③ 残りを追記（結果 or 組み合わせ）
        for km in still_pending:
            # 出典側の異常（同一校が同ラウンドに複数回）に絡む試合は追記しない
            if team_counts.get(match_key(km["home"]), 0) > 1 \
                    or team_counts.get(match_key(km["away"]), 0) > 1:
                warnings.append(
                    f"要確認: {kkey} の「{km['home']} vs {km['away']}」は、出典側で同一校が"
                    f"同ラウンドに複数回登場しており異常の可能性 → 追記を保留（手動確認を）")
                continue
            target = ensure_round(kkey, kr)
            pair = {match_key(km["home"]), match_key(km["away"])}
            partial_hit = None
            for idx in target["match_idxs"]:
                if idx in consumed:
                    continue
                parsed = parse_md_line(body_lines[idx])
                if parsed and len({match_key(parsed[0]), match_key(parsed[1])} & pair) == 1:
                    partial_hit = body_lines[idx].strip()
            a, b = display(km["home"]), display(km["away"])
            if km["finished"] and km["score"]:
                if draw_without_pk(km["score"]):
                    warnings.append(
                        f"要確認: {kkey}「{a} {km['score']} {b}」が"
                        f"引き分けのままPK表記なし（出典の誤記の可能性）")
                newline = f"- {a} {km['score']} {b}"
            else:
                newline = f"- {a} vs {b}"
            if partial_hit:
                warnings.append(
                    f"要確認: {kkey} に追記した「{a} / {b}」と片チームのみ一致する既存行あり"
                    f" →「{partial_hit}」（校名の誤記の可能性。手動確認を）")
            insert_idx = (target["match_idxs"][-1] + 1
                          if target["match_idxs"] else target["heading_idx"] + 2)
            # 挿入で後続のconsumed idxがずれるため補正
            consumed = {i + 1 if i >= insert_idx else i for i in consumed}
            body_lines.insert(insert_idx, newline)
            added += 1
            modified = True

    # --- status 自動前進（決勝が終わったら「終了」） ---
    meta = parse_meta(fm)
    new_fm = fm
    if meta.get("status") != "終了":
        final_done = any(
            round_key(kr["name"]) == "決勝"
            and any(m["finished"] and m["score"] for m in kr["matches"])
            for kr in koko_rounds
        )
        if final_done:
            new_fm = re.sub(r"(?m)^(status:).*$", r"\1 終了", fm)
            if new_fm != fm:
                modified = True
                log("  status を「終了」に更新")

    if modified and not dry_run:
        md_path.write_text(f"---{new_fm}---{chr(10).join(body_lines)}",
                           encoding="utf-8")
    return modified, filled, added, warnings


def _rescan_rounds(body_lines):
    rounds = []
    cur = None
    for i, line in enumerate(body_lines):
        s = line.strip()
        if s.startswith("## "):
            cur = {"key": round_key(s[3:]), "heading_idx": i, "match_idxs": []}
            rounds.append(cur)
        elif s.startswith("- ") and cur is not None:
            cur["match_idxs"].append(i)
    return rounds


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def process_file(md_path: Path, url: str, dry_run: bool):
    content = md_path.read_text(encoding="utf-8")
    fm, _ = split_frontmatter(content)
    meta = parse_meta(fm or "")
    pref = meta.get("prefecture", "")
    log(f"▶ {md_path.name} ({pref}) ← {url}")

    try:
        koko_rounds = fetch_koko_rounds(url)
    except Exception as e:
        log(f"  ⚠ 取得失敗のため据え置き: {e}")
        return

    if not koko_rounds:
        log("  ⚠ 試合テーブルが見つからないため据え置き")
        return

    name_map = build_name_map(pref)
    modified, filled, added, warnings = update_md(
        md_path, koko_rounds, name_map, dry_run=dry_run)

    total = sum(len(r["matches"]) for r in koko_rounds)
    log(f"  koko試合数={total} / スコア記入={filled} / カード追加={added}"
        f"{'（dry-run: 保存なし）' if dry_run and modified else ''}"
        f"{'' if modified else ' → 変更なし'}")
    for w in sorted(set(warnings)):
        log(f"  ⚠ {w}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--file", help="単体テスト用: 対象mdのパス")
    ap.add_argument("--url", help="単体テスト用: kokoページURL（--fileと併用）")
    args = ap.parse_args()

    if args.file and args.url:
        process_file(Path(args.file), args.url, args.dry_run)
        return 0

    targets = []
    for md_path in sorted(TOURNAMENT_DIR.glob("*.md")):
        content = md_path.read_text(encoding="utf-8")
        fm, _ = split_frontmatter(content)
        if fm is None:
            continue
        meta = parse_meta(fm)
        src = meta.get("source", "")
        if "koko-soccer.com" not in src:
            continue
        if meta.get("status") == "終了":
            continue
        targets.append((md_path, src))

    if not targets:
        log("source付きの未終了トーナメントはありません（正常終了）")
        return 0

    log(f"対象: {len(targets)}ファイル")
    for md_path, url in targets:
        process_file(md_path, url, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
