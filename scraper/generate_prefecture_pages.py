#!/usr/bin/env python3
"""
SEO 用の都道府県別ランディングページを自動生成するスクリプト。

機能:
    1. data/teams.json を読み込み、47都道府県それぞれの HTML を生成
       → prefectures/<id>/index.html (例: /prefectures/tokyo/index.html)
    2. sitemap.xml を更新して全ページを Google に伝える
    3. 各ページに OGP / 構造化データ / canonical / 内部リンクを完備

Phase 9-A ステップ2 で追加された構造化データ:
    - FAQPage: 各都道府県ごとの Q&A (検索 / AI 検索エンジン対策)
    - ItemList: 順位表をリスト構造として明示
    - SportsTeam (強化版): URL / sport / location / memberOf

使い方:
    cd <repo-root>
    python scraper/generate_prefecture_pages.py

依存ライブラリ: 標準ライブラリのみ (Python 3.8+)
"""
import json
import re
from pathlib import Path
from datetime import date

# ============================================================
# 都道府県別の特集記事マッピング
# 今後、他県の特集記事を書いたらここに追加していく
# ============================================================
PREFECTURE_FEATURED_ARTICLES = {
    "miyazaki": [
        {
            "title": "【2026最新】宮崎県高校サッカー3強の力関係｜日章学園・宮崎日大・鵬翔を救急医が分析",
            "url": "/blog/posts/2026-05-17-miyazaki-3-powerhouse/",
            "date": "2026-05-17",
        },
        {
            "title": "「鵬翔から日章学園へ」｜Dr.Kazu Soccerが追いかけた宮崎県の高校サッカー",
            "url": "/blog/posts/2026-05-11-miyazaki-soccer-feature/",
            "date": "2026-05-11",
        },
    ],
}


def render_featured_articles(pref_id):
    """都道府県の特集記事HTMLを返す。記事がなければ空文字を返す。"""
    articles = PREFECTURE_FEATURED_ARTICLES.get(pref_id, [])
    if not articles:
        return ""
    
    items = "\n".join([
        f'          <li><a href="{a["url"]}">{a["title"]}</a> '
        f'<span style="color:#999;font-size:0.9em;">（{a["date"]}）</span></li>'
        for a in articles
    ])
    
    return f"""      <section class="lp-section">
        <h2>📖 観戦コラム</h2>
        <ul class="lp-related-links">
{items}
        </ul>
      </section>
"""
def _detect_winner_and_wrap(s):
    """マッチ文字列の勝者を判定してmatch-winnerクラスでラップ
    対応形式:
      - "team1 7-0 team2"     → team1 を勝者強調
      - "team1 0-1 team2"     → team2 を勝者強調
      - "team1 2-2(PK4-2) team2" → PK勝者を強調
      - "team1 vs team2"      → 試合前なのでハイライトなし
    """
    # PK付きスコア（より具体的なパターン）を先に検出
    pk_match = re.search(r'(\d+)\s*-\s*(\d+)\s*\(\s*PK\s*(\d+)\s*-\s*(\d+)\s*\)', s)
    if pk_match:
        score_start = pk_match.start()
        score_end = pk_match.end()
        pkl = int(pk_match.group(3))
        pkr = int(pk_match.group(4))
        if pkl > pkr:
            winner_side = "left"
        elif pkr > pkl:
            winner_side = "right"
        else:
            return s
    else:
        # 通常スコア
        score_match = re.search(r'(\d+)\s*-\s*(\d+)', s)
        if not score_match:
            return s
        score_start = score_match.start()
        score_end = score_match.end()
        l_score = int(score_match.group(1))
        r_score = int(score_match.group(2))
        if l_score > r_score:
            winner_side = "left"
        elif r_score > l_score:
            winner_side = "right"
        else:
            return s
    left = s[:score_start]
    center = s[score_start:score_end]
    right = s[score_end:]
    if winner_side == "left":
        stripped = left.rstrip()
        trailing_ws = left[len(stripped):]
        return f'<span class="match-winner">{stripped}</span>{trailing_ws}{center}{right}'
    else:
        stripped = right.lstrip()
        leading_ws = right[:len(right) - len(stripped)]
        return f'{left}{center}{leading_ws}<span class="match-winner">{stripped}</span>'

