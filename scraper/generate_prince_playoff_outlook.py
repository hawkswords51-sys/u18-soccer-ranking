#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参入戦ページに「各地域のプリンスリーグ参入戦 暫定出場チーム」の表を出す（2026-10-12 新設）。

- 県1部の今の順位（data/league_matches/pref-*-1.json の official_standings）から、
  「このまま終わったら各地域のプリンスリーグ参入戦に出るチーム」を9地域ぶん作る。
- 書き換えるのは tournaments/promotion-playoff-2026/index.html の
  <!-- PRINCE-PLAYOFF-OUTLOOK:START --> 〜 <!-- PRINCE-PLAYOFF-OUTLOOK:END --> の間だけ。
- [2026-10-12] 同じページの「プレミア参入プレーオフ 出場決定チーム（16枠）」の表にも、各行の
  <!-- PPO-PREMIER:prince-xxx --> 〜 <!-- /PPO-PREMIER --> の中に今の順位の暫定チームを入れる（確定チームは手書きのまま）。
- 手で持つ情報（地域・行き先・北海道/四国の枠・北信越の組み合わせ・下のチームの対応表・確定の上書き）は
  data/prince_playoff_outlook.yml。東北〜九州の県の枠は league_zones.yml の pref-*-1 をそのまま読む。

