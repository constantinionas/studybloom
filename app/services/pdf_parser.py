import re
from pathlib import Path

import fitz

from app.schemas.upload_schema import AnswerPreview, QuestionPreview


QUESTION_PATTERN = re.compile(r"^\s*(\d+)[\.\)](?:\s+(.*\S)\s*)?$")
LETTER_ANSWER_PATTERN = re.compile(r"^\s*([a-jA-J])[\.\)]\s+(.*\S)\s*$")
NUMBERED_LINE_PATTERN = re.compile(r"^\s*(\d+)[\.\)]\s+(.*\S)\s*$")
PAGE_NUMBER_PATTERN = re.compile(r"^\s*\d+\s*$")

MAX_NUMERIC_ANSWER_LABEL = 10


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


def color_is_visible_highlight(color) -> bool:
    """
    Acceptă aproape orice culoare vizibilă folosită ca marker.
    Exclude alb, negru și griuri foarte neutre.
    PyMuPDF returnează culori în intervalul 0-1.
    """
    if not color:
        return False

    if len(color) < 3:
        return False

    red, green, blue = color[:3]

    # Excludem alb / aproape alb.
    if red > 0.92 and green > 0.92 and blue > 0.92:
        return False

    # Excludem negru / aproape negru.
    if red < 0.12 and green < 0.12 and blue < 0.12:
        return False

    # Excludem griuri neutre.
    max_channel = max(red, green, blue)
    min_channel = min(red, green, blue)

    if max_channel - min_channel < 0.08:
        return False

    return True