def render_tournament_html(pref_id, teams):
    """都道府県のトーナメント情報を data/tournaments/*.md から読み取り、
    試合文字列のチーム名に県内順位バッジを自動付与してHTMLで返す。
    記事がなければ空文字を返す。
    """
    tournament_dir = BASE_DIR / "data" / "tournaments"
    if not tournament_dir.exists():
        return ""

    # 表示用の県内順位をティア順ソートで計算（prefecture pageと同じ並び順）
    sorted_for_rank = sort_teams(teams)
    rank_map = {}
    for i, t in enumerate(sorted_for_rank, 1):
        nm = t.get("name", "")
        if nm:
            rank_map[nm] = i

    # チーム名 → 県内順位＋リーグのマッピング（aliasも含む）
    team_lookup = {}
    for t in teams:
        name = t.get("name", "")
        info = {
            "rank": rank_map.get(name, t.get("prefectureRank")),
            "league": t.get("league", ""),
            "canonical": name,
        }
        if name:
            team_lookup[name] = info
            for alias in (t.get("aliases") or []):
                team_lookup[alias] = info

    def enrich_match(match_str):
        """試合文字列にチームの県内順位バッジを付加
        （最長一致・1チーム1回・単語境界判定で誤マッチ防止）"""
        # team_lookup に「高校」省略形も加えて拡張
        expanded_lookup = {}
        for nm, inf in team_lookup.items():
            expanded_lookup[nm] = inf
            short = nm.replace("高等学校", "").replace("高校", "").strip()
            if short and len(short) >= 2 and short != nm and short not in expanded_lookup:
                expanded_lookup[short] = inf

        known_names = sorted(expanded_lookup.keys(), key=len, reverse=True)

        def _is_jp_continuation(c):
            """日本語単語の続き文字か（区切り文字でない）"""
            if not c:
                return False
            code = ord(c)
            # 漢字
            if 0x4e00 <= code <= 0x9fff:
                return True
            # ひらがな
            if 0x3041 <= code <= 0x309f:
                return True
            # カタカナ（中点 0x30fb は除外）
            if 0x30a1 <= code <= 0x30fa:
                return True
            if 0x30fc <= code <= 0x30ff:
                return True
            return False

        def _has_clean_boundary(s, name, idx):
            """name が s の idx 位置で日本語の単語境界マッチしているか。
            「勝者」「ブロック」など、特定の文脈マーカーが続く場合は境界扱いにする。"""
            before_idx = idx - 1
            if before_idx >= 0 and _is_jp_continuation(s[before_idx]):
                return False
            after_idx = idx + len(name)
            if after_idx < len(s):
                # 既知の「次に続いても境界とみなせる」マーカー
                winner_markers = ("勝者", "ブロック", "側勝者", "系勝者", "シード")
                for marker in winner_markers:
                    if s[after_idx:after_idx + len(marker)] == marker:
                        return True
                if _is_jp_continuation(s[after_idx]):
                    return False
            return True

        matches = []
        matched_canonicals = set()
        used_ranges = []

        def _overlaps(s, e):
            for us, ue in used_ranges:
                if not (e <= us or s >= ue):
                    return True
            return False

        for nm in known_names:
            inf = expanded_lookup[nm]
            canonical = inf["canonical"]
            if canonical in matched_canonicals:
                continue
            rank = inf["rank"]
            if not rank or rank >= 99:
                continue

            # 単語境界マッチを探す（複数候補がある場合も対応）
            search_start = 0
            found_idx = -1
            while True:
                idx = match_str.find(nm, search_start)
                if idx < 0:
                    break
                if _has_clean_boundary(match_str, nm, idx):
                    found_idx = idx
                    break
                search_start = idx + 1

            if found_idx < 0:
                continue

            end = found_idx + len(nm)
            if _overlaps(found_idx, end):
                continue
            used_ranges.append((found_idx, end))
            matched_canonicals.add(canonical)
            badge = f' <span class="tm-rank">(県内{rank}位)</span>'
            matches.append((end, badge))

        # 後ろから挿入してインデックスがずれないように
        matches.sort(key=lambda x: x[0], reverse=True)
        result = match_str
        for pos, badge in matches:
            result = result[:pos] + badge + result[pos:]
        # 勝者ハイライト追加
        result = _detect_winner_and_wrap(result)
        return result

    html_parts = []
    for filepath in sorted(tournament_dir.glob("*.md")):
        content = filepath.read_text(encoding='utf-8')
        if not content.startswith('---'):
            continue
        parts = content.split('---', 2)
        if len(parts) < 3:
            continue
        _, frontmatter_str, body = parts

        metadata = {}
        for line in frontmatter_str.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                metadata[key.strip()] = value.strip()

        if metadata.get("prefecture") != pref_id:
            continue

        title = metadata.get("title", "大会")
        subtitle = metadata.get("subtitle", "")
        status = metadata.get("status", "")

        # 本文をパース
        rounds = []
        current_round = None
        for line in body.strip().split('\n'):
            line = line.strip()
            if line.startswith('## '):
                current_round = {"name": line[3:].strip(), "matches": []}
                rounds.append(current_round)
            elif line.startswith('- ') and current_round is not None:
                current_round["matches"].append(line[2:].strip())

        # HTML生成
        rounds_html_list = []
        for r in rounds:
            if not r["matches"]:
                matches_html = '            <li style="color:#888;">（試合確定後に追記）</li>'
            else:
                matches_html = "\n".join(
                    f'            <li>{enrich_match(m)}</li>'
                    for m in r["matches"]
                )
            rounds_html_list.append(
                f'        <div class="tournament-round">\n'
                f'          <h3>{r["name"]}</h3>\n'
                f'          <ul class="tournament-matches">\n'
                f'{matches_html}\n'
                f'          </ul>\n'
                f'        </div>'
            )

        status_html = f' <span class="tournament-status">[{status}]</span>' if status else ''
        subtitle_html = f'\n        <p class="tournament-subtitle" style="color:#666;font-size:0.9em;margin-top:-8px;">{subtitle}</p>' if subtitle else ''
        rounds_html_str = "\n".join(rounds_html_list)

        html_parts.append(
            f'      <section class="lp-section tournament-section">\n'
            f'        <h2>📋 {title}{status_html}</h2>{subtitle_html}\n'
            f'        <div class="tournament-rounds">\n'
            f'{rounds_html_str}\n'
            f'        </div>\n'
            f'      </section>'
        )

    return "\n".join(html_parts)


def render_tournament_results(pref_id):
    """都道府県の過去の全国大会成績HTMLを返す。
    全国高校選手権・インターハイのみ表示。直近5年。"""
    tournaments_file = BASE_DIR / "data" / "tournaments.json"
    if not tournaments_file.exists():
        return ""

    try:
        data = json.loads(tournaments_file.read_text(encoding='utf-8'))
    except Exception:
        return ""

    tournaments = data.get("tournaments", {})

    # 高校選手権・インターハイのみ
    target_tournaments = ["all_japan_highschool", "interhigh"]

    # この県の結果を集める {tournament_id: {year: [teams]}}
    pref_results = {}
    for t_id in target_tournaments:
        if t_id not in tournaments:
            continue
        t = tournaments[t_id]
        results = t.get("results", {})
        for year, year_data in results.items():
            teams = year_data.get("teams", [])
            for team in teams:
                if team.get("pref") == pref_id:
                    pref_results.setdefault(t_id, {}).setdefault(year, []).append(team)

    if not pref_results:
        return ""

    # 結果の表示順（rankが小さい=好成績を先に）
    def _result_key(team):
        r = team.get("rank")
        if r is None:
            return 999
        return r

    # 結果に応じたCSSクラス
    def _result_class(result):
        if result == "優勝":
            return "result-champion"
        if result == "準優勝":
            return "result-runner-up"
        if result == "ベスト4":
            return "result-best4"
        if result == "ベスト8":
            return "result-best8"
        if result == "ベスト16":
            return "result-best16"
        if result == "代表":
            return "result-representative"
        return ""

    def _result_display(result):
        if result == "代表":
            return "都道府県代表"
        return result

    html_parts = [
        '      <section class="lp-section tournament-results">',
        '        <h2>📜 過去の全国大会成績</h2>',
        '        <p class="tournament-results-intro" style="color:var(--text-light);font-size:0.9em;margin-bottom:12px;">直近5年の全国大会出場・成績</p>',
    ]

    for t_id in target_tournaments:
        if t_id not in pref_results:
            continue
        t = tournaments[t_id]
        t_name = t.get("shortName", t.get("displayName", t_id))

        html_parts.append(f'        <div class="tournament-result-block">')
        html_parts.append(f'          <h3>{html_escape(t_name)}</h3>')
        html_parts.append(f'          <ul class="tournament-result-list">')

        # 年度降順、最新5年
        years = sorted(pref_results[t_id].keys(), reverse=True)[:5]
        for year in years:
            teams = sorted(pref_results[t_id][year], key=_result_key)
            for team in teams:
                team_name = html_escape(team.get("team", ""))
                result = team.get("result", "")
                result_disp = _result_display(result)
                result_cls = _result_class(result)
                html_parts.append(
                    f'            <li>'
                    f'<span class="result-year">{year}年</span> '
                    f'<span class="result-team">{team_name}</span> '
                    f'<span class="result-place {result_cls}">{result_disp}</span>'
                    f'</li>'
                )

        html_parts.append(f'          </ul>')
        html_parts.append(f'        </div>')

    html_parts.append('      </section>')
    return '\n'.join(html_parts)
# ============================================================
# 設定
# ============================================================
BASE_DIR = Path(__file__).parent.parent
TEAMS_FILE = BASE_DIR / "data" / "teams.json"
OUTPUT_ROOT = BASE_DIR / "prefectures"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"
DOMAIN = "https://u18-soccer.com"
GA_ID = "G-KTPR94SPYS"
ADSENSE_CLIENT = "ca-pub-6953440022497606"


# ============================================================
# ヘルパー
# ============================================================
def html_escape(s):
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def league_category(team_league):
    lg = team_league or ""
    if "プレミアリーグ" in lg:
        return "premier"
    if "プリンスリーグ" in lg:
        return "prince"
    return "prefecture"

