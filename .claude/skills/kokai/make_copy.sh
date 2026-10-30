#!/bin/bash
# リポジトリの「いまの作業中の状態」をコピーし、生成スクリプトはこのコピーで走らせる。
#   使い方: bash make_copy.sh <コピー先フォルダ（scratchpad の中）>
# リポジトリ側には何も書かない。コピー先は毎回作り直す（中身を消してから入れ直す）。
set -euo pipefail
REPO="$(cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)" && pwd -P)"
DEST="${1:?コピー先を指定してください}"
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd -P)"   # 「.」や相対パス・/tmp の別名でもリポジトリ内を見抜けるように
case "$DEST" in
  "$REPO"|"$REPO"/*) echo "コピー先がリポジトリの中です。中止します。" >&2; exit 1;;
esac
rsync -a --delete --exclude .git --exclude __pycache__ "$REPO"/ "$DEST"/
echo "コピーしました: $DEST"
echo "生成のあと、変わったファイルを見るには:"
echo "  diff -rq --exclude=.git --exclude=__pycache__ \"$REPO\" \"$DEST\""
