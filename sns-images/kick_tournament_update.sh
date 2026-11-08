#!/bin/bash
# 選手権など県予選だけの更新（update_rankings.yml を範囲 tournament で）を、Mac から起動する合図を送る。
#   Mac の launchd から毎日 13:47・15:47・18:47 に呼ぶ（install_today_finals.sh で一緒に登録される）。手で打っても同じ。
#   bash sns-images/kick_tournament_update.sh
# [2026-11-08] GitHub の schedule が遅れ・抜けだらけになった（evening_tournament.yml の 13:47・15:47 は 11/1 から一度も
#   動かず、18:47 も 20〜22時に1回だけ。11/8 は0回）。決勝の日に結果が入らなかったので、合図を Mac から出す。
#   evening_tournament.yml の schedule は予備として残す（Mac が眠っていて合図を出せなかった日の分）。
# すでに更新が走っている・順番待ちのときは送らない（手で何本も起動して渋滞した 11/8 の教訓）。
# 記録は ~/Library/Logs/u18-kick-tournament.log
set -u
GH="${GH:-/opt/homebrew/bin/gh}"   # launchd の PATH には homebrew が入っていない
R="hawkswords51-sys/u18-soccer-ranking"

echo "=== $(date '+%Y-%m-%d %H:%M') 県予選の更新の合図 ==="
busy=""
for st in queued in_progress waiting pending requested; do
  n="$("$GH" run list -R "$R" --workflow update_rankings.yml --status "$st" --limit 5 --json databaseId -q 'length' 2>&1)" \
    || { echo "GitHub に問い合わせられませんでした: $n"; exit 1; }
  [ "$n" != 0 ] && busy="$busy $st=$n"
done
if [ -n "$busy" ]; then
  echo "更新がもう走っているか順番待ちなので、合図は送りません（$busy ）"
  exit 0
fi
if "$GH" workflow run update_rankings.yml -R "$R" --ref main -f scope=tournament; then
  echo "合図を送りました（範囲 tournament。2〜3分で終わる）"
else
  echo "合図を送れませんでした（ネットにつながっていない？ gh のログインが切れた？）"
  exit 1
fi