def get_notable_teams_for_title(teams):
    """都道府県の上位チーム（タイトル用）を最大3校返す。
    優先：プレミア > プリンス1部 > プリンス2部 > 県1部
    控えチーム（2nd, 3rd, セカンド等）と長すぎる名前は除外。
    """
    tier_order = {"premier": 0, "prince": 1, "prefecture": 2}

    def get_division(league):
        if not league:
            return 9
        if "1部" in league:
            return 1
        if "2部" in league:
            return 2
        return 0

    def is_main_team(name):
        """1軍チーム判定（控えチームを除外）"""
        suffixes = ["2nd", "3rd", "4th", "セカンド", "サード",
                    "Ⅱ", "Ⅲ", "②", "③", "B", "C"]
        return not any(name.endswith(s) for s in suffixes)

    def short_name(name):
        """タイトル用の短縮名（「高校」「高等学校」を除去）"""
        return (name
                .replace("高等学校", "")
                .replace("高校", "")
                .replace("日本大学", "日大")
                .replace("関西大学", "関大")     # 関西大学北陽 → 関大北陽
                .replace("専修大学", "専大")     # 専修大学北上 → 専大北上
                .replace("帝京大学", "帝京大")   # 帝京大学可児 → 帝京大可児
                .strip())

    sorted_teams = sorted(
        teams,
        key=lambda t: (
            tier_order.get(league_category(t.get("league")), 9),
            get_division(t.get("league")),
            t.get("rank", 99),
        )
    )

    notable = []
    for t in sorted_teams:
        name = t.get("name", "")
        if not is_main_team(name):
            continue
        display = short_name(name)
        if not display or len(display) > 12:  # 長すぎる名前は除外
            continue
        if display in notable:
            continue
        notable.append(display)
        if len(notable) >= 3:
            break
    return notable


def get_top_league(teams):
    if not teams:
        return "未登録"
    has_premier = any(league_category(t.get("league")) == "premier" for t in teams)
    has_prince = any(league_category(t.get("league")) == "prince" for t in teams)
    if has_premier:
        return "プレミアリーグ"
    if has_prince:
        return "プリンスリーグ"
    return "都道府県リーグ1部"


def is_club_youth(team_name):
    """クラブのユース・U-18 チームか判定 (FC東京U-18, ○○ユース, ○○U18 など)"""
    n = team_name or ""
    return any(kw in n for kw in ("U-18", "U18", "ユース", "ジュニアユース"))


def is_high_school(team_name):
    """高校サッカー部か判定 (高校 / 高等学校 を含み、かつクラブユースでない)"""
    n = team_name or ""
    if is_club_youth(n):
        return False
    return ("高校" in n) or ("高等学校" in n)


def count_team_types(teams):
    """高校サッカー部数とクラブユース数をカウント"""
    hs = sum(1 for t in teams if is_high_school(t.get("name", "")))
    cy = sum(1 for t in teams if is_club_youth(t.get("name", "")))
    return hs, cy


def sort_teams(teams):
    """ティア順 → 部(1部/2部) → 県内順位順にソート"""
    tier_order = {"premier": 0, "prince": 1, "prefecture": 2}

    def get_division(league):
        """リーグ名から'1部'/'2部'などを抽出して数値で返す。
        部の表記がなければ0(プレミアEAST/WESTなど)。"""
        if not league:
            return 9
        if "1部" in league:
            return 1
        if "2部" in league:
            return 2
        if "3部" in league:
            return 3
        return 0

    return sorted(
        teams,
        key=lambda t: (
            tier_order.get(league_category(t.get("league")), 9),
            get_division(t.get("league")),
            t.get("rank") or 99,
        ),
    )

def format_team_name(name):
    """チーム名: U-18, 2nd, 3rd, ユース, F.C. を <span class="nb"> で改行禁止に"""
    if not name:
        return "—"
    escaped = html_escape(name)
    # 長いトークンから先に置換 (短いものが先だと誤動作する可能性)
    tokens = ["U-18", "U-15", "F.C.", "U18", "U15", "2nd", "3rd", "ユース"]
    for token in sorted(tokens, key=len, reverse=True):
        escaped_token = html_escape(token)
        escaped = escaped.replace(
            escaped_token,
            f'<span class="nb">{escaped_token}</span>'
        )
    return escaped


def format_league_badge(league):
    """リーグバッジ: 「リーグ」を削除し、地域名を改行禁止に
    例: 'プレミアリーグEAST' → 'プレミア<span class="nb">EAST</span>'
    例: 'プリンスリーグ東北'  → 'プリンス<span class="nb">東北</span>'
    """
    if not league:
        return "—"
    # 「リーグ」を削除
    short = (league
             .replace("プレミアリーグ", "プレミア")
             .replace("プリンスリーグ", "プリンス"))
    escaped = html_escape(short)
    # 地域名・部別を改行禁止スパンで保護
    regions = [
        "EAST", "WEST",
        "北海道", "東北",
        "関東1部", "関東2部",
        "北信越1部", "北信越2部",
        "東海",
        "関西1部", "関西2部",
        "中国", "四国",
        "九州1部", "九州2部",
    ]
    for region in sorted(regions, key=len, reverse=True):
        escaped_region = html_escape(region)
        escaped = escaped.replace(
            escaped_region,
            f'<span class="nb">{escaped_region}</span>'
        )
    return escaped
    
def render_team_row(team, pref_rank):
    league = team.get("league", "—")
    badge_class = league_category(league)
    rank_class = f"rank-{pref_rank}" if pref_rank <= 3 else "rank-other"
    league_rank = team.get("leagueRank") if team.get("leagueRank") is not None else team.get("rank")
    league_rank_str = f"{league_rank}位" if league_rank not in (None, "") else "—"
    points = team.get("points", 0) or 0
    played = team.get("played", 0) or 0
    won = team.get("won", 0) or 0
    drawn = team.get("drawn", 0) or 0
    lost = team.get("lost", 0) or 0
    goal_diff = (team.get("goalsFor", 0) or 0) - (team.get("goalsAgainst", 0) or 0)
    diff_str = f"+{goal_diff}" if goal_diff > 0 else str(goal_diff)
    diff_class = (
        "goal-diff-positive" if goal_diff > 0
        else "goal-diff-negative" if goal_diff < 0
        else "goal-diff-zero"
    )
    return f"""        <tr>
          <td><span class="rank-badge {rank_class}">{pref_rank}</span></td>
          <td><strong>{format_team_name(team.get('name', '—'))}</strong></td>
          <td><span class="league-badge {badge_class}">{format_league_badge(league)}</span></td>
          <td>{league_rank_str}</td>
          <td><strong>{points}</strong></td>
          <td>{played}</td>
          <td>{won}</td>
          <td>{drawn}</td>
          <td>{lost}</td>
          <td class="{diff_class}" style="color:{'#28a745' if goal_diff > 0 else ('#dc3545' if goal_diff < 0 else '#666')}">{diff_str}</td>
        </tr>"""


