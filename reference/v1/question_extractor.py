"""Question Extractor — detects questions from ingested chunks."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_EXERCISE_HEADINGS = re.compile(
    r"(exercise|problem|review question|worked example|practice|self[- ]?assessment|"
    r"check your understanding|try it|sample question|test yourself)",
    re.IGNORECASE,
)

_QUESTION_PATTERNS = [
    re.compile(r"\?$"),
    re.compile(r"^\d+[\.\)]\s+", re.MULTILINE),
    re.compile(r"^[a-z][\.\)]\s+", re.MULTILINE),
    re.compile(
        r"^(calculate|find|determine|solve|prove|show that|explain|describe|define|"
        r"state|list|compare|differentiate|evaluate|simplify|derive|sketch|plot|"
        r"what is|what are|why does|how does|how many|how much)\b",
        re.IGNORECASE,
    ),
]

_SOLUTION_MARKERS = re.compile(
    r"^(solution|answer|hint|worked solution|explanation)\s*[:.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class QuestionData:
    document_id: uuid.UUID
    section_node_index: int | None
    chunk_index: int | None
    question_text: str
    question_type: str
    detected_by: str = "structural"
    page_number: int | None = None
    solution_exists: bool = False
    metadata_json: dict | None = None


def extract_questions(
    chunks: list,
    nodes: list,
    document_id: uuid.UUID,
) -> list[QuestionData]:
    questions: list[QuestionData] = []

    exercise_section_indices: set[int | None] = set()
    for idx, nd in enumerate(nodes):
        if _EXERCISE_HEADINGS.search(nd.heading_text):
            exercise_section_indices.add(idx)

    def _classify_type(section_index: int | None, in_exercise: bool) -> str:
        if section_index is None:
            return "in_text"
        nd = nodes[section_index] if section_index < len(nodes) else None
        if nd and nd.heading_level == 1:
            return "end_of_chapter"
        if in_exercise:
            return "in_chapter"
        return "in_text"

    text_chunks = [
        (i, c)
        for i, c in enumerate(chunks)
        if c.block_type not in {"Figure", "Picture", "Table", "SectionHeader", "Title"}
    ]

    for chunk_pos, (chunk_idx, chunk) in enumerate(text_chunks):
        text = chunk.content.strip()
        if not text or len(text) < 10:
            continue

        is_exercise_zone = chunk.section_index in exercise_section_indices
        is_question = False

        if is_exercise_zone and any(p.search(text) for p in _QUESTION_PATTERNS[:3]):
            is_question = True

        if not is_question:
            score = sum(1 for p in _QUESTION_PATTERNS if p.search(text))
            if score >= 2 or text.rstrip().endswith("?"):
                is_question = True

        if not is_question:
            continue

        solution_exists = False
        if chunk_pos + 1 < len(text_chunks):
            next_text = text_chunks[chunk_pos + 1][1].content
            if _SOLUTION_MARKERS.search(next_text):
                solution_exists = True

        q_type = _classify_type(chunk.section_index, is_exercise_zone)
        if solution_exists:
            q_type = "end_of_chapter" if q_type == "end_of_chapter" else "in_chapter"

        questions.append(
            QuestionData(
                document_id=document_id,
                section_node_index=chunk.section_index,
                chunk_index=chunk_idx,
                question_text=text,
                question_type=q_type,
                detected_by="structural",
                page_number=chunk.page_number,
                solution_exists=solution_exists,
            )
        )

    logger.info("Extracted %d questions from %d chunks", len(questions), len(text_chunks))
    return questions
