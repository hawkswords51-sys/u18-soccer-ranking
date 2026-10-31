#!/bin/bash
# 「今日の決勝」（朝）と「今日決まった県代表カード」（夜）を自動で作る（Mac の launchd から呼ぶ。手で打っても同じ）。
#   bash sns-images/today_finals_auto.sh              # 朝：今日の決勝
#   bash sns-images/today_finals_auto.sh today-daihyo # 夜：今日決まった県代表カード
#   （後ろに --date 10/31 を足すと日付を指定して試せる）
# 手元のリポジトリの作業中のファイルは触らない：git fetch で GitHub の最新を取り寄せ、
# そのデータだけを一時フォルダに取り出して読む。画像は運営フォルダの SNS画像/今日の日付/ にできる。
set -u
KIND="${1:-today-finals}"
case "$KIND" in
  today-finals) TITLE="今日の決勝"; PAT="today-finals-*" ;;
  today-daihyo) TITLE="今日の県代表"; PAT="senshuken-daihyo-* today-daihyo-*" ;;
  *) echo "知らない種類: $KIND"; exit 1 ;;
esac
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-/opt/anaconda3/bin/python3}"   # Pillow が入っている python
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "=== $(date '+%Y-%m-%d %H:%M') $TITLE ==="
git -C "$REPO" fetch -q origin main || { echo "GitHub から取れませんでした（ネットにつながっていない？）"; exit 1; }
git -C "$REPO" archive origin/main data/tournaments | tar -x -C "$TMP" || exit 1
git -C "$REPO" log -1 --format='データ: %h %ad %s' --date=format-local:'%m/%d %H:%M' origin/main

OUT="$(SNS_DATA_ROOT="$TMP" "$PY" "$REPO/sns-images/make_sns_images.py" --only "$KIND" "${@:2}" 2>&1)"
status=$?
echo "$OUT"
# 夜：今日カードができたら、代表校一覧6枚も作り直す（数が変わるので）
ICHIRAN=""
if [ "$KIND" = today-daihyo ] && [ $status -eq 0 ] && echo "$OUT" | grep -q "senshuken-daihyo-.*\.png"; then
  OUT2="$(SNS_DATA_ROOT="$TMP" "$PY" "$REPO/sns-images/make_sns_images.py" --only senshuken-ichiran 2>&1)" || status=$?
  echo "$OUT2"
  PAT="$PAT senshuken-ichiran*"
  n=$(echo "$OUT2" | sed -n 's/.*代表校一覧：\([0-9]*\)\/47.*/\1/p')
  if [ -n "$n" ]; then
    STATE="${SNS_STATE_FILE:-$HOME/Library/Logs/u18-ichiran-count.txt}"   # 前の回の決定数（「出しどき」の知らせを1回にするため）
    prev=$(cat "$STATE" 2>/dev/null || echo 0)
    echo "$n" > "$STATE"
    ICHIRAN="代表決定 $n/47"
    # 半分（24）を超えた日と、47そろった日に「出しどき」を知らせる
    if { [ "$prev" -lt 24 ] && [ "$n" -ge 24 ]; } || { [ "$prev" -lt 47 ] && [ "$n" -ge 47 ]; }; then
      ICHIRAN="$ICHIRAN。代表校一覧6枚の出しどきです"
    fi
  fi
fi
# スマホから開けるように Dropbox にも同じものを置く（Dropbox が無い Mac では飛ばす）
DBX="${SNS_DROPBOX_DIR:-$HOME/Dropbox/u18-soccer SNS画像}"
SRC="$(echo "$OUT" | sed -n 's/^出力先: //p')"
DEST="$DBX/$(basename "$SRC")"
before=$(cd "$DEST" 2>/dev/null && ls $PAT 2>/dev/null | wc -l | tr -d ' ')
made=$(echo "$OUT" | grep -c -E '^   (today-finals-|senshuken-daihyo-).*\.png$')
if [ $status -eq 0 ] && [ -d "$HOME/Dropbox" ] && [ "$made" -gt 0 ]; then
  mkdir -p "$DEST" && (cd "$SRC" && cp $PAT "$DEST"/) && echo "Dropbox にも置きました: $DEST"
fi
after=$(cd "$DEST" 2>/dev/null && ls $PAT 2>/dev/null | wc -l | tr -d ' ')
summary="$(echo "$OUT" | grep -E "・ ${TITLE}：.*(試合|校)（" | head -1 | sed "s/.*${TITLE}：//; s/／ほかに.*//")"
if [ $status -ne 0 ]; then
  msg="作れませんでした。ログを Claude Code に見せてください"
elif [ "$made" -gt 0 ] && [ "$after" != "$before" ]; then
  msg="${summary}${ICHIRAN:+（${ICHIRAN}）}。Dropbox の「u18-soccer SNS画像」に置きました"   # 前の回より増えたときだけ知らせる
else
  msg=""   # 何も無い日・前の回と同じときは知らせない
fi
[ -n "$msg" ] && osascript -e "display notification \"$msg\" with title \"$TITLE\"" >/dev/null 2>&1
exit $status