# ============================================================
# 構造化データ
# ============================================================
def render_team_schema(teams, pref_name, pref_id):
    """SportsTeam 構造化データ (上位5チーム)"""
    items = []
    canonical = f"{DOMAIN}/prefectures/{pref_id}/"
    for t in sort_teams(teams)[:5]:
        items.append({
            "@type": "SportsTeam",
            "name": t.get("name", ""),
            "sport": "Football",
            "url": canonical,
            "location": {
                "@type": "Place",
                "name": pref_name,
                "address": {
                    "@type": "PostalAddress",
                    "addressCountry": "JP",
                    "addressRegion": pref_name,
                },
            },
            "memberOf": {
                "@type": "SportsOrganization",
                "name": t.get("league", ""),
            },
        })
    return items


def render_breadcrumb_schema(pref_name, pref_id):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": pref_name,
             "item": f"{DOMAIN}/prefectures/{pref_id}/"},
        ],
    }


# ============================================================
# Phase 9-A ステップ3: 内部リンク用のグローバル集計
# ============================================================
def get_global_top_teams(all_prefs, limit=10):
    """全国から上位 N チームを抽出 (リーグティア + 順位)"""
    all_teams = []
    for pref in all_prefs:
        for t in pref.get("teams", []):
            all_teams.append({
                **t,
                "_pref_name": pref["name"],
                "_pref_id": pref["id"],
            })
    return sorted(
        all_teams,
        key=lambda t: (
            {"premier": 0, "prince": 1, "prefecture": 2}.get(
                league_category(t.get("league")), 9
            ),
            t.get("rank") or 99,
        ),
    )[:limit]


def get_prefectures_with_league(all_prefs, category):
    """指定リーグカテゴリ('premier' / 'prince')のチームを持つ都道府県を取得"""
    result = []
    for pref in all_prefs:
        teams_in_league = [
            t for t in pref.get("teams", [])
            if league_category(t.get("league")) == category
        ]
        if teams_in_league:
            result.append({
                "id": pref["id"],
                "name": pref["name"],
                "team_count": len(teams_in_league),
                "team_names": [t.get("name", "") for t in teams_in_league[:3]],
            })
    return result


# 8地方ブロック分類 (region コードがデータに無い場合のフォールバック用)
REGION_LABEL = {
    "hokkaido": "北海道",
    "tohoku": "東北",
    "kanto": "関東",
    "chubu": "中部",
    "kansai": "関西",
    "chugoku": "中国",
    "shikoku": "四国",
    "kyushu": "九州・沖縄",
}


def group_prefectures_by_region(all_prefs):
    """都道府県を地方ブロックでグループ化"""
    groups = {}
    for pref in all_prefs:
        region = pref.get("region") or "other"
        groups.setdefault(region, []).append(pref)
    # 地方順序を整理
    ordered = []
    for r_id, r_label in REGION_LABEL.items():
        if r_id in groups:
            ordered.append((r_label, groups[r_id]))
    if "other" in groups:
        ordered.append(("その他", groups["other"]))
    return ordered


# ============================================================
# Phase 9-A ステップ3: 内部リンクセクションの HTML 生成
# ============================================================
def render_top10_html(top_teams, current_pref_id):
    """全国強豪校 TOP10 セクションの HTML"""
    if not top_teams:
        return '          <p style="color:#888;">情報を準備中</p>'
    items = []
    for i, t in enumerate(top_teams):
        league = t.get("league", "")
        league_class = league_category(league)
        is_current = (t.get("_pref_id") == current_pref_id)
        rank_class = (
            f"rank-{i+1}" if i < 3 else "rank-other"
        )
        # 自県の場合はリンクではなく強調表示
        team_block = (
            f'<strong>{html_escape(t.get("name", ""))}</strong>'
            f' <span class="lp-top10-pref-current">({html_escape(t["_pref_name"])} ・ このページ)</span>'
            if is_current else
            f'<a href="/prefectures/{t["_pref_id"]}/" class="lp-top10-link">'
            f'<strong>{html_escape(t.get("name", ""))}</strong>'
            f'<span class="lp-top10-pref">{html_escape(t["_pref_name"])}</span>'
            f'</a>'
        )
        items.append(
            f'        <li class="lp-top10-item">'
            f'<span class="lp-top10-rank {rank_class}">{i+1}</span>'
            f'<div class="lp-top10-body">'
            f'<span class="league-badge {league_class}">{html_escape(league)}</span>'
            f'{team_block}'
            f'</div>'
            f'</li>'
        )
    return "\n".join(items)


def render_league_prefs_html(prefs, current_pref_id, league_label):
    """プレミア/プリンスリーグ所属都道府県のリンク群 HTML"""
    if not prefs:
        return f'          <p style="color:#888;">{league_label}所属の都道府県は現在ありません。</p>'
    items = []
    for p in prefs:
        is_current = (p["id"] == current_pref_id)
        team_examples = "、".join(html_escape(n) for n in p["team_names"])
        if is_current:
            items.append(
                f'          <span class="lp-league-pref lp-league-pref--current" '
                f'title="{team_examples}">{html_escape(p["name"])}'
                f'<small>({p["team_count"]}校)</small></span>'
            )
        else:
            items.append(
                f'          <a href="/prefectures/{p["id"]}/" class="lp-league-pref" '
                f'title="{team_examples}">{html_escape(p["name"])}'
                f'<small>({p["team_count"]}校)</small></a>'
            )
    return "\n".join(items)


def render_all_prefs_html(grouped_prefs, current_pref_id):
    """47都道府県を地方別にグループ化した全リンク HTML"""
    blocks = []
    for region_label, prefs in grouped_prefs:
        links = []
        for p in prefs:
            is_current = (p["id"] == current_pref_id)
            cls = "lp-allprefs-link" + (" lp-allprefs-link--current" if is_current else "")
            if is_current:
                links.append(
                    f'            <span class="{cls}">{html_escape(p["name"])}</span>'
                )
            else:
                links.append(
                    f'            <a href="/prefectures/{p["id"]}/" class="{cls}">'
                    f'{html_escape(p["name"])}</a>'
                )
        blocks.append(
            f'        <div class="lp-allprefs-region">\n'
            f'          <h3 class="lp-allprefs-region-title">{html_escape(region_label)}</h3>\n'
            f'          <div class="lp-allprefs-grid">\n'
            + "\n".join(links) + "\n"
            f'          </div>\n'
            f'        </div>'
        )
    return "\n".join(blocks)


# Phase 9-C: 都道府県内のチームが所属するリーグ → リーグ詳細ページへのリンク
LEAGUE_TO_SLUG = {
    "プレミアリーグEAST": ("premier-east", "プレミアリーグ EAST"),
    "プレミアリーグWEST": ("premier-west", "プレミアリーグ WEST"),
    "プリンスリーグ北海道": ("prince-hokkaido", "プリンスリーグ 北海道"),
    "プリンスリーグ東北": ("prince-tohoku", "プリンスリーグ 東北"),
    "プリンスリーグ関東1部": ("prince-kanto-1", "プリンスリーグ 関東 1部"),
    "プリンスリーグ関東2部": ("prince-kanto-2", "プリンスリーグ 関東 2部"),
    "プリンスリーグ北信越": ("prince-hokushinetsu", "プリンスリーグ 北信越"),
    "プリンスリーグ東海": ("prince-tokai", "プリンスリーグ 東海"),
    "プリンスリーグ関西1部": ("prince-kansai-1", "プリンスリーグ 関西 1部"),
    "プリンスリーグ関西2部": ("prince-kansai-2", "プリンスリーグ 関西 2部"),
    "プリンスリーグ中国": ("prince-chugoku", "プリンスリーグ 中国"),
    "プリンスリーグ四国": ("prince-shikoku", "プリンスリーグ 四国"),
    "プリンスリーグ九州1部": ("prince-kyushu-1", "プリンスリーグ 九州 1部"),
    "プリンスリーグ九州2部": ("prince-kyushu-2", "プリンスリーグ 九州 2部"),
}


