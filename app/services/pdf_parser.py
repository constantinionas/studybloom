import re
from pathlib import Path

import fitz

from app.schemas.upload_schema import AnswerPreview, QuestionPreview


QUESTION_PATTERN = re.compile(r"^\s*(\d+)[\.\)](?:\s+(.*\S)\s*)?$")
ANSWER_PATTERN = re.compile(r"^\s*([a-jA-J])[\.\)]\s+(.*\S)\s*$")
ANSWER_LABEL_ONLY_PATTERN = re.compile(r"^\s*([a-jA-J])[\.\)]\s*$")
PAGE_NUMBER_PATTERN = re.compile(r"^\s*\d+\s*$")

I_QUESTION_PATTERN = re.compile(
    r"^\s*[IÎl]\s*(\d+)\s+(.+?)\s*$",
    re.IGNORECASE,
)

CORRECT_WRONG_ANSWER_PATTERN = re.compile(
    r"^\s*([a-jA-J])[\.\)]\s+(.+?)\s+(Corect|Greșit|Gresit)\s*$",
    re.IGNORECASE,
)

VERDICT_ONLY_PATTERN = re.compile(
    r"^(.*?)(?:\s+)(Corect|Greșit|Gresit)\s*$",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_verdict(text: str) -> str:
    return (
        text.lower()
        .replace("ș", "s")
        .replace("ş", "s")
        .replace("ă", "a")
        .replace("â", "a")
        .replace("î", "i")
        .replace("ț", "t")
        .replace("ţ", "t")
    )


def extract_page_lines(page: fitz.Page, page_number: int) -> list[dict]:
    page_dict = page.get_text("dict")
    lines: list[dict] = []

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            text = normalize_text(
                "".join(span.get("text", "") for span in line.get("spans", []))
            )

            if not text:
                continue

            lines.append(
                {
                    "text": text,
                    "bbox": fitz.Rect(line["bbox"]),
                    "page": page_number,
                }
            )

    lines.sort(key=lambda item: (round(item["bbox"].y0, 1), item["bbox"].x0))
    return lines


def extract_page_rows(page: fitz.Page, page_number: int) -> list[dict]:
    """
    Grupează liniile după poziția verticală.

    În unele PDF-uri cu tabele, PyMuPDF citește separat celulele:
    I1 | text întrebare | CORECT/GREȘIT
    a. | text răspuns | Corect

    Funcția asta le pune înapoi pe același rând:
    I1 text întrebare CORECT/GREȘIT
    a. text răspuns Corect
    """
    lines = extract_page_lines(page, page_number)
    rows: list[list[dict]] = []

    current_row: list[dict] = []
    current_y: float | None = None
    y_tolerance = 3.2

    for line in lines:
        line_y = line["bbox"].y0

        if current_y is None:
            current_row = [line]
            current_y = line_y
            continue

        if abs(line_y - current_y) <= y_tolerance:
            current_row.append(line)
            current_y = (current_y * 0.7) + (line_y * 0.3)
        else:
            rows.append(current_row)
            current_row = [line]
            current_y = line_y

    if current_row:
        rows.append(current_row)

    merged_rows: list[dict] = []

    for row in rows:
        row.sort(key=lambda item: item["bbox"].x0)

        row_text = normalize_text(" ".join(item["text"] for item in row))

        row_bbox = fitz.Rect(row[0]["bbox"])
        for item in row[1:]:
            row_bbox |= item["bbox"]

        merged_rows.append(
            {
                "text": row_text,
                "bbox": row_bbox,
                "page": page_number,
                "parts": row,
            }
        )

    return merged_rows


def extract_highlights(document: fitz.Document) -> dict[int, list[fitz.Rect]]:
    highlights_by_page: dict[int, list[fitz.Rect]] = {}

    for page_index, page in enumerate(document, start=1):
        page_highlights: list[fitz.Rect] = []

        annotation = page.first_annot
        while annotation:
            annotation_name = annotation.type[1].lower()

            if annotation_name == "highlight":
                page_highlights.append(annotation.rect)

            annotation = annotation.next

        highlights_by_page[page_index] = page_highlights

    return highlights_by_page


def line_is_highlighted(
    line_rect: fitz.Rect,
    highlights: list[fitz.Rect],
) -> bool:
    for highlight_rect in highlights:
        intersection = line_rect & highlight_rect

        if intersection.is_empty:
            continue

        vertical_coverage = intersection.height / max(line_rect.height, 1)

        if intersection.width > 2 and vertical_coverage >= 0.35:
            return True

    return False


def answer_is_highlighted(
    answer_lines: list[dict],
    highlights_by_page: dict[int, list[fitz.Rect]],
) -> bool:
    for line in answer_lines:
        page_highlights = highlights_by_page.get(line["page"], [])

        if line_is_highlighted(line["bbox"], page_highlights):
            return True

    return False


def clean_i_question_text(text: str) -> str:
    text = normalize_text(text)

    text = re.sub(
        r"\s*CORECT\s*/\s*GREȘIT\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*CORECT\s*/\s*GRESIT\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*Corect\s*/\s*greșit\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*Corect\s*/\s*gresit\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return normalize_text(text)


def parse_i_correct_wrong_pdf(
    document: fitz.Document,
) -> tuple[list[QuestionPreview], list[str]]:
    warnings: list[str] = []
    raw_questions: list[dict] = []
    current_question: dict | None = None
    current_answer: dict | None = None

    def finish_current_question() -> None:
        nonlocal current_question

        if current_question is not None:
            raw_questions.append(current_question)

    for page_number, page in enumerate(document, start=1):
        rows = extract_page_rows(page, page_number)

        for row in rows:
            text = row["text"]

            if not text or PAGE_NUMBER_PATTERN.match(text):
                continue

            normalized_lower = normalize_verdict(text)

            if normalized_lower in {
                "corect / gresit",
                "corect/gresit",
                "corect",
                "gresit",
            }:
                continue

            question_match = I_QUESTION_PATTERN.match(text)

            if question_match:
                finish_current_question()

                current_question = {
                    "number": int(question_match.group(1)),
                    "text": clean_i_question_text(question_match.group(2)),
                    "answers": [],
                    "source_pages": [page_number],
                }
                current_answer = None
                continue

            if current_question is None:
                continue

            answer_match = CORRECT_WRONG_ANSWER_PATTERN.match(text)

            if answer_match:
                label = answer_match.group(1).lower()
                answer_text = normalize_text(answer_match.group(2))
                verdict = normalize_verdict(answer_match.group(3))

                current_answer = {
                    "label": label,
                    "text": answer_text,
                    "correct": verdict == "corect",
                    "source_page": page_number,
                }

                current_question["answers"].append(current_answer)

                if page_number not in current_question["source_pages"]:
                    current_question["source_pages"].append(page_number)

                continue

            label_only_match = ANSWER_LABEL_ONLY_PATTERN.match(text)

            if label_only_match:
                current_answer = {
                    "label": label_only_match.group(1).lower(),
                    "text": "",
                    "correct": False,
                    "source_page": page_number,
                }

                current_question["answers"].append(current_answer)

                if page_number not in current_question["source_pages"]:
                    current_question["source_pages"].append(page_number)

                continue

            verdict_match = VERDICT_ONLY_PATTERN.match(text)

            if current_answer is not None and verdict_match:
                continuation_text = normalize_text(verdict_match.group(1))
                verdict = normalize_verdict(verdict_match.group(2))

                if continuation_text:
                    current_answer["text"] = normalize_text(
                        f'{current_answer["text"]} {continuation_text}'
                    )

                current_answer["correct"] = verdict == "corect"

                if page_number not in current_question["source_pages"]:
                    current_question["source_pages"].append(page_number)

                continue

            if current_answer is not None:
                current_answer["text"] = normalize_text(
                    f'{current_answer["text"]} {text}'
                )

                if page_number not in current_question["source_pages"]:
                    current_question["source_pages"].append(page_number)
            else:
                current_question["text"] = normalize_text(
                    f'{current_question["text"]} {text}'
                )

                if page_number not in current_question["source_pages"]:
                    current_question["source_pages"].append(page_number)

    finish_current_question()

    parsed_questions: list[QuestionPreview] = []

    for raw_question in raw_questions:
        answers = [
            AnswerPreview(
                label=answer["label"],
                text=answer["text"],
                correct=answer["correct"],
                source_page=answer["source_page"],
            )
            for answer in raw_question["answers"]
            if normalize_text(answer["text"])
        ]

        if not answers:
            warnings.append(
                f'Întrebarea {raw_question["number"]} nu are variante detectate.'
            )
            continue

        if not any(answer.correct for answer in answers):
            warnings.append(
                f'Întrebarea {raw_question["number"]} nu are niciun răspuns corect detectat.'
            )

        parsed_questions.append(
            QuestionPreview(
                number=raw_question["number"],
                text=raw_question["text"],
                answers=answers,
                source_pages=raw_question["source_pages"],
            )
        )

    if not parsed_questions:
        warnings.append("Nu am găsit întrebări de tip I1 Corect/Gresit în PDF.")

    return parsed_questions, warnings


def parse_highlight_pdf(
    document: fitz.Document,
) -> tuple[list[QuestionPreview], list[str]]:
    warnings: list[str] = []
    raw_questions: list[dict] = []
    current_question: dict | None = None
    current_answer: dict | None = None

    highlights_by_page = extract_highlights(document)

    for page_number, page in enumerate(document, start=1):
        lines = extract_page_lines(page, page_number)

        for line in lines:
            text = line["text"]

            if PAGE_NUMBER_PATTERN.match(text):
                continue

            question_match = QUESTION_PATTERN.match(text)

            if question_match:
                if current_question is not None:
                    raw_questions.append(current_question)

                current_question = {
                    "number": int(question_match.group(1)),
                    "text": question_match.group(2),
                    "answers": [],
                    "source_pages": [page_number],
                }
                current_answer = None
                continue

            if current_question is None:
                continue

            answer_match = ANSWER_PATTERN.match(text)

            if answer_match:
                current_answer = {
                    "label": answer_match.group(1).lower(),
                    "text": answer_match.group(2),
                    "lines": [line],
                    "source_page": page_number,
                }

                current_question["answers"].append(current_answer)

                if page_number not in current_question["source_pages"]:
                    current_question["source_pages"].append(page_number)

                continue

            if current_answer is not None:
                current_answer["text"] = normalize_text(
                    f'{current_answer["text"]} {text}'
                )
                current_answer["lines"].append(line)

                if page_number not in current_question["source_pages"]:
                    current_question["source_pages"].append(page_number)
            else:
                current_question["text"] = normalize_text(
                    f'{current_question["text"]} {text}'
                )

                if page_number not in current_question["source_pages"]:
                    current_question["source_pages"].append(page_number)

    if current_question is not None:
        raw_questions.append(current_question)

    parsed_questions: list[QuestionPreview] = []

    for raw_question in raw_questions:
        answers: list[AnswerPreview] = []

        for raw_answer in raw_question["answers"]:
            answers.append(
                AnswerPreview(
                    label=raw_answer["label"],
                    text=raw_answer["text"],
                    correct=answer_is_highlighted(
                        raw_answer["lines"],
                        highlights_by_page,
                    ),
                    source_page=raw_answer["source_page"],
                )
            )

        if not answers:
            warnings.append(
                f'Întrebarea {raw_question["number"]} nu are variante detectate.'
            )
            continue

        if not any(answer.correct for answer in answers):
            warnings.append(
                f'Întrebarea {raw_question["number"]} nu are niciun răspuns evidențiat detectat.'
            )

        parsed_questions.append(
            QuestionPreview(
                number=raw_question["number"],
                text=raw_question["text"],
                answers=answers,
                source_pages=raw_question["source_pages"],
            )
        )

    if not parsed_questions:
        warnings.append(
            "Nu am găsit întrebări în PDF. Verifică dacă textul este selectabil."
        )

    return parsed_questions, warnings


def parse_pdf_questions(file_path: str | Path) -> tuple[list[QuestionPreview], list[str]]:
    """
    Încearcă întâi formatul I1 + Corect/Gresit.
    Dacă nu găsește întrebări, revine la parserul vechi cu highlight.

    Așa nu stricăm documentele vechi.
    """
    with fitz.open(str(file_path)) as document:
        correct_wrong_questions, correct_wrong_warnings = parse_i_correct_wrong_pdf(
            document
        )

        if correct_wrong_questions:
            return correct_wrong_questions, correct_wrong_warnings

        return parse_highlight_pdf(document)