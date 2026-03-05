import argparse
import csv
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests
from datasets import load_dataset
from pypdf import PdfReader


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Download academic papers from Qasper and generate 0a_registry.csv and 0b_qa_pairs.csv in one run."
		)
	)
	parser.add_argument(
		"--limit",
		type=int,
		default=20,
		help="Maximum number of papers to include (existing PDFs are counted).",
	)
	parser.add_argument(
		"--split",
		default="train",
		help="Dataset split to use from allenai/qasper (default: train).",
	)
	parser.add_argument(
		"--sleep-seconds",
		type=float,
		default=1.0,
		help="Wait time between downloads to reduce server load.",
	)
	parser.add_argument(
		"--timeout",
		type=float,
		default=20.0,
		help="HTTP timeout (seconds) for PDF download.",
	)
	return parser.parse_args()


def get_base_paths() -> Dict[str, Path]:
	script_dir = Path(__file__).resolve().parent
	dataset_root = script_dir.parent
	source_pdfs = dataset_root / "source_pdfs"

	source_pdfs.mkdir(parents=True, exist_ok=True)

	return {
		"dataset_root": dataset_root,
		"source_pdfs": source_pdfs,
		"registry_csv": dataset_root / "0a_registry.csv",
		"qa_csv": dataset_root / "0b_qa_pairs.csv",
	}


def get_pdf_url(paper_id: str) -> str:
	return f"https://arxiv.org/pdf/{paper_id}.pdf"


def download_pdf(pdf_url: str, save_path: Path, timeout: float) -> bool:
	response = requests.get(pdf_url, timeout=timeout)
	if response.status_code != 200:
		return False

	save_path.write_bytes(response.content)
	return True


def count_pdf_pages(pdf_path: Path) -> int:
	try:
		reader = PdfReader(str(pdf_path))
		return len(reader.pages)
	except Exception:
		return 0


def normalize_answer(answers: Any) -> str:
	# Qasper provides each element as a dict with key 'answer';
	# earlier code assumed a list, so accept either type.
	if isinstance(answers, dict):
		first_answer = answers
	elif isinstance(answers, list) and len(answers) > 0:
		first_answer = answers[0]
	else:
		return ""

	if not isinstance(first_answer, dict):
		return ""

	answer_list = first_answer.get("answer")
	if not isinstance(answer_list, list) or len(answer_list) == 0:
		return ""

	answer_payload = answer_list[0]
	if not isinstance(answer_payload, dict):
		return ""

	free_form = answer_payload.get("free_form_answer")
	if isinstance(free_form, str) and free_form.strip():
		return " ".join(free_form.split())

	extractive_spans = answer_payload.get("extractive_spans")
	if isinstance(extractive_spans, list):
		# remove newlines/extra spaces from extractive spans
		joined = " ".join(" ".join(str(span).split()) for span in extractive_spans if str(span).strip())
		if joined:
			return joined

	yes_no = answer_payload.get("yes_no")
	if isinstance(yes_no, bool):
		return "yes" if yes_no else "no"

	if answer_payload.get("unanswerable") is True:
		return "unanswerable"

	return ""


def normalize_evidence(answers: Any) -> str:
	# Accept dict or list like normalize_answer above.
	if isinstance(answers, dict):
		first_answer = answers
	elif isinstance(answers, list) and len(answers) > 0:
		first_answer = answers[0]
	else:
		return ""

	if not isinstance(first_answer, dict):
		return ""

	answer_list = first_answer.get("answer")
	if not isinstance(answer_list, list) or len(answer_list) == 0:
		return ""

	answer_payload = answer_list[0]
	if not isinstance(answer_payload, dict):
		return ""

	evidence = answer_payload.get("evidence")
	if not isinstance(evidence, list):
		return ""

	flattened: List[str] = []
	for item in evidence:
		if isinstance(item, list):
			flattened.extend(" ".join(str(x).split()) for x in item if str(x).strip())
		elif isinstance(item, str) and item.strip():
			flattened.append(" ".join(item.split()))

	return " | ".join(flattened)


