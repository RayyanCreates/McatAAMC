"""quiz_dialog.py — Pop-out batched quiz dialog.

Uses same visual style language as dialog.py while running the quiz entirely
locally (selection, checking, reveal, score, summary).
"""

from __future__ import annotations

from typing import Callable, List, Optional

from aqt.qt import (
    QButtonGroup,
    QDialog,
    QFont,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    Qt,
    QTextBrowser,
    QVBoxLayout,
)

from .quiz_buffer import QuizQuestion


class MCATQuizDialog(QDialog):
    def __init__(self, parent=None, on_close: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent)
        self._on_close = on_close
        self._questions: List[QuizQuestion] = []
        self._index = 0
        self._score = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("MCAT Question Generator")
        self.setMinimumSize(700, 600)
        self.resize(760, 700)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(16, 14, 16, 12)

        header = QHBoxLayout()
        title = QLabel("MCAT Pop Quiz")
        f = QFont()
        f.setPointSize(15)
        f.setBold(True)
        title.setFont(f)
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(self._status)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        self._question = QTextBrowser()
        self._question.setReadOnly(True)
        self._question.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._question.setMinimumHeight(170)
        self._question.setStyleSheet(
            "QTextBrowser { background-color: #FFFFFF; border: 1px solid #DADADA;"
            " border-radius: 6px; padding: 14px; font-size: 13px; color: #1a1a1a;}"
        )
        root.addWidget(self._question)

        self._choice_group = QButtonGroup(self)
        self._choice_group.setExclusive(True)
        self._choice_buttons = {}
        for key in ["A", "B", "C", "D"]:
            rb = QRadioButton()
            rb.setStyleSheet("font-size: 13px; padding: 4px 0;")
            self._choice_group.addButton(rb)
            self._choice_buttons[key] = rb
            root.addWidget(rb)

        self._feedback = QTextBrowser()
        self._feedback.setReadOnly(True)
        self._feedback.setMinimumHeight(150)
        self._feedback.setStyleSheet(
            "QTextBrowser { background-color: #FDFEFE; border: 1px solid #DADADA;"
            " border-radius: 6px; padding: 12px; font-size: 12px; }"
        )
        root.addWidget(self._feedback)

        btns = QHBoxLayout()
        self._submit = QPushButton("Submit Answer")
        self._submit.clicked.connect(self._submit_answer)
        self._submit.setStyleSheet(_BUTTON_STYLE_PRIMARY)
        btns.addWidget(self._submit)

        self._next = QPushButton("Next Question")
        self._next.clicked.connect(self._next_question)
        self._next.setEnabled(False)
        self._next.setStyleSheet(_BUTTON_STYLE_SECONDARY)
        btns.addWidget(self._next)

        btns.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet(_BUTTON_STYLE_SECONDARY)
        btns.addWidget(close_btn)

        root.addLayout(btns)

    def load_quiz(self, questions: List[QuizQuestion]) -> None:
        self._questions = questions
        self._index = 0
        self._score = 0
        for q in self._questions:
            q.selected_key = None
            q.submitted = False
        self._render_current()

    def _render_current(self) -> None:
        if self._index >= len(self._questions):
            self._show_summary()
            return
        q = self._questions[self._index]
        self._status.setText(f"Question {self._index + 1} of {len(self._questions)}")
        self._question.setHtml(f"<b>{q.question}</b>")
        self._feedback.setHtml("<i>Select one answer and click Submit Answer.</i>")
        for k, rb in self._choice_buttons.items():
            rb.setText(f"{k}. {q.choices.get(k, '')}")
            rb.setChecked(False)
            rb.setEnabled(True)
        self._submit.setEnabled(True)
        self._next.setEnabled(False)

    def _submit_answer(self) -> None:
        if self._index >= len(self._questions):
            return
        selected = None
        for key, rb in self._choice_buttons.items():
            if rb.isChecked():
                selected = key
                break
        if selected is None:
            self._feedback.setHtml("<span style='color:#a00;'><b>Please select an answer before submitting.</b></span>")
            return

        q = self._questions[self._index]
        q.selected_key = selected
        q.submitted = True
        if q.is_correct:
            self._score += 1

        outcome = "✅ Correct" if q.is_correct else "❌ Incorrect"
        wrong_reason = q.explanations_wrong.get(selected, "") if not q.is_correct else ""
        parts = [
            f"<b>{outcome}</b>",
            f"<br><b>Correct answer:</b> {q.correct_answer}. {q.choices.get(q.correct_answer, '')}",
            f"<br><b>Explanation:</b> {q.explanation_correct}",
        ]
        if wrong_reason:
            parts.append(f"<br><b>Your choice rationale:</b> {wrong_reason}")
        if q.high_yield_takeaway:
            parts.append(f"<br><b>High-yield takeaway:</b> {q.high_yield_takeaway}")
        self._feedback.setHtml("".join(parts))

        for rb in self._choice_buttons.values():
            rb.setEnabled(False)
        self._submit.setEnabled(False)
        self._next.setEnabled(True)
        self._next.setText("Finish Quiz" if self._index == len(self._questions) - 1 else "Next Question")

    def _next_question(self) -> None:
        self._index += 1
        self._render_current()

    def _show_summary(self) -> None:
        total = len(self._questions)
        pct = (self._score / total * 100.0) if total else 0.0
        self._status.setText("Quiz complete")
        self._question.setHtml(f"<h3>Score Summary</h3><p><b>{self._score} / {total}</b> ({pct:.0f}%)</p>")
        self._feedback.setHtml("<i>Great work. Continue reviewing to trigger the next quiz batch.</i>")
        for rb in self._choice_buttons.values():
            rb.hide()
        self._submit.hide()
        self._next.hide()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._on_close:
            self._on_close()
        super().closeEvent(event)


_BUTTON_STYLE_PRIMARY = (
    "QPushButton { padding: 7px 18px; background-color: #2980b9; color: white; border: none;"
    " border-radius: 5px; font-size: 12px; font-weight: bold;}"
    "QPushButton:hover  { background-color: #2471a3; }"
    "QPushButton:pressed { background-color: #1a5276; }"
    "QPushButton:disabled { background-color: #a9cce3; color: #eaf4fb; }"
)

_BUTTON_STYLE_SECONDARY = (
    "QPushButton { padding: 7px 16px; background-color: #f4f6f7; color: #1f2d3a;"
    " border: 1px solid #d5d8dc; border-radius: 5px; font-size: 12px;}"
    "QPushButton:hover { background-color: #ebedef; }"
    "QPushButton:pressed { background-color: #d6dbdf; }"
)
