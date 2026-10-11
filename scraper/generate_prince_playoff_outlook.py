#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参入戦ページに「各地域のプリンスリーグ参入戦 暫定出場チーム」の表を出す（2026-10-12 新設）。

- 県1部の今の順位（data/league_matches/pref-*-1.json の official_standings）から、
  「このまま終わったら各地域のプリンスリーグ参入戦に出るチーム」を9地域ぶん作る。
- 書き換えるのは tournaments/promotion-playoff-2026/index.html の
  <!-- PRINCE-PLAYOFF-OUTLOOK:START --> 〜 <!-- PRINCE-PLAYOFF-OUTLOOK:END --> の間だけ。
- 手で持つ情報（地域・行き先・北海道/四国の枠・北信越の組み合わせ・下のチームの対応表・確定の上書き）は
  data/prince_playoff_outlook.yml。東北〜九州の県の枠は league_zones.yml の pref-*-1 をそのまま読む。

セカンドチームの判定（2026-10-12 Kei 決定）:
  同じ学校・クラブのチームは同じリーグに2つ入れない。下のチーム（2nd・B・Ⅱ・S など）は、
  上のチームの「来季のリーグ」を今の順位と league_zones.yml のゾーンから見積もり、それが行き先と同じなら繰り下げる。
  ゾーンの色が付いていない枠は「動かない」。12月のプレミア参入戦の結果は見込まない。
  対応表に無い下のチームが枠の中・枠のすぐ下に来たら [要確認] を出して止まる（表は書き換えない）。
