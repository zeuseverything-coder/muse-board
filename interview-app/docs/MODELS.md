# AIモデル導入手順

すべてローカル実行・無料です。外部APIは使用しません。

## 1. 音声認識: faster-whisper

- 既定モデル: `base`（約140MB、CPU int8量子化）。初回起動時に自動ダウンロードされます（`scripts/setup_windows.bat` で事前取得も可能）。
- モデル変更: 環境変数 `ISA_WHISPER_MODEL`（例: `small` / `medium` / `large-v3-turbo`）。
- 選定指針（実機スペック別）:
  - CPUのみ・メモリ8GB: `base`（低遅延優先）または `small`（精度優先）
  - CPUのみ・メモリ16GB以上: `small` 推奨、`medium` も可（遅延増）
  - GPU（VRAM 6GB以上）: `large-v3-turbo` を `device="cuda", compute_type="float16"` で（コード内 `_load_model` の device 指定を変更）

## 2. 生成AI: Ollama（Windows実機）

1. https://ollama.com/download から Windows 版をインストール
2. モデル取得（初回のみネット接続が必要）:
   - 標準: `ollama pull qwen2.5:7b-instruct-q4_K_M`（約4.7GB、日本語品質と速度のバランス）
   - 軽量: `ollama pull qwen2.5:3b-instruct-q4_K_M`（低スペックPC向け）
   - 高品質: `ollama pull qwen2.5:14b-instruct-q4_K_M`（メモリ16GB以上）
3. 起動: `ollama serve`（`start_windows.bat` が未起動時に自動で起動を試みます）
4. アプリ側の接続先は環境変数で変更可能: `OLLAMA_URL`（既定 `http://127.0.0.1:11434`）、`ISA_OLLAMA_MODEL`（既定 `qwen2.5:7b-instruct-q4_K_M`）

Ollama が動いていない場合、アプリは自動的に「モック生成」に切り替わります。
モック生成は登録資料・想定問答の内容だけから要点と回答を組み立てる決定的処理で、
捏造はしませんが、文章の自然さはLLMに劣ります。画面上ではバッジで区別されます。

## 3. 意味検索（想定問答のマッチング）

- 既定（auto）: sentence-transformers が導入済みなら `intfloat/multilingual-e5-small` を使用し、なければ文字n-gram TF-IDF + 日本語概念正規化のフォールバックで動作します。
- 高精度化したい場合: `pip install sentence-transformers` 後、初回検索時にモデル（約470MB）が自動取得されます。環境変数 `ISA_EMBEDDER=st|tfidf|auto`、`ISA_ST_MODEL` で切替可能。
- 一致しきい値: 環境変数 `ISA_QA_THRESHOLD`（既定 0.30）。TF-IDFバックエンドでの実測では、言い回しの異なる同一テーマ質問が 0.32〜0.73 を記録しました（TEST_RESULTS.md 参照）。

## 4. VAD（音声区間検出）

- 既定: エネルギーベースVAD（依存なし）。
- 任意: `pip install silero-vad` し、環境変数 `ISA_VAD=silero` で Silero VAD に切替可能（無音区間の切り分け精度が上がります）。
