#!/usr/bin/env python3
"""
インターハイ本選（全国大会）専用ページ生成スクリプト
====================================================
data/tournaments/interhigh-final-2026.md を読み込み、
独立ページ /tournaments/interhigh-2026/ を生成する。

- 「各県代表」セクション：県名: 学校名 を一覧化(学校はチーム詳細へ自動リンク)
- 「トーナメント表(組み合わせ)」セクション：紙の組み合わせ表風のSVGトーナメント表を自動描画
  (スコアは各ラウンドの結果行から自動照合し、勝ち上がり線を赤で描く)
- 「トーナメント」セクション：予選と同じ書式の試合行を描画し、スコアから勝者を自動ハイライト
- まだ組み合わせ未定でも「準備中」表示で正しく出力される

依存：標準ライブラリ + PyYAML
"""
import re
import json
import unicodedata
import yaml
from pathlib import Path
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


class _JSTDate:
    """GitHubのサーバーは世界標準時のため、日本時間の「今日」を返す"""
    @staticmethod
    def today():
        return _dt.now(_tz(_td(hours=9))).date()


date = _JSTDate

BASE_DIR = Path(__file__).parent.parent
DOMAIN = "https://u18-soccer.com"
GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"

SOURCE = BASE_DIR / "data" / "tournaments" / "interhigh-final-2026.md"
OUT_DIR = BASE_DIR / "tournaments" / "interhigh-2026"
CANONICAL = f"{DOMAIN}/tournaments/interhigh-2026/"

# ============================================================
# インターハイページの観戦コラム(複数記事を一括表示)
# 上から順に表示される。新しい記事は配列の先頭に追加してください。
# ============================================================
INTERHIGH_FEATURED_ARTICLES = [
    {
        "title": '【2026インターハイ優勝候補・注目校】プレミア7校が本命｜リーグ階層で読む全国大会の構図',
        "url": "/blog/posts/interhigh-2026-preview/",
        "date": "2026-06-18",
    },
    {
        "title": '【2026インハイ予選総括】47都道府県代表校完全リスト｜W杯OB母校7校・伝統校復活・新興校台頭の全体像',
        "url": "/blog/posts/interhigh-2026-summary/",
        "date": "2026-06-19",
    },
    {
        "title": '【2026W杯開幕】日本代表26人は"どこから"来たのか｜全員の出身高校・ユース完全ガイド',
        "url": "/blog/posts/worldcup-2026-japan-roots/",
        "date": "2026-06-10",
    },
    {
        "title": "【医学コラム】真夏のインターハイ暑熱対策ガイド｜選手・保護者・指導者向け",
        "url": "/blog/posts/interhigh-2026-heat-safety/",
        "date": "2026-05-15",
    },
]


