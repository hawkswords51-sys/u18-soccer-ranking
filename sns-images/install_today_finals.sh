#!/bin/bash
# SNS画像の自動作成を Mac（launchd）に登録する。1回打てばよい（打ち直しても大丈夫）。
#   朝 8:00          … 今日の決勝（today-finals）
#   昼 14:30・16:30／夜 19:30・20:45 … 今日決まった県代表カード（today-daihyo）。2回目以降は増えたときだけ通知
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
SCRIPT="$AUTO/repo/sns-images/today_finals_auto.sh"
LOG="$HOME/Library/Logs/u18-today-finals.log"
mkdir -p "$HOME/Library/LaunchAgents"

register() {  # $1=ラベル $2=種類 $3=時刻の並び（<dict>…</dict> を並べたもの）
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
  <array><string>/bin/bash</string><string>$SCRIPT</string><string>$2</string></array>
  <key>StartCalendarInterval</key><array>$3</array>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PL
  plutil -lint "$P" >/dev/null && launchctl bootstrap "gui/$(id -u)" "$P"
}
at() { echo "<dict><key>Hour</key><integer>$1</integer><key>Minute</key><integer>$2</integer></dict>"; }

REMOVE=0; [ "${1:-}" = "--remove" ] && REMOVE=1
register com.u18soccer.today-finals today-finals "$(at 8 0)"
register com.u18soccer.today-daihyo today-daihyo "$(at 14 30)$(at 16 30)$(at 19 30)$(at 20 45)"
if [ $REMOVE = 1 ]; then echo "自動作成をやめました（朝・昼・夜とも。写し $AUTO は残しています）"; else
  echo "自動作成専用の写し: $AUTO/repo（手で編集しない）／できた画像: $AUTO/out と Dropbox"
  echo "登録しました：朝8:00 今日の決勝／昼14:30・16:30／夜19:30・20:45 今日決まった県代表カード"; fi
