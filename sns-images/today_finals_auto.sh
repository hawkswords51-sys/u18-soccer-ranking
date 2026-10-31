#!/bin/bash
# 毎朝の「今日の決勝」画像と投稿文を自動で作る（Mac の launchd から呼ぶ。手で打っても同じ）。
# 手元のリポジトリの作業中のファイルは触らない：git fetch で GitHub の最新を取り寄せ、
# そのデータだけを一時フォルダに取り出して読む。画像は運営フォルダの SNS画像/今日の日付/ にできる。
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-/opt/anaconda3/bin/python3}"   # Pillow が入っている python
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "=== $(date '+%Y-%m-%d %H:%M') 今日の決勝 ==="
git -C "$REPO" fetch -q origin main || { echo "GitHub から取れませんでした（ネットにつながっていない？）"; exit 1; }
git -C "$REPO" archive origin/main data/tournaments | tar -x -C "$TMP" || exit 1
git -C "$REPO" log -1 --format='データ: %h %ad %s' --date=format-local:'%m/%d %H:%M' origin/main

OUT="$(SNS_DATA_ROOT="$TMP" "$PY" "$REPO/sns-images/make_sns_images.py" --only today-finals 2>&1)"
status=$?
echo "$OUT"
# スマホから開けるように Dropbox にも同じものを置く（Dropbox が無い Mac では飛ばす）
DBX="${SNS_DROPBOX_DIR:-$HOME/Dropbox/u18-soccer SNS画像}"
SRC="$(echo "$OUT" | sed -n 's/^出力先: //p')"
if [ $status -eq 0 ] && [ -d "$HOME/Dropbox" ] && ls "$SRC"/today-finals-* >/dev/null 2>&1; then
  DEST="$DBX/$(basename "$SRC")"
  mkdir -p "$DEST" && cp "$SRC"/today-finals-* "$DEST"/ && echo "Dropbox にも置きました: $DEST"
fi
if [ $status -ne 0 ]; then
  msg="作れませんでした。ログを Claude Code に見せてください"
elif echo "$OUT" | grep -q "today-finals-.*\.png"; then
  msg="$(echo "$OUT" | grep '決勝 [0-9]*試合' | sed 's/.*今日の決勝：//; s/／.*//')。Dropbox の「u18-soccer SNS画像」にも置きました"
else
  msg=""   # 決勝の無い日は知らせない
fi
[ -n "$msg" ] && osascript -e "display notification \"$msg\" with title \"今日の決勝\"" >/dev/null 2>&1
exit $status
