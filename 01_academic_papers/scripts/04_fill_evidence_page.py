import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional

from pypdf import PdfReader


NULL_LIKE_VALUES = {"", "null", "none", "nan", "na"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fill target_page by searching evidence_text fragments in each PDF page."
        )
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to 0b_qa_pairs.csv (default: ../0b_qa_pairs.csv from this script).",
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=None,
        help="Directory containing source PDFs (default: ../source_pdfs from this script).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path. If omitted, input CSV is overwritten.",
    )
    parser.add_argument(
        "--first-words",
        type=int,
        default=10,
        help="Maximum number of words used for matching (default: 10).",
    )
    parser.add_argument(
        "--min-words",
        type=int,
        default=1,
        help="Minimum number of words used for fallback matching (default: 1).",
    )
    parser.add_argument(
        "--overwrite-target-page",
        action="store_true",
        help="Overwrite existing target_page values as well (default: fill only when NULL-like).",
    )
    return parser.parse_args()


def is_null_like(value: Optional[str]) -> bool:
    if value is None:
        return True
    return value.strip().lower() in NULL_LIKE_VALUES


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def normalize_text_loose(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def tokenize_words(text: str) -> List[str]:
    return re.findall(r"\S+", text or "")


def build_candidate_queries(words: List[str], max_words: int, min_words: int) -> List[str]:
    if not words:
        return []

    safe_max = max(1, min(max_words, len(words)))
    safe_min = max(1, min(min_words, safe_max))

    candidates: List[str] = []
    for window_size in range(safe_max, safe_min - 1, -1):
        for start_idx in range(0, len(words) - window_size + 1):
            candidates.append(" ".join(words[start_idx : start_idx + window_size]))

    return candidates


def load_pdf_pages(pdf_path: Path) -> List[str]:
    reader = PdfReader(str(pdf_path))
    pages: List[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        pages.append(normalize_text(page_text))
    return pages


def find_page(queries: List[str], pages_normalized: List[str]) -> Optional[int]:
    if not queries:
        return None

    for query_text in queries:
        query = normalize_text(query_text)
        if query:
            for i, page_text in enumerate(pages_normalized, start=1):
                if query in page_text:
                    return i

        # Fallback for punctuation/layout differences.
        query_loose = normalize_text_loose(query_text)
        if query_loose:
            for i, page_text in enumerate(pages_normalized, start=1):
                if query_loose in normalize_text_loose(page_text):
                    return i

    return None


def main() -> None:
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    dataset_dir = script_dir.parent

    csv_path = args.csv or (dataset_dir / "0b_qa_pairs.csv")
    pdf_dir = args.pdf_dir or (dataset_dir / "source_pdfs")
    output_path = args.output or csv_path

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    if not pdf_dir.exists():
        raise FileNotFoundError(f"PDF directory not found: {pdf_dir}")

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not reader.fieldnames:
            raise ValueError("CSV has no header.")
        fieldnames = list(reader.fieldnames)

    page_column = "target_page"
    if page_column not in fieldnames:
        fieldnames.append(page_column)

    pdf_cache: Dict[str, List[str]] = {}
    updated = 0
    matched = 0
    missing_pdf = 0

    for row in rows:
        target_file = (row.get("target_file") or "").strip()
        evidence_text = row.get("evidence_text") or ""

        if not target_file:
            if args.overwrite_target_page or is_null_like(row.get(page_column)):
                row[page_column] = "NULL"
            continue

        pdf_path = pdf_dir / target_file
        if not pdf_path.exists():
            if args.overwrite_target_page or is_null_like(row.get(page_column)):
                row[page_column] = "NULL"
            missing_pdf += 1
            continue

        if target_file not in pdf_cache:
            pdf_cache[target_file] = load_pdf_pages(pdf_path)

        words = tokenize_words(evidence_text)
        candidate_queries = build_candidate_queries(
            words=words,
            max_words=args.first_words,
            min_words=args.min_words,
        )
        page = find_page(candidate_queries, pdf_cache[target_file])

        found_page = str(page) if page is not None else "NULL"
        if args.overwrite_target_page or is_null_like(row.get(page_column)):
            row[page_column] = found_page

        updated += 1
        if page is not None:
            matched += 1

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Input CSV:   {csv_path}")
    print(f"Output CSV:  {output_path}")
    print(f"PDF folder:  {pdf_dir}")
    print(f"Rows handled: {updated}")
    print(f"Matched rows: {matched}")
    print(f"Missing PDFs: {missing_pdf}")


if __name__ == "__main__":
    main()