セカンドチームの判定（2026-10-12 Kei 決定）:
  同じ学校・クラブのチームは同じリーグに2つ入れない。下のチーム（2nd・B・Ⅱ・S など）は、
  上のチームの「来季のリーグ」を今の順位と league_zones.yml のゾーンから見積もり、それが行き先と同じなら繰り下げる。
  ゾーンの色が付いていない枠は「動かない」。12月のプレミア参入戦の結果は見込まない。
  対応表に無い下のチームが枠の中・枠のすぐ下に来たら [要確認] を出して止まる（表は書き換えない）。
  [2026-11-24 条件つき] 上のチームのリーグがまだ動くときは、言い切らずに条件を書く（判定は変えない）。
    ・繰り下げなのに、上のチームが行き先のリーグから出ていく可能性がある
      （リーグ内で昇格圏に届く／降格圏から残留できる／プレミア参入戦に出場確定・暫定出場）→「ただし…出場の可能性」
    ・出場なのに、上のチームが上のリーグから行き先のリーグへ落ちてくる可能性がある →「降格した場合は繰り下げ」
    「届く可能性」は 勝点＋3×残り試合 ≧ 境目のチームの今の勝点 で見る（直接対決などの細かい計算はしない）。
    プレミア参入戦の出場は、同じページの16枠の表（手書きの確定＋暫定）と同じ判定。結果は yml の premier_playoff_results。
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
NOTE_PREMIER_UP = "※Aチームがプレミアに昇格したため出場可"


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
        self.tables = {}         # slug → (順位の並びの official_standings, チーム名 → 残り試合数)
        self.ppo = None          # プレミア参入戦に出るチーム → "確定" | "暫定"（main で16枠の表から入れる）
        self.ppo_results = {k: str(v) for k, v in (self.conf.get("premier_playoff_results") or {}).items()}
        for k, v in self.ppo_results.items():
            if v not in ("昇格", "残留"):
                raise NeedsCheck(f"premier_playoff_results の {k} が「昇格」「残留」のどちらでもない: {v}")
        for p in sorted(MATCHES.glob("*.json")):
            slug = p.stem
            if not (slug.startswith("premier-") or slug.startswith("prince-")):
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            st = sorted(d.get("official_standings") or [], key=lambda r: int(r["rank"]))
            rem = {}
            for m in d.get("matches") or []:
                if (m or {}).get("status") != "played":
                    for t in ((m or {}).get("home"), (m or {}).get("away")):
                        if t:
                            rem[t.strip()] = rem.get(t.strip(), 0) + 1
            self.tables[slug] = (st, rem)
            for r in st:
                if r.get("team") in self.upper:
                    raise NeedsCheck(f"上のリーグに同じ名前のチームが2つある: {r['team']}")
                self.upper[r["team"]] = (slug, int(r["rank"]), len(st))

    def zone_ranks(self, slug: str, ztype: str) -> list[int]:
        """そのリーグの promotion / relegation の順位（無ければ空）。"""
        n = len(self.tables.get(slug, ([], {}))[0])
        out = []
        for z in (self.zones.get(slug) or {}).get("zones") or []:
            if z.get("type") != ztype:
                continue
            if "ranks" in z:
                out += [int(x) for x in z["ranks"]]
            elif z.get("slots"):
                s = int(z["slots"])
                out += list(range(1, s + 1)) if z.get("from", "top") == "top" else list(range(n - s + 1, n + 1))
        return sorted(out)

    def _pts_rem(self, slug: str, rank: int):
        st, rem = self.tables[slug]
        r = st[rank - 1]
        return pts_of(r), rem.get(r["team"], 0), r["team"]

    def can_rise(self, team: str):
        """昇格圏の外にいて、まだ届く可能性があれば (境目の順位, 勝点差, 残り試合)。無ければ None。"""
        slug, rank, n = self.upper[team]
        zr = self.zone_ranks(slug, "promotion")
        if not zr or rank in zr:
            return None
        k = max(zr)
        p, r, _ = self._pts_rem(slug, rank)
        bp, _, _ = self._pts_rem(slug, k)
        return (k, bp - p, r) if p + 3 * r >= bp else None

    def can_escape(self, team: str):
        """降格圏にいて、まだ残留できる可能性があれば (残留圏の最後の順位, 勝点差, 残り試合)。"""
        slug, rank, n = self.upper[team]
        zr = self.zone_ranks(slug, "relegation")
        if not zr or rank not in zr or min(zr) < 2:
            return None
        k = min(zr) - 1
        p, r, _ = self._pts_rem(slug, rank)
        bp, _, _ = self._pts_rem(slug, k)
        return (k, bp - p, r) if p + 3 * r >= bp else None

    def can_fall(self, team: str):
        """降格圏の外にいて、降格圏のどれかのチームに抜かれる可能性があれば (降格圏の最初の順位, 勝点差)。"""
        slug, rank, n = self.upper[team]
        zr = self.zone_ranks(slug, "relegation")
        if not zr or rank in zr:
            return None
        p, _, _ = self._pts_rem(slug, rank)
        hit = any(self._pts_rem(slug, z)[0] + 3 * self._pts_rem(slug, z)[1] >= p for z in zr if z <= n)
        return (min(zr), p - self._pts_rem(slug, min(zr))[0]) if hit else None

    def promo_clinched(self, team: str) -> bool:
        """昇格圏にいて、圏外のどのチームも今の勝点に届かない＝昇格確定（2026-11-26 九州・佐賀東で新設）。
        can_rise と同じ「勝点＋3×残り試合」で見る。同勝点に届くだけでも「まだ」とする（順位の決め方は見ない）。"""
        slug, rank, n = self.upper[team]
        zr = self.zone_ranks(slug, "promotion")
        if not zr or rank not in zr:
            return False
        p, _, _ = self._pts_rem(slug, rank)
        return not any(self._pts_rem(slug, k)[0] + 3 * self._pts_rem(slug, k)[1] >= p
                       for k in range(1, n + 1) if k not in zr)

    def conditions(self, up: str, now: str, nxt: str, ladder: list[str]) -> list[str]:
        """繰り下げ（nxt＝行き先）だが、上のチームが行き先から出ていく可能性があるときの「ただし…」の文。"""
        out = []
        slug = self.upper[up][0]
        if now == nxt:
            c = self.can_rise(up)
            if c:
                k, gap, r = c
                gap_s = "同勝点" if gap == 0 else f"{gap}差"
                out.append(f"ただし{up}が{LEAGUE_LABEL[ladder[ladder.index(now) - 1]]}に上がれば出場の可能性"
                           f"（昇格圏の{k}位と{gap_s}・残り{r}試合）")
            if self.ppo is None:
                raise NeedsCheck("プレミア参入戦の出場チーム（16枠の表）を読む前に判定しようとした")
            if up not in self.ppo_results and up in self.ppo:
                if self.ppo[up] == "確定":
                    out.append(f"ただし{up}がプレミア参入戦で昇格すれば出場の可能性")
                else:
                    out.append(f"ただし{up}がプレミア参入戦に出場し、昇格すれば出場の可能性（参入戦は今の順位での暫定出場）")
        else:
            c = self.can_escape(up)
            if c:
                k, gap, r = c
                gap_s = "同勝点" if gap == 0 else f"{gap}差"
                out.append(f"ただし{up}が{LEAGUE_LABEL.get(slug, slug)}に残留すれば出場の可能性（残留圏の{k}位と{gap_s}・残り{r}試合）")
        return out

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
        """('ok' | 'blocked' | 'blocked_cond', 注記) を返す。下のチームでなければ ('ok', [])。
        blocked_cond ＝ 今は繰り下げだが、上のチームのリーグしだいで出場の可能性があるもの（2026-11-24）。"""
        if not is_second(team):
            return "ok", []
        uppers = ((self.conf.get("second_teams") or {}).get(pref) or {}).get(team)
        if not uppers:
            raise NeedsCheck(f"{pref}: 下のチーム「{team}」が対応表（second_teams）に無い")
        dest, key = region["dest"], region["key"]
        ladder = self.conf["ladders"][key]
        notes, blocked, conds = [], [], []
        for up in uppers:
            if up not in self.upper:
                raise NeedsCheck(f"{pref}: 「{team}」の上のチーム「{up}」がプレミア／プリンスの順位表に無い")
            now, nxt, why = self.next_league(up, key)
            if self.ppo_results.get(up) == "昇格" and now != "premier":
                notes.append(f"{NOTE_PREMIER_UP}（{up}はプレミア参入戦で昇格）")
            elif key == "hokushinetsu" and now == "prince-hokushinetsu-1" and nxt == dest:
                notes.append(f"{NOTE_HSE17}（{up}は{why}）")      # 出場は可・昇格だけ取り消し（要項17条2項）
            elif nxt == dest:
                more = "" if now == nxt else f"＝来季{LEAGUE_LABEL[dest]}の見込み"
                blocked.append(f"{up}は{why}{more}")
                conds += self.conditions(up, now, nxt, ladder)
            elif nxt == "pref":
                notes.append(f"{NOTE_PREFDOWN}（{up}は{why}）")
            elif now == dest and nxt != dest:      # ここに来るのは昇格だけ（降格の行き先 pref は上で処理済み）
                if self.promo_clinched(up):        # 昇格が決まったら「このまま終わった場合」を付けない
                    _s, _r, _n = self.upper[up]
                    notes.append(f"※Aチームが{LEAGUE_LABEL[nxt]}への昇格を決めたため出場可"
                                 f"（{up}は{LEAGUE_LABEL.get(_s, _s)}{_r}位＝昇格決定）")
                else:
                    notes.append(f"{NOTE_PROMO}（{up}は{why}）")
            elif nxt == now and now in ladder and ladder.index(now) + 1 < len(ladder) \
                    and ladder[ladder.index(now) + 1] == dest:
                c = self.can_fall(up)              # 今は上のリーグに残る見込みだが、落ちると行き先と同じリーグ
                if c:
                    k, gap = c
                    gap_s = "同勝点" if gap == 0 else f"{gap}差"
                    notes.append(f"※Aチームが降格圏まで{gap_s}のため、降格した場合は繰り下げ（{up}は{why}）")
        if blocked:
            if conds and len(blocked) > 1:
                raise NeedsCheck(f"{pref}: 「{team}」は上のチーム2つが同じリーグにいて、条件つきの書き方を決められない")
            note = (NOTE_BLOCK_HSE if key == "hokushinetsu" else NOTE_BLOCK) + "（" + "・".join(blocked) + "）"
            if conds:
                return "blocked_cond", [note + "。" + "。".join(conds)]
            return "blocked", [note]
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
                   "remaining": remaining.get(r["team"], 0), "notes": notes, "cond": status == "blocked_cond"}
            (picked if status == "ok" else blocked).append(row)
        if picked and tie_partner and pts_of(tie_partner) == picked[-1]["pts"]:
            picked[-1]["notes"].insert(0, f"（{tie_partner['team']}と同勝点・公式順位による）")
        # 条件つきの繰り下げがあれば、押し出されうる側（枠の最後から）にも印を付ける（2026-11-24）
        for j, b in enumerate(x for x in blocked if x["cond"]):
            if j < len(picked):
                picked[-(j + 1)]["notes"].append(f"※{DISPLAY.get(b['team'], b['team'])}が出場になった場合は入れ替わり")
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


