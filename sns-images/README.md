# SNS用画像の作り方

サイトのデータから、Instagram・Threads 向けの縦長画像（1080×1350）を作ります。サイトのページは何も変わりません。

1. ターミナルでリポジトリのフォルダに入り、`python3 sns-images/make_sns_images.py` を打つ。
2. 画像は `運営フォルダ/SNS画像/今日の日付/` にできる（リポジトリの中には置かない）。
3. 作るもの：選手権の県代表決定カード（決勝が終わった県だけ）／代表校一覧6枚（地域別）／プレミア順位表2枚（EAST・WEST）。
4. 一部だけ作るとき：`--only premier` のように種類を選ぶ（`senshuken-daihyo`・`senshuken-ichiran`・`premier`、カンマで複数）。
5. 出力先を変えるとき：`OUT_DIR=/保存したい場所 python3 sns-images/make_sns_images.py`
6. 数字はその日のサイトのデータのまま。朝の自動更新のあとに作ると最新になる。
7. 「フォントが見つかりません」「Pillow が入っていません」と出たら、その表示をそのまま Claude Code に貼る。

## 毎朝の「今日の決勝」（自動）

選手権予選の決勝がある日の朝、ストーリーズとThreads用の画像1枚（決勝が9試合以上なら2枚）と投稿文（`today-finals-MMDD.txt`）を作ります。決勝の無い日は何も作りません。

- 自動にする登録（1回だけ）：`bash sns-images/install_today_finals.sh`。毎朝8:00に動き、できたら Mac の通知が出ます。8時に Mac が眠っていたら、起きたときに動きます。
- やめるとき：`bash sns-images/install_today_finals.sh --remove`
- 手で作るとき：`bash sns-images/today_finals_auto.sh`。日付を指定して試すときは `python3 sns-images/make_sns_images.py --only today-finals --date 11/8`
- データは GitHub の最新（直近の自動更新の分）を読みます。手元のリポジトリのファイルは変えません。
- 準決勝がまだで相手が決まっていない決勝（「A/B vs C/D」）は画像に入れず、記録に名前だけ出します。
- スマホ用に Dropbox の「u18-soccer SNS画像/今日の日付/」にも同じものを置きます（Dropbox アプリで開いて保存→投稿）。
- 動いた記録：`~/Library/Logs/u18-today-finals.log`
