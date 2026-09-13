#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""県内総合順位の並べ替えキー（正本）

2026-09-13 新設。それまで並べ替えのルールは generate_prefecture_pages.py の
sort_teams() の中にだけあり、data/teams.json の prefectureRank は
別のルール（リーグ内順位＋leagueRank）で振られていて食い違っていた。
食い違いは「配列順まかせ＝毎回入れ替わる」という形で表に出ていた。

⚠️ 並べ替えのルールはこのファイルにだけ書く。呼ぶ側にコピーしないこと。
"""


def league_category(team_league: str) -> str:
    """プレミア / プリンス / 県リーグ の3分類"""
    lg = team_league or ""
    if "プレミアリーグ" in lg:
        return "premier"
    if "プリンスリーグ" in lg:
        return "prince"
    return "prefecture"


_TIER = {"premier": 0, "prince": 1, "prefecture": 2}


def league_division(team_league: str) -> int:
    """リーグ名から 1部/2部/3部 を数値で返す。部の表記が無ければ0。
    （プレミアEAST/WEST、プリンス東海・中国・四国・東北・北海道、
      および多くの県リーグは部の表記を持たない）"""
    lg = team_league or ""
    if not lg:
        return 9
    if "1部" in lg:
        return 1
    if "2部" in lg:
        return 2
    if "3部" in lg:
        return 3
    return 0


def pref_sort_key(t: dict):
    """県内総合順位の並べ替えキー。
    格 → 部 → リーグ内順位 → 勝点 → 得失点差 → 得点 → 名前。
    ⚠️ 最後に name を入れて**完全に一意**にする。ここが同値だと
       「安定ソート＝配列順まかせ」に戻り、また毎回入れ替わる。
    """
    gf = t.get("goalsFor", 0) or 0
    ga = t.get("goalsAgainst", 0) or 0
    return (
        _TIER.get(league_category(t.get("league")), 9),
        league_division(t.get("league")),
        t.get("leagueRank") or 99,
        -(t.get("points", 0) or 0),
        -(gf - ga),
        -gf,
        t.get("name", ""),
    )