def render_league_links_html(teams):
    """都道府県内のチームが所属しているリーグへのリンク群"""
    leagues_in_pref = {}
    for t in teams:
        league_name = t.get("league") or ""
        if league_name in LEAGUE_TO_SLUG:
            slug, label = LEAGUE_TO_SLUG[league_name]
            if slug not in leagues_in_pref:
                leagues_in_pref[slug] = {
                    "label": label,
                    "category": league_category(league_name),
                    "team_count": 0,
                    "team_names": [],
                }
            leagues_in_pref[slug]["team_count"] += 1
            leagues_in_pref[slug]["team_names"].append(t.get("name", ""))

    if not leagues_in_pref:
        return (
            '          <p style="color:#888;">'
            'この都道府県のチームが所属するプレミア/プリンスリーグはありません'
            '（都道府県リーグ1部のみ）</p>'
        )

    items = []
    # premier を先、prince を後
    sorted_leagues = sorted(
        leagues_in_pref.items(),
        key=lambda kv: (0 if kv[1]["category"] == "premier" else 1, kv[0]),
    )
    for slug, info in sorted_leagues:
        names = "、".join(html_escape(n) for n in info["team_names"])
        cls = f"league-link league-link--{info['category']}"
        items.append(
            f'          <a href="/leagues/{slug}/" class="{cls}" '
            f'title="所属チーム: {names}">'
            f'{html_escape(info["label"])}'
            f'<small>({info["team_count"]}校)</small></a>'
        )
    return "\n".join(items)


def render_itemlist_schema(teams, pref_name, pref_id):
    """順位表を ItemList として表現"""
    canonical = f"{DOMAIN}/prefectures/{pref_id}/"
    sorted_t = sort_teams(teams)[:20]  # 上位20チームまで構造化データ化
    if not sorted_t:
        return None
    item_list = []
    for i, t in enumerate(sorted_t):
        item_list.append({
            "@type": "ListItem",
            "position": i + 1,
            "item": {
                "@type": "SportsTeam",
                "name": t.get("name", ""),
                "sport": "Football",
                "memberOf": t.get("league", ""),
            },
        })
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"{pref_name} U-18 高校サッカー 順位表",
        "description": f"{pref_name}の高校サッカーチーム順位リスト",
        "url": canonical,
        "numberOfItems": len(item_list),
        "itemListElement": item_list,
    }


def build_faqs(pref_name, teams):
    """都道府県ごとの FAQ を生成（5問）"""
    sorted_t = sort_teams(teams)
    team_count = len(teams)
    hs_count, cy_count = count_team_types(teams)

    # Q1: 上位チーム（上位3チーム = 高校・クラブユース両方を含む）
    top3 = sorted_t[:3]
    if top3:
        top3_names = "、".join(html_escape(t.get("name", "")) for t in top3)
        a1 = (
            f"現在の最新データでは、{html_escape(pref_name)}の上位3チームは<strong>{top3_names}</strong>です。"
            f"順位はリーグカテゴリ（プレミア＞プリンス＞都道府県1部）と、各リーグ内順位を加味してランキングしています。"
        )
    else:
        a1 = f"{html_escape(pref_name)}のデータはまだ準備中です。"

    # Q2: チーム数（高校サッカー部・クラブユースを区別）
    if hs_count > 0 and cy_count > 0:
        a2 = (
            f"{html_escape(pref_name)}には<strong>高校サッカー部 {hs_count}校</strong>と"
            f"<strong>クラブユース {cy_count}チーム</strong>（J リーグクラブの U-18 / ユースなど）の"
            f"合計 {team_count} チームが U-18 年代の各種リーグ"
            f"（高円宮杯JFA U-18 サッカープレミアリーグ・プリンスリーグ・都道府県リーグ1部）に参加しています。"
            f"なお、本サイトでは都道府県リーグの<strong>1部</strong>に所属するチームのみを掲載しており、2部以下は対象外です。"
        )
    elif hs_count > 0:
        a2 = (
            f"{html_escape(pref_name)}からは<strong>高校サッカー部 {hs_count}校</strong>が"
            f" U-18 年代の各種リーグ（高円宮杯JFA U-18 サッカープレミアリーグ・プリンスリーグ・都道府県リーグ1部）に参加しています。"
            f"なお、本サイトでは都道府県リーグの<strong>1部</strong>に所属するチームのみを掲載しており、2部以下は対象外です。"
        )
    elif cy_count > 0:
        a2 = (
            f"{html_escape(pref_name)}からは<strong>クラブユース {cy_count}チーム</strong>が"
            f" U-18 年代の各種リーグ（高円宮杯JFA U-18 サッカープレミアリーグ・プリンスリーグ・都道府県リーグ1部）に参加しています。"
        )
    else:
        a2 = f"{html_escape(pref_name)}のデータはまだ準備中です。"

    # Q3: プレミア所属チーム
    premier_teams = [t for t in teams if league_category(t.get("league")) == "premier"]
    if premier_teams:
        names = "、".join(html_escape(t.get("name", "")) for t in premier_teams)
        a3 = f"<strong>{names}</strong>がプレミアリーグに所属しています。プレミアリーグは全国2地域（EAST/WEST 各12チーム）の最上位リーグです。"
    else:
        prince_teams = [t for t in teams if league_category(t.get("league")) == "prince"]
        if prince_teams:
            names = "、".join(html_escape(t.get("name", "")) for t in prince_teams)
            a3 = (
                f"現在、{html_escape(pref_name)}からプレミアリーグへの所属はありません。"
                f"プリンスリーグには<strong>{names}</strong>が所属しています。"
            )
        else:
            a3 = (
                f"現在、{html_escape(pref_name)}からプレミアリーグ・プリンスリーグへの所属はありません。"
                f"上位リーグへの昇格を目指す<strong>都道府県リーグ1部</strong>所属チームの順位を本サイトで確認できます。"
            )

    # Q4: 更新頻度
    a4 = (
        "本サイトの順位データは <strong>毎日 9:00 (JST)</strong> 頃に自動更新されています。"
        "JFA（日本サッカー協会）公式サイト・各都道府県サッカー協会の最新データを反映しているため、"
        "週末の試合結果も最短で翌朝には順位表に反映されます。"
    )

    # Q5: 大会説明
    a5 = (
        "高円宮杯 JFA U-18 サッカーリーグは、日本サッカー協会主催の U-18（高校生年代）向けリーグ戦です。"
        "<strong>プレミアリーグ</strong>（全国2地域 各12チーム）、<strong>プリンスリーグ</strong>（9地域）、"
        "<strong>都道府県リーグ</strong>（1部・2部・3部など複数のディビジョン）という階層的なピラミッド構造になっており、"
        "各リーグ間で昇降格があります。"
        f"なお本サイトでは、{html_escape(pref_name)}を含む各都道府県の<strong>1部</strong>所属チームのみを掲載対象としています。"
    )

    return [
        (f"{html_escape(pref_name)}で最も強い高校サッカー部・クラブユースはどこですか？", a1),
        (f"{html_escape(pref_name)}の U-18 年代のチーム構成は？（高校サッカー部・クラブユース）", a2),
        (f"{html_escape(pref_name)}のプレミアリーグ・プリンスリーグ所属チームは？", a3),
        ("順位データはいつ更新されますか？", a4),
        ("高円宮杯 JFA U-18 サッカーリーグとは何ですか？", a5),
    ]


