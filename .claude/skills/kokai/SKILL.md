---
name: kokai
description: Keiの依頼（依頼文・実装指示書・貼られた指示）をサイトに出すまでの共通の流れ。コピーで試す→変更一覧を見せる→Keiの承認→ファイルを1つずつ選んでコミット→push→GitHubの処理を待つ→公開ページを実物で確認。「/kokai」「公開して」「コミットしてpushして」「反映して」と言われたとき、または依頼を片付けてpushまで進めるときに使う。チームページだけなら /publish-team でもよい。
---

# 公開の手順（どの依頼にも使う共通の流れ）

CLAUDE.md の「絶対に守ること」が最優先。この手順はそれを抜けなく回すためのもの。
1つでも予定と違うことが起きたら、**そこで止めてKeiに報告する**（勝手に直さない）。

## 0. 何を見れば「できた」と言えるかを先に決める
作業に入る前に、依頼文の期待値から**公開後に確かめること**を書き出しておく。
- どのページの、どの文字・数字が、どう変わるはずか（例：「/tournaments/incolle-2026/ に『第75回の組み合わせと会場』が出る」）
- 変わってはいけないもの（例：「要確認」が出ない、他県の表が変わらない）
- 依頼文に期待値があれば、それをそのまま使う。

## 1. いまの状態を見る
```
git --no-optional-locks status --short
git fetch -q && git log --oneline HEAD..origin/main
```
- 依頼と関係ない変更（`.claude/settings.local.json`、書きかけの blog-source など）は**触らない・入れない**。
- `.git/index.lock` が0バイトで残っていて git が動いていなければ消してよい（CLAUDE.md ルール4の例外）。

## 2. コピーで試す（生成スクリプトはリポジトリで走らせない）
```
bash .claude/skills/kokai/make_copy.sh <scratchpad>/kokai-copy
cd <scratchpad>/kokai-copy && python3 scraper/<生成スクリプト>.py
diff -rq --exclude=.git --exclude=__pycache__ <リポジトリ> <scratchpad>/kokai-copy
```
- 生成スクリプトは引数を無視して全体が動くことがある（`--help` でも本体が走る）。必ずコピーで。
- diff で**変わってよいファイルだけ**が変わっているかを見る。想定外のファイルが変わっていたら止めて報告。
- 依頼文の期待値（件数・順位・スコアなど）と突き合わせる。食い違ったら報告。
- **導出されるデータ（順位・勝点など）は手で書かない**。生成に任せる。

## 3. Keiに見せて承認を取る
次の形で見せ、「これをコミットします。よろしいですか」で**止まる**。
```
■ コミット（1作業＝1コミット）
  ① <メッセージ案>
     M data/xxx.json
     M scraper/yyy.py
■ 入れないもの： .claude/settings.local.json ほか（関係ない変更）
■ コピーでの確認： <期待値どおりだった点／違った点>
■ 公開後に確かめること： <0で決めたもの>
```
承認の言葉（「お願いします」「pushして」など）が出るまで commit も push もしない。
承認はその回かぎり。次の依頼ではまた取る。

## 4. コミットと push
```
git add <ファイル1> <ファイル2>        # 1つずつ名前で。-A や . は使わない
git commit -m "<日本語で簡潔に>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- <ファイル1> <ファイル2>
git fetch -q && git merge --ff-only origin/main   # 先に進んでいたら（手元に変更があっても使える形）
git push                                            # --force は絶対に使わない
```
- `git commit ... -- <ファイル>` の形にして、ほかに add 済みのものが混ざらないようにする。
- ボットが先にコミットしていて ff-only できないときは `git rebase origin/main`（手元に未コミットの変更があれば、[[pull-with-local-edits]] の手順で）。
- push が通らないときは止めて報告。

## 5. GitHub の処理を待つ
```
python3 .claude/skills/kokai/wait_deploy.py <コミット番号>
```
- 最後の公開（pages-build-deployment）が success なら反映済み。
- 自分のコミットの公開が cancelled なのは、ボットのコミットの公開に置き換わっただけ。問題ない。
- 「in progress deployment」で失敗していたら `gh run rerun <id> --failed`。
- **data/ の決まった場所（team-profiles・tournaments・university など）以外だけを変えたときは、
  「順位自動更新」は走らない。** scraper/*.py だけの変更は、**次の定期実行（朝・夜）でページに出る**。
  その場合はそう報告し、確かめることを `/mihari` の宿題（メモリの mihari-homework）に書き足す。

## 6. 公開ページを実物で確かめる
```
python3 .claude/skills/kokai/check_live.py https://u18-soccer.com/<ページ>/ "<あるはずの文字>" "!<無いはずの文字>"
```
- 0で決めたことを1つずつ確かめる。キャッシュよけ（?nocache=）は自動で付く。
- 見た目が絡むもの（表・画像・スマホ幅）は、必要ならブラウザでも見る。

## 7. 報告（素人にわかる言葉で・短く）
- 何をコミットしたか（番号つき）、GitHubの処理が緑か、公開ページで何を確かめたか。
- 次の定期実行を待つものがあれば、何がいつ出るはずか、と「/mihari で確かめます」。
- 依頼文と実物の食い違い・気づいたことは、直さずに並べて、判断をKeiに聞く。