PREF_SUFFIX = {"tokyo": "都", "hokkaido": "", "osaka": "府", "kyoto": "府"}


def region_html(w: World, region: dict, outs: dict) -> str:
    head = f'<h3 class="ppo-h3">{escape(region["name"])}（{escape(region["dest_label"])}' \
           f'{"・自動昇格圏" if region.get("auto_promotion") else ""}）</h3>'
    note = f'<p class="ih-note">{escape(region["note"])}</p>' if region.get("note") else ""
    # 公式の組み合わせが出た地域は「組み合わせ表」で出す（yml に <地域key>_bracket があれば）。
    #   2026-10-12 北信越で新設 → 2026-11-23 関東を足すときに地域を決め打ちしない形にした。
    #   ref_style: "代表" … 枠が各県1つの地域（関東）。「茨城県代表」と書く（北信越は「石川1位」のまま）。
    #   ref_style: "第◯代表" … 公式が「大阪府第1代表」と書く地域（関西・2026-11-23）。
    #   note: … 説明文のあとに足す1文（試合方式・会場変更の注記など）。
    #   結果（2026-11-23 北信越で新設。地域は決め打ちしない）:
    #     result: {home: 1, away: 1, pk: [6, 7]} … その試合のスコア（pk は同点のときだけ）。「vs」の位置にスコアを出し、
    #               勝者に「勝ち上がり」、promote: true の試合の勝者に「2部昇格決定」（promote_label で変更可）。
    #     from: ["3011", "3012"] … 2試合の勝者どうし（先の試合の勝者がホーム側）。両方に result があれば
    #               text: の代わりにチーム名のカードを出す。片方でも無ければ text: のまま。
    #     同点で pk が無い・pk も同点 → NeedsCheck で止まる（勝者を勝手に決めない）。
    #   その地域の県が全部 confirmed なら、見出しを「組み合わせ・結果」、説明文を「公式の発表によります」にする。
    br = w.conf.get(f'{region["key"]}_bracket')
    if br:
        style = br.get("ref_style")
        rep = style in ("代表", "第◯代表")
        rows, winners = [], {}

        def decide(g, home_p, away_p):
            """result から勝者（チームの dict）を返す。result が無ければ None。"""
            r = g.get("result")
            if not r:
                return None
            h, a = int(r["home"]), int(r["away"])
            if h == a:
                pk = r.get("pk")
                if not pk or len(pk) != 2 or int(pk[0]) == int(pk[1]):
                    raise NeedsCheck(f'{region["key"]}_bracket {g["game"]}: 同点 {h}-{a} なのに PK の勝者が書かれていない')
                h, a = int(pk[0]), int(pk[1])
            if home_p is None or away_p is None:
                raise NeedsCheck(f'{region["key"]}_bracket {g["game"]}: 結果があるのにチームが決まっていない')
            return home_p if h > a else away_p

        def score_html(g):
            r = g["result"]
            pk = r.get("pk")
            return (f'<br><strong>{int(r["home"])} - {int(r["away"])}</strong>'
                    + (f'<span class="ppo-sub">（PK {int(pk[0])}-{int(pk[1])}）</span>' if pk else "") + "<br>")

        def win_badge(g, p, win):
            if p is None or p is not win:
                return ""
            label = br.get("promote_label", "2部昇格決定") if g.get("promote") else "勝ち上がり"
            return f' <span class="ppo-badge">{escape(label)}</span>'

        for g in br["games"]:
            src = g.get("from")
            if src and all(s_ in winners and winners[s_] for s_ in src):
                hp, ap = winners[src[0]], winners[src[1]]
                win = decide(g, hp, ap)
                winners[g["game"]] = win
                mid = score_html(g) if win else '<br><span class="ppo-sub">vs</span><br>'
                card = (team_cell(hp) + win_badge(g, hp, win) + mid + team_cell(ap) + win_badge(g, ap, win))
            elif g.get("text"):
                winners[g["game"]] = None
                card = escape(g["text"])
            else:
                def side(ref):
                    pref, k = ref
                    o = outs[pref]
                    nm = region["prefs"][pref]
                    p = o["picked"][k - 1] if len(o["picked"]) >= k else None
                    badge = '<span class="ppo-badge">確定</span> ' if o.get("confirmed") else ""
                    label = (f"{nm}{PREF_SUFFIX.get(pref, '県')}{f'第{k}' if style == '第◯代表' else ''}代表"
                             if rep else nm)
                    return (f'<a href="/prefectures/{pref}/">{escape(label)}</a>{"" if rep else f"{k}位"} '
                            + (badge + team_cell(p) if p else '<span class="ppo-sub">未定</span>')), p
                (hs, hp), (as_, ap) = side(g["home"]), side(g["away"])
                win = decide(g, hp, ap)
                winners[g["game"]] = win
                mid = score_html(g) if win else '<br><span class="ppo-sub">vs</span><br>'
                card = hs + win_badge(g, hp, win) + mid + as_ + win_badge(g, ap, win)
            rows.append(f'<tr><td>{escape(g["game"])}</td><td>{escape(g["when"])}<br>'
                        f'<span class="ppo-sub">{escape(g["venue"])}</span></td><td>{card}</td></tr>')
        all_conf = all(outs[p].get("confirmed") for p in region["prefs"])
        blocked = "".join(blocked_html(outs[p]).replace("<br>", f'<br><span class="ppo-sub">{escape(region["prefs"][p])}</span> ', 1)
                          for p in region["prefs"] if outs[p].get("blocked"))
        return (head + f'<p class="ih-note">組み合わせ（試合番号・日時・会場・{"「◯府県第◯代表」" if style == "第◯代表" else "「◯県代表」" if rep else "「◯県◯位」"}）は '
                f'<a href="{escape(br["source_url"])}" target="_blank" rel="noopener">{escape(br["source_label"])}</a> の発表（'
                f'{escape(br["venue_note"])}）。'
                + ("出場チームと結果は公式の発表によります。" if all_conf else "チーム名だけを県1部の今の順位から入れています。")
                + (escape(br["note"]) if br.get("note") else "") + '</p>'
                '<div class="ppo-scroll"><table class="ih-history-table ppo-table ppo-bracket"><thead><tr><th>試合</th><th>日時・会場</th>'
                '<th>' + ("組み合わせ・結果" if all_conf else "組み合わせ（暫定のチーム名）") + '</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
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
        '同じ学校・クラブのチームは同じリーグに入れないため、上のチームの来季のリーグを今の順位で見積もり、'
        '行き先と同じリーグになるセカンドチームは次の順位に繰り下げています（上のチームが行き先と違うリーグなら出場できます）。'
        '上のチームの昇格・降格や12月のプレミア参入戦の結果しだいで繰り下げが変わる場合は、その条件を書いています。</p>\n'
        f"        {STYLE}\n        " + "\n        ".join(parts) + "\n      </section>\n"
    )