def render_featured_articles_section():
    """インターハイページの観戦コラムセクションHTMLを返す。記事がなければ空文字を返す。"""
    if not INTERHIGH_FEATURED_ARTICLES:
        return ""
    items = "\n".join([
        f'          <li><a href="{a["url"]}">{a["title"]}</a> '
        f'<span style="color:#999;font-size:0.9em;">（{a["date"]}）</span></li>'
        for a in INTERHIGH_FEATURED_ARTICLES
    ])
    return f"""
      <section class="lp-section">
        <h2><i class="fas fa-book-open"></i> 観戦コラム</h2>
        <p style="color:var(--text-secondary,#6b7280);margin-bottom:12px;">本大会をより楽しむための特集記事をまとめています。</p>
        <ul class="lp-related-links">
{items}
        </ul>
      </section>
"""


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
        "A vs B"(試合前)はそのまま。"""
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
    # 校名の直後に付ける所属リーグ（県・リーグ短縮）。勝者強調の枠の外側に置く。
    sa, sb = league_suffix(a), league_suffix(b)
    if "vs" in mid:
        return f'{a_html}{sa} <span style="color:#888;">vs</span> {b_html}{sb}'
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
    return f'{a_html}{sa} <strong style="color:var(--accent-color,#2563eb);">{html_escape(score)}</strong> {b_html}{sb}'

def parse_source():
    text = SOURCE.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    # コメント除去
    body_nocomment = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    # セクション分割(## 見出し)
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

PREF_SLUG = {
    "北海道": "hokkaido", "青森": "aomori", "岩手": "iwate", "宮城": "miyagi",
    "秋田": "akita", "山形": "yamagata", "福島": "fukushima", "茨城": "ibaraki",
    "栃木": "tochigi", "群馬": "gunma", "埼玉": "saitama", "千葉": "chiba",
    "東京": "tokyo", "神奈川": "kanagawa", "新潟": "niigata", "富山": "toyama",
    "石川": "ishikawa", "福井": "fukui", "山梨": "yamanashi", "長野": "nagano",
    "岐阜": "gifu", "静岡": "shizuoka", "愛知": "aichi", "三重": "mie",
    "滋賀": "shiga", "京都": "kyoto", "大阪": "osaka", "兵庫": "hyogo",
    "奈良": "nara", "和歌山": "wakayama", "鳥取": "tottori", "島根": "shimane",
    "岡山": "okayama", "広島": "hiroshima", "山口": "yamaguchi", "徳島": "tokushima",
    "香川": "kagawa", "愛媛": "ehime", "高知": "kochi", "福岡": "fukuoka",
    "佐賀": "saga", "長崎": "nagasaki", "熊本": "kumamoto", "大分": "oita",
    "宮崎": "miyazaki", "鹿児島": "kagoshima", "沖縄": "okinawa",
}


def pref_slug(pref_name):
    """県名（「岩手」「東京都」等）から都道府県ページのスラッグを返す。不明ならNone。"""
    key = (pref_name or "").strip()
    if key in PREF_SLUG:
        return PREF_SLUG[key]
    if key and key[-1] in "都府県" and key[:-1] in PREF_SLUG:
        return PREF_SLUG[key[:-1]]
    return None


def pref_heading(pref):
    """各県代表セクションの県名見出し。県ページが分かればリンクにする（内部リンク分配）。"""
    disp = html_escape(pref)
    slug = pref_slug(pref)
    if slug:
        return (f'<a href="/prefectures/{slug}/" '
                f'style="color:var(--accent-color,#2563eb);text-decoration:none;font-weight:600;">'
                f'{disp}の予選結果・順位 ›</a>')
    return disp

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
            # 末尾の（記録）または(記録)を分離
            rm = re.search(r'[（(]([^）)]*)[）)]\s*$', token)
            if rm:
                name = token[:rm.start()].strip()
                record = rm.group(1).strip()
            else:
                name, record = token, ""
            if not name:
                continue
            badge = (f'<span style="font-size:0.82em;color:var(--text-secondary,#6b7280);white-space:nowrap;">({html_escape(record)})</span>' if record else "")
            # 学校名は途中で折り返さない(nowrap)。記録バッジは別要素で必要時のみ改行。
            # 校名の直後に所属リーグ（県・リーグ短縮）を表示。pref は見出しの県名を優先。
            rendered.append(f'<span style="white-space:nowrap;font-weight:600;">{team_link(name)}</span>{league_suffix(name, pref)}{badge}')
            school_count += 1
        if not rendered:
            continue
        items.append(
            '<div style="padding:10px 4px;border-bottom:1px solid var(--border-color,#e5e7eb);">'
            f'<div style="color:var(--text-secondary,#6b7280);font-size:0.82em;margin-bottom:2px;">{pref_heading(pref)}</div>'
            f'<div style="line-height:1.6;">{"、".join(rendered)}</div>'
            '</div>'
        )
    if not items:
        return '<p style="color:var(--text-secondary,#6b7280);">各県予選の終了後、代表校を順次掲載します。</p>'
    # 画面幅に応じて自動で1〜2カラム(モバイル=1列、PC=2列)。multi-columnの途中改行を回避。
    return ('<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:0 28px;">'
            + "\n".join(items) + '</div>'
            + f'<p style="margin-top:10px;color:var(--text-secondary,#6b7280);font-size:0.9em;">出場校 {school_count} 校</p>')

def render_rounds(sections):
    blocks = []
    for name, lines in sections.items():
        if name.startswith("各県代表") or name.startswith("トーナメント"):
            continue
        # ラウンド見出し(## 1回戦(8/1) 等)のみ対象
        matches = [ln for ln in lines if re.match(r'^\s*-\s+', ln)]
        rows = []
        for ln in matches:
            content = re.sub(r'^\s*-\s+', '', ln).strip()
            rows.append(f'<li style="padding:10px 12px;border-bottom:1px solid var(--border-color,#e5e7eb);font-size:1.05em;">{linkify_match(content)}</li>')
        if rows:
            blocks.append(f'<h3 style="margin-top:24px;color:var(--accent-color,#2563eb);">{html_escape(name)}</h3>'
                          f'<ul style="list-style:none;padding:0;">' + "\n".join(rows) + '</ul>')
    if not blocks:
        return '<p style="color:var(--text-secondary,#6b7280);">組み合わせ抽選後、トーナメント表と試合結果をここに掲載します(決勝まで随時更新)。</p>'
    return "\n".join(blocks)


# =========================================================================
# トーナメント表(組み合わせ表風SVG)自動描画
# data md の「## トーナメント表(組み合わせ)」セクションを読み、
# 紙の組み合わせ表のようなSVGを生成する。
# スコアは各ラウンドの結果行(- A 2-1 B)からチーム名で自動照合し、
# 勝者を次のラウンドへ自動で進め、勝ち上がり線を赤で描く。
# =========================================================================

def _norm_team(n):
    """チーム名照合用の正規化(全角半角ゆれ・空白を吸収)"""
    n = unicodedata.normalize("NFKC", n or "")
    return n.replace(" ", "").replace("　", "")


def _short_label(name):
    """表示用の短縮名(紙の組み合わせ表と同じく「高校」等を省く)"""
    n = re.sub(r'(高等学校|高等部|高校)$', '', name or "")
    return n or (name or "")


# =========================================================================
# 所属リーグ表示(データ：data/teams.json の各チーム "league")
#  ・各県代表リスト／試合結果欄に「（県・リーグ短縮）」を付ける。
#  ・短縮ルール：
#     プレミアリーグWEST       → プレミアWEST     (「リーグ」を省く)
#     プリンスリーグ九州2部     → プリンス九州2部   (「リーグ」を省く)
#     山口県1部 / 沖縄県波布リーグ2部 / T2リーグ(東京都2部)
#                              → 県1部 / 県2部 …  (末尾の「N部」の数字を拾う)
# =========================================================================

# スラッグ(英字)→ 県名(日本語・短縮形)の逆引き表
SLUG_TO_PREF = {v: k for k, v in PREF_SLUG.items()}


def _short_league(league):
    """正式リーグ名を表示用の短い名前に変換する。"""
    if not league:
        return ""
    s = unicodedata.normalize("NFKC", str(league)).strip()
    if "プレミア" in s:
        # 「プレミア」以降だけを残し、「リーグ」の語を省く
        return s[s.index("プレミア"):].replace("リーグ", "")
    if "プリンス" in s:
        return s[s.index("プリンス"):].replace("リーグ", "")
    # 県リーグ系：末尾付近の「N部」の数字を拾って「県N部」に
    m = re.search(r'(\d+)\s*部', s)
    if m:
        return f"県{m.group(1)}部"
    return "県1部"


def load_school_league_map() -> dict:
    """data/teams.json から {正規化校名: (県名, 短縮リーグ名)} を作る。
       name と aliases の両方を見出しに登録する。"""
    p = BASE_DIR / "data" / "teams.json"
    school_map = {}
    if not p.exists():
        return school_map
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return school_map
    for slug, pref in (data or {}).items():
        if not isinstance(pref, dict):
            continue
        pref_jp = SLUG_TO_PREF.get(slug, "")
        for t in (pref.get("teams") or []):
            short_lg = _short_league(t.get("league"))
            if not short_lg:
                continue
            names = [t.get("name")] + list(t.get("aliases") or [])
            for nm in names:
                if nm:
                    school_map.setdefault(_norm_team(nm), (pref_jp, short_lg))
    return school_map


SCHOOL_LEAGUE_MAP = load_school_league_map()


def league_suffix(name, pref=None):
    """校名の後ろに付ける「（県・リーグ短縮）」のHTMLを返す。
       teams.json に見つからない校は空文字(従来表示のまま)。"""
    meta = SCHOOL_LEAGUE_MAP.get(_norm_team(name or ""))
    if not meta:
        return ""
    map_pref, short_lg = meta
    p = (pref or map_pref or "").strip()
    if p and p[-1] in "都府県" and p[:-1] in PREF_SLUG:
        p = p[:-1]  # 「東京都」→「東京」等
    inner = f"{p}・{short_lg}" if p else short_lg
    return (f'<span style="font-size:0.82em;color:var(--text-secondary,#6b7280);'
            f'white-space:nowrap;">（{html_escape(inner)}）</span>')


def parse_bracket_pairs(lines):
    """セクションの行を [(校名A, 校名B or None), ...] に変換。
       「- A vs B」= 1回戦の対戦カード ／ 「- A」= シード(2回戦から登場)"""
    pairs = []
    for ln in lines:
        m = re.match(r'^\s*-\s+(.*)$', ln)
        if not m:
            continue
        content = m.group(1).strip()
        if not content:
            continue
        content = re.sub(r'[（(]\s*(シード|２回戦から|2回戦から)\s*[）)]\s*$', '', content).strip()
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
        if name.startswith("各県代表") or name.startswith("トーナメント"):
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


def parse_pref_map(reps_lines):
    """各県代表セクションから {正規化校名: 県名} を作る(表示用)"""
    pref_map = {}
    for ln in reps_lines:
        m = re.match(r'^\s*-\s*([^:：]+)[:：]\s*(.+)$', ln)
        if not m:
            continue
        pref = m.group(1).strip()
        for token in re.split(r'[、,]', m.group(2).strip()):
            token = token.strip()
            if not token:
                continue
            rm = re.search(r'[（(]([^）)]*)[）)]\s*$', token)
            name = token[:rm.start()].strip() if rm else token
            if name:
                pref_map[_norm_team(name)] = pref
    return pref_map


def build_bracket_tree(pairs, results):
    """シード込みのトーナメント木を組み、結果を当てはめて勝者を伝播させる。"""
    n = 1
    while n < len(pairs):
        n *= 2
    if n != len(pairs):
        print(f"⚠ トーナメント表の行数が {len(pairs)} です(16/32などが正常)。空き枠で埋めて描画します。")
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
            print(f"⚠ 結果行がトーナメント表のどの対戦とも一致しません: {r[0]} vs {r[4]}"
                  f"(校名の表記ゆれ、または前のラウンドの結果が未入力の可能性)")

    return levels


def _round_names(num_levels):
    """レベル数からラウンド名を決める(後ろから 決勝・準決勝・準々決勝)"""
    tail = ["準々決勝", "準決勝", "決勝"]
    if num_levels <= 3:
        return tail[-num_levels:]
    head = [f"{i+1}回戦" for i in range(num_levels - 3)]
    return head + tail


def render_bracket_svg(sections, reps_lines):
    """「## トーナメント表(組み合わせ)」があればSVGトーナメント表のHTMLを返す。無ければ空文字。"""
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
    pref_map = parse_pref_map(reps_lines)
    num_levels = len(levels)
    wing_levels = num_levels - 1
    names = _round_names(num_levels)

    # ---- レイアウト定数 ----
    LABEL_W = 168
    LVL_W = 58
    ROW_H = 21
    TOP = 56
    CENTER_GAP = 150
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

    # 左右の翼で校数が違うと2つの準決勝ノードの高さがずれ、決勝中央の
    # 接続線が歪む。左右の翼を反対方向へ半分ずつ寄せ、準決勝の高さを揃える。
    if num_levels >= 2:
        _dy = (levels[-2][1]["yj"] - levels[-2][0]["yj"]) / 2
        if abs(_dy) > 0.01:
            for _li in range(num_levels - 1):
                _lvl = levels[_li]
                _cnt = len(_lvl) // 2
                for _i, _nd in enumerate(_lvl):
                    _s = _dy if _i < _cnt else -_dy
                    if "ya" in _nd:
                        _nd["ya"] += _s
                    if "yb" in _nd:
                        _nd["yb"] += _s
                    _nd["yj"] += _s

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
        pref = pref_map.get(_norm_team(name), "")
        tid = TEAM_MAP.get(name)
        color = RED if won else (ACC if tid else TXT)
        weight = ' font-weight="700"' if won else (' font-weight="600"' if tid else "")
        body = (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="10.5" '
                f'fill="{color}"{weight}>{html_escape(label)}'
                + (f'<tspan font-size="8.5" fill="{SUB}" font-weight="400">［{html_escape(pref)}］</tspan>' if pref else "")
                + '</text>')
        if tid:
            body = f'<a href="/teams/{tid}/">{body}</a>'
        S.append(body)

    # ---- ラウンド見出し ----
    for k in range(wing_levels):
        x_prev = LABEL_W if k == 0 else xsL[k - 1]
        text((x_prev + xsL[k]) / 2 + LVL_W / 2 - 8, 34, names[k], "middle", 10, SUB, "600")
        x_prevR = width - LABEL_W if k == 0 else xsR[k - 1]
        text((x_prevR + xsR[k]) / 2 - LVL_W / 2 + 8, 34, names[k], "middle", 10, SUB, "600")
    text(cx, 34, names[-1], "middle", 11, SUB, "700")

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
                line(x_edge, nd["ya"], xs[0], nd["ya"], RED if won_a else GRAY, 2.2 if won_a else 1.6)
                line(x_edge, nd["yb"], xs[0], nd["yb"], RED if won_b else GRAY, 2.2 if won_b else 1.6)
                line(xs[0], nd["ya"], xs[0], nd["yb"], GRAY)
                if nd["score"]:
                    text(xs[0] + 3 * sign, nd["yj"] - 3.5, nd["score"], score_anchor, 8.5, ACC, "700")

        # 前進線(各レベルのノードの yj に沿って次の列へ)＋ 上位レベルのスコア
        final_champ = levels[-1][0].get("winner")
        for li in range(0, wing_levels):
            lvl_nodes = levels[li]
            cnt = len(lvl_nodes) // 2
            wing_nodes = lvl_nodes[:cnt] if side == "L" else lvl_nodes[cnt:]
            for nd in wing_nodes:
                x_from = xs[li]
                if li + 1 < wing_levels:
                    x_to = xs[li + 1]
                    seg_red = bool(nd["score"]) and nd.get("winner")
                else:
                    # 準決勝→決勝：両者とも中央まで引く。赤は優勝校だけ（敗者は灰で連結）
                    x_to = cx - sign * 10
                    seg_red = bool(final_champ) and nd.get("winner") == final_champ
                line(x_from, nd["yj"], x_to, nd["yj"],
                     RED if seg_red else GRAY, 2.2 if seg_red else 1.6)
                if li >= 1 and nd["score"]:
                    text(x_from + 3 * sign, nd["yj"] - 3.5, nd["score"], score_anchor, 8.5, ACC, "700")

        # 縦の接続線(レベル1以上：子2つの yj を結ぶ)
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

    draw_wing("L")
    draw_wing("R")

    # ---- 決勝(中央) ----
    final = levels[-1][0]
    semiL = levels[-2][0]
    semiR = levels[-2][1]
    ymid = (semiL["yj"] + semiR["yj"]) / 2
    champ = final.get("winner")
    # 両決勝進出チームを中央へ連結。優勝校側は赤、敗者側は灰。
    left_red = bool(champ) and champ == final.get("a")
    right_red = bool(champ) and champ == final.get("b")
    line(cx - 10, semiL["yj"], cx - 10, ymid, RED if left_red else GRAY, 2.4 if left_red else 1.6)
    line(cx - 10, ymid, cx, ymid, RED if left_red else GRAY, 2.4 if left_red else 1.6)
    line(cx + 10, semiR["yj"], cx + 10, ymid, RED if right_red else GRAY, 2.4 if right_red else 1.6)
    line(cx, ymid, cx + 10, ymid, RED if right_red else GRAY, 2.4 if right_red else 1.6)
    if final["score"]:
        text(cx, ymid + 16, final["score"], "middle", 11, ACC, "700")
    # 優勝校は中央の連結点から上へ1本線を伸ばし、その先に表示
    if champ:
        stem_top = ymid - 28
        line(cx, ymid, cx, stem_top, RED, 2.4)
        text(cx, stem_top - 7, f"🏆 {_short_label(champ)}", "middle", 13, RED, "700")

    svg = (f'<svg viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" '
           f'xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="トーナメント表" style="display:block;font-family:inherit;">'
           + "".join(S) + '</svg>')

    return (
        '<p style="margin:0 0 8px;color:var(--text-secondary,#6b7280);font-size:0.88em;">'
        '📱 スマホでは表を左右にスクロールできます ／ '
        '<span style="color:#dc2626;font-weight:700;">赤線</span>＝勝ち上がり(結果の入力に合わせて自動で伸びます)</p>'
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;'
        'border:1px solid var(--border-color,#e5e7eb);border-radius:10px;'
        'background:var(--bg-white,#fff);padding:8px 4px;">'
        + svg + '</div>'
    )


