import os
import csv
from pathlib import Path
from unstructured.partition.auto import partition

def run():
    # 1. パスの設定（相対参照）
    # スクリプトの場所から見た親フォルダ（トピックフォルダ）を取得
    current_dir = Path(__file__).resolve().parent
    topic_dir = current_dir.parent
    pdf_dir = topic_dir / "source_pdfs"
    csv_path = topic_dir / "0a_registry.csv"

    # トピックフォルダ名の先頭2文字を取得 (例: "02")
    topic_id = topic_dir.name[:2]

    print(f"Processing topic: {topic_dir.name} (ID: {topic_id})")

    # 2. PDFファイルのリスト取得（隠しファイルを除外）
    files = sorted([f for f in os.listdir(pdf_dir) if not f.startswith('.') and (pdf_dir / f).is_file()])
    
    if not files:
        print("No files found in source_pdfs.")
        return

    registry_data = []

    # 3. ファイルのリネームと情報取得
    for i, original_name in enumerate(files, 1):
        # 新しいファイル名の作成 (例: 02_01_original.pdf)
        new_name = f"{topic_id}_{i:02d}_{original_name}"
        
        old_file_path = pdf_dir / original_name
        new_file_path = pdf_dir / new_name

        print(f"Renaming: {original_name} -> {new_name}")
        os.rename(old_file_path, new_file_path)

        # 4. Unstructuredを使用してページ数をカウント
        print(f"Counting pages for: {new_name}...")
        try:
            elements = partition(
                filename=str(new_file_path),
                languages=["jpn", "eng"],  # 日本語と英語を指定
                strategy="fast"             # ページ数取得が目的なら "fast" にすると高速化します
            )
            # メタデータからpage_numberの最大値を取得
            pages = [el.metadata.page_number for el in elements if el.metadata.page_number is not None]
            page_count = max(pages) if pages else 1
        except Exception as e:
            print(f"Error processing {new_name}: {e}")
            page_count = 0

        # registryに追加するデータ行を作成
        registry_data.append({
            "file_name": new_name,
            "title": original_name, # titleにはリネーム前の名称を入れる
            "source_url": "null",
            "page_count": page_count
        })

    # 5. CSVへの書き出し
    header = ["file_name", "title", "source_url", "page_count"]
    
    try:
        with open(csv_path, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(registry_data)
        print(f"\nSuccessfully created: {csv_path}")
    except Exception as e:
        print(f"CSV Write Error: {e}")

if __name__ == "__main__":
    run()