def render_faq_schema(faqs):
    """FAQPage 構造化データ"""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": strip_tags(q),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": strip_tags(a),
                },
            }
            for q, a in faqs
        ],
    }


def strip_tags(s):
    """構造化データ用に簡易的にタグを除去"""
    return re.sub(r"<[^>]+>", "", s)


def render_faq_html(faqs):
    """可視 FAQ セクションの HTML を生成 (details/summary)"""
    items = []
    for q, a in faqs:
        items.append(
            f'        <details class="lp-faq-item">\n'
            f'          <summary class="lp-faq-q">{q}</summary>\n'
            f'          <div class="lp-faq-a">{a}</div>\n'
            f'        </details>'
        )
    return "\n".join(items)


# ============================================================
# HTML テンプレート
# ============================================================
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <!-- Google Analytics -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=__GA_ID__"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', '__GA_ID__');
  </script>

  <!-- Google AdSense -->
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=__ADSENSE__"
          crossorigin="anonymous"></script>
  <meta name="google-adsense-account" content="__ADSENSE__">

  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">

  <title>__TITLE__</title>
  <meta name="description" content="__DESCRIPTION__">
  <meta name="keywords" content="__KEYWORDS__">
  <meta name="robots" content="index, follow">
  <meta name="format-detection" content="telephone=no">
  <link rel="canonical" href="__CANONICAL__">

  <!-- OGP -->
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="高校サッカー順位確認システム">
  <meta property="og:title" content="__TITLE__">
  <meta property="og:description" content="__DESCRIPTION__">
  <meta property="og:url" content="__CANONICAL__">
  <meta property="og:image" content="https://u18-soccer.com/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:locale" content="ja_JP">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@DrKazuSoccer">
  <meta name="twitter:creator" content="@DrKazuSoccer">
  <meta name="twitter:title" content="__TITLE__">
  <meta name="twitter:description" content="__DESCRIPTION__">
  <meta name="twitter:image" content="https://u18-soccer.com/og-image.png">

  <!-- ファビコン -->
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <meta name="theme-color" content="#1e40af">

  <!-- 構造化データ: BreadcrumbList -->
  <script type="application/ld+json">
__SCHEMA_BREADCRUMB__
  </script>
  <!-- 構造化データ: SportsTeam (上位5チーム) -->
  <script type="application/ld+json">
__SCHEMA_TEAMS__
  </script>
  <!-- 構造化データ: ItemList (順位表) -->
  <script type="application/ld+json">
__SCHEMA_ITEMLIST__
  </script>
  <!-- 構造化データ: FAQPage -->
  <script type="application/ld+json">
__SCHEMA_FAQ__
  </script>

  <!-- フォント・アイコン・スタイル -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/css/style.css">

  <!-- ダークモード初期化 (FOUC 防止) -->
  <script>
    (function() {
      try {
        var t = localStorage.getItem('theme');
        if (t === 'light' || t === 'dark') {
          document.documentElement.setAttribute('data-theme', t);
        }
      } catch (e) {}
    })();
  </script>
</head>
<body>
  <header class="header">
    <div class="container">
      <div class="header-content">
        <h1 class="site-title">
          <a href="/" style="color:white;text-decoration:none;display:inline-flex;align-items:center;gap:10px">
            <i class="fas fa-futbol"></i>
            高校サッカー順位確認システム
          </a>
        </h1>
        <nav class="nav">
          <a href="/" class="nav-link"><i class="fas fa-home"></i> ホーム</a>
          <a href="/#search" class="nav-link"><i class="fas fa-search"></i> 検索</a>
        </nav>
      </div>
    </div>
  </header>

  <main class="main-content">
    <div class="container">
      <!-- パンくずリスト -->
      <nav class="breadcrumb" aria-label="パンくずリスト">
        <a href="/">ホーム</a>
        <span class="breadcrumb__sep">›</span>
        <span aria-current="page">__PREF_NAME__</span>
      </nav>

      <h1 class="lp-title">__PREF_NAME__ U-18 高校サッカー 順位表</h1>

      <p class="lp-intro">
        __PREF_NAME__の高校サッカー部・クラブユース（U-18年代）所属
        <strong>__TEAM_COUNT__チーム</strong>（高校 __HS_COUNT__校＋クラブユース __CY_COUNT__チーム）
        の最新順位・成績情報。
        高円宮杯JFA U-18サッカープレミアリーグ・プリンスリーグ・__PREF_NAME__リーグ1部の順位表を、
        毎日最新データに自動更新しています（都道府県リーグは1部のみ掲載）。
      </p>

      <!-- 統計 -->
      <div class="stats-summary">
        <div class="stat-item">
          <div class="stat-label">登録チーム数</div>
          <div class="stat-value">__TEAM_COUNT__</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">最高リーグ</div>
          <div class="stat-value">__TOP_LEAGUE__</div>
        </div>
      </div>
__FEATURED_ARTICLES__
__TOURNAMENT_RESULTS__
__TOURNAMENT_HTML__
      <!-- メイン CTA -->
      <div class="lp-cta">
        <a href="/" class="lp-cta__btn">
          <i class="fas fa-bolt"></i> 全国版・インタラクティブビュー (検索/お気に入り/詳細表示)
        </a>
      </div>

      <!-- チーム一覧 -->
      <h2 class="section-title-lp">__PREF_NAME__ 所属チーム順位表</h2>
      <div id="teamsTableLP" style="overflow-x:auto;-webkit-overflow-scrolling:touch;">
        <table class="data-table">
          <thead>
            <tr>
              <th>県内順位</th>
              <th>チーム名</th>
              <th>リーグ</th>
              <th>順位</th>
              <th>勝点</th>
              <th>試合</th>
              <th>勝</th>
              <th>分</th>
              <th>負</th>
              <th>得失差</th>
            </tr>
          </thead>
          <tbody>
