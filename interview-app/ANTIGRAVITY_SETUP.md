# Antigravity への作業指示書：面接支援アプリの Windows セットアップ

## 目的

このフォルダ（interview-app/）にある「リアルタイムAI面接支援アプリ」を、このPC（Windows）に完全セットアップし、起動確認と簡易スモークテストまで行うこと。
作業結果は `interview-app/SETUP_RESULT.md` に記録し、このリポジトリ（muse-board）へ commit & push すること。

アプリの概要は同フォルダの README.md、モデルの選定指針は docs/MODELS.md、スマホ接続手順は docs/PHONE.md を参照。

## 作業場所

- リポジトリのクローン内で作業し、アプリのファイルは interview-app/ フォルダを基準にする（.bat はフォルダ内の scripts/ にある）。
- セットアップで生成される .venv、データベース（data/ 配下）などはコミットしない（.gitignore 設定済み）。

## 手順

### 0. PCスペックの記録

最初にこのPCのスペックを調べ、SETUP_RESULT.md に記録する：CPU名、GPU名、メモリ容量（GB）。
例（PowerShell）：
- `Get-CimInstance Win32_Processor | Select-Object Name`
- `Get-CimInstance Win32_VideoController | Select-Object Name`
- `(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB`

### 1. Python 3.11+ の確認と導入

- `python --version`（または `py --version`）で Python 3.11 以上があるか確認する。
- なければ `winget install -e --id Python.Python.3.12` で導入を試みる。winget が使えない場合は python.org の公式インストーラでの導入を試みる。
- どうしても導入できない場合は、その旨と理由を SETUP_RESULT.md に書いて、以降の手順は中止してよい（結果ファイルだけは必ず commit & push する）。

### 2. アプリのセットアップ（scripts\setup_windows.bat）

- interview-app/ フォルダで `scripts\setup_windows.bat` を実行する。
  - この .bat は、仮想環境（.venv）の作成、requirements.txt のインストール、PyAudioWPatch のインストール、Whisper base モデルの事前ダウンロードを行う。
  - .bat の最後に `pause` があるため、自動実行では入力待ちで止まることがある。その場合はキーを送るか、標準入力に改行を渡して進めること。
- エラーが出たら、無理に進めず、エラーメッセージの要点（最後の数十行）を SETUP_RESULT.md に残す。よくある原因（ネット接続、pip の失敗、コンパイラ不足など）が分かれば併記する。

### 3. Ollama の導入とモデル取得

- `ollama --version` で Ollama の有無を確認する。なければ公式インストーラ（https://ollama.com/download）で導入する。
  - インストール時に管理者権限のダイアログなど人の操作が必要になったら、無理に進めず、その旨を SETUP_RESULT.md に書いてこの手順を止める（他の手順は続けてよい）。
- モデルの選択（手順0で記録したメモリ容量で判断する）：
  - メモリ 16GB 以上：`ollama pull qwen2.5:7b-instruct-q4_K_M`
  - メモリ 16GB 未満：`ollama pull qwen2.5:3b-instruct-q4_K_M` を取得し、サーバー起動時に環境変数 `ISA_OLLAMA_MODEL=qwen2.5:3b-instruct-q4_K_M` を設定する（アプリの既定は 7b 側のため）。どちらのモデルを選んだかと判断理由（メモリ容量）を SETUP_RESULT.md に記録する。
- `ollama list` で取得したモデルが一覧にあることを確認する。

### 4. サーバー起動と状態APIの確認

- `scripts\start_windows.bat` でサーバーを起動する。
  - この .bat は Ollama が起動していなければ別ウィンドウで起動し、ブラウザで http://localhost:8765 を開き、uvicorn をフォアグラウンドで動かす。確認作業の間だけ起動していればよい。
  - ポートは **8765**（8000 ではない）。
- 起動したら `http://localhost:8765/api/system/status` にアクセスし、応答JSONを SETUP_RESULT.md にそのまま記録する。特に次の項目を確認する：
  - `whisper_available`（true であること）
  - `ollama_available`（Ollama 導入済みなら true）
  - `generator`（"ollama" または "mock"）
  - `embedder`（検索バックエンド名。tfidf でも可）
  - `vad`（energy でも可）
- トップページ http://localhost:8765 が表示できることも確認する。

### 5. スモークテスト

次の3つを確認し、結果（成功／失敗と、失敗時は状況）を SETUP_RESULT.md に記録する。テスト用の文面には個人情報を入れないこと。

(a) 想定問答の検索：
- API で想定問答を1件登録する：`POST http://localhost:8765/api/qa`、JSON ボディは `{"question": "退職理由を教えてください", "answer": "テスト用の回答です。スキルアップのため転職を決意しました。"}`
- 続けて `POST http://localhost:8765/api/qa/search`、JSON ボディ `{"query": "転職を決意した背景を教えてください。"}` を送り、登録した想定問答が results の先頭にヒットするか確認する（スコアも記録する）。

(b) 手動テキスト入力での回答生成：
- `POST http://localhost:8765/api/sessions` でセッションを作成する（応答の session_id と token を使う）。
- ブラウザで http://localhost:8765 を開き、そのセッションに接続した状態で、`POST http://localhost:8765/api/sessions/{session_id}/manual-input`、JSON ボディ `{"text": "退職理由を教えてください", "force": true}` を送る。
- 画面に回答（要点・回答例）が表示されるか確認する。ブラウザ確認が難しい場合は、WebSocket（ws://localhost:8765/ws/{session_id}?token=...）に接続して answer 系イベントが届くかで代替確認し、その旨を記録する。
- 確認後、`POST http://localhost:8765/api/sessions/{session_id}/end` でセッションを終了する。

(c) PC内部音声（WASAPIループバック）の文字起こし【可能な範囲で】：
- YouTube 等で面接風の動画を再生しながら、セッションに対して `POST http://localhost:8765/api/sessions/{session_id}/audio/start`（フォームパラメータ kind=wasapi_loopback）を送るか、UI の音声開始操作を使う。
- 文字起こし（transcript 系イベント／画面表示）が流れるか確認する。
- 環境上の理由で実施できない場合は、理由（音が出せない、デバイスが見つからない等）を記録する。無理に実施しなくてよい。

### 6. 後片付け

- 確認が終わったらサーバー（uvicorn）を停止してよい。起動したままにしない。
- テストで登録した想定問答は残してよい（テスト用文面のみのため）。

## 結果ファイル SETUP_RESULT.md の書式

interview-app/SETUP_RESULT.md に、次の構成で書くこと：

```
# セットアップ結果（Windows実機）

- 実施日時：
- PCスペック：CPU ／ GPU ／ メモリ

## 手順ごとの結果
1. Python：バージョンと成否
2. setup_windows.bat：成否（失敗時はエラーの要点）
3. Ollama：導入の成否、選んだモデルと判断理由
4. サーバー起動・状態API：/api/system/status の応答JSON 全文
5. スモークテスト：(a) 検索（ヒットの有無とスコア）／ (b) 手動入力での回答表示 ／ (c) ループバック文字起こし

## 残った問題
- （なければ「なし」）
```

## 注意事項

- 課金が発生する操作は一切しない（有料サービスの契約・購入をしない）。
- 管理者権限のダイアログなど、人の操作が必要な場面に当たったら、その旨を結果に書いて、その手順は止める。
- SETUP_RESULT.md やコミットに、ユーザーの実名・メールアドレス等の個人情報を書かない。
- 作業が終わったら（途中で止まった場合も）、SETUP_RESULT.md を commit & push して報告する。
