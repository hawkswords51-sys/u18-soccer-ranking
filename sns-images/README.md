# SNS用画像の作り方

サイトのデータから、Instagram・Threads 向けの縦長画像（1080×1350）を作ります。サイトのページは何も変わりません。

1. ターミナルでリポジトリのフォルダに入り、`python3 sns-images/make_sns_images.py` を打つ。
2. 画像は `運営フォルダ/SNS画像/今日の日付/` にできる（リポジトリの中には置かない）。
3. 作るもの：選手権の県代表決定カード（決勝が終わった県だけ）／代表校一覧6枚（地域別）／プレミア順位表2枚（EAST・WEST）。
4. 一部だけ作るとき：`--only premier` のように種類を選ぶ（`senshuken-daihyo`・`senshuken-ichiran`・`premier`、カンマで複数）。
5. 出力先を変えるとき：`OUT_DIR=/保存したい場所 python3 sns-images/make_sns_images.py`
6. 数字はその日のサイトのデータのまま。朝の自動更新のあとに作ると最新になる。
7. 「フォントが見つかりません」「Pillow が入っていません」と出たら、その表示をそのまま Claude Code に貼る。