"""
import json
import re
import sys
import unicodedata
from html import escape
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jst import today as _jst_today  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "data" / "prince_playoff_outlook.yml"
ZONES = ROOT / "data" / "league_zones.yml"
MATCHES = ROOT / "data" / "league_matches"
PAGE = ROOT / "tournaments" / "promotion-playoff-2026" / "index.html"
START = "<!-- PRINCE-PLAYOFF-OUTLOOK:START -->"
END = "<!-- PRINCE-PLAYOFF-OUTLOOK:END -->"

LEAGUE_LABEL = {
    "premier": "プレミア", "premier-east": "プレミアEAST", "premier-west": "プレミアWEST",
    "prince-hokkaido": "プリンス北海道", "prince-tohoku": "プリンス東北",
    "prince-kanto-1": "プリンス関東1部", "prince-kanto-2": "プリンス関東2部",
    "prince-hokushinetsu-1": "プリンス北信越1部", "prince-hokushinetsu-2": "プリンス北信越2部",
    "prince-tokai": "プリンス東海", "prince-kansai-1": "プリンス関西1部", "prince-kansai-2": "プリンス関西2部",
    "prince-chugoku": "プリンス中国", "prince-shikoku": "プリンス四国",
    "prince-kyushu-1": "プリンス九州1部", "prince-kyushu-2": "プリンス九州2部", "pref": "県リーグ",
}

# 下のチームの印。B/C/D/S は直前が英字でないときだけ（「いわきFC」「栃木シティFC」の C を拾わない）
_SECOND_RE = re.compile(r"(?:\s?(?:2nd|3rd|4th|セカンド|サード|Ⅱ|Ⅲ|II|III|②|③)|(?<![A-Za-z])\s?[BCDS])$")

NOTE_BLOCK = "※Aチームが同じリーグにいるため繰り下げ"
NOTE_BLOCK_HSE = "※Aチームが同じリーグにいるため出場資格なし（枠の扱いは公式発表待ち）"
NOTE_PROMO = "※Aチームが昇格圏のため出場可（このまま終わった場合）"
NOTE_PREFDOWN = "※Aチームが県リーグ降格圏のため扱いは要確認"
NOTE_HSE17 = "※Aチームが2部へ降格した場合は昇格できません（要項17条）"


class NeedsCheck(Exception):
    """対応表に無い下のチームなど、推測で判定してはいけないもの。"""


def is_second(name: str) -> bool:
    return bool(_SECOND_RE.search(unicodedata.normalize("NFKC", name or "").strip()))


def pts_of(r: dict):
    return r.get("points", r.get("pts"))


def load_json(slug: str) -> dict | None:
    p = MATCHES / f"{slug}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class World:
    def __init__(self):
        self.conf = yaml.safe_load(CONF.read_text(encoding="utf-8"))
        self.zones = (yaml.safe_load(ZONES.read_text(encoding="utf-8")) or {}).get("leagues") or {}
        self.upper = {}          # チーム名 → (slug, rank, チーム数)
        for p in sorted(MATCHES.glob("*.json")):
            slug = p.stem
            if not (slug.startswith("premier-") or slug.startswith("prince-")):
                continue
            st = (json.loads(p.read_text(encoding="utf-8")).get("official_standings") or [])
            for r in st:
                if r.get("team") in self.upper:
                    raise NeedsCheck(f"上のリーグに同じ名前のチームが2つある: {r['team']}")
                self.upper[r["team"]] = (slug, int(r["rank"]), len(st))

    def zone_type(self, slug: str, rank: int, n: int) -> str | None:
        for z in (self.zones.get(slug) or {}).get("zones") or []:
            if "ranks" in z:
                hit = rank in z["ranks"]
            elif z.get("slots"):
                hit = rank <= z["slots"] if z.get("from", "top") == "top" else rank > n - z["slots"]
            else:
                hit = False
            if hit and z.get("type") in ("promotion", "relegation"):
                return z["type"]
        return None

    def next_league(self, team: str, region: str) -> tuple[str, str, str]:
        """(今のリーグ, 来季の見積もり, 理由) を返す。リーグは ladder の段の名前（premier/prince-…/pref）。"""
        slug, rank, n = self.upper[team]
        ladder = self.conf["ladders"][region]
        now = "premier" if slug.startswith("premier-") else slug
        if now not in ladder:
            raise NeedsCheck(f"{team}（{LEAGUE_LABEL.get(slug, slug)}）が {region} の段に無い")
        i = ladder.index(now)
        zt = self.zone_type(slug, rank, n)
        if zt == "promotion" and i > 0:
            return now, ladder[i - 1], f"{LEAGUE_LABEL.get(slug, slug)}{rank}位＝昇格圏"
        if zt == "relegation" and i < len(ladder) - 1:
            return now, ladder[i + 1], f"{LEAGUE_LABEL.get(slug, slug)}{rank}位＝降格圏"
        return now, now, f"{LEAGUE_LABEL.get(slug, slug)}{rank}位"

    def judge(self, pref: str, team: str, region: dict) -> tuple[str, list[str]]:
        """('ok' | 'blocked', 注記) を返す。下のチームでなければ ('ok', [])。"""
        if not is_second(team):
            return "ok", []
        uppers = ((self.conf.get("second_teams") or {}).get(pref) or {}).get(team)
        if not uppers:
            raise NeedsCheck(f"{pref}: 下のチーム「{team}」が対応表（second_teams）に無い")
        dest, key = region["dest"], region["key"]
        notes, blocked = [], []
        for up in uppers:
            if up not in self.upper:
                raise NeedsCheck(f"{pref}: 「{team}」の上のチーム「{up}」がプレミア／プリンスの順位表に無い")
            now, nxt, why = self.next_league(up, key)
            if key == "hokushinetsu" and now == "prince-hokushinetsu-1" and nxt == dest:
                notes.append(f"{NOTE_HSE17}（{up}は{why}）")      # 出場は可・昇格だけ取り消し（要項17条2項）
            elif nxt == dest:
                more = "" if now == nxt else f"＝来季{LEAGUE_LABEL[dest]}の見込み"
                blocked.append(f"{up}は{why}{more}")
            elif nxt == "pref":
                notes.append(f"{NOTE_PREFDOWN}（{up}は{why}）")
            elif now == dest and nxt != dest:      # ここに来るのは昇格だけ（降格の行き先 pref は上で処理済み）
                notes.append(f"{NOTE_PROMO}（{up}は{why}）")
        if blocked:
            return "blocked", [(NOTE_BLOCK_HSE if key == "hokushinetsu" else NOTE_BLOCK) + "（" + "・".join(blocked) + "）"]
        return "ok", notes

    def slots(self, pref: str) -> int | None:
        extra = (self.conf.get("extra_slots") or {}).get(pref)
        if extra:
            return int(extra)
        for z in (self.zones.get(f"pref-{pref}-1") or {}).get("zones") or []:
            if z.get("type") == "playoff" and z.get("slots"):
                return int(z["slots"])
        return None

    def pref_outlook(self, pref: str, region: dict) -> dict:
        conf = (self.conf.get("confirmed") or {}).get(pref)
        n_slots = self.slots(pref)
        data = load_json(f"pref-{pref}-1")
        if n_slots is None:
            raise NeedsCheck(f"{pref}: 枠の数が分からない（league_zones.yml にも extra_slots にも無い）")
        st = sorted((data or {}).get("official_standings") or [], key=lambda r: int(r["rank"]))
        if conf:
            return {"pref": pref, "slots": n_slots, "confirmed": True, "note": conf.get("note", ""),
                    "picked": [{"team": t, "notes": []} for t in conf.get("teams", [])], "blocked": []}
        if not st:
            return {"pref": pref, "slots": n_slots, "picked": [], "blocked": [], "nodata": True}
        remaining = {}
        for m in data.get("matches") or []:
            if m.get("status") != "played":
                for t in (m.get("home"), m.get("away")):
                    remaining[t] = remaining.get(t, 0) + 1
        picked, blocked, tie_partner = [], [], None
        for r in st:
            status, notes = self.judge(pref, r["team"], region)
            if len(picked) >= n_slots:
                if status == "ok":           # 枠のすぐ下で最初に出場できるチーム（同勝点の表示に使う）
                    tie_partner = r
                    break
                continue
            row = {"team": r["team"], "rank": int(r["rank"]), "pts": pts_of(r),
                   "remaining": remaining.get(r["team"], 0), "notes": notes}
            (picked if status == "ok" else blocked).append(row)
        if picked and tie_partner and pts_of(tie_partner) == picked[-1]["pts"]:
            picked[-1]["notes"].insert(0, f"（{tie_partner['team']}と同勝点・公式順位による）")
        return {"pref": pref, "slots": n_slots, "picked": picked, "blocked": blocked}


# ---------------------------------------------------------------- HTML
DISPLAY = {}   # 県1部の表記 → 表示名（yml の display_names。誤解されやすい名前だけ）


def team_cell(p: dict) -> str:
    small = []
    if p.get("pts") is not None:
        small.append(f"勝点{p['pts']}")
    if "remaining" in p:
        small.append("全日程終了" if p["remaining"] == 0 else f"残り{p['remaining']}試合")
    out = f"<strong>{escape(DISPLAY.get(p['team'], p['team']))}</strong>"
    if small:
        out += f' <span class="ppo-sub">（{"・".join(small)}）</span>'
    for n in p.get("notes") or []:
        out += f'<br><span class="ppo-note">{escape(n)}</span>'
    return out


def blocked_html(o: dict) -> str:
    if not o.get("blocked"):
        return ""
    items = [f"{b['rank']}位 {escape(DISPLAY.get(b['team'], b['team']))}"
             + (f"：{escape(b['notes'][0])}" if b["notes"] else "") for b in o["blocked"]]
    return '<br><span class="ppo-note">繰り下げ：' + " ／ ".join(items) + "</span>"


def pref_row(o: dict, name: str) -> str:
    link = f'<a href="/prefectures/{o["pref"]}/">{escape(name)}</a>'
    if o.get("nodata"):
        body = '<span class="ppo-sub">県1部の順位データがありません</span>'
    else:
        body = "<br>".join(team_cell(p) for p in o["picked"]) + blocked_html(o)
        if o.get("confirmed"):
            body = '<span class="ppo-badge">確定</span> ' + body + (
                f'<br><span class="ppo-note">{escape(o["note"])}</span>' if o.get("note") else "")
    return f"<tr><td>{link}<br><span class=\"ppo-sub\">{o['slots']}枠</span></td><td>{body}</td></tr>"


def region_html(w: World, region: dict, outs: dict) -> str:
    head = f'<h3 class="ppo-h3">{escape(region["name"])}（{escape(region["dest_label"])}' \
           f'{"・自動昇格圏" if region.get("auto_promotion") else ""}）</h3>'
    note = f'<p class="ih-note">{escape(region["note"])}</p>' if region.get("note") else ""
    if region["key"] == "hokushinetsu":
        br = w.conf["hokushinetsu_bracket"]
        rows = []
        for g in br["games"]:
            if g.get("text"):
                card = escape(g["text"])
            else:
                def side(ref):
                    pref, k = ref
                    o = outs[pref]
                    nm = region["prefs"][pref]
                    p = o["picked"][k - 1] if len(o["picked"]) >= k else None
                    badge = '<span class="ppo-badge">確定</span> ' if o.get("confirmed") else ""
                    return (f'<a href="/prefectures/{pref}/">{escape(nm)}</a>{k}位 '
                            + (badge + team_cell(p) if p else '<span class="ppo-sub">未定</span>'))
                card = f'{side(g["home"])}<br><span class="ppo-sub">vs</span><br>{side(g["away"])}'
            rows.append(f'<tr><td>{escape(g["game"])}</td><td>{escape(g["when"])}<br>'
                        f'<span class="ppo-sub">{escape(g["venue"])}</span></td><td>{card}</td></tr>')
        blocked = "".join(blocked_html(outs[p]).replace("<br>", f'<br><span class="ppo-sub">{escape(region["prefs"][p])}</span> ', 1)
                          for p in region["prefs"] if outs[p].get("blocked"))
        return (head + f'<p class="ih-note">組み合わせ（試合番号・日時・会場・「◯県◯位」）は '
                f'<a href="{escape(br["source_url"])}" target="_blank" rel="noopener">{escape(br["source_label"])}</a> の発表（'
                f'{escape(br["venue_note"])}）。チーム名だけを県1部の今の順位から入れています。</p>'
                '<div class="ppo-scroll"><table class="ih-history-table ppo-table ppo-bracket"><thead><tr><th>試合</th><th>日時・会場</th>'
                '<th>組み合わせ（暫定のチーム名）</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
                + (f'<p class="ih-note">{blocked[4:]}</p>' if blocked else ""))
    rows = "".join(pref_row(outs[p], nm) for p, nm in region["prefs"].items())
    return (head + note + '<div class="ppo-scroll"><table class="ih-history-table ppo-table"><thead><tr><th>県</th>'
            '<th>暫定出場チーム</th></tr></thead><tbody>' + rows + "</tbody></table></div>")


STYLE = (
    "<style>"
    ".ppo-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:6px 0 14px;}"
    # 見出しは左寄せ（ブラウザ初期値の th＝中央 だと中身とずれる）。1列目の幅を固定して9地域の表で列の位置をそろえる
    ".ppo-table{width:100%;table-layout:fixed;}"
    ".ppo-table th,.ppo-table td{padding:6px 12px 6px 0;vertical-align:top;text-align:left;}"
    ".ppo-table th:first-child,.ppo-table td:first-child{width:5.5em;white-space:nowrap;}"
    ".ppo-table.ppo-bracket th:nth-child(2),.ppo-table.ppo-bracket td:nth-child(2){width:8.5em;}"
    ".ppo-table td{overflow-wrap:anywhere;}"
    ".ppo-h3{margin:22px 0 6px;font-size:1.05em;}"
    ".ppo-sub{font-size:0.82em;color:var(--text-light,#6b7280);}"
    ".ppo-note{font-size:0.82em;color:var(--text-light,#6b7280);}"
    ".ppo-badge{display:inline-block;font-size:0.75em;font-weight:700;padding:1px 6px;border-radius:4px;"
    "background:var(--accent-color,#2563eb);color:#fff;}"
    "</style>"
)


def build(w: World) -> str:
    today = _jst_today()
    for names in (w.conf.get("display_names") or {}).values():
        DISPLAY.update(names or {})
    outs, parts = {}, []
    for region in w.conf["regions"]:
        for pref in region["prefs"]:
            outs[pref] = w.pref_outlook(pref, region)
        parts.append(region_html(w, region, outs))
    return (
        '\n      <section class="lp-section" id="prince-playoff-outlook">\n'
        '        <h2><i class="fas fa-ranking-star"></i> 各地域のプリンスリーグ参入戦　暫定出場チーム（県1部の順位がこのまま終わった場合）</h2>\n'
        f'        <p class="ih-note"><strong>{today.month}月{today.day}日時点の県1部の順位による暫定です。</strong>'
        '各県の代表の決め方や枠の数は年度・県によって異なることがあり、公式発表を優先します。'
        '同じ学校・クラブのチームは同じリーグに入れないため、上のチームの来季のリーグ（今の順位とリーグの昇格・降格圏から見積もり。'
        '12月のプレミア参入戦の結果は見込まない）が行き先と同じセカンドチームは、次の順位に繰り下げています。</p>\n'
        f"        {STYLE}\n        " + "\n        ".join(parts) + "\n      </section>\n"
    )


def main() -> int:
    try:
        w = World()
        html = build(w)
    except NeedsCheck as e:
        print(f"[要確認] プリンス参入戦の暫定表: {e}（表は書き換えません）")
        return 0
    src = PAGE.read_text(encoding="utf-8")
    if START not in src or END not in src:
        print(f"[要確認] プリンス参入戦の暫定表: {PAGE} にマーカーが無い（表は書き換えません）")
        return 0
    pre, rest = src.split(START, 1)
    _, post = rest.split(END, 1)
    new = pre + START + html + "      " + END + post
    if new != src:
        PAGE.write_text(new, encoding="utf-8")
    print(f"OK: 参入戦ページの暫定出場チーム表を書きました（{len(w.conf['regions'])}地域）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
