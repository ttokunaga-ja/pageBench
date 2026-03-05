import os
import csv
import json
import time
import shutil  # <-- 追加
from pathlib import Path
from dotenv import load_dotenv

# 新しいGemini SDKとPydanticをインポート
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


# ---------------------------------------------------------
# 1. 出力スキーマの定義 (Pydantic)
# ---------------------------------------------------------
class QAPair(BaseModel):
    question: str = Field(description="The question based on the document, written in Japanese.")
    reference_answer: str = Field(description="The expected correct answer, written in Japanese.")
    target_page: int = Field(description="The physical page number (integer, starting from 1) where the evidence is found.")
    evidence_text: str = Field(description="The exact text extracted from the document that supports the answer, in Japanese.")

class QADataset(BaseModel):
    qa_list: list[QAPair] = Field(description="A list of generated Question and Answer pairs.")

# ---------------------------------------------------------
# 2. メイン処理
# ---------------------------------------------------------
def run():
    # パスの設定（相対参照）
    current_dir = Path(__file__).resolve().parent
    topic_dir = current_dir.parent
    root_dir = topic_dir.parent

    # 環境変数の読み込み
    load_dotenv(root_dir / ".env")
    API_KEY = os.getenv("GEMINI_API_KEY")
    MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash") # デフォルトを2.5-flashに設定
    TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "600000"))
    RATE_LIMIT_SLEEP_SEC = float(os.getenv("GEMINI_RATE_LIMIT_SLEEP_SEC", "5"))

    if not API_KEY:
        raise ValueError("GEMINI_API_KEY is not set in the .env file.")

    # Geminiクライアントの初期化（google-genai の timeout はミリ秒単位）
    client = genai.Client(
        api_key=API_KEY,
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
    )

    # プロンプトの読み込み
    prompt_file = current_dir / "prompt.txt"
    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    # ファイルパスの設定
    registry_file = topic_dir / "0a_registry.csv"
    output_file = topic_dir / "0b_qa_pairs.csv"
    pdf_dir = topic_dir / "source_pdfs"

    # レジストリの読み込み
    registry = []
    with open(registry_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        registry = list(reader)

    q_id_counter = 1
    print(f"Writing to {output_file}...")
    fieldnames = ["q_id", "question", "reference_answer", "target_file", "target_page", "evidence_text"]
    with open(output_file, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        # 各PDFファイルの処理
        for row in registry:
            file_name = row["file_name"]
            title = row["title"]
            try:
                page_count = int(row["page_count"])
            except ValueError:
                page_count = 1

            pdf_path = pdf_dir / file_name
            if not pdf_path.exists():
                print(f"Skip (File not found): {pdf_path}")
                continue

            # 【ページ数に合わせた問題数の調整】 (3ページにつき1問、最大15問)
            num_questions = max(1, min(15, page_count // 3))

            print(f"Processing: {file_name} (Pages: {page_count}, Target Qs: {num_questions})")

            # プロンプトの構築
            # `str.format` はJSONサンプル中の `{}` まで置換対象と解釈してしまうため、
            # 必要なプレースホルダのみ明示的に置換する
            prompt_text = (
                prompt_template
                .replace("{title}", str(title))
                .replace("{page_count}", str(page_count))
                .replace("{num_questions}", str(num_questions))
            )

            temp_pdf_path = pdf_dir / "temp_upload.pdf"
            uploaded_file_name = None

            try:
                # 1. 日本語ファイル名によるAPIエンコードエラーを回避するための一時コピー作成
                shutil.copy2(pdf_path, temp_pdf_path)

                print("  Uploading PDF to Gemini...", end="", flush=True)
                # オリジナルのファイルパスではなく、ASCII名の一時ファイルをアップロードする
                uploaded_file = client.files.upload(
                    file=str(temp_pdf_path),
                    config=types.UploadFileConfig(
                        http_options=types.HttpOptions(timeout=TIMEOUT_MS)
                    ),
                )

                uploaded_file_name = uploaded_file.name
                if not uploaded_file_name:
                    raise Exception("Uploaded file name is empty.")

                # API側のファイル処理完了を待機
                while getattr(uploaded_file.state, "name", None) == "PROCESSING":
                    print(".", end="", flush=True)
                    time.sleep(2)
                    uploaded_file = client.files.get(name=uploaded_file_name)

                if getattr(uploaded_file.state, "name", None) == "FAILED":
                    raise Exception("File processing failed on Gemini server.")
                print(" Done.")

                # 2. 構造化出力（Structured Output）を用いた生成
                print("  Generating QA data with Structured Output...")
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=[uploaded_file, prompt_text],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=QADataset, # Pydanticスキーマを適用
                        temperature=0.2,           # 事実抽出のため温度を低く設定
                        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
                    )
                )

                # 3. JSONのパース（スキーマが強制されているため安全）
                data = json.loads(response.text or "{}")

                # 取得したQAリストをCSV出力用の形式に変換して逐次書き込み
                generated_count = 0
                for qa in data.get("qa_list", []):
                    writer.writerow({
                        "q_id": q_id_counter,
                        "question": qa.get("question", ""),
                        "reference_answer": qa.get("reference_answer", ""),
                        "target_file": file_name, # レジストリのファイル名と一致させる
                        "target_page": qa.get("target_page", ""),
                        "evidence_text": qa.get("evidence_text", "")
                    })
                    q_id_counter += 1
                    generated_count += 1

                print(f"  -> Generated {generated_count} questions successfully.\n")

            except Exception as e:
                print(f"  -> Error generating QA for {file_name}: {e}\n")

            finally:
                # サーバー上のPDFと、ローカルの一時ファイルを削除（クリーンアップ）
                if uploaded_file_name:
                    try:
                        client.files.delete(name=uploaded_file_name)
                    except Exception as cleanup_error:
                        print(f"  -> Warning: failed to delete uploaded file: {cleanup_error}")

                if temp_pdf_path.exists():
                    os.remove(temp_pdf_path)

            # APIレートリミット対策（環境変数で調整可能）
            if RATE_LIMIT_SLEEP_SEC > 0:
                time.sleep(RATE_LIMIT_SLEEP_SEC)

    print("=== QA Generation Complete ===")

if __name__ == "__main__":
    run()