__TEAM_ROWS__
          </tbody>
        </table>
      </div>

      <!-- 説明文 (SEO 用) -->
      <section class="lp-section">
        <h2>__PREF_NAME__ U-18 高校サッカーについて</h2>
        <p>
          __PREF_NAME__からは現在<strong>高校サッカー部 __HS_COUNT__校</strong>と
          <strong>クラブユース __CY_COUNT__チーム</strong>（合計 __TEAM_COUNT__ チーム）が
          U-18 年代の各種リーグに参加しています。所属する最高位リーグは<strong>__TOP_LEAGUE__</strong>です。
        </p>
        <p>
          高円宮杯 JFA U-18 サッカーリーグは、日本サッカー協会主催の U-18（高校生年代）向けリーグ戦で、
          全国規模の<strong>プレミアリーグ</strong>（東西各12チーム）、9地域それぞれの<strong>プリンスリーグ</strong>、
          各都道府県の<strong>都道府県リーグ</strong>（1部・2部・3部などの複数ディビジョン）という階層構造になっています。
          各リーグの上位・下位チームには毎年昇降格があり、上位リーグ昇格を目指してハイレベルな戦いが繰り広げられています。
          なお、本サイトでは都道府県リーグは<strong>1部</strong>所属チームのみを掲載しています。
        </p>
      </section>

      <!-- ★ FAQ セクション (Phase 9-A ステップ2 で追加) -->
      <section class="lp-section lp-faq">
        <h2><i class="fas fa-question-circle"></i> よくある質問</h2>
__FAQ_HTML__
      </section>

      <!-- ★ Phase 9-C: 所属リーグ詳細ページへのリンク -->
      <section class="lp-section">
        <h2><i class="fas fa-trophy"></i> __PREF_NAME__のチームが所属するリーグ詳細</h2>
        <p class="lp-section-desc">
          __PREF_NAME__のチームが所属するプレミア・プリンスリーグの専用ページです。
          リーグ全体の順位や他県の所属チーム、リーグの仕組みを詳しく確認できます。
        </p>
        <div class="lp-related-leagues">
__LEAGUE_LINKS_HTML__
        </div>
      </section>

      <!-- ★ Phase 9-A ステップ3: 全国強豪校 TOP 10 -->
      <section class="lp-section lp-top10">
        <h2><i class="fas fa-trophy"></i> 全国強豪校 TOP 10</h2>
        <p class="lp-section-desc">
          全国47都道府県のチームを、所属リーグ階層と順位を加味してランキングしました。
          各チームをクリックすると所属する都道府県の順位表ページに移動できます。
        </p>
        <ol class="lp-top10-list">
__TOP10_HTML__
        </ol>
      </section>

      <!-- ★ Phase 9-A ステップ3: プレミアリーグ所属都道府県 -->
      <section class="lp-section">
        <h2><i class="fas fa-star"></i> プレミアリーグ所属の都道府県</h2>
        <p class="lp-section-desc">
          高円宮杯JFA U-18 サッカープレミアリーグ（全国2地域・各12チーム）に
          所属するチームがある都道府県の一覧です。
        </p>
        <div class="lp-league-prefs">
__PREMIER_PREFS_HTML__
        </div>
      </section>

      <!-- ★ Phase 9-A ステップ3: プリンスリーグ所属都道府県 -->
      <section class="lp-section">
        <h2><i class="fas fa-medal"></i> プリンスリーグ所属の都道府県</h2>
        <p class="lp-section-desc">
          高円宮杯JFA U-18 サッカープリンスリーグ（9地域）に所属するチームがある都道府県の一覧です。
        </p>
        <div class="lp-league-prefs">
__PRINCE_PREFS_HTML__
        </div>
      </section>

      <!-- 近隣の都道府県 -->
      <section class="lp-section">
        <h2><i class="fas fa-map-marker-alt"></i> 近隣の都道府県</h2>
        <div class="lp-neighbor-grid">
__NEIGHBOR_LINKS__
        </div>
      </section>

      <!-- ★ Phase 9-A ステップ3: 全47都道府県(地方別) -->
      <section class="lp-section lp-allprefs">
        <h2><i class="fas fa-globe"></i> 全47都道府県の順位表を見る</h2>
        <p class="lp-section-desc">
          地方ブロック別に全国の順位表ページへリンクしています。
          気になる都道府県をクリックして高校サッカーの最新情報をチェックしてください。
        </p>
__ALL_PREFS_HTML__
      </section>

      <!-- 関連リンク -->
      <section class="lp-section">
        <h2>関連リンク</h2>
        <ul class="lp-related-links">
          <li><a href="/">全国の高校サッカー順位表トップ</a></li>
          <li><a href="/#search">チーム名で検索</a></li>
          <li><a href="/about.html">運営者情報</a></li>
          <li><a href="/contact.html">お問い合わせ</a></li>
        </ul>
      </section>
    </div>
  </main>

  <footer class="footer">
    <div class="container">
      <p>&copy; 2025 高校サッカー順位確認システム</p>
      <nav class="footer-nav" style="margin-top:12px;">
        <a href="/about.html">運営者情報</a> ・
        <a href="/privacy.html">プライバシーポリシー</a> ・
        <a href="/contact.html">お問い合わせ</a>
      </nav>
      <p class="footer-note" style="margin-top:12px;">
        <i class="fas fa-info-circle"></i>
        データ出典：JFA（日本サッカー協会）、各都道府県サッカー協会、各高校・クラブ公式情報。最新情報は各公式サイトをご確認ください。
      </p>
    </div>
  </footer>
  <script src="/js/main.js" defer></script>
