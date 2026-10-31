#!/bin/bash
# 毎朝8時に today_finals_auto.sh を動かす登録（Mac の launchd）。1回打てばよい。
#   登録:   bash sns-images/install_today_finals.sh
#   やめる: bash sns-images/install_today_finals.sh --remove
# 8時に Mac が眠っていたら、起きたときに1回動く。記録は ~/Library/Logs/u18-today-finals.log
LABEL=com.u18soccer.today-finals
P="$HOME/Library/LaunchAgents/$LABEL.plist"
SCRIPT="$(cd "$(dirname "$0")" && pwd)/today_finals_auto.sh"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
if [ "${1:-}" = "--remove" ]; then
  rm -f "$P" && echo "毎朝の自動作成をやめました"
  exit 0
fi
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$P" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$SCRIPT</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/u18-today-finals.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/u18-today-finals.log</string>
</dict>
</plist>
PL
plutil -lint "$P" >/dev/null && launchctl bootstrap "gui/$(id -u)" "$P" && echo "登録しました：毎朝8:00に「今日の決勝」を作ります（$P）"
