#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
県1部を「県サッカー協会 公式」から更新する
==============================================
2026-09-06 新設。

なぜ作ったか
------------
県1部のこれまでの出典 junior-soccer.jp は **GitHub Actions から403で弾かれる**ように
なり（Cloudflareが送信元IPで遮断）、2026-07-15以降ずっと自動更新が止まっていた。
調べたところ **一部の県は県協会の公式システムにデータがあり、定形URLの素のHTMLで取れる**。
対象は増えていくので、**実数は下の PREF_OFFICIAL を数えること**（2026-09-07時点で14県）。

移行して得られるもの:
  1. 自動更新に戻せる（junior-soccerではないドメインなので403にならない）
  2. 出典の格が上がる（junior-soccer は自ら「公式結果ではありません」と明記するファン投稿型）
  3. 誤りが消える。実例＝愛知は9/5「日福大付 1-0 名古屋」が誤りで公式は 1-2 名古屋の勝ち。
     岩手は同じ試合が2行重複していて順位表も二重計上されていた（29pt/13試合 → 公式26pt/12試合）
  4. 佐賀が初めて自動で取れるようになる（これまで唯一データ源が無かった県）

データ源は2系統
---------------
  GoalNote (6県) https://www.goalnote.net/detail-standings.php?tid={tid}
                 https://www.goalnote.net/detail-schedule.php?tid={tid}
  tecra    (3県) https://{host}/order/1/{season}/all   （順位表）
                 https://{host}/match/1/{season}/all   （試合結果）
                 ※ 2026-09-06に3ドメイン×パスを実測。`/all` の有無で結果は変わらない

安全設計（update_pref_cross_tables.py と同じ思想）
--------------------------------------------------
  1. 公式のチーム名を既存JSONのチーム名へ名寄せし、**1対1（全単射）が取れた県だけ**処理する
  2. 試合一覧から再計算した順位が、公式の順位表と**全項目一致**したときだけ書き込む
  3. 公式の消化試合数が既存より少なければ**据え置き**（退行防止）
  4. どれかに落ちたらそのファイルは1バイトも書かず、理由をログに出す

使い方
------
  python scraper/fetch_pref_official.py             # 取得して書き込む
  python scraper/fetch_pref_official.py --dry-run   # 書き込まず、既存との差分だけ出す
  python scraper/fetch_pref_official.py --only aichi,saga
"""
import argparse
import collections
import json
import re
import sys
import time
import unicodedata
from datetime import date as _date
from jst import today as _jst_today
import fetch_status
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 既存の県1部スクリプトから、名寄せ・検算・JSON組み立てをそのまま流用する。
# 同じ関数を使うことで、出力スキーマと検算の厳しさが junior-soccer 版と完全に揃う。
from update_pref_cross_tables import (  # noqa: E402
    SEASON_YEAR, apply_source_ties, build_from_source, norm, set_source_standings,
)
import pdf_source  # noqa: E402  PDF出典の下ごしらえ（URLを辿る・取得・版日付・行/表の復元）

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "league_matches"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36")
}
TIMEOUT = 25
RETRIES = 3
SLEEP = 1.5      # 相手のサーバに優しく（1リクエストごとに待つ）

# ----------------------------------------------------------------------------
# 対象の県。**件数は増える。文章中の県数より、この表の実数が正**（2026-09-07時点で14県）。
#   goalnote … tid を差し替えるだけ
#   tecra    … 県ごとに独自ドメイン
# ⚠️ 鳥取は「1部リーグ前期」でtidが分かれている。後期が始まったらtidの追加が要る。
#    年度が変わったら全tidを新年度のものに差し替えること（年度切り替えチェックリスト参照）。
# ----------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 一時的な例外の台帳（2026-09-07新設）
# ---------------------------------------------------------------------------
# `known_bad_existing` や `REGRESSION_EXEMPT` のような**一時的な例外**を足したら、
# ここに「いつ・なぜ入れたか／いつ外すか」を書く。audit_pref_freshness.py が読んで
# ⚪️情報行に出すので、**例外が書いた本人の記憶の中だけに残る状態**を防げる。
#
# ⚠️ **例外がゼロなら「なし」と1行出るだけ。** 常に何か出ていると読み飛ばされるので、
#    役目を終えたものは必ず消すこと。
#
# 2026-09-07に見つけた5件の事故は、どれも**「例外や除外が見えなかった」**ことが原因だった
# （見張りが未実装／島根が完了扱いで対象外／paths 漏れ／導出が push で飛ぶ／
#   記録がコミットされない）。この台帳は6件目を作らないための仕掛け。
TEMP_EXCEPTIONS: dict[str, str] = {
    # "pref": "2026-09-07 追加：理由 → 外す条件",
    "niigata": ("2026-09-14 追加：一覧ページで「試合予定」のままの 7/18 の2試合を星取表PDFの結果で補完"
                "（PREF_OFFICIAL の hoshitori_results）→ 外す条件＝一覧ページに 07.18 の2件のスコアが"
                "入力されたら（期限ではなくイベント待ち。協会が2か月未入力のため2週間ルールの意図的な例外）"),
}


PREF_OFFICIAL = {
    "chiba":    {"platform": "goalnote", "tid": "18441", "label": "千葉県サッカー協会 公式（GoalNote）"},
    "aichi":    {"platform": "goalnote", "tid": "18269", "label": "愛知県サッカー協会 公式（GoalNote）"},
    "iwate":    {"platform": "goalnote", "tid": "18702", "label": "岩手県サッカー協会 公式（GoalNote）"},
    "nagasaki": {"platform": "goalnote", "tid": "18526", "label": "長崎県サッカー協会 公式（GoalNote）"},
    # 鳥取は前期(18541・8チーム1回戦総当たり・7/24完了)と後期(19293・上位4/下位4の
    # グループ分け・9/5開幕)が**別大会として登録**されている。試合は両方から集め、
    # 順位表は後期のもの（＝通年通算になっている）を使う。
    # 後期はグループ分けなので総当たり枠を作らない（round_robin: False）。
    "tottori":  {"platform": "goalnote", "tid": "19293", "extra_tids": ["18541"],
                 "standings_from": "19293", "round_robin": False,
                 "label": "鳥取県サッカー協会 公式（GoalNote）"},
    "kagawa":   {"platform": "goalnote", "tid": "18633", "label": "香川県サッカー協会 公式（GoalNote）"},
    "yamagata": {"platform": "goalnote", "tid": "18649", "label": "山形県サッカー協会 公式（GoalNote）"},
    "ibaraki":  {"platform": "goalnote", "tid": "18463", "label": "茨城県サッカー協会 公式（GoalNote）"},
    "shiga":    {"platform": "tecra", "host": "shiga-fa-u18.com", "label": "滋賀県サッカー協会 公式"},
    "fukuoka":  {"platform": "tecra", "host": "fukuoka-fa-u18.com", "label": "福岡県サッカー協会 公式"},
    "saga":     {"platform": "tecra", "host": "saga-fa-u18.com", "label": "佐賀県サッカー協会 公式"},

    # ここから下は県ごとの独自システム。共通プラットフォームではないので
    # パース仕様・検算ゲート・節番号の有無がそれぞれ違う（2026-09-07追加）。
    "gunma":     {"platform": "gunma", "tid": "173",
                  "source": "https://gunma-fa.com/post-694/",
                  "label": "群馬県サッカー協会 公式"},
    # 2026-09-07 追加の5県。ここも県ごとの独自システムで、共通化していない。
    "tokyo":     {"platform": "tokyo", "dt": "1", "ltno": "16",
                  "source": f"https://www.tleague-u18.com/schedule.php"
                            f"?dy={SEASON_YEAR}&dt=1&ltno=16",
                  "label": "東京都U-18サッカーリーグ 公式"},
    # ⚠️ 神奈川は610KBのページで504が頻発する。この県だけリトライを長くする
    #    （全県で増やすと他県の小さなサーバに無用な負荷がかかる）。
    "kanagawa":  {"platform": "kanagawa",
                  "base": f"https://www.kanagawa-fa.gr.jp/cms/u18-league/{SEASON_YEAR}/div1/",
                  "source": f"https://www.kanagawa-fa.gr.jp/cms/u18-league/{SEASON_YEAR}/div1/",
                  "label": "神奈川県サッカー協会 公式（2種大会部会）",
                  "retries": 6, "retry_wait": 5.0},
    "toyama":    {"platform": "toyama", "tid": "82",
                  "source": "https://www.taikai-go.com/tournaments/82/schedule",
                  "label": "富山県サッカー協会 公式（大会GO）"},
    "kumamoto":  {"platform": "kumamoto", "id": "1006",
                  "source": "https://kumamoto-fa.net/league/competition/gamelist/?id=1006",
                  "label": "熊本県サッカー協会 公式"},
    # 星取表が勝点・得点・失点・順位しか持たない（勝分敗が無い）ため専用ゲート。
    "okinawa":   {"platform": "okinawa", "tid": "161",
                  "source": "http://www.okinawa-soccer-habu.com/scores/table/161",
                  "label": "沖縄県サッカー協会 公式（波布リーグ）",
                  "standings_gate": "okinawa"},
                  # ✅ known_bad_existing は 2026-09-07 の移行完了後に削除済み。
                  #    junior-soccer が 2026-04-29「那覇西 vs 那覇」を 1-2（那覇の勝ち）と
                  #    していたが公式は 1-1（引分）で、これ1件で「那覇は試合が増えるのに
                  #    勝点が減る」が説明できた。移行で公式値に置き換わったため、
                  #    設定を残すと毎回「known_bad に書いた試合が見つからない」で
                  #    verify_failed になり、3日続けば赤①が鳴る。設計どおりの後始末。

    # 2026-09-07 追加の2県。どちらも**枠を作り直す**（double_round）。
    # 1回戦制の枠のまま止まっていたため、島根は「完了」と誤認されて見張りも黙っていた。
    "shimane":   {"platform": "sportsonline_table", "teams": 8,
                  "url": "https://www.sportsonline.jp/reportv2/PublisherFull/"
                         "viewdata.aspx?parentid=RX%5ER%5B&rallyid=U%5EYQ%5E",
                  "source": "https://www.sportsonline.jp/reportv2/PublisherFull/"
                            "viewdata.aspx?parentid=RX%5ER%5B&rallyid=U%5EYQ%5E",
                  "label": "島根県サッカー協会 公式（SportsOnline）",
                  "double_round": True},
    # 広島（2026-09-07追加）。島根と同じ SportsOnline の1ページ型で、
    # **島根のリーダを無改造で当てて動くことを実測で確認**したうえで共用にした。
    # 枠は90のまま（2回戦制で作られている）。ALIASは不要（10チームすべて表記が一致）。
    "hiroshima": {"platform": "sportsonline_table", "teams": 10,
                  "url": "https://www.sportsonline.jp/reportv2/PublisherFull/"
                         "viewdata.aspx?parentid=RX_ZZ&rallyid=U%5E%5BU%5E",
                  "source": "https://www.sportsonline.jp/reportv2/PublisherFull/"
                            "viewdata.aspx?parentid=RX_ZZ&rallyid=U%5E%5BU%5E",
                  "label": "広島県サッカー協会 公式（SportsOnline）"},
                  # ✅ known_bad_existing は 2026-09-07 の移行完了後に削除済み。
                  #    junior-soccer が**公式に存在しない試合**「サンフレセカンド 5-1
                  #    銀河学院」（日付が空）を登録していた。公式では両者は一度も対戦して
                  #    いない（全試合を突き合わせて確認）。
                  #    ⚠️ これは「スコアの誤り」「重複登録」とも違う**存在しない試合の登録**
                  #       という型。**日付が空の消化済み試合は、まずこれを疑う。**
                  #    移行で該当試合が既存JSONから消えたため、設定を残すと除外するものが
                  #    無いのに「見つからない」警告だけ出て県が verify_failed になる
                  #    （今日、沖縄・岡山でそれが起きて2県が据え置きになった）。
    "okayama":   {"platform": "okayama",
                  "entry": "http://okayama-fa.or.jp/2022/2-2",
                  "heading": "高円宮杯 JFA U-18 サッカーリーグ OKAYAMA",
                  "source": "http://okayama-fa.or.jp/2022/2-2",
                  "label": "岡山県サッカー協会 公式",
                  "double_round": True,
                  # 公式順位表が存在しないので、順位表は試合から自前計算して代替ゲートで守る
                  "standings_gate": "self"},
                  # ✅ known_bad_existing は 2026-09-07 の移行完了後に削除済み。
                  #    junior-soccer が 2026-04-12「創志学園 vs 倉敷古城池」を 1-0 と
                  #    していたが公式PDFは 0-1（勝敗が逆）。
                  #    ⚠️ この型（スコア反転）は検算では絶対に検出できない。両チームの勝点が
                  #       3ずつ入れ替わるだけで、リーグ全体の合計勝点が変わらないため。
                  #    移行で公式値に置き換わったため設定を削除（残すと毎回 verify_failed）。
    # 大分（2026-09-14追加）。前期・後期の対戦表PDFを合わせて90枠にする。
    # 星取表は勝点・得点・失点（前期／通算／後期）しか持たないので、沖縄と同じ代替ゲート。
    # ALIASは不要（10チームすべて表記が既存JSONと一致。2026-09-14実測）。
    "oita":      {"platform": "oita", "teams": 10,
                  "source": "https://www.ofa.or.jp/news/tournaments/high-school/",
                  "label": "大分県サッカー協会 公式",
                  "double_round": True,
                  "standings_gate": "okinawa"},
    # 新潟（2026-09-14追加）。試合一覧HTML＋星取表PDFの2ソース構成（read_niigata のコメント参照）。
    # 一覧に公式順位表は無く、星取表は第11節止まりなので、順位表は試合から自前計算して self ゲートで守る。
    "niigata":   {"platform": "niigata", "tid": "591", "teams": 8,
                  "source": "https://www.niigata-fa.or.jp/result/contest/tournament_id/591",
                  "label": "新潟県サッカー協会 公式",
                  "standings_gate": "self",
                  # 一覧ページで「試合予定」のままだが、星取表PDFに結果が載っている試合。
                  # 出典: https://www.niigata-fa.or.jp/news/public/detail?id=743
                  #       「N1星取表（第11節終了時点）」2026_result_U18_N1_11.pdf（2026-09-08更新）
                  "hoshitori_results": [
                      {"date": "2026-07-18", "home": "上越2nd", "away": "新潟工業", "hs": 7, "as": 0},
                      {"date": "2026-07-18", "home": "北越2nd", "away": "帝京長岡3rd", "hs": 3, "as": 4},
                  ]},

    # 秋田（2026-09-14追加）。日程PDF＋星取表PDF（read_akita のコメント参照）。
    # 星取表に勝・負・分・勝点・得点・失点が揃っているので、通常の検算ゲート（全項目一致）。
    # ALIASは不要（8チームすべて表記が既存JSONと一致。2026-09-14実測）。
    "akita":     {"platform": "akita", "teams": 8,
                  "entry": "https://fa-akita.net/16943/",
                  "source": "https://fa-akita.net/16943/",
                  "label": "秋田県サッカー協会 公式"},

    # 北海道（2026-09-18追加・47県目）。kawakitanet の北海道FAリーグ。
    # ⚠️⚠️ **`label` に「公式」と書かないこと。** ここは sourceName になって県ページの「出典」表示に出る。
    #    kawakitanet は北海道サッカー協会ではなく**個人運営の有志入力サイト**（read_hokkaido のコメント参照）。
    #    📌 埼玉で「sourceName に県協会と書いてリンク先は junior-soccer」という出典の誤表示を作った前例がある。
    # ⚠️ 順位表に得点・失点が無い（得失点差だけ）→ pts_gd ゲート。
    "hokkaido":  {"platform": "hokkaido", "teams": 8, "gameid": "9740",
                  "source": "https://www.kawakitanet.com/league_soccer/main.php?pref_cd=1&gameid=9740",
                  "label": "北海道FAリーグ 試合結果（kawakitanet・有志運営）",
                  "standings_gate": "pts_gd"},

    # 兵庫（2026-09-14追加）。日程･結果PDF（1部）＋戦績表PDF（read_hyogo のコメント参照）。
    # 戦績表は勝点・得失点差・順位だけ → 勝点＋得失点差で照合する "pts_gd" ゲート。
    "hyogo":     {"platform": "hyogo", "teams": 10, "first_no": 101,
                  "entry": "https://hyogo-fa.gr.jp/competition_info/13224/",
                  "source": "https://hyogo-fa.gr.jp/competition_info/13224/",
                  "label": "兵庫県サッカー協会 公式",
                  "standings_gate": "pts_gd"},

    # 徳島（2026-09-15追加）。日程・結果PDF 1本（read_tokushima のコメント参照）。
    # 公式順位表が無いので self ゲート＋読み取り側の前後半検算・No.連番・対戦の組のチェック。
    "tokushima": {"platform": "tokushima", "teams": 10,
                  "entry": "https://tokushima-fa.jp/post-414/",
                  "source": "https://tokushima-fa.jp/post-414/",
                  "label": "徳島県サッカー協会 公式",
                  "standings_gate": "self"},

    # 青森（2026-09-15追加）。大会日程PDF（前期・後期）＋星取表PDF（read_aomori のコメント参照）。
    # 星取表は勝点・得点・失点（＋得失点差）だけ → 沖縄と同じ代替ゲート。
    "aomori":    {"platform": "aomori", "teams": 9,
                  "source": "https://www.aomori-fa.jp/category/committee/all-committee/highschool/",
                  "label": "青森県サッカー協会 公式",
                  "standings_gate": "okinawa"},

    # 長野（2026-09-15追加）。日程及び試合結果PDF＋星取表PDF（read_nagano のコメント参照）。
    # 星取表が全項目そろっているので通常の検算ゲート。ALIASは不要（8チームとも既存JSONと同じ表記）。
    "nagano":    {"platform": "nagano", "teams": 8,
                  "entry": "https://www.nagano-fa.or.jp/cat_2",
                  "source": "https://www.nagano-fa.or.jp/cat_2",
                  "label": "長野県サッカー協会 公式"},

    # 福井（2026-09-15追加）。節ごとの試合結果PDF（F1第N節結果・13本前後）＋星取表PDF。
    # ⚠️ 2本（日程＋星取表）ではなく節ごとPDFを全部取る理由は read_fukui のコメント参照（延期で向きが静かに入れ替わるため）。
    # 星取表は勝点・得点・失点だけ → 沖縄と同じ代替ゲート。ALIASは不要（8チームとも既存JSONと同じ表記）。
    "fukui":     {"platform": "fukui", "teams": 8,
                  "source": "https://www.fukui-fa.com/author/high-school/",
                  "label": "福井県サッカー協会 公式",
                  "standings_gate": "okinawa"},
                  # ✅ known_bad_existing は 2026-09-15 の移行時だけ使い、設定には残していない。
                  #    junior-soccer が 5/10「福井商業 1-2 丸岡2nd」としていたが、公式は 丸岡2nd 2-0 福井商業
                  #    （星取表と第N節結果PDFの2つの公式資料で一致）。移行で既存JSONから消えたため、
                  #    残すと「見つからない」警告で毎回 verify_failed になる。

    # 山梨（2026-09-15追加）。星取表PDF＋通し日程PDF（read_yamanashi のコメント参照）。
    # 星取表は勝点・得点・失点・得失点差だけ → 沖縄と同じ代替ゲート。ALIASは不要（8チームとも既存JSONと同じ表記）。
    # ⚠️ home/away は「日程表の左側＝home」の格納規約で、**事実ではない**（56試合のマスを一意に埋めるための約束）。
    #    日程表の会場を数えると、左のチームの会場29・右のチームの会場17・どちらでもない10（2026-09-15）で、
    #    「左＝ホーム」とは言えない。表示は cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。「向きが逆だ」と直さないこと。
    "yamanashi": {"platform": "yamanashi", "teams": 8,
                  "entry": "https://www.yamanashi-football.com/pages/75/",
                  "source": "https://www.yamanashi-football.com/pages/75/",
                  "label": "山梨県サッカー協会 公式",
                  "hoshitori_names": {"東海甲府": "東海大甲府"},
                  "standings_gate": "okinawa"},
                  # ✅ known_bad_existing は 2026-09-15 の移行時だけ使い、設定には残していない。
                  #    junior-soccer が 6/28「韮崎 2-1 VF甲府B」を登録していたが、公式ではこの対戦は第4節の1回だけ
                  #    （4/25 韮崎 0-2 VF甲府B）。6/28 の実体は第6節 日大明誠 1-2 韮崎（対戦相手の取り違え）と見られる。

    # 岐阜（2026-09-15追加）。戦績表PDF＋日程表PDF（read_gifu のコメント参照）。
    # ⚠️ home/away は公式に無いので「1巡目＝番号の小さい側／2巡目＝大きい側」の格納規約。事実ではない。
    #    表示は cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。戦績表が全項目そろうので通常の検算ゲート。
    "gifu":      {"platform": "gifu", "teams": 10,
                  "source": "https://www.gifu-fa.com/type2-category/g1/",
                  "label": "岐阜県サッカー協会 公式",
                  "hoshitori_names": {"帝京大可児B": "帝京可児B", "FC岐阜U-18": "FC岐阜"}},

    # 三重（2026-09-15追加）。星取表PDF＋日程および組合せPDF（read_mie のコメント参照）。
    # 星取表は勝点・得失点差・総得点・総失点だけ → 沖縄と同じ代替ゲート（順位は星取表右の順位一覧から）。
    # ⚠️ home/away は「日程表の左側＝home」の格納規約で、**事実ではない**（56試合のマスを一意に埋めるための約束）。
    #    学校名の会場（海星・四中工）で行われる20試合は、左のチームの会場5・右のチームの会場4・どちらでもない11
    #    （2026-09-15）＝セントラル開催。表示は cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。「向きが逆だ」と直さないこと。
    "mie":       {"platform": "mie", "teams": 8,
                  "source": "https://www.fa-mie.jp/category2/",
                  "label": "三重県サッカー協会 公式",
                  "hoshitori_names": {"四日市中央工業": "四中工", "宇治山田商業": "宇治山田商"},
                  "standings_gate": "okinawa"},

    # 愛媛（2026-09-16追加）。E1日程PDF（1試合1行・結果入り＝主資料）＋E1星取表PDF（順位表だけ使う）。
    # 星取表に勝分敗がそろうので通常の検算ゲート（全項目一致）。ALIASは不要（日程PDFの表記＝既存JSONの表記）。
    # ⚠️ home/away は「日程PDFの左側＝home」の格納規約で、**事実ではない**。会場10種すべてが公共施設で
    #    学校名の会場が1つも無い（2026-09-15）＝完全なセントラル開催。表示は cross_table.NO_HOME_AWAY_SLUGS で
    #    H/A を出さない。「向きが逆だ」と直さないこと。
    "ehime":     {"platform": "ehime", "teams": 10,
                  "source": "https://efa.jp/meeting/second/?y=" + str(SEASON_YEAR),
                  "label": "愛媛県サッカー協会 公式",
                  "hoshitori_names": {"愛媛FCS": "愛媛FCU-18S", "FC今治NEXT": "FC今治U-18S"}},

    # 京都（2026-09-16追加）。TOPリーグ日程PDF（1試合1行・結果入り＝主資料）＋リザルトPDF（順位表だけ使う）。
    # 星取表に勝分敗がそろうので通常の検算ゲート（全項目一致）。
    # ⚠️ PDFはホットリンク防止で Referer が要る（read_kyoto のコメント参照）。
    # ⚠️ home/away は「日程表の左側＝home」の格納規約で、**事実ではない**。会場に学校のグラウンドが出るが、
    #    東山総合で東山が右・京都共栄Gで京都共栄が右・橘のスタジアムに橘が出ない試合がある（2026-09-16）＝
    #    左右も会場もホームを表していない。表示は cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。
    # 大阪（2026-09-17追加）。星取表CGI（ofa-tec.jp・Shift_JIS・httpのみ）＋1部試合日程表PDF。
    # 順位表に勝分敗が無いので沖縄と同じ代替ゲート。ALIASは不要（日程PDFの半角カナはNFKCでそろう）。
    # ⚠️ home/away は「日程表の左側＝home」の格納規約で、**事実ではない**。ホーム試合数は10チームともH9/A9・
    #    45ペアすべて左右が入れ替わるが、会場の持ち主は左15・右20・無関係28で**右のほうが多い**＝①③は根拠にならない実例。
    #    表示は cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。「向きが逆だ」と直さないこと。
    # ⚠️ 巡目は「マスの1件目＝前期」という**並び順の規約**に頼っている（出典に節も日付も無い）。read_osaka のコメント参照。
    "osaka":     {"platform": "osaka", "teams": 10,
                  "source": "https://osaka-fa.or.jp/2shu/game_information/",
                  "label": "大阪府サッカー協会 公式",
                  "standings_gate": "okinawa",
                  # ⚠️ マスの並び順に意味が無いので、増分（前回の保存内容＋新しく増えた分）で割り当てる。
                  "leg_assign": "incremental"},

    # 和歌山（2026-09-17追加）。「1部リーグ 試合結果」PDF1本に順位表・星取表・前期日程・後期日程が全部入っている。
    # 順位表に勝分敗が無いので沖縄と同じ代替ゲート。ALIASは不要（10チームとも既存JSONと同じ表記）。
    # ⚠️ home/away は「日程表の左側＝home」の格納規約で、**事実ではない**（ホーム試合数が近大和歌山10/4・桐蔭4/10、
    #    25ペア中7ペアが両巡とも同じ側、90試合中59が中立会場）。
    #    表示は cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。「向きが逆だ」と直さないこと。
    "wakayama":  {"platform": "wakayama", "teams": 10,
                  "source": "https://www.wfa.or.jp/pages/350/",
                  "label": "和歌山県サッカー協会 公式",
                  "standings_gate": "okinawa"},

    # 高知（2026-09-17追加）。星取表PDF（スコア・丸数字の節番号＝主資料）＋日程表PDF（日付の付与用）。
    # 星取表に勝分敗がそろうので通常の検算ゲート（高知小津の得点だけ KNOWN_SOURCE_ERRORS で差を明示）。
    # ⚠️ home/away は「日程表の左側＝home」の格納規約で、**事実ではない**。ホーム試合数は8チームとも7-7で
    #    28ペアすべて左右が入れ替わるが、機械的に総当たりを組めばそうなるだけで根拠にならない。
    #    会場は56試合中54が中立で、唯一の学校会場（明徳義塾高校）でも明徳義塾が左（第6節）と右（第13節）の両方に出る。
    #    表示は cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。「向きが逆だ」と直さないこと。
    "kochi":     {"platform": "kochi", "teams": 8,
                  "source": "https://www.kochi-fa.com/class02/class02sch/entry-305.html",
                  "label": "高知県サッカー協会 公式"},

    # 奈良（2026-09-17追加）。日程表PDF（1試合1行・結果入り＝主資料）＋1部リーグ星取表PDF（合計列だけ使う）。
    # 星取表に勝分敗が無く、失点も総得点−得失点で導くので沖縄と同じ代替ゲート。ALIASは不要（3か所とも同表記）。
    # ⚠️ home/away は「日程表の左側＝home」の格納規約で、**事実ではない**（左右はチーム番号順。奈良クラブユースは
    #    12試合すべて左・五條は12試合すべて右で、2試合あるペア14組は両巡目とも同じ側）。
    #    表示は cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。「向きが逆だ」と直さないこと。
    "nara":      {"platform": "nara", "teams": 10,
                  "source": "https://www.narafa.or.jp/pages/26/",
                  "label": "奈良県サッカー協会 公式",
                  "standings_gate": "okinawa"},

    # 福島（2026-09-16追加）。日程表PDF3本（節・日付・HOME/AWAY・会場）＋F1星取表PDF（スコア）＋F1順位表PDF。
    # 順位表に勝分敗がそろうので通常の検算ゲート。ALIASは不要（NFKCで半角カナが既存JSONの表記にそろう）。
    # ⚠️ home/away は「日程表のHOME列＝home」の格納規約で、**事実ではない**（ホーム試合数が均等でない・
    #    30ペアが両巡目とも同じ側・会場の持ち主はHOME側23/AWAY側13/どちらでもない54）。
    #    表示は cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。「向きが逆だ」と直さないこと。
    "fukushima": {"platform": "fukushima", "teams": 10,
                  "source": "https://fukushima-fa.com/match/c_match/ffa02/",
                  "label": "福島県サッカー協会 公式"},

    "kyoto":     {"platform": "kyoto", "teams": 10,
                  "source": "https://www.kyoto-fa.or.jp/archives.php?category=13",
                  "label": "京都府サッカー協会 公式",
                  "hoshitori_names": {"福知山成美A": "成美A", "京都サンガB": "サンガB"}},

    # 栃木（2026-09-07追加）。LSIN cloud は星取表(m=r)と日程(m=s)が別ビュー。
    # ⚠️ c= は都道府県IDではなく LSIN の契約団体ID。1〜320を総当たりして
    #    公開されているのは c=3（栃木）だけと確認済み。**他県への横展開はできない。**
    "tochigi":   {"platform": "lsin", "event": "1059", "club": "3", "teams": 10,
                  "unit_name": "高円宮杯U-18リーグ１部",
                  "source": "https://api.lsin.jp/?m=r&e=1059&c=3",
                  "label": "栃木県サッカー協会 公式（LSIN cloud）"},

    "miyazaki":  {"platform": "miyazaki",
                  "url": f"https://miyazaki-fa-u18.net/schedule/{SEASON_YEAR}/U-18-1.htm",
                  "source": f"https://miyazaki-fa-u18.net/schedule/{SEASON_YEAR}/U-18-1.htm",
                  "label": "宮崎県サッカー協会 公式（U-18リーグ）",
                  # 公式順位表が画像PDFなので、順位表との突き合わせができない。
                  # 代わりに self_check ゲート（process内）で守る。
                  "standings_gate": "self"},
    "yamaguchi": {"platform": "yamaguchi",
                  "url": ("https://www.sportsonline.jp/reportv2/PublisherFull/"
                          "viewdata.aspx?parentid=RX%5eS%5d&rallyid=U%5eZ%5b%5b"),
                  "source": "https://yamaguchi-fa.com/archives/16620",
                  "label": "山口県サッカー協会 公式（SportsOnline）",
                  # 出典に実日付が無い。既存JSONの同じ対戦から date を引き継ぐ。
                  "inherit_dates": True},
}

# ⭐️ 読み手が自分の県キーを参照できるようにする（増分での巡目割り当てが既存JSONを読むため・2026-09-17）。
for _pref_key, _cfg in PREF_OFFICIAL.items():
    _cfg.setdefault("pref", _pref_key)

# norm() で寄らない表記だけを手で書く。
# ⚠️ norm() が吸収するもの（セカンド→2nd、B→2nd、高校の除去 等）は**書かないこと**。
#    不要なエイリアスは将来の誤対応の種になる。
PREF_ALIAS = {
    # 2026-09-06に当時の9県ぶんを実測し、norm() で寄らなかった7件だけを登録した。
    # いずれも「既存で余っているチームが1つだけ」の状態で対応先が確定している。
    "aichi": {
        "名古屋グランパスB": "グランパスB",
        "日本福祉大学付属": "日福大付",
    },
    # 北海道（2026-09-18）。**空で1回走らせて `[要確認]` に出た2件だけ**を登録した。
    # ⚠️ 出典とサイトで表記が違うチームは8件中8件あるが、6件は norm() と teams.json の
    #    aliases（大谷室蘭2nd・札幌大谷2nd・東海大札幌・札幌創成・札幌第一 ほか）で寄る。
    #    先回りで8件全部書くと**二重管理になる**（norm() や aliases が改善されたとき片方が古くなる）。
    "hokkaido": {
        "VITA U-18": "旭実FC VITA",   # 文字列がほぼ重ならない（旭川実業高校サッカー部のクラブチーム）
        "旭川実2nd": "旭川実業高校2nd",
    },
    "iwate": {
        "G盛岡ユース": "グルージャ",      # グルージャ盛岡ユース
        "盛大附": "盛岡大附",             # 盛岡大学附属
    },
    "nagasaki": {
        "長崎総大附B": "長崎総附2nd",     # 長崎総合科学大学附属のセカンド
    },
    "kagawa": {
        "四国学院大学香川西高等学校": "香川西",
    },
    "fukuoka": {
        # norm() は「U-18 B」の空白のせいで末尾のBを2ndと解釈できない
        "アビスパ福岡U-18 B": "アビスパ福岡B",
    },
    # 群馬は10チームすべて公式表記＝既存JSONの表記なのでALIAS不要
    "miyazaki": {
        "宮崎日本大学": "宮崎日大",
        "テゲバジャーロ宮崎U-18": "テゲバジャーロ",
        "ヴェロスクロノス都農U-18": "ヴェロスクロノス",
    },
    # 東京は10チームすべて公式表記＝既存JSONの表記なのでALIAS不要
    "kanagawa": {
        # 公式は正式名称＋全角Ａ/Ｂ。既存JSONは略称＋半角A/B。
        # ⚠️ 「湘南工科大附Ａ」だけ既存JSONが全角Ａ。既存の表記を勝手に揃えない。
        "湘南ベルマーレU-18･Ａ": "湘南ベルマーレA",
        "東海大学付属相模高校Ａ": "東海大相模A",
        "桐光学園高校Ｂ": "桐光学園B",
        "横浜創英高校Ａ": "横浜創英A",
        "法政大学第二高校Ａ": "法政二A",
        "湘南工科大学附属高校Ａ": "湘南工科大附Ａ",
        "桐蔭学園高校Ｂ": "桐蔭学園B",
        "川崎市立橘高校Ａ": "川崎橘A",
        "日本大学藤沢高校Ｂ": "日大藤沢B",
        "相洋高校Ａ": "相洋A",
    },
    "toyama": {
        "富一2nd": "富山第一2nd",
    },
    "kumamoto": {
        # 試合表側の表記から寄せる（順位表の正式名称は名寄せに使わない）
        "熊本商業高校": "熊本商業",
    },
    "okinawa": {
        "沖縄SV Ｕ-18": "沖縄SV",
        "FC琉球OKINAWA U-18 2nd": "FC琉球OKINAWA 2nd",
    },
    # 島根は norm() が全角Ｂ→半角B を吸収するので ALIAS 不要（全単射を実測で確認）
    "okayama": {
        # PDFは略称。全角空白は読み取り側で除去済み。
        "学芸館B": "岡山学芸館B",
        "ファジB": "ファジ岡山U-18B",
        "光南B": "玉野光南B",
        "古城池": "倉敷古城池",
    },
    "tochigi": {
        # ⚠️ 「矢板中央Ｂ」は norm() が全角Ｂ→半角B を吸収するので**不要**
        #    （指示書には3件とあったが、実測すると2件で足りた）。
        "栃木SCU-18B": "栃木SC B",
        "栃木シティU-18": "栃木シティFC",
    },
    "aomori": {
        # 日程PDFは正式名、星取表は略称（どちらも空白除去・NFKC後の表記）。norm() で寄らないものだけ。
        "八戸工業大学第一高等学校": "八戸工大一",
        "八工大一": "八戸工大一",
        "八学野西": "八戸学院野辺地西",
        "八学光星": "八戸学院光星",
        "ヴァンラーレU-18": "ヴァンラーレ八戸U18",   # 星取表の半角カナ ｳﾞｧﾝﾗｰﾚU-18 を NFKC したもの
        "三農恵拓": "三本木農業恵拓",
    },
    "gifu": {
        # 日程表の表記（戦績表の表記は読み取り側で日程表の表記に読み替え済み）
        "岐阜工業": "岐阜工",
        "土岐商業": "土岐商",
    },
    "kyoto": {
        # 日程表の表記 → 既存JSONの表記（星取表の表記は読み取り側で日程表の表記に読み替え済み）。
        # ⚠️ この3つは既存名を部分文字列として含まないので、norm() でも部分一致でも寄らない。
        # ⚠️ A/B/C はチーム区分（A＝トップ・B＝2nd・C＝3rd）。全角Ａ/Ｂ/Ｃは読み取り側の NFKC で半角になっている。
        "成美A": "福知山成美A",
        "サンガB": "京都サンガU-18B",
        "立宇治A": "立命館宇治A",
    },
    "mie": {
        # 日程表の表記（星取表の表記は読み取り側で日程表の表記に読み替え済み）
        # ⚠️ fetch_pdf_scorers.py の MIE_ALIASES は逆向き（短→長）。流用しないこと。
        "四日市工業": "四日市工",
        "三重2nd": "三重②",
    },
    "hyogo": {
        # 日程･戦績表PDFは略称（チーム名の空白は読み取り側で除去済み）
        "報徳A": "報徳学園A",
        "三田B": "三田学園B",
        "蒼開": "蒼開A",
    },
    "niigata": {
        # 一覧ページの1件（No.30）だけ「JSC」が抜けている。
        # ※「開志学園JSC2nd」と既存の「開志学園JSC 2nd」は norm() が同一視するので不要。
        "開志学園2nd": "開志学園JSC 2nd",
    },
    "yamaguchi": {
        "小野田工": "小野田工業",
        "宇部工": "宇部工業",
    },
}

_SCORE_RE = re.compile(r"(\d+)\s*[-ー－―]\s*(\d+)")
_GN_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
_TECRA_DATE_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


# ============================================================
# 取得
# ============================================================
def fetch_html(url: str, encoding: str | None = None,
               retries: int = RETRIES, wait: float = SLEEP,
               timeout: int = TIMEOUT, must_contain: str = "") -> str:
    """HTMLを取得する。

    encoding      … その文字コードで読む。出典が Content-Type に charset を
                    書いていないとき必須（書かないと requests が ISO-8859-1 を
                    仮定し、**例外を出さずに静かに文字化けする**。宮崎・沖縄がこれ）
    retries/wait  … 県ごとに変える。神奈川は610KBのページで504が頻発するため
                    長めにする。**全県のリトライを増やすと他県の小さなサーバに
                    無用な負荷がかかる**ので、必要な県だけに効かせること
    must_contain  … デコード結果にこの文字列が無ければ失敗扱いにする。
                    文字化けを黙って通さないためのガード
    """
    last = None
    for _ in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = encoding or resp.apparent_encoding or "utf-8"
            text = resp.text
            if must_contain and must_contain not in text:
                raise RuntimeError(f"期待した文字列 {must_contain!r} が無い"
                                   f"（文字コードの取り違えの可能性）")
            return text
        except Exception as e:
            last = e
            time.sleep(wait)
    raise RuntimeError(f"{url} の取得に失敗 ({last})")


def fetch_json(url: str, retries: int = RETRIES, wait: float = SLEEP):
    """JSONを取得する。パースもリトライの中で行う
    （途中で切れたレスポンスを1回で諦めないため）。"""
    last = None
    for _ in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return json.loads(resp.text, strict=False)
        except Exception as e:
            last = e
            time.sleep(wait)
    raise RuntimeError(f"{url} の取得に失敗 ({last})")


def _rows(table) -> list[list[str]]:
    return [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            for tr in table.find_all("tr")]


def _to_int(v):
    s = unicodedata.normalize("NFKC", str(v)).strip().lstrip("+")
    return int(s) if re.fullmatch(r"-?\d+", s) else None


# ============================================================
# GoalNote
#   順位表: 1行目がヘッダ（先頭セルは大会名）。以降 [順位, チーム名, 勝点, 試合数,
#           勝利, 引分, 敗戦, 得点, 失点, 得失差]
#   日程  : 節ごとにテーブルが分かれる。試合行は
#           [番号, YYYY/MM/DD, HH:MM, ホーム, "1-2 [試合終了]", アウェイ, 会場, 詳細]
#           未消化の行は [試合終了] を持たない
# ============================================================
def read_goalnote_all(cfg: dict) -> tuple[dict, list[dict]]:
    """1県ぶんを読む。extra_tids があれば試合を合算する。

    鳥取のように**前期と後期が別大会として登録**されている県がある。
    その場合は試合を両方から集め、順位表は "standings_from" で指定した
    大会（後期＝通年通算）のものだけを使う。
    """
    main_tid = cfg["tid"]
    st_tid = cfg.get("standings_from", main_tid)
    standings, matches = {}, []
    for tid in [main_tid] + list(cfg.get("extra_tids") or []):
        st, ms = read_goalnote({"tid": tid})
        matches += ms
        if tid == st_tid:
            standings = st
    return standings, matches


def read_goalnote(cfg: dict) -> tuple[dict, list[dict]]:
    tid = cfg["tid"]
    soup = BeautifulSoup(
        fetch_html(f"https://www.goalnote.net/detail-standings.php?tid={tid}"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    for table in soup.find_all("table"):
        rows = _rows(table)
        if not rows:
            continue
        head = rows[0]
        if "勝点" not in "".join(head):
            continue
        col = {}
        for i, c in enumerate(head):
            for key, names in (("pts", ("勝点",)), ("played", ("試合数",)),
                               ("won", ("勝利", "勝数")), ("drawn", ("引分",)),
                               ("lost", ("敗戦", "敗数")), ("gf", ("得点",)),
                               ("ga", ("失点",))):
                if key not in col and any(n in c for n in names):
                    col[key] = i
        if len(col) < 7:
            continue
        # ⚠️ GoalNoteのヘッダ行は先頭セルが大会名で、本文の「順位」「チーム名」2列ぶんを
        #    1セルで占める。そのため本文はヘッダより1列多く、列位置が右へずれる。
        #    ずれ幅は行の長さの差から求める（決め打ちにしない）。
        body = [r for r in rows[1:] if len(r) > len(head)]
        offset = (len(body[0]) - len(head)) if body else 0
        for r in rows[1:]:
            if len(r) <= max(col.values()) + offset:
                continue
            team = r[1].strip() if offset else r[0].strip()
            vals = {k: _to_int(r[i + offset]) for k, i in col.items()}
            if team and all(v is not None for v in vals.values()):
                standings[team] = vals
        # ⚠️ ここで break しない。鳥取の後期リーグのように**グループA・Bで表が分かれる**
        #    大会があり、最初の表だけ読むと片方のグループしか取れない（実測で確認）。
        #    見つかった順位表をすべて合算して1つのロスターとして扱う。

    soup2 = BeautifulSoup(
        fetch_html(f"https://www.goalnote.net/detail-schedule.php?tid={tid}"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    for table in soup2.find_all("table"):
        for r in _rows(table):
            if len(r) < 6:
                continue
            joined = " ".join(r)
            if "試合終了" not in joined:
                continue      # 未消化の行はスコアが確定していないので取らない
            dm = _GN_DATE_RE.search(joined)
            if not dm:
                continue
            # スコアと前後のチーム名を位置で拾う
            si = next((i for i, c in enumerate(r) if "試合終了" in c), None)
            if si is None or si < 1 or si + 1 >= len(r):
                continue
            sm = _SCORE_RE.search(unicodedata.normalize("NFKC", r[si]))
            if not sm:
                continue
            home, away = r[si - 1].strip(), r[si + 1].strip()
            if not home or not away:
                continue
            # 会場はスコアの2つ右（[番号, 日付, 時刻, ホーム, スコア, アウェイ, **会場**, 詳細]）。
            # ⚠️ 大会ごとに列数が違うので必ず範囲を見る（順位表側で offset を実測しているのと同じ理由）。
            #    会場列が無い大会では次の列が「詳細」になるので、それは空に落とす。
            venue = r[si + 2].strip() if si + 2 < len(r) else ""
            if venue in ("詳細", "-", "−", "未定"):
                venue = ""
            matches.append(dict(
                date=f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}",
                home=home, hs=int(sm.group(1)), **{"as": int(sm.group(2))}, away=away,
                venue=venue))
    return standings, matches


# ============================================================
# tecra（{県}-fa-u18.com）
#   順位表: [順位, チーム名, 勝点, 試合数, 勝数, 引分(数), 敗数, 得点, 失点, 得失点差(, FPP)]
#           ※ 滋賀だけ末尾に FPP 列がある → 列名で位置を決める
#   試合  : [MM/DD（曜）, ホーム, "2 - 3 試合終了", アウェイ, 会場]
#           年が入っていないので SEASON_YEAR から補う（1月は翌年＝県リーグは年をまたぐ）
# ============================================================
def read_tecra(cfg: dict) -> tuple[dict, list[dict]]:
    host = cfg["host"]
    soup = BeautifulSoup(
        fetch_html(f"https://{host}/order/1/{SEASON_YEAR}/all"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    for table in soup.find_all("table"):
        rows = _rows(table)
        if not rows or "勝点" not in "".join(rows[0]):
            continue
        head = rows[0]
        col = {}
        for i, c in enumerate(head):
            for key, names in (("pts", ("勝点",)), ("played", ("試合数",)),
                               ("won", ("勝数", "勝利")), ("drawn", ("引分",)),
                               ("lost", ("敗数", "敗戦")), ("gf", ("得点",)),
                               ("ga", ("失点",))):
                if key not in col and any(n in c for n in names):
                    col[key] = i
        if len(col) < 7:
            continue
        for r in rows[1:]:
            if len(r) <= max(col.values()):
                continue
            team = r[1].strip()
            vals = {k: _to_int(r[i]) for k, i in col.items()}
            if team and all(v is not None for v in vals.values()):
                standings[team] = vals
        if standings:
            break

    soup2 = BeautifulSoup(
        fetch_html(f"https://{host}/match/1/{SEASON_YEAR}/all"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    for table in soup2.find_all("table"):
        for r in _rows(table):
            if len(r) < 4 or "試合終了" not in " ".join(r):
                continue
            si = next((i for i, c in enumerate(r) if "試合終了" in c), None)
            if si is None or si < 1 or si + 1 >= len(r):
                continue
            sm = _SCORE_RE.search(unicodedata.normalize("NFKC", r[si]))
            if not sm:
                continue
            dm = _TECRA_DATE_RE.search(unicodedata.normalize("NFKC", r[0]))
            if not dm:
                continue
            mo, da = int(dm.group(1)), int(dm.group(2))
            # 既存 update_pref_cross_tables.py と同じ規則。県リーグは年をまたぐので、
            # 1月の試合だけ翌年になる（2月以降＝今シーズンの年）。
            yr = SEASON_YEAR if mo >= 2 else SEASON_YEAR + 1
            home, away = r[si - 1].strip(), r[si + 1].strip()
            if not home or not away:
                continue
            # 会場はスコアの2つ右（[MM/DD（曜）, ホーム, スコア, アウェイ, **会場**]）。
            # ⚠️ 範囲を必ず見る（大会によって列が足りないことがある）。
            # ⚠️ **保存は出典の表記のまま**。滋賀の「綾⽻」は羽が異体字（U+2F7B 康熙部首）で
            #    チーム名の「綾羽」（U+7FBD）と文字が違うが、ここで書き換えると出典と違うものを持つことになる。
            #    突き合わせる側が unicodedata.normalize("NFKC", s) で正規化すること。
            venue = r[si + 2].strip() if si + 2 < len(r) else ""
            matches.append(dict(date=f"{yr}-{mo:02d}-{da:02d}", home=home,
                                hs=int(sm.group(1)), **{"as": int(sm.group(2))},
                                away=away, venue=venue))
    return standings, matches


# ============================================================
# 群馬（management.gunma-fa.com）— 県協会の独自リーグ管理システム
#   順位表 /api/table/{tid} … <h2>1部リーグ</h2> のセクションの2つ目のtable
#                             列: 順位|チーム名|勝点|試合数|勝数|引分数|敗数|得点|失点|得失点差
#   試合   /api/match/{tid} … 同セクションのtable（91行＝ヘッダ1＋全90試合）
#                             1行6セル: 節|キックオフ|HOME|スコア/状況|AWAY|会場
# ⚠️ スコアは必ず `.point .pt` の1つ目と2つ目を取る。セルのテキスト全体から数字を拾うと
#    前後半スコア（"0 0-2 0-1 3"）を巻き込んで壊れる。
# ⚠️ セクションは id で決め打ちしない。h2 のテキストが厳密に「1部リーグ」の要素から辿る。
# ⚠️ 1〜3部が1ページに入っているので、必ず1部だけ抜き出してから処理する。
# 年度切り替え: https://gunma-fa.com/post-694/ から新年度の大会IDを取る（2026=173）
# ============================================================
_GUNMA_MD_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


def _gunma_section(html: str, heading: str = "1部リーグ"):
    """h2 が厳密に heading のセクション（tableを含む親）を返す"""
    soup = BeautifulSoup(html, "html.parser")
    for h2 in soup.find_all("h2"):
        if h2.get_text(strip=True) != heading:
            continue
        sec = h2.find_parent(["section", "div"])
        while sec is not None and not sec.find_all("table"):
            sec = sec.find_parent(["section", "div"])
        if sec is not None:
            return sec
    return None


def read_gunma(cfg: dict) -> tuple[dict, list[dict]]:
    tid = cfg["tid"]
    base = "https://management.gunma-fa.com/api"

    # --- 順位表 ---
    sec = _gunma_section(fetch_html(f"{base}/table/{tid}"))
    time.sleep(SLEEP)
    standings = {}
    if sec is not None:
        tables = sec.find_all("table")
        # 1つ目は星取表、2つ目が順位表
        for table in tables[1:]:
            rows = _rows(table)
            if not rows or "勝点" not in "".join(rows[0]):
                continue
            col = {}
            for i, c in enumerate(rows[0]):
                for key, names in (("pts", ("勝点",)), ("played", ("試合数",)),
                                   ("won", ("勝数",)), ("drawn", ("引分",)),
                                   ("lost", ("敗数",)), ("gf", ("得点",)),
                                   ("ga", ("失点",))):
                    if key not in col and any(n in c for n in names):
                        col[key] = i
            if len(col) < 7:
                continue
            for r in rows[1:]:
                if len(r) <= max(col.values()):
                    continue
                team = r[1].strip()
                vals = {k: _to_int(r[i]) for k, i in col.items()}
                if team and all(v is not None for v in vals.values()):
                    standings[team] = vals
            if standings:
                break
        m = re.search(r"最終更新日[:：]\s*([\d\-]+\s[\d:]+)",
                      sec.get_text(" ", strip=True))
        if m:
            print(f"       （群馬 出典の最終更新日: {m.group(1)}）")

    # --- 試合 ---
    sec2 = _gunma_section(fetch_html(f"{base}/match/{tid}"))
    time.sleep(SLEEP)
    matches = []
    if sec2 is not None:
        for tr in sec2.find_all("table")[0].find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) < 6:
                continue
            status = cells[3].get_text(" ", strip=True)
            if "試合終了" not in status:
                continue          # 未消化。枠は generate_fixtures 側が作る
            pts = cells[3].select(".point .pt")
            if len(pts) < 2:
                continue
            hs, as_ = _to_int(pts[0].get_text(strip=True)), _to_int(pts[1].get_text(strip=True))
            if hs is None or as_ is None:
                continue
            home = cells[2].get_text(" ", strip=True)
            away = cells[4].get_text(" ", strip=True)
            if not home or not away:
                continue
            dm = _GUNMA_MD_RE.search(cells[1].get_text(" ", strip=True))
            date = ""
            if dm:
                mo, da = int(dm.group(1)), int(dm.group(2))
                # 大会期間は 2026-03-07〜2026-12-05。年をまたがないので SEASON_YEAR 固定。
                date = f"{SEASON_YEAR}-{mo:02d}-{da:02d}"
            matches.append(dict(date=date, home=home, hs=hs,
                                **{"as": as_}, away=away))
    return standings, matches


# ============================================================
# 宮崎（miyazaki-fa-u18.net）— 県協会のU-18リーグ専用サイト
#   /schedule/{年}/U-18-1.htm の3つ目のtable（93行）。先頭3行は見出し。
#   9セル … 節|期日|会場|KickOff|HOME|HOME得点|－|AWAY得点|AWAY
#   8セル … 節が省略（セル結合）。直前の節を引き継ぐ
# ⚠️ 指示書には Shift_JIS とあるが、実物は UTF-8（HTML内の宣言も charset=UTF-8）。
#    shift_jis を明示するとデコードに失敗する（2026-09-07 実測）。
# ⚠️ 全角数字が混在するので NFKC で正規化してから数値化する。
# ⚠️ 公式の順位表は画像PDFで機械可読でないため、順位表は取得せず自前計算する
#    （検算は別ゲート。process() 側を参照）
# 年度切り替え: URLの年を差し替える
# ============================================================
_MIYAZAKI_DATE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")
_MIYAZAKI_MD_RE = re.compile(r"第(\d+)節")


def read_miyazaki(cfg: dict) -> tuple[dict, list[dict]]:
    html = fetch_html(cfg["url"], encoding="utf-8")
    time.sleep(SLEEP)
    tables = BeautifulSoup(html, "html.parser").find_all("table")
    if len(tables) < 3:
        return {}, []
    matches = []
    md = 0
    for r in _rows(tables[2]):
        z = [unicodedata.normalize("NFKC", c) for c in r]
        if len(z) == 9:
            mm = _MIYAZAKI_MD_RE.search(z[0])
            if mm:
                md = int(mm.group(1))
            z = z[1:]              # 以降は8セルと同じ並びにそろえる
        if len(z) != 8:
            continue
        date_raw, venue, _ko, home, hs, _dash, as_, away = z
        home, away = home.strip(), away.strip()
        if not home or not away:
            continue
        # 得点が空＝未消化。宮崎は出典が第18節まで節番号を持っているので、
        # 未消化の行も hs/as を None のまま返して**節番号だけ**を活かす。
        # ⚠️ 未消化行を検算に流すと壊れる（build_from_source は渡された試合を
        #    全部「消化済み」として順位を再計算するため）。呼び出し側で
        #    「消化ぶんだけ検算に渡す → 枠が組み上がってから節番号を入れる」順序にしている。
        # 参考: 同じ節に消化と未消化が混在することがある。
        #   第12節 … 延期2件が未消化のまま残っている
        #   第14節 … 8/30に1試合だけ前倒し実施、残り4試合は9/19（延期ではない）
        hs, as_ = _to_int(hs), _to_int(as_)
        dm = _MIYAZAKI_DATE_RE.search(date_raw)
        # 1部は4/4〜11/29で年をまたがない。
        # 日付が読めない行（`月日（）＋延期` の第12節2件）は空のまま。
        date = (f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
                if dm else "")
        matches.append(dict(date=date, home=home, hs=hs,
                            **{"as": as_}, away=away, md=md,
                            venue=venue.strip()))
    return {}, matches            # 順位表は公式に機械可読なものが無い


# ============================================================
# 山口（sportsonline.jp）— 県協会が公式に案内する速報システム
#   viewdata.aspx 1ページに 星取表＋順位表 と 全試合一覧 が入っている（GET1本）
# ⚠️ 順位表のHTMLが不正で、2行目以降の <tr> が欠落している（td が1つの tr に
#    ぶら下がる）。行では読めないので、**ヘッダの列数で区切って行を復元**する
#    （2026-09-07 実測。td 153個 ÷ 17列 = 9行）。
# ⚠️ 全試合の 開始日 が `2026/04/04` のダミー、開始時刻は空、会場は「県内各地」。
#    出典に実日付が存在しないので **date は空で入れ、既存JSONの同じ対戦から引き継ぐ**
#    （process() 側で処理）。ダミー日付は絶対に採用しない。
#    → 山口の lastUpdated は「出典を確認した日」であって試合日ではない。
# 年度切り替え: SportsOnline の子大会一覧から新しい rallyid を取る
# ============================================================
_YAMAGUCHI_SCORE_RE = re.compile(r"^(.+?)\s+(\d+)\s*[-ー－―]\s*(\d+)\s+(.+?)$")


def read_yamaguchi(cfg: dict) -> tuple[dict, list[dict]]:
    soup = BeautifulSoup(fetch_html(cfg["url"]), "html.parser")
    time.sleep(SLEEP)
    tables = soup.find_all("table")

    # --- 順位表（壊れたHTMLを列数で復元する） ---
    standings = {}
    for table in tables:
        cells = [c.get_text(" ", strip=True) for c in table.find_all("td")]
        if not cells or "勝点" not in "".join(cells[:40]):
            continue
        # ヘッダは「順位 … 勝数 負数 引分 勝点 得点 失点 得失差」で終わる。
        # 「得失差」までをヘッダ幅とみなす（列数を決め打ちしない）。
        try:
            width = cells.index("得失差") + 1
        except ValueError:
            continue
        head = cells[:width]
        col = {}
        for i, c in enumerate(head):
            for key, names in (("pts", ("勝点",)), ("won", ("勝数",)),
                               ("drawn", ("引分",)), ("lost", ("負数",)),
                               ("gf", ("得点",)), ("ga", ("失点",))):
                if key not in col and c == names[0]:
                    col[key] = i
        if len(col) < 6:
            continue
        for i in range(width, len(cells) - width + 1, width):
            row = cells[i:i + width]
            if len(row) < width:
                break
            team = row[1].strip()
            vals = {k: _to_int(row[j]) for k, j in col.items()}
            if team and all(v is not None for v in vals.values()):
                vals["played"] = vals["won"] + vals["drawn"] + vals["lost"]
                standings[team] = vals
        if standings:
            break

    # --- 全試合一覧 ---
    matches = []
    for table in tables:
        rows = _rows(table)
        if not rows or "組み合わせ" not in "".join(rows[0]):
            continue
        for r in rows[1:]:
            if len(r) < 4:
                continue          # 「Away」の区切り行など
            if "試合終了" not in r[3]:
                continue
            m = _YAMAGUCHI_SCORE_RE.match(unicodedata.normalize("NFKC", r[0]).strip())
            if not m:
                continue
            # date は入れない（出典のダミー日付は採用しない）
            matches.append(dict(date="", home=m.group(1).strip(),
                                hs=int(m.group(2)), **{"as": int(m.group(3))},
                                away=m.group(4).strip()))
        if matches:
            break
    return standings, matches


# ============================================================
# 名寄せ（公式表記 → 既存JSONのチーム名）
# ============================================================
# ============================================================
# 東京（tleague-u18.com）— 東京都U-18サッカーリーグ公式
#   順位表 rank.php / 試合 schedule.php。どちらも素のHTML・UTF-8・table 1つ。
# ⚠️ **順位表の列は「勝・敗・引」の順**。他県によくある「勝・分・敗」ではない。
#    ここを取り違えると勝点は合うのに勝分敗だけズレる（検算をすり抜けない＝気づける）。
# ⚠️ 1行目は「<<スワイプでご覧いただけます>>」の注記。2行目がヘッダ。
#    列名で引くので、注記行が増減しても壊れない。
# 年度切り替え: URLの dy を差し替える
# ============================================================
_TOKYO_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
_TOKYO_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _tokyo_cols(header: list[str]) -> dict:
    """ヘッダ行から列の位置を決める。「引」と「勝」の取り違えを防ぐため完全一致で引く。"""
    want = {"team": ("チーム名",), "pts": ("勝点",), "played": ("試合数",),
            "won": ("勝",), "lost": ("敗",), "drawn": ("引",),
            "gf": ("得点",), "ga": ("失点",)}
    col = {}
    for i, c in enumerate(header):
        t = c.strip()
        for key, names in want.items():
            if key not in col and t in names:
                col[key] = i
    return col


def read_tokyo(cfg: dict) -> tuple[dict, list[dict]]:
    base = "https://tleague-u18.com"
    q = f"dy={SEASON_YEAR}&dt={cfg['dt']}&ltno={cfg['ltno']}"

    # --- 順位表 ---
    soup = BeautifulSoup(fetch_html(f"{base}/rank.php?{q}"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    for table in soup.find_all("table"):
        rows = _rows(table)
        head = next((r for r in rows if "勝点" in r and "チーム名" in r), None)
        if not head:
            continue
        col = _tokyo_cols(head)
        if len(col) < 8:
            continue
        for r in rows[rows.index(head) + 1:]:
            if len(r) <= max(col.values()):
                continue
            team = r[col["team"]].strip()
            vals = {k: _to_int(r[i]) for k, i in col.items() if k != "team"}
            if team and all(v is not None for v in vals.values()):
                standings[team] = vals
        if standings:
            break

    # --- 試合 ---
    soup2 = BeautifulSoup(fetch_html(f"{base}/schedule.php?{q}"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    for table in soup2.find_all("table"):
        rows = _rows(table)
        head = next((r for r in rows if "ホームチーム" in r), None)
        if not head:
            continue
        idx = {name: head.index(name) for name in
               ("節", "日時", "ホームチーム", "スコア", "アウェイチーム", "会場")
               if name in head}
        if len(idx) < 5:
            continue
        for r in rows[rows.index(head) + 1:]:
            if len(r) <= max(idx.values()):
                continue
            home = r[idx["ホームチーム"]].strip()
            away = r[idx["アウェイチーム"]].strip()
            if not home or not away:
                continue
            sc = r[idx["スコア"]].strip()
            m = re.match(r"^(\d+)\s*-\s*(\d+)$", sc)
            # 未消化はスコア欄が空。枠は generate_fixtures 側が作る。
            if not m:
                continue
            raw = r[idx["日時"]]
            # 日時未定は「--/-- :」。年は無いので SEASON_YEAR を補う。
            dm = _TOKYO_DATE_RE.search(raw)
            date = f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}" if dm else ""
            tm = _TOKYO_TIME_RE.search(raw)
            matches.append(dict(
                date=date, home=home, hs=int(m.group(1)),
                **{"as": int(m.group(2))}, away=away,
                md=_to_int(r[idx["節"]]) or 0,
                kickoff=f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "",
                venue=r[idx["会場"]].strip() if "会場" in idx else "",
            ))
        if matches:
            break
    return standings, matches


# ============================================================
# 富山（taikai-go.com「大会GO」）— 順位表と試合がJSONで取れる
#   /api/tournaments/{id}/standings … data[0].teams[] に順位表
#   /api/tournaments/{id}/results   … data[0].teams[]（id→名前）と matches[]
#   /tournaments/{id}/schedule      … 日付・時刻・会場はこのHTMLにしかない
# ⚠️ /api/tournaments/{id}/matches は 401（要認証）。使うのは results のほう。
# ⚠️ results の試合に日付が無いので、match_code（M1, M3…）をキーに schedule と join する。
# ⚠️ schedule のHTMLはレスポンシブ対応でテキストが二重に出る。textContent を
#    そのまま使わず要素単位で取ること。
# 年度切り替え: /api/tournaments/public-groups/7 で新年度のT1のIDを取る
# ============================================================
_TOYAMA_CODE_RE = re.compile(r"\bM\d+\b")
_TOYAMA_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")


def _toyama_schedule(tid: str) -> dict:
    """/schedule のHTMLから {match_code: (日付, 時刻)} を作る。
    ⚠️ 会場は取っていない（説明文が「会場」まで含んでいたが、実装は日付と時刻の2つだけ。
       2026-09-17に説明文のほうを実物に合わせた）。

    行の中に M番号 と 日付が両方あるものだけを拾う。二重テキスト対策として、
    同じ match_code が複数回出てきたら最初の1件だけを採用する。
    """
    soup = BeautifulSoup(fetch_html(f"https://www.taikai-go.com/tournaments/{tid}/schedule"),
                         "html.parser")
    time.sleep(SLEEP)
    out = {}
    cur_date = ""
    for el in soup.find_all(["tr", "li", "div", "section", "article"]):
        # 子要素を持たない末端に近いものだけ見る（親を見ると全文が入る）
        txt = el.get_text(" ", strip=True)
        if len(txt) > 200:
            continue
        dm = _TOYAMA_DATE_RE.search(txt)
        if dm and not _TOYAMA_CODE_RE.search(txt):
            cur_date = f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
            continue
        cm = _TOYAMA_CODE_RE.search(txt)
        if not cm:
            continue
        code = cm.group(0)
        if code in out:
            continue
        date = cur_date
        if dm:
            date = f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
        tm = re.search(r"(\d{1,2}):(\d{2})", txt)
        out[code] = (date, f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "")
    return out


def read_toyama(cfg: dict) -> tuple[dict, list[dict]]:
    tid = cfg["tid"]
    api = "https://www.taikai-go.com/api/tournaments"

    st = fetch_json(f"{api}/{tid}/standings")
    time.sleep(SLEEP)
    standings = {}
    for blk in (st.get("data") or []):
        for t in (blk.get("teams") or []):
            name = (t.get("team_name") or "").strip()
            if not name:
                continue
            standings[name] = dict(
                pts=t.get("points"), played=t.get("matches_played"),
                won=t.get("wins"), drawn=t.get("draws"), lost=t.get("losses"),
                gf=t.get("goals_for"), ga=t.get("goals_against"))

    res = fetch_json(f"{api}/{tid}/results")
    time.sleep(SLEEP)
    sched = _toyama_schedule(tid)
    matches = []
    for blk in (res.get("data") or []):
        id2name = {t.get("team_id"): (t.get("team_name") or "").strip()
                   for t in (blk.get("teams") or [])}
        for m in (blk.get("matches") or []):
            # completed だけを消化として扱う。scheduled の枠は generate_fixtures が作る。
            if m.get("match_status") != "completed":
                continue
            home = id2name.get(m.get("team1_id"), "")
            away = id2name.get(m.get("team2_id"), "")
            hs, as_ = m.get("team1_goals"), m.get("team2_goals")
            if not home or not away or hs is None or as_ is None:
                continue
            date, kick = sched.get(m.get("match_code") or "", ("", ""))
            matches.append(dict(date=date, home=home, hs=int(hs),
                                **{"as": int(as_)}, away=away, kickoff=kick))
    return standings, matches


# ============================================================
# 熊本（kumamoto-fa.net）— 県協会のリーグシステム。得点者まで公開している
#   試合 gamelist/?id= … table 1つ・182行＝ヘッダ2＋90試合×2行
#     ホーム行(12セル): 編集|節|対戦日時|試合会場|チーム|前半|後半|合計|得点者|アシスト|警告|退場
#     アウェイ行(8セル): チーム|前半|後半|合計|得点者|アシスト|警告|退場
#     → ホーム得点＝ホーム行[7]（合計）／アウェイ得点＝アウェイ行[3]（合計）
#   順位表 ranking/?id= … 順位|チーム名|試合|勝点|勝|分|敗|得点|失点|得失
# ⚠️ **順位表と試合表でチーム名の表記が違う**（順位表＝熊本県立熊本商業高等学校 /
#    試合表＝熊本商業高校）。JSONに入れるのは試合表側の略称にし、
#    順位表とは**順位の並び**で対応づける（process の standings は試合表の名前で作る）。
# 年度切り替え: kumamoto-fa.net/league/ の一覧から新年度の1部の id を取る
# ============================================================
_KUMAMOTO_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
_KUMAMOTO_MD_RE = re.compile(r"第\s*(\d+)\s*節")


def read_kumamoto(cfg: dict) -> tuple[dict, list[dict]]:
    tid = cfg["id"]
    base = "https://kumamoto-fa.net/league/competition"

    # --- 試合（こちらが名前の正本） ---
    soup = BeautifulSoup(fetch_html(f"{base}/gamelist/?id={tid}"), "html.parser")
    time.sleep(SLEEP)
    table = max(soup.find_all("table"), key=lambda t: len(t.find_all("tr")), default=None)
    matches, order = [], []
    if table is not None:
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        i = 0
        while i < len(rows) - 1:
            h, a = rows[i], rows[i + 1]
            if len(h) != 12 or len(a) != 8:
                i += 1
                continue
            home, away = h[4].strip(), a[0].strip()
            for n in (home, away):
                if n and n not in order:
                    order.append(n)
            hs, as_ = _to_int(h[7]), _to_int(a[3])       # 「合計」列。未消化は "-"
            if home and away and hs is not None and as_ is not None:
                dm = _KUMAMOTO_DATE_RE.search(h[2])
                tm = re.search(r"(\d{1,2}):(\d{2})", h[2])
                mm = _KUMAMOTO_MD_RE.search(h[1])
                matches.append(dict(
                    date=(f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
                          if dm else ""),
                    home=home, hs=hs, **{"as": as_}, away=away,
                    md=int(mm.group(1)) if mm else 0,
                    kickoff=f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "",
                    venue=h[3].strip()))
            i += 2

    # --- 順位表（正式名称。順位の並びで試合表の名前に対応づける） ---
    soup2 = BeautifulSoup(fetch_html(f"{base}/ranking/?id={tid}"), "html.parser")
    time.sleep(SLEEP)
    ranked = []
    for table in soup2.find_all("table"):
        rows = _rows(table)
        head = next((r for r in rows if "勝点" in r and "順位" in r), None)
        if not head:
            continue
        col = {}
        for i, c in enumerate(head):
            for key, names in (("pts", ("勝点",)), ("played", ("試合",)),
                               ("won", ("勝",)), ("drawn", ("分",)), ("lost", ("敗",)),
                               ("gf", ("得点",)), ("ga", ("失点",))):
                if key not in col and c.strip() in names:
                    col[key] = i
        if len(col) < 7:
            continue
        for r in rows[rows.index(head) + 1:]:
            if len(r) <= max(col.values()):
                continue
            rank = _to_int(r[0])
            vals = {k: _to_int(r[i]) for k, i in col.items()}
            if rank is not None and all(v is not None for v in vals.values()):
                ranked.append((rank, vals))
        if ranked:
            break
    ranked.sort(key=lambda x: x[0])

    # 公式順位表（正式名称）を、試合表の名前（略称）に載せ替える。
    # ⚠️ 「順位の並びで対応づける」方式は、公式と当方で同着の並べ方が違うと
    #    静かにズレる。ここでは**成績(勝点・試合数・得失点)の完全一致**で
    #    対応づけ、1対1にならなければ空を返して据え置きにする（fail closed）。
    standings = {}
    if ranked and order:
        mine = standings_from_matches(matches, order)
        used = set()
        for _, vals in ranked:
            hit = [t for t in order
                   if t not in used
                   and mine[t]["pts"] == vals["pts"]
                   and mine[t]["played"] == vals["played"]
                   and mine[t]["gf"] == vals["gf"]
                   and mine[t]["ga"] == vals["ga"]]
            if len(hit) != 1:
                print(f"       [要確認] 熊本: 公式順位表の行 {vals} に対応する"
                      f"チームが{len(hit)}件（1件でない）。据え置きます。")
                return {}, matches
            standings[hit[0]] = vals
            used.add(hit[0])
    return standings, matches


# ============================================================
# 神奈川（kanagawa-fa.gr.jp）— 県協会2種大会部会。WordPress + AnWP Football Leagues
#   試合 /div1/       … **<table> ではない**。div.anwp-fl-game が90個
#   順位表 /div1/group-1/ … これも div。.standing-table の直下に
#                          ヘッダ10個 → 各チーム10個 が平らに並ぶ
# ⚠️ **610KBのページで504が頻発する**（実測：初回504・2回目200）。
#    この県だけリトライ回数と待ち時間を長くしている。
# ⚠️ 日付は **data-fl-game-kickoff（ISO8601・JST付き）が正本**。
#    画面の日本語表記をパースしないこと。
# ⚠️ 順位表のデータセルは意味クラス（standing-table__won 等）を持っているが、
#    **ヘッダの並びから列の意味を決めて位置で拾う**ようにしている。
#    プラグインの版が変わってクラスが落ちても壊れないため。
# 年度切り替え: パスの 2026 を差し替える
# ============================================================
_KANAGAWA_HEAD = {"勝点": "pts", "試合": "played", "勝": "won", "分": "drawn",
                  "敗": "lost", "得": "gf", "失": "ga", "差": "gd"}


def read_kanagawa(cfg: dict) -> tuple[dict, list[dict]]:
    base = cfg["base"]
    rt, wt = cfg.get("retries", RETRIES), cfg.get("retry_wait", SLEEP)

    # --- 順位表 ---
    soup = BeautifulSoup(fetch_html(f"{base}group-1/", retries=rt, wait=wt,
                                    timeout=90, must_contain="Club"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    tbl = soup.select_one(".standing-table")
    if tbl is not None:
        cells = [c for c in tbl.find_all(recursive=False)]
        texts = [c.get_text(" ", strip=True) for c in cells]
        # ヘッダは「# Club 勝点 試合 …」。Club の次から数値列が始まる。
        try:
            club_i = texts.index("Club")
        except ValueError:
            club_i = -1
        if club_i >= 0:
            order = []                      # 数値列の意味を左から並べる
            j = club_i + 1
            while j < len(texts) and texts[j] in _KANAGAWA_HEAD:
                order.append(_KANAGAWA_HEAD[texts[j]])
                j += 1
            width = 2 + len(order)          # 順位 + チーム名 + 数値列
            for k in range(j, len(cells) - width + 1, width):
                row = cells[k:k + width]
                # チーム名セルには直近5試合の ○●△ が混ざるので a 要素から取る
                link = row[1].find("a")
                name = (link.get_text(" ", strip=True) if link
                        else row[1].get_text(" ", strip=True)).strip()
                vals = {}
                for n, key in enumerate(order):
                    vals[key] = _to_int(row[2 + n].get_text(" ", strip=True))
                vals.pop("gd", None)        # 得失差は得点-失点から出るので持たない
                if name and all(v is not None for v in vals.values()):
                    standings[name] = vals

    # --- 試合 ---
    soup2 = BeautifulSoup(fetch_html(base, retries=rt, wait=wt, timeout=90,
                                     must_contain="anwp-fl-game"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    md = 0
    for el in soup2.find_all(True):
        cls = el.get("class") or []
        if "competition__stage-title" in cls:
            m = re.search(r"(\d+)", el.get_text(" ", strip=True))
            if m:
                md = int(m.group(1))
            continue
        if "anwp-fl-game" not in cls:
            continue
        # game-status-1 が消化。枠は generate_fixtures 側が作る。
        if "game-status-1" not in cls:
            continue
        h = el.select_one(".match-slim__team-home-title")
        a = el.select_one(".match-slim__team-away-title")
        hs = el.select_one(".anwp-fl-game__scores-home")
        as_ = el.select_one(".anwp-fl-game__scores-away")
        if not (h and a and hs and as_):
            continue
        hv, av = _to_int(hs.get_text(strip=True)), _to_int(as_.get_text(strip=True))
        if hv is None or av is None:
            continue
        kick = el.get("data-fl-game-kickoff") or ""     # 2026-03-07T12:00:00+09:00
        matches.append(dict(
            date=kick[:10], home=h.get_text(" ", strip=True),
            hs=hv, **{"as": av}, away=a.get_text(" ", strip=True),
            md=md, kickoff=kick[11:16]))
    return standings, matches


# ============================================================
# 沖縄（okinawa-soccer-habu.com）— 県協会2種委員会「波布リーグ」
#   試合 /scores/table/161 … table 1つ・57行。日程と会場に rowspan がかかるので
#     行によってセル数が 8/10/11/12 と変わる。**列番号で取ってはいけない。**
#     td.all_score を基準に、2つ前=ホーム名/1つ前=ホーム得点/1つ後=アウェイ得点/
#     2つ後=アウェイ名 で取る。
#   星取表 /scores/sheet/161 … 勝ち点・得点・失点・得失差・順位
# ⚠️ **星取表のHTMLが不正**。<tr> 開始9個に対し </tr> の閉じが1個しかなく、
#    パースすると全チームが1行に潰れる（山口は逆に閉じのほうが多かった。壊れ方が違う）。
#    → セルを平らに並べ、ヘッダ幅（「順位」の位置+1＝12）で切り直す。
#    切ったあとデータ行がちょうどチーム数になることを必ず確認する。
# ⚠️ **HTTPヘッダに charset が無い**（meta は UTF-8）。明示しないと requests が
#    ISO-8859-1 を仮定して静かに文字化けする。宮崎とまったく同じ罠。
# ⚠️ 得点/失点は1セルに見えるが <span> が3つ（得点・失点・得失差）。
#    get_text() をそのまま使うと "17710" に連結される。区切りを指定して分ける。
# 得点者・警告退場も取れる（将来の県別得点ランキング用。いまは使わない）
# 年度切り替え: /scores/table/ の番号を差し替える（県協会サイトからは辿れない）
# ============================================================
_OKINAWA_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")


def read_okinawa(cfg: dict) -> tuple[dict, list[dict]]:
    base = f"http://www.okinawa-soccer-habu.com/scores"
    tid = cfg["tid"]

    # --- 星取表（順位表として使う） ---
    soup = BeautifulSoup(fetch_html(f"{base}/sheet/{tid}", encoding="utf-8",
                                    must_contain="勝ち点"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    tbl = max(soup.find_all("table"),
              key=lambda t: len(t.find_all(["td", "th"])), default=None)
    if tbl is not None:
        cells = tbl.find_all(["td", "th"])
        texts = [c.get_text("|", strip=True) for c in cells]
        if "順位" in texts:
            width = texts.index("順位") + 1
            rows = [cells[i:i + width] for i in range(width, len(cells), width)]
            rows = [r for r in rows if len(r) == width]
            for r in rows:
                name = r[0].get_text(" ", strip=True).strip()
                pts = _to_int(r[-3].get_text(strip=True))
                # 得失点セルは <span>得点</span><span>失点</span><span>差</span>
                gs = [x for x in r[-2].get_text("|", strip=True).split("|") if x != ""]
                rank = _to_int(r[-1].get_text(strip=True))
                if name and pts is not None and rank is not None and len(gs) >= 2:
                    standings[name] = dict(pts=pts, gf=_to_int(gs[0]),
                                           ga=_to_int(gs[1]), rank=rank)

    # --- 試合 ---
    soup2 = BeautifulSoup(fetch_html(f"{base}/table/{tid}", encoding="utf-8",
                                     must_contain="得点者"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    tbl2 = max(soup2.find_all("table"),
               key=lambda t: len(t.find_all("tr")), default=None)
    cur_date = ""
    if tbl2 is not None:
        for tr in tbl2.find_all("tr"):
            cs = tr.find_all(["td", "th"])
            if not cs:
                continue
            # 日程は rowspan で複数行にまたがる。現れたら以降の行に引き継ぐ。
            first = cs[0]
            if first.get("rowspan") and _OKINAWA_DATE_RE.search(first.get_text()):
                dm = _OKINAWA_DATE_RE.search(first.get_text())
                cur_date = (f"{SEASON_YEAR}-{int(dm.group(1)):02d}-"
                            f"{int(dm.group(2)):02d}")
            sc = tr.find("td", class_="all_score")
            if sc is None or sc not in cs:
                continue
            i = cs.index(sc)
            if i < 2 or i + 2 >= len(cs):
                continue
            home = cs[i - 2].get_text(" ", strip=True).strip()
            away = cs[i + 2].get_text(" ", strip=True).strip()
            hs = _to_int(cs[i - 1].get_text(strip=True))
            as_ = _to_int(cs[i + 1].get_text(strip=True))
            if not home or not away or hs is None or as_ is None:
                continue      # 未消化。枠は generate_fixtures 側が作る
            tm = re.search(r"(\d{1,2}):(\d{2})", " ".join(
                c.get_text(" ", strip=True) for c in cs[:i - 2]))
            matches.append(dict(date=cur_date, home=home, hs=hs,
                                **{"as": as_}, away=away,
                                kickoff=f"{int(tm.group(1)):02d}:{tm.group(2)}"
                                if tm else ""))
    return standings, matches


# ============================================================
# SportsOnline の「星取表＋全試合が1ページ」型（島根・広島で共用）
#   viewdata.aspx 1本で順位表と全試合が取れる（POST・ViewState・cookie 不要）。
#   table[2] = 星取表＋順位表 … 順位|チーム名|Nチーム列|勝数|負数|引分|勝点|得点|失点|得失差
#   table[3] = 全試合一覧     … 組み合わせ|開始日|開始時刻|進行状況|会場|審判|ユニフォーム
#
# ✅ 共用の根拠（2026-09-07）: 島根用に書いたこの関数を**無改造で広島に当てて動くことを
#    実測で確認**したうえで共用にした。構造を決め打ちしていないので列数が違っても動く
#    （順位表は「得失差」の位置からヘッダ幅を導出／列は名前で引く／試合表はヘッダで探す）。
#    実測: 島根8チーム17列・広島10チーム19列。
# ⚠️ **3県目が出てきたら、まず無改造で当ててみること。**
#    **無改造で動いたら共用、分岐が要るなら別リーダにする。**
#    分岐を足して共用を維持するより、別に書くほうが安全（「同じプラットフォームだから
#    同じだろう」で共通化して静かにズレるのが、いちばん避けたい形）。
# ⚠️ **山口は共用しない。** 日付が全部ダミーで既存JSONからの引き継ぎ処理が要り、
#    表の位置も違う。表面の違いではなく**扱いの違い**なので混ぜない。
#
# ⚠️ **HTMLの壊れ方は県ごとに違う**（山口=`</tr>`が多い／島根=`<tr>`が多い／
#    広島=`</tr>`が多いが順位表の潰れ方は島根と同じ）。壊れ方と必要な対処は別物。
#    どの県でも順位表は1行に潰れるので、ヘッダ幅で切り直す。
#    ★**復元後の行数がチーム数と一致しなければ失敗にする**（共用なので、片方の県で
#      HTMLの形が変わったときにもう片方の期待で黙って通るのを防ぐ）。
# ⚠️ 山口と違い **実際の試合日が入っている**ので NO_RECENT_RESULTS には入れない。
# 年度切り替え: parentid / rallyid を差し替える（Rally.aspx の子大会一覧から）
# ============================================================
_SPORTSONLINE_SCORE_RE = re.compile(r"^(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)$")
_SPORTSONLINE_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def read_sportsonline_table(cfg: dict) -> tuple[dict, list[dict]]:
    soup = BeautifulSoup(fetch_html(cfg["url"], encoding="utf-8",
                                    must_contain="得失差"), "html.parser")
    time.sleep(SLEEP)
    tables = soup.find_all("table")

    # --- 順位表（潰れた1行を列数で切り直す） ---
    standings = {}
    for table in tables:
        cells = table.find_all(["td", "th"])
        texts = [c.get_text(" ", strip=True) for c in cells]
        if "得失差" not in texts or "勝点" not in texts:
            continue
        width = texts.index("得失差") + 1
        head = texts[:width]
        col = {}
        for i, c in enumerate(head):
            for key, name in (("won", "勝数"), ("lost", "負数"), ("drawn", "引分"),
                              ("pts", "勝点"), ("gf", "得点"), ("ga", "失点")):
                if key not in col and c == name:
                    col[key] = i
        if len(col) < 6:
            continue
        rows = [texts[i:i + width] for i in range(width, len(texts), width)]
        full = [r for r in rows if len(r) == width]
        # ★ 復元後の行数がチーム数と一致しなければ**失敗にする**（据え置き）。
        #   共用のリーダなので、片方の県でHTMLの形が変わったときに
        #   もう片方の期待で黙って通るのを防ぐ。警告ではなく失敗にすること。
        expected = cfg.get("teams")
        if expected is not None and len(full) != expected:
            raise RuntimeError(
                f"順位表の復元行数 {len(full)} がチーム数 {expected} と一致しない"
                f"（列数{width}で切り直した結果。出典のHTMLの形が変わった疑い）")
        if len(full) != len(rows):
            raise RuntimeError(
                f"順位表に列数{width}で割り切れない行がある"
                f"（{len(rows) - len(full)}行。出典のHTMLの形が変わった疑い）")
        rows = full
        for r in rows:
            team = r[1].strip()
            vals = {k: _to_int(r[i]) for k, i in col.items()}
            vals["played"] = sum(v for k, v in vals.items()
                                 if k in ("won", "drawn", "lost") and v is not None)
            if team and all(v is not None for v in vals.values()):
                standings[team] = vals
        if standings:
            break

    # --- 試合一覧 ---
    matches = []
    for table in tables:
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        head = next((r for r in rows if len(r) >= 4 and "組み合わせ" in r[0]), None)
        if not head:
            continue
        for r in rows[rows.index(head) + 1:]:
            # 途中に「Away」などの区切り行が入る。セル数で弾く。
            if len(r) < 4:
                continue
            if "試合終了" not in r[3]:
                continue          # 未消化。枠は generate_fixtures 側が作る
            m = _SPORTSONLINE_SCORE_RE.match(r[0])
            if not m:
                continue
            dm = _SPORTSONLINE_DATE_RE.search(r[1])
            matches.append(dict(
                date=(f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
                      if dm else ""),
                home=m.group(1).strip(), hs=int(m.group(2)),
                **{"as": int(m.group(3))}, away=m.group(4).strip(),
                kickoff=r[2].strip() if len(r) > 2 else "",
                venue=r[4].strip() if len(r) > 4 else ""))
        if matches:
            break
    return standings, matches


# ============================================================
# 岡山（okayama-fa.or.jp）— 県協会のテキストPDF
# ⚠️ **PDFのURLは更新のたびに変わる**（2026-09-07に1日で /2026/06/ → /2026/09/ に変わった）。
#    URLを固定で書かず、**入口ページから毎回辿る**こと。
#    同じページに `➡2026` が3つある（高校総体・OKAYAMA・チャレンジリーグ）ので、
#    **見出し「高円宮杯 JFA U-18 サッカーリーグ OKAYAMA」の直後**のリンクを取る。
# ⚠️ **1ページに県1部（左段）と県2部（右段）が並ぶ。** テキスト抽出すると1行に両方出るので、
#    **座標（extract_words）で x < 430 の左段だけを取る**。こうすると2部がそもそも入ってこない
#    （`光南B`(1部) と `光南C`(2部) の取り違えが構造的に起きない）。
#    チーム名の集合による絞り込みは保険として残す。
# ⚠️ 単語の top は1試合の中で数px ばらつく（チーム名が少し上に出る）ので、
#    許容差4pxでクラスタしてから x 順に並べる。
# ⚠️ 節と日付：**ページ末尾に一覧は無い**。各節ブロックの中の行に埋め込まれている。
#    - `1 4月4日 就実 9:00 3 ファジB 3 - 0 就 実 B 8` … 行頭に「節 月日」
#    - `2 理大 12:30 3 …` ＋ 独立行 `4月11日`        … 節2だけ番号と日付が別の行
#    - `4月12日 創志赤坂 12:30 1 …`                  … その節の既定日と違う日＝行頭日付を優先
#    試合行は**節ごとに5試合ずつ節番号の順**に並ぶので、5件ずつ区切って節番号を振る。
# ⚠️ チーム名に全角空白が入る（`光 南 B` `古 城 池`）ので除去してから名寄せする。
# ⚠️ **公式順位表は存在しない。** 順位表は試合から自前計算し、代替ゲートで守る（宮崎と同じ）。
# ✅ **版日付ガード**：PDF冒頭の版日付（`2026/9/7`）より後の日付を持つ「消化済み」試合を
#    作っていたら、日付の割り当てが壊れている。**据え置きにする。**
#    これは「取れなくなったこと」ではなく「静かに間違ったものを取り始めたこと」を捕まえる
#    仕掛けで、鮮度チェック（4-2c）では拾えない種類の事故に効く。
# 年度切り替え: 入口URLは固定。見出し直下の新年度リンクを自動で辿る
# ============================================================
_OKAYAMA_SPLIT_X = 430          # 県1部（左段）と県2部（右段）の境界
_OKAYAMA_ROW_TOL = 4            # 同じ行とみなす top の許容差(px)
_OKAYAMA_MATCH_RE = re.compile(
    r"(\d{1,2}:\d{2})\s+(\d{1,2})\s+(.+?)\s+(?:(\d+)\s*-\s*(\d+)|-)\s+(.+?)\s+(\d{1,2})\s*$")
_OKAYAMA_HEAD_MD_DATE = re.compile(r"^(\d{1,2})\s+(\d{1,2})月(\d{1,2})日")
_OKAYAMA_HEAD_DATE = re.compile(r"^(\d{1,2})月(\d{1,2})日")
_OKAYAMA_ONLY_DATE = re.compile(r"^(\d{1,2})月(\d{1,2})日$")


def _okayama_pdf_url(cfg: dict) -> str:
    """入口ページから、その年度のリーグ戦PDFのURLを辿る。"""
    soup = BeautifulSoup(fetch_html(cfg["entry"], encoding="utf-8",
                                    must_contain=cfg["heading"]), "html.parser")
    time.sleep(SLEEP)
    return pdf_source.pdf_link_after_heading(soup, cfg["heading"])


def _okayama_rows(page) -> list[str]:
    """左段（県1部）だけを、1試合＝1行の文字列にして返す。"""
    return pdf_source.page_row_texts(page, _OKAYAMA_ROW_TOL, x_max=_OKAYAMA_SPLIT_X, top_min=75)


def read_okayama(cfg: dict) -> tuple[dict, list[dict]]:
    url = _okayama_pdf_url(cfg)
    content = pdf_source.fetch_pdf(url, HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)

    with pdf_source.open_pdf(content) as pdf:
        lines = [ln for pg in pdf.pages for ln in _okayama_rows(pg)]
        version = pdf_source.version_date(pdf.pages[0].extract_text() or "")
    if not version:
        raise RuntimeError("PDF冒頭の版日付が読めない")

    matches, md_date = [], {}
    for line in lines:
        m = _OKAYAMA_MATCH_RE.search(line)
        if not m:
            # 節2のように、節の既定日だけが独立行で出ることがある
            d = _OKAYAMA_ONLY_DATE.match(line.strip())
            if d:
                md_date[len(matches) // 5 + 1] = \
                    f"{SEASON_YEAR}-{int(d.group(1)):02d}-{int(d.group(2)):02d}"
            continue
        pre = line[:m.start()].strip()
        own = ""
        hm = _OKAYAMA_HEAD_MD_DATE.match(pre)
        if hm:
            md_date[int(hm.group(1))] = \
                f"{SEASON_YEAR}-{int(hm.group(2)):02d}-{int(hm.group(3)):02d}"
        else:
            hd = _OKAYAMA_HEAD_DATE.match(pre)
            if hd:      # その節の既定日と違う日に行われた試合。行頭の日付を優先する
                own = f"{SEASON_YEAR}-{int(hd.group(1)):02d}-{int(hd.group(2)):02d}"
        matches.append(dict(
            md=len(matches) // 5 + 1, _own=own,
            home=m.group(3).replace(" ", "").replace("　", ""),
            away=m.group(6).replace(" ", "").replace("　", ""),
            hs=int(m.group(4)) if m.group(4) else None,
            **{"as": int(m.group(5)) if m.group(5) else None},
            kickoff=m.group(1)))

    for x in matches:
        x["date"] = x.pop("_own") or md_date.get(x["md"], "")

    # ✅ 版日付ガード。日付の割り当てが壊れたことを検知する唯一の手がかり。
    future = [x for x in matches
              if x["hs"] is not None and x["date"] and x["date"] > version]
    if future:
        raise RuntimeError(
            f"版日付({version})より後の日付を持つ消化済み試合が{len(future)}件ある"
            f"（例: {future[0]['date']} {future[0]['home']} vs {future[0]['away']}）。"
            f"節と日付の割り当てが壊れている疑い")
    blank = [x for x in matches if x["hs"] is not None and not x["date"]]
    if blank:
        raise RuntimeError(f"日付を割り当てられなかった消化済み試合が{len(blank)}件ある")

    # 公式順位表は存在しない。process 側で試合から自前計算する（standings_gate: self）。
    return {}, matches


# ============================================================
# 大分（ofa.or.jp）— 県協会のテキストPDF。前期・後期で記事もPDFも別（2026-09-14追加）
# ⚠️ **1回戦総当たり×2（前期 第1〜9節・後期 第10〜18節）。** 前期45試合だけで「全試合消化済み」
#    に見え、見張りが7/19から2か月黙っていた。**前期と後期の対戦表を両方読んで90枠にする**（double_round）。
# ⚠️ **PDFのURLは版ごとに変わる**（`2026ofa1ten-1.pdf`／`2026ofa1tenkouki.pdf`…）。
#    入口＝高校カテゴリの記事一覧 → 「OFAリーグ前期/後期 …試合結果」の記事 → PDF と毎回辿る。
#    記事一覧はページ送りがあるので、前期の記事が2ページ目以降に落ちても探しに行く。
# ⚠️ **記事の中のリンク文字は「対戦表」「星取表」だけで、1部〜3部Cが同じ文字で並ぶ。**
#    見出しでも見分けられない。→ **PDF冒頭の「OFA1部リーグ」を読んで1部を特定する**
#    （ファイル名の `ofa1` には頼らない）。
# ⚠️ 日付は対戦表の「月日」列。**節の途中で日付が変わる**（第12節=9/19と9/20、第15節=10/10と10/12）
#    ので、節ではなく**行ごとに直前の月日を引き継ぐ**。延期で第10節が12/12に回っている。
# ⚠️ **星取表の勝点・得点・失点・得失差は「前期／通算／後期」の3段重ね**（1セルに改行区切り）。
#    2026-09-14に3段とも試合から計算した値と10チーム全部で一致することを確認した。
#    **中段（通算）を公式順位表として使う。** 勝分敗・試合数・順位は無い（左端の数字は
#    チーム番号で順位ではない）→ 沖縄と同じ「勝点・得点・失点」の代替ゲートで守る。
# ⚠️ 星取表のマス目は公式側の記入ミスがある（2026-09-14時点、中津東の後期 1×2 大分西 が
#    「大分」の列に入っている）。**試合はマス目からは作らず、対戦表から作る。**
# ✅ 版日付ガード：記事タイトルの「(9/13現在)」より後の日付を持つ消化済み試合があれば据え置く。
# 年度切り替え: 入口URLは固定。記事タイトルの年度（SEASON_YEAR）で絞る
# ============================================================
_OITA_ENTRY = "https://www.ofa.or.jp/news/tournaments/high-school/"
_OITA_MAX_PAGES = 5
_OITA_ASOF_RE = re.compile(r"(\d{1,2})/(\d{1,2})\s*現在")
_OITA_MD_RE = re.compile(r"第\s*(\d+)\s*節")
_OITA_DATE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")
_OITA_SCORE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def _oita_articles() -> dict:
    """{"前期": (タイトル, URL), "後期": (…)} をそれぞれ最新の記事で返す。"""
    found = {}
    for page in range(1, _OITA_MAX_PAGES + 1):
        url = _OITA_ENTRY if page == 1 else f"{_OITA_ENTRY}page/{page}/"
        soup = BeautifulSoup(fetch_html(url, encoding="utf-8"), "html.parser")
        time.sleep(SLEEP)
        for a in soup.find_all("a", href=True):
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            if not (f"サッカーリーグ{SEASON_YEAR}" in title and "OFAリーグ" in title
                    and "試合結果" in title):
                continue
            for phase in ("前期", "後期"):
                if phase in title and phase not in found:   # 一覧は新しい順
                    found[phase] = (title, a["href"])
        if "前期" in found and "後期" in found:
            break
    return found


def _oita_pdf(article_url: str, link_text: str, title_word: str) -> bytes:
    """記事の中から、PDF冒頭に title_word（例「OFA1部リーグ」）を含む link_text のPDFを返す。"""
    import io
    import pdfplumber

    soup = BeautifulSoup(fetch_html(article_url, encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True) != link_text or not a["href"].lower().endswith(".pdf"):
            continue
        resp = requests.get(a["href"], headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        time.sleep(SLEEP)
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            head = re.sub(r"\s+", "", pdf.pages[0].extract_text() or "")[:200]
        if title_word in head:
            return resp.content
    raise RuntimeError(f"記事に1部の{link_text}PDFが無い（{article_url}）")


def _oita_schedule(content: bytes) -> list[dict]:
    """対戦表PDF → 試合のリスト（未消化も含む）"""
    import io
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        rows = [r for pg in pdf.pages for t in pg.extract_tables() for r in t]
    out, md, day = [], None, ""
    for r in rows:
        if len(r) < 6:
            continue
        mm = _OITA_MD_RE.search(r[0] or "")
        if mm:
            md = int(mm.group(1))
        dm = _OITA_DATE_RE.search(r[1] or "")
        if dm:
            day = f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
        card = re.sub(r"[\s　]+", "", r[4] or "")
        if "vs" not in card:
            continue
        home, away = card.split("vs", 1)
        sm = _OITA_SCORE_RE.match((r[5] or "").strip())
        if (r[5] or "").strip() and not sm:
            raise RuntimeError(f"結果欄が読めない: {r[5]!r}（{home} vs {away}）")
        out.append(dict(md=md, date=day, home=home, away=away,
                        hs=int(sm.group(1)) if sm else None,
                        **{"as": int(sm.group(2)) if sm else None},
                        kickoff=(r[3] or "").strip()))
    return out


def _oita_totals(content: bytes) -> dict:
    """星取表PDF → {チーム名: {pts, gf, ga}}（中段＝通算）"""
    import io
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        rows = pdf.pages[0].extract_tables()[0]
    head = [re.sub(r"\s+", "", c or "") for c in rows[0]]
    col = {k: head.index(k) for k in ("勝点", "得点", "失点")}
    totals = {}
    for r in rows[1:]:
        if not (r[0] or "").strip().isdigit():
            continue
        name = re.sub(r"\s+", "", r[1] or "")
        vals = {}
        for key, label in (("pts", "勝点"), ("gf", "得点"), ("ga", "失点")):
            stack = (r[col[label]] or "").split("\n")
            if len(stack) != 3:
                raise RuntimeError(f"{name} の{label}が「前期／通算／後期」の3段になっていない: {stack}")
            vals[key] = int(stack[1])
        totals[name] = vals
    return totals


def read_oita(cfg: dict) -> tuple[dict, list[dict]]:
    arts = _oita_articles()
    if "前期" not in arts:
        raise RuntimeError(f"入口から{SEASON_YEAR}年のOFAリーグ前期の結果記事が見つからない")

    matches, versions = [], []
    for phase in ("前期", "後期"):
        if phase not in arts:
            continue
        title, url = arts[phase]
        got = _oita_schedule(_oita_pdf(url, "対戦表", "OFA1部リーグ"))
        if len(got) != cfg["teams"] * (cfg["teams"] - 1) // 2:
            raise RuntimeError(f"{phase}の対戦表が{len(got)}試合（1回戦総当たりの"
                               f"{cfg['teams'] * (cfg['teams'] - 1) // 2}試合と違う）")
        matches += got
        am = _OITA_ASOF_RE.search(title)
        if am:
            versions.append(f"{SEASON_YEAR}-{int(am.group(1)):02d}-{int(am.group(2)):02d}")

    # 公式順位表の代わり＝最新の記事（後期があれば後期）の星取表の「通算」段
    latest = arts.get("後期") or arts["前期"]
    standings = _oita_totals(_oita_pdf(latest[1], "星取表", "OFA1部リーグ"))

    # ✅ 版日付ガード（「(9/13現在)」より後の日付を持つ消化済み試合＝日付の割り当てが壊れている）
    version = max(versions) if versions else _jst_today().isoformat()
    future = [x for x in matches if x["hs"] is not None and x["date"] > version]
    if future:
        raise RuntimeError(
            f"版日付({version})より後の日付を持つ消化済み試合が{len(future)}件ある"
            f"（例: {future[0]['date']} {future[0]['home']} vs {future[0]['away']}）")
    blank = [x for x in matches if x["hs"] is not None and not x["date"]]
    if blank:
        raise RuntimeError(f"日付を割り当てられなかった消化済み試合が{len(blank)}件ある")
    return standings, matches


# ============================================================
# 新潟（niigata-fa.or.jp）— 県協会の試合一覧HTML＋星取表PDFの2ソース構成（2026-09-14追加）
#   一覧: /result/contest/tournament_id/{tid} … 1部の全56試合が1ページ（素のHTML）
#   補完: 記事「高円宮杯U-18新潟県リーグ 星取表」の「N1星取表（第◯節終了時点）」PDF
# ⚠️⚠️ **一覧ページに入力漏れがある。** 2026-09-14時点で 7/18 の2試合が一覧では「試合予定」の
#    ままだが、**星取表PDF（第11節終了時点・9/8更新）には結果が載っている**。星取表の順位表
#    （勝点・得点・失点）は、一覧の9/8までの42試合だけだと8チーム中4チームしか合わず、
#    この2試合を足すと8チーム全部が一致した。→ 設定 "hoshitori_results" で補う。
#    📌「第◯節終了時点」は古さではなく**網羅範囲**の表示。どちらが新しいかだけでなく何を含むかを見る。
#    - 一覧に後からスコアが入ったら**一覧を使う**（補完は使われなくなる＝設定を消すサイン）
#    - そのとき星取表の値と食い違っていたら**書き込まない**（どちらかが誤っている）
#    - 補完対象の試合が一覧から消えていたら**書き込まない**（ページの作りが変わった疑い）
#    星取表は第11節止まりで9/13の試合を含まないので、**検算ゲートには使わない**（self ゲート）。
# ⚠️ **節番号と日付が単調でない**（第6節が8/30、第11節に7/18と9/5が混在）。日付は必ず各行から取る。
# ⚠️ 年は本文に無い（`09.13` だけ）。ページの大会名に SEASON_YEAR が含まれることを必須にしている
#    ので、年度が変わって tid が古いままなら取得失敗で止まる。
# 年度切り替え: tid を新年度の「高円宮杯 JFA U-18サッカーリーグ{年} 新潟県リーグ 1部」のものに差し替え、
#              hoshitori_results を空にする
# ============================================================
_NIIGATA_SCORE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
_NIIGATA_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})$")


def read_niigata(cfg: dict) -> tuple[dict, list[dict]]:
    url = f"https://www.niigata-fa.or.jp/result/contest/tournament_id/{cfg['tid']}"
    soup = BeautifulSoup(fetch_html(url, encoding="utf-8",
                                    must_contain=f"U-18サッカーリーグ{SEASON_YEAR}"), "html.parser")
    time.sleep(SLEEP)
    matches = []
    for b in soup.select("div.p-result__tournament"):
        md_p = b.select(".type p")
        date_p = b.select(".date p")
        side = b.select(".score > p")
        if len(md_p) < 2 or not date_p or len(side) < 3:
            raise RuntimeError("試合ブロックの形が想定と違う（ページの作りが変わった疑い）")
        dm = _NIIGATA_DATE_RE.match(date_p[0].get_text(strip=True))
        if not dm:
            raise RuntimeError(f"日付が読めない: {date_p[0].get_text(strip=True)!r}")
        mid = re.sub(r"\s+", " ", side[1].get_text(" ", strip=True))
        sm = _NIIGATA_SCORE_RE.match(mid)
        if not sm and mid != "試合予定":
            raise RuntimeError(f"スコア欄が読めない: {mid!r}")
        mdm = re.search(r"\d+", md_p[1].get_text(strip=True))
        matches.append(dict(
            md=int(mdm.group()) if mdm else 0,
            date=f"{SEASON_YEAR}-{dm.group(1)}-{dm.group(2)}",
            home=re.sub(r"\s+", "", side[0].get_text(strip=True)),
            away=re.sub(r"\s+", "", side[-1].get_text(strip=True)),
            hs=int(sm.group(1)) if sm else None,
            **{"as": int(sm.group(2)) if sm else None}))
    if len(matches) != cfg["teams"] * (cfg["teams"] - 1):
        raise RuntimeError(f"試合数が{len(matches)}（2回戦総当たりの{cfg['teams'] * (cfg['teams'] - 1)}と違う）")

    # --- 星取表PDFでしか確認できない結果を補う ---
    for sup in cfg.get("hoshitori_results") or []:
        hit = [m for m in matches
               if m["date"] == sup["date"] and {m["home"], m["away"]} == {sup["home"], sup["away"]}]
        if len(hit) != 1:
            raise RuntimeError(f"補完する試合 {sup['date']} {sup['home']} vs {sup['away']} が"
                               f"一覧に{len(hit)}件（1件のはず）")
        m = hit[0]
        hs, as_ = ((sup["hs"], sup["as"]) if m["home"] == sup["home"] else (sup["as"], sup["hs"]))
        if m["hs"] is None:
            m["hs"], m["as"] = hs, as_
            print(f"       （新潟: 一覧で「試合予定」の {sup['date']} {m['home']} {hs}-{as_} {m['away']} "
                  f"を星取表PDFの結果で補完）")
        elif (m["hs"], m["as"]) != (hs, as_):
            raise RuntimeError(f"{sup['date']} {m['home']} vs {m['away']}: 一覧 {m['hs']}-{m['as']} と"
                               f"星取表 {hs}-{as_} が食い違う")
        else:
            print(f"       （新潟: {sup['date']} {m['home']} vs {m['away']} は一覧に入力済み。"
                  f"hoshitori_results から外してよい）")
    return {}, matches


# ============================================================
# 北海道（kawakitanet）— 北海道FAリーグ（2026-09-18追加・47県目）
#   試合結果 select.php?pref_cd=1&gameid={gameid} ／ 順位表 main.php?pref_cd=1&gameid={gameid}
#
# ⚠️⚠️ **kawakitanet は北海道サッカー協会ではない。** 個人運営のリーグ戦管理サービスで、
#    ページに「試合結果を追加する」フォームがあり編集パスは「お好きな4〜8桁の数字」＝**誰でも追加できる**。
#    junior-soccer.jp と同じ「有志入力」の型。`label` に「公式」と書かないこと（sourceName に出る）。
#    ⭐️ それでも使う根拠＝**公式（北海道サッカー協会の星取表PDF・7/5現在）と1件も違わなかった**。
#       公式は7/5で止まっていて残り3か月ぶんが出ていないので、結果はこちらを使うほかない。
#
# ⚠️⚠️ **文字コードは HTTPヘッダの charset=UTF-8 が正。**
#    HTML内の `<meta ... charset=EUC-JP>` は**古いまま残っている嘘**で、
#    これを信じてデコードすると 0xe5 で落ちる（2026-09-18 実測）。
#    → **ヘッダを優先し、メタタグは見ない**（fetch_html に encoding を渡さない）。
#
# ⚠️ **試合一覧に `<table>` タグが1つも無い。** 全体がほぼ1行のHTMLで、`<hr>` 区切りの直列。
#    1試合ぶんの実体：
#      <font size=-1>2026-09-12 忠和公園 多目的広場</font></br>VITA U-18
#      <font color=red><b> 2-0</font></b> 札幌第一<a href="update.php?...&game_num=290076">更</a>
#    ⚠️ `</br>`（閉じタグの書き方が逆）や `<font color=red><b>…</font></b>`（入れ子が交差）など
#       HTMLとして壊れているので、パーサではなく**正規表現で1かたまりずつ読む**。
#
# ⚠️ **順位表に得点・失点が無い（得失点差だけ）。** 列は 順位・チーム・試合・勝点・勝・分・敗・得失。
#    → 既定ゲート（全項目一致）も okinawa ゲート（勝点・得点・失点）も使えない。**pts_gd ゲート**を使う。
#
# ⭐️ `game_num` は**出典が各試合に付けている固有ID**。`srcId` として保存すると
#    「既存の試合のスコアが黙って書き換わった」を正確に検出できる。
#    ⚠️ **他県には無いキー**なので、読む側は無くても壊れない作りにすること。
# ============================================================
_HKD_MATCH_RE = re.compile(
    r"<font size=-1>\s*(\d{4}-\d{2}-\d{2})\s*(.*?)</font>"      # 日付と会場
    r".*?</br>\s*(.*?)\s*<font color=red>\s*<b>\s*"             # ホーム
    r"(\d+)\s*[-‐−–—]\s*(\d+)\s*</font>\s*</b>\s*"              # スコア
    r"(.*?)\s*<a href=\"update\.php\?[^\"]*game_num=(\d+)",     # アウェイと固有ID
    re.S)
_HKD_TAG_RE = re.compile(r"<[^>]+>")


def _hkd_text(s: str) -> str:
    """タグを剥がして空白（全角含む）を落とす。"""
    return re.sub(r"[\s　]+", " ", _HKD_TAG_RE.sub("", s or "")).strip()


def read_hokkaido(cfg: dict) -> tuple[dict, list[dict]]:
    base = "https://www.kawakitanet.com/league_soccer"
    q = f"pref_cd=1&gameid={cfg['gameid']}"

    # --- 試合結果 ---
    # ⚠️ encoding を渡さない＝ヘッダの charset(UTF-8) に従わせる。メタタグの EUC-JP は嘘。
    html = fetch_html(f"{base}/select.php?{q}", must_contain="試合結果一覧")
    time.sleep(SLEEP)
    matches = []
    for date, venue, home, hs, as_, away, gid in _HKD_MATCH_RE.findall(html):
        home, away, venue = _hkd_text(home), _hkd_text(away), _hkd_text(venue)
        if not home or not away:
            continue
        matches.append(dict(md=0, date=date, home=home, hs=int(hs),
                            **{"as": int(as_)}, away=away,
                            venue=venue, srcId=gid))
    # ページ末尾に「42試合」と自己申告があるので、読み取り漏れをここで捕まえる
    mm = re.search(r"(\d+)\s*試合", _hkd_text(html))
    if mm and int(mm.group(1)) != len(matches):
        raise RuntimeError(f"試合結果が{len(matches)}件（ページの自己申告は{mm.group(1)}件）")
    if not matches:
        raise RuntimeError("試合結果を1件も読めなかった（ページの作りが変わった可能性）")

    # --- 順位表 ---
    soup = BeautifulSoup(fetch_html(f"{base}/main.php?{q}"), "html.parser")
    time.sleep(SLEEP)
    standings = {}
    for table in soup.find_all("table"):
        rows = _rows(table)
        head = next((r for r in rows if "勝点" in r and "得失" in r), None)
        if not head:
            continue
        idx = {k: head.index(k) for k in ("順位", "チーム", "試合", "勝点", "勝", "分", "負", "得失")
               if k in head}
        if not {"順位", "チーム", "勝点", "得失"} <= set(idx):
            continue
        for r in rows[rows.index(head) + 1:]:
            if len(r) <= max(idx.values()):
                continue
            name = r[idx["チーム"]].strip()
            rank, pts, gd = (_to_int(r[idx["順位"]]), _to_int(r[idx["勝点"]]), _to_int(r[idx["得失"]]))
            if not name or rank is None or pts is None or gd is None:
                continue
            # ⚠️ pts_gd ゲートが見るのは pts / gd / rank の3つ（得点・失点は出典に無い）
            standings[name] = dict(pts=pts, gd=gd, rank=rank)
        if standings:
            break
    n = cfg["teams"]
    if len(standings) != n:
        raise RuntimeError(f"順位表が{len(standings)}チーム（{n}チームのはず）")
    if sum(v["gd"] for v in standings.values()) != 0:
        raise RuntimeError("順位表の得失点差の合計が0でない（読み取りの誤り、または出典の誤り）")
    return standings, matches


# ============================================================
# 秋田（fa-akita.net）— 県協会の日程PDF＋星取表PDF（2026-09-14追加・pdf_source を使う最初の県）
#   入口: 記事「【◯◯更新】2種大会情報」（2026年度は /16943/）。リンク文字が
#         「2026_日程1部・2部･3部(0913更新)」「2026_星取表1部・2部・3部A･3部B(0913更新)」
# ⚠️ **PDFのURLはハッシュ名で更新のたびに変わる。** リンク文字（年度＋「日程」/「星取表」＋「1部」）で辿る。
# ⚠️ **日程PDFの「節」「月日」は結合セルで、文字はセルの縦中央に出る。**
#    座標で「上にある一番近い月日」を前方補完すると、ブロック前半の試合に前の日付が付く。
#    → **表として読む**（pdf_source.page_tables）。結合セルの値は先頭行に入り、以降は None。
#    テキスト抽出だと節・月日が末尾にまとめて出て、節も 14→13 の順に見えるが、表では 1→14 の順に並ぶ。
# ⚠️ 1ブロックの中で同じ日付のセルが分かれていることがある（7/4 のブロックが2つ）。表の読み方なら問題ない。
# ⚠️ 1部は「カテゴリー」列が `A1` の行（A2=2部・A3=3部A）。列は**ヘッダの名前で位置を決める**。
# ⚠️ 星取表は1部〜3部Bが1ファイル4ページ。**ページ冒頭の「１部 星取表」で1部を特定**する。
#    ⚠️⚠️ **列の順が「勝 負 分」**（東京と同じ罠）。ヘッダの名前で位置を取るので順番に依存しない。
#    ✅ 表の下に合計行（勝計 負計 分計 得点計 失点計 得失計）がある → 読み取りの自己検算に使う。
# ✅ 版日付ガード：日程PDF冒頭の「2026/9/13 更新」より後の日付を持つ消化済み試合があれば停止。
# 年度切り替え: 入口の記事IDが年度で変わる見込み（平成27〜30年度は別記事だった）。
#              新年度の「2種大会情報」記事のURLに entry を差し替える。リンク文字の年度で絞っているので、
#              差し替え忘れは「PDFリンクが0件」の取得失敗で止まる（古い年度を黙って読まない）。
# ============================================================
_AKITA_DATE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")
_AKITA_TIME_RE = re.compile(r"^(\d{1,2}:\d{2}|未定)?$")   # 時刻が「未定」のまま消化済みの試合がある


def _akita_links(cfg: dict) -> tuple[str, str]:
    soup = BeautifulSoup(fetch_html(cfg["entry"], encoding="utf-8",
                                    must_contain=f"{SEASON_YEAR}_日程"), "html.parser")
    time.sleep(SLEEP)
    year = str(SEASON_YEAR)
    sched = pdf_source.pdf_link_by_text(
        soup, lambda t: t.startswith(f"{year}_日程") and "1部" in t, "1部の日程")
    hoshi = pdf_source.pdf_link_by_text(
        soup, lambda t: t.startswith(f"{year}_星取表") and "1部" in t, "1部の星取表")
    return sched, hoshi


def _akita_schedule(content: bytes) -> tuple[list[dict], str]:
    with pdf_source.open_pdf(content) as pdf:
        version = pdf_source.version_date(pdf.pages[0].extract_text() or "")
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    if not version:
        raise RuntimeError("日程PDF冒頭の版日付が読めない")
    out, md, day = [], None, ""
    for t in tables:
        head = [re.sub(r"\s+", "", c or "") for c in t[0]]
        if not {"節", "月日", "カテゴリー", "時間", "対戦"} <= set(head):
            raise RuntimeError(f"日程表のヘッダが想定と違う: {head}")
        c_md, c_day, c_cat = head.index("節"), head.index("月日"), head.index("カテゴリー")
        c_time, c_vs = head.index("時間"), head.index("対戦")   # 対戦＝ホーム／得点／-／得点／アウェイ の5列
        for r in t[1:]:
            if (r[c_md] or "").strip().isdigit():
                md = int(r[c_md])
            dm = _AKITA_DATE_RE.search(r[c_day] or "")
            if dm:
                day = f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
            if (r[c_cat] or "").strip() != "A1":
                continue
            home, hs, sep, as_, away = [(r[c_vs + i] or "").strip() for i in range(5)]
            if sep != "-" or not _AKITA_TIME_RE.match((r[c_time] or "").strip()) or not home or not away:
                raise RuntimeError(f"1部の行が読めない: {r}")
            if hs.isdigit() and as_.isdigit():
                hs, as_ = int(hs), int(as_)
            elif not hs and not as_:
                hs = as_ = None
            else:
                raise RuntimeError(f"スコアが読めない: {home} {hs}-{as_} {away}")
            if md is None or not day:
                raise RuntimeError(f"節・月日を割り当てられない: {home} vs {away}")
            out.append(dict(md=md, date=day, home=home, away=away, hs=hs, **{"as": as_},
                            kickoff=(r[c_time] or "").strip()))
    return out, version


def _akita_standings(content: bytes) -> tuple[dict, list[int]]:
    with pdf_source.open_pdf(content) as pdf:
        page = next((p for p in pdf.pages
                     if "1部星取表" in unicodedata.normalize("NFKC", re.sub(r"\s+", "", (p.extract_text() or "")[:80]))),
                    None)
        if page is None:
            raise RuntimeError("星取表PDFに1部のページが無い")
        tables = pdf_source.page_tables(page)
        lines = (page.extract_text() or "").splitlines()
    if len(tables) != 1:
        raise RuntimeError(f"1部の星取表ページの表が{len(tables)}個")
    t = tables[0]
    head = [re.sub(r"\s+", "", c or "") for c in t[0]]
    col = {k: head.index(v) for k, v in (("won", "勝"), ("lost", "負"), ("drawn", "分"),
                                          ("pts", "勝点"), ("gf", "得点"), ("ga", "失点"))}
    standings = {}
    for r in t[1:]:
        name = (r[0] or "").strip()
        if not name or not all((r[c] or "").strip().lstrip("-").isdigit() for c in col.values()):
            continue
        v = {k: int(r[c]) for k, c in col.items()}
        v["played"] = v["won"] + v["drawn"] + v["lost"]
        standings[name] = v
    # 表の下の合計行「勝計 負計 分計 得点計 失点計 得失計」
    tm = re.fullmatch(r"(\d+) (\d+) (\d+) (\d+) (\d+) (-?\d+)", lines[-1].strip()) if lines else None
    if not tm:
        raise RuntimeError("星取表の合計行が読めない")
    totals = [int(x) for x in tm.groups()]
    return standings, totals


def read_akita(cfg: dict) -> tuple[dict, list[dict]]:
    sched_url, hoshi_url = _akita_links(cfg)
    matches, version = _akita_schedule(pdf_source.fetch_pdf(sched_url, HEADERS, TIMEOUT, wait=SLEEP))
    time.sleep(SLEEP)
    standings, totals = _akita_standings(pdf_source.fetch_pdf(hoshi_url, HEADERS, TIMEOUT, wait=SLEEP))
    time.sleep(SLEEP)

    n = cfg["teams"]
    if len(matches) != n * (n - 1):
        raise RuntimeError(f"1部の試合が{len(matches)}件（2回戦総当たりの{n * (n - 1)}件と違う）")
    if len(standings) != n:
        raise RuntimeError(f"星取表の1部が{len(standings)}チーム（{n}のはず）")
    # ✅ 星取表の読み取りの自己検算（合計行と、表から足し上げた値が一致するか）
    got = [sum(v[k] for v in standings.values()) for k in ("won", "lost", "drawn", "gf", "ga")]
    if got != totals[:5] or totals[3] - totals[4] != totals[5] or got[0] != got[1] or got[3] != got[4]:
        raise RuntimeError(f"星取表の合計が合わない（表から {got}／合計行 {totals}）")
    played = [m for m in matches if m["hs"] is not None]
    if sum(v["played"] for v in standings.values()) != len(played) * 2:
        raise RuntimeError(f"星取表の試合数の合計が 消化{len(played)}×2 と合わない"
                           f"（日程と星取表の版がずれている疑い）")
    # ✅ 版日付ガード
    future = [m for m in played if m["date"] > version]
    if future:
        raise RuntimeError(f"版日付({version})より後の日付を持つ消化済み試合が{len(future)}件"
                           f"（例: {future[0]['date']} {future[0]['home']} vs {future[0]['away']}）")
    return standings, matches


# ============================================================
# 兵庫（hyogo-fa.gr.jp）— 県協会の日程･結果PDF（1部）＋戦績表PDF（1･2部）（2026-09-14追加）
#   入口: /competition_info/13224/（高円宮杯U-18兵庫県リーグ1部･2部 2026）
#   リンク文字（空白を詰めたもの）が「日程･結果(1部)」「戦績表(1･2部)」のPDFを使う。
# ⚠️ **同じページにプレーオフの「プレーオフ日程･結果」「プレーオフ戦績表」がある。** 県1部ではない。
#    前方一致だと誤爆するので**リンク文字の完全一致**で取る。中点は半角カナの `･`（U+FF65）。
# ⚠️ 日程PDFの見出しは1ページ目「前期(1～9節)」2ページ目も「前期(10～18節)」（誤記）。実際は通年90試合
#    （試合番号 101〜190）。**試合番号が101〜190で過不足なく揃うこと**を確認して取りこぼしを防ぐ。
# ⚠️ 表として読むと「月/日」「試合番号」「対戦カード」の列に分かれる。対戦カードは
#    `芦 屋 学 園 A 2 VS 2 蒼 開`（**チーム名は1文字ずつ空白区切り**）、未消化は `三 田 B VS 芦 屋 学 園 A`。
# ⚠️ 開始時刻に `17;00`（セミコロン）の誤記がある。**時刻は使わない。**
# ⚠️ 戦績表は1ページに1部と2部の表が並ぶ。**日程のチーム名と同じ10チームの表を1部とみなす。**
#    各チーム「前期」「後期」の2行で、勝点・得失点差・順位は前期の行にだけある。
#    **勝分敗・試合数・得点・失点は無い** → 勝点＋得失点差で照合するゲート（standings_gate: "pts_gd"）。
# ⚠️ 版日付はPDF本文に無い（URLの先頭 `0913-` だけ）。版日付ガードは「今日（JST）より後の消化済み試合」で代用。
# 年度切り替え: 入口の記事ID（13224）が年度で変わる見込み。新年度の「高円宮杯U-18兵庫県リーグ1部･2部」
#              記事に entry を差し替える。ページタイトルの年度を必須にしているので、差し替え忘れは取得失敗で止まる。
# ============================================================
_HYOGO_CARD_RE = re.compile(r"^(.+?)\s+(?:(\d+)\s+VS\s+(\d+)|VS)\s+(.+)$")
_HYOGO_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")


def read_hyogo(cfg: dict) -> tuple[dict, list[dict]]:
    soup = BeautifulSoup(fetch_html(cfg["entry"], encoding="utf-8",
                                    must_contain=f"兵庫県リーグ1部･2部 {SEASON_YEAR}"), "html.parser")
    time.sleep(SLEEP)
    sched_url = pdf_source.pdf_link_by_text(soup, lambda t: t == "日程･結果(1部)", "日程･結果(1部)")
    table_url = pdf_source.pdf_link_by_text(soup, lambda t: t == "戦績表(1･2部)", "戦績表(1･2部)")

    # --- 日程･結果（1部） ---
    content = pdf_source.fetch_pdf(sched_url, HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    matches, numbers = [], []
    for t in tables:
        head = [re.sub(r"\s+", "", c or "") for c in t[0]]
        if not {"月/日", "試合番号", "対戦カード"} <= set(head):
            raise RuntimeError(f"日程表のヘッダが想定と違う: {head}")
        c_day, c_no, c_card = head.index("月/日"), head.index("試合番号"), head.index("対戦カード")
        for r in t[1:]:
            dm = _HYOGO_DATE_RE.match((r[c_day] or "").strip())
            cm = _HYOGO_CARD_RE.match(re.sub(r"\s+", " ", (r[c_card] or "").strip()))
            no = (r[c_no] or "").strip()
            if not (dm and cm and no.isdigit()):
                raise RuntimeError(f"1部の行が読めない: {r}")
            numbers.append(int(no))
            matches.append(dict(
                md=0, date=f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}",
                home=re.sub(r"\s+", "", cm.group(1)), away=re.sub(r"\s+", "", cm.group(4)),
                hs=int(cm.group(2)) if cm.group(2) else None,
                **{"as": int(cm.group(3)) if cm.group(3) else None}))
    n = cfg["teams"]
    want = list(range(cfg["first_no"], cfg["first_no"] + n * (n - 1)))
    if sorted(numbers) != want:
        raise RuntimeError(f"試合番号が {cfg['first_no']}〜{want[-1]} で揃っていない（{len(numbers)}件）")
    teams = {m["home"] for m in matches} | {m["away"] for m in matches}

    # --- 戦績表（1･2部）→ 1部の勝点・得失点差・順位 ---
    content = pdf_source.fetch_pdf(table_url, HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    standings = None
    for t in tables:
        head = [re.sub(r"\s+", "", c or "") for c in t[0]]
        if not {"勝点", "得失点差", "順位"} <= set(head):
            continue
        c_pts, c_gd, c_rank = head.index("勝点"), head.index("得失点差"), head.index("順位")
        rows = {}
        for r in t[1:]:
            name = re.sub(r"\s+", "", r[0] or "")
            if name and (r[1] or "").strip() == "前期":
                rows[name] = dict(pts=int(r[c_pts]), gd=int(r[c_gd]), rank=int(r[c_rank]))
        if set(rows) == teams:
            standings = rows
            break
    if standings is None:
        raise RuntimeError("戦績表に、日程と同じ10チームの表（1部）が無い")

    # ✅ 版日付ガードの代用（本文に版日付が無い）
    today = _jst_today().isoformat()
    future = [m for m in matches if m["hs"] is not None and m["date"] > today]
    if future:
        raise RuntimeError(f"今日({today})より後の日付を持つ消化済み試合が{len(future)}件"
                           f"（例: {future[0]['date']} {future[0]['home']} vs {future[0]['away']}）")
    return standings, matches


# ============================================================
# 徳島（tokushima-fa.jp）— 県協会の日程・結果PDF 1本（T1/T2/T3 同居）（2026-09-15追加）
#   入口: /post-414/（2010年度からの**年度別アーカイブ**が1ページに並ぶ）
# ⚠️⚠️ **どの年度もリンク文字が「※ダウンロード」**。リンク文字では特定できない。
#    → 見出し「高円宮杯U-18サッカーリーグ{年}・徳島県Tリーグ」の直後のPDFを取る（岡山方式）。
#    ⚠️ 見出しの後ろは前年度以前のリンクが続くので、今年のリンクが消えると**前年度を黙って拾う**。
#       → **ファイル名の版日付（t20260913）の年がシーズン年であること**を必須にする。
# ⚠️ 協会ページの T1/T2/T3 リンク先 fukuoka-soccer.com はファン投稿型（「公式結果ではありません」）。**使わない。**
# ⚠️ **公式順位表が無い** → standings_gate: "self"。守りは構造チェックと、下の前後半検算だけ。
#    ❌ 新しく入る試合のホーム/アウェイの取り違えと、括弧（前後半）の無い行のスコアの読み違いは、
#       原理的に検出できない（突き合わせる公式の集計値が無い）。
# ⭐️ **前後半スコアの和＝合計スコア**（`2 - 7 (1-3,1-4)`）で、スコアの読み違いの大半を捕まえる。
#    括弧の無い行がある（2026-09-15時点でT1に2件：No.124・126）ので括弧は任意。無い行の件数をログに出す。
# ⚠️ 表として読む（2ページ目以降）。末尾の「変更日／変更内容」も表なので、ヘッダ先頭が「節」の表だけ使う。
# ⚠️ 節はファイルの並び順と一致しない（延期分が後ろ）。日付は各行の `YYYY/MM/DD(曜)` から取る。
# ⚠️ `No.` は T1/T2/T3 通しの連番 → 全Divまとめて 1〜最大 が過不足なく揃うことで取りこぼしを検出。
# ⚠️ スコアの空白が崩れる行がある（`10- 0`・`1 -10`）。
# 名寄せは norm() で10チームすべて寄る（「高校」「ユース」の除去・全角Ｓ）。ALIAS不要（2026-09-15実測）。
# 年度切り替え: 見出しに SEASON_YEAR を使うので設定変更は不要。
# ============================================================
_TOKUSHIMA_SCORE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)(?:\s*\((\d+)-(\d+),(\d+)-(\d+)\))?$")
_TOKUSHIMA_DATE_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})")


def read_tokushima(cfg: dict) -> tuple[dict, list[dict]]:
    heading = f"高円宮杯U-18サッカーリーグ{SEASON_YEAR}・徳島県Tリーグ"
    soup = BeautifulSoup(fetch_html(cfg["entry"], encoding="utf-8", must_contain=heading), "html.parser")
    time.sleep(SLEEP)
    url = pdf_source.pdf_link_after_heading(soup, heading)
    version = pdf_source.version_from_label(url.rsplit("/", 1)[-1])
    if not version or not version.startswith(f"{SEASON_YEAR}-"):
        raise RuntimeError(f"PDFのファイル名から{SEASON_YEAR}年の版日付が読めない（{url}）。前年度のPDFを拾っている疑い")

    content = pdf_source.fetch_pdf(url, HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]

    numbers, matches, no_half = [], [], []
    for t in tables:
        head = [re.sub(r"\s+", "", c or "") for c in t[0]]
        if not head or head[0] != "節":
            continue                              # 注意事項・変更履歴の表
        if not {"No.", "日付", "Div", "試合開始"} <= set(head):
            raise RuntimeError(f"日程表のヘッダが想定と違う: {head}")
        c_no, c_date, c_div = head.index("No."), head.index("日付"), head.index("Div")
        c_home = head.index("試合開始") + 1        # 以降「ホーム／スコア（前後半）／…／アウェイ」
        for r in t[1:]:
            no = (r[c_no] or "").strip()
            if not no.isdigit():
                raise RuntimeError(f"No. が読めない行: {r}")
            numbers.append(int(no))
            if (r[c_div] or "").strip() != "T1":
                continue
            dm = _TOKUSHIMA_DATE_RE.match((r[c_date] or "").strip())
            score = re.sub(r"\s+", " ", (r[c_home + 1] or "").strip())
            home = re.sub(r"\s+", "", r[c_home] or "")
            away = re.sub(r"\s+", "", r[-1] or "")
            if not dm or dm.group(1) != str(SEASON_YEAR) or not home or not away:
                raise RuntimeError(f"T1の行が読めない: {r}")
            if score in ("-", ""):
                hs = as_ = None
            else:
                sm = _TOKUSHIMA_SCORE_RE.match(score)
                if not sm:
                    raise RuntimeError(f"スコアが読めない: No.{no} {score!r}")
                hs, as_ = int(sm.group(1)), int(sm.group(2))
                if sm.group(3) is None:
                    no_half.append(no)
                else:
                    h1, a1, h2, a2 = (int(x) for x in sm.group(3, 4, 5, 6))
                    if (h1 + h2, a1 + a2) != (hs, as_):
                        raise RuntimeError(f"前後半の和が合計と合わない: No.{no} {home} {score} {away}")
            matches.append(dict(md=0, date=f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}",
                                home=home, away=away, hs=hs, **{"as": as_}))

    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        raise RuntimeError(f"No. が 1〜{len(numbers)} で揃っていない（取りこぼし・重複の疑い）")
    n = cfg["teams"]
    if len(matches) != n * (n - 1):
        raise RuntimeError(f"T1が{len(matches)}試合（2回戦総当たりの{n * (n - 1)}と違う）")
    pairs = collections.Counter(frozenset((m["home"], m["away"])) for m in matches)
    if max(pairs.values()) > 2 or len(pairs) != n * (n - 1) // 2:
        raise RuntimeError(f"対戦の組が想定と違う（最大{max(pairs.values())}回・{len(pairs)}組）＝重複登録の疑い")
    if no_half:
        print(f"       （徳島: 前後半の記載が無く前後半検算をしていないT1の消化済み試合 {len(no_half)}件: "
              f"No.{','.join(no_half)}）")
    future = [m for m in matches if m["hs"] is not None and m["date"] > version]
    if future:
        raise RuntimeError(f"版日付({version})より後の日付を持つ消化済み試合が{len(future)}件"
                           f"（例: {future[0]['date']} {future[0]['home']} vs {future[0]['away']}）")
    return {}, matches


# ============================================================
# 青森（aomori-fa.jp）— 県協会の大会日程PDF（前期・後期）＋星取表PDF（2026-09-15追加）
#   入口: 2種カテゴリの記事一覧 → タイトルに「サッカーリーグ青森{年}」を含む記事 → 記事の表からPDF
# ⚠️ **記事タイトルもURLも更新・年度で変わる**（2025年度の記事と1文字違い）。記事URLは固定しない。
#    一覧はページ送りがあるので数ページ探す。タイトルの年がシーズン年でなければ使わない。
# ⚠️⚠️ **記事の表の「大会日程」行の各セル（前期・後期）にPDFリンクが2本ある。**
#    テキストリンク「前期」「後期」は4月版（古い）、隣の文字なしPDFアイコンが現行版。
#    → セルの全リンクから**ファイル名の版日付が最新のもの**を選ぶ（pdf_source.newest_by_label_version）。
#    ⚠️ フォルダの年月は使わない（0907版が /2026/08/ にある）。
# ⚠️⚠️ **日程PDFは表として読めない。** セルの背景の塗りつぶしの境目を pdfplumber が罫線と誤認し、
#    結合された月日セルを途中で切る（4/29 の最初の2試合に 4/25 が付いた）。
#    → 単語の座標で読む。月日・カテゴリーは**その列を横切る細い横線で区切ったブロック**の中の文字を、
#       同じブロックにある試合行に付ける（pdf_source.page_hrules）。
#    ⚠️ 節と月日が1語にくっつくことがある（「第１４節9月12日」）。月日は単語の中から探す。
# ⚠️ 1部と2部が同じPDFに交互に入る。カテゴリーのブロックで分け、1部が teams チーム・1部と2部が重ならないことを確認。
#    チーム名は完全一致で扱う（`三本木農業恵拓`／`三本木`／`三本木農業恵拓２ｎｄ` が共存）。
# ⚠️ 星取表は1部・2部が1ページ。表として読める。1部の表（左上が「１部リーグ」）の各行の
#    先頭＝略称、末尾4列＝勝点・得点・失点・得失点差。**勝分敗・試合数・順位は無い**
#    → 沖縄と同じ代替ゲート（勝点・得点・失点）。ヘッダのチーム名は縦書きなので使わない。
#    略称は半角カナを含む（`ｳﾞｧﾝﾗｰﾚU-18`）ので NFKC してから名寄せする。
# 年度切り替え: 記事はタイトルの年で探すので設定変更は不要。
# ============================================================
_AOMORI_ENTRY = "https://www.aomori-fa.jp/category/committee/all-committee/highschool/"
_AOMORI_MD_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")
_AOMORI_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
_AOMORI_SCORE_RE = re.compile(r"^(?:(\d+)-(\d+)|-)$")


def _aomori_article() -> str:
    year = str(SEASON_YEAR)
    for page in range(1, 4):
        url = _AOMORI_ENTRY if page == 1 else f"{_AOMORI_ENTRY}page/{page}/"
        soup = BeautifulSoup(fetch_html(url, encoding="utf-8"), "html.parser")
        time.sleep(SLEEP)
        for a in soup.find_all("a", href=True):
            title = re.sub(r"\s+", "", unicodedata.normalize("NFKC", a.get_text()))
            if "高円宮杯" in title and f"サッカーリーグ青森{year}" in title:
                return a["href"]
    raise RuntimeError(f"記事一覧に{year}年の「高円宮杯…サッカーリーグ青森{year}」の記事が無い")


def _aomori_blocks(page, words, head_word: str, pattern) -> list[tuple[float, float, str]]:
    """見出し head_word の列を横切る細い線で区切ったブロックごとに、その中で pattern に合う文字を返す"""
    hw = [w for w in words if re.sub(r"\s+", "", w["text"]) == head_word]
    if len(hw) != 1:
        raise RuntimeError(f"日程表の見出し「{head_word}」が{len(hw)}個")
    x0, x1 = hw[0]["x0"], hw[0]["x1"]
    ys = pdf_source.page_hrules(page, x0, x1)
    blocks = []
    for top, bottom in zip(ys, ys[1:]):
        hits = []
        for w in words:
            cy = (w["top"] + w["bottom"]) / 2
            if top < cy < bottom and w["x0"] < x1 + 8 and w["x1"] > x0 - 8:
                m = pattern.search(unicodedata.normalize("NFKC", w["text"]))
                if m:
                    hits.append(m.group(0))
        if len(hits) > 1:
            raise RuntimeError(f"「{head_word}」の1ブロックに候補が複数: {hits}")
        blocks.append((top, bottom, hits[0] if hits else ""))
    return blocks


def _aomori_schedule(content: bytes) -> list[dict]:
    out = []
    with pdf_source.open_pdf(content) as pdf:
        for page in pdf.pages:
            words = pdf_source.page_words(page)
            head = {re.sub(r"\s+", "", w["text"]): w for w in words}
            for k in ("キックオフ", "主"):
                if k not in head:
                    raise RuntimeError(f"日程表の見出し「{k}」が無い")
            days = _aomori_blocks(page, words, "月日", _AOMORI_MD_RE)
            cats = _aomori_blocks(page, words, "カテゴリー", re.compile(r"[12]部"))
            x_ko, x_end = head["キックオフ"]["x0"] - 8, head["主"]["x0"] - 4
            for t in [w for w in words if _AOMORI_TIME_RE.match(w["text"]) and x_ko <= w["x0"] < x_ko + 40]:
                cy = (t["top"] + t["bottom"]) / 2
                row = sorted([w for w in words if abs(w["top"] - t["top"]) <= 3
                              and t["x1"] < w["x0"] < x_end], key=lambda w: w["x0"])
                toks = [unicodedata.normalize("NFKC", w["text"]) for w in row]
                sc = [i for i, s in enumerate(toks) if _AOMORI_SCORE_RE.match(s)]
                if len(sc) != 1 or sc[0] == 0 or sc[0] == len(toks) - 1:
                    raise RuntimeError(f"日程の行が読めない: {t['text']} {toks}")
                day = next((d for top, bottom, d in days if top < cy < bottom), "")
                cat = next((c for top, bottom, c in cats if top < cy < bottom), "")
                dm = _AOMORI_MD_RE.search(day)
                if not dm or not cat:
                    raise RuntimeError(f"月日・カテゴリーを割り当てられない: {t['text']} {toks}")
                m = _AOMORI_SCORE_RE.match(toks[sc[0]])
                out.append(dict(cat=cat, md=0,
                                date=f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}",
                                home="".join(toks[:sc[0]]), away="".join(toks[sc[0] + 1:]),
                                hs=int(m.group(1)) if m.group(1) else None,
                                **{"as": int(m.group(2)) if m.group(2) else None}))
    return out


def read_aomori(cfg: dict) -> tuple[dict, list[dict]]:
    article = _aomori_article()
    soup = BeautifulSoup(fetch_html(article, encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    sched_cells = pdf_source.pdf_links_in_table_row(soup, lambda t: t == "大会日程")
    hoshi_cells = pdf_source.pdf_links_in_table_row(soup, lambda t: t.startswith("星取表") and "1部" in t)
    sched = [pdf_source.newest_by_label_version([u for _t, u in cell], SEASON_YEAR)
             for cell in sched_cells if cell]
    hoshi = [pdf_source.newest_by_label_version([u for _t, u in cell], SEASON_YEAR)
             for cell in hoshi_cells if cell]
    if len(sched) != 2 or len(hoshi) != 1:
        raise RuntimeError(f"日程PDFが{len(sched)}本（前期・後期の2本のはず）・星取表PDFが{len(hoshi)}本")

    rows = []
    for url, _v in sched:
        rows += _aomori_schedule(pdf_source.fetch_pdf(url, HEADERS, TIMEOUT, wait=SLEEP))
        time.sleep(SLEEP)
    one = [r for r in rows if r["cat"] == "1部"]
    t1 = {r["home"] for r in one} | {r["away"] for r in one}
    t2 = {r["home"] for r in rows if r["cat"] != "1部"} | {r["away"] for r in rows if r["cat"] != "1部"}
    n = cfg["teams"]
    if len(t1) != n or t1 & t2:
        raise RuntimeError(f"1部のチームが{len(t1)}（{n}のはず）／2部と重なるチーム {sorted(t1 & t2)}")
    if len(one) != n * (n - 1):
        raise RuntimeError(f"1部が{len(one)}試合（2回戦総当たりの{n * (n - 1)}と違う）")
    pairs = collections.Counter(frozenset((r["home"], r["away"])) for r in one)
    if max(pairs.values()) != 2 or len(pairs) != n * (n - 1) // 2:
        raise RuntimeError("1部の対戦の組が想定と違う（重複・欠落の疑い）")

    # --- 星取表（1部）：略称・勝点・得点・失点・得失点差 ---
    content = pdf_source.fetch_pdf(hoshi[0][0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    t_one = [t for t in tables if unicodedata.normalize("NFKC", re.sub(r"\s+", "", t[0][0] or "")) == "1部リーグ"]
    if len(t_one) != 1:
        raise RuntimeError(f"星取表に1部の表が{len(t_one)}個")
    standings = {}
    for r in t_one[0][1:]:
        name = unicodedata.normalize("NFKC", re.sub(r"\s+", "", r[0] or ""))
        vals = [(c or "").strip() for c in r[-4:]]
        if not name or not all(re.fullmatch(r"-?\d+", v) for v in vals):
            raise RuntimeError(f"星取表の1部の行が読めない: {r}")
        pts, gf, ga, gd = (int(v) for v in vals)
        if gf - ga != gd:
            raise RuntimeError(f"星取表 {name}: 得点{gf}−失点{ga}≠得失点差{gd}（読み取りの誤り）")
        standings[name] = dict(pts=pts, gf=gf, ga=ga)
    if len(standings) != n or sum(v["gf"] for v in standings.values()) != sum(v["ga"] for v in standings.values()):
        raise RuntimeError("星取表の1部が9チームでない、または得点計≠失点計")

    version = max(v for _u, v in sched)
    matches = [{k: v for k, v in r.items() if k != "cat"} for r in one]
    future = [m for m in matches if m["hs"] is not None and m["date"] > version]
    if future:
        raise RuntimeError(f"版日付({version})より後の日付を持つ消化済み試合が{len(future)}件"
                           f"（例: {future[0]['date']} {future[0]['home']} vs {future[0]['away']}）")
    return standings, matches


# ============================================================
# 長野（nagano-fa.or.jp）— 県協会の日程及び試合結果PDF＋星取表PDF（2026-09-15追加）
#   入口: /cat_2（2種 高校。年度非依存の固定URL）。「大会日程/大会結果」の箇条書きが部ごとに1項目。
# ⚠️ リンク文字（「日程・試合結果」「星取表」）は全部の部で同じ。**項目の先頭が「１部」の <li>** から取る
#    （`２部A` `４部北信地区A` などと紛れないよう先頭で判定）。
# ⚠️ URLは更新のたびに WordPress の連番（`2026_U18_1-9.pdf` の `-9`）が変わる。固定しない。
#    ファイル名に日付は無いので version_from_label は使わない。版日付は**星取表PDF本文の「2026/9/14 現在」**。
# ⚠️ 日程PDFは表として読める（罫線が明瞭で背景の塗りつぶしが無い。2026-09-15に画像で結合セルを確認し、
#    表の月日が既存データと1件を除き一致することで検算）。節・月日は結合セルで、表では先頭行に入る。
#    **1つの節が2日にまたがる**（第10節＝6/27 と 6/28 で月日セルが分かれている）ので、節ではなく月日を行ごとに引き継ぐ。
# ⚠️ 星取表は各チーム2行（対戦マスの前半・後半）。チーム名・順位・勝点…得失点は1行目にだけある。
#    テキスト抽出だと2チーム分の数値が交互に出るので、**表として読む**。列はヘッダ名で特定する。
#    ✅ 自己検算：勝+分+負＝試合数／3×勝+分＝勝点／得点−失点＝得失点（全チーム必須）。
# ✅ 星取表に勝点・試合数・勝分敗・得点・失点が揃っているので、**通常の検算ゲート（全項目一致）**。
# 年度切り替え: 入口は固定。PDFの見出し「…サッカーリーグ{年} 長野県1部」の年を必須にしているので、
#              前年度のPDFを読むと止まる。
# ============================================================
_NAGANO_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
_NAGANO_SCORE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def _nagano_head_ok(pdf) -> None:
    title = re.sub(r"\s+", "", unicodedata.normalize("NFKC", pdf.pages[0].extract_text() or ""))[:80]
    if f"サッカーリーグ{SEASON_YEAR}長野県1部" not in title:
        raise RuntimeError(f"PDFの見出しが「…サッカーリーグ{SEASON_YEAR} 長野県1部」でない: {title[:40]}")


def read_nagano(cfg: dict) -> tuple[dict, list[dict]]:
    soup = BeautifulSoup(fetch_html(cfg["entry"], encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    links = pdf_source.pdf_links_in_list_item(soup, lambda t: re.match(r"^1部(?![A-Za-z0-9])", t) is not None)
    sched = [u for t, u in links if t.startswith("日程")]
    hoshi = [u for t, u in links if t.startswith("星取表")]
    if len(sched) != 1 or len(hoshi) != 1:
        raise RuntimeError(f"1部の項目に日程PDFが{len(sched)}本・星取表PDFが{len(hoshi)}本（各1本のはず）")

    # --- 日程及び試合結果 ---
    content = pdf_source.fetch_pdf(sched[0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        _nagano_head_ok(pdf)
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    matches, day = [], ""
    for t in tables:
        hi = next((i for i, r in enumerate(t) if re.sub(r"\s+", "", r[0] or "") == "節"), None)
        if hi is None:
            raise RuntimeError("日程表に「節」のヘッダ行が無い")
        head = [re.sub(r"\s+", "", c or "") for c in t[hi]]
        if len(head) != 7 or head[2] != "時間" or head[3] != "組合せ" or head[6] != "会場":
            raise RuntimeError(f"日程表のヘッダが想定と違う: {head}")
        for r in t[hi + 1:]:
            dm = _NAGANO_DATE_RE.search(r[1] or "")
            if dm:
                day = f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
            home, score, away = (re.sub(r"\s+", "", r[3] or ""), (r[4] or "").strip(), re.sub(r"\s+", "", r[5] or ""))
            sm = _NAGANO_SCORE_RE.match(score)
            if not home or not away or (score != "-" and not sm) or not day:
                raise RuntimeError(f"日程の行が読めない: {r}")
            matches.append(dict(md=0, date=day, home=home, away=away,
                                hs=int(sm.group(1)) if sm else None,
                                **{"as": int(sm.group(2)) if sm else None},
                                venue=re.sub(r"\s+", "", r[6] or "")))

    # --- 星取表 ---
    content = pdf_source.fetch_pdf(hoshi[0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        _nagano_head_ok(pdf)
        version = pdf_source.version_date(pdf.pages[0].extract_text() or "")
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    if not version or not version.startswith(f"{SEASON_YEAR}-"):
        raise RuntimeError("星取表PDF本文の版日付が読めない")
    if len(tables) != 1:
        raise RuntimeError(f"星取表PDFの表が{len(tables)}個")
    head = [re.sub(r"\s+", "", c or "") for c in tables[0][0]]
    names = ("勝点", "試合数", "勝", "分", "負", "得点", "失点", "得失点")
    if not set(names) <= set(head) or head[0] != "順位":
        raise RuntimeError(f"星取表のヘッダが想定と違う: {head}")
    col = {k: head.index(k) for k in names}
    standings = {}
    for r in tables[0][1:]:
        name = re.sub(r"\s+", "", r[1] or "")
        if not name:
            continue                                      # 対戦マスの2行目
        v = {k: int((r[col[k]] or "").strip()) for k in names}
        if (v["勝"] + v["分"] + v["負"] != v["試合数"] or 3 * v["勝"] + v["分"] != v["勝点"]
                or v["得点"] - v["失点"] != v["得失点"]):
            raise RuntimeError(f"星取表の自己検算が合わない: {name} {v}")
        standings[name] = dict(pts=v["勝点"], played=v["試合数"], won=v["勝"], drawn=v["分"],
                               lost=v["負"], gf=v["得点"], ga=v["失点"])

    n = cfg["teams"]
    if len(matches) != n * (n - 1) or len(standings) != n:
        raise RuntimeError(f"日程が{len(matches)}試合・星取表が{len(standings)}チーム（{n * (n - 1)}試合・{n}チームのはず）")
    pairs = collections.Counter(frozenset((m["home"], m["away"])) for m in matches)
    if max(pairs.values()) != 2 or len(pairs) != n * (n - 1) // 2:
        raise RuntimeError("対戦の組が想定と違う（重複・欠落の疑い）")
    future = [m for m in matches if m["hs"] is not None and m["date"] > version]
    if future:
        raise RuntimeError(f"版日付({version})より後の日付を持つ消化済み試合が{len(future)}件"
                           f"（例: {future[0]['date']} {future[0]['home']} vs {future[0]['away']}）")
    return standings, matches


# ============================================================
# 福井（fukui-fa.com）— 県協会の節ごとの試合結果PDF（F1第N節結果）＋星取表PDF（F1リーグ）（2026-09-15追加）
#   入口: /author/high-school/（記事一覧）→ リンク文字「…リーグ{年}福井」→ 年度のリーグページ
# ⚠️⚠️ **なぜ「日程PDF＋星取表」の2本ではなく、節ごとの結果PDFを全部（13本前後）取るのか**
#    星取表のマスには**ホーム/アウェイも「どちらが1試合目か」も無い**（行チームから見たスコアだけ）。
#    日程PDFと組むには「マスの1行目＝日程上の1試合目」と仮定するしかなく、**延期で1試合目が
#    2試合目より後になると、日付だけでなく向きとスコアの割り当てまで静かに入れ替わる**。
#    勝点・得点・失点は変わらないので検算では絶対に捕まらない（2026-09-15に48/48で仮定が成り立つことは
#    確認したが、それは延期がまだ無いからにすぎない）。
#    節ごとの結果PDFには**ホーム・スコア・前後半・アウェイ・実際の日付**が明記されている。
#    → **「2本で足りるのに無駄」と思って減らさないこと。**
# ⚠️ 1本でも取れなければ全体を止める。理由は「構造が変わった疑い（リンクが無い等）」と
#    「一時的な取得失敗の疑い（リトライ後も失敗）」を分けてメッセージに出す。
# ⚠️ 節ごとPDFは1ページに1試合1表（最大4表）。表の1行目＝[ホーム(＋勝点), -, ホーム得点, 前半/後半, アウェイ得点, アウェイ(＋勝点)]。
#    チーム名は改行の前（1行目）だけ。数字で区切ると「丸岡2nd」が「丸岡」になる。
#    日付は**表の上にある見出し「第12節 9月12日(土)」**（同じ列で一番近いもの）から取る。
#    ✅ 前後半の和＝合計を全試合で検算する（徳島と同じ）。
# ⚠️ 星取表（F1リーグ）は勝点・得点・失点・得失差・順位だけ（勝分敗・試合数なし）→ 沖縄と同じ代替ゲート。
#    ✅ **節ごとPDFの試合の集合（向きなし）＝星取表のマスの集合**を照合する（出典をまたいだ検算）。
# ⚠️ 得点ランキングPDF（fetch_pdf_scorers.py）は漢字がCJK互換部首で出るが、この2種類では出なかった
#    （2026-09-15確認）。念のため同じ正規化（_fix: 部首置換＋NFKC）を通す。
# 年度切り替え: 記事一覧のリンク文字の年で辿るので設定変更は不要。
# ============================================================
_FUKUI_LIST = "https://www.fukui-fa.com/author/high-school/"
_FUKUI_ROUND_RE = re.compile(r"^F1第(\d+)節結果$")
_FUKUI_MD_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")
_FUKUI_HALF_RE = re.compile(r"(\d+)\s*-\s*(\d+)")
_FUKUI_CELL_RE = re.compile(r"(\d+)\s*[○●△]\s*(\d+)")


def _fukui_fix(s: str) -> str:
    from fetch_pdf_scorers import _fix      # CJK互換部首の置換＋NFKC（得点ランキングと同じ正規化）
    return re.sub(r"\s+", "", _fix(s or ""))


def _fukui_fetch(url: str, what: str) -> bytes:
    try:
        return pdf_source.fetch_pdf(url, HEADERS, TIMEOUT, wait=SLEEP)
    except Exception as e:
        raise RuntimeError(f"一時的な取得失敗の疑い（{what}・リトライ後も失敗）: {e}")


def _fukui_round(content: bytes, md: int) -> list[dict]:
    out = []
    with pdf_source.open_pdf(content) as pdf:
        for page in pdf.pages:
            words = pdf_source.page_words(page)
            heads = [(w, _FUKUI_MD_RE.search(_fukui_fix(w["text"]))) for w in words]
            heads = [(w, m) for w, m in heads if m]
            secs = [(w, re.search(r"第(\d+)節", _fukui_fix(w["text"]))) for w in words]
            secs = [(w, m) for w, m in secs if m]
            for tb in page.find_tables():
                r0 = tb.extract()[0]
                if len(r0) != 6:
                    raise RuntimeError(f"構造が変わった疑い（第{md}節PDFの表の列数が{len(r0)}）")
                col_above = lambda cands: [(tb.bbox[1] - w["bottom"], m) for w, m in cands
                                           if w["bottom"] <= tb.bbox[1] + 1 and w["x0"] < tb.bbox[2] and w["x1"] > tb.bbox[0]]
                above, sec = col_above(heads), col_above(secs)
                if not above or not sec:
                    raise RuntimeError(f"構造が変わった疑い（第{md}節PDFの表の上に「第N節 M月D日」の見出しが無い）")
                dm = min(above, key=lambda x: x[0])[1]
                # ✅ 見出しの節番号＝リンクの節番号（日付を別の見出しと取り違えたら止める）
                if int(min(sec, key=lambda x: x[0])[1].group(1)) != md:
                    raise RuntimeError(f"第{md}節PDFの表の見出しの節番号が{min(sec, key=lambda x: x[0])[1].group(1)}（日付の割り当てが壊れた疑い）")
                home = _fukui_fix((r0[0] or "").split("\n")[0])
                away = _fukui_fix((r0[5] or "").split("\n")[0])
                hs, as_ = _fukui_fix(r0[2]), _fukui_fix(r0[4])
                halves = _FUKUI_HALF_RE.findall(r0[3] or "")
                if not (home and away and hs.isdigit() and as_.isdigit() and len(halves) == 2):
                    raise RuntimeError(f"構造が変わった疑い（第{md}節PDFの行が読めない: {r0}）")
                hs, as_ = int(hs), int(as_)
                if (sum(int(a) for a, _b in halves), sum(int(b) for _a, b in halves)) != (hs, as_):
                    raise RuntimeError(f"前後半の和が合計と合わない: 第{md}節 {home} {hs}-{as_} {away} {halves}")
                out.append(dict(md=md, date=f"{SEASON_YEAR}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}",
                                home=home, away=away, hs=hs, **{"as": as_}))
    return out


def read_fukui(cfg: dict) -> tuple[dict, list[dict]]:
    year = str(SEASON_YEAR)
    soup = BeautifulSoup(fetch_html(_FUKUI_LIST, encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    pages = [a["href"] for a in soup.find_all("a", href=True) if f"リーグ{year}福井" in _fukui_fix(a.get_text())]
    if not pages:
        raise RuntimeError(f"構造が変わった疑い（記事一覧に「リーグ{year}福井」のリンクが無い）")
    soup = BeautifulSoup(fetch_html(pages[0], encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)

    fixed = lambda t: _fukui_fix(t)
    result_url = pdf_source.pdf_link_by_text(soup, lambda t: fixed(t) == "F1リーグ(pdf)", "F1リーグ(pdf)（星取表）")
    rounds = sorted((int(_FUKUI_ROUND_RE.match(fixed(t)).group(1)), u)
                    for t, u in pdf_source.pdf_links_all_by_text(soup, lambda t: bool(_FUKUI_ROUND_RE.match(fixed(t)))))
    nums = [md for md, _u in rounds]
    if not nums or nums != list(range(1, len(nums) + 1)):
        raise RuntimeError(f"構造が変わった疑い（F1第N節結果のリンクが1から連番でない: {nums}）")

    matches = []
    for md, url in rounds:
        matches += _fukui_round(_fukui_fetch(url, f"第{md}節PDF"), md)
        time.sleep(SLEEP)
    n = cfg["teams"]
    if len(matches) != len(nums) * (n // 2):
        raise RuntimeError(f"節ごとPDFの試合数が{len(matches)}（{len(nums)}節×{n // 2}のはず）")

    # --- 星取表（F1リーグ）：勝点・得点・失点・得失差・順位 と、マスの試合 ---
    content = _fukui_fetch(result_url, "星取表PDF")
    with pdf_source.open_pdf(content) as pdf:
        title = _fukui_fix((pdf.pages[0].extract_text() or "")[:60])
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    if f"サッカーリーグ{year}福井" not in title or len(tables) != 1:
        raise RuntimeError(f"構造が変わった疑い（星取表PDFの見出しが{year}年でない、または表が{len(tables)}個）")
    head = [_fukui_fix(c) for c in tables[0][0]]
    if head[0] != "チーム名" or not {"勝点", "得点", "失点", "得失差"} <= set(head):
        raise RuntimeError(f"構造が変わった疑い（星取表のヘッダ: {head}）")
    teams = [re.sub(r"^\d+", "", h) for h in head[1:1 + n]]
    col = {k: head.index(k) for k in ("勝点", "得点", "失点", "得失差")}
    standings, cells = {}, collections.Counter()
    for r in tables[0][1:]:
        me = re.sub(r"^\d+", "", _fukui_fix(r[0]))
        v = {k: int(_fukui_fix(r[c])) for k, c in col.items()}
        if v["得点"] - v["失点"] != v["得失差"]:
            raise RuntimeError(f"星取表 {me}: 得点−失点≠得失差（読み取りの誤り）")
        standings[me] = dict(pts=v["勝点"], gf=v["得点"], ga=v["失点"])
        for j, opp in enumerate(teams):
            for a, b in _FUKUI_CELL_RE.findall(unicodedata.normalize("NFKC", r[1 + j] or "")):
                cells[(me, opp, int(a), int(b))] += 1
    if set(standings) != set(teams) or len(teams) != n:
        raise RuntimeError("構造が変わった疑い（星取表の行と列のチームが合わない）")
    # ✅ 出典をまたいだ照合：節ごとPDFの試合（両チームの目線）＝星取表のマス
    mine = collections.Counter()
    for m in matches:
        mine[(m["home"], m["away"], m["hs"], m["as"])] += 1
        mine[(m["away"], m["home"], m["as"], m["hs"])] += 1
    if mine != cells:
        raise RuntimeError(f"節ごとPDFの試合と星取表のマスが合わない（節PDFのみ {sorted((mine - cells).elements())[:2]}・"
                           f"星取表のみ {sorted((cells - mine).elements())[:2]}）")
    today = _jst_today().isoformat()
    future = [m for m in matches if m["date"] > today]
    if future:
        raise RuntimeError(f"今日({today})より後の日付を持つ消化済み試合が{len(future)}件（日付の割り当てが壊れた疑い）")
    return standings, matches


# ============================================================
# 山梨（yamanashi-football.com）— 県協会の星取表PDF（結果：１部）＋通し日程PDF（日程：１・２・３部）（2026-09-15追加）
#   入口: /pages/75/（各種大会情報）。リンク文字（全角）が「１部」「１・２・３部」の完全一致。
#   ⚠️ 「４部」は日程と結果の両方にあるので、同じ書き方を他の部に流用しないこと。
# ⚠️⚠️ **星取表にホーム/アウェイも日付も無い**（福井で退けた「案1」と同じ形）。山梨には節ごとの結果資料が
#    無いので、**節の順番で数えた「そのペアの何回目か」→ 星取表の上段（1巡目）／下段（2巡目）**で割り当てる。
#    星取表が「日付順」ではなく「巡目」で書かれているなら延期しても崩れないが、2026-09-15時点は延期が無く未確認。
#    → 巡目の前提が崩れた形を検出したら止める（下の守り①②）＋ 版日付までの予定数と結果数の差をログに出す（③）。
#    延期が起きたら、VF甲府Bのクラブ公式（https://www.ventforet.jp/academy/U-18?year=年）の日付・相手で
#    1チームぶん実物を確かめられる（自動取得には入れない：ホーム/アウェイの列が無く、協会より更新が遅れる）。
# ⚠️ **向き（ホーム/アウェイ）は格納規約（日程PDFの左側＝home）で、事実ではない。** 会場を数えると左のチームの会場29・
#    右のチームの会場17で、左＝ホームとは言えない（2026-09-15）→ cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。
#    📌 1巡目と2巡目で左右が入れ替わっていても、総当たりの日程を機械的に組めば自然にそうなるので、ホーム/アウェイの証拠にはならない。
#    日付は日程PDF（4/9版の予定）だが、VF甲府Bの8節ぶんがクラブ公式の実際の日付と一致した（2026-09-15）。
# ⚠️⚠️ **「1節＝1日」と仮定しない。** 第1〜4節は2日に分かれている（第4節＝4/25×3・4/26×1）。
#    日付は1試合ごとに日程表の行から取る（表として読むと月日は結合ブロックの先頭行に入り、行ごとに引き継げる）。
# ⚠️ 日程PDFは1〜3部の通し。「リーグ」列が `1` の行だけを使う。
# ⚠️ 星取表は「東海甲府」、日程PDFと既存JSONは「東海大甲府」。星取表側だけ読み替える。
# ✅ 星取表の鏡チェック（A行B列とB行A列が逆向きで一致）→ 沖縄と同じ代替ゲート（勝点・得点・失点）。
# ✅ 版日付＝星取表PDF本文の `2026/9/13`。表題の年（「2026山梨県ユースリーグ 1部リーグ 星取表」）も必須。
# ❌ 山梨県高体連サイトの `123部日程.pdf` は中身が駐車場案内図（2026-09-15）。使わない。
# 年度切り替え: 入口は固定。表題の年で前年度のPDFを読む事故を止める。
# ============================================================
_YAMANASHI_SCORE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")


def read_yamanashi(cfg: dict) -> tuple[dict, list[dict]]:
    year = str(SEASON_YEAR)
    nfkc = lambda s: re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))
    soup = BeautifulSoup(fetch_html(cfg["entry"], encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    result_url = pdf_source.pdf_link_by_text(soup, lambda t: t == "１部", "結果「１部」")
    sched_url = pdf_source.pdf_link_by_text(soup, lambda t: t == "１・２・３部", "日程「１・２・３部」")

    # --- 星取表 ---
    content = pdf_source.fetch_pdf(result_url, HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        text = pdf.pages[0].extract_text() or ""
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    version = pdf_source.version_date(text)
    if f"{year}山梨県ユースリーグ1部リーグ星取表" not in nfkc(text) or not version or not version.startswith(f"{year}-"):
        raise RuntimeError(f"星取表PDFの表題または版日付が{year}年でない（前年度のPDFの疑い）")
    if len(tables) != 1:
        raise RuntimeError(f"星取表PDFの表が{len(tables)}個")
    rename = cfg.get("hoshitori_names", {})
    head = [nfkc(c) for c in tables[0][0]]
    n = cfg["teams"]
    teams = [rename.get(h, h) for h in head[1:1 + n]]
    if head[1 + n:1 + n + 4] != ["勝点", "得点", "失点", "得失点差"]:
        raise RuntimeError(f"星取表のヘッダが想定と違う: {head}")
    standings, cells = {}, {}
    for r in tables[0][1:]:
        me = rename.get(nfkc(r[0]), nfkc(r[0]))
        pts, gf, ga, gd = (int(nfkc(x)) for x in r[1 + n:1 + n + 4])
        if gf - ga != gd:
            raise RuntimeError(f"星取表 {me}: 得点−失点≠得失点差（読み取りの誤り）")
        standings[me] = dict(pts=pts, gf=gf, ga=ga)
        for j, opp in enumerate(teams):
            if opp == me:
                continue
            segs = unicodedata.normalize("NFKC", r[1 + j] or "").split("\n")
            legs = []
            for seg in segs[:2]:
                m = _YAMANASHI_SCORE_RE.search(seg)
                legs.append((int(m.group(1)), int(m.group(2))) if m else None)
            legs += [None] * (2 - len(legs))
            # 守り①：上段が空なのに下段にだけ結果がある＝巡目の前提が崩れた
            if legs[0] is None and legs[1] is not None:
                raise RuntimeError(f"星取表 {me}×{opp}: 上段が空なのに下段に結果がある（巡目の前提が崩れた疑い）")
            cells[(me, opp)] = legs
    if set(standings) != set(teams) or len(teams) != n:
        raise RuntimeError("星取表の行と列のチームが合わない")
    for (a, b), legs in cells.items():            # ✅ 鏡チェック
        if [None if x is None else (x[1], x[0]) for x in legs] != cells[(b, a)]:
            raise RuntimeError(f"星取表の鏡チェックが合わない: {a}×{b} {legs} / {b}×{a} {cells[(b, a)]}")

    # --- 通し日程（1部） ---
    content = pdf_source.fetch_pdf(sched_url, HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        if f"{year}山梨" not in nfkc(pdf.pages[0].extract_text() or "")[:60]:
            raise RuntimeError(f"日程PDFの表題が{year}年でない")
        rows = [r for pg in pdf.pages for t in pdf_source.page_tables(pg) for r in t]
    sched, md, day = [], None, ""
    for r in rows:
        if len(r) != 7 or nfkc(r[1]) == "日時":
            continue
        mm = re.search(r"第(\d+)節", nfkc(r[0]))
        if mm:
            md = int(mm.group(1))
        dm = re.search(r"(\d{1,2})月(\d{1,2})日", nfkc(r[1]))
        if dm:
            day = f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
        if nfkc(r[3]) != "1":
            continue
        home, away = nfkc(r[4]), nfkc(r[5])
        if not (home in standings and away in standings and md and day):
            raise RuntimeError(f"日程の1部の行が読めない: {r}")
        sched.append(dict(md=md, date=day, home=home, away=away))
    if len(sched) != n * (n - 1) or [s["md"] for s in sched] != sorted(s["md"] for s in sched):
        raise RuntimeError(f"日程の1部が{len(sched)}試合、または節の順に並んでいない")

    # --- 割り当て：そのペアの何回目か（節の順）→ 上段／下段 ---
    count, matches = collections.Counter(), []
    for s in sched:
        k = frozenset((s["home"], s["away"]))
        i = count[k]
        count[k] += 1
        if i > 1:
            raise RuntimeError(f"日程に {s['home']}×{s['away']} が3回以上ある")
        leg = cells[(s["home"], s["away"])][i]
        # 守り②：日程上の2試合目に結果があるのに1試合目が空（①と同じ形を試合の側から確かめる）
        if i == 1 and leg is not None and cells[(s["home"], s["away"])][0] is None:
            raise RuntimeError(f"{s['home']}×{s['away']}: 2試合目に結果があるのに1試合目が空（巡目の前提が崩れた疑い）")
        matches.append(dict(md=s["md"], date=s["date"], home=s["home"], away=s["away"],
                            hs=leg[0] if leg else None, **{"as": leg[1] if leg else None}))
    played = [m for m in matches if m["hs"] is not None]
    # 守り③：版日付までに行われているはずの試合数と、星取表の結果数の差をログに出す（止めない）
    due = sum(1 for s in sched if s["date"] <= version)
    if due != len(played):
        print(f"       （山梨: 版日付{version}までの予定{due}試合に対し、星取表の結果は{len(played)}試合"
              f"＝{due - len(played):+d}。延期または星取表の更新遅れの可能性）")
    future = [m for m in played if m["date"] > version]
    if future:
        examples = ", ".join("{} {}×{}".format(m["date"], m["home"], m["away"]) for m in future[:3])
        print(f"       （山梨: 版日付{version}より後の予定日に結果がある試合 {len(future)}件：{examples}。"
              f"予定より前倒しで行われた可能性）")
    # ✅ 守り（2026-09-17）：巡目を「そのペアの何回目か」で決めているので、同じペアの2試合が入れ替わると
    #    順位表は変わらず検算をすり抜ける。前回の保存内容と突き合わせて入れ替わりだけを捕まえる。
    check_legs_not_swapped(cfg["pref"], matches)
    return standings, matches


# ============================================================
# 岐阜（gifu-fa.com）— 県協会の戦績表PDF（第N節結果の記事）＋日程表PDF（2026-09-15追加）
#   入口: /type2-category/g1/（2種 G1 の記事一覧）。❌ /highschool/ は2026-07-03で凍結した旧サイト。
# ⚠️ 記事の題名で新しさを判断しない（「最新版」の日程がいちばん古い）。
#    戦績表＝題名「{年} G1 第N節結果」のNが最大の記事、日程表＝題名に「G1」「日程」を含む記事のうち
#    **記事の公開日時（<time datetime>）が最新**のもの。
# ⚠️⚠️ **公式にホーム/アウェイは無い。** 日程表はチーム番号の昇順に並べているだけ（降順の行0件・セントラル開催）。
#    → **格納規約**：1巡目（第1〜9節）は番号の小さい側を home、2巡目（第10〜18節）は大きい側を home。
#       これは事実の主張ではなく、90マスを一意に埋めるための約束。**「向きが逆だ」と直さないこと。**
#       表示では cross_table.NO_HOME_AWAY_SLUGS に入れて H/A を出さない。
# ⚠️ 戦績表の各マスは上段＝1巡目・下段＝2巡目。表として読むと2試合が1つの文字列につながり、
#    1試合だけのマスが上段か下段か分からない → **数字の縦位置（マスの中央より上か下か）で分ける**。
#    1巡目・2巡目の中では同じ組が1回ずつなので、「第1〜9節の試合＝上段、第10〜18節＝下段」で一意に結べる
#    （延期で日付の順が前後しても崩れない）。
# ⚠️ 日程表は表として読める（2026-09-15に画像と照合：90行・各節5試合・巡目ごとに45組）。末尾に振替ブロック
#    （12/5 第16節・第13節、6/20 第11節）があり、節も日付も時系列順ではない。月日は行ごとに引き継ぐ。
#    G1の行＝両側にチーム番号がある行（B/Cチームの試合は番号が無い）。`#N/A` などの行も番号が無いので外れる。
# ✅ 戦績表に勝・分・負・勝点・得点・失点がそろう → 通常の検算ゲート（全項目一致）。鏡チェックを先に行う。
# 年度切り替え: 題名の年で絞るので設定変更は不要。
# ============================================================
_GIFU_LIST = "https://www.gifu-fa.com/type2-category/g1/"


def _gifu_article(url: str):
    soup = BeautifulSoup(fetch_html(url, encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    t = soup.find("time", attrs={"datetime": True})
    return soup, (t["datetime"] if t else "")


def read_gifu(cfg: dict) -> tuple[dict, list[dict]]:
    year = str(SEASON_YEAR)
    nfkc = lambda s: re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))
    soup = BeautifulSoup(fetch_html(_GIFU_LIST, encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    results, schedules = [], []
    for a in soup.find_all("a", href=True):
        title = nfkc(a.get_text())
        if not title.startswith(f"{year}G1"):
            continue
        m = re.search(r"第(\d+)節結果", title)
        if m:
            results.append((int(m.group(1)), a["href"]))
        elif "日程" in title:
            schedules.append(a["href"])
    results, schedules = sorted(set(results)), list(dict.fromkeys(schedules))
    if not results or not schedules:
        raise RuntimeError(f"記事一覧に{year} G1 の結果記事（{len(results)}件）・日程記事（{len(schedules)}件）が無い")

    # --- 戦績表（節番号が最大の結果記事） ---
    n_md, res_url = results[-1]
    art, res_published = _gifu_article(res_url)
    if not re.match(r"\d{4}-\d{2}-\d{2}", res_published or ""):
        raise RuntimeError("戦績表の記事の公開日時が読めない")
    pdf_url = pdf_source.pdf_link_by_text(art, lambda t: f"({n_md}節終了)" in nfkc(t) and "戦績表" in t,
                                          f"戦績表({n_md}節終了)")
    content = pdf_source.fetch_pdf(pdf_url, HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        page = pdf.pages[0]
        tbs = page.find_tables()
        if len(tbs) != 1:
            raise RuntimeError(f"戦績表PDFの表が{len(tbs)}個")
        tb, words = tbs[0], pdf_source.page_words(page)
        data = tb.extract()
        head = [nfkc(c) for c in data[0]]
        n = cfg["teams"]
        want = ["勝数", "分数", "負数", "勝点", "得点", "失点", "得失点差", "順位"]
        if head[1 + n:] != want:
            raise RuntimeError(f"戦績表のヘッダが想定と違う: {head[1 + n:]}")
        rename = cfg.get("hoshitori_names", {})
        order, standings, legs = [], {}, {}
        team_rows = [i for i, r in enumerate(data) if i > 0 and nfkc(r[0])]
        for i in team_rows:
            order.append(rename.get(nfkc(data[i][0]), nfkc(data[i][0])))
        if len(order) != n:
            raise RuntimeError(f"戦績表のチームが{len(order)}（{n}のはず）")
        # ⚠️ 表の行の区切りは崩れている（2物理行目が別の行になる列がある）。マス単位の高さは使わず、
        #    縦＝「そのチームの行の上端〜次のチームの行の上端」、横＝見出し行の列 で範囲を決める。
        cols = tb.rows[0].cells[1:1 + n]
        if any(c is None for c in cols):
            raise RuntimeError("戦績表の見出し行の列が取れない")
        tops = [tb.rows[i].bbox[1] for i in team_rows] + [tb.bbox[3]]
        for k, (i, me) in enumerate(zip(team_rows, order)):
            v = dict(zip(want, (int(nfkc(data[i][1 + n + kk])) for kk in range(len(want)))))
            count = 0
            for j, opp in enumerate(order):
                if opp == me:
                    continue
                x0, x1 = cols[j][0], cols[j][2]
                top, bottom = tops[k], tops[k + 1]
                mid = (top + bottom) / 2
                nums = [w for w in words if x0 <= w["x0"] < x1 and top <= w["top"] < bottom
                        and re.fullmatch(r"\d+", w["text"])]
                pair = []
                for upper in (True, False):
                    ns = sorted((w for w in nums if (w["top"] < mid) == upper), key=lambda w: w["x0"])
                    if len(ns) not in (0, 2):
                        raise RuntimeError(f"戦績表 {me}×{opp} の{'上' if upper else '下'}段が読めない")
                    pair.append((int(ns[0]["text"]), int(ns[1]["text"])) if ns else None)
                legs[(me, opp)] = pair
                count += sum(1 for x in pair if x)
            if v["勝数"] + v["分数"] + v["負数"] != count or 3 * v["勝数"] + v["分数"] != v["勝点"] \
                    or v["得点"] - v["失点"] != v["得失点差"]:
                raise RuntimeError(f"戦績表 {me} の自己検算が合わない（マスの試合数{count}・{v}）")
            standings[me] = dict(pts=v["勝点"], played=count, won=v["勝数"], drawn=v["分数"],
                                 lost=v["負数"], gf=v["得点"], ga=v["失点"])
    for (a, b), pr in legs.items():                  # ✅ 鏡チェック
        if [None if x is None else (x[1], x[0]) for x in pr] != legs[(b, a)]:
            raise RuntimeError(f"戦績表の鏡チェックが合わない: {a}×{b} {pr} / {b}×{a} {legs[(b, a)]}")

    # --- 日程表（公開日時が最新の日程記事） ---
    dated = []
    for u in schedules:
        art, dt = _gifu_article(u)
        links = pdf_source.pdf_links_all_by_text(art, lambda t: "日程" in t)
        if links:
            dated.append((dt, links))
    if not dated or not dated[0][0]:
        raise RuntimeError("日程記事に日程表PDFが無い、または公開日時が読めない")
    dated.sort(key=lambda x: x[0])
    if len(dated[-1][1]) != 1:
        raise RuntimeError(f"最新の日程記事に日程表PDFが{len(dated[-1][1])}本")
    content = pdf_source.fetch_pdf(dated[-1][1][0][1], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        rows = [r for pg in pdf.pages for t in pdf_source.page_tables(pg) for r in t]
    sched, md, day, numbered = [], None, "", {}
    for r in rows:
        if len(r) != 9:
            continue
        mm = re.search(r"第(\d+)節", nfkc(r[0]))
        if mm:
            md = int(mm.group(1))
        dm = re.search(r"(\d{1,2})/(\d{1,2})", nfkc(r[1]))
        if dm:
            day = f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
        if not (nfkc(r[2]).isdigit() and nfkc(r[5]).isdigit()):
            continue
        hn, an = int(nfkc(r[2])), int(nfkc(r[5]))
        for num, name in ((hn, nfkc(r[3])), (an, nfkc(r[6]))):
            if numbered.setdefault(num, name) != name:
                raise RuntimeError(f"日程表のチーム番号{num}の名前が行によって違う")
        if hn >= an or not md or not day:
            raise RuntimeError(f"日程表のG1の行が想定と違う（番号の昇順でない、または節・日付なし）: {r}")
        sched.append(dict(md=md, date=day, lo=hn, hi=an))
    if sorted(numbered) != list(range(1, n + 1)) or [numbered[k] for k in range(1, n + 1)] != order:
        raise RuntimeError(f"日程表のチーム番号と戦績表の並びが合わない: {numbered} / {order}")
    if len(sched) != n * (n - 1) or any(sum(1 for s in sched if s["md"] == k) != n // 2 for k in range(1, 2 * (n - 1) + 1)):
        raise RuntimeError(f"日程表のG1が{len(sched)}試合、または節ごとの試合数が{n // 2}でない")
    half = n - 1
    for rnd in (1, 2):
        ps = [frozenset((s["lo"], s["hi"])) for s in sched if (s["md"] <= half) == (rnd == 1)]
        if len(set(ps)) != len(ps) or len(ps) != n * (n - 1) // 2:
            raise RuntimeError(f"日程表の{rnd}巡目に同じ組が重複または欠落")

    # ✅ 上段・下段の件数の期待値チェック（2026-09-15 Kei追加）
    #    「第N節結果」の N と日程表から、各チームの上段（1巡目）・下段（2巡目）の件数の期待値を出し、
    #    戦績表から読んだ件数と違えば止める。1巡目の試合が延期されて下段だけ埋まった／上下段の判定が崩れた、
    #    を取り違える前に捕まえる。
    #    期待値に数えるのは「第N節以内」かつ「日程表の日付が戦績表の記事の公開日以前」の試合。
    #    日程表に載っている振替（例：第13節 FC岐阜×岐阜工業＝12/5）は日付で自然に外れるので、止まり続けない。
    cutoff = res_published[:10]
    for team_no, team in numbered.items():
        exp = [0, 0]
        for s in sched:
            if team_no in (s["lo"], s["hi"]) and s["md"] <= n_md and s["date"] <= cutoff:
                exp[0 if s["md"] <= half else 1] += 1
        got = [sum(1 for opp in order if opp != team and legs[(team, opp)][k]) for k in (0, 1)]
        if got != exp:
            raise RuntimeError(f"戦績表 {team} の上段・下段の件数 {got} が、日程表から見込んだ {exp}"
                               f"（第{n_md}節まで・{cutoff}以前）と違う（延期または上下段の判定崩れの疑い）")

    # --- 格納規約で試合を作る（1巡目＝番号の小さい側が home／2巡目＝大きい側が home） ---
    matches = []
    for s in sched:
        rnd = 0 if s["md"] <= half else 1
        lo, hi = numbered[s["lo"]], numbered[s["hi"]]
        home, away = (lo, hi) if rnd == 0 else (hi, lo)
        leg = legs[(home, away)][rnd]
        matches.append(dict(md=s["md"], date=s["date"], home=home, away=away,
                            hs=leg[0] if leg else None, **{"as": leg[1] if leg else None}))
    today = _jst_today().isoformat()
    future = [m for m in matches if m["hs"] is not None and m["date"] > today]
    if future:
        raise RuntimeError(f"今日({today})より後の予定日に結果がある試合が{len(future)}件（例: {future[0]['date']} "
                           f"{future[0]['home']}×{future[0]['away']}）")
    return standings, matches


# ============================================================
# 大阪（ofa-tec.jp のCGI＋osaka-fa.or.jp のPDF）— 星取表CGI（スコア）＋1部試合日程表PDF（節・日付）（2026-09-17追加）
#   入口: osaka-fa.or.jp/2shu/game_information/ →「高円宮杯JFA U-18サッカーリーグ{年} OSAKA」の記事。
#   記事の中で **見出し「1部リーグ」の直後**に「試合予定」（PDF）と「試合結果」（CGI）が並ぶ。
#   ⚠️ CGIの `tsl=` は部ごとの番号で年度が変わると変わる（170=1部・171=2部…）。**決め打ちしない。**
# ⚠️⚠️ CGIは **http でしか繋がらず、文字コードは Shift_JIS**（沖縄・宮崎と同じ作法）。
# ⚠️ 星取表の1つのマスに2試合が `<br>` で並ぶ。**`<br>` で割ること**（テキストをまとめて正規表現でなめると
#    `2○1` と `3○2` が `2○13` `○2` に割れる）。
# ⚠️⚠️ **この県の弱点：星取表に節も日付も無く、日程表にはスコアが無い。**
#    どちらのマスがどちらの節かは**並び順の規約（1件目＝前期・2件目＝後期）**で決めるしかない。
#    2026-09-17に既存データ（junior-soccer）と突き合わせて **18/20 が前期先**（逆順なら2/20）と確認した。
#    ⚠️ 残る2件（近大附属×アサンプション）は結果の集合が同じで日付だけ入れ替わっており、**検算では決まらない**。
#       公式の並び順を採っているが、**規約に頼って決めた1件**であることを忘れないこと。
#    ✅ 守り：マスの件数が「そのペアの、予定日をすでに過ぎた試合数」を超えたら止める
#       （＝結果があるのに予定日が来ていない。前期が未消化で後期だけ消化した場合に前期と誤読するのを防ぐ）。
# ⭐️ ページ冒頭に出典自身が数えた消化数（`１部リーグ（54/90 試合消化）`）と版日付が出る。**どちらも検算に使う。**
# ⚠️ ホーム/アウェイは出さない。**①ホーム試合数は10チームともH9/A9・③両巡とも同じ側は45ペア中0**と
#    「いちばん白く見える」形だが、**②会場の持ち主が否定する**（学校名の会場63試合で 左15・右20・無関係28）。
#    ＝①③は根拠にならないことの実例。cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。
# ⚠️ 名寄せは日程PDF側にNFKC（半角カナ）を当てるだけ。⚠️ NFKCはチーム名にだけ当てる。
# 年度切り替え: 記事の見出しと `tsl` をページから取るので設定変更は不要。
# ============================================================
_OSAKA_LIST = "https://osaka-fa.or.jp/2shu/game_information/"
_OSAKA_CELL_RE = re.compile(r"(\d+)([○●△])(\d+)")


def _osaka_links(year: str) -> tuple[str, str]:
    """記事の「1部リーグ」の見出しの直後にある (日程PDF, 星取表CGI) を返す。"""
    from urllib.parse import urljoin
    from bs4 import NavigableString
    nfkc = lambda s: re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", s or ""))
    soup = BeautifulSoup(fetch_html(_OSAKA_LIST, encoding=None), "html.parser")
    time.sleep(SLEEP)
    arts = [urljoin(_OSAKA_LIST, a["href"]) for a in soup.find_all("a", href=True)
            if f"U-18サッカーリーグ{year}OSAKA" in nfkc(a.get_text()) and "game_information" in a["href"]]
    if len(dict.fromkeys(arts)) != 1:
        raise RuntimeError(f"入口に{year}年OSAKAの記事が{len(dict.fromkeys(arts))}件（1件のはず）")
    art_url = list(dict.fromkeys(arts))[0]
    art = BeautifulSoup(fetch_html(art_url, encoding=None), "html.parser")
    time.sleep(SLEEP)
    sect, pdf, cgi = None, None, None
    for node in art.descendants:
        if isinstance(node, NavigableString):
            t = nfkc(str(node))
            if re.match(r"[1-4]部リーグ", t):
                sect = t[:1]
        elif getattr(node, "name", "") == "a" and node.get("href"):
            href, label = node["href"], nfkc(node.get_text())
            if sect != "1":
                continue
            if label == "試合予定" and href.lower().endswith(".pdf") and pdf is None:
                pdf = urljoin(art_url, href)
            elif label == "試合結果" and "gmresult.cgi" in href and cgi is None:
                cgi = urljoin(art_url, href)
    if not (pdf and cgi):
        raise RuntimeError(f"記事の「1部リーグ」の欄に日程PDF({pdf})と試合結果CGI({cgi})がそろっていない")
    return pdf, cgi


def read_osaka(cfg: dict) -> tuple[dict, list[dict]]:
    year = str(SEASON_YEAR)
    pref_key = cfg["pref"]
    nfkc = lambda s: re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", s or ""))
    pdf_url, cgi = _osaka_links(year)
    if not cgi.startswith("http://"):
        cgi = "http://" + cgi.split("://", 1)[1]       # ⚠️ https では繋がらない
    if "bsl=" not in cgi:
        cgi += ("&" if "?" in cgi else "?") + "bsl=0"  # 全ブロック
    html = fetch_html(cgi, encoding="shift_jis")
    time.sleep(SLEEP)
    soup = BeautifulSoup(html, "html.parser")
    text = nfkc(soup.get_text(" "))
    if f"U-18サッカーリーグ{year}OSAKA" not in text:
        raise RuntimeError(f"星取表CGIの表題が{year}年のOSAKAでない（文字化けの疑い）")
    m = re.search(r"1部リーグ\((\d+)/(\d+)試合消化", text)
    v = re.search(r"最新の更新(\d{4})/(\d{2})/(\d{2})", text)
    if not m or not v:
        raise RuntimeError("星取表CGIから消化数または更新日が読めない")
    said_played, said_total = int(m.group(1)), int(m.group(2))
    version = f"{v.group(1)}-{v.group(2)}-{v.group(3)}"
    n = cfg["teams"]
    grids = [t for t in soup.find_all("table") if len(t.find_all("tr")) == 2 + n]
    if len(grids) != 1:
        raise RuntimeError(f"星取表CGIの表が{len(grids)}個（1個のはず）")
    rows = grids[0].find_all("tr")

    def cell_parts(td):
        """1つのマスを <br> で割って ['2○1', '3○2'] にする。⚠️ まとめてテキスト化しないこと。"""
        h = td.decode_contents().replace("<br/>", "\x01").replace("<br>", "\x01").replace("<BR>", "\x01")
        return [x for x in (nfkc(p) for p in BeautifulSoup(h, "html.parser").get_text().split("\x01")) if x]

    head = [nfkc(td.get_text()) for td in rows[0].find_all(["td", "th"])]
    teams = head[1:1 + n]
    if head[1 + n:] != ["勝点", "得失差", "得点", "失点", "順位"]:
        raise RuntimeError(f"星取表CGIのヘッダが想定と違う: {head}")
    standings, legs = {}, {}
    for k, tr in enumerate(rows[1:1 + n]):
        tds = tr.find_all(["td", "th"])
        me = nfkc(tds[0].get_text())
        if me != teams[k]:
            raise RuntimeError(f"星取表CGIの{k + 1}行目 {me} が列の並び {teams[k]} と合わない")
        vals = [nfkc(td.get_text()) for td in tds[1 + n:1 + n + 5]]
        if not all(re.fullmatch(r"[+-]?\d+", x) for x in vals):
            raise RuntimeError(f"星取表CGI {me} の成績欄が読めない: {vals}")
        pts, gd, gf, ga, rank = (int(x) for x in vals)
        if gf - ga != gd:
            raise RuntimeError(f"星取表CGI {me}: 得点−失点≠得失差（読み取りの誤り、または出典の誤り）")
        standings[me] = dict(pts=pts, gf=gf, ga=ga, rank=rank)
        for j, opp in enumerate(teams):
            if j == k:
                continue
            got = []
            for part in cell_parts(tds[1 + j]):
                mm = _OSAKA_CELL_RE.fullmatch(part)
                if not mm:
                    raise RuntimeError(f"星取表CGI {me}×{opp} のマスが読めない: {part!r}")
                a, mark, b = int(mm.group(1)), mm.group(2), int(mm.group(3))
                if mark != ("○" if a > b else "●" if a < b else "△"):
                    raise RuntimeError(f"星取表CGI {me}×{opp}: ○●△とスコアが合わない {part!r}")
                got.append((a, b))
            legs[(me, opp)] = got
    for (a, b), got in legs.items():                  # ✅ 鏡チェック（件数と順番も含めて）
        other = legs[(b, a)]
        if [(y, x) for x, y in got] != other:
            raise RuntimeError(f"星取表の鏡チェックが合わない: {a}×{b} {got} / {b}×{a} {other}")

    # --- 日程表PDF（節・日付。スコアは無い） ---
    content = pdf_source.fetch_pdf(pdf_url, HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        if f"U-18サッカーリーグ{year}OSAKA1部試合日程表" not in nfkc(pdf.pages[0].extract_text() or ""):
            raise RuntimeError(f"日程PDFの表題が{year}年のOSAKA1部でない")
        rows_pdf = [r for pg in pdf.pages for t in pdf_source.page_tables(pg) for r in t]
    alt = "|".join(sorted((re.escape(t) for t in teams), key=len, reverse=True))
    card = re.compile(rf"({alt})VS({alt})")
    md = None
    sched = []
    for r in rows_pdf:
        c = [nfkc(x) for x in r]
        if len(c) != 6 or c[0] == "節":
            continue
        if c[0].isdigit():
            md = int(c[0])
        dm = re.fullmatch(r"(\d{1,2})/(\d{1,2})", c[1])
        mm = card.fullmatch(c[5])
        if not (mm and dm and md):
            raise RuntimeError(f"日程PDFの行が読めない: {r}")
        sched.append(dict(md=md, date=f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}",
                          home=mm.group(1), away=mm.group(2)))
    half = n - 1
    if len(sched) != n * (n - 1):
        raise RuntimeError(f"日程PDFから{len(sched)}試合（{n * (n - 1)}試合のはず）")
    if any(sum(1 for s in sched if s["md"] == k) != n // 2 for k in range(1, 2 * half + 1)):
        raise RuntimeError("日程PDFの節ごとの試合数が想定と違う")
    for rnd in (1, 2):
        ps = [frozenset((s["home"], s["away"])) for s in sched if (s["md"] <= half) == (rnd == 1)]
        if len(set(ps)) != len(ps) or len(ps) != n * (n - 1) // 2:
            raise RuntimeError(f"日程PDFの{rnd}巡目に同じ組が重複または欠落")

    # --- 結合：**マスの並び順には頼らない**。前回の保存内容をスコアで引き継ぎ、増えた分だけを
    #     「版日付までに予定されていた空き枠」に当てる（assign_legs_incrementally）。 ---
    today = _jst_today().isoformat()
    by_pair = collections.defaultdict(list)
    for s in sched:
        by_pair[frozenset((s["home"], s["away"]))].append(s)
    matches = []
    for key, two in by_pair.items():
        two.sort(key=lambda s: s["md"])
        a, b = sorted(key)
        # ⚠️ 「1件目＝前期」という並び順には頼らない（大阪2部で、どの並べ方も偶然と変わらないと実測）。
        #    ⚠️ 判定に使うのは**版日付**（今日ではない）。版より後の枠に結果は入りえないので空き枠が狭まる。
        got = assign_legs_incrementally(pref_key, a, b, legs[(a, b)], two, version)
        for s, x in zip(two, got):
            hs, as_ = (None, None) if x is None else (x if s["home"] == a else (x[1], x[0]))
            matches.append(dict(md=s["md"], date=s["date"], home=s["home"], away=s["away"],
                                hs=hs, **{"as": as_}))
    played = [m for m in matches if m["hs"] is not None]
    if len(played) != said_played or len(matches) != said_total:
        raise RuntimeError(f"組み立てた{len(played)}/{len(matches)}試合が、出典の自己申告"
                           f"{said_played}/{said_total}と合わない")
    future = [m for m in played if m["date"] > version]
    if future:
        raise RuntimeError(f"版日付({version})より後の予定日に結果がある試合が{len(future)}件"
                           f"（例: {future[0]['date']} {future[0]['home']}×{future[0]['away']}）")
    check_legs_not_swapped(pref_key, matches)
    print(f"       （大阪: 出典の自己申告 {said_played}/{said_total} と一致。版 {version}）")
    return standings, matches


# ============================================================
# 和歌山（wfa.or.jp）— 県協会の「1部リーグ 試合結果」PDF **1本・1ページ**（2026-09-17追加）
#   入口: /pages/350/（第2種）。⚠️ 同じページに2部・3部・フレッシュマン・高校総体のPDFが並び、
#   リンク文字はどれも「試合結果 9/14UP」で区別が付かない。
#   → **h2（高円宮杯 JFA U-18サッカーリーグ{年}）→ h3「1部リーグ」に完全一致**、その直後のPDFを取る。
#   ⚠️ 「1部」の部分一致で拾わない（将来「1部リーグ順位表」等が増えると壊れる）。URLは更新のたびに変わる。
# ⭐️ 1ページに **順位表・星取表・前期日程・後期日程** が全部入っている。`page_tables` が3つの表に割ってくれる
#    （星取表＋順位表／前期45行／後期45行）ので、座標を使わずに読める。
# ⚠️ 節番号は前期・後期それぞれ1〜9。**後期は +9 して md=1〜18 にする**（福島・京都と同じ規約）。
# ⚠️ 同じ節の日付が大きく離れることがある（前期第7節に5/9、後期第6節に10/17）。
#    ❌ 「同じ節は3日以内」のような検査を入れない（奈良で同じ失敗をした）。
# ⭐️⭐️ この県は**同じPDFの中に独立した2つの結果表**（星取表グリッドと日程表）がある。
#    → 日程表の70試合を、星取表の (home,away,巡目) と (away,how,巡目) の**両方のマス**と突き合わせる（140セル）。
#      愛媛の鏡チェックより強い検算で、誤記があれば「どのマスか」まで分かる。
# ⚠️ 未消化のマスは空欄（高知のように 0-0 とは出ない）。印（○●△）のあるマスだけを消化として扱う。
# ⚠️ ホーム/アウェイは出さない。ホーム試合数が近大和歌山 10/4・桐蔭 4/10 と最大6試合ずれ、
#    25ペア中7ペアが両巡とも同じ側、90試合中59が中立会場（学校名の会場31試合でも左16・右1・無関係14）。
# ✅ 順位表は勝点・得点・失点・得失差・順位（勝分敗なし）→ `okinawa` ゲート。
# 年度切り替え: h2 の年で追随する。
# ============================================================
_WAKAYAMA_LIST = "https://www.wfa.or.jp/pages/350/"
_WAKAYAMA_CELL_RE = re.compile(r"(\d+)([○●△])(\d+)")


def read_wakayama(cfg: dict) -> tuple[dict, list[dict]]:
    from urllib.parse import urljoin
    year = str(SEASON_YEAR)
    nfkc = lambda s: re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", s or ""))
    soup = BeautifulSoup(fetch_html(_WAKAYAMA_LIST, encoding=None), "html.parser")
    time.sleep(SLEEP)
    # ⚠️ 同じPDFに画像リンク（文字なし）と文字リンクの2つが張られている。**版日付を持つ文字リンク**を選ぶ。
    hits, h2, h3 = [], None, None
    for e in soup.find_all(["h2", "h3", "a"]):
        t = nfkc(e.get_text())
        if e.name == "h2":
            h2, h3 = t, None
        elif e.name == "h3":
            h3 = t
        elif e.get("href", "").lower().endswith(".pdf"):
            if h2 and "高円宮杯" in h2 and f"U-18サッカーリーグ{year}" in h2 and h3 == "1部リーグ":
                hits.append((urljoin(_WAKAYAMA_LIST, e["href"]), t))
    if not hits:
        raise RuntimeError(f"入口ページに{year}年・1部リーグの試合結果PDFが見つからない")
    if len({u for u, _ in hits}) != 1:
        raise RuntimeError(f"1部リーグの欄にPDFが{len({u for u, _ in hits})}本ある: {[u for u, _ in hits]}")
    url = hits[0][0]
    labels = [t for _, t in hits if re.search(r"(\d{1,2})/(\d{1,2})UP", t)]
    if not labels:
        raise RuntimeError(f"リンク文字から版日付が読めない: {[t for _, t in hits]}")
    m = re.search(r"(\d{1,2})/(\d{1,2})UP", labels[0])
    version = f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    content = pdf_source.fetch_pdf(url, HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        page = pdf.pages[0]
        if f"U-18サッカーリーグ{year}和歌山" not in nfkc(page.extract_text() or ""):
            raise RuntimeError(f"PDFの表題が{year}年の和歌山でない")
        tables = pdf_source.page_tables(page)
    n = cfg["teams"]
    want = ["勝点", "得点", "失点", "得失差", "順位"]
    grids = [t for t in tables if t and [nfkc(c) for c in t[0][-5:]] == want]
    scheds = [t for t in tables if t and [nfkc(c) for c in t[0]] == ["節", "日付(曜日)", "場所", "開始時間", "対戦"]]
    if len(grids) != 1 or len(scheds) != 2:
        raise RuntimeError(f"PDFの表が想定と違う（星取表{len(grids)}個・日程表{len(scheds)}個）")
    grid = grids[0]
    teams = [nfkc(c) for c in grid[0][2:2 + n]]
    if len(grid) != 1 + 2 * n or len(set(teams)) != n:
        raise RuntimeError(f"星取表が{len(grid)}行・チーム{len(set(teams))}（{1 + 2 * n}行・{n}チームのはず）")

    # --- 星取表グリッド（前期／後期の2段）と順位表 ---
    standings, cells = {}, {}
    for k in range(n):
        first, second = grid[1 + 2 * k], grid[2 + 2 * k]
        me = nfkc(first[0])
        if me != teams[k] or nfkc(first[1]) != "前期" or nfkc(second[1]) != "後期" or nfkc(second[0]):
            raise RuntimeError(f"星取表の{k + 1}行目が想定と違う（{me}／{nfkc(first[1])}・{nfkc(second[1])}）")
        v = [nfkc(x) for x in first[-5:]]
        if not all(re.fullmatch(r"[+-]?\d+", x) for x in v):
            raise RuntimeError(f"順位表 {me} の数値が読めない: {v}")
        pts, gf, ga, gd, rank = (int(x) for x in v)
        if gf - ga != gd:
            raise RuntimeError(f"順位表 {me}: 得点−失点≠得失差（読み取りの誤り、または出典の誤り）")
        standings[me] = dict(pts=pts, gf=gf, ga=ga, rank=rank)
        for j, opp in enumerate(teams):
            if j == k:
                if nfkc(first[2 + j]) or nfkc(second[2 + j]):
                    raise RuntimeError(f"星取表 {me} の対角のマスに文字がある")
                continue
            for rnd, row in ((0, first), (1, second)):
                s = nfkc(row[2 + j])
                if not s:
                    continue                      # 未消化（この県は空欄。0-0とは出ない）
                mm = _WAKAYAMA_CELL_RE.fullmatch(s)
                if not mm:
                    raise RuntimeError(f"星取表 {me}×{opp}（{'前期' if rnd == 0 else '後期'}）のマスが読めない: {s!r}")
                gf_, mark, ga_ = int(mm.group(1)), mm.group(2), int(mm.group(3))
                if mark != ("○" if gf_ > ga_ else "●" if gf_ < ga_ else "△"):
                    raise RuntimeError(f"星取表 {me}×{opp}: ○●△とスコアが合わない {s!r}")
                cells[(me, opp, rnd)] = (gf_, ga_)

    # --- 前期・後期の日程表（結果入り） ---
    alt = "|".join(sorted((re.escape(t) for t in teams), key=len, reverse=True))
    card = re.compile(rf"({alt})(\d*)-(\d*)({alt})")
    matches = []
    for rnd, tb in enumerate(scheds):
        md = None
        for r in tb[1:]:
            c = [nfkc(x) for x in r]
            if len(c) != 5:
                raise RuntimeError(f"日程表の行の列数が想定と違う: {r}")
            if c[0].isdigit():
                md = int(c[0])
            dm = re.match(r"(\d{1,2})月(\d{1,2})日", c[1])
            mm = card.fullmatch(c[4])
            if not (mm and dm and md):
                raise RuntimeError(f"日程表の行が読めない: {r}")
            home, away = mm.group(1), mm.group(4)
            hs = int(mm.group(2)) if mm.group(2) else None
            as_ = int(mm.group(3)) if mm.group(3) else None
            if (hs is None) != (as_ is None):
                raise RuntimeError(f"日程表の結果が片側だけ入っている: {r}")
            matches.append(dict(md=md + rnd * (n - 1), date=f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}",
                                home=home, away=away, hs=hs, **{"as": as_}))
    if len(matches) != n * (n - 1):
        raise RuntimeError(f"日程表から{len(matches)}試合（{n * (n - 1)}試合のはず）")
    for rnd in (0, 1):
        ps = [frozenset((m["home"], m["away"])) for m in matches if (m["md"] <= n - 1) == (rnd == 0)]
        if len(set(ps)) != len(ps) or len(ps) != n * (n - 1) // 2:
            raise RuntimeError(f"日程表の{'前期' if rnd == 0 else '後期'}に同じ組が重複または欠落")

    # ✅ 同じPDFの中の独立した2つの表（星取表グリッド × 日程表）を突き合わせる
    played = [m for m in matches if m["hs"] is not None]
    used = 0
    for m in played:
        rnd = 0 if m["md"] <= n - 1 else 1
        a = cells.get((m["home"], m["away"], rnd))
        b = cells.get((m["away"], m["home"], rnd))
        if a is None or b is None:
            raise RuntimeError(f"日程表にあるのに星取表に無い試合: 第{m['md']}節 {m['home']}×{m['away']}")
        if a != (m["hs"], m["as"]) or b != (m["as"], m["hs"]):
            raise RuntimeError(f"日程表と星取表が食い違う: 第{m['md']}節 {m['home']} {m['hs']}-{m['as']} {m['away']}"
                               f"／星取表 {a} と {b}")
        used += 2
    if used != len(cells):
        raise RuntimeError(f"星取表のマス{len(cells)}個のうち、日程表と結べたのは{used}個"
                           f"（日程表に無い結果が星取表にある）")
    future = [m for m in played if m["date"] > version]
    if future:
        raise RuntimeError(f"版日付({version})より後の予定日に結果がある試合が{len(future)}件"
                           f"（例: {future[0]['date']} {future[0]['home']}×{future[0]['away']}）")
    print(f"       （和歌山: 日程表{len(matches)}枠・消化{len(played)}／星取表のマス{len(cells)}個と完全一致。版 {version}）")
    return standings, matches


# ============================================================
# 高知（kochi-fa.com）— 県協会の星取表PDF（スコア・節番号＝**主資料**）＋ 日程表PDF（日付の付与用）（2026-09-17追加）
#   入口: /class02/class02sch/entry-305.html（第2種）。⚠️ **必ず https://www. で開く**（PDFは www 側にある）。
#   ⚠️ 同じページに2部・3部A/B/C・順位戦、さらに前年度分も並ぶ。リンク文字は「日程表」「星取表」だけで部も年も入らない。
#     → **本文の並び順（「2026」→「▶1部」）を辿って、その直後の2本だけ**を取る。URLは更新のたびに変わるので直リンクしない。
# ⭐️ 星取表は各マスに**丸数字①〜⑭で節番号**が入っている（巡目の材料が出典にある3例目）。
#    上段は①〜⑦・下段は⑧〜⑭（2026-09-14版で40マスすべて例外なし）→ **巡目の割り当てにも検算にも使う。**
# ⚠️⚠️ **未消化のマスが `0－0` と表示される。** 本物の0-0と見分けがつかないので、
#    **○●△の印があるマスだけを消化として扱う**（愛媛の「印とスコアの整合」の逆向きの使い方）。
# ⚠️⚠️ **丸数字は NFKC で普通の数字になる（⑦→7）。** セル全体に NFKC を当てるとスコアに節番号が混ざる。
#    **NFKC はチーム名にだけ当て、数字を拾うときは丸数字を除外する。**
# ⚠️ 星取表は表として読むと段がずれる（`page_tables` では節とスコアが1つのセルに混ざる）。
#    → 表の**列（見出し行のセル）と行の帯**を使い、帯を3pt上にずらして上段・下段に分ける（岐阜と同じ作法）。
# ⚠️ 日程表は2カラム同居だが `page_tables` が左右を別の表として返す（各表6列）。チーム名は1文字ずつ空白で区切られる。
#    対戦欄は `高知中央5(2vs0)0宿毛工業` の形（前半得点つき）。**日程表は日付を付けるためだけに使う。**
# ⚠️ ホーム/アウェイは出さない（cross_table.NO_HOME_AWAY_SLUGS）。
#    ホーム試合数は8チームとも7-7で28ペアすべて左右が入れ替わるが、**機械的に総当たりを組めばそうなるだけで根拠にならない**。
#    会場は56試合中54が中立の公共施設で、唯一の学校会場（明徳義塾高校）でも明徳義塾が左（第6節）と右（第13節）の両方に出る。
# ✅ 星取表に勝分敗がそろうので通常の検算ゲート。ただし**高知小津の得点だけ合計欄が3多い**（KNOWN_SOURCE_ERRORS）。
# 年度切り替え: 本文の年の並びで追随する。
# ============================================================
_KOCHI_ENTRY = "https://www.kochi-fa.com/class02/class02sch/entry-305.html"
_KOCHI_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭"


def _kochi_links(year: str) -> dict:
    """入口ページの並び順（{年} → ▶1部 → 日程表／星取表）を辿ってPDFのURLを返す。"""
    from urllib.parse import urljoin
    from bs4 import NavigableString
    soup = BeautifulSoup(fetch_html(_KOCHI_ENTRY, encoding=None), "html.parser")
    time.sleep(SLEEP)
    nfkc = lambda s: re.sub(r"[\s​　]+", "", unicodedata.normalize("NFKC", s or ""))
    cur_year = cur_sect = None
    out = {}
    for node in soup.descendants:
        if isinstance(node, NavigableString):
            t = nfkc(str(node))
            if re.fullmatch(r"・?20\d\d", t):
                cur_year = t[-4:]
            elif re.fullmatch(r"[▶▼]\d部|順位戦", t):
                cur_sect = t
        elif getattr(node, "name", "") == "a" and node.get("href") and "media-download" in node["href"]:
            label = nfkc(node.get_text())
            if cur_year == year and cur_sect in ("▶1部", "▼1部") and label in ("日程表", "星取表"):
                out.setdefault(label, urljoin(_KOCHI_ENTRY, node["href"]))
    return out


def read_kochi(cfg: dict) -> tuple[dict, list[dict]]:
    year = str(SEASON_YEAR)
    nfkc = lambda s: re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", s or ""))
    links = _kochi_links(year)
    for key in ("日程表", "星取表"):
        if key not in links:
            raise RuntimeError(f"入口ページの{year}年・1部の欄に「{key}」のリンクが見つからない")

    # --- 星取表（スコア・節番号・成績。主資料） ---
    content = pdf_source.fetch_pdf(links["星取表"], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    n = cfg["teams"]
    with pdf_source.open_pdf(content) as pdf:
        page = pdf.pages[0]
        if f"サッカーリーグ{year}高知県リーグ1部" not in nfkc(page.extract_text() or ""):
            raise RuntimeError(f"星取表PDFの表題が{year}年の高知県リーグ1部でない")
        tbs = page.find_tables()
        if len(tbs) != 1:
            raise RuntimeError(f"星取表PDFの表が{len(tbs)}個")
        tb = tbs[0]
        head = [nfkc(c) for c in tb.extract()[0]]
        want = ["勝", "分", "負", "勝点", "得点", "失点", "得失点差", "順位"]
        if head[2:2 + n + 8][n:] != want:
            raise RuntimeError(f"星取表のヘッダが想定と違う: {head}")
        teams = head[2:2 + n]
        cols = [tb.rows[0].cells[2 + j] for j in range(n)]
        num_cols = [tb.rows[0].cells[2 + n + j] for j in range(8)]
        bands = [(r.bbox[1], r.bbox[3]) for r in tb.rows if r.bbox[3] - r.bbox[1] > 40]
        if len(bands) != n or any(c is None for c in cols + num_cols):
            raise RuntimeError(f"星取表の行の帯が{len(bands)}本（{n}本のはず）、または列が取れない")
        words = pdf_source.page_words(page)

    def plain_ints(ws):
        """丸数字（節番号）を除いた数字だけ。⚠️ NFKC は ⑦ を 7 にするので、必ず元の文字で判定する。"""
        return [int(nfkc(w["text"])) for w in ws
                if re.fullmatch(r"-?\d+", nfkc(w["text"])) and not any(ch in _KOCHI_CIRCLED for ch in w["text"])]

    # ⚠️ マスの中身は行の帯より少し上に出る（節番号が帯の上端をまたぐ）。帯を3pt上にずらす。
    shift, standings, legs = 3, {}, {}
    for k, (b0, b1) in enumerate(bands):
        top, bot = b0 - shift, b1 - shift
        mid = (top + bot) / 2
        me = teams[k]
        vals = []
        for c in num_cols:
            ws = [w for w in words if c[0] <= w["x0"] < c[2] and top <= w["top"] < bot]
            got = plain_ints(ws)
            if len(got) != 1:
                raise RuntimeError(f"星取表 {me} の成績欄が読めない（{len(got)}個の数字）")
            vals.append(got[0])
        won, drawn, lost, pts, gf, ga, gd, rank = vals
        if 3 * won + drawn != pts or gf - ga != gd:
            raise RuntimeError(f"星取表 {me} の自己検算が合わない（{won}勝{drawn}分{lost}敗・勝点{pts}・{gf}-{ga}・差{gd}）")
        standings[me] = dict(pts=pts, played=won + drawn + lost, won=won, drawn=drawn,
                             lost=lost, gf=gf, ga=ga)
        for j, opp in enumerate(teams):
            if j == k:
                continue
            pair = []
            for a, b in ((top, mid), (mid, bot)):
                ws = sorted([w for w in words if cols[j][0] <= w["x0"] < cols[j][2] and a <= w["top"] < b],
                            key=lambda w: (w["top"], w["x0"]))
                md = [_KOCHI_CIRCLED.index(ch) + 1 for w in ws for ch in w["text"] if ch in _KOCHI_CIRCLED]
                mark = [nfkc(w["text"]) for w in ws if nfkc(w["text"]) in "○●△"]
                score = plain_ints(ws)
                if len(md) != 1:
                    raise RuntimeError(f"星取表 {me}×{opp} のマスに節番号が{len(md)}個")
                # ⚠️ 未消化のマスも `0－0` と出るので、**印の有無**で消化を決める（スコアで決めない）。
                if not mark:
                    pair.append(dict(md=md[0], score=None))
                    continue
                if len(score) != 2:
                    raise RuntimeError(f"星取表 {me}×{opp} のスコアが読めない: {score}")
                if mark[0] != ("○" if score[0] > score[1] else "●" if score[0] < score[1] else "△"):
                    raise RuntimeError(f"星取表 {me}×{opp}: ○●△とスコアが合わない {mark[0]} {score}")
                pair.append(dict(md=md[0], score=(score[0], score[1])))
            half = n - 1
            for i, p in enumerate(pair):       # ✅ 上段は①〜⑦・下段は⑧〜⑭
                if (p["md"] <= half) != (i == 0):
                    raise RuntimeError(f"星取表 {me}×{opp} の{'上' if i == 0 else '下'}段に第{p['md']}節がある"
                                       f"（上段は1〜{half}節・下段は{half + 1}節以降のはず）")
            legs[(me, opp)] = pair
    for (a, b), pr in legs.items():            # ✅ 鏡チェック（節番号とスコアの両方）
        for i, p in enumerate(pr):
            q = legs[(b, a)][i]
            if p["md"] != q["md"] or (p["score"] is None) != (q["score"] is None) \
                    or (p["score"] and p["score"][::-1] != q["score"]):
                raise RuntimeError(f"星取表の鏡チェックが合わない: {a}×{b} {p} / {b}×{a} {q}")
    # ✅ 出典の合計と、マスから数えた値を突き合わせる（既知の誤りは KNOWN_SOURCE_ERRORS の差で明示）
    known = KNOWN_SOURCE_ERRORS.get("kochi", {})
    mine = {t: dict(pts=0, played=0, won=0, drawn=0, lost=0, gf=0, ga=0) for t in teams}
    for (a, _b), pr in legs.items():
        for p in pr:
            if not p["score"]:
                continue
            gf_, ga_ = p["score"]
            s = mine[a]
            s["played"] += 1
            s["gf"] += gf_
            s["ga"] += ga_
            s["won"] += gf_ > ga_
            s["drawn"] += gf_ == ga_
            s["lost"] += gf_ < ga_
            s["pts"] += 3 if gf_ > ga_ else 1 if gf_ == ga_ else 0
    for team, off in standings.items():
        want_diff = {k: 0 for k in off}
        want_diff.update(known.get(team, {}))
        got = {k: off[k] - mine[team][k] for k in off}
        if got != want_diff:
            extra = ("。協会が直したなら KNOWN_SOURCE_ERRORS から高知の項目を消すこと"
                     if known.get(team) else "")
            raise RuntimeError(f"星取表 {team} の合計欄がマスから数えた値と合わない（公式−計算＝"
                               f"{ {k: v for k, v in got.items() if v} }・見込みは"
                               f"{ {k: v for k, v in want_diff.items() if v} or '差なし' }）{extra}")
    standings = {t: dict(mine[t]) for t in teams}   # 既知の差を除いた値＝マスと一致する値

    # --- 日程表（ペア＋巡目 → 日付） ---
    content = pdf_source.fetch_pdf(links["日程表"], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        if f"サッカーリーグ{year}高知県リーグ1部" not in nfkc(pdf.pages[0].extract_text() or ""):
            raise RuntimeError(f"日程表PDFの表題が{year}年の高知県リーグ1部でない")
        rows = [r for pg in pdf.pages for t in pdf_source.page_tables(pg) if len(t[0]) == 6 for r in t]
    alt = "|".join(sorted((re.escape(t) for t in teams), key=len, reverse=True))
    card = re.compile(rf"({alt})(\d+)\((\d*)vs(\d*)\)(\d+)({alt})")
    md = None
    dates = {}
    for r in rows:
        c = [nfkc(x) for x in r]
        if len(c) != 6 or c[0] == "節":
            continue
        mm = re.fullmatch(r"第(\d+)節", c[0])
        if mm:
            md = int(mm.group(1))
        dm = re.match(r"(\d{1,2})/(\d{1,2})", c[1])
        m = card.match(c[3])
        if not m:
            continue
        if not (dm and md):
            raise RuntimeError(f"日程表の行に節または日付が無い: {r}")
        home, away = m.group(1), m.group(6)
        key = (frozenset((home, away)), md)
        if key in dates:
            raise RuntimeError(f"日程表に第{md}節の {home}×{away} が2回ある")
        dates[key] = (f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}", home, away)
    if len(dates) != n * (n - 1):
        raise RuntimeError(f"日程表から{len(dates)}試合（{n * (n - 1)}試合のはず）")

    # --- 星取表（スコア・節）と日程表（日付・左右）を「ペア＋節」で結合 ---
    matches, seen = [], set()
    for (key, md_), (date, home, away) in sorted(dates.items(), key=lambda kv: kv[0][1]):
        p = legs[(home, away)][0 if md_ <= n - 1 else 1]
        if p["md"] != md_:
            raise RuntimeError(f"日程表の第{md_}節 {home}×{away} が、星取表では第{p['md']}節になっている")
        if (key, md_) in seen:
            continue
        seen.add((key, md_))
        matches.append(dict(md=md_, date=date, home=home, away=away,
                            hs=p["score"][0] if p["score"] else None,
                            **{"as": p["score"][1] if p["score"] else None}))
    played = [m for m in matches if m["hs"] is not None]
    if len(played) * 2 != sum(v["played"] for v in standings.values()):
        raise RuntimeError(f"結合後の消化{len(played)}試合×2が、星取表の試合数の合計"
                           f"{sum(v['played'] for v in standings.values())}と合わない")
    today = _jst_today().isoformat()
    future = [m for m in played if m["date"] > today]
    if future:
        raise RuntimeError(f"今日({today})より後の予定日に結果がある試合が{len(future)}件"
                           f"（例: {future[0]['date']} {future[0]['home']}×{future[0]['away']}）")
    return standings, matches


# ============================================================
# 奈良（narafa.or.jp）— 県協会の日程表PDF（結果入り・**主資料**）＋ 1部リーグ星取表PDF（検算用）（2026-09-17追加）
#   入口: /pages/26/（第二種）。リンク文字は「日程表」「1部リーグ星取表」（NFKC後）。
#   ⚠️ PDFのURLは更新のたびに変わるので、必ずページのリンクから取る。2部・3部A・3部Bの星取表も同じページにある。
# ⭐️ 版日付はページ本文の `(2026-09-14・234KB)` から取れる（PDF本文には無い）。
#    **日程表と星取表の更新日が一致することを確認する**（片方だけ新しいと検算が誤って落ちる）。
# ⭐️ 日程表は1試合1行（日付・部・節・時間・カード・会場）。`部` 列は結合しておらず1行ごとに値が入るので、
#    **`部` が「1部」の行だけを採ればよい**（福島のようなカテ列の結合セル問題は無い）。
#    ⚠️ 名前の部分一致で拾わないこと（2部3部に `生駒2nd`・`奈良クラブユースB` などがある）。
# ⚠️ 日付は結合セルだが、`page_tables` で解ける（ブロックの先頭行にだけ入るので行ごとに引き継ぐ）。
#    📌 座標（ラベルのy）で割り当てないこと。**日付ラベルはブロックの中央に無く、位置がブロックごとに違う**。
# ⚠️⚠️ スコアの区切りに**全角マイナス（−）と半角（-）が混在**する（第1節「生駒 3−0 法隆寺国際」が全角）。
#    受けそこねると、その試合を落とすうえ、junior-soccer 側の誤り（3-1）も見つけられない。
# ⚠️ スコア欄が「延期」の行は捨てる（振替先の日付の行に同じ節でもう一度出てくる。2試合として数えない）。
# ⚠️ 節の順＝日付の順ではない（振替で前後する）。日程表は第15節までで、第16〜18節は未掲載（異常ではない）。
# ⚠️ ホーム/アウェイは無い。左右はチーム番号順で、奈良クラブユースは12試合すべて左・五條は12試合すべて右、
#    2試合あるペア14組は両巡目とも同じ側（2026-09-17実測）→ cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。
# ✅ 星取表の合計は勝点・得失点・総得点・順位だけ（勝分敗が無い）。**失点＝総得点−得失点**で導いて `okinawa` ゲート。
# ✅ 日程表から数えた総得点と、星取表の総得点の合計が一致することを確かめる（2本のPDFをまたぐ独立した裏づけ）。
# 年度切り替え: 入口は固定。表題の年で前年度のPDFを読む事故を止める。
# ============================================================
_NARA_LIST = "https://www.narafa.or.jp/pages/26/"
_NARA_SCORE_RE = re.compile(r"(\d+)\s*[-−ー―–]\s*(\d+)")
_NARA_VER_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})・")


def read_nara(cfg: dict) -> tuple[dict, list[dict]]:
    from urllib.parse import urljoin
    year = str(SEASON_YEAR)
    nfkc = lambda s: re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))
    soup = BeautifulSoup(fetch_html(_NARA_LIST, encoding=None), "html.parser")
    time.sleep(SLEEP)
    found = {}
    for a in soup.find_all("a", href=True):
        t = nfkc(a.get_text())
        if t in ("日程表", "1部リーグ星取表"):
            ctx = nfkc(a.parent.get_text(" ")) if a.parent else t
            m = _NARA_VER_RE.search(ctx)
            found.setdefault(t, []).append((urljoin(_NARA_LIST, a["href"]), m.group(1) if m else ""))
    for key in ("日程表", "1部リーグ星取表"):
        if len(found.get(key, [])) != 1:
            raise RuntimeError(f"入口ページに「{key}」のリンクが{len(found.get(key, []))}件（1件のはず）")
    versions = {k: v[0][1] for k, v in found.items()}
    if not all(v.startswith(f"{year}-") for v in versions.values()):
        raise RuntimeError(f"更新日が{year}年として読めない: {versions}")
    if versions["日程表"] != versions["1部リーグ星取表"]:
        raise RuntimeError(f"日程表({versions['日程表']})と星取表({versions['1部リーグ星取表']})の更新日が違う"
                           f"（片方だけ更新されている）")
    version = versions["日程表"]

    # --- 1部リーグ星取表（合計列だけを使う） ---
    content = pdf_source.fetch_pdf(found["1部リーグ星取表"][0][0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        text = "".join(pg.extract_text() or "" for pg in pdf.pages)
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    if f"サッカーリーグ{year}奈良1部" not in nfkc(text):
        raise RuntimeError(f"星取表PDFの表題が{year}年の奈良1部でない")
    n = cfg["teams"]
    want = ["勝点", "得失点", "総得点", "順位"]
    grids = [t for t in tables if t and [nfkc(c) for c in t[0][-4:]] == want and len(t) == 1 + n]
    if len(grids) != 1:
        raise RuntimeError(f"星取表PDFの表が{len(grids)}個（1個のはず）")
    standings, ranks = {}, []
    for r in grids[0][1:]:
        team = nfkc(r[0])
        v = [nfkc(x) for x in r[-4:]]
        if not all(re.fullmatch(r"[+-]?\d+", x) for x in v):
            raise RuntimeError(f"星取表 {team} の合計列が読めない: {v}")
        pts, gd, gf, rank = (int(x) for x in v)
        # ⭐️ 失点は出ていないので 総得点−得失点 で導く（この県だけの事情）。
        standings[team] = dict(pts=pts, gf=gf, ga=gf - gd, rank=rank)
        ranks.append((rank, team))
    if len(standings) != n:
        raise RuntimeError(f"星取表の順位表が{len(standings)}チーム（{n}チームのはず）")

    # --- 日程表（結果入り・主資料） ---
    content = pdf_source.fetch_pdf(found["日程表"][0][0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        if f"サッカーリーグ{year}奈良日程" not in nfkc(pdf.pages[0].extract_text() or ""):
            raise RuntimeError(f"日程PDFの表題が{year}年の奈良でない")
        rows = [r for pg in pdf.pages for t in pdf_source.page_tables(pg) for r in t]
    matches, date, n_rows, n_post = [], "", 0, 0
    for r in rows:
        c = [nfkc(x) for x in r]
        if len(c) != 8 or c[0] == "日付":
            continue
        dm = re.match(r"(\d{1,2})月(\d{1,2})日", c[0])
        if dm:
            date = f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
        if c[1] != "1部":
            continue
        n_rows += 1
        mm = re.fullmatch(r"(\d+)節", c[2])
        home, away = c[4], c[6]
        if not (mm and home in standings and away in standings and date):
            raise RuntimeError(f"日程表の1部の行が読めない: {r}")
        if "延期" in c[5]:
            n_post += 1          # 振替先の行に同じ節でもう一度出てくるので捨てる
            continue
        sm = _NARA_SCORE_RE.fullmatch(c[5])
        if c[5] and not sm:
            raise RuntimeError(f"日程表のスコア欄が読めない: {c[5]!r}（行: {r}）")
        matches.append(dict(md=int(mm.group(1)), date=date, home=home, away=away,
                            hs=int(sm.group(1)) if sm else None,
                            **{"as": int(sm.group(2)) if sm else None}))
    played = [m for m in matches if m["hs"] is not None]
    print(f"       （奈良: 日程表の1部は{n_rows}行＝結果あり{len(played)}・未消化{len(matches) - len(played)}"
          f"・延期{n_post}。版 {version}）")
    half = n - 1
    for rnd in (1, 2):
        ps = [frozenset((m["home"], m["away"])) for m in matches if (m["md"] <= half) == (rnd == 1)]
        if len(set(ps)) != len(ps):
            raise RuntimeError(f"日程表の{rnd}巡目に同じ組が2回以上ある（延期行の捨て漏れの疑い）")
    if any(sum(1 for m in matches if m["md"] == k) != n // 2 for k in sorted({m["md"] for m in matches})):
        raise RuntimeError("日程表の節ごとの試合数が5でない節がある")
    # ✅ 2本のPDFをまたぐ裏づけ：日程表の総得点＝星取表の総得点の合計
    goals = sum(m["hs"] + m["as"] for m in played)
    if goals != sum(v["gf"] for v in standings.values()):
        raise RuntimeError(f"日程表から数えた総得点{goals}が、星取表の総得点の合計"
                           f"{sum(v['gf'] for v in standings.values())}と合わない（読み取りの誤りの疑い）")
    future = [m for m in played if m["date"] > version]
    if future:
        raise RuntimeError(f"版日付({version})より後の予定日に結果がある試合が{len(future)}件"
                           f"（例: {future[0]['date']} {future[0]['home']}×{future[0]['away']}）")
    return standings, matches


# ============================================================
# 福島（fukushima-fa.com）— 県協会の日程表PDF3本（節・日付・**HOME/AWAY**・会場）＋ F1星取表PDF（スコア）＋ F1順位表PDF（2026-09-16追加）
#   入口: /match/c_match/ffa02/（2種）。⚠️ **記事は一覧の2ページ目にあることがある**ので1〜2ページ目を見る。
#   リンク文字「高円宮杯JFA U-18サッカーリーグ{年} 福島（F1、F2）」。記事URLは年度で変わるので直リンクにしない。
# ⚠️⚠️ **日程表に HOME/AWAY の列はあるが、ホーム/アウェイを表していない**（2026-09-16実測）。
#    ・各チームのホーム試合数が均等でない（2回戦総当たりなら全チーム9・9のはず。尚志ｾｶﾝﾄﾞ15/3・いわきFC 5/13）
#    ・45ペアのうち**30ペアは1巡目も2巡目も同じ側がHOME**（本物のホーム/アウェイなら0ペア）
#    ・会場の持ち主は HOME側23・AWAY側13・どちらでもない54（会場は「主管」列と相関している）
#    → home/away は「日程表のHOME列＝home」の格納規約で事実ではない。cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。
#    📌 **列名を証拠にしないこと。**「出典に HOME と書いてある」だけでは、ホーム/アウェイの根拠にならない。
# ⚠️ スコアと日付が別のファイル（山梨・三重と同じ型）。**星取表に日付と節が無い**ので、
#    日程表と星取表を「ペア＋巡目」で結合する。巡目は節番号（第1〜9節＝1巡目＝上段／第10〜18節＝2巡目＝下段）。
# ⚠️⚠️ **日程PDFには F1 と F2 が混在し、同じ節の中で行が交互に出る。**
#    ❌ 「カテ」列（F1/F2）で絞らない（結合セルでカバー行数が一定でない）。
#    ❌ チーム名の部分一致で絞らない（**F2の名前がF1の名前を含む**：福島ﾕﾅｲﾃｯﾄﾞｾｶﾝﾄﾞ ⊃ 福島ﾕﾅｲﾃｯﾄﾞ、
#       聖光学院ｾｶﾝﾄﾞ、いわきFCｾｶﾝﾄﾞ、ふたば未来学園ｾｶﾝﾄﾞ、尚志ｻｰﾄﾞ ⊃ 尚志ｾｶﾝﾄﾞ）。
#    ✅ **HOME列とAWAY列の両方が順位表の10チームに完全一致する行だけ**を採る（F1とF2でチームは重複しない）。
#    ⚠️ 主管・審判の列にもチーム名が出る。列で絞ってから名前を見ること（`page_tables` なら列が分かれる）。
# ⚠️ 名寄せは NFKC（半角カナ→全角カナ）だけで既存JSONの表記にそろう。個別の対応表は不要。
# ⚠️⚠️ **日程表3本は版が古いのが正常**（1-6節=3/17・7-12節=6/17・13-18節=3/2）。星取表・順位表は9/12版。
#    ❌ 「版日付が違ったら止める」はこの県では使えない。
#    ✅ 代わりに **「星取表に結果があるのに、日程表のその試合の予定日がまだ来ていない」なら止める**
#       （進行中の節が3月版PDFの範囲なので、延期で日付が動いていたらここで引っかかる）。
# ✅ 順位表は勝点・勝分敗・得点・失点・差・順位がそろう → 通常の検算ゲート。星取表の右端の成績欄とも突き合わせる。
# 年度切り替え: 記事のリンク文字の年で追随する。
# ============================================================
_FUKUSHIMA_LIST = "https://fukushima-fa.com/match/c_match/ffa02/"
_FUKUSHIMA_SCORE_COLS = 3   # 星取表は1対戦につき「得点・○●△・失点」の3列


def _fukushima_names(cell: str, teams) -> list[str]:
    """日程表のHOME/AWAYのマスを1部のチーム名に割る。1部でなければ空リスト。

    ⚠️ 2行ぶんが1つのマスに連結されることがある（2026-09-16実測：13節の
       `郡山商業学法石川ｾｶﾝﾄﾞ` × `ふたば未来学園いわきFC`）。**先頭から最長一致で切り、
       全部が1部のチーム名で消費できたときだけ採用**する。部分一致で拾わないための作法でもある
       （F2の名前がF1の名前を含むので、途中で余りが出れば F2 と分かって外れる）。"""
    out, rest = [], cell
    while rest:
        hit = max((t for t in teams if rest.startswith(t)), key=len, default=None)
        if hit is None:
            return []
        out.append(hit)
        rest = rest[len(hit):]
    return out


def read_fukushima(cfg: dict) -> tuple[dict, list[dict]]:
    from urllib.parse import urljoin
    year = str(SEASON_YEAR)
    nfkc = lambda s: re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))
    arts = []
    for page in (_FUKUSHIMA_LIST, _FUKUSHIMA_LIST + "page/2/"):
        soup = BeautifulSoup(fetch_html(page, encoding=None), "html.parser")
        time.sleep(SLEEP)
        arts += [urljoin(page, a["href"]) for a in soup.find_all("a", href=True)
                 if f"U-18サッカーリーグ{year}福島" in nfkc(a.get_text())]
    arts = list(dict.fromkeys(arts))
    if len(arts) != 1:
        raise RuntimeError(f"入口に{year}年のF1・F2の記事が{len(arts)}件（1件のはず）")
    art = BeautifulSoup(fetch_html(arts[0], encoding=None), "html.parser")
    time.sleep(SLEEP)
    links = collections.defaultdict(list)
    for a in art.find_all("a", href=True):
        if not a["href"].lower().endswith(".pdf"):
            continue
        t = nfkc(a.get_text())
        for key in ("日程表", "F1星取表", "F1順位表"):
            if t.startswith(key):
                links[key].append(urljoin(arts[0], a["href"]))
    if len(links["日程表"]) != 3 or len(links["F1星取表"]) != 1 or len(links["F1順位表"]) != 1:
        raise RuntimeError(f"記事のPDFが想定と違う（日程表{len(links['日程表'])}本・"
                           f"星取表{len(links['F1星取表'])}本・順位表{len(links['F1順位表'])}本）")

    # --- 順位表（検算の相手・チーム名の正本） ---
    content = pdf_source.fetch_pdf(links["F1順位表"][0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        text = "".join(pg.extract_text() or "" for pg in pdf.pages)
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    if f"サッカーリーグ{year}福島1部" not in nfkc(text):
        raise RuntimeError(f"順位表PDFの表題が{year}年の福島1部でない")
    want = ["チーム名", "勝ち点", "勝", "分", "負", "得点", "失点", "差", "順位"]
    grids = [t for t in tables if t and [nfkc(c) for c in t[0]] == want]
    n = cfg["teams"]
    if len(grids) != 1 or len(grids[0]) != 1 + n:
        raise RuntimeError(f"順位表PDFの表が想定と違う（{len(grids)}個・{len(grids[0]) if grids else 0}行）")
    standings, ranks = {}, []
    for r in grids[0][1:]:
        team = nfkc(r[0])
        v = [nfkc(x) for x in r[1:]]
        if not all(re.fullmatch(r"[+-]?\d+", x) for x in v):
            raise RuntimeError(f"順位表 {team} の数値が読めない: {v}")
        pts, won, drawn, lost, gf, ga, gd, rank = (int(x) for x in v)
        if 3 * won + drawn != pts or gf - ga != gd:
            raise RuntimeError(f"順位表 {team} の自己検算が合わない（{won}勝{drawn}分{lost}敗・勝点{pts}・{gf}-{ga}・差{gd}）")
        standings[team] = dict(pts=pts, played=won + drawn + lost, won=won, drawn=drawn,
                               lost=lost, gf=gf, ga=ga)
        ranks.append((rank, team))
    if len(standings) != n:
        raise RuntimeError(f"順位表が{len(standings)}チーム（{n}チームのはず）")
    if sum(v["gf"] - v["ga"] for v in standings.values()) != 0:
        raise RuntimeError("順位表の得失差の合計が0でない（読み取りの誤り、または出典の誤り）")

    # --- 星取表（スコア。上段＝1巡目・下段＝2巡目） ---
    content = pdf_source.fetch_pdf(links["F1星取表"][0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        text = "".join(pg.extract_text() or "" for pg in pdf.pages)
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    if f"サッカーリーグ{year}福島1部" not in nfkc(text):
        raise RuntimeError(f"星取表PDFの表題が{year}年の福島1部でない")
    grids = [t for t in tables if t and nfkc(t[0][0]) == "チーム名"
             and len(t) == 1 + 2 * n and len(t[0]) == 1 + _FUKUSHIMA_SCORE_COLS * n + 8]
    if len(grids) != 1:
        raise RuntimeError(f"星取表PDFの表が{len(grids)}個（1個のはず）")
    grid = grids[0]
    order = [nfkc(grid[1 + 2 * k][0]) for k in range(n)]
    if sorted(order) != sorted(standings):
        raise RuntimeError(f"星取表の行のチームが順位表と合わない: {order}")
    legs = {}
    for k, me in enumerate(order):
        upper, lower = grid[1 + 2 * k], grid[2 + 2 * k]
        if nfkc(lower[0]):
            raise RuntimeError(f"星取表 {me} の下段にチーム名がある（行の並びが想定と違う）")
        # 右端の成績欄が順位表と一致するか（星取表と順位表は別PDFなので二重確認になる）
        v = [nfkc(x) for x in upper[-8:]]
        if not all(re.fullmatch(r"[+-]?\d+", x) for x in v):
            raise RuntimeError(f"星取表 {me} の成績欄が読めない: {v}")
        o = standings[me]
        if [int(x) for x in v[:7]] != [o["pts"], o["won"], o["drawn"], o["lost"], o["gf"], o["ga"],
                                       o["gf"] - o["ga"]]:
            raise RuntimeError(f"星取表 {me} の成績欄が順位表と合わない（{v[:7]}）")
        for j, opp in enumerate(order):
            if opp == me:
                continue
            pair = []
            for row in (upper, lower):
                c = [nfkc(x) for x in row[1 + _FUKUSHIMA_SCORE_COLS * j:1 + _FUKUSHIMA_SCORE_COLS * (j + 1)]]
                if not any(c):
                    pair.append(None)
                    continue
                if not (c[0].isdigit() and c[2].isdigit() and c[1] in "○●△"):
                    raise RuntimeError(f"星取表 {me}×{opp} のマスが読めない: {c}")
                gf, ga = int(c[0]), int(c[2])
                if c[1] != ("○" if gf > ga else "●" if gf < ga else "△"):
                    raise RuntimeError(f"星取表 {me}×{opp}: ○●△とスコアが合わない {c}")
                pair.append((gf, ga))
            # 守り：上段（1巡目）が空なのに下段（2巡目）にだけ結果がある
            if pair[0] is None and pair[1] is not None:
                raise RuntimeError(f"星取表 {me}×{opp}: 上段が空なのに下段に結果がある（巡目の前提が崩れた疑い）")
            legs[(me, opp)] = pair
    for (a, b), pr in legs.items():                  # ✅ 鏡チェック（上段・下段とも）
        if [None if x is None else (x[1], x[0]) for x in pr] != legs[(b, a)]:
            raise RuntimeError(f"星取表の鏡チェックが合わない: {a}×{b} {pr} / {b}×{a} {legs[(b, a)]}")

    # --- 日程表3本（節・日付・HOME/AWAY） ---
    sched = []
    for url in links["日程表"]:
        content = pdf_source.fetch_pdf(url, HEADERS, TIMEOUT, wait=SLEEP)
        time.sleep(SLEEP)
        with pdf_source.open_pdf(content) as pdf:
            rows = [r for pg in pdf.pages for t in pdf_source.page_tables(pg) for r in t]
        md = day = None
        for r in rows:
            c = [nfkc(x) for x in r]
            # ⚠️ 表によって列数が違う（主管・審判が無い表がある）。先頭6列（節・日・曜・カテ・HOME・AWAY）は共通。
            if len(c) < 6 or c[0] == "節":
                continue
            if c[0].isdigit():
                md = int(c[0])
            dm = re.fullmatch(r"(\d{1,2})/(\d{1,2})", c[1])
            if dm:
                day = f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
            # ⚠️ カテ列や部分一致で絞らない。両側が1部の10チームに（分割後も）完全一致する行だけがF1。
            homes, aways = _fukushima_names(c[4], standings), _fukushima_names(c[5], standings)
            if not homes or len(homes) != len(aways):
                continue
            if not (md and day):
                raise RuntimeError(f"日程表のF1の行に節または日付が無い: {r}")
            for home, away in zip(homes, aways):
                sched.append(dict(md=md, date=day, home=home, away=away))
    half = n - 1
    if len(sched) != n * (n - 1):
        raise RuntimeError(f"日程表3本からF1が{len(sched)}試合（{n * (n - 1)}試合のはず）")
    if any(sum(1 for s in sched if s["md"] == k) != n // 2 for k in range(1, 2 * half + 1)):
        raise RuntimeError("日程表の節ごとの試合数が想定と違う")
    for rnd in (1, 2):
        ps = [frozenset((s["home"], s["away"])) for s in sched if (s["md"] <= half) == (rnd == 1)]
        if len(set(ps)) != len(ps) or len(ps) != n * (n - 1) // 2:
            raise RuntimeError(f"日程表の{rnd}巡目（第{'1-9' if rnd == 1 else '10-18'}節）に同じ組が重複または欠落")

    # --- 結合（ペア＋巡目） ---
    matches, today = [], _jst_today().isoformat()
    for s in sched:
        x = legs[(s["home"], s["away"])][0 if s["md"] <= half else 1]
        matches.append(dict(md=s["md"], date=s["date"], home=s["home"], away=s["away"],
                            hs=x[0] if x else None, **{"as": x[1] if x else None}))
    # ✅ 日程表は版が古いのが正常なので版日付では守れない。「予定日がまだ来ていないのに結果がある」で守る。
    future = [m for m in matches if m["hs"] is not None and m["date"] > today]
    if future:
        raise RuntimeError(f"星取表に結果があるのに日程表の予定日({future[0]['date']})がまだ来ていない試合が"
                           f"{len(future)}件（例: 第{future[0]['md']}節 {future[0]['home']}×{future[0]['away']}）"
                           f"。日程表の版が古く、延期で日付が動いた疑い")
    played = [m for m in matches if m["hs"] is not None]
    if sum(v["played"] for v in standings.values()) != 2 * len(played):
        raise RuntimeError(f"順位表の試合数の合計{sum(v['played'] for v in standings.values())}が"
                           f"星取表の結果{len(played)}試合×2と合わない")
    return standings, matches


# ============================================================
# 京都（kyoto-fa.or.jp）— 府協会の TOPリーグ日程PDF（結果入り・**主資料**）＋ リザルトPDF（星取表・検算用）（2026-09-16追加）
#   入口: /archives.php?category=13（第2種）→ リンク文字「高円宮杯JFA U-18サッカーリーグ{年}京都」の記事。
#   ⚠️ 記事IDは年度で変わるので直リンクにしない。
# ⚠️⚠️ **`/upload/` のPDFは「ホットリンク防止」で、Referer が無いと403になる。**
#    **記事ページのURLを Referer に付ければ素の requests で200**（2026-09-16実測：117,871バイト／216,020バイト）。
#    リンクを辿るブラウザは必ず Referer を送るので、これは回避ではなく通常の辿り方。
#    ❌ 403になったからといってヘッドレスブラウザに倒さないこと。
#    📌 この403のせいで「京都は中身未確認＝移行できない」と2か月扱っていた。**「403だった」で止めない。**
# ⚠️ 記事には1部〜4部の スケジュール／リザルト が並ぶ。ファイル名 `{年}u18_{部}{s|r}{MMDD}.pdf` の **`_1s`/`_1r` だけ**を取る。
# ⭐️ 日程PDFは1試合1行で**節の列がある**（全18節×5試合＝90）。巡目は節番号で決まる（第1〜9節＝1巡目＝星取表の上段）。
#    ⚠️⚠️ **延期分は「元の節番号のまま、ずっと後ろの日付」で出る**（第7節に7/4、第9節に8/30）。
#      **節番号の順＝日付の順ではない。日付から節を推定しないこと。**
#    ⚠️ 節・月・日・曜・会場は結合セルなので、行ごとに引き継ぐ（`page_tables` で読める）。
# ⚠️ 星取表のマスは読まない（上段・下段が1つの文字列につながる形）。**スコアは日程PDFが正本**、星取表は
#    順位表（勝分敗・勝点・得点・失点・得失差・順位）だけを使い、既定ゲート（全項目一致）で突き合わせる。
# ⚠️ 版日付は**ファイル名の MMDD**（本文の「◯月◯日現在」はデータの基準日で、1日ずれるのが正常なので突き合わせない）。
#    2本のファイル名の MMDD が一致することだけ確かめる（片方だけ更新されたら止める）。
# ⚠️⚠️ 名寄せが5例目で最悪。**成美A・サンガB・立宇治A は既存名（福知山成美A・京都サンガU-18B・立命館宇治A）を
#    部分文字列として含まない**ので明示の対応表が要る。A/B/C は全角と半角が同じPDFの中で混在する（NFKCで吸収）。
#    ⚠️ A/B/C はチーム区分（A＝トップ・B＝2nd・C＝3rd）。落とさない。
# ⚠️ ホーム/アウェイは無い。会場に学校のグラウンドが出るが、左右とも会場ともホームを表していない
#    （東山総合で東山が右、京都共栄Gで京都共栄が右、橘のスタジアムに橘が出ない試合がある＝中立会場）。
# 年度切り替え: 記事のリンク文字の年で追随する。
# ============================================================
_KYOTO_LIST = "https://www.kyoto-fa.or.jp/archives.php?category=13"


def read_kyoto(cfg: dict) -> tuple[dict, list[dict]]:
    from urllib.parse import urljoin
    year = str(SEASON_YEAR)
    nfkc = lambda s: re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))
    soup = BeautifulSoup(fetch_html(_KYOTO_LIST, encoding=None), "html.parser")
    time.sleep(SLEEP)
    arts = [urljoin(_KYOTO_LIST, a["href"]) for a in soup.find_all("a", href=True)
            if f"U-18サッカーリーグ{year}京都" in nfkc(a.get_text()) and "archives.php?id=" in a["href"]]
    arts = list(dict.fromkeys(arts))
    if len(arts) != 1:
        raise RuntimeError(f"入口に{year}年のU-18リーグの記事が{len(arts)}件（1件のはず）")
    art_url = arts[0]
    art = BeautifulSoup(fetch_html(art_url, encoding=None), "html.parser")
    time.sleep(SLEEP)
    pdfs = {}
    for a in art.find_all("a", href=True):
        u = urljoin(art_url, a["href"])
        m = re.search(r"u18_1([sr])(\d{4})\.pdf$", u)
        if m:
            pdfs.setdefault(m.group(1), []).append((u, m.group(2)))
    for k, what in (("s", "日程（スケジュール）"), ("r", "星取表（リザルト）")):
        if len(pdfs.get(k, [])) != 1:
            raise RuntimeError(f"記事に1部の{what}PDFが{len(pdfs.get(k, []))}本（1本のはず）")
    if pdfs["s"][0][1] != pdfs["r"][0][1]:
        raise RuntimeError(f"日程PDF({pdfs['s'][0][1]})と星取表PDF({pdfs['r'][0][1]})のファイル名の版日付が違う"
                           f"（片方だけ更新されている）")
    version = pdf_source.version_from_label(pdfs["s"][0][1], SEASON_YEAR)
    if not version or not version.startswith(f"{year}-"):
        raise RuntimeError(f"版日付（ファイル名の MMDD）が{year}年として読めない: {pdfs['s'][0][0]}")
    # ⚠️ ホットリンク防止。**記事ページを Referer に付ける**（直リンクだと403）。
    headers = dict(HEADERS, Referer=art_url)

    # --- 日程PDF（結果入り・主資料） ---
    content = pdf_source.fetch_pdf(pdfs["s"][0][0], headers, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        if f"サッカーリーグ{year}京都TOPリーグ日程表" not in nfkc(pdf.pages[0].extract_text() or ""):
            raise RuntimeError(f"日程PDFの表題が{year}年の京都TOPリーグでない")
        rows = [r for pg in pdf.pages for t in pdf_source.page_tables(pg) for r in t]
    n = cfg["teams"]
    half = n - 1
    md = mon = day = None
    matches = []
    for r in rows:
        c = [nfkc(x) for x in r]
        if len(c) != 10:
            raise RuntimeError(f"日程PDFの行の列数が想定と違う: {r}")
        if c[0] == "節":
            continue
        if c[0].isdigit():
            md = int(c[0])
        if c[1].isdigit():
            mon = int(c[1])
        if c[2].isdigit():
            day = int(c[2])
        home, away = c[6], c[8]
        m = re.fullmatch(r"(\d+)-(\d+)", c[7])
        if not (home and away and md and mon and day):
            raise RuntimeError(f"日程PDFの行が読めない（節・日付・対戦のいずれかが無い）: {r}")
        matches.append(dict(md=md, date=f"{year}-{mon:02d}-{day:02d}", home=home, away=away,
                            hs=int(m.group(1)) if m else None,
                            **{"as": int(m.group(2)) if m else None}))
    if len(matches) != n * (n - 1):
        raise RuntimeError(f"日程PDFから{len(matches)}試合（{n * (n - 1)}試合のはず）")
    if any(sum(1 for m in matches if m["md"] == k) != n // 2 for k in range(1, 2 * half + 1)):
        raise RuntimeError("日程PDFの節ごとの試合数が想定と違う")
    for rnd in (1, 2):
        ps = [frozenset((m["home"], m["away"])) for m in matches if (m["md"] <= half) == (rnd == 1)]
        if len(set(ps)) != len(ps) or len(ps) != n * (n - 1) // 2:
            raise RuntimeError(f"日程PDFの{rnd}巡目（第{'1-9' if rnd == 1 else '10-18'}節）に同じ組が重複または欠落")
    played = [m for m in matches if m["hs"] is not None]
    # 守り：1巡目が未消化なのに2巡目だけ結果がある組（巡目の前提が崩れた形）
    done = {frozenset((m["home"], m["away"])) for m in played if m["md"] <= half}
    bad = [m for m in played if m["md"] > half and frozenset((m["home"], m["away"])) not in done]
    if bad:
        print(f"       （京都: 1巡目が未消化なのに2巡目に結果がある組が{len(bad)}件"
              f"：例 第{bad[0]['md']}節 {bad[0]['home']}×{bad[0]['away']}。延期の可能性）")
    future = [m for m in played if m["date"] > version]
    if future:
        raise RuntimeError(f"版日付({version})より後の予定日に結果がある試合が{len(future)}件（例: {future[0]['date']} "
                           f"{future[0]['home']}×{future[0]['away']}）")

    # --- 星取表PDF（順位表だけを使う） ---
    content = pdf_source.fetch_pdf(pdfs["r"][0][0], headers, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        text = "".join(pg.extract_text() or "" for pg in pdf.pages)
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    if f"サッカーリーグ{year}京都" not in nfkc(text):
        raise RuntimeError(f"星取表PDFの表題が{year}年の京都でない")
    want = ["勝", "分", "負", "勝点", "得点", "失点", "得失差", "順位"]
    grids = [t for t in tables if t and [nfkc(c) for c in t[0][-8:]] == want]
    if len(grids) != 1 or len(grids[0]) != 1 + n:
        raise RuntimeError(f"星取表PDFの順位表が想定と違う（{len(grids)}個・"
                           f"{len(grids[0]) if grids else 0}行）")
    rename = cfg.get("hoshitori_names", {})
    standings, ranks = {}, []
    for r in grids[0][1:]:
        team = rename.get(nfkc(r[0]), nfkc(r[0]))
        v = [nfkc(x) for x in r[-8:]]
        if not all(re.fullmatch(r"[+-]?\d+", x) for x in v):
            raise RuntimeError(f"星取表 {team} の順位表の数値が読めない: {v}")
        won, drawn, lost, pts, gf, ga, gd, rank = (int(x) for x in v)
        if 3 * won + drawn != pts or gf - ga != gd:
            raise RuntimeError(f"星取表 {team} の自己検算が合わない（{won}勝{drawn}分{lost}敗・勝点{pts}・{gf}-{ga}・得失差{gd}）")
        standings[team] = dict(pts=pts, played=won + drawn + lost, won=won, drawn=drawn,
                               lost=lost, gf=gf, ga=ga)
        ranks.append((rank, team))
    if sorted(standings) != sorted({m["home"] for m in matches} | {m["away"] for m in matches}):
        raise RuntimeError(f"星取表のチームと日程PDFのチームが合わない: {sorted(standings)}")
    if sum(v["gf"] - v["ga"] for v in standings.values()) != 0:
        raise RuntimeError("順位表の得失差の合計が0でない（読み取りの誤り、または出典の誤り）")
    if sum(v["played"] for v in standings.values()) != 2 * len(played):
        raise RuntimeError(f"星取表の勝分敗の合計{sum(v['played'] for v in standings.values())}が"
                           f"日程PDFの結果{len(played)}試合×2と合わない")
    # ⚠️ 同着（大谷A・洛北Aが揃って5位）があるので「順位の昇順＝勝点の降順」は厳密不等号にしない
    for (r1, t1), (r2, t2) in zip(sorted(ranks), sorted(ranks)[1:]):
        if standings[t1]["pts"] < standings[t2]["pts"]:
            raise RuntimeError(f"星取表の順位が勝点の降順でない: {r1}位 {t1}（勝点{standings[t1]['pts']}）→ "
                               f"{r2}位 {t2}（勝点{standings[t2]['pts']}）")
    return standings, matches


# ============================================================
# 愛媛（efa.jp）— 県協会の E1日程PDF（結果入り・**主資料**）＋ E1星取表PDF（検算用）（2026-09-16追加）
#   入口: /meeting/second/?y={年}（第2種）→ リンク文字に「リーグ{年}愛媛」を含む記事（fetch_pdf_scorers.discover_ehime と同じ経路）。
#   ⚠️ 記事IDは年度で変わるので直リンクにしない。
# ⚠️⚠️ **同じ記事に E2A・E2B・E3東予A/B・E3中予・E3南予 の日程と星取表が並ぶ。** リンク文字が「E1日程」「E1星取表」で
#    始まるものだけを取る（"E2A日程" は前方一致で外れる）。
# ⭐️ 日程PDFは**1試合1行**（月・日・曜日・会場・時間・対戦・結果・対戦）で、前期45＋後期45＝90試合。
#    ⚠️ 1行だけ日付・会場・時刻が空の行がある（2026-09-15版＝後期の 済美×松山工業。PDF上は赤地＝日程未定）。
#      **落とさずに日付なしの未消化として持つ。** 逆に「日付が無いのにスコアがある」行は読み取りの崩れなので止める。
# ⚠️ **「節」の列が無い。** 巡目は日程PDFの「前期／後期」の見出しで分かる（星取表の表題も「上段：前期、下段：後期」）。
#    → 星取表のマスは読まない（未消化が `―` だらけで、上段・下段が1つの文字列につながる形）。**スコアは日程PDFが正本**、
#      星取表は**順位表（勝分敗・勝点・得点・失点・得失点・順位）だけ**を使い、既定ゲート（全項目一致）で突き合わせる。
# ⚠️⚠️ **両PDFとも本文に版日付が無い。** リンク文字（`E1日程(9/15)`）とファイル名（`2-26-E1_0915.pdf`）だけ。
#    → `version_from_label`（年なし＝シーズン年を補う）。**2本の版日付が食い違ったら止める**
#      （星取表だけ古いと、新しい日程と古い順位表を突き合わせてゲートが誤って落ちる）。
# ⚠️ **ホーム/アウェイは無い。** 会場10種すべてが公共施設で学校名の会場が0（しおさい20・今治SP17・梅津寺14・桜井9・
#    平野9・北条球技場8・SAKURAフィールド4・北条陸上4・あけぼの3・丸山1＝2026-09-15）＝完全なセントラル開催。
#    home/away は「日程PDFの左側＝home」の格納規約で事実ではない。cross_table.NO_HOME_AWAY_SLUGS で H/A を出さない。
# ⚠️ 星取表だけ表記が違う（愛媛FCS→愛媛FCU-18S・FC今治NEXT→FC今治U-18S）。日程PDFは既存JSONと同じ表記。
#    ❌ fetch_pdf_scorers.py の EHIME_ALIASES は得点王用で「愛媛FCS」を持たない。流用しない。
# 年度切り替え: 入口の ?y= と記事のリンク文字の年で追随する。
# ============================================================
_EHIME_LIST = "https://efa.jp/meeting/second/?y={}"

# ⚠️ **出典（県協会）そのものの既知の誤り**（2026-09-16新設）。値は「公式の順位表 − 日程PDFから計算した値」の差。
#    ❌ 「検算しない」形にはしないこと。差を書くと、**協会が直した瞬間に差が0になって止まり、
#       コードのほうから「この例外を消せ」と言ってくる**。絶対値で書くと試合が進むたびに壊れる。
# 愛媛（2026-09-15版の星取表）：大洲の行×FC今治NEXTの列（前期）が「5―3 ●」＝左右が逆。正しくは 3―5。
#   そのため星取表の**大洲の合計だけ**が 得点+2 / 失点-2 ずれている（勝分敗・勝点は正しい）。
#   証拠 (1) 全マスの鏡チェックで食い違うのはこの1組だけ（FC今治NEXTの行は 5―3 ○ で日程PDFと一致）
#        (2) ○●とスコアが矛盾するのもこの1マスだけ
#        (3) 得失点の列の合計が0でなく +4（このマスを直すと0になる）
#   外す条件：協会が星取表を直すと差が0になり read_ehime が止まる。止まったらこの項目を消す。
# 高知（2026-09-14版の星取表）：高知小津の「得点」の合計欄だけが3多い（表25・マスから計算すると22）。
#   証拠 (1) 鏡チェックは40試合すべて一致＝マスは正しい（＝愛媛のような「マスが逆向き」ではない）
#        (2) 8チーム中7チームは合計が一致し、高知小津も勝分敗・勝点・失点は一致
#        (3) 得点を22にすると Σ得点＝Σ失点＝187、Σ得失点差＝0 になる
#   外す条件：協会が直すと差が0になり read_kochi が止まる。止まったらこの項目を消す。
# ============================================================
# 1つのマスに2試合が並ぶ出典で、どちらがどの試合かを決めるための共通ヘルパー（2026-09-17追加）
# ============================================================
# ⚠️⚠️ **マスの並び順に意味があるとは限らない。**
#   大阪2部A/B/Cで実測したところ、節順・日付順・試合番号順のどれで並べても 26/44 しか当たらず
#   （でたらめなら22/44）、21ペア中9ペアが「同じ2つの結果が逆の日付に付く」形で食い違った。
#   大阪1部は 18/20 が「1件目＝前期」で当たったが、**これも偶然の可能性がある**（2部の結果から）。
#
# ✅ そこで、並び順に頼るのは**新しく増えた分だけ**にする。
#   1. すでに保存済みの試合は、**スコアで突き合わせて日付を動かさない**（前回の割り当てを引き継ぐ）。
#   2. 残ったマス＝新しく消化された試合なので、**残った予定日**（予定日を過ぎているもの）を順に当てる。
#   3. 残りが2件以上あって、**スコアが違う**なら曖昧なので止める（人に見せる）。
#      ⚠️ 残り2件のスコアが同じなら、どちらに当てても保存内容が変わらないので止めない。
#   📌 既存JSONがそのまま前回のスナップショットになるので、追加の保存領域は要らない。
#   ⚠️ **移行の時点ですでに両巡終わっているペアは、この仕組みでは守れない。**
#      移行時に既存データで1件ずつ検証して初期値を固定すること（大阪1部の10ペアがそれ）。
def _existing_played(pref: str) -> list[dict]:
    """既存JSON（前回のスナップショット）の消化済み試合。読めなければ空。

    ⚠️ ファイル名は `pref-{pref}-1.json` の決め打ち。**2部（pref-osaka-2a 等）に広げるときは効かない**ので、
       そのときは slug を渡す形に変えること。
    ⚠️ 止まったときの逃げ道：出典が誤記を正しく訂正すると check_legs_not_swapped が止まり続ける。
       訂正が正しいと確認できたら、**その試合を pref-*-1.json から消す（または hs/as を null にする）**
       ＝前回のスナップショットから外してコミットすれば、次の実行で割り当て直される。"""
    try:
        d = json.loads((DIR / f"pref-{pref}-1.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    return [m for m in d.get("matches", [])
            if m.get("status") == "played" and m.get("hs") is not None and m.get("date")]


def assign_legs_incrementally(pref: str, a: str, b: str, legs: list, sched: list, cutoff: str) -> list:
    """ペア (a,b) のマスの結果 legs（aから見た (gf,ga) の並び）を、日程 sched（節順）に割り当てる。

    戻り値は sched と同じ長さのリストで、各要素は (hs, as) か None（その試合はまだ未消化）。
    ⚠️ 並び順に頼るのは「前回に無かった分」だけ（上のコメント参照）。曖昧なら RuntimeError。
    ⚠️ `cutoff` は**出典の版日付**を渡すこと（今日ではない）。版が 9/13 なら 9/14 以降の枠に結果は入りえないので、
       空き枠がそのぶん狭まり、**曖昧さを後から検出するのではなく最初から減らせる**。
    """
    prev = {}
    for m in _existing_played(pref):
        if {m.get("home"), m.get("away")} != {a, b}:
            continue
        s = (m["hs"], m["as"]) if m["home"] == a else (m["as"], m["hs"])
        prev.setdefault(m["date"], []).append(s)
    out = [None] * len(sched)
    rest = list(legs)
    # 1. 前回と同じスコアの試合は、前回と同じ日付のまま動かさない
    for i, s in enumerate(sched):
        for cand in prev.get(s["date"], []):
            if cand in rest:
                out[i] = cand
                rest.remove(cand)
                break
    if not rest:
        return out
    # 2. 残りは「予定日を過ぎていて、まだ埋まっていない」枠へ節の順に当てる
    free = [i for i, s in enumerate(sched) if out[i] is None and s["date"] <= cutoff]
    if len(rest) > len(free):
        raise RuntimeError(f"{a}×{b}: 結果が{len(legs)}件あるのに、版日付までに予定されていた空き枠は{len(free)}件"
                           f"（結果があるのに予定日が来ていない）")
    # 3-a. 空き枠のほうが多い＝どの試合が消化されたのか決められない（zip で黙って早い枠に当てない）
    #      例：大阪1部の節9（6/27 大阪学院×近大附属）は6/27を過ぎても未消化で、裏の節17は11/29。
    #      12月に片方だけ結果が出ると rest=1・free=2 になる。通常進行（前期済み＋後期1件）は rest=1・free=1。
    if len(rest) < len(free):
        raise RuntimeError(f"{a}×{b}: 新しく増えた結果が{len(rest)}件なのに、空いている枠が{len(free)}件"
                           f"（{[sched[i]['date'] for i in free]}）。どの試合の結果か決められないので人が確認すること")
    # 3-b. 残りが2件以上でスコアが違うなら、どちらがどちらか決められない
    #      ⚠️ 同じスコアなら、どちらに当てても保存内容が変わらないので止めない。
    if len(rest) > 1 and len(set(rest)) > 1:
        raise RuntimeError(f"{a}×{b}: 新しく増えた結果が{len(rest)}件（{rest}）あり、どちらがどの日付か決められない"
                           f"（出典のマスの並び順は当てにならない）。人が確認して割り当てること")
    for i, s in zip(free, rest):
        out[i] = s
    return out


def check_legs_not_swapped(pref: str, matches: list[dict]) -> None:
    """すでに保存済みの試合の日付に、別のスコアが付いていないかを見る守り（2026-09-17追加）。

    ⚠️ 巡目の割り当てを「並び順」や「ペアの何回目か」で決めている県（山梨など）向け。
       **同じペアの2つの結果が入れ替わった**とき、順位表は変わらないので検算では捕まらない。
       前回の保存内容と突き合わせれば、入れ替わりだけをはっきり捕まえられる。
    """
    prev = {}
    for m in _existing_played(pref):
        prev[(m["date"], frozenset((m.get("home"), m.get("away"))))] = \
            (m["hs"], m["as"]) if m.get("home") <= m.get("away") else (m["as"], m["hs"])
    for m in matches:
        if m.get("hs") is None or not m.get("date"):
            continue
        key = (m["date"], frozenset((m["home"], m["away"])))
        if key not in prev:
            continue
        now = (m["hs"], m["as"]) if m["home"] <= m["away"] else (m["as"], m["hs"])
        if now != prev[key]:
            raise RuntimeError(f"{m['date']} {m['home']}×{m['away']}: 前回は {prev[key]} で保存されていたのに"
                               f"今回は {now}（同じペアの2試合が入れ替わった疑い。巡目の割り当てを確認すること）")


KNOWN_SOURCE_ERRORS: dict[str, dict[str, dict[str, int]]] = {
    "ehime": {"大洲": {"gf": +2, "ga": -2}},
    "kochi": {"高知小津": {"gf": +3}},
}


def read_ehime(cfg: dict) -> tuple[dict, list[dict]]:
    from urllib.parse import urljoin
    year = str(SEASON_YEAR)
    nfkc = lambda s: re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))
    entry = _EHIME_LIST.format(year)
    soup = BeautifulSoup(fetch_html(entry, encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    arts = [urljoin(entry, a["href"]) for a in soup.find_all("a", href=True)
            if f"リーグ{year}愛媛" in nfkc(a.get_text())]
    if len(arts) != 1:
        raise RuntimeError(f"入口に{year}年のEリーグの記事が{len(arts)}件（1件のはず）")
    art = BeautifulSoup(fetch_html(arts[0], encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    links = collections.defaultdict(list)
    for a in art.find_all("a", href=True):
        if not a["href"].lower().endswith(".pdf"):
            continue
        for want in ("E1日程", "E1星取表"):
            if nfkc(a.get_text()).startswith(want):
                links[want].append(urljoin(arts[0], a["href"]))
    versions = {}
    for want in ("E1日程", "E1星取表"):
        if len(links[want]) != 1:
            raise RuntimeError(f"記事に「{want}」のPDFが{len(links[want])}本（1本のはず）")
        versions[want] = pdf_source.version_from_label(links[want][0], SEASON_YEAR)
        if not versions[want] or not versions[want].startswith(f"{year}-"):
            raise RuntimeError(f"「{want}」PDFの版日付（ファイル名）が{year}年として読めない: {links[want][0]}")
    if versions["E1日程"] != versions["E1星取表"]:
        raise RuntimeError(f"日程PDF({versions['E1日程']})と星取表PDF({versions['E1星取表']})の版日付が違う"
                           f"（片方だけ更新されている。突き合わせが誤って落ちるので止める）")
    version = versions["E1日程"]

    # --- 日程PDF（結果入り・主資料） ---
    content = pdf_source.fetch_pdf(links["E1日程"][0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        rows = [r for pg in pdf.pages for t in pdf_source.page_tables(pg) for r in t]
    matches, seg, nodate = [], None, 0
    for r in rows:
        if len(r) != 10:
            raise RuntimeError(f"日程PDFの行の列数が想定と違う: {r}")
        c = [nfkc(x) for x in r]
        if c[0] == "月":
            continue
        if c[0] in ("前期", "後期"):
            seg = c[0]
            continue
        home, away = c[5], c[9]
        hs, as_ = (int(c[6]) if c[6].isdigit() else None), (int(c[8]) if c[8].isdigit() else None)
        if not (home and away and seg):
            raise RuntimeError(f"日程PDFの行が読めない（対戦または前期/後期の見出しが無い）: {r}")
        if c[0].isdigit() and c[1].isdigit():
            date = f"{year}-{int(c[0]):02d}-{int(c[1]):02d}"
        else:
            # 日程未定の行（PDF上は赤地）。落とさずに日付なしの未消化として持つ。
            if hs is not None or as_ is not None:
                raise RuntimeError(f"日程PDFに「日付が無いのに結果がある」行がある（読み取りの崩れ）: {r}")
            date, nodate = "", nodate + 1
        if (hs is None) != (as_ is None):
            raise RuntimeError(f"日程PDFの結果が片側だけ入っている: {r}")
        matches.append(dict(seg=seg, date=date, home=home, away=away, hs=hs, **{"as": as_}))
    n = cfg["teams"]
    if len(matches) != n * (n - 1):
        raise RuntimeError(f"日程PDFから{len(matches)}試合（{n * (n - 1)}試合のはず）")
    for s in ("前期", "後期"):
        ps = [frozenset((m["home"], m["away"])) for m in matches if m["seg"] == s]
        if len(set(ps)) != len(ps) or len(ps) != n * (n - 1) // 2:
            raise RuntimeError(f"日程PDFの{s}が{len(ps)}試合・重複{len(ps) - len(set(ps))}件（同じ組が1回ずつのはず）")
    if nodate:
        print(f"       （愛媛: 日程未定の試合が{nodate}件。日付なしの未消化として持つ）")
    played = [m for m in matches if m["hs"] is not None]
    future = [m for m in played if m["date"] > version]
    if future:
        raise RuntimeError(f"版日付({version})より後の予定日に結果がある試合が{len(future)}件（例: {future[0]['date']} "
                           f"{future[0]['home']}×{future[0]['away']}）")

    # --- 星取表PDF（順位表だけを使う） ---
    content = pdf_source.fetch_pdf(links["E1星取表"][0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        text = "".join(pg.extract_text() or "" for pg in pdf.pages)
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    if f"{year}E1リーグ" not in nfkc(text):
        raise RuntimeError(f"星取表PDFの表題が{year}年のE1リーグでない")
    want = ["勝", "分", "負", "勝点", "得点", "失点", "得失点", "順位"]
    grids = [t for t in tables if t and [nfkc(c) for c in t[0][-8:]] == want]
    if len(grids) != 1:
        raise RuntimeError(f"星取表PDFの順位表が{len(grids)}個")
    rename = cfg.get("hoshitori_names", {})
    standings, ranks = {}, []
    for r in grids[0][1:]:
        if not re.fullmatch(r"[A-Z]", nfkc(r[0])):
            continue                      # 下段（2巡目）の行。マスは読まない
        team = rename.get(nfkc(r[1]), nfkc(r[1]))
        v = [nfkc(x) for x in r[-8:]]
        if not all(re.fullmatch(r"-?\d+", x) for x in v):
            raise RuntimeError(f"星取表 {team} の順位表の数値が読めない: {v}")
        won, drawn, lost, pts, gf, ga, gd, rank = (int(x) for x in v)
        if 3 * won + drawn != pts or gf - ga != gd:
            raise RuntimeError(f"星取表 {team} の自己検算が合わない（{won}勝{drawn}分{lost}敗・勝点{pts}・{gf}-{ga}・得失点{gd}）")
        standings[team] = dict(pts=pts, played=won + drawn + lost, won=won, drawn=drawn,
                               lost=lost, gf=gf, ga=ga)
        ranks.append((rank, team))
    if len(standings) != n:
        raise RuntimeError(f"星取表の順位表が{len(standings)}チーム（{n}チームのはず）")
    if sorted(standings) != sorted({m["home"] for m in matches} | {m["away"] for m in matches}):
        raise RuntimeError("星取表のチームと日程PDFのチームが合わない")

    # ✅ 星取表の順位表と、日程PDFの結果から計算した値を1チームずつ突き合わせる。
    #    既知の出典の誤り（KNOWN_SOURCE_ERRORS）は「公式 − 計算」の差として明示し、その差ちょうどでなければ止める。
    #    ⚠️ 差が0になった＝協会が直した。そのときも止める（例外を消させるため）。
    mine = {t: dict(pts=0, played=0, won=0, drawn=0, lost=0, gf=0, ga=0) for t in standings}
    for m in played:
        for t, gf, ga in ((m["home"], m["hs"], m["as"]), (m["away"], m["as"], m["hs"])):
            s = mine[t]
            s["played"] += 1
            s["gf"] += gf
            s["ga"] += ga
            s["won"] += gf > ga
            s["drawn"] += gf == ga
            s["lost"] += gf < ga
            s["pts"] += 3 if gf > ga else 1 if gf == ga else 0
    known = KNOWN_SOURCE_ERRORS.get("ehime", {})
    for team, off in standings.items():
        want = {k: 0 for k in off}
        want.update(known.get(team, {}))
        got = {k: off[k] - mine[team][k] for k in off}
        if got != want:
            extra = ("。協会が直したなら KNOWN_SOURCE_ERRORS から愛媛の項目を消すこと"
                     if known.get(team) else "")
            raise RuntimeError(f"星取表 {team} の順位表と日程PDFの結果が合わない（公式−計算＝"
                               f"{ {k: v for k, v in got.items() if v} }・見込みは"
                               f"{ {k: v for k, v in want.items() if v} or '差なし' }）{extra}")
    standings = {t: dict(mine[t]) for t in standings}   # 既知の差を除いた値＝日程PDFと一致する値
    if sum(v["gf"] - v["ga"] for v in standings.values()) != 0:
        raise RuntimeError("順位表の得失点の合計が0でない（読み取りの誤り、または出典の誤り）")
    for (r1, t1), (r2, t2) in zip(sorted(ranks), sorted(ranks)[1:]):
        if standings[t1]["pts"] < standings[t2]["pts"]:
            raise RuntimeError(f"星取表の順位が勝点の降順でない: {r1}位 {t1}（勝点{standings[t1]['pts']}）→ "
                               f"{r2}位 {t2}（勝点{standings[t2]['pts']}）")
    # 星取表の消化数と日程PDFの結果数（勝分敗の合計は1試合2件）
    if sum(v["played"] for v in standings.values()) != 2 * len(played):
        raise RuntimeError(f"星取表の勝分敗の合計{sum(v['played'] for v in standings.values())}が"
                           f"日程PDFの結果{len(played)}試合×2と合わない")
    return standings, [dict(date=m["date"], home=m["home"], away=m["away"],
                            hs=m["hs"], **{"as": m["as"]}) for m in matches]


# ============================================================
# 三重（fa-mie.jp）— 県協会の星取表PDF＋日程および組合せPDF（2026-09-15追加）
#   入口: /category2/（2種）。1部の <tr>（「高円宮杯JFA U-18サッカーリーグ{年} 三重県１部」）に
#   大会要項／日程および組合せ／星取表／得点ランキング の4本が並ぶ（得点は fetch_pdf_scorers.py の discover_mie）。
# ⚠️⚠️ 「日程および組合せ」は選手権のニュース行にも同じ文字で出る → **必ず1部の <tr> に絞ってから**リンク文字で選ぶ。
# ⚠️⚠️ **星取表にホーム/アウェイも日付も無い。** 各マスは上段＝前期（第1〜7節）・下段＝後期（第8〜14節）。
#    前期・後期の中では同じ組が1回ずつなので、日程表の節で上段／下段に一意に結べる（延期で日付が前後しても崩れない）。
#    表として読むと、上段と下段は別の行（チーム名のある行＋チーム名の無い行）に分かれる。
# ⚠️ 向きは格納規約（日程表の左側＝home）で事実ではない（設定コメント参照）。後期は前期の左右が入れ替わっているが、
#    総当たりを機械的に組めば自然にそうなるので、ホーム/アウェイの証拠にはならない。
# ⚠️⚠️ **星取表の右の数値（勝点・得失点差・総得点・総失点）は左の星取表の行順、さらに右の「順位＋チーム名」は
#    勝点順の別の表。** 数値を隣のチーム名に結ぶと順位表が丸ごと壊れる（「1位 海星＝勝点19」になる）。
#    → 数値は行のチームに結び、「マスから数えた勝点・得点・失点との一致」と「順位の昇順＝勝点の降順」で確かめる。
# ⚠️ 日程表は前期・後期が左右2つの表。第11節は2日（9/26・9/27）に分かれるので日付は行ごとに引き継ぐ。
#    第14節は時刻が「未定」（時刻は使わないので行を落とさない）。
# ✅ 版日付＝星取表本文の `2026/09/13 現在`。表題の年も必須。
# 年度切り替え: 入口は固定。行の年・表題の年で前年度のPDFを読む事故を止める。
# ============================================================
_MIE_LEG_RE = re.compile(r"(\d+)([○●△])(\d+)")


def read_mie(cfg: dict) -> tuple[dict, list[dict]]:
    from urllib.parse import urljoin
    year = str(SEASON_YEAR)
    nfkc = lambda s: re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))
    soup = BeautifulSoup(fetch_html(cfg["source"], encoding="utf-8"), "html.parser")
    time.sleep(SLEEP)
    trs = [tr for tr in soup.find_all("tr")
           if f"U-18サッカーリーグ{year}三重県1部" in nfkc(tr.get_text()) and tr.find("a", href=True)]
    if len(trs) != 1:
        raise RuntimeError(f"入口ページに{year}年の1部の行が{len(trs)}件（1件のはず）")
    links = collections.defaultdict(list)
    for a in trs[0].find_all("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            links[nfkc(a.get_text())].append(urljoin(cfg["source"], a["href"]))
    for want in ("星取表", "日程および組合せ"):
        if len(links[want]) != 1:
            raise RuntimeError(f"1部の行に「{want}」のPDFが{len(links[want])}本")

    # --- 星取表 ---
    content = pdf_source.fetch_pdf(links["星取表"][0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        text = "".join(pg.extract_text() or "" for pg in pdf.pages)
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    version = pdf_source.version_date(text)
    if f"サッカーリーグ{year}三重1部リーグ星取表" not in nfkc(text) or not version or not version.startswith(f"{year}-"):
        raise RuntimeError(f"星取表PDFの表題または版日付が{year}年でない（前年度のPDFの疑い）")
    n, half = cfg["teams"], cfg["teams"] - 1
    rename = cfg.get("hoshitori_names", {})
    name = lambda s: rename.get(nfkc(s), nfkc(s))
    nums = ["勝点", "得失点差", "総得点", "総失点"]
    grids = [t for t in tables if t and [nfkc(c) for c in t[0][1 + n:]] == nums]
    ranks = [t for t in tables if t and nfkc(t[0][0]) == "順位"]
    if len(grids) != 1 or len(ranks) != 1 or len(grids[0]) != 1 + 2 * n:
        raise RuntimeError(f"星取表PDFの表の形が想定と違う（星取表{len(grids)}個・順位表{len(ranks)}個）")
    grid = grids[0]
    teams = [name(h) for h in grid[0][1:1 + n]]

    def leg(s, me, opp):
        s = nfkc(s)
        if not s:
            return None
        m = _MIE_LEG_RE.fullmatch(s)
        if not m:
            raise RuntimeError(f"星取表 {me}×{opp} のマスが読めない: {s!r}")
        a, mark, b = int(m.group(1)), m.group(2), int(m.group(3))
        if mark != ("○" if a > b else "●" if a < b else "△"):
            raise RuntimeError(f"星取表 {me}×{opp}: ○●△とスコアが合わない {s!r}")
        return (a, b)

    standings, cells = {}, {}
    for k in range(n):
        upper, lower = grid[1 + 2 * k], grid[2 + 2 * k]
        me = name(upper[0])
        if me != teams[k] or nfkc(lower[0]):
            raise RuntimeError(f"星取表の{k + 1}行目のチーム {me} が列の並び {teams[k]} と合わない（または下段にチーム名）")
        pts, gd, gf, ga = (int(nfkc(x)) for x in upper[1 + n:1 + n + 4])
        if gf - ga != gd:
            raise RuntimeError(f"星取表 {me}: 総得点−総失点≠得失点差（読み取りの誤り）")
        mine = dict(pts=0, gf=0, ga=0)
        for j, opp in enumerate(teams):
            if j == k:
                if nfkc(upper[1 + j]) or nfkc(lower[1 + j]):
                    raise RuntimeError(f"星取表 {me} の対角のマスに文字がある")
                continue
            legs = [leg(upper[1 + j], me, opp), leg(lower[1 + j], me, opp)]
            # 守り①：上段が空なのに下段にだけ結果がある＝前期/後期の前提が崩れた
            if legs[0] is None and legs[1] is not None:
                raise RuntimeError(f"星取表 {me}×{opp}: 上段が空なのに下段に結果がある（巡目の前提が崩れた疑い）")
            cells[(me, opp)] = legs
            for x in legs:
                if x:
                    mine["pts"] += 3 if x[0] > x[1] else 1 if x[0] == x[1] else 0
                    mine["gf"] += x[0]
                    mine["ga"] += x[1]
        # ✅ 右の数値ブロックが「行のチーム」のものか（隣の順位一覧に結んでいないか）をマスから確かめる
        if mine != dict(pts=pts, gf=gf, ga=ga):
            raise RuntimeError(f"星取表 {me}: 右の数値（勝点{pts}・得点{gf}・失点{ga}）がマスから数えた値 {mine} と合わない")
        standings[me] = dict(pts=pts, gf=gf, ga=ga)
    # ✅ ○●△の個数（本文の文字数）＝読めた試合の片側数（取りこぼし対策）
    n_marks = sum(text.count(c) for c in "○●△")
    n_legs = sum(1 for legs in cells.values() for x in legs if x)
    if n_marks != n_legs:
        raise RuntimeError(f"星取表の○●△が{n_marks}個なのに、読めたスコアは{n_legs}個（取りこぼしの疑い）")
    for (a, b), legs in cells.items():            # ✅ 鏡チェック（上段・下段とも）
        if [None if x is None else (x[1], x[0]) for x in legs] != cells[(b, a)]:
            raise RuntimeError(f"星取表の鏡チェックが合わない: {a}×{b} {legs} / {b}×{a} {cells[(b, a)]}")
    # ✅ 順位一覧（勝点順の別の表）：チームがそろい、順位の昇順＝勝点の降順
    listed = []
    for r in ranks[0][1:]:
        m = re.fullmatch(r"(\d+)位(.+)", nfkc(r[0]))
        if not m or name(m.group(2)) not in standings:
            raise RuntimeError(f"星取表の順位一覧が読めない: {r}")
        listed.append((int(m.group(1)), name(m.group(2))))
    if sorted(t for _, t in listed) != sorted(teams):
        raise RuntimeError("星取表の順位一覧のチームが星取表と合わない")
    for (r1, t1), (r2, t2) in zip(listed, listed[1:]):
        if r1 > r2 or standings[t1]["pts"] < standings[t2]["pts"]:
            raise RuntimeError(f"星取表の順位一覧の並びが勝点の降順でない: {r1}位 {t1}（勝点{standings[t1]['pts']}）→ "
                               f"{r2}位 {t2}（勝点{standings[t2]['pts']}）")
    for r, t in listed:
        standings[t]["rank"] = r

    # --- 日程および組合せ（前期・後期の2つの表） ---
    content = pdf_source.fetch_pdf(links["日程および組合せ"][0], HEADERS, TIMEOUT, wait=SLEEP)
    time.sleep(SLEEP)
    with pdf_source.open_pdf(content) as pdf:
        text = "".join(pg.extract_text() or "" for pg in pdf.pages)
        tables = [t for pg in pdf.pages for t in pdf_source.page_tables(pg)]
    if f"サッカーリーグ{year}三重県1部リーグ日程" not in nfkc(text):
        raise RuntimeError(f"日程PDFの表題が{year}年の三重県1部でない")
    sched = []
    for t in tables:
        md, day = None, ""
        for r in t:
            if len(r) != 7 or nfkc(r[0]) == "節":
                continue
            mm = re.fullmatch(r"(\d+)節", nfkc(r[0]))
            if mm:
                md = int(mm.group(1))
            dm = re.fullmatch(r"(\d{1,2})/(\d{1,2})", nfkc(r[1]))
            if dm:
                day = f"{year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
            home, away = nfkc(r[3]), nfkc(r[5])
            if not (home in standings and away in standings and home != away and md and day):
                raise RuntimeError(f"日程表の行が読めない: {r}")
            sched.append(dict(md=md, date=day, home=home, away=away))
    if len(sched) != n * (n - 1) or any(sum(1 for s in sched if s["md"] == k) != n // 2
                                        for k in range(1, 2 * half + 1)):
        raise RuntimeError(f"日程表が{len(sched)}試合、または節ごとの試合数が{n // 2}でない")
    for rnd in (1, 2):
        ps = [frozenset((s["home"], s["away"])) for s in sched if (s["md"] <= half) == (rnd == 1)]
        if len(set(ps)) != len(ps) or len(ps) != n * (n - 1) // 2:
            raise RuntimeError(f"日程表の{'前' if rnd == 1 else '後'}期に同じ組が重複または欠落")

    # ✅ 守り②：各チームの上段・下段の件数が「星取表の版日付までに予定されていた試合数」と一致するか
    #    （節番号ではなく日付で数える。延期・前倒しがあると止まる＝そのときは実物を見て判断する）
    for team in teams:
        exp = [0, 0]
        for s in sched:
            if team in (s["home"], s["away"]) and s["date"] <= version:
                exp[0 if s["md"] <= half else 1] += 1
        got = [sum(1 for opp in teams if opp != team and cells[(team, opp)][i]) for i in (0, 1)]
        if got != exp:
            raise RuntimeError(f"星取表 {team} の上段・下段の件数 {got} が、日程表から見込んだ {exp}"
                               f"（版日付{version}以前）と違う（延期・前倒し、または上下段の判定崩れの疑い）")

    # --- 格納規約で試合を作る（日程表の左側＝home。前期＝上段・後期＝下段） ---
    matches = []
    for s in sched:
        x = cells[(s["home"], s["away"])][0 if s["md"] <= half else 1]
        matches.append(dict(md=s["md"], date=s["date"], home=s["home"], away=s["away"],
                            hs=x[0] if x else None, **{"as": x[1] if x else None}))
    today = _jst_today().isoformat()
    future = [m for m in matches if m["hs"] is not None and m["date"] > today]
    if future:
        raise RuntimeError(f"今日({today})より後の予定日に結果がある試合が{len(future)}件（例: {future[0]['date']} "
                           f"{future[0]['home']}×{future[0]['away']}）")
    return standings, matches


# ============================================================
# 栃木（api.lsin.jp「LSIN cloud」）— 星取表と日程が別ビューに分かれている
#   m=r … 星取表＋順位表（**成績の正本**）
#   m=s … スコア速報（**日付・時刻・会場の供給元**）
#   m=p … 組み合わせ（使わない）
#
# ⚠️ **1大会に3つのビューがある。** 2026-09-07に `m=r` だけを見て「日付が無いから
#    移行は見送り」と判断し、あとで撤回した。**出典を見るときは、他のビュー・他の
#    パラメータが無いかを必ず確認すること。**（同じ型を同日に4回踏んでいる：
#    宮崎=framesetの宣言だけ／神奈川=innerTextだけ／山口=ChromeのDOMだけ／栃木=m=rだけ）
#
# ⚠️⚠️ **BeautifulSoup の find_all は入れ子のテーブルまで再帰的に拾う。**
#    星取表のセルの中に `<table class="scoreDatail">` が入っているため、
#    素直に取ると 11行→**191行**、19列のはずが入れ子の td まで混ざって
#    順位表の列がずれる（勝点が `'2 1 - …'` になる）。
#    **行もセルも `find_parent("table") is table` で直下だけに絞る。**
#    ※ ブラウザの `table.rows` / `row.cells` は直下しか返さないので、
#      DOMで確認しているとこの差は見えない。**パーサのAPIの意味論の違い。**
#
# ⚠️ 1部の特定に「行数が11」は使えない（上記のとおり191行に見える）。
#    **直前の見出しテキスト「高円宮杯U-18リーグ１部」で特定する。**
#    ページには星取表が13個あり、2部以下や「(データ破損)」という表も含まれる。
#
# ⚠️ **勝敗と引き分けで書式が違う。**
#      勝敗   <td class="score">2 <i class="fa fa-circle"></i> 3</td>  → "2 3"
#      引分   <td class="score">2 △ 2</td>                             → "2 △ 2"（△は文字）
#      未消化 <td class="score last">- -</td>
#    空白区切りを前提にすると**引き分け（10レグ＝5試合）だけが丸ごと落ちる**。
#    各チームの不足数が「分」の数と一致する形で現れるので気づきにくい。
#    → **レグの文字列から数字と `-` のトークンを順に抜き、先頭2つを得点とする。**
#      これなら △ も ○ も明示的に扱わずに済む。
# ⚠️ **セルの textContent をまとめて数字で切ってはいけない。** 1stレグと2ndレグの間に
#    改行が無いので `5 0` と `6 0` が `5 06 0` に連結し、`06` という数字ができる。
#    **必ず td.score を1レグずつ取り出してから、そのレグの中だけでトークンを読む。**
#
# ⚠️ `m=s` には1試合足りないことがある（日時が未入力の試合）。**落とさずに日付だけ空にする。**
#    2026-09-07時点で1件（矢板中央Ｂ 2-3 國學院栃木）。件数はログに出す（増えていたら
#    m=s の入力が滞っているサイン）。
#
# 年度切り替え: e= を https://api.lsin.jp/?c=3 の大会一覧から拾う。
#              unit_id は m=s の units[...] の unit_name から引く（決め打ちしない）。
# ============================================================
_LSIN_UNIT_RE = re.compile(r'unit_id\s*:\s*(\d+)\s*,\s*unit_name\s*:\s*["\']([^"\']+)["\']')
_LSIN_TOKEN_RE = re.compile(r"\d+|-")
_LSIN_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_LSIN_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _lsin_legs(cell) -> list:
    """1セル（＝ある対戦カード）のレグを [(hs, as), None, ...] で返す。

    レグごとに td.score を取り出し、**そのレグの中だけで**トークンを読む。
    "2 3"→(2,3) ／ "2 △ 2"→(2,2) ／ "- -"→None
    """
    out = []
    for sc in cell.select("table.scoreDatail td.score"):
        txt = sc.get_text(" ", strip=True).replace("\xa0", " ")
        tok = _LSIN_TOKEN_RE.findall(txt)[:2]
        if len(tok) == 2 and tok[0].isdigit() and tok[1].isdigit():
            out.append((int(tok[0]), int(tok[1])))
        else:
            out.append(None)
    return out


def _lsin_schedule(url: str, unit_name: str) -> list[dict]:
    """m=s から**消化済み（試合終了）**のパネルだけを
    [{home, away, hs, as, date, kickoff, venue}] で返す。

    ⚠️ **未消化パネルを混ぜてはいけない。** m=s には未来の試合も入っているので、
       混ぜると**消化済み試合に未来の日付が付く**（2026-09-07に実際に踏んだ。
       9/6が最新のはずが9/13になった）。
    ⚠️ ステータスの判定は **.strip() してから**（先頭に空白が入る）。
    """
    html = fetch_html(url, encoding="utf-8", must_contain="マッチナンバー")
    time.sleep(SLEEP)
    m = next((mm for mm in _LSIN_UNIT_RE.finditer(html)
              if mm.group(2).strip() == unit_name), None)
    if not m:
        raise RuntimeError(f"m=s に unit_name {unit_name!r} が見つからない"
                           f"（年度が変わって名前が変わった可能性）")
    unit_id = m.group(1)
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for panel in soup.select(f'div[data-unitid="{unit_id}"]'):
        txt = panel.get_text(" ", strip=True).replace("\xa0", " ")
        if not txt.strip().startswith("試合終了"):
            continue                      # 未消化は日付の供給元にしない
        dm = _LSIN_DATE_RE.search(txt)
        if not dm:
            continue
        tm = _LSIN_TIME_RE.search(txt[dm.end():dm.end() + 20])
        vm = re.search(r"\[会場\]\s*(\S+)", txt)
        # チーム名の行 → その次の行が得点
        names, score = None, None
        trs = panel.find_all("tr")
        for i, tr in enumerate(trs):
            cs = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            cs = [c for c in cs if c]
            if len(cs) == 2 and not all(c.isdigit() for c in cs):
                names = cs
                for nxt in trs[i + 1:]:
                    ns = [c.get_text(" ", strip=True) for c in nxt.find_all(["td", "th"])]
                    ns = [c for c in ns if c]
                    if len(ns) == 2 and all(c.isdigit() for c in ns):
                        score = (int(ns[0]), int(ns[1]))
                    break
                break
        if not names or score is None:
            continue
        out.append(dict(home=names[0], away=names[1], hs=score[0],
                        **{"as": score[1]},
                        date=f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}",
                        kickoff=f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "",
                        venue=vm.group(1) if vm else ""))
    return out


def read_lsin(cfg: dict) -> tuple[dict, list[dict]]:
    base = f"https://api.lsin.jp/?e={cfg['event']}&c={cfg['club']}"
    unit_name = cfg["unit_name"]

    # --- m=r：星取表と順位表（成績の正本） ---
    soup = BeautifulSoup(fetch_html(f"{base}&m=r".replace("?e=", "?m=r&e="),
                                    encoding="utf-8", must_contain=unit_name),
                         "html.parser")
    time.sleep(SLEEP)
    # 各星取表の直前にある「見出しらしいテキスト」を1つ拾って、unit_name と突き合わせる。
    # ⚠️ 直前の非空テキストで止めてはいけない（空白や記号が挟まる）。
    #    「リーグ」か「部」を含む短い文字列を見出しとみなす。
    table = None
    for t in soup.find_all("table"):
        if not t.select("table.scoreDatail"):
            continue
        for prev in t.find_all_previous(string=True):
            txt = prev.strip()
            if not txt or len(txt) > 60:
                continue
            if "リーグ" not in txt and "部" not in txt:
                continue
            if txt == unit_name:
                table = t
            break
        if table is not None:
            break
    if table is None:
        raise RuntimeError(f"m=r に見出し {unit_name!r} の星取表が見つからない")

    # ★ 行もセルも直下だけを取る（入れ子の scoreDatail を拾わないため）
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]

    def cells(tr):
        return [c for c in tr.find_all(["td", "th"])
                if c.find_parent("table") is table]

    head = [c.get_text(" ", strip=True) for c in cells(rows[0])]
    col = {}
    for i, c in enumerate(head):
        key = c.replace(" ", "")
        for k, name in (("pts", "勝点"), ("won", "勝数"), ("drawn", "分数"),
                        ("lost", "負数"), ("gf", "得点"), ("ga", "失点")):
            if k not in col and key == name:
                col[k] = i
    n_teams = min(col.values()) - 1 if col else 0
    teams = head[1:1 + n_teams]
    expected = cfg.get("teams")
    if expected is not None and len(teams) != expected:
        raise RuntimeError(f"星取表のチーム数 {len(teams)} が設定の {expected} と違う")
    if len(rows) - 1 != len(teams):
        raise RuntimeError(f"星取表の行数 {len(rows) - 1} がチーム数 {len(teams)} と違う")

    standings, matches = {}, []
    for i in range(1, len(rows)):
        ri = cells(rows[i])
        standings[teams[i - 1]] = {k: _to_int(ri[v].get_text(" ", strip=True))
                                   for k, v in col.items()}
        standings[teams[i - 1]]["played"] = sum(
            standings[teams[i - 1]][k] or 0 for k in ("won", "drawn", "lost"))
        # 同じ試合が両チームの行に出るので i < j の組だけ採る
        for j in range(i + 1, len(teams) + 1):
            for lg in _lsin_legs(ri[j]):
                if lg is None:
                    continue
                matches.append(dict(date="", home=teams[i - 1], hs=lg[0],
                                    **{"as": lg[1]}, away=teams[j - 1]))

    # --- m=s から日付を補う ---
    # ⚠️ **カード名だけで突き合わせてはいけない。** 2回戦制なので同じカードが2試合あり、
    #    1件だけ拾うと**両レグに同じ日付が付く**（2026-09-07に実際に踏んだ）。
    #    ホーム・アウェイ・両得点の4つ組で照合し、それでも決まらない
    #    （＝同じカードで同じスコアの2レグ）ときは**日付順にレグ順へ割り当てる**。
    sched = _lsin_schedule(f"{base}&m=s".replace("?e=", "?m=s&e="), unit_name)

    def _key(m, swap=False):
        h, a, hs, as_ = m["home"], m["away"], m["hs"], m["as"]
        return (a, h, as_, hs) if swap else (h, a, hs, as_)

    pool = collections.defaultdict(list)
    for x in sched:
        pool[_key(x)].append(x)
    for v in pool.values():
        v.sort(key=lambda x: (x["date"], x["kickoff"]))

    nodate, ambiguous = 0, 0
    for m in matches:
        got = None
        for k in (_key(m), _key(m, swap=True)):
            if pool.get(k):
                if len(pool[k]) > 1:
                    ambiguous += 1
                got = pool[k].pop(0)      # 日付順に古いものから割り当てる
                break
        if got:
            m["date"], m["kickoff"], m["venue"] = got["date"], got["kickoff"], got["venue"]
        else:
            nodate += 1

    # ★ 全単射の確認：どちらか一方にしか無いものを**両方向**でログに出す。
    #   片側だけ数えると取りこぼしに気づけない。
    leftover = [x for v in pool.values() for x in v]
    print(f"       （栃木: 試合終了パネル {len(sched)}件 / 星取表の消化 {len(matches)}件 → "
          f"日付を付けた {len(matches) - nodate}件）")
    if nodate:
        print(f"       （栃木: 星取表にあり m=s に無い試合 {nodate}件"
              f"＝日付なしで取り込む。増えていたら m=s の入力が滞っているサイン）")
    if leftover:
        print(f"       [要確認] 栃木: m=s にあり星取表に無い試合が{len(leftover)}件"
              f"（例 {leftover[0]['date']} {leftover[0]['home']} {leftover[0]['hs']}-"
              f"{leftover[0]['as']} {leftover[0]['away']}）")
    if ambiguous:
        print(f"       （栃木: 同じカードで同じスコアの2レグが{ambiguous}件あり、"
              f"日付順にレグ順へ割り当てた）")
    return standings, matches


def build_name_map(official_names, site_names, pref) -> tuple[dict, list]:
    """1対1（全単射）が取れたら (対応表, []) を、取れなければ (部分表, 未対応リスト) を返す。"""
    alias = PREF_ALIAS.get(pref, {})
    by_norm = {}
    for n in site_names:
        by_norm.setdefault(norm(n), n)
    name_map, unknown = {}, []
    for o in sorted(official_names):
        if o in alias:
            name_map[o] = alias[o]
            continue
        hit = by_norm.get(norm(o))
        if hit:
            name_map[o] = hit
        else:
            unknown.append(o)
    return name_map, unknown


# ============================================================
# 宮崎専用の検算ゲート（2026-09-07新設）
# ------------------------------------------------------------
# 宮崎の公式順位表は**画像PDFしか無く機械では読めない**ので、
# 「試合から再計算した順位＝公式順位表」という通常の検算ができない。
# 代わりに次の5つを全部通ったときだけ書き込む。
#   1. チーム数が既存JSONと同じ
#   2. 各チームの試合数の合計 ＝ 消化試合数 × 2
#   3. 勝点 ＝ 勝×3 ＋ 分（全チーム）
#   4. 消化試合数が既存より減っていない（退行防止・呼び出し側で確認）
#   5. 既存JSONと重なる試合のスコアが全部一致する
#      ※初回は既知の差分（公式にだけある2試合）があるので、
#        「既存にあって公式に無い試合がゼロ」であることを確認する
# ============================================================
def self_check_gate(existing: dict, standings: dict, matches: list[dict],
                    site_names: list[str], known_bad: list[dict] | None = None) -> list[str]:
    """通れば空リスト、落ちたら理由のリストを返す

    known_bad … **既存JSON側が誤っていると確認済みの試合**を除外する。
    移行の初回だけ効く。junior-soccer のスコア誤りが1件でもあると
    「既存にあって公式に無い試合」として弾かれ、正しい移行が止まるため。
    ⚠️ 日付・両チーム・スコアまで完全一致で指定する。件数を書くだけの
       ゆるい除外にすると、本物の取りこぼしまで通してしまう。
    """
    ng = []
    if len(standings) != len(site_names):
        ng.append(f"チーム数 {len(standings)} が既存の {len(site_names)} と違う")
    total = sum(v["played"] for v in standings.values())
    if total != len(matches) * 2:
        ng.append(f"試合数の合計 {total} ≠ 消化 {len(matches)} × 2")
    for t, v in standings.items():
        if v["pts"] != v["won"] * 3 + v["drawn"]:
            ng.append(f"{t}: 勝点{v['pts']} ≠ 勝×3+分")
        if v["played"] != v["won"] + v["drawn"] + v["lost"]:
            ng.append(f"{t}: 試合数{v['played']} ≠ 勝分敗の合計")

    # 既存にあって公式に無い試合（＝公式が取りこぼしている）が無いこと。
    # ⚠️ 出典の「左右」はホーム/アウェイとは限らないので、**向きを問わない**キーで
    #    照合する。向きだけ違う同じ試合を「消えた試合」と誤判定すると、
    #    正常な移行が止まってしまう（2026-09-07 宮崎で実際に4件誤検出した）。
    def key(m):
        h, a, hs, as_ = m.get("home"), m.get("away"), m.get("hs"), m.get("as")
        if h > a:                       # 並びを正規化して向きの違いを吸収する
            h, a, hs, as_ = a, h, as_, hs
        return (h, a, hs, as_)

    new_keys = collections.Counter(key(m) for m in matches)
    bad_keys = collections.Counter(key(b) for b in (known_bad or []))
    missing = []
    for m in existing.get("matches", []):
        if m.get("status") != "played" or m.get("hs") is None:
            continue
        k = key(m)
        if new_keys.get(k):
            new_keys[k] -= 1
        elif bad_keys.get(k):
            bad_keys[k] -= 1          # 既存側が誤っていると確認済み。除外する
        else:
            missing.append(m)
    for k, n in bad_keys.items():
        if n:
            ng.append(f"known_bad に書いた試合 {k} が既存JSONに見つからない"
                      f"（すでに直っている？ 設定を見直すこと）")
    if missing:
        ng.append(f"既存にあって公式に無い試合が{len(missing)}件"
                  f"（例: {missing[0].get('home')} {missing[0].get('hs')}-"
                  f"{missing[0].get('as')} {missing[0].get('away')}）")
    return ng


def standings_from_matches(matches: list[dict], teams: list[str]) -> dict:
    """試合一覧から順位表を自前計算する（公式順位表が機械可読でない県用）"""
    st = {t: dict(pts=0, played=0, won=0, drawn=0, lost=0, gf=0, ga=0) for t in teams}
    for m in matches:
        h, a, hs, as_ = m["home"], m["away"], m["hs"], m["as"]
        if h not in st or a not in st:
            continue
        for t, gf, ga in ((h, hs, as_), (a, as_, hs)):
            v = st[t]
            v["played"] += 1
            v["gf"] += gf
            v["ga"] += ga
            if gf > ga:
                v["won"] += 1
                v["pts"] += 3
            elif gf == ga:
                v["drawn"] += 1
                v["pts"] += 1
            else:
                v["lost"] += 1
    return st


# ============================================================
# 既存データとの差分（何が直ったかの記録用）
# ============================================================
def diff_against_existing(existing: dict, new_matches: list[dict]) -> dict:
    """既存JSON（junior-soccer由来）と、公式から作った試合一覧を突き合わせる。

    突き合わせは段階的に行う。いきなり「ホーム＋アウェイ」で対応づけると、
    香川・佐賀のように**同じ組み合わせで2回対戦する**リーグで取り違える。
      1. ホーム＋アウェイ＋日付が一致  … 同じ試合。スコアが違えば「結果が違う」
      2. 残りをホーム＋アウェイで一致  … 「日付ズレ」（スコアも違えば結果も併記）
      3. 残りを{2チーム}＋日付で一致   … 「ホーム/アウェイが逆」
      4. それでも残ったもの            … 公式にだけ有／旧にだけ有
    """
    def played(ms):
        return [m for m in ms
                if m.get("status") == "played" and m.get("hs") is not None]

    old = played(existing.get("matches", []))
    new = played(new_matches)
    old_n, new_n = len(old), len(new)

    def take(pool, keyfn):
        d = {}
        for m in pool:
            d.setdefault(keyfn(m), []).append(m)
        return d

    score_diff, date_diff, swapped = [], [], []

    # 1. ホーム＋アウェイ＋日付
    idx = take(old, lambda m: (m.get("home"), m.get("away"), m.get("date")))
    rest_new = []
    for nm in new:
        k = (nm.get("home"), nm.get("away"), nm.get("date"))
        if idx.get(k):
            om = idx[k].pop(0)
            if (om.get("hs"), om.get("as")) != (nm.get("hs"), nm.get("as")):
                score_diff.append((om, nm))
        else:
            rest_new.append(nm)
    rest_old = [m for v in idx.values() for m in v]

    # 2. ホーム＋アウェイ（日付だけ違う）
    idx2 = take(rest_old, lambda m: (m.get("home"), m.get("away")))
    rest_new2 = []
    for nm in rest_new:
        k = (nm.get("home"), nm.get("away"))
        if idx2.get(k):
            om = idx2[k].pop(0)
            date_diff.append((om, nm))
        else:
            rest_new2.append(nm)
    rest_old2 = [m for v in idx2.values() for m in v]

    # 3. ホーム/アウェイが逆（日付が同じ）
    idx3 = take(rest_old2, lambda m: (frozenset((m.get("home"), m.get("away"))),
                                      m.get("date")))
    added = []
    for nm in rest_new2:
        k = (frozenset((nm.get("home"), nm.get("away"))), nm.get("date"))
        if idx3.get(k):
            swapped.append((idx3[k].pop(0), nm))
        else:
            added.append(nm)
    removed = [m for v in idx3.values() for m in v]

    return {"oldPlayed": old_n, "newPlayed": new_n,
            "score": score_diff, "date": date_diff, "swapped": swapped,
            "added": added, "removed": removed}


def _fmt(m):
    return f"{m.get('date','')} {m.get('home')} {m.get('hs')}-{m.get('as')} {m.get('away')}"


def print_diff(pref: str, d: dict) -> None:
    n = (len(d["score"]) + len(d["date"]) + len(d["swapped"])
         + len(d["added"]) + len(d["removed"]))
    delta = d["newPlayed"] - d["oldPlayed"]
    print(f"  \u2500\u2500 {pref}: 消化 {d['oldPlayed']} \u2192 {d['newPlayed']} "
          f"({delta:+d})\u3000差分 {n} 件")
    for om, nm in d["score"]:
        print(f"       \u2605結果が違う  旧 {_fmt(om)}  \u2192  公式 {_fmt(nm)}")
    for om, nm in d["date"]:
        extra = ("" if (om.get("hs"), om.get("as")) == (nm.get("hs"), nm.get("as"))
                 else f"（スコアも {om.get('hs')}-{om.get('as')} \u2192 "
                      f"{nm.get('hs')}-{nm.get('as')}）")
        print(f"       日付ズレ     旧 {om.get('date')} \u2192 公式 {nm.get('date')}"
              f"  {nm.get('home')} vs {nm.get('away')}{extra}")
    for om, nm in d["swapped"]:
        print(f"       ホーム逆     旧 {_fmt(om)}  \u2192  公式 {_fmt(nm)}")
    for m in d["added"]:
        print(f"       公式にだけ有 {_fmt(m)}")
    for m in d["removed"]:
        print(f"       旧にだけ有   {_fmt(m)}")


# ============================================================
# 1県の処理
# ============================================================
def process(pref: str, cfg: dict, dry_run: bool) -> str:
    slug = f"pref-{pref}-1"
    path = DIR / f"{slug}.json"
    if not path.exists():
        return f"[skip] {slug}: JSONなし"
    data = json.loads(path.read_text(encoding="utf-8"))
    existing_total = len(data.get("matches", []))
    cur_played = len([m for m in data.get("matches", [])
                      if m.get("status") == "played" and m.get("hs") is not None])

    try:
        if cfg["platform"] == "goalnote":
            standings, matches = read_goalnote_all(cfg)
            src = ("https://www.goalnote.net/detail-standings.php?tid="
                   f"{cfg.get('standings_from', cfg['tid'])}")
        elif cfg["platform"] == "tecra":
            standings, matches = read_tecra(cfg)
            src = f"https://{cfg['host']}/order/1/{SEASON_YEAR}/all"
        else:
            # 県ごとの独自システム。読者に見せる公式ページを source にする。
            reader = {"gunma": read_gunma, "miyazaki": read_miyazaki,
                      "yamaguchi": read_yamaguchi, "tokyo": read_tokyo,
                      "kanagawa": read_kanagawa, "toyama": read_toyama,
                      "kumamoto": read_kumamoto, "okinawa": read_okinawa,
                      "lsin": read_lsin,
                      "sportsonline_table": read_sportsonline_table,
                      "okayama": read_okayama, "oita": read_oita,
                      "niigata": read_niigata, "akita": read_akita,
                      "hyogo": read_hyogo, "tokushima": read_tokushima,
                      "hokkaido": read_hokkaido,
                      "aomori": read_aomori, "nagano": read_nagano,
                      "fukui": read_fukui, "yamanashi": read_yamanashi,
                      "gifu": read_gifu, "mie": read_mie,
                      "ehime": read_ehime, "kyoto": read_kyoto,
                      "fukushima": read_fukushima, "nara": read_nara,
                      "kochi": read_kochi, "wakayama": read_wakayama,
                      "osaka": read_osaka}[cfg["platform"]]
            standings, matches = reader(cfg)
            src = cfg["source"]
    except Exception as e:
        return f"[要確認] {slug}: 取得失敗 ({e})"

    # 宮崎のように公式順位表が機械可読でない県は、順位表を試合から自前計算する
    # （standings_gate: "self"）。その県では順位表が空でも異常ではない。
    if not standings and cfg.get("standings_gate") != "self":
        return f"[要確認] {slug}: 順位表を解析できず（据え置き）"
    if not matches:
        return f"[要確認] {slug}: 試合一覧を解析できず（据え置き）"

    # --- 名寄せ（公式表記 → 既存JSONのチーム名） ---
    site_names = [t["name"] for t in data.get("teams", []) if t.get("name")]
    official_names = (set(standings) | {m["home"] for m in matches}
                      | {m["away"] for m in matches})
    name_map, unknown = build_name_map(official_names, site_names, pref)
    if unknown:
        return f"[要確認] {slug}: 名寄せできないチーム名 {unknown[:4]}（据え置き）"
    if len(set(name_map.values())) != len(site_names):
        return (f"[要確認] {slug}: チーム名が1対1で対応しない"
                f"（公式{len(set(name_map.values()))}／既存{len(site_names)}・据え置き）")

    standings = {name_map[k]: v for k, v in standings.items()}
    matches = [dict(m, home=name_map[m["home"]], away=name_map[m["away"]]) for m in matches]

    # ------------------------------------------------------------------
    # [2026-09-19] ⭐️ ここが「出典の順位表そのもの」を持っている**最後の瞬間**。
    #   この下の代替ゲート（self / okinawa / pts_gd）は
    #       standings = standings_from_matches(matches, site_names)
    #   で standings を**試合から再計算した値に置き換える**。置き換わったあとでは出典の表は取り出せない
    #   （okinawa / pts_gd は局所変数 `official` に退避しているだけ）。
    #   ⚠️ だから「build_from_source の第1引数＝出典の表」は**既定ゲートでしか成り立たない**。
    #      build_from_source 側では拾わないこと（拾うと11リーグで再計算値を「出典」と称して保存する）。
    #   ⚠️ **名寄せ済みの名前で捕まえる**（上の2行より前だと出典表記のままで teams[].name と突き合わない）。
    # ------------------------------------------------------------------
    if cfg.get("standings_gate") == "self":
        # 出典に順位表が無いリーグ（宮崎・新潟・岡山・徳島）。
        # **空の表を持つ**のではなく**キーごと持たない**のが正しい。「空の表がある」と「表が無い」は違う。
        source_table = None
    else:
        source_table = list(standings.items()) or None

    # --- 出典に日付が無い県は、既存JSONの同じ対戦から date を引き継ぐ（山口） ---
    # 出典のダミー日付（山口は全試合 2026/04/04）は絶対に採用しない。
    # 新しく増える試合は日付なしのままになる＝県ページの「直近の試合結果」には出ない。
    if cfg.get("inherit_dates"):
        prev = {}
        for m in data.get("matches", []):
            if m.get("date"):
                prev.setdefault((m.get("home"), m.get("away")), []).append(m["date"])
                # 出典の左右はホーム/アウェイと限らないので逆向きも見る
                prev.setdefault((m.get("away"), m.get("home")), []).append(m["date"])
        for m in matches:
            got = prev.get((m["home"], m["away"]))
            if got:
                m["date"] = got.pop(0)

    # --- 消化と未消化を分ける ---
    # 未消化の行は、**日程ごと読む県（愛媛・京都・福島・奈良・高知・和歌山・大阪1部・三重・山梨・岐阜など）と
    # 宮崎**が返す。節番号と**予定日**を未消化の枠に入れるために使う（2026-09-17に日付も入れるようにした）。
    upcoming = [m for m in matches if m.get("hs") is None or m.get("as") is None]
    matches = [m for m in matches if m.get("hs") is not None and m.get("as") is not None]

    # --- 出典そのものの自己矛盾チェック（2026-09-16追加）---
    # 総当たり表なら「Σ(得点−失点)＝0」が必ず成り立つ（誰かの得点は誰かの失点）。
    # **こちらのデータと突き合わせる前に、出典が出典自身と合っているか**を見る検査で、
    # 愛媛（星取表の1マスが左右逆で Σ＝+4）・高知（Σ＝+3）と、2県で実際に当たっている。
    # ⚠️⚠️ **必ず「出典の数字」で計算すること。** 代替ゲート（self/okinawa/pts_gd）では、この後
    #    standings が standings_from_matches() の値に置き換わる。置き換わったほうは作り方から必ず 0 になるので、
    #    そこで数えても永遠に鳴らない（=何も検査しない検査になる）。
    # ⚠️ gf/ga を持たない県（pts_gd の兵庫は gd だけ・self の宮崎/徳島は順位表なし）は対象外。落とさず飛ばす。
    #    兵庫は pts_gd ゲートの中に同じ検査が既にある（二重に足さない）。
    if standings and all(v.get("gf") is not None and v.get("ga") is not None for v in standings.values()):
        gd_sum = sum(v["gf"] - v["ga"] for v in standings.values())
        if gd_sum != 0:
            return (f"[据え置き] {slug}: 出典の順位表の Σ(得点−失点) が {gd_sum:+d} で0でない"
                    f"（読み取りの誤り、または出典の誤り）")

    # --- 宮崎は公式順位表が画像PDFなので、順位表を自前計算して代替ゲートで守る ---
    if cfg.get("standings_gate") == "self":
        standings = standings_from_matches(matches, site_names)
        ng = self_check_gate(data, standings, matches, site_names,
                             cfg.get("known_bad_existing"))
        if ng:
            return f"[据え置き] {slug}: 検算不一致 {ng[:2]} …"

    # --- 沖縄は星取表が勝点・得点・失点・順位しか持たない（勝分敗が無い）ので、
    #     順位表を自前計算し、公式の4項目と突き合わせる代替ゲートで守る ---
    if cfg.get("standings_gate") == "okinawa":
        official = {name_map.get(k, k): v for k, v in standings.items()}
        standings = standings_from_matches(matches, site_names)
        ng = self_check_gate(data, standings, matches, site_names,
                             cfg.get("known_bad_existing"))
        mine_rank = sorted(site_names,
                           key=lambda t: (-standings[t]["pts"],
                                          -(standings[t]["gf"] - standings[t]["ga"]),
                                          -standings[t]["gf"]))
        for team, off in official.items():
            got = standings.get(team)
            if got is None:
                ng.append(f"{team}: 星取表にあるが試合から作れない")
                continue
            for key, label in (("pts", "勝点"), ("gf", "得点"), ("ga", "失点")):
                if off.get(key) is not None and got[key] != off[key]:
                    ng.append(f"{team}: {label} 公式{off[key]} ≠ 試合から{got[key]}")
            if off.get("rank") and team in mine_rank:
                # 同着があると並べ方で前後しうるので、勝点が同じ相手との入れ替わりは許す
                mine_i = mine_rank.index(team) + 1
                if mine_i != off["rank"]:
                    same = [t for t in site_names
                            if standings[t]["pts"] == got["pts"]]
                    if len(same) < 2:
                        ng.append(f"{team}: 順位 公式{off['rank']} ≠ 試合から{mine_i}")
        if ng:
            return f"[据え置き] {slug}: 検算不一致 {ng[:2]} …"

    # --- 公式順位表が「勝点・得失点差・順位」しか持たない県（兵庫 2026-09-14〜）。
    #     順位表は試合から自前計算し、代替ゲート（self と同じ5項目）に加えて
    #     **チームごとの勝点・得失点差**と順位を公式と突き合わせる。
    #     チーム単位で見るので、リーグ合計が変わらないスコア反転（岡山で実例）も捕まる。
    #     使い回すには、reader が {チーム: {"pts", "gd", "rank"}} を返せばよい ---
    if cfg.get("standings_gate") == "pts_gd":
        official = {name_map.get(k, k): v for k, v in standings.items()}
        standings = standings_from_matches(matches, site_names)
        ng = self_check_gate(data, standings, matches, site_names,
                             cfg.get("known_bad_existing"))
        if set(official) != set(site_names):
            ng.append(f"公式順位表のチーム {sorted(set(official) ^ set(site_names))} が既存と合わない")
        if sum(v["gd"] for v in official.values()) != 0:
            ng.append("公式順位表の得失点差の合計が0でない（読み取りの誤り、または出典の誤り）")
        for team, off in official.items():
            got = standings.get(team)
            if got is None:
                continue
            if got["pts"] != off["pts"]:
                ng.append(f"{team}: 勝点 公式{off['pts']} ≠ 試合から{got['pts']}")
            if got["gf"] - got["ga"] != off["gd"]:
                ng.append(f"{team}: 得失点差 公式{off['gd']} ≠ 試合から{got['gf'] - got['ga']}")
        # 順位：公式は勝点→得失点差。両方が並ぶチーム同士の前後だけは許す
        mine = sorted(site_names, key=lambda t: (-standings[t]["pts"],
                                                 -(standings[t]["gf"] - standings[t]["ga"])))
        for team, off in official.items():
            if team in mine and mine.index(team) + 1 != off["rank"]:
                g = standings[team]
                tied = [t for t in site_names if (standings[t]["pts"], standings[t]["gf"] - standings[t]["ga"])
                        == (g["pts"], g["gf"] - g["ga"])]
                if len(tied) < 2:
                    ng.append(f"{team}: 順位 公式{off['rank']} ≠ 試合から{mine.index(team) + 1}")
        if ng:
            return f"[据え置き] {slug}: 検算不一致 {ng[:2]} …"

    # --- 検算とJSON組み立て（junior-soccer版と同じ関数を使う） ---
    # round_robin: False のリーグは総当たり枠を作らない。
    # 鳥取の後期のようにグループ分けのリーグでは、8チームの総当たり（56枠）を
    # 機械的に作ると**存在しない試合枠が大量に出る**。出典の試合一覧をそのまま枠にする。
    # 枠を2回戦制で作り直す県（島根28→56・岡山45→90）。
    # build_from_source は既存の枠数から1回戦制/2回戦制を推定するので、
    # 1回戦制の枠のまま止まっていた県はヒントを与えないと枠が増えない。
    # ⚠️ 退行防止は**枠数ではなく消化試合数**で見る（下の new_played < cur_played）。
    total_hint = existing_total
    if cfg.get("double_round"):
        n = len(site_names)
        total_hint = n * (n - 1)
    res = build_from_source(standings, matches, total_hint,
                            round_robin=cfg.get("round_robin", True))
    if isinstance(res, str):
        return f"[据え置き] {slug}: {res}"
    team_objs, fixtures, meta = res

    # 未消化試合にも出典の節番号・予定日・会場を入れる（宮崎は第15〜18節が未消化）。
    # 「次節」を出すときに効くので、取れる県では入れておく。
    if upcoming:
        # ⚠️ 枠は**向きを問わず両方のキー**に登録される。同じペアの未消化枠が2つあるとき（両巡とも未消化）、
        #    先頭から当てるとどちらに入るかが `generate_fixtures` の生成順まかせになる。
        #    節だけのうちは実害が見えなかったが、**日付を入れると「第9節に11/29」のような取り違えが表に出る**。
        #    → **向きが一致する枠を優先**し、埋まったかどうかは **`md`/`date` の有無ではなく専用の印**で見る
        #       （`md` は 0、`date` は空が正常値としてありうる）。
        slots, today_iso = {}, _jst_today().isoformat()
        for f in fixtures:
            if f.get("status") != "played":
                slots.setdefault((f["home"], f["away"]), []).append(f)
                slots.setdefault((f["away"], f["home"]), []).append(f)
        used, past = set(), []
        for m in upcoming:
            free = [f for f in slots.get((m["home"], m["away"]), []) if id(f) not in used]
            if not free:
                continue
            f = next((x for x in free if x["home"] == m["home"] and x["away"] == m["away"]), free[0])
            used.add(id(f))
            if m.get("md"):
                f["md"] = m["md"]
            if m.get("date"):            # ⚠️ 節が無い県（愛媛）でも日付は入れる
                f["date"] = m["date"]
                if m["date"] < today_iso:
                    past.append(f"{m['date']} {m['home']}×{m['away']}")
            if m.get("venue"):           # ⚠️ 空のときはキーごと書かない
                f["venue"] = m["venue"]
        if past:
            # ⚠️ 予定日が過ぎているのに未消化＝延期か、出典の結果反映が遅れている。止めずにログに出すだけ。
            print(f"       （{pref}: 予定日が今日({today_iso})より前なのに未消化の試合が{len(past)}件"
                  f"：{', '.join(past[:3])}{' …' if len(past) > 3 else ''}）")

    # 書き込む内容が公式の消化数と一致しているか（試合が落ちていないかの最終確認）
    written = sum(1 for f in fixtures if f.get("status") == "played")
    if written != meta["played"]:
        return (f"[要確認] {slug}: 組み立て後の消化{written}件が公式{meta['played']}件と"
                f"合わない（試合が落ちている・据え置き）")

    new_played = meta["played"]
    # 退行防止：公式の消化数がこちらより少なければ据え置く。
    # ⚠️ この原則そのものは残すこと。2026-09-07に沖縄が那覇の異常値
    #    （試合が減るのに勝点が増える）で守られたのは、このガードのおかげ。
    # ただし known_bad_existing に**明示された試合だけ**は、既存側の誤りと確認済みなので
    # 分母から外す。除外を一般的に緩めない（件数だけのゆるい除外にしない）ため、
    # 「既存JSONに実在し、かつ日付・両チーム・スコアまで完全一致するもの」だけを数える。
    known_bad = cfg.get("known_bad_existing") or []
    bogus = 0
    if known_bad:
        def _k(m):
            h, a, hs, as_ = m.get("home"), m.get("away"), m.get("hs"), m.get("as")
            if h > a:
                h, a, hs, as_ = a, h, as_, hs
            return (m.get("date") or "", h, a, hs, as_)
        want = collections.Counter(_k(b) for b in known_bad)
        for m in data.get("matches", []):
            if m.get("status") != "played" or m.get("hs") is None:
                continue
            k = _k(m)
            if want.get(k):
                want[k] -= 1
                bogus += 1
        if bogus:
            print(f"       （{pref}: known_bad_existing の{bogus}件を退行判定の分母から除外）")
    if new_played < cur_played - bogus:
        return (f"[据え置き] {slug}: 公式消化{new_played} < 現在{cur_played}"
                f"{f'−既知の誤り{bogus}' if bogus else ''}"
                f"（公式側が遅れている。退行防止）")

    diff = diff_against_existing(data, fixtures)
    if dry_run:
        print_diff(pref, diff)
        return f"[DRY RUN] {slug}: 消化{new_played}試合（検算一致・書き込みなし）"

    print_diff(pref, diff)
    data["teams"] = team_objs
    data["matches"] = fixtures
    # ⚠️⚠️ **`official_standings` は「出典の順位表そのもの」ではない。**
    #    `meta["official"]` は build_from_source が `recompute(js_matches, teams)` で
    #    **試合から再計算した値**。出典の表と突き合わせる関門は build_from_source の中にあり、
    #    **書き込む時点で**効いている。ここに入るのはその派生物。
    #    📌 名前が「official」なので「出典の表」と読まれがちで、2026-09-18に実際に取り違えた
    #       （scraper/check_standings_vs_matches.py の docstring に経緯）。
    #    ⚠️ そのため**保存される列は50リーグすべて同じ10列**になる。出典が持っていない列も入る
    #       （北海道は出典に得点・失点が無いのに gf/ga が入る）。
    #    ⚠️ **出典の順位（rank）は捨てられる。** ここで付け直すので、
    #       **出典が同着で並べていても必ず1位2位に割れる**（2026-09-15 長野で発覚・未着手）。
    # [2026-09-20] 出典が**同着**と書いているチームに、同じ順位の数字を戻す。
    #   ⚠️ 渡すのは `source_table`（名寄せ直後に捕まえた出典の表）。`standings` を渡さないこと
    #      （self/okinawa/pts_gd ゲートでは試合からの再計算値に化けていて rank が無い）。
    #   ⚠️ 並び順は変えない。変わるのは rank の数字だけ。
    ties_warn = apply_source_ties(meta["official"],
                                  [dict(r, team=t) for t, r in (source_table or [])])
    for w in ties_warn:
        print(f"  ⚠️ {pref}: {w}")
    data["official_standings"] = meta["official"]
    set_source_standings(data, source_table)   # [2026-09-19] 出典の表そのもの（上とは別物）
    data["source"] = src
    data["sourceName"] = cfg["label"]
    data["lastUpdated"] = _jst_today().isoformat()   # UTCだと1日ずれる（jst.py参照）
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    note = ("／" + "／".join(ties_warn)) if ties_warn else ""
    return f"[更新] {slug}: 消化{new_played}試合に更新（検算一致）{note}"


# ---------------------------------------------------------------------------
# 取得結果の記録（2026-09-07 追加）
# ---------------------------------------------------------------------------
# process() が返したメッセージを、見張り用の結果コードに読み替えるだけ。
# **判定（赤にするか）はここでは行わない** — audit_pref_freshness.py の担当。
# process() 本体には一切手を入れていないので、更新処理の挙動は変わらない。
def classify(msg: str) -> tuple[str, str]:
    """process() の戻り値 → (結果コード, 説明)"""
    body = msg.split(": ", 1)[-1]
    if msg.startswith("[更新]"):
        return "ok", body
    # 公式側の消化数がこちらより少ない＝出典が遅れているだけ。取得は成功している。
    # ここを失敗にすると、出典が休みの県が毎日赤くなる（打つ手が無いものは赤にしない）。
    if "退行防止" in msg:
        return "ok", body
    if "取得失敗" in msg or "例外" in msg:
        return "fetch_error", body
    if "解析できず" in msg:
        return "parse_empty", body
    if "名寄せ" in msg or "1対1で対応しない" in msg:
        return "alias_failed", body
    return "verify_failed", body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="県1部を県協会公式（GoalNote / tecra ほか）から更新する")
    parser.add_argument("--dry-run", action="store_true",
                        help="書き込まず、既存との差分だけ出す")
    parser.add_argument("--only", default="", help="県idをカンマ区切りで指定")
    args = parser.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    print("=== 県1部 戦績表 自動更新（県協会公式：GoalNote / tecra）===")
    updated = held = warn = 0
    for pref, cfg in PREF_OFFICIAL.items():
        if only and pref not in only:
            continue
        try:
            msg = process(pref, cfg, args.dry_run)
        except Exception as e:      # 想定外でも他県は止めない
            msg = f"[要確認] pref-{pref}-1: 例外 {e}"
        print(" ", msg)
        if not args.dry_run:
            fetch_status.set_pref_result(pref, *classify(msg))
        if msg.startswith("[更新]"):
            updated += 1
        elif msg.startswith("[据え置き]"):
            held += 1
        elif msg.startswith("[要確認]"):
            warn += 1
    print(f"--- 完了: 更新{updated} / 据え置き{held} / 要確認{warn} ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