</body>
</html>
"""


def generate_page(pref, all_prefs):
    pref_id = pref["id"]
    pref_name = pref["name"]
    teams = pref["teams"]
    team_count = len(teams)
    hs_count, cy_count = count_team_types(teams)
    top_league = get_top_league(teams)
    canonical = f"{DOMAIN}/prefectures/{pref_id}/"
    sorted_teams = sort_teams(teams)
    if sorted_teams:
        team_rows = "\n".join(
            render_team_row(t, i + 1) for i, t in enumerate(sorted_teams)
        )
    else:
        team_rows = (
            '        <tr><td colspan="10" '
            'style="text-align:center;padding:30px;color:#888;">'
            f'{html_escape(pref_name)}のデータはまだ登録されていません</td></tr>'
        )
    region = pref.get("region") or ""
    neighbors = [p for p in all_prefs if p.get("region") == region and p["id"] != pref_id]
    if neighbors:
        neighbor_links = "\n".join(
            f'          <a href="/prefectures/{n["id"]}/" class="lp-neighbor-link">{html_escape(n["name"])}</a>'
            for n in neighbors
        )
    else:
        neighbor_links = '          <p style="color:#888;">情報を準備中</p>'

   # ★ 強豪校名をタイトル・description に組み込む（GSC実データに基づく全県SEO最適化版）
    notable_teams = get_notable_teams_for_title(teams)
    year_label = date.today().year

    # === 地域 → プリンスリーグ名 のマッピング ===
    REGION_TO_PRINCE_LEAGUE = {
        "北海道":  "プリンスリーグ北海道",
        "東北":    "プリンスリーグ東北",
        "関東":    "プリンスリーグ関東",
        "北信越":  "プリンスリーグ北信越",
        "東海":    "プリンスリーグ東海",
        "関西":    "プリンスリーグ関西",
        "中国":    "プリンスリーグ中国",
        "四国":    "プリンスリーグ四国",
        "九州":    "プリンスリーグ九州",
    }
    prince_league = REGION_TO_PRINCE_LEAGUE.get(region, "プリンスリーグ")

    # タイトル用は強豪校を最大2チームまで（文字数オーバー防止）
    notable_short = "・".join(notable_teams[:2]) if notable_teams else ""
    # description用は全強豪校
    notable_full = "・".join(notable_teams) if notable_teams else ""

    if notable_teams:
        title = (
            f"【{year_label}最新】{pref_name}高校サッカーリーグ U-18 1部順位表"
            f" | {notable_short}"
        )
        description = (
            f"{pref_name}高校サッカーリーグ1部（U-18年代）の最新順位・試合結果を毎日自動更新。"
            f"{notable_full}など県内{team_count}チームの成績、"
            f"高円宮杯JFA U-18プレミアリーグ・{prince_league}との連動状況も掲載。"
        )
    else:
        title = (
            f"【{year_label}最新】{pref_name}高校サッカーリーグ U-18 1部順位表"
            f" | プレミア・プリンス対応"
        )
        description = (
            f"{pref_name}高校サッカーリーグ1部（U-18年代）{team_count}チームの最新順位・試合結果を毎日自動更新。"
            f"高円宮杯JFA U-18プレミアリーグ・{prince_league}との連動状況もわかりやすく掲載。"
        )

    keywords = (
        f"{pref_name},高校サッカー,クラブユース,U-18,U18,高円宮杯,プレミアリーグ,プリンスリーグ,"
        f"{pref_name}リーグ1部,{pref_name}リーグ,順位,成績,日程,結果"
    )
    # 構造化データ
    breadcrumb = json.dumps(
        render_breadcrumb_schema(pref_name, pref_id),
        ensure_ascii=False, indent=2
    )
    teams_schema = json.dumps(
        {"@context": "https://schema.org", "@graph": render_team_schema(teams, pref_name, pref_id)},
        ensure_ascii=False, indent=2
    )
    itemlist = render_itemlist_schema(teams, pref_name, pref_id)
    if itemlist:
        itemlist_json = json.dumps(itemlist, ensure_ascii=False, indent=2)
    else:
        # データなし都道府県は空の ItemList を出さない
        itemlist_json = json.dumps({"@context": "https://schema.org", "@type": "ItemList", "name": f"{pref_name} 順位表 (準備中)", "itemListElement": []}, ensure_ascii=False, indent=2)
    # FAQ
    faqs = build_faqs(pref_name, teams)
    faq_schema = json.dumps(render_faq_schema(faqs), ensure_ascii=False, indent=2)
    faq_html = render_faq_html(faqs)
    # ★ Phase 9-A ステップ3: 内部リンクセクション
    top10 = get_global_top_teams(all_prefs, limit=10)
    top10_html = render_top10_html(top10, pref_id)
    premier_prefs = get_prefectures_with_league(all_prefs, "premier")
    prince_prefs = get_prefectures_with_league(all_prefs, "prince")
    premier_prefs_html = render_league_prefs_html(premier_prefs, pref_id, "プレミアリーグ")
    prince_prefs_html = render_league_prefs_html(prince_prefs, pref_id, "プリンスリーグ")
    grouped_prefs = group_prefectures_by_region(all_prefs)
    all_prefs_html = render_all_prefs_html(grouped_prefs, pref_id)
    # Phase 9-C: 所属リーグへのリンク
    league_links_html = render_league_links_html(teams)
    return (
        PAGE_TEMPLATE
        .replace("__GA_ID__", GA_ID)
        .replace("__ADSENSE__", ADSENSE_CLIENT)
        .replace("__TITLE__", html_escape(title))
        .replace("__DESCRIPTION__", html_escape(description))
        .replace("__KEYWORDS__", html_escape(keywords))
        .replace("__CANONICAL__", canonical)
        .replace("__SCHEMA_BREADCRUMB__", breadcrumb)
        .replace("__SCHEMA_TEAMS__", teams_schema)
        .replace("__SCHEMA_ITEMLIST__", itemlist_json)
        .replace("__SCHEMA_FAQ__", faq_schema)
        .replace("__PREF_NAME__", html_escape(pref_name))
        .replace("__FEATURED_ARTICLES__", render_featured_articles(pref_id))
        .replace("__TOURNAMENT_RESULTS__", render_tournament_results(pref_id))
        .replace("__TOURNAMENT_HTML__", render_tournament_html(pref_id, teams))
        .replace("__TEAM_COUNT__", str(team_count))
        .replace("__HS_COUNT__", str(hs_count))
        .replace("__CY_COUNT__", str(cy_count))
        .replace("__TOP_LEAGUE__", html_escape(top_league))
        .replace("__TEAM_ROWS__", team_rows)
        .replace("__NEIGHBOR_LINKS__", neighbor_links)
        .replace("__FAQ_HTML__", faq_html)
        .replace("__TOP10_HTML__", top10_html)
        .replace("__PREMIER_PREFS_HTML__", premier_prefs_html)
        .replace("__PRINCE_PREFS_HTML__", prince_prefs_html)
        .replace("__ALL_PREFS_HTML__", all_prefs_html)
        .replace("__LEAGUE_LINKS_HTML__", league_links_html)
    )

def update_sitemap(all_prefs):
    today = date.today().isoformat()
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
             '  <url>',
             f'    <loc>{DOMAIN}/</loc>',
             f'    <lastmod>{today}</lastmod>',
             '    <changefreq>daily</changefreq>',
             '    <priority>1.0</priority>',
             '  </url>']
    for p in all_prefs:
        parts.extend([
            '  <url>',
            f'    <loc>{DOMAIN}/prefectures/{p["id"]}/</loc>',
            f'    <lastmod>{today}</lastmod>',
            '    <changefreq>daily</changefreq>',
            '    <priority>0.8</priority>',
            '  </url>',
        ])
    # 静的ページも登録
    for static_url in ("/about.html", "/privacy.html", "/contact.html"):
        parts.extend([
            '  <url>',
            f'    <loc>{DOMAIN}{static_url}</loc>',
            f'    <lastmod>{today}</lastmod>',
            '    <changefreq>monthly</changefreq>',
            '    <priority>0.4</priority>',
            '  </url>',
        ])
    parts.append('</urlset>')
    SITEMAP_FILE.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"sitemap.xml 更新: {len(all_prefs) + 1 + 3} URL を登録")


def main():
    if not TEAMS_FILE.exists():
        print(f"[ERROR] {TEAMS_FILE} が見つかりません。先にスクレイパーを実行してください。")
        return 1

    teams_data = json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    all_prefs = [
        {"id": pid, **p}
        for pid, p in teams_data.items()
        if isinstance(p, dict) and "teams" in p
    ]

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    for pref in all_prefs:
        pref_dir = OUTPUT_ROOT / pref["id"]
        pref_dir.mkdir(parents=True, exist_ok=True)
        html = generate_page(pref, all_prefs)
        (pref_dir / "index.html").write_text(html, encoding="utf-8")

    update_sitemap(all_prefs)
    print(f"完了: {len(all_prefs)} 都道府県の SEO ランディングページを生成しました")
    print(f"   出力先: {OUTPUT_ROOT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
