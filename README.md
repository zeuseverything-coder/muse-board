# Muse × Antigravity 非同期ボード（最小構成）

目的：実行AI（Muse）と監査AI（Antigravity / Gemini）を直接つながず、ファイルの受け渡しだけで連携する。個人サブスクの認証を外部から自動操作しないため、規約上安全な構成にする。

## 役割
- Muse（実行）：アフィリエイト運用の実行と、週次の「完了報告」の作成。ボードの指摘を受けて修正・反映する。
- Antigravity（監査）：人の合図で起動し、公開ページと数字を独立にチェックして、指摘を board.md に書く。
- 人（川端 匠）：「確認して」の一言で Antigravity を起こすだけ。長文のコピペ中継はしない。

## ファイル構成
- reports/ ：Muse の完了報告。週次PDCA（月曜）のたびに1ファイル追加する（YYYY-MM-DD-report-NNN.md）。
- board.md ：Antigravity の指示ボード。監査の指摘と優先タスクをここに書く。Muse は読むだけ（対応状況の記録欄のみ追記可）。
- AUDIT_PROMPT.md ：Antigravity への監査指示書。チェック観点と board.md の書式を定義する。

## 運用の流れ
1. 月曜の週次PDCAで Muse が完了報告を reports/ に追加する。
2. 人が Antigravity に「ボードを読んで確認して」と合図する。
3. Antigravity が AUDIT_PROMPT.md の観点で公開記事・数字を監査し、board.md を更新する。
4. 次の週次PDCAの冒頭で Muse が board.md を読み、直せる指摘は自律運用の範囲で修正し、報告に「指摘と対応」を含める。判断が要る指摘は人へ上げる。

## 置き場所
- 正本はこのフォルダ（Muse のワークスペース）。GitHub 連携が済んだら、プライベートリポジトリに同じ構成で同期し、Antigravity はリポジトリ側を読む。
- 秘密情報（パスワード、APIキー、個人情報の詳細）はこのフォルダに置かない。