# =========================================================================
# AI引用向け一文要約(H1直下)。毎日の大会状況から自動生成。
#   - プレミア/県別/Jユースページの「lp-lead-summary」と同じ見た目。
#   - 優勝決定後／開催中(勝ち上がり)／開催前(代表校・会期) を自動で切替。
# =========================================================================
def _summary_p(body):
    style = (
        "margin:0 0 18px;padding:12px 16px;background:var(--bg-light,#f1f5fb);"
        "border-left:4px solid var(--primary-color,#1e40af);border-radius:0 8px 8px 0;"
        "font-size:0.95rem;line-height:1.8;"
    )
    return f'      <p class="lp-lead-summary" style="{style}">{body}</p>\n'


def _is_result_round(name):
    return not (name.startswith("各県代表") or name.startswith("トーナメント") or name.startswith("歴代優勝"))


def _round_winners(lines):
    """ラウンドのスコア行から勝者名のリストを返す(PK含む)。"""
    winners = []
    for ln in lines:
        mm = re.match(r'^\s*-\s+(.*?)\s+(\d+)\s*-\s*(\d+)'
                      r'(?:\s*\(\s*PK\s*(\d+)\s*-\s*(\d+)\s*\))?\s+(.*)$', ln.strip())
        if not mm:
            continue
        a, ga, gb, b = mm.group(1).strip(), int(mm.group(2)), int(mm.group(3)), mm.group(6).strip()
        if ga > gb:
            winners.append(a)
        elif gb > ga:
            winners.append(b)
        elif mm.group(4):
            winners.append(a if int(mm.group(4)) > int(mm.group(5)) else b)
    return winners