def build_qa_rows(paper: Dict[str, Any], file_name: str) -> Iterable[Dict[str, str]]:
	qas = paper.get("qas")
	if not isinstance(qas, dict):
		return []

	questions = qas.get("question", [])
	question_ids = qas.get("question_id", [])
	answers_per_question = qas.get("answers", [])

	if not isinstance(questions, list) or not isinstance(answers_per_question, list):
		return []

	count = min(len(questions), len(answers_per_question))

	rows: List[Dict[str, str]] = []
	for i in range(count):
		question = str(questions[i]).strip()
		if not question:
			continue

		q_id = str(question_ids[i]).strip() if i < len(question_ids) else ""
		answers = answers_per_question[i]
		reference_answer = normalize_answer(answers)
		evidence_text = normalize_evidence(answers)

		rows.append(
			{
				"q_id": q_id,
				"question": question,
				"reference_answer": reference_answer,
				"target_file": file_name,
				# Qasper dataset does not include page numbers; record as NULL
				"target_page": "NULL",
				"evidence_text": evidence_text,
			}
		)

	return rows


def write_csv(path: Path, fieldnames: List[str], rows: Iterable[Dict[str, str]]) -> None:
	with path.open("w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(rows)


def main() -> None:
	args = parse_args()
	paths = get_base_paths()

	print("Loading dataset: allenai/qasper ...")
	dataset = load_dataset(
		"allenai/qasper",
		split=args.split,
		revision="refs/convert/parquet",
	)

	selected_papers: List[Dict[str, Any]] = []
	downloaded_count = 0

	print(f"Preparing up to {args.limit} papers...")
	for paper in dataset:
		if len(selected_papers) >= args.limit:
			break

		paper_id = str(paper.get("id", "")).strip()
		title = str(paper.get("title", "")).strip()
		if not paper_id:
			continue

		file_name = f"{paper_id}.pdf"
		save_path = paths["source_pdfs"] / file_name
		pdf_url = get_pdf_url(paper_id)

		if save_path.exists():
			print(f"[Skip] {paper_id} already exists.")
		else:
			print(f"[Download] {paper_id} - {title[:50]}")
			try:
				ok = download_pdf(pdf_url=pdf_url, save_path=save_path, timeout=args.timeout)
				if not ok:
					print(f"  -> Failed (HTTP status != 200): {paper_id}")
					continue
				downloaded_count += 1
				time.sleep(args.sleep_seconds)
			except Exception as ex:
				print(f"  -> Failed ({paper_id}): {ex}")
				continue

		selected_papers.append(paper)

	registry_rows: List[Dict[str, str]] = []
	qa_rows: List[Dict[str, str]] = []

	for paper in selected_papers:
		paper_id = str(paper.get("id", "")).strip()
		title = str(paper.get("title", "")).strip()
		file_name = f"{paper_id}.pdf"
		save_path = paths["source_pdfs"] / file_name
		pdf_url = get_pdf_url(paper_id)

		page_count = count_pdf_pages(save_path) if save_path.exists() else 0
		registry_rows.append(
			{
				"file_name": file_name,
				"title": title,
				"source_url": pdf_url,
				"page_count": str(page_count),
			}
		)
		qa_rows.extend(build_qa_rows(paper, file_name))

	write_csv(
		paths["registry_csv"],
		fieldnames=["file_name", "title", "source_url", "page_count"],
		rows=registry_rows,
	)
	write_csv(
		paths["qa_csv"],
		fieldnames=["q_id", "question", "reference_answer", "target_file", "target_page", "evidence_text"],
		rows=qa_rows,
	)

	print("Done.")
	print(f"Downloaded this run: {downloaded_count}")
	print(f"Registry rows: {len(registry_rows)} -> {paths['registry_csv']}")
	print(f"QA rows: {len(qa_rows)} -> {paths['qa_csv']}")


if __name__ == "__main__":
	main()
