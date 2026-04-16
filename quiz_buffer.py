"""
quiz_buffer.py — Session-only rolling buffer of recently reviewed cards.

Tracks the last N reviewed cards in memory and triggers a pop quiz when the
batch is complete.  All state is ephemeral and session-scoped; nothing is
written to the Anki collection.

ARCHITECTURE NOTE:
  The buffer is a plain module-level list.  add_reviewed_card() is called
  from the reviewer_did_answer_card hook every time the user rates a card.
  When the list reaches quiz_interval entries, the caller receives True,
  should immediately call get_and_reset_batch(), and then start quiz generation.
  The buffer is cleared atomically so no double-triggering can occur.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# QuizQuestion — central data object shared with quiz_generator and quiz_dialog
# ---------------------------------------------------------------------------

class QuizQuestion:
    """
    One MCAT-style quiz question, generated from a source card concept.

    Attributes populated at generation time (immutable after creation):
        source_concept  short description of the card concept this came from
        stem            question text (may include a brief scenario)
        choices         {"A": text, "B": text, "C": text, "D": text}
        correct_key     which key ("A"–"D") is the right answer
        explanation     shown after submission; 2-3 sentences
        topic           inferred MCAT topic, e.g. "Psych/Soc: Identity"

    Attributes written during quiz interaction:
        selected_key    the choice the user clicked (None until selection)
        submitted       True once the user hit "Submit Answer"
    """

    __slots__ = (
        "source_concept", "stem", "choices", "correct_key",
        "explanation", "topic", "selected_key", "submitted",
    )

    def __init__(
        self,
        source_concept: str,
        stem: str,
        choices: Dict[str, str],
        correct_key: str,
        explanation: str,
        topic: str = "",
    ) -> None:
        self.source_concept: str = source_concept
        self.stem: str = stem
        self.choices: Dict[str, str] = choices
        self.correct_key: str = correct_key
        self.explanation: str = explanation
        self.topic: str = topic
        # Mutable interaction state
        self.selected_key: Optional[str] = None
        self.submitted: bool = False

    @property
    def is_correct(self) -> bool:
        """True when the user submitted the right answer."""
        return self.submitted and self.selected_key == self.correct_key


# ---------------------------------------------------------------------------
# Session buffer state  (module-level, cleared per batch)
# ---------------------------------------------------------------------------

_buffer: List[Dict[str, Any]] = []


def add_reviewed_card(card_data: Dict[str, Any], quiz_interval: int = 10) -> bool:
    """
    Append a card data snapshot to the rolling buffer.

    Returns True if the buffer has reached `quiz_interval` and a quiz should
    now be triggered.  The caller must then call get_and_reset_batch() to
    consume the batch and reset the counter atomically.

    Args:
        card_data:     read-only card dict from card_reader.get_card_data_from_card()
        quiz_interval: cards between quizzes; read from add-on config

    Returns:
        True  — buffer full; call get_and_reset_batch() now
        False — buffer not yet full; do nothing
    """
    if not card_data:
        return False
    _buffer.append(card_data)
    return len(_buffer) >= max(1, quiz_interval)


def get_and_reset_batch() -> List[Dict[str, Any]]:
    """
    Return a copy of the current buffer and reset it to empty.
    Call this immediately after add_reviewed_card() returns True.
    Thread-safety note: Anki hooks run on the main Qt thread so there
    is no concurrent access risk here.
    """
    global _buffer
    batch = list(_buffer)
    _buffer = []
    return batch


def get_buffer_size() -> int:
    """Current number of cards waiting in the buffer."""
    return len(_buffer)


# ---------------------------------------------------------------------------
# Scrambling utilities
# ---------------------------------------------------------------------------

def scramble_question_order(questions: List[QuizQuestion]) -> List[QuizQuestion]:
    """
    Return a new list with the questions in a random order.
    The input list is not mutated.
    """
    shuffled = list(questions)
    random.shuffle(shuffled)
    return shuffled


def scramble_answer_choices(question: QuizQuestion) -> None:
    """
    Shuffle the A-D choices of a single question in-place.
    Updates correct_key to reflect the new position of the correct answer
    so scoring remains accurate after scrambling.
    """
    letters = ["A", "B", "C", "D"]
    correct_text = question.choices.get(question.correct_key, "")

    # Collect, shuffle, reassign
    texts = [question.choices.get(l, "") for l in letters]
    random.shuffle(texts)
    question.choices = {l: t for l, t in zip(letters, texts)}

    # Update correct_key to point to the new position of the correct text
    for letter, text in question.choices.items():
        if text == correct_text:
            question.correct_key = letter
            return
    # Fallback: if exact match is lost (shouldn't happen), leave key unchanged