def build_ai_summary(meta, sections):
    title_main = meta.get("title", "全国高校総体 サッカー競技大会(男子)")
    period = meta.get("period", "")
    venue = meta.get("venue", "")
    host = meta.get("host", "")
    slots = meta.get("slots", "")
    d = date.today()
    date_str = f"{d.year}年{d.month}月{d.day}日"

    # ① 優勝が確定していれば優勝校を主役に
    champion = meta.get("champion") or ""
    champ_name = champion.get("team", "") if isinstance(champion, dict) else (champion.strip() if isinstance(champion, str) else "")
    if champ_name:
        body = (f"【{date_str}時点】{html_escape(title_main)}は{html_escape(champ_name)}が優勝。"
                f"組み合わせ・トーナメント表・全試合結果をまとめています。")
        return _summary_p(body)

    # ② 開催中：まだ vs(未実施)が残る最初のラウンド＝勝ち上がった顔ぶれ
    next_name, next_teams = None, []
    for name, lines in sections.items():
        if not _is_result_round(name):
            continue
        teams = []
        for ln in lines:
            mm = re.match(r'^\s*-\s+(.*?)\s+vs\s+(.*)$', ln.strip())
            if mm:
                teams += [mm.group(1).strip(), mm.group(2).strip()]
        if teams:
            next_name, next_teams = name, teams
            break
    if next_name:
        round_word = re.split(r'[（(]', next_name)[0].strip()
        n = len(next_teams)
        stage = {16: "ベスト16", 8: "ベスト8", 4: "ベスト4", 2: "決勝"}.get(n, f"{n}校")
        if n <= 12:
            teams_str = "・".join(html_escape(t) for t in next_teams)
            mid = f"勝ち上がった{n}校は{teams_str}。"
        else:
            mid = f"{n}校が勝ち上がっています。"
        body = (f"【{date_str}時点】{html_escape(title_main)}は{round_word}({stage})の組み合わせが決定。{mid}"
                f"各都道府県の予選を勝ち抜いた代表校が日本一を争うノックアウト方式の"
                f"組み合わせ・トーナメント表・結果を毎日更新。")
        return _summary_p(body)

    # ②' ラウンド間(直近ラウンドは終了・次節未掲載)：直近ラウンドの勝ち残りを要約
    latest_name, latest_lines = None, None
    for name, lines in sections.items():
        if not _is_result_round(name):
            continue
        if any(re.search(r'\d+\s*-\s*\d+', l) for l in lines):
            latest_name, latest_lines = name, lines
    if latest_name:
        winners = _round_winners(latest_lines)
        n = len(winners)
        round_word = re.split(r'[（(]', latest_name)[0].strip()
        stage = {8: "ベスト8", 4: "ベスト4", 2: "決勝進出の2校", 1: "優勝"}.get(n, f"{n}校")
        if winners and n <= 8:
            teams_str = "・".join(html_escape(t) for t in winners)
            body = (f"【{date_str}時点】{html_escape(title_main)}は{round_word}が終了し、{stage}が決定。"
                    f"勝ち残りは{teams_str}。組み合わせ・トーナメント表・結果を毎日更新。")
        else:
            body = (f"【{date_str}時点】{html_escape(title_main)}は{round_word}まで終了。"
                    f"組み合わせ・トーナメント表・結果を毎日更新。")
        return _summary_p(body)

    # ③ 開催前：判明している各県代表・会期・会場・出場枠から要約
    reps_lines = sections.get("各県代表", [])
    rep_names = []
    for ln in reps_lines:
        m = re.match(r'^\s*-\s*([^:：]+)[:：]\s*(.+)$', ln)
        if not m:
            continue
        for token in re.split(r'[、,]', m.group(2).strip()):
            token = token.strip()
            if not token:
                continue
            rm = re.search(r'[（(][^）)]*[）)]\s*$', token)
            nm = token[:rm.start()].strip() if rm else token
            if nm:
                rep_names.append(nm)

    loc = re.sub(r'[（(].*$', '', host).strip() if host else re.split(r'[／/（(]', venue)[0].strip()
    if venue and "Jヴィレッジ" in venue and loc and "Jヴィレッジ" not in loc:
        loc = f"{loc}・Jヴィレッジ"
    # 「(計51チーム)」を優先。無ければ「○チーム」表記の最大値を採用("1チーム"等の誤取得を防ぐ)
    cnt_m = re.search(r'計\s*(\d+)', slots)
    if cnt_m:
        teams_count = cnt_m.group(1)
    else:
        nums = re.findall(r'(\d+)\s*チーム', slots)
        teams_count = max(nums, key=int) if nums else ""

    parts = [f"【{date_str}時点】{html_escape(title_main)}は"]
    if period:
        parts.append(f"{html_escape(period)}に")
    if loc:
        parts.append(f"{html_escape(loc)}で開催。")
    else:
        parts.append("開催予定。")
    if teams_count:
        parts.append(f"各都道府県代表の計{teams_count}チームがノックアウト方式で全国一を争います。")
    else:
        parts.append("各都道府県の代表校がノックアウト方式で全国一を争います。")
    if rep_names:
        sample = "・".join(html_escape(x) for x in rep_names[:6])
        parts.append(f"現在までに{sample}など{len(rep_names)}校の出場が決定。")
    parts.append("組み合わせ・トーナメント表・結果を毎日更新。")
    return _summary_p("".join(parts))