# ---------------------------------------------------------------- プレミア参入 16枠の表の暫定（2026-10-12）
# 「プレミア参入プレーオフ2026 出場決定チーム（16枠）」の各行の3列目にある
#   <!-- PPO-PREMIER:prince-xxx --> 〜 <!-- /PPO-PREMIER -->
# の中だけを書き換え、未定の枠に今の順位の暫定チームを出す。
# ⚠️ 確定チームはマーカーの外に手で書く（今までどおり）。合計行の「N ／ 16 決定」は確定の数のまま・暫定は数えない。
#    audit_premier_playoff.py がこの文字を読むので、暫定の部分には「◯ ／ 16」の形の文字を入れない。
_PREM_RE = re.compile(r"(<tr><td><a href=\"/leagues/(prince-[a-z0-9-]+)/\">.*?</td><td>(\d+)</td><td[^>]*>)(.*?)"
                      r"<!-- PPO-PREMIER:\2 -->.*?<!-- /PPO-PREMIER -->", re.S)


def _canon_team(n: str) -> str:
    n = unicodedata.normalize("NFKC", n or "").replace(" ", "").replace("　", "")
    for suf in ("高等学校", "高校"):
        if n.endswith(suf) and len(n) > len(suf):
            n = n[:-len(suf)]
    return n


