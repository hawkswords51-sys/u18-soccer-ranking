#!/usr/bin/env python3
"""
Jユースカップ専用ページ生成スクリプト（2026-06-13版 / 機能強化）
====================================================
data/tournaments/j-youth-cup-2026.md を読み込み、
独立ページ /tournaments/j-youth-cup-2026/ を生成する。

このバージョンで追加した3機能：
  ① SVGトーナメント表（紙の組み合わせ表風・勝ち上がりを赤線で自動描画）
     → data md に「## トーナメント表（組み合わせ）」セクションを書くと表示。
  ② 「次の試合」上部固定ボックス＋最終更新日
     → まだ結果が入っていない（vs の）最初のラウンドを冒頭に大きく表示。
  ③ 大会データ・見どころ（結果行から大量得点・PK決着などを自動集計）

既存機能：
  - 「各県代表」セクション：県名: 学校名 を一覧化（学校はチーム詳細へ自動リンク）
  - 各ラウンドの試合行を描画し、スコアから勝者を自動ハイライト
  - まだ組み合わせ未定でも「準備中」表示で正しく出力される
  - FAQ / SportsEvent / FAQPage 構造化データ

依存：標準ライブラリ + PyYAML
"""
import re
import unicodedata
import yaml
from pathlib import Path
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


class _JSTDate:
    """GitHubのサーバーは世界標準時(UTC)のため、日本時間の「今日」を返す。
       （朝の自動実行で日付が前日になるのを防ぐ）"""
    @staticmethod
    def today():
        return _dt.now(_tz(_td(hours=9))).date()


date = _JSTDate

BASE_DIR = Path(__file__).parent.parent
DOMAIN = "https://u18-soccer.com"
GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"

SOURCE = BASE_DIR / "data" / "tournaments" / "j-youth-cup-2026.md"
OUT_DIR = BASE_DIR / "tournaments" / "j-youth-cup-2026"
CANONICAL = f"{DOMAIN}/tournaments/j-youth-cup-2026/"

# ---- チーム詳細リンク用マップ ----
def load_team_profile_map() -> dict:
    profiles_dir = BASE_DIR / "data" / "team-profiles"
    team_map = {}
    if not profiles_dir.exists():
        return team_map
    for md in profiles_dir.glob("*.md"):
        try:
            c = md.read_text(encoding="utf-8")
            if not c.startswith("---"):
                continue
            parts = c.split("---", 2)
            if len(parts) < 3:
                continue
            meta = yaml.safe_load(parts[1]) or {}
            tid, tname = meta.get("id"), meta.get("name")
            if tid and tname:
                team_map[tname] = tid
                sn = meta.get("short_name")
                if sn and sn != tname:
                    team_map[sn] = tid
        except Exception:
            pass
    return team_map

TEAM_MAP = load_team_profile_map()