def main():
    meta, sections = parse_source()
    title_main = meta.get("title", "全国高校総体 サッカー競技")
    year = meta.get("year", date.today().year)
    venue = meta.get("venue", "")
    host = meta.get("host", "")
    period = meta.get("period", "")
    status = meta.get("status", "")
    champion = meta.get("champion") or ""
    slots = meta.get("slots", "")
    fmt = meta.get("format", "")
    schedule = meta.get("schedule") or []
    slots_li = f'<li><strong>出場枠</strong>:{html_escape(slots)}</li>' if slots else ""
    format_li = f'<li><strong>大会方式</strong>:{html_escape(fmt)}</li>' if fmt else ""
    if schedule:
        _items = "\n".join(f'<li style="padding:6px 12px;border-bottom:1px solid var(--border-color,#e5e7eb);">{html_escape(x)}</li>' for x in schedule)
        schedule_html = f'<h3 style="margin-top:16px;">📅 日程</h3><ul style="list-style:none;padding:0;">{_items}</ul>'
    else:
        schedule_html = ""

    seo_title = f"インターハイ サッカー{year} 結果・組み合わせ・トーナメント表【最新】｜全国高校総体(男子)速報"
    description = (f"高校総体(インターハイ)サッカー競技 男子{year} 全国大会(本選)の組み合わせ・試合結果・"
                  f"トーナメント表・各県代表校を毎日自動更新。各都道府県代表の計51校が福島・Jヴィレッジで"
                  f"全国一を争うノックアウト方式。{html_escape(period)}開催。決勝まで随時更新。")
    keywords = (f"インターハイ サッカー{year},全国高校総体 サッカー,高校総体 サッカー 結果,"
                f"インターハイ サッカー トーナメント表,インターハイ サッカー 組み合わせ,"
                f"インターハイ サッカー 速報,インターハイ サッカー 代表校,高校サッカー,U-18,{year}")

    # AI引用向け一文要約(H1直下・毎日自動更新)
    ai_summary_html = build_ai_summary(meta, sections)

    # 観戦コラムセクション(大会概要の直後に表示)
    featured_articles_section = render_featured_articles_section()

    # 代表校・ラウンド
    reps_lines = sections.get("各県代表", [])
    # トーナメント見出し名のゆれ吸収
    reps_html = render_reps(reps_lines)
    rounds_html = render_rounds(sections)

    # トーナメント表(組み合わせ表風SVG)。「## トーナメント表(組み合わせ)」が無ければ空。
    bracket_html = render_bracket_svg(sections, reps_lines)
    if bracket_html:
        bracket_section = f'''
      <section class="lp-section">
        <h2><i class="fas fa-network-wired"></i> 組み合わせトーナメント表</h2>
        {bracket_html}
      </section>
'''
    else:
        bracket_section = ""

    champion_html = ""
    if champion and isinstance(champion, dict) and champion.get("team"):
        champion_html = (f'<div style="text-align:center;padding:16px;margin:16px 0;'
                         f'background:linear-gradient(135deg,#fde68a,#fbbf24);border-radius:10px;'
                         f'font-weight:700;color:#7c2d12;font-size:1.2em;">🏆 全国優勝:{team_link(champion["team"])}</div>')
    elif isinstance(champion, str) and champion.strip():
        champion_html = (f'<div style="text-align:center;padding:16px;margin:16px 0;'
                         f'background:linear-gradient(135deg,#fde68a,#fbbf24);border-radius:10px;'
                         f'font-weight:700;color:#7c2d12;font-size:1.2em;">🏆 全国優勝:{team_link(champion.strip())}</div>')

    status_badge = (f'<span style="display:inline-block;padding:4px 14px;border-radius:999px;'
                    f'background:#dbeafe;color:#1e40af;font-weight:600;font-size:0.9em;">{html_escape(status)}</span>'
                    if status else "")

    breadcrumb_schema = (
        '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":['
        '{"@type":"ListItem","position":1,"name":"ホーム","item":"' + DOMAIN + '/"},'
        '{"@type":"ListItem","position":2,"name":"インターハイ' + str(year) + '","item":"' + CANONICAL + '"}]}'
    )

    # --- FAQ と大会構造化データ(SportsEvent / FAQPage) ---
    import json as _json
    faq_items = [
        (f"インターハイ{year}のサッカー競技はいつ開催されますか？",
         f"{period} に開催されます。" if period else "日程は確定後に掲載します。"),
        ("開催地・会場はどこですか？",
         (f"{venue}({host})で開催されます。" if host else f"{venue}で開催されます。") if venue else "確定後に掲載します。"),
        ("出場枠・出場校数は？", slots or "各都道府県の予選を勝ち抜いた代表校が出場します。"),
        ("試合方式・試合時間は？", fmt or "ノックアウト方式で行われます。"),
        ("試合結果・組み合わせはどこで確認できますか？",
         "このページで組み合わせ・試合結果を随時更新しています。各都道府県予選の結果は当サイトの都道府県別ページで確認できます。"),
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
        "organizer": {"@type": "Organization", "name": "公益財団法人全国高等学校体育連盟", "url": "https://www.zen-koutairen.com/"},
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
        <span aria-current="page">インターハイ{year}</span>
      </nav>
      <h1 class="lp-title">{html_escape(title_main)}</h1>
{ai_summary_html}      <p class="lp-intro">
        高校総体(<strong>インターハイ</strong>)サッカー競技 男子 {year} の<strong>全国大会(本選)</strong>の
        組み合わせ・試合結果・各県代表校をまとめています。各県予選の結果は
        <a href="/">都道府県別ページ</a>からご確認いただけます。
      </p>

      <p style="margin:4px 0 16px;display:flex;flex-wrap:wrap;gap:10px;">
        <a href="/tournaments/interhigh-history/" style="display:inline-block;padding:9px 18px;border-radius:999px;background:var(--primary-color,#1e40af);color:#fff;text-decoration:none;font-weight:600;font-size:0.92em;">🏆 歴代優勝校一覧(2008-2025)</a>
        <a href="/blog/posts/interhigh-2026-heat-safety/" style="display:inline-block;padding:9px 18px;border-radius:999px;background:#dc2626;color:#fff;text-decoration:none;font-weight:600;font-size:0.92em;">🌡️ 救急医の暑熱対策ガイド</a>
      </p>

      <section class="lp-section">
        <h2><i class="fas fa-circle-info"></i> 大会概要 {status_badge}</h2>
        <ul style="list-style:none;padding:0;line-height:2;">
          <li><strong>大会名</strong>:{html_escape(title_main)}</li>
          <li><strong>会期</strong>:{html_escape(period) or '日程確定後に掲載'}</li>
          <li><strong>開催地</strong>:{html_escape(venue) or '確定後に掲載'}{(' / ' + html_escape(host)) if host else ''}</li>
          {slots_li}
          {format_li}
        </ul>
        {schedule_html}
        {champion_html}
      </section>
{featured_articles_section}
      <section class="lp-section">
        <h2><i class="fas fa-flag"></i> 各県代表</h2>
        {reps_html}
      </section>
{bracket_section}
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
          <li><a href="/leagues/">リーグ一覧(プレミア・プリンス)</a></li>
          <li><a href="/blog/">ブログ・医学コラム</a></li>
          <li><a href="/blog/posts/interhigh-2026-heat-safety/">【医学コラム】真夏のインターハイ暑熱対策ガイド(選手・保護者・指導者向け)</a></li>
          <li><a href="/blog/posts/2026-05-08-may-heatstroke-prevention/">【医学コラム】熱中症の危険サインと応急処置・予防法（救急医が解説）</a></li>
          <li><a href="/blog/posts/concussion-return-to-play-2026/">【医学コラム】脳震盪の見極め方と競技復帰プロトコル（頭を打ったら）</a></li>
          <li><a href="/blog/posts/2026-05-22-pre-match-sleep-strategy/">【医学コラム】試合前日に眠れない時の対処法・睡眠戦略</a></li>
          <li><a href="/blog/posts/2026-06-08-iron-deficiency-anemia/">【医学コラム】スポーツ貧血（鉄欠乏性貧血）の見抜き方と対策</a></li>
          <li><a href="/tournaments/interhigh-history/">インターハイ サッカー男子 歴代優勝校一覧</a></li>
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

    # --- sitemap に登録(idempotent) ---
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

            # --- 歴代優勝校ページも sitemap に登録(idempotent) ---
        history_url = f"{DOMAIN}/tournaments/interhigh-history/"
        s = sm.read_text(encoding="utf-8")
        if history_url not in s:
            entry = f"  <url>\n    <loc>{history_url}</loc>\n    <lastmod>{date.today().isoformat()}</lastmod>\n    <changefreq>monthly</changefreq>\n    <priority>0.6</priority>\n  </url>\n"
            s = s.replace("</urlset>", entry + "</urlset>")
            sm.write_text(s, encoding="utf-8")
            print("✅ sitemap.xml に歴代優勝校ページを登録")

if __name__ == "__main__":
    main()
