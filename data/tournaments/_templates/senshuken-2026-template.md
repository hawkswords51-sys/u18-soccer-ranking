---
prefecture: ○○（例: shizuoka）
title: 第105回全国高校サッカー選手権大会 ○○県大会
subtitle: 選手権予選
year: 2026
category: 選手権予選
status: 開催前
source: https://koko-soccer.com/score/XXXX
---

<!--
使い方（選手権予選の自動更新）:
1. koko-soccer が県予選ページを公開したら、上の source: にそのURLを入れる。
2. このテンプレートを data/tournaments/{pref}-senshuken-2026.md としてコピーする
   （このファイル自体は _templates/ 内にあるためサイト生成の対象外）。
3. 本文は空でOK。毎朝のワークフロー「高円宮杯 順位自動更新」内の
   scraper/update_tournament_results.py が、組み合わせ（vs行）も結果（スコア）も
   自動で追記していく。決勝の結果が入ると status は自動で「終了」になる。
4. Actionsログの「⚠ 要確認」は週末にまとめて確認する（詳細は運営マスター手順書 4-11）。
-->
