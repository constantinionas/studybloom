import re
from pathlib import Path

import fitz

from app.schemas.upload_schema import AnswerPreview, QuestionPreview


NUMBERED_LINE_PATTERN = re.compile(r"^\s*(\d+)[\.\)]\s+(.*\S)\s*$")
LETTER_ANSWER_PATTERN = re.compile(r"^\s*([a-jA-J])[\.\)]\s+(.*\S)\s*$")
PAGE_NUMBER_PATTERN = re.compile(r"^\s*\d+\s*$")

MAX_NUMERIC_ANSWER_LABEL = 10


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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


def color_is_visible_highlight(color) -> bool:
    if not color or len(color) < 3:
        return False

    red, green, blue = color[:3]

    if red > 0.92 and green > 0.92 and blue > 0.92:
        return False

    if red < 0.12 and green < 0.12 and blue < 0.12:
        return False

    if max(red, green, blue) - min(red, green, blue) < 0.08:
        return False

    return True


def extract_annotation_highlights(document: fitz.Document) -> dict[int, list[fitz.Rect]]:
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


def extract_drawn_highlights(document: fitz.Document) -> dict[int, list[fitz.Rect]]:
    highlights_by_page: dict[int, list[fitz.Rect]] = {}

    for page_index, page in enumerate(document, start=1):
        page_highlights: list[fitz.Rect] = []

        for drawing in page.get_drawings():
            rect = drawing.get("rect")

            if rect is None:
                continue

            fill_color = drawing.get("fill")
            stroke_color = drawing.get("color")

            has_highlight_color = color_is_visible_highlight(
                fill_color
            ) or color_is_visible_highlight(stroke_color)

            if not has_highlight_color:
                continue

            highlight_rect = fitz.Rect(rect)

            if highlight_rect.width < 8 or highlight_rect.height < 2:
                continue

            page_highlights.append(highlight_rect)

        highlights_by_page[page_index] = page_highlights

    return highlights_by_page


def merge_highlights(
    annotation_highlights: dict[int, list[fitz.Rect]],
    drawn_highlights: dict[int, list[fitz.Rect]],
) -> dict[int, list[fitz.Rect]]:
    page_numbers = set(annotation_highlights.keys()) | set(drawn_highlights.keys())
    merged: dict[int, list[fitz.Rect]] = {}

    for page_number in page_numbers:
        merged[page_number] = [
            *annotation_highlights.get(page_number, []),
            *drawn_highlights.get(page_number, []),
        ]

    return merged


def line_is_highlighted(line_rect: fitz.Rect, highlights: list[fitz.Rect]) -> bool:
    for highlight_rect in highlights:
        intersection = line_rect & highlight_rect

        if intersection.is_empty:
            continue

        vertical_coverage = intersection.height / max(line_rect.height, 1)
        horizontal_coverage = intersection.width / max(line_rect.width, 1)

        if (
            intersection.width > 2
            and vertical_coverage >= 0.20
            and horizontal_coverage >= 0.08
        ):
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


def start_question(
    raw_questions: list[dict],
    current_question: dict | None,
    question_number: int,
    question_text: str,
    page_number: int,
) -> dict:
    if current_question is not None:
        raw_questions.append(current_question)

    return {
        "number": question_number,
        "text": normalize_text(question_text),
        "answers": [],
        "source_pages": [page_number],
    }


def add_answer(
    current_question: dict,
    label: str,
    answer_text: str,
    line: dict,
    page_number: int,
) -> dict:
    answer = {
        "label": str(label).lower(),
        "text": normalize_text(answer_text),
        "lines": [line],
        "source_page": page_number,
    }

    current_question["answers"].append(answer)

    if page_number not in current_question["source_pages"]:
        current_question["source_pages"].append(page_number)

    return answer


def get_next_expected_numeric_answer(current_question: dict) -> int:
    numeric_answers = []

    for answer in current_question["answers"]:
        try:
            numeric_answers.append(int(answer["label"]))
        except ValueError:
            continue

    if not numeric_answers:
        return 1

    return max(numeric_answers) + 1


def should_start_new_question_from_number(
    current_question: dict,
    line_number: int,
) -> bool:
    answers_count = len(current_question["answers"])

    if answers_count >= MAX_NUMERIC_ANSWER_LABEL:
        return True

    expected_answer_number = get_next_expected_numeric_answer(current_question)

    if 1 <= line_number <= MAX_NUMERIC_ANSWER_LABEL:
        return line_number != expected_answer_number

    return True


def parse_pdf_questions(file_path: str | Path) -> tuple[list[QuestionPreview], list[str]]:
    warnings: list[str] = []
    raw_questions: list[dict] = []
    current_question: dict | None = None
    current_answer: dict | None = None

    with fitz.open(str(file_path)) as document:
        highlights_by_page = merge_highlights(
            extract_annotation_highlights(document),
            extract_drawn_highlights(document),
        )

        for page_number, page in enumerate(document, start=1):
            lines = extract_page_lines(page, page_number)

            for line in lines:
                text = line["text"]

                if PAGE_NUMBER_PATTERN.match(text):
                    continue

                letter_answer_match = LETTER_ANSWER_PATTERN.match(text)

                if current_question is not None and letter_answer_match:
                    current_answer = add_answer(
                        current_question=current_question,
                        label=letter_answer_match.group(1),
                        answer_text=letter_answer_match.group(2),
                        line=line,
                        page_number=page_number,
                    )
                    continue

                numbered_match = NUMBERED_LINE_PATTERN.match(text)

                if numbered_match:
                    line_number = int(numbered_match.group(1))
                    line_text = numbered_match.group(2)

                    if current_question is None:
                        current_question = start_question(
                            raw_questions=raw_questions,
                            current_question=current_question,
                            question_number=line_number,
                            question_text=line_text,
                            page_number=page_number,
                        )
                        current_answer = None
                        continue

                    if should_start_new_question_from_number(
                        current_question,
                        line_number,
                    ):
                        current_question = start_question(
                            raw_questions=raw_questions,
                            current_question=current_question,
                            question_number=line_number,
                            question_text=line_text,
                            page_number=page_number,
                        )
                        current_answer = None
                        continue

                    current_answer = add_answer(
                        current_question=current_question,
                        label=str(line_number),
                        answer_text=line_text,
                        line=line,
                        page_number=page_number,
                    )
                    continue

                if current_question is None:
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
