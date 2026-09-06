#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日本時間（JST）の「いま」を返す小さなヘルパ
==============================================
2026-09-07 新設。

なぜ要るか
----------
GitHub Actions のサーバーは**世界標準時（UTC）**で動いている。素の `date.today()` を使うと、
日本の朝9時までに走ったジョブは**前日の日付**を書いてしまう。

実際に起きたこと（2026-09-07）：同じ県ページの中で

  AI要約        「【2026年9月7日時点】…」  ← ページ生成側はJST化済みだった
  戦績表の見出し 「最終更新 2026-09-06」    ← JSONに書かれた日付がUTC

と**1日ずれた**。22:00 JST の定期実行は UTC では前日13:00なので、毎回ずれる。

Kei の Mac（JST）で手で実行すると正しい日付になるため、**手元では再現しない**のが厄介なところ。

使い方
------
    from jst import today, now
    data["lastUpdated"] = today().isoformat()          # 2026-09-07
    stamp = now().strftime("%Y-%m-%dT%H:%M:%S")        # 2026-09-07T01:20:06

⚠️ 新しくスクリプトを書くときは `date.today()` / `datetime.now()` を**直接使わない**こと。
   ページ生成側（generate_*.py）は各ファイルの `_JSTDate` シムで既にJST化されている。
"""
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def now() -> datetime:
    """JSTの現在時刻（tz情報つき）"""
    return datetime.now(JST)


def today():
    """JSTの「今日」の日付"""
    return now().date()