def _alias_groups() -> list[set[str]]:
    """data/teams.json の「正式名＋aliases」を1チーム1組にして返す（_canon_team 済み）。
    [2026-11-21 Kei判断(a)] ページの確定チームは正式名（例「立正大学淞南高校」）、JFA順位表は略称（「立正大淞南」）で
    「高校」を外すだけでは揃わない。teams.json の aliases に略称が入っているので、それを照合に使う。"""
    try:
        data = json.loads((ROOT / "data" / "teams.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    # teams.json は {県キー: {"name": 県名, "teams": [...]}} の形
    prefs = list(data.values()) if isinstance(data, dict) else list(data)
    groups = []
    for p in prefs:
        if not isinstance(p, dict):
            continue
        for t in (p or {}).get("teams") or []:
            names = [t.get("name")] + list(t.get("aliases") or [])
            g = {_canon_team(n) for n in names if n}
            if g:
                groups.append(g)
    return groups


def _hit_by_alias(written: str, canon: dict, groups: list[set[str]]) -> str | None:
    """written と同じチームの別名のうち、順位表に**ちょうど1つ**だけ当たるものがあればその順位表の名前。"""
    w = _canon_team(written)
    hits = {canon[n] for g in groups if w in g for n in g if n in canon}
    return hits.pop() if len(hits) == 1 else None


def _premier_ctx() -> dict:
    import audit_premier_playoff as ap
    from league_zones import _base_team_name, is_second_team, premier_teams_from_league_matches
    return {"ap": ap, "base": _base_team_name, "is2": is_second_team,
            "premier": {t["name"] for t in premier_teams_from_league_matches(ROOT)},
            "zones": dict(ap.playoff_zones()), "groups": _alias_groups()}


def _premier_row(c: dict, slug: str, slots: int, outside: str):
    """16枠の表の1行ぶん：(手書きの確定チーム名, 順位表で当たった確定チーム, 暫定チーム, 対象外のセカンド, 枠のすぐ下, 残り試合)。
    [2026-11-24] 参入戦ページの「条件つきの繰り下げ」でも同じ判定を使うため、premier_slot_rows から切り出した。"""
    ap, premier, zones, groups = c["ap"], c["premier"], c["zones"], c["groups"]
    if zones.get(slug) != slots:
        raise NeedsCheck(f"16枠の表の {slug} の枠 {slots} が league_zones.yml の {zones.get(slug)} と違う")
    d = ap.load_league(slug, MATCHES) or {}
    st = sorted(d.get("official_standings") or [], key=lambda r: int(r["rank"]))
    rem = ap.remaining_counts(d.get("matches"))
    written = re.findall(r"<strong>(?:<a [^>]*>)?([^<]+)(?:</a>)?</strong>", outside)
    canon = {_canon_team(r["team"]): r["team"] for r in st}
    confirmed = set()
    for w_ in written:
        hit = canon.get(_canon_team(w_)) or _hit_by_alias(w_, canon, groups)
        if not hit:
            raise NeedsCheck(f"16枠の表の {slug} の確定チーム「{w_}」が順位表のどのチームとも合わない")
        confirmed.add(hit)
    need = slots - len(confirmed)
    if need < 0:
        raise NeedsCheck(f"16枠の表の {slug} に確定チームが枠より多い（{len(confirmed)}／{slots}）")
    picks, skipped, nxt = [], [], None
    for r in st:
        t = r["team"]
        if t in confirmed:
            continue
        if c["is2"](t) and c["base"](t) in premier:
            if len(picks) < need:
                skipped.append(t)
            continue
        if len(picks) < need:
            picks.append(r)
        else:
            nxt = r
            break
    return written, confirmed, picks, skipped, nxt, rem


def premier_playoff_teams(src: str) -> dict:
    """16枠の表から、プレミア参入戦に出るチーム → "確定"（手書き）| "暫定"（今の順位）。"""
    c = _premier_ctx()
    out = {}
    for m in _PREM_RE.finditer(src):
        _, confirmed, picks, _, _, _ = _premier_row(c, m.group(2), int(m.group(3)), m.group(4))
        out.update({t: "確定" for t in confirmed})
        out.update({r["team"]: "暫定" for r in picks})
    if not out:
        raise NeedsCheck("16枠の表からプレミア参入戦の出場チームを読めない")
    return out


def premier_slot_rows(src: str) -> tuple[str, int]:
    """16枠の表の各行を書き換えた src と、暫定を出したチーム数を返す。読めない／合わないときは NeedsCheck。"""
    c = _premier_ctx()
    zones = c["zones"]
    total = 0

    def one(m):
        nonlocal total
        head, slug, slots, outside = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        written, confirmed, picks, skipped, nxt, rem = _premier_row(c, slug, slots, outside)
        parts = []
        for r in picks:
            # ⚠️ Actions は Python 3.11。f文字列の中に同じ引用符を入れ子にできない（3.12 から可）ので、先に組み立てる
            n_rem = rem.get(r["team"], 0)
            rest = "全日程終了" if n_rem == 0 else f"残り{n_rem}試合"
            parts.append(f'<span class="ppo-sub">暫定：{escape(r["team"])}（{r["rank"]}位・勝点{pts_of(r)}・{rest}）</span>')
        if picks and nxt is not None:
            diff = pts_of(picks[-1]) - pts_of(nxt)
            gap = "同勝点" if diff == 0 else f"{diff}差"
            parts.append(f'<span class="ppo-note">（{nxt["rank"]}位 {escape(nxt["team"])}と{gap}）</span>')
        for t in skipped:
            parts.append(f'<span class="ppo-note">※{escape(t)}はプレミア所属チームのセカンドのため対象外</span>')
        total += len(picks)
        body = ("<br>" if parts and written else "") + "<br>".join(parts) if parts else ""
        if not parts and not written:
            body = '<span class="ppo-sub">未定</span>'
        return head + outside + f"<!-- PPO-PREMIER:{slug} -->{body}<!-- /PPO-PREMIER -->"

    new, n = _PREM_RE.subn(one, src)
    if n != len(zones):
        raise NeedsCheck(f"16枠の表で書き換えの印を読めた行が{n}行（league_zones.yml の参入戦リーグは{len(zones)}）")
    return new, total


def main() -> int:
    src = PAGE.read_text(encoding="utf-8")
    new = src
    # --- 各地域のプリンスリーグ参入戦 暫定出場チーム ---
    try:
        w = World()
        w.ppo = premier_playoff_teams(new)
        html = build(w)
        if START not in new or END not in new:
            raise NeedsCheck(f"{PAGE} にマーカーが無い")
        pre, rest = new.split(START, 1)
        _, post = rest.split(END, 1)
        new = pre + START + html + "      " + END + post
        print(f"OK: 参入戦ページの暫定出場チーム表を書きました（{len(w.conf['regions'])}地域）")
    except NeedsCheck as e:
        print(f"[要確認] プリンス参入戦の暫定表: {e}（表は書き換えません）")
    # --- プレミア参入 16枠の表の暫定 ---
    try:
        new, n = premier_slot_rows(new)
        print(f"OK: 16枠の表に暫定チームを{n}チーム書きました（確定チームと「N ／ 16 決定」は手書きのまま）")
    except NeedsCheck as e:
        print(f"[要確認] 16枠の表の暫定: {e}（この表は書き換えません）")
    if new != src:
        PAGE.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
