#!/bin/bash
# SNS画像の自動作成を Mac（launchd）に登録する。1回打てばよい（打ち直しても大丈夫）。
#   朝 8:00          … 今日の決勝（today-finals）
#   昼 14:30・16:30／夜 19:30・20:45 … 今日決まった県代表カード（today-daihyo）。2回目以降は増えたときだけ通知
#   13:47・15:47・18:47 … GitHub に「選手権など県予選だけの更新」を起動する合図（kick_tournament_update.sh）
#     [2026-11-08] GitHub の時刻起動が遅れ・抜けだらけで、決勝の結果が入らなかったため Mac から合図を出す
#   登録:   bash sns-images/install_today_finals.sh
#   やめる: bash sns-images/install_today_finals.sh --remove
# 決まった時刻に Mac が眠っていたら、起きたときに1回動く。記録は ~/Library/Logs/u18-today-finals.log
# [2026-11-01] launchd は書類フォルダを読めない（Mac の安全機能）ので、書類フォルダの外に自動作成専用の写しを置き、そちらを動かす
AUTO="$HOME/u18-sns-auto"
SRC_REPO="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" != "--remove" ] && [ ! -d "$AUTO/repo/.git" ]; then
  mkdir -p "$AUTO" && git clone -q "$(git -C "$SRC_REPO" remote get-url origin)" "$AUTO/repo" \
    || { echo "写しを作れませんでした（ネットにつながっていない？）"; exit 1; }
fi
if [ "${1:-}" != "--remove" ]; then  # 写しを最新に（新しく足したスクリプトが写しに無いと登録しても動かない）
  git -C "$AUTO/repo" fetch -q origin main && git -C "$AUTO/repo" reset -q --hard origin/main \
    || echo "写しを最新にできませんでした（ネットにつながっていない？）。前の写しのまま登録します"
fi
SCRIPT="$AUTO/repo/sns-images/today_finals_auto.sh"
LOG="$HOME/Library/Logs/u18-today-finals.log"
mkdir -p "$HOME/Library/LaunchAgents"

register() {  # $1=ラベル $2=種類 $3=時刻の並び（<dict>…</dict> を並べたもの） $4=動かすスクリプト（省略時は today_finals_auto.sh）
  local S="${4:-$SCRIPT}" LG="${5:-$LOG}"
  local P="$HOME/Library/LaunchAgents/$1.plist"
  launchctl bootout "gui/$(id -u)/$1" 2>/dev/null
  if [ "$REMOVE" = 1 ]; then rm -f "$P"; return; fi
  cat > "$P" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$S</string><string>$2</string></array>
  <key>StartCalendarInterval</key><array>$3</array>
  <key>StandardOutPath</key><string>$LG</string>
  <key>StandardErrorPath</key><string>$LG</string>
</dict>
</plist>
PL
  plutil -lint "$P" >/dev/null && launchctl bootstrap "gui/$(id -u)" "$P"
}
at() { echo "<dict><key>Hour</key><integer>$1</integer><key>Minute</key><integer>$2</integer></dict>"; }

REMOVE=0; [ "${1:-}" = "--remove" ] && REMOVE=1
register com.u18soccer.today-finals today-finals "$(at 8 0)"
register com.u18soccer.today-daihyo today-daihyo "$(at 14 30)$(at 16 30)$(at 19 30)$(at 20 45)"
register com.u18soccer.kick-tournament - "$(at 13 47)$(at 15 47)$(at 18 47)" \
  "$AUTO/repo/sns-images/kick_tournament_update.sh" "$HOME/Library/Logs/u18-kick-tournament.log"
if [ $REMOVE = 1 ]; then echo "自動作成と県予選更新の合図をやめました（朝・昼・夜とも。写し $AUTO は残しています）"; else
  echo "自動作成専用の写し: $AUTO/repo（手で編集しない）／できた画像: $AUTO/out と Dropbox"
  echo "登録しました：朝8:00 今日の決勝／昼14:30・16:30／夜19:30・20:45 今日決まった県代表カード"
  echo "　　　　　　　13:47・15:47・18:47 県予選だけの更新の合図（記録 ~/Library/Logs/u18-kick-tournament.log）"; fi
