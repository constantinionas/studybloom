import re
from pathlib import Path

import fitz

from app.schemas.upload_schema import AnswerPreview, QuestionPreview


QUESTION_PATTERN = re.compile(r"^\s*(\d+)[\.\)](?:\s+(.*\S)\s*)?$")
ANSWER_PATTERN = re.compile(r"^\s*([a-jA-J])[\.\)]\s+(.*\S)\s*$")
PAGE_NUMBER_PATTERN = re.compile(r"^\s*\d+\s*$")


def normalize_text(text: str) -> str:
    """Elimină spațiile repetate și marginile inutile."""
    return re.sub(r"\s+", " ", text).strip()


def extract_page_lines(page: fitz.Page, page_number: int) -> list[dict]:
    """
    Extrage liniile de text și coordonatele lor.
    Coordonatele sunt necesare pentru asocierea highlight-ului
    cu varianta de răspuns.
    """
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


def extract_highlights(document: fitz.Document) -> dict[int, list[fitz.Rect]]:
    """
    Găsește toate adnotările de tip Highlight.
    Culoarea nu este verificată: orice highlight înseamnă răspuns corect.
    """
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
    """
    Verifică dacă o linie este acoperită suficient de un highlight.

    Nu folosim doar simpla atingere a dreptunghiurilor, deoarece markerul
    poate ajunge foarte puțin peste linia vecină și ar produce răspunsuri
    corecte false.
    """
    for highlight_rect in highlights:
        intersection = line_rect & highlight_rect

        if intersection.is_empty:
            continue

        vertical_coverage = intersection.height / line_rect.height

        if intersection.width > 2 and vertical_coverage >= 0.35:
            return True

    return False


def answer_is_highlighted(
    answer_lines: list[dict],
    highlights_by_page: dict[int, list[fitz.Rect]],
) -> bool:
    """
    O variantă poate ocupa mai multe rânduri sau poate continua pe pagina
    următoare. Este corectă dacă minimum o linie a sa are highlight.
    """
    for line in answer_lines:
        page_highlights = highlights_by_page.get(line["page"], [])

        if line_is_highlighted(line["bbox"], page_highlights):
            return True

    return False


def parse_pdf_questions(file_path: str | Path) -> tuple[list[QuestionPreview], list[str]]:
    """
    Extrage întrebările și răspunsurile corecte dintr-un PDF cu text
    selectabil și răspunsuri marcate prin Highlight.
    """
    warnings: list[str] = []
    raw_questions: list[dict] = []
    current_question: dict | None = None
    current_answer: dict | None = None

    # Folosim context manager ca PDF-ul să fie închis automat,
    # inclusiv dacă apare o eroare în timpul procesării.
    with fitz.open(str(file_path)) as document:
        highlights_by_page = extract_highlights(document)

        for page_number, page in enumerate(document, start=1):
            lines = extract_page_lines(page, page_number)

            for line in lines:
                text = line["text"]

                # Ignorăm numărul simplu al paginii.
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
                    # Ignorăm titluri sau antete dinaintea primei întrebări.
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
                    # Linie care continuă textul variantei precedente.
                    current_answer["text"] = normalize_text(
                        f'{current_answer["text"]} {text}'
                    )
                    current_answer["lines"].append(line)

                    if page_number not in current_question["source_pages"]:
                        current_question["source_pages"].append(page_number)
                else:
                    # Linie care continuă enunțul întrebării.
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