def html_escape(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def format_team_name(name):
    if not name:
        return "—"
    esc = html_escape(name)
    for token in sorted(["U-18","U-15","F.C.","U18","U15","2nd","3rd","ユース"], key=len, reverse=True):
        et = html_escape(token)
        esc = esc.replace(et, f'<span class="nb">{et}</span>')
    return esc

def team_link(name):
    """チーム詳細ページがあればリンク。無ければ整形のみ。"""
    name = name.strip()
    tid = TEAM_MAP.get(name)
    formatted = format_team_name(name)
    if tid:
        return f'<a href="/teams/{tid}/" class="team-profile-link">{formatted}</a>'
    return formatted

def detect_winner_and_wrap(s):
    """ "A 3-1 B" / "A 0-1 B" / "A 2-2(PK4-2) B" の勝者を <span class="match-winner"> で強調。
        "A vs B"（試合前）はそのまま。"""
    pk = re.search(r'(\d+)\s*-\s*(\d+)\s*\(\s*PK\s*(\d+)\s*-\s*(\d+)\s*\)', s)
    if pk:
        ss, se = pk.start(), pk.end()
        l, r = int(pk.group(3)), int(pk.group(4))
    else:
        m = re.search(r'(\d+)\s*-\s*(\d+)', s)
        if not m:
            return None  # スコアなし＝未実施
        ss, se = m.start(), m.end()
        l, r = int(m.group(1)), int(m.group(2))
    if l == r:
        return s
    left, center, right = s[:ss], s[ss:se], s[se:]
    if l > r:
        st = left.rstrip(); tw = left[len(st):]
        return f'<span class="match-winner">{st}</span>{tw}{center}{right}'
    else:
        st = right.lstrip(); lw = right[:len(right)-len(st)]
        return f'{left}{center}{lw}<span class="match-winner">{st}</span>'

def linkify_match(match_str):
    """試合行のチーム名をリンク化しつつ勝者強調。
       'A 3-1 B' 形式を分解してチーム名だけリンク化する。"""
    m = re.match(r'^(.*?)(\s*\d+\s*-\s*\d+(?:\s*\(\s*PK\s*\d+\s*-\s*\d+\s*\))?\s*|\s+vs\s+)(.*)$', match_str)
    if not m:
        return html_escape(match_str)
    a, mid, b = m.group(1).strip(), m.group(2), m.group(3).strip()
    a_html, b_html = team_link(a), team_link(b)
    if "vs" in mid:
        return f'{a_html} <span style="color:#888;">vs</span> {b_html}'
    score = mid.strip()
    rebuilt = f'{a_html} <strong style="color:var(--accent-color,#2563eb);">{html_escape(score)}</strong> {b_html}'
    # 勝者強調：プレーンテキストで勝敗判定し、勝った側のhtmlをラップ
    pk = re.search(r'\(\s*PK\s*(\d+)\s*-\s*(\d+)\s*\)', score)
    if pk:
        lwin = int(pk.group(1)) > int(pk.group(2))
        rwin = int(pk.group(2)) > int(pk.group(1))
    else:
        sm = re.search(r'(\d+)\s*-\s*(\d+)', score)
        lwin = int(sm.group(1)) > int(sm.group(2))
        rwin = int(sm.group(2)) > int(sm.group(1))
    if lwin:
        a_html = f'<span class="match-winner">{a_html}</span>'
    elif rwin:
        b_html = f'<span class="match-winner">{b_html}</span>'
    return f'{a_html} <strong style="color:var(--accent-color,#2563eb);">{html_escape(score)}</strong> {b_html}'

def parse_source():
    text = SOURCE.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    # コメント除去
    body_nocomment = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    # セクション分割（## 見出し）。insertion順を保持（dictは3.7+で順序保持）
    sections = {}
    cur = None
    for line in body_nocomment.splitlines():
        h = re.match(r'^##\s+(.*)$', line)
        if h:
            cur = h.group(1).strip()
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(line)
    return meta, sections


# =========================================================================
# 共通：このラウンドは「結果ラウンド」か（各県代表/トーナメント表/歴代優勝を除く）
# =========================================================================
def _is_result_round(name):
    skip = ("各県代表", "トーナメント表", "トーナメント", "歴代優勝")
    return not any(name.startswith(s) for s in skip)


def render_reps(lines):
    items = []
    school_count = 0
    for ln in lines:
        m = re.match(r'^\s*-\s*([^:：]+)[:：]\s*(.+)$', ln)
        if not m:
            continue
        pref = m.group(1).strip()
        schools_raw = m.group(2).strip()
        rendered = []
        for token in re.split(r'[、,]', schools_raw):
            token = token.strip()
            if not token:
                continue
            rm = re.search(r'[（(]([^）)]*)[）)]\s*$', token)
            if rm:
                name = token[:rm.start()].strip()
                record = rm.group(1).strip()
            else:
                name, record = token, ""
            if not name:
                continue
            badge = (f'<span style="font-size:0.82em;color:var(--text-secondary,#6b7280);">（{html_escape(record)}）</span>' if record else "")
            rendered.append(f'<span style="white-space:nowrap;font-weight:600;">{team_link(name)}</span>{badge}')
            school_count += 1
        if not rendered:
            continue
        items.append(
            '<div style="padding:10px 4px;border-bottom:1px solid var(--border-color,#e5e7eb);">'
            f'<div style="color:var(--text-secondary,#6b7280);font-size:0.82em;margin-bottom:2px;">{html_escape(pref)}</div>'
            f'<div style="line-height:1.6;">{"、".join(rendered)}</div>'
            '</div>'
        )
    if not items:
        return '<p style="color:var(--text-secondary,#6b7280);">各県予選の終了後、代表校を順次掲載します。</p>'
    return ('<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:0 28px;">'
            + "\n".join(items) + '</div>'
            + f'<p style="margin-top:10px;color:var(--text-secondary,#6b7280);font-size:0.9em;">出場校 {school_count} 校</p>')

def render_rounds(sections):
    blocks = []
    for name, lines in sections.items():
        if not _is_result_round(name):
            continue
        matches = [ln for ln in lines if re.match(r'^\s*-\s+', ln)]
        rows = []
        for ln in matches:
            content = re.sub(r'^\s*-\s+', '', ln).strip()
            rows.append(f'<li style="padding:10px 12px;border-bottom:1px solid var(--border-color,#e5e7eb);font-size:1.05em;">{linkify_match(content)}</li>')
        if rows:
            blocks.append(f'<h3 style="margin-top:24px;color:var(--accent-color,#2563eb);">{html_escape(name)}</h3>'
                          f'<ul style="list-style:none;padding:0;">' + "\n".join(rows) + '</ul>')
    if not blocks:
        return '<p style="color:var(--text-secondary,#6b7280);">組み合わせ抽選後、トーナメント表と試合結果をここに掲載します（決勝まで随時更新）。</p>'
    return "\n".join(blocks)


# =========================================================================
# ① トーナメント表（組み合わせ表風SVG）自動描画
#    data md の「## トーナメント表（組み合わせ）」を読み、紙の組み合わせ表風SVGを生成。
#    スコアは各ラウンドの結果行から自動照合し、勝者を次のラウンドへ進め、勝ち上がり線を赤で描く。
# =========================================================================
def _norm_team(n):
    """チーム名照合用の正規化（全角半角ゆれ・空白を吸収）"""
    n = unicodedata.normalize("NFKC", n or "")
    return n.replace(" ", "").replace("　", "")


def _short_label(name):
    """表示用の短縮名（U-18/ユース等の共通サフィックスを省いて見やすく）"""
    n = name or ""
    n = re.sub(r'\s*(U-?18|U-?15)\s*$', '', n)
    n = re.sub(r'\s*ユース\s*$', '', n)
    n = n.strip()
    return n or (name or "")


def parse_bracket_pairs(lines):
    """セクションの行を [(名A, 名B or None), ...] に変換。
       「- A vs B」= そのラウンドの対戦カード ／ 「- A」= シード（次のラウンドから）"""
    pairs = []
    for ln in lines:
        m = re.match(r'^\s*-\s+(.*)$', ln)
        if not m:
            continue
        content = m.group(1).strip()
        if not content:
            continue
        content = re.sub(r'[（(]\s*(シード|次から|準々決勝から|準決勝から)\s*[）)]\s*$', '', content).strip()
        sides = re.split(r'\s+vs\s+', content)
        if len(sides) == 2:
            pairs.append((sides[0].strip(), sides[1].strip()))
        else:
            pairs.append((content, None))
    return pairs


def collect_results(sections):
    """各ラウンドのセクションからスコア行を集める。
       戻り値: {frozenset(正規化名2つ): (名A, 点A, 点B, (PK_A,PK_B) or None, 名B)}"""
    res = {}
    for name, lines in sections.items():
        if not _is_result_round(name):
            continue
        for ln in lines:
            m = re.match(r'^\s*-\s+(.*)$', ln)
            if not m:
                continue
            s = m.group(1).strip()
            mm = re.match(
                r'^(.*?)\s+(\d+)\s*-\s*(\d+)'
                r'(?:\s*\(\s*PK\s*(\d+)\s*-\s*(\d+)\s*\))?\s+(.*)$', s)
            if not mm:
                continue
            a = mm.group(1).strip()
            b = mm.group(6).strip()
            ga, gb = int(mm.group(2)), int(mm.group(3))
            pk = (int(mm.group(4)), int(mm.group(5))) if mm.group(4) else None
            key = frozenset((_norm_team(a), _norm_team(b)))
            if len(key) == 2:
                res[key] = (a, ga, gb, pk, b)
    return res


def build_bracket_tree(pairs, results):
    """シード込みのトーナメント木を組み、結果を当てはめて勝者を伝播させる。"""
    n = 1
    while n < len(pairs):
        n *= 2
    if n != len(pairs):
        print(f"⚠ トーナメント表の行数が {len(pairs)} です（8/16などが正常）。空き枠で埋めて描画します。")
        pairs = pairs + [("", None)] * (n - len(pairs))

    base = []
    for a, b in pairs:
        node = {"a": a, "b": b, "bye": b is None, "winner": None, "score": None}
        if b is None and a:
            node["winner"] = a
        base.append(node)

    levels = [base]
    cur = base
    while len(cur) > 1:
        nxt = [{"a": None, "b": None, "bye": False, "winner": None, "score": None}
               for _ in range(len(cur) // 2)]
        levels.append(nxt)
        cur = nxt

    used_keys = set()

    def lookup(a, b):
        if not a or not b:
            return None
        key = frozenset((_norm_team(a), _norm_team(b)))
        r = results.get(key)
        if r is None:
            return None
        used_keys.add(key)
        ra, ga, gb, pk, rb = r
        if _norm_team(ra) == _norm_team(a):
            return ga, gb, pk
        return gb, ga, ((pk[1], pk[0]) if pk else None)

    for li, lvl in enumerate(levels):
        for ni, node in enumerate(lvl):
            if li > 0:
                node["a"] = levels[li - 1][2 * ni].get("winner")
                node["b"] = levels[li - 1][2 * ni + 1].get("winner")
            if node["bye"]:
                continue
            sc = lookup(node["a"], node["b"])
            if sc:
                ga, gb, pk = sc
                node["score"] = f"{ga}-{gb}" + (f"(PK{pk[0]}-{pk[1]})" if pk else "")
                if ga > gb:
                    node["winner"] = node["a"]
                elif gb > ga:
                    node["winner"] = node["b"]
                elif pk:
                    node["winner"] = node["a"] if pk[0] > pk[1] else node["b"]

    for key, r in results.items():
        if key not in used_keys:
            # トーナメント表に無い対戦（前のラウンド等）は警告のみ。表記ゆれの発見に使う。
            pass

    return levels


def _round_names(num_levels):
    """レベル数からラウンド名を決める。
       Jユースは ラウンド16(=3回戦) 始まりの山を想定。
       後ろから 準々決勝・準決勝・決勝、その手前は チーム数からラウンドNN。"""
    tail = ["準々決勝", "準決勝", "決勝"]
    if num_levels <= 3:
        return tail[-num_levels:]
    head = []
    for i in range(num_levels - 3):
        matches_in_level = 2 ** (num_levels - 1 - i)
        head.append(f"ラウンド{matches_in_level * 2}")
    return head + tail


def render_bracket_svg(sections):
    """「## トーナメント表（組み合わせ）」があればSVGトーナメント表のHTMLを返す。無ければ空文字。"""
    lines = None
    for name, ls in sections.items():
        if name.startswith("トーナメント表"):
            lines = ls
            break
    if lines is None:
        return ""
    pairs = parse_bracket_pairs(lines)
    if len(pairs) < 2:
        return ""

    results = collect_results(sections)
    levels = build_bracket_tree(pairs, results)
    num_levels = len(levels)
    wing_levels = num_levels - 1
    names = _round_names(num_levels)

    # ---- レイアウト定数（大きめ・読みやすさ優先） ----
    LABEL_W = 190
    LVL_W = 72
    ROW_H = 28
    TOP = 60
    CENTER_GAP = 168
    width = 2 * (LABEL_W + wing_levels * LVL_W) + CENTER_GAP
    cx = width / 2

    base = levels[0]
    half = len(base) // 2
    wings = {"L": base[:half], "R": base[half:]}

    def assign_base_y(nodes):
        y = TOP
        for nd in nodes:
            if nd["bye"]:
                nd["ya"] = y + ROW_H / 2
                nd["yj"] = nd["ya"]
                y += ROW_H
            else:
                nd["ya"] = y + ROW_H / 2
                nd["yb"] = y + ROW_H * 1.5
                nd["yj"] = (nd["ya"] + nd["yb"]) / 2
                y += 2 * ROW_H
        return y

    bottom = max(assign_base_y(wings["L"]), assign_base_y(wings["R"]))
    height = bottom + 28

    for li in range(1, num_levels):
        for ni, nd in enumerate(levels[li]):
            c1, c2 = levels[li - 1][2 * ni], levels[li - 1][2 * ni + 1]
            nd["yj"] = (c1["yj"] + c2["yj"]) / 2

    xsL = [LABEL_W + (k + 1) * LVL_W for k in range(wing_levels)]
    xsR = [width - x for x in xsL]

    GRAY = "var(--border-color,#9ca3af)"
    RED = "#dc2626"
    TXT = "var(--text-primary,#1f2937)"
    SUB = "var(--text-secondary,#6b7280)"
    ACC = "var(--accent-color,#2563eb)"

    S = []

    def line(x1, y1, x2, y2, color, w=1.6):
        S.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                 f'stroke="{color}" stroke-width="{w}" stroke-linecap="round"/>')

    def text(x, y, s, anchor, size=10.5, color=TXT, weight=""):
        w = f' font-weight="{weight}"' if weight else ""
        S.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
                 f'font-size="{size}" fill="{color}"{w}>{html_escape(s)}</text>')

    def team_text(x, y, name, anchor, won=False):
        if not name:
            return
        label = _short_label(name)
        tid = TEAM_MAP.get(name)
        color = RED if won else (ACC if tid else TXT)
        weight = ' font-weight="700"' if won else (' font-weight="600"' if tid else "")
        body = (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="12.5" '
                f'fill="{color}"{weight}>{html_escape(label)}</text>')
        if tid:
            body = f'<a href="/teams/{tid}/">{body}</a>'
        S.append(body)

    # ---- ラウンド見出し ----
    for k in range(wing_levels):
        x_prev = LABEL_W if k == 0 else xsL[k - 1]
        text((x_prev + xsL[k]) / 2 + LVL_W / 2 - 8, 36, names[k], "middle", 12, SUB, "600")
        x_prevR = width - LABEL_W if k == 0 else xsR[k - 1]
        text((x_prevR + xsR[k]) / 2 - LVL_W / 2 + 8, 36, names[k], "middle", 12, SUB, "600")
    text(cx, 36, names[-1], "middle", 13, SUB, "700")

    # ---- 翼の描画 ----
    def draw_wing(side):
        sign = 1 if side == "L" else -1
        x_edge = LABEL_W if side == "L" else width - LABEL_W
        xs = xsL if side == "L" else xsR
        anchor = "end" if side == "L" else "start"
        tx = x_edge - 5 * sign
        score_anchor = "start" if side == "L" else "end"

        nodes = wings[side]
        for nd in nodes:
            won_a = bool(nd["score"]) and nd.get("winner") == nd["a"]
            won_b = bool(nd["score"]) and nd.get("winner") == nd["b"]
            if nd["bye"]:
                team_text(tx, nd["ya"] + 3.5, nd["a"], anchor)
                line(x_edge, nd["ya"], xs[0], nd["ya"], GRAY)
            else:
                team_text(tx, nd["ya"] + 3.5, nd["a"], anchor, won=won_a)
                team_text(tx, nd["yb"] + 3.5, nd["b"], anchor, won=won_b)
                line(x_edge, nd["ya"], xs[0], nd["ya"], RED if won_a else GRAY, 2.4 if won_a else 1.6)
                line(x_edge, nd["yb"], xs[0], nd["yb"], RED if won_b else GRAY, 2.4 if won_b else 1.6)
                # 縦の連結線（兄弟をつなぐ）。勝者側だけ赤で上書きして勝ち上がりを連続表示
                line(xs[0], nd["ya"], xs[0], nd["yb"], GRAY)
                if nd["score"] and nd.get("winner"):
                    wy = nd["ya"] if won_a else nd["yb"]
                    line(xs[0], wy, xs[0], nd["yj"], RED, 2.4)
                if nd["score"]:
                    text(xs[0] + 3 * sign, nd["yj"] - 4, nd["score"], score_anchor, 10.5, ACC, "700")

        for li in range(0, wing_levels):
            lvl_nodes = levels[li]
            cnt = len(lvl_nodes) // 2
            wing_nodes = lvl_nodes[:cnt] if side == "L" else lvl_nodes[cnt:]
            for nd in wing_nodes:
                x_from = xs[li]
                x_to = xs[li + 1] if li + 1 < wing_levels else cx - sign * 10
                played_win = bool(nd["score"]) and nd.get("winner")
                line(x_from, nd["yj"], x_to, nd["yj"],
                     RED if played_win else GRAY, 2.4 if played_win else 1.6)
                if li >= 1 and nd["score"]:
                    text(x_from + 3 * sign, nd["yj"] - 4, nd["score"], score_anchor, 10.5, ACC, "700")

        for li in range(1, wing_levels):
            lvl_nodes = levels[li]
            cnt = len(lvl_nodes) // 2
            wing_nodes = lvl_nodes[:cnt] if side == "L" else lvl_nodes[cnt:]
            child_lvl = levels[li - 1]
            ccnt = len(child_lvl) // 2
            child_wing = child_lvl[:ccnt] if side == "L" else child_lvl[ccnt:]
            for ni, nd in enumerate(wing_nodes):
                c1, c2 = child_wing[2 * ni], child_wing[2 * ni + 1]
                line(xs[li], c1["yj"], xs[li], c2["yj"], GRAY)
                # 勝者が出た上位ノードは、勝った子の縦線を赤で上書き
                if nd["score"] and nd.get("winner"):
                    win_child = c1 if nd["winner"] == nd["a"] else c2
                    line(xs[li], win_child["yj"], xs[li], nd["yj"], RED, 2.4)

    draw_wing("L")
    draw_wing("R")

    # ---- 決勝（中央） ----
    final = levels[-1][0]
    semiL = levels[-2][0]
    semiR = levels[-2][1]
    ymid = (semiL["yj"] + semiR["yj"]) / 2
    line(cx - 10, semiL["yj"], cx - 10, ymid, GRAY)
    line(cx + 10, semiR["yj"], cx + 10, ymid, GRAY)
    line(cx - 10, ymid, cx + 10, ymid, GRAY)
    # 決勝に勝者が出たら、優勝チームが上がってきた側の中央縦線を赤に
    if final.get("winner"):
        if final["winner"] == final.get("a"):
            line(cx - 10, semiL["yj"], cx - 10, ymid, RED, 2.4)
            line(cx - 10, ymid, cx + 10, ymid, RED, 2.4)
        elif final["winner"] == final.get("b"):
            line(cx + 10, semiR["yj"], cx + 10, ymid, RED, 2.4)
            line(cx - 10, ymid, cx + 10, ymid, RED, 2.4)
    if final["score"]:
        text(cx, ymid + 17, final["score"], "middle", 13, ACC, "700")
    if final.get("winner"):
        text(cx, ymid + 35, f"🏆 {_short_label(final['winner'])}", "middle", 15, RED, "700")

    # PCでは横幅いっぱいまで拡大し、スマホでは min-width で横スクロール
    svg = (f'<svg viewBox="0 0 {width:.0f} {height:.0f}" '
           f'xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="Jユースカップ トーナメント表" '
           f'preserveAspectRatio="xMidYMid meet" '
           f'style="display:block;width:100%;min-width:{width:.0f}px;height:auto;font-family:inherit;">'
           + "".join(S) + '</svg>')

    return (
        '<p style="margin:0 0 8px;color:var(--text-secondary,#6b7280);font-size:0.88em;">'
        '📱 スマホでは表を左右にスクロールできます ／ '
        '<span style="color:#dc2626;font-weight:700;">赤線</span>＝勝ち上がり（結果の入力に合わせて自動で伸びます）</p>'
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;'
        'border:1px solid var(--border-color,#e5e7eb);border-radius:10px;'
        'background:var(--bg-white,#fff);padding:8px 4px;">'
        + svg + '</div>'
    )


# =========================================================================
# ② 「次の試合」上部固定ボックス
#    まだ vs（結果未入力）の試合を含む最初のラウンドを冒頭に大きく表示。
# =========================================================================
def render_next_match(sections):
    for name, lines in sections.items():
        if not _is_result_round(name):
            continue
        vs_lines = []
        for ln in lines:
            m = re.match(r'^\s*-\s+(.*)$', ln)
            if not m:
                continue
            content = m.group(1).strip()
            if re.search(r'\s+vs\s+', content):
                vs_lines.append(content)
        if vs_lines:
            cards = "".join(
                '<li style="padding:9px 6px;border-bottom:1px dashed var(--border-color,#e5e7eb);'
                'font-size:1.05em;text-align:center;">' + linkify_match(c) + '</li>'
                for c in vs_lines
            )
            return (
                '<section class="lp-section" style="background:linear-gradient(135deg,#1e3a8a,#2563eb);'
                'border-radius:12px;padding:18px 18px 10px;color:#fff;margin-bottom:18px;">'
                '<div style="font-size:0.85em;letter-spacing:0.08em;opacity:0.85;margin-bottom:2px;">'
                '<i class="fas fa-bolt"></i> NEXT MATCH ／ 次の試合</div>'
                f'<div style="font-size:1.25em;font-weight:700;margin-bottom:10px;">{html_escape(name)}</div>'
                '<ul style="list-style:none;padding:0;margin:0;background:rgba(255,255,255,0.96);'
                'border-radius:8px;color:var(--text-primary,#1f2937);">'
                f'{cards}</ul>'
                '<p style="margin:8px 2px 4px;font-size:0.82em;opacity:0.9;">'
                '※ 試合終了後、スコアと勝ち上がり（赤線）が自動で反映されます。</p>'
                '</section>'
            )
    return ""


# =========================================================================
# ③ 大会データ・見どころ（結果行から自動集計）
# =========================================================================
def render_stats(sections):
    games = []  # (名A, 点A, 点B, pk or None, 名B, ラウンド名)
    for name, lines in sections.items():
        if not _is_result_round(name):
            continue
        for ln in lines:
            m = re.match(r'^\s*-\s+(.*)$', ln)
            if not m:
                continue
            s = m.group(1).strip()
            mm = re.match(
                r'^(.*?)\s+(\d+)\s*-\s*(\d+)'
                r'(?:\s*\(\s*PK\s*(\d+)\s*-\s*(\d+)\s*\))?\s+(.*)$', s)
            if not mm:
                continue
            a, b = mm.group(1).strip(), mm.group(6).strip()
            ga, gb = int(mm.group(2)), int(mm.group(3))
            pk = (int(mm.group(4)), int(mm.group(5))) if mm.group(4) else None
            games.append((a, ga, gb, pk, b, name))
    if not games:
        return ""

    total_games = len(games)
    total_goals = sum(g[1] + g[2] for g in games)
    pk_games = [g for g in games if g[3]]

    # 大量得点（得失点差トップ3）
    def margin(g):
        return abs(g[1] - g[2])
    big = sorted([g for g in games if margin(g) >= 4], key=margin, reverse=True)[:3]

    # 最長PK戦（合計本数）
    longest_pk = None
    if pk_games:
        longest_pk = max(pk_games, key=lambda g: g[3][0] + g[3][1])

    def card(label, value, sub=""):
        return (
            '<div style="flex:1 1 120px;min-width:120px;text-align:center;padding:12px 8px;'
            'background:var(--bg-white,#fff);border:1px solid var(--border-color,#e5e7eb);border-radius:10px;">'
            f'<div style="font-size:1.7em;font-weight:800;color:var(--accent-color,#2563eb);line-height:1.1;">{value}</div>'
            f'<div style="font-size:0.82em;color:var(--text-secondary,#6b7280);margin-top:4px;">{html_escape(label)}</div>'
            + (f'<div style="font-size:0.74em;color:var(--text-secondary,#9ca3af);margin-top:2px;">{html_escape(sub)}</div>' if sub else "")
            + '</div>'
        )

    avg = total_goals / total_games if total_games else 0
    stat_cards = (
        '<div style="display:flex;flex-wrap:wrap;gap:10px;margin:6px 0 16px;">'
        + card("消化試合", f"{total_games}")
        + card("総ゴール数", f"{total_goals}")
        + card("1試合平均", f"{avg:.1f}")
        + card("PK決着", f"{len(pk_games)}")
        + '</div>'
    )

    rows = []
    def big_winner_str(g):
        a, ga, gb, pk, b, rnd = g
        win, lose, ws, ls = (a, b, ga, gb) if ga > gb else (b, a, gb, ga)
        return (f'<li style="padding:9px 12px;border-bottom:1px solid var(--border-color,#e5e7eb);">'
                f'<span style="display:inline-block;min-width:84px;font-size:0.8em;color:var(--text-secondary,#6b7280);">{html_escape(rnd.split("（")[0])}</span>'
                f'{team_link(win)} <strong style="color:var(--accent-color,#2563eb);">{ws}-{ls}</strong> {team_link(lose)}</li>')
    for g in big:
        rows.append(big_winner_str(g))

    highlight = ""
    if rows:
        highlight += ('<h3 style="margin-top:18px;color:var(--accent-color,#2563eb);">'
                      '<i class="fas fa-fire"></i> 大量得点ゲーム</h3>'
                      '<ul style="list-style:none;padding:0;">' + "".join(rows) + '</ul>')
    if longest_pk:
        a, ga, gb, pk, b, rnd = longest_pk
        highlight += ('<h3 style="margin-top:18px;color:var(--accent-color,#2563eb);">'
                      '<i class="fas fa-bullseye"></i> 死闘のPK戦</h3>'
                      '<ul style="list-style:none;padding:0;">'
                      f'<li style="padding:9px 12px;border-bottom:1px solid var(--border-color,#e5e7eb);">'
                      f'<span style="display:inline-block;min-width:84px;font-size:0.8em;color:var(--text-secondary,#6b7280);">{html_escape(rnd.split("（")[0])}</span>'
                      f'{team_link(a)} <strong style="color:var(--accent-color,#2563eb);">{ga}-{gb}（PK{pk[0]}-{pk[1]}）</strong> {team_link(b)}'
                      f'</li></ul>')

    return stat_cards + highlight


def main():
    meta, sections = parse_source()
    title_main = meta.get("title", "Jユースカップ Jリーグユース選手権大会")
    year = meta.get("year", date.today().year)
    venue = meta.get("venue", "")
    host = meta.get("host", "")
    period = meta.get("period", "")
    status = meta.get("status", "")
    champion = meta.get("champion") or ""
    slots = meta.get("slots", "")
    fmt = meta.get("format", "")
    schedule = meta.get("schedule") or []
    slots_li = f'<li><strong>出場枠</strong>：{html_escape(slots)}</li>' if slots else ""
    format_li = f'<li><strong>大会方式</strong>：{html_escape(fmt)}</li>' if fmt else ""
    if schedule:
        _items = "\n".join(f'<li style="padding:6px 12px;border-bottom:1px solid var(--border-color,#e5e7eb);">{html_escape(x)}</li>' for x in schedule)
        schedule_html = f'<h3 style="margin-top:16px;">📅 日程</h3><ul style="list-style:none;padding:0;">{_items}</ul>'
    else:
        schedule_html = ""

    seo_title = f"Jユースカップ {year} 結果・組み合わせ｜Jリーグユース選手権 トーナメント速報"
    description = (f"Jユースカップ（Jリーグユース選手権大会）{year} の組み合わせ・試合結果を速報でまとめています。"
                  f"{html_escape(period)}開催。Jクラブユース日本一を懸けたトーナメントを決勝まで随時更新。")
    keywords = (f"Jユースカップ {year},Jユースカップ 結果,Jリーグユース選手権,Jユースカップ 組み合わせ,"
                f"Jユースカップ 速報,Jユースカップ トーナメント表,クラブユース,U-18,高校サッカー,{year}")

    # ① SVGトーナメント表（「## トーナメント表（組み合わせ）」が無ければ空）
    bracket_html = render_bracket_svg(sections)
    if bracket_html:
        bracket_section = (
            '<section class="lp-section">'
            '<h2><i class="fas fa-network-wired"></i> 組み合わせトーナメント表</h2>'
            f'{bracket_html}</section>'
        )
    else:
        bracket_section = ""

    # ② 次の試合ボックス
    next_match_html = render_next_match(sections)

    # ③ 大会データ・見どころ
    stats_html = render_stats(sections)
    if stats_html:
        stats_section = (
            '<section class="lp-section">'
            '<h2><i class="fas fa-chart-simple"></i> 大会データ・見どころ</h2>'
            f'{stats_html}</section>'
        )
    else:
        stats_section = ""

    # ラウンド描画（## 1回戦 等の見出しをすべて拾う）
    rounds_html = render_rounds(sections)

    champion_html = ""
    if champion and isinstance(champion, dict) and champion.get("team"):
        champion_html = (f'<div style="text-align:center;padding:16px;margin:16px 0;'
                         f'background:linear-gradient(135deg,#fde68a,#fbbf24);border-radius:10px;'
                         f'font-weight:700;color:#7c2d12;font-size:1.2em;">🏆 全国優勝：{team_link(champion["team"])}</div>')
    elif isinstance(champion, str) and champion.strip():
        champion_html = (f'<div style="text-align:center;padding:16px;margin:16px 0;'
                         f'background:linear-gradient(135deg,#fde68a,#fbbf24);border-radius:10px;'
                         f'font-weight:700;color:#7c2d12;font-size:1.2em;">🏆 全国優勝：{team_link(champion.strip())}</div>')

    status_badge = (f'<span style="display:inline-block;padding:4px 14px;border-radius:999px;'
                    f'background:#dbeafe;color:#1e40af;font-weight:600;font-size:0.9em;">{html_escape(status)}</span>'
                    if status else "")

    # 最終更新日
    today = date.today()
    _wd = "月火水木金土日"[today.weekday()]
    updated_str = f"{today.year}年{today.month}月{today.day}日（{_wd}）"
    updated_html = (f'<p style="text-align:right;color:var(--text-secondary,#6b7280);font-size:0.85em;margin:4px 0 0;">'
                    f'<i class="fas fa-clock"></i> 最終更新：{updated_str}</p>')

    breadcrumb_schema = (
        '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":['
        '{"@type":"ListItem","position":1,"name":"ホーム","item":"' + DOMAIN + '/"},'
        '{"@type":"ListItem","position":2,"name":"Jユースカップ' + str(year) + '","item":"' + CANONICAL + '"}]}'
    )

    # --- FAQ と大会構造化データ（SportsEvent / FAQPage） ---
    import json as _json
    faq_items = [
        (f"Jユースカップ{year}はいつ開催されますか？",
         f"{period} に開催されます。" if period else "日程は確定後に掲載します。"),
        ("出場チームは？", slots or "Jリーグ各クラブのユース（U-18）チームなどが出場します。"),
        ("大会方式は？", fmt or "ノックアウト方式で行われます。"),
        ("試合結果はどこで確認できますか？",
         "このページで組み合わせ・試合結果を随時更新しています。トーナメント表で勝ち上がりも一目で確認できます。各チームの普段のリーグ戦順位は当サイトのリーグ・都道府県別ページで確認できます。"),
    ]
    faq_schema = _json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in faq_items
        ],
    }, ensure_ascii=False)
    _event = {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        "name": title_main,
        "description": description,
        "url": CANONICAL,
        "sport": "サッカー",
        "eventStatus": "https://schema.org/EventScheduled",
        "organizer": {"@type": "Organization", "name": "公益社団法人日本プロサッカーリーグ（Jリーグ）", "url": "https://www.jleague.jp/"},
        "image": [f"{DOMAIN}/og-image.png"],
    }
    if meta.get("start_date"):
        _event["startDate"] = str(meta["start_date"])
    if meta.get("end_date"):
        _event["endDate"] = str(meta["end_date"])
    if venue:
        _event["location"] = {"@type": "Place", "name": venue, "address": host or venue}
    event_schema = _json.dumps(_event, ensure_ascii=False)
    faq_html = "".join(
        '<details style="margin:8px 0;padding:10px 14px;background:var(--bg-white,#fff);'
        'border:1px solid var(--border-color,#e5e7eb);border-radius:8px;">'
        f'<summary style="font-weight:600;cursor:pointer;">{html_escape(q)}</summary>'
        f'<p style="margin:10px 0 4px;line-height:1.8;">{html_escape(a)}</p></details>'
        for q, a in faq_items
    )

    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', '{GA_ID}');
  </script>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT}" crossorigin="anonymous"></script>
  <meta name="google-adsense-account" content="{ADSENSE_CLIENT}">
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html_escape(seo_title)}</title>
  <meta name="description" content="{html_escape(description)}">
  <meta name="keywords" content="{html_escape(keywords)}">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{CANONICAL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="{html_escape(seo_title)}">
  <meta property="og:description" content="{html_escape(description)}">
  <meta property="og:url" content="{CANONICAL}">
  <meta property="og:image" content="https://u18-soccer.com/og-image.png">
  <meta property="og:locale" content="ja_JP">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:title" content="{html_escape(seo_title)}">
  <meta name="twitter:description" content="{html_escape(description)}">
  <meta name="twitter:image" content="https://u18-soccer.com/og-image.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <meta name="theme-color" content="#1e40af">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/css/style.css">
  <script type="application/ld+json">{breadcrumb_schema}</script>
  <script type="application/ld+json">{event_schema}</script>
  <script type="application/ld+json">{faq_schema}</script>
  <script>
    (function() {{
      try {{
        var t = localStorage.getItem('theme');
        if (t === 'light' || t === 'dark') {{ document.documentElement.setAttribute('data-theme', t); }}
      }} catch (e) {{}}
    }})();
  </script>
</head>
<body>
  <header class="header">
    <div class="container">
      <div class="header-content">
        <div class="site-title">
          <a href="/" style="color:white;text-decoration:none;display:inline-flex;align-items:center;gap:10px">
            <i class="fas fa-futbol"></i> 高校サッカー順位確認システム
          </a>
        </div>
        <nav class="nav">
          <a href="/" class="nav-link"><i class="fas fa-home"></i> ホーム</a>
          <a href="/leagues/" class="nav-link"><i class="fas fa-trophy"></i> リーグ一覧</a>
        </nav>
      </div>
    </div>
  </header>
  <main class="main-content">
    <div class="container">
      <nav class="breadcrumb" aria-label="パンくずリスト">
        <a href="/">ホーム</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">Jユースカップ{year}</span>
      </nav>
      <h1 class="lp-title">{html_escape(title_main)}</h1>
      {updated_html}
      <p class="lp-intro">
        <strong>Jユースカップ（Jリーグユース選手権大会）</strong>{year} の組み合わせ・試合結果をまとめています。
        Jクラブのユースチームが日本一を懸けて戦うノックアウトトーナメント。各チームの普段のリーグ戦成績は
        <a href="/leagues/">リーグ一覧</a>・<a href="/">都道府県別ページ</a>からご確認いただけます。
      </p>

      {next_match_html}

      <section class="lp-section">
        <h2><i class="fas fa-circle-info"></i> 大会概要 {status_badge}</h2>
        <ul style="list-style:none;padding:0;line-height:2;">
          <li><strong>大会名</strong>：{html_escape(title_main)}</li>
          <li><strong>会期</strong>：{html_escape(period) or '日程確定後に掲載'}</li>
          <li><strong>開催地</strong>：{html_escape(venue) or '確定後に掲載'}{(' / ' + html_escape(host)) if host else ''}</li>
          {slots_li}
          {format_li}
        </ul>
        {schedule_html}
        {champion_html}
      </section>

      {bracket_section}

      {stats_section}

      <section class="lp-section">
        <h2><i class="fas fa-sitemap"></i> トーナメント・試合結果</h2>
        {rounds_html}
      </section>

      <section class="lp-section">
        <h2><i class="fas fa-circle-question"></i> よくある質問</h2>
        {faq_html}
      </section>

      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/">全国47都道府県の高校サッカー順位・予選結果</a></li>
          <li><a href="/leagues/">リーグ一覧（プレミア・プリンス）</a></li>
          <li><a href="/blog/">ブログ・医学コラム</a></li>
          <li><a href="/tournaments/interhigh-2026/">インターハイ2026 全国大会 速報・結果</a></li>
          <li><a href="https://www.jleague.jp/jyouth/" target="_blank" rel="noopener">Jユースカップ公式（Jリーグ）</a></li>
        </ul>
      </section>
    </div>
  </main>
  <footer class="footer">
    <div class="container">
      <p>&copy; 2025-2026 高校サッカー順位確認システム</p>
      <nav class="footer-nav" style="margin-top:12px;">
        <a href="/about.html">運営者情報</a> ・
        <a href="/privacy.html">プライバシーポリシー</a> ・
        <a href="/contact.html">お問い合わせ</a>
      </nav>
    </div>
  </footer>
  <script src="/js/main.js" defer></script>
</body>
</html>
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(page, encoding="utf-8")
    print(f"✅ 生成: {OUT_DIR / 'index.html'}")

    # --- sitemap に登録（idempotent） ---
    sm = BASE_DIR / "sitemap.xml"
    if sm.exists():
        s = sm.read_text(encoding="utf-8")
        if CANONICAL not in s:
            entry = f"  <url>\n    <loc>{CANONICAL}</loc>\n    <lastmod>{date.today().isoformat()}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>\n"
            s = s.replace("</urlset>", entry + "</urlset>")
            sm.write_text(s, encoding="utf-8")
            print("✅ sitemap.xml に登録")
        else:
            print("ℹ️ sitemap.xml は登録済み")

if __name__ == "__main__":
    main()
