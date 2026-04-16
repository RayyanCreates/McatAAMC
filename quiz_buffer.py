"""
quiz_buffer.py — Session-only rolling buffer and quiz question utilities.

Tracks only reviewed/answered cards (from reviewer context) and keeps an
in-memory rolling buffer until quiz_interval is reached. Nothing in this module
writes to Anki data structures.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


@dataclass
class QuizQuestion:
    """Structured quiz question used by local quiz flow and UI."""

    source_id: str
    source_preview: str
    question: str
    choices: Dict[str, str]
    correct_answer: str
    explanation_correct: str
    explanations_wrong: Dict[str, str] = field(default_factory=dict)
    topic_category: str = ""
    high_yield_takeaway: str = ""

    # Local interaction state
    selected_key: Optional[str] = None
    submitted: bool = False

    @property
    def is_correct(self) -> bool:
        return self.submitted and self.selected_key == self.correct_answer


_buffer: Deque[Dict[str, Any]] = deque()


def add_reviewed_card(card_data: Dict[str, Any], quiz_interval: int = 10) -> bool:
    """Append one answered card snapshot; return True when quiz should trigger."""
    if not card_data:
        return False
    interval = max(1, int(quiz_interval or 10))
    _buffer.append(card_data)
    # Keep only last `interval` cards, so we always quiz the latest window.
    while len(_buffer) > interval:
        _buffer.popleft()
    return len(_buffer) >= interval


def get_and_reset_batch(batch_size: int = 10) -> List[Dict[str, Any]]:
    """Get latest batch_size cards and reset buffer."""
    global _buffer
    size = max(1, int(batch_size or 10))
    batch = list(_buffer)[-size:]
    _buffer.clear()
    return batch


def get_buffer_size() -> int:
    return len(_buffer)


def scramble_question_order(questions: List[QuizQuestion]) -> List[QuizQuestion]:
    shuffled = list(questions)
    random.shuffle(shuffled)
    return shuffled


def scramble_answer_choices(question: QuizQuestion) -> None:
    """Shuffle A-D locally while preserving correct-answer mapping and rationales."""
    letters = ["A", "B", "C", "D"]
    original_choices = {k: question.choices.get(k, "") for k in letters}
    original_correct_key = question.correct_answer
    original_correct_text = original_choices.get(original_correct_key, "")

    items = [(k, original_choices[k]) for k in letters]
    random.shuffle(items)

    remapped: Dict[str, str] = {}
    old_to_new: Dict[str, str] = {}
    for idx, (old_key, text) in enumerate(items):
        new_key = letters[idx]
        remapped[new_key] = text
        old_to_new[old_key] = new_key

    question.choices = remapped

    # Remap rationales keyed by choice letter.
    new_wrong: Dict[str, str] = {}
    for old_key, rationale in question.explanations_wrong.items():
        if old_key in old_to_new:
            new_wrong[old_to_new[old_key]] = rationale
    question.explanations_wrong = new_wrong

    # Recompute correct key.
    question.correct_answer = old_to_new.get(original_correct_key, question.correct_answer)
    if question.correct_answer not in question.choices:
        # Fallback by matching text if key remap failed unexpectedly.
        for key, text in question.choices.items():
            if text == original_correct_text:
                question.correct_answer = key
                break
