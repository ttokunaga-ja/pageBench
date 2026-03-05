# PageBench

PDF文書からQ&Aデータセットを作成するための実験用リポジトリです。  
トピックごとにフォルダを分け、以下のCSVを生成します。

- `0a_registry.csv`: 文書一覧（ファイル名、タイトル、URL、ページ数）
- `0b_qa_pairs.csv`: Q&Aペア（質問、参照解答、対象ファイル、ページ、根拠テキスト）

## ディレクトリ構成

- `00_sample/`
- `01_academic_papers/`
- `02_financial_results/`
- `03_government_policy/`

各トピック配下の基本構成:

- `source_pdfs/`: 入力PDF
- `scripts/`: 生成スクリプト
- `0a_registry.csv`: 文書レジストリ
- `0b_qa_pairs.csv`: Q&A出力

## 前提環境

- Python 3.10+ 推奨
- macOS の場合: `brew` が使えること
- Gemini API キー

## セットアップ

### 1. 仮想環境を作成して有効化

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 依存関係のインストール

`setup_env.py` はOS依存ツールとPythonパッケージをまとめてセットアップします。

```bash
python setup_env.py
```

補足:

- チェックのみ実行: `python setup_env.py --check`
- システム依存をスキップ: `python setup_env.py --skip-system`
- Python依存をスキップ: `python setup_env.py --skip-python`
- 強制再インストール: `python setup_env.py --force`

### 3. `.env` を作成

リポジトリ直下に `.env` を作成し、以下を設定します。

```env
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-3.1-flash-lite-preview
GEMINI_TIMEOUT_MS=600000
GEMINI_RATE_LIMIT_SLEEP_SEC=5
```

### 4. NLTKリソースの取得（必要時）

SSLやNLTKリソース不足で失敗する場合は実行してください。

```bash
python fix_nltk.py
```

## 実行方法

### A. `01_academic_papers` を作成する（推奨の最短ルート）

`01_academic_papers/scripts/01_fetch_data.py` は、以下を一括で実行します。

- Qasperデータセットの取得
- PDFダウンロード（`source_pdfs/`）
- `0a_registry.csv` 生成
- `0b_qa_pairs.csv` 生成（`target_page` は `NULL`）

```bash
python 01_academic_papers/scripts/01_fetch_data.py --limit 20
```

主なオプション:

- `--split`（既定: `train`）
- `--sleep-seconds`（既定: `1.0`）
- `--timeout`（既定: `20.0`）

必要に応じて、根拠テキストからページ番号を埋める処理を実行できます。

```bash
python 01_academic_papers/scripts/04_fill_evidence_page.py
```

上書きしたい場合:

```bash
python 01_academic_papers/scripts/04_fill_evidence_page.py --overwrite-target-page
```

### B. `00_sample` / `02_financial_results` / `03_government_policy` を作成する

これら3トピックは同じ処理フローです。

1. `source_pdfs/` に元PDFを配置
2. `scripts/02_create_registry_cvs.py` でPDFをリネームし、`0a_registry.csv` 生成
3. `scripts/03_generate_qa.py` で Gemini を使って `0b_qa_pairs.csv` 生成

例: `02_financial_results` の場合

```bash
python 02_financial_results/scripts/02_create_registry_cvs.py
python 02_financial_results/scripts/03_generate_qa.py
```

注意:

- `scripts/01_fetch_data.py` は `00_sample` / `02_financial_results` / `03_government_policy` では現状空ファイルです。
- `02_create_registry_cvs.py` 実行時にPDFは `02_01_xxx.pdf` のようにリネームされます（トピックIDに応じて接頭辞が変化）。

## 出力CSV仕様

### `0a_registry.csv`

- `file_name`: 保存PDF名
- `title`: タイトル（多くのケースで元ファイル名）
- `source_url`: 出典URL（不明時 `null`）
- `page_count`: ページ数

### `0b_qa_pairs.csv`

- `q_id`: 質問ID
- `question`: 質問文
- `reference_answer`: 期待解答
- `target_file`: 対象PDF名
- `target_page`: 根拠ページ（不明時 `NULL`）
- `evidence_text`: 根拠本文

## トラブルシューティング

- `GEMINI_API_KEY is not set`: `.env` が存在するか、キー名が正しいか確認
- `zsh: command not found: brew`: Homebrewをインストールして再実行
- OCR/ページ数取得周りで失敗: `python setup_env.py` を再実行して `poppler` / `tesseract` を確認
- NLTK関連エラー: `python fix_nltk.py` を実行

## 補足

- スクリプト名は `create_registry_cvs.py`（`csv` ではなく `cvs`）です。
- `setup_env.py` は `requirements.txt` のハッシュを `.setup_state.json` に保存し、差分がない場合は再インストールをスキップします。