def extract_annotation_highlights(document: fitz.Document) -> dict[int, list[fitz.Rect]]:
    """
    Găsește adnotările PDF de tip Highlight.
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


def extract_drawn_highlights(document: fitz.Document) -> dict[int, list[fitz.Rect]]:
    """
    Găsește highlight-uri desenate direct în PDF, nu salvate ca adnotări.
    Asta acoperă PDF-uri exportate de pe iPad sau din aplicații care lipesc
    culoarea ca dreptunghi peste/sub text.
    """
    highlights_by_page: dict[int, list[fitz.Rect]] = {}

    for page_index, page in enumerate(document, start=1):
        page_highlights: list[fitz.Rect] = []

        for drawing in page.get_drawings():
            fill_color = drawing.get("fill")
            stroke_color = drawing.get("color")
            rect = drawing.get("rect")

            if rect is None:
                continue

            highlight_color = fill_color if color_is_visible_highlight(fill_color) else stroke_color

            if not color_is_visible_highlight(highlight_color):
                continue

            highlight_rect = fitz.Rect(rect)

            # Evităm linii decorative foarte mici.
            if highlight_rect.width < 8 or highlight_rect.height < 2:
                continue

            page_highlights.append(highlight_rect)

        highlights_by_page[page_index] = page_highlights

    return highlights_by_page


def merge_highlights(
    annotation_highlights: dict[int, list[fitz.Rect]],
    drawn_highlights: dict[int, list[fitz.Rect]],
) -> dict[int, list[fitz.Rect]]:
    all_pages = set(annotation_highlights.keys()) | set(drawn_highlights.keys())
    merged: dict[int, list[fitz.Rect]] = {}

    for page_number in all_pages:
        merged[page_number] = [
            *annotation_highlights.get(page_number, []),
            *drawn_highlights.get(page_number, []),
        ]

    return merged


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

        vertical_coverage = intersection.height / max(line_rect.height, 1)
        horizontal_coverage = intersection.width / max(line_rect.width, 1)

        if intersection.width > 2 and vertical_coverage >= 0.25 and horizontal_coverage >= 0.12:
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


def looks_like_question_text(text: str) -> bool:
    """
    În documentele cu variante 1-10, și întrebările și variantele încep cu număr.
    Folosim indicii simple ca să separăm întrebarea de variante.
    """
    normalized = normalize_text(text).lower()

    if not normalized:
        return False

    if normalized.endswith(":"):
        return True

    question_keywords = [
        "sunt:",
        "este:",
        "cuprind:",
        "cuprinde:",
        "se poate spune",
        "sunt adevărate",
        "sunt false",
        "nu sunt",
        "se recomandă",
        "se evită",
        "fac parte",
        "se regăsesc",
        "următoarele",
        "referitor la",
        "despre",
        "printre",
    ]

    return any(keyword in normalized for keyword in question_keywords)


def start_new_question(
    raw_questions: list[dict],
    current_question: dict | None,
    question_number: int,
    question_text: str | None,
    page_number: int,
) -> dict:
    if current_question is not None:
        raw_questions.append(current_question)

    return {
        "number": question_number,
        "text": normalize_text(question_text or ""),
        "answers": [],
        "source_pages": [page_number],
    }


def add_answer_to_question(
    current_question: dict,
    label: str,
    answer_text: str,
    line: dict,
    page_number: int,
) -> dict:
    current_answer = {
        "label": str(label).lower(),
        "text": normalize_text(answer_text),
        "lines": [line],
        "source_page": page_number,
    }

    current_question["answers"].append(current_answer)

    if page_number not in current_question["source_pages"]:
        current_question["source_pages"].append(page_number)

    return current_answer


def parse_pdf_questions(file_path: str | Path) -> tuple[list[QuestionPreview], list[str]]:
    """
    Extrage întrebările și răspunsurile corecte dintr-un PDF cu text
    selectabil și răspunsuri marcate prin highlight.

    Suportă:
    - întrebări numerotate: 1. / 2. / 3.
    - variante cu litere: a. / b. / c.
    - variante numerotate: 1. / 2. / ... / 10.
    - highlight-uri PDF reale
    - highlight-uri desenate direct în pagină, de exemplu roșu/galben din iPad
    """
    warnings: list[str] = []
    raw_questions: list[dict] = []
    current_question: dict | None = None
    current_answer: dict | None = None

    with fitz.open(str(file_path)) as document:
        annotation_highlights = extract_annotation_highlights(document)
        drawn_highlights = extract_drawn_highlights(document)
        highlights_by_page = merge_highlights(annotation_highlights, drawn_highlights)

        for page_number, page in enumerate(document, start=1):
            lines = extract_page_lines(page, page_number)

            for line in lines:
                text = line["text"]

                if PAGE_NUMBER_PATTERN.match(text):
                    continue

                letter_answer_match = LETTER_ANSWER_PATTERN.match(text)

                if current_question is not None and letter_answer_match:
                    current_answer = add_answer_to_question(
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
                        current_question = start_new_question(
                            raw_questions=raw_questions,
                            current_question=current_question,
                            question_number=line_number,
                            question_text=line_text,
                            page_number=page_number,
                        )
                        current_answer = None
                        continue

                    has_answers = len(current_question["answers"]) > 0
                    is_possible_numeric_answer = 1 <= line_number <= MAX_NUMERIC_ANSWER_LABEL

                    if has_answers and looks_like_question_text(line_text):
                        current_question = start_new_question(
                            raw_questions=raw_questions,
                            current_question=current_question,
                            question_number=line_number,
                            question_text=line_text,
                            page_number=page_number,
                        )
                        current_answer = None
                        continue

                    if is_possible_numeric_answer:
                        current_answer = add_answer_to_question(
                            current_question=current_question,
                            label=str(line_number),
                            answer_text=line_text,
                            line=line,
                            page_number=page_number,
                        )
                        continue

                    current_question = start_new_question(
                        raw_questions=raw_questions,
                        current_question=current_question,
                        question_number=line_number,
                        question_text=line_text,
                        page_number=page_number,
                    )
                    current_answer = None
                    continue

                question_match = QUESTION_PATTERN.match(text)

                if question_match:
                    current_question = start_new_question(
                        raw_questions=raw_questions,
                        current_question=current_question,
                        question_number=int(question_match.group(1)),
                        question_text=question_match.group(2),
                        page_number=page_number,
                    )
                    current_answer = None
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
