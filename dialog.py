"""
dialog.py — Pop-out MCAT Question dialog window.

Displays the AI-generated question in a clean, scrollable, read-only window.
Provides Copy, Regenerate, and Close buttons.

Qt class imports are all sourced from aqt.qt (Anki's compatibility shim) so
they work correctly with both PyQt5 and PyQt6 environments.

This module does not interact with Anki's collection at all.
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional

from aqt.qt import (
    QApplication,
    QDialog,
    QFont,
    QFrame,
    QHBoxLayout,
    QKeySequence,
    QLabel,
    QPushButton,
    QShortcut,
    QSizePolicy,
    Qt,
    QTextBrowser,
    QTimer,
    QVBoxLayout,
)


# ---------------------------------------------------------------------------
# Main dialog class
# ---------------------------------------------------------------------------

class MCATDialog(QDialog):
    """
    Pop-out window that shows the generated MCAT question.

    Constructor args:
        parent:         Parent Qt widget (usually mw).
        on_regenerate:  Callable invoked when the user clicks "Regenerate".
    """

    def __init__(
        self,
        parent=None,
        on_regenerate: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_regenerate = on_regenerate
        self._current_plain_text: str = ""
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("MCAT Question Generator")
        self.setMinimumSize(700, 600)
        self.resize(760, 700)

        # Independent window — does not block Anki
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(16, 14, 16, 12)

        # ---- Header row ------------------------------------------------
        header_row = QHBoxLayout()
        title_lbl = QLabel("MCAT Question Generator")
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        header_row.addWidget(title_lbl)
        header_row.addStretch()
        root.addLayout(header_row)

        # ---- Status label ----------------------------------------------
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(self._status_lbl)

        # ---- Horizontal separator -------------------------------------
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # ---- Loading label (shown while generating) -------------------
        self._loading_lbl = QLabel("Generating MCAT question — please wait...")
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet(
            "color: #2980b9; font-size: 13px; padding: 50px 20px;"
        )
        root.addWidget(self._loading_lbl)

        # ---- Content browser (hidden while loading) -------------------
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setReadOnly(True)
        self._browser.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._browser.setStyleSheet(
            "QTextBrowser {"
            "  background-color: #FFFFFF;"
            "  border: 1px solid #DADADA;"
            "  border-radius: 6px;"
            "  padding: 14px;"
            "  font-size: 13px;"
            "  color: #1a1a1a;"
            "}"
        )
        self._browser.hide()
        root.addWidget(self._browser)

        # ---- Button row -----------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._copy_btn = QPushButton("Copy to Clipboard")
        self._copy_btn.setEnabled(False)
        self._copy_btn.setToolTip("Copy the generated question as plain text")
        self._copy_btn.clicked.connect(self._on_copy)
        self._copy_btn.setStyleSheet(_BUTTON_STYLE_SECONDARY)
        btn_row.addWidget(self._copy_btn)

        self._regen_btn = QPushButton("Regenerate")
        self._regen_btn.setEnabled(False)
        self._regen_btn.setToolTip("Generate a new question from the same card")
        self._regen_btn.clicked.connect(self._on_regenerate_clicked)
        self._regen_btn.setStyleSheet(_BUTTON_STYLE_PRIMARY)
        btn_row.addWidget(self._regen_btn)

        btn_row.addStretch()

        self._close_btn = QPushButton("Close")
        self._close_btn.setToolTip("Close this window  (Esc)")
        self._close_btn.clicked.connect(self.close)
        self._close_btn.setStyleSheet(_BUTTON_STYLE_SECONDARY)
        btn_row.addWidget(self._close_btn)

        root.addLayout(btn_row)

        # Esc key closes the dialog
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(self.close)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def show_loading(
        self, message: str = "Generating MCAT question — please wait..."
    ) -> None:
        """Enter loading state."""
        self._loading_lbl.setText(message)
        self._loading_lbl.show()
        self._browser.hide()
        self._copy_btn.setEnabled(False)
        self._regen_btn.setEnabled(False)
        self._status_lbl.setText("Working...")

    def show_result(
        self,
        plain_text: str,
        source_note_type: str = "",
        source_deck: str = "",
    ) -> None:
        """Display a successfully generated question."""
        self._current_plain_text = plain_text

        self._loading_lbl.hide()
        self._browser.show()
        self._browser.setHtml(_render_html(plain_text))
        # Scroll to the top of the new content
        sb = self._browser.verticalScrollBar()
        if sb is not None:
            sb.setValue(0)

        parts = [p for p in [source_note_type, source_deck] if p]
        self._status_lbl.setText(" · ".join(parts) if parts else "Ready")

        self._copy_btn.setEnabled(True)
        self._regen_btn.setEnabled(True)

    def show_error(self, message: str) -> None:
        """Display an error, keeping Regenerate available."""
        self._current_plain_text = ""

        self._loading_lbl.hide()
        self._browser.show()
        self._browser.setHtml(_render_error_html(message))
        sb = self._browser.verticalScrollBar()
        if sb is not None:
            sb.setValue(0)

        self._status_lbl.setText("Error")
        self._copy_btn.setEnabled(False)
        self._regen_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_copy(self) -> None:
        if not self._current_plain_text:
            return
        QApplication.clipboard().setText(self._current_plain_text)
        self._copy_btn.setText("Copied!")
        self._copy_btn.setEnabled(False)

        # Use a named closure to avoid lambda GC issues in PyQt6
        copy_btn = self._copy_btn  # local ref so the closure doesn't capture self

        def _restore() -> None:
            copy_btn.setText("Copy to Clipboard")
            copy_btn.setEnabled(True)

        QTimer.singleShot(2000, _restore)

    def _on_regenerate_clicked(self) -> None:
        if self._on_regenerate is not None:
            self.show_loading()
            self._on_regenerate()


# ---------------------------------------------------------------------------
# Button styles
# ---------------------------------------------------------------------------

_BUTTON_STYLE_PRIMARY = (
    "QPushButton {"
    "  padding: 7px 18px;"
    "  background-color: #2980b9;"
    "  color: white;"
    "  border: none;"
    "  border-radius: 5px;"
    "  font-size: 12px;"
    "  font-weight: bold;"
    "}"
    "QPushButton:hover  { background-color: #2471a3; }"
    "QPushButton:pressed { background-color: #1a5276; }"
    "QPushButton:disabled { background-color: #a9cce3; color: #eaf4fb; }"
)

_BUTTON_STYLE_SECONDARY = (
    "QPushButton {"
    "  padding: 7px 18px;"
    "  background-color: #f0f0f0;"
    "  color: #222;"
    "  border: 1px solid #ccc;"
    "  border-radius: 5px;"
    "  font-size: 12px;"
    "}"
    "QPushButton:hover  { background-color: #e0e0e0; }"
    "QPushButton:pressed { background-color: #d0d0d0; }"
    "QPushButton:disabled { color: #aaa; }"
)


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _render_html(text: str) -> str:
    """
    Convert the plain-text AI output to styled HTML for QTextBrowser.

    The renderer walks lines, matches known section headers, and applies
    appropriate styling.  Unrecognised lines fall through to a plain
    paragraph so the output degrades gracefully if the AI varies its format.
    """
    lines: List[str] = [ln.rstrip() for ln in text.split("\n")]
    out: List[str] = []

    out.append(
        '<div style="font-family: -apple-system, \'Segoe UI\', Arial, sans-serif;'
        ' font-size: 13px; line-height: 1.65; color: #1a1a1a; padding: 2px 4px;">'
    )

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # ------ Based on Current Card -----------------------------------
        if stripped.startswith("Based on Current Card:"):
            content = stripped[len("Based on Current Card:"):].strip()
            i += 1
            i, extra = _collect_continuation(lines, i)
            if extra:
                content = (content + " " + extra).strip()
            out.append(
                '<div style="background:#eaf4fb;border-left:4px solid #2980b9;'
                'padding:8px 12px;margin:6px 0 10px 0;border-radius:0 4px 4px 0;">'
                '<span style="font-weight:bold;color:#1a6a9a;">Based on Current Card</span>'
                f'<br><span style="color:#2c3e50;">{_esc(content)}</span></div>'
            )
            continue

        # ------ Question -----------------------------------------------
        if stripped.startswith("Question:"):
            content = stripped[len("Question:"):].strip()
            i += 1
            while i < len(lines):
                s = lines[i].strip()
                if not s:
                    i += 1
                    continue
                if _is_answer_choice(s) or _is_known_header(s):
                    break
                content = (content + " " + s).strip() if content else s
                i += 1
            out.append(
                '<div style="margin:12px 0 8px 0;">'
                '<span style="font-weight:bold;font-size:14px;color:#1a3a5c;">Question</span>'
                f'<p style="margin:6px 0 0 0;color:#111;">{_esc(content)}</p></div>'
            )
            continue

        # ------ Answer choices A-D -------------------------------------
        if _is_answer_choice(stripped):
            out.append(
                '<div style="margin:8px 0;background:#f7f9fc;'
                'border:1px solid #dce3ec;border-radius:6px;padding:10px 14px;">'
            )
            while i < len(lines):
                s = lines[i].strip()
                if not s:
                    i += 1
                    continue
                if not _is_answer_choice(s):
                    break
                letter = s[0]
                choice_text = s[2:].strip()
                i += 1
                # Absorb continuation lines for this choice
                while i < len(lines):
                    nxt = lines[i].strip()
                    if not nxt:
                        i += 1
                        break
                    if _is_answer_choice(nxt) or _is_known_header(nxt):
                        break
                    choice_text = choice_text + " " + nxt
                    i += 1
                out.append(
                    f'<div style="margin:3px 0;">'
                    f'<span style="font-weight:bold;color:#2980b9;">{letter}.</span>'
                    f" {_esc(choice_text)}</div>"
                )
            out.append("</div>")
            continue

        # ------ Correct Answer -----------------------------------------
        if stripped.startswith("Correct Answer:"):
            answer = stripped[len("Correct Answer:"):].strip()
            i += 1
            out.append(
                '<div style="margin:10px 0;padding:8px 12px;'
                'background:#eafaf1;border-left:4px solid #27ae60;'
                'border-radius:0 4px 4px 0;">'
                '<span style="font-weight:bold;color:#1e8449;">'
                f"Correct Answer: {_esc(answer)}</span></div>"
            )
            continue

        # ------ Why the Correct Answer Is Right -------------------------
        if stripped.startswith("Why the Correct Answer Is Right:"):
            content = stripped[len("Why the Correct Answer Is Right:"):].strip()
            i += 1
            i, extra = _collect_continuation(lines, i)
            if extra:
                content = (content + " " + extra).strip()
            out.append(
                '<div style="margin:10px 0;">'
                '<span style="font-weight:bold;color:#1e8449;">'
                "Why the Correct Answer Is Right</span>"
                f'<p style="margin:5px 0 0 0;color:#2c3e50;">{_esc(content)}</p></div>'
            )
            continue

        # ------ Why the Other Answers Are Wrong -------------------------
        if stripped.startswith("Why the Other Answers Are Wrong:"):
            i += 1
            wrong_lines: List[str] = []
            while i < len(lines):
                s = lines[i].strip()
                if not s:
                    i += 1
                    continue
                if _is_known_header(s):
                    break
                wrong_lines.append(s)
                i += 1
            inner = "".join(
                f'<div style="margin:2px 0 4px 0;color:#555;">{_esc(wl)}</div>'
                for wl in wrong_lines
            )
            out.append(
                '<div style="margin:10px 0;">'
                '<span style="font-weight:bold;color:#c0392b;">'
                "Why the Other Answers Are Wrong</span>"
                f'<div style="margin:5px 0 0 8px;">{inner}</div></div>'
            )
            continue

        # ------ MCAT Topic / Category ----------------------------------
        if stripped.startswith("MCAT Topic / Category:"):
            content = stripped[len("MCAT Topic / Category:"):].strip()
            i += 1
            i, extra = _collect_continuation(lines, i)
            if extra:
                content = (content + " " + extra).strip()
            out.append(
                '<div style="margin:10px 0;padding:7px 12px;'
                'background:#fef9e7;border:1px solid #f9e79f;border-radius:4px;">'
                '<span style="font-weight:bold;color:#7d6608;">'
                "MCAT Topic / Category:&nbsp;</span>"
                f'<span style="color:#555;">{_esc(content)}</span></div>'
            )
            continue

        # ------ High-Yield Takeaway ------------------------------------
        if stripped.startswith("High-Yield Takeaway:"):
            content = stripped[len("High-Yield Takeaway:"):].strip()
            i += 1
            i, extra = _collect_continuation(lines, i)
            if extra:
                content = (content + " " + extra).strip()
            out.append(
                '<div style="margin:10px 0;padding:8px 12px;'
                'background:#f5eef8;border-left:4px solid #8e44ad;'
                'border-radius:0 4px 4px 0;">'
                '<span style="font-weight:bold;color:#6c3483;">High-Yield Takeaway</span>'
                f'<p style="margin:5px 0 0 0;color:#2c3e50;">{_esc(content)}</p></div>'
            )
            continue

        # ------ Common Trap --------------------------------------------
        if stripped.startswith("Common Trap:"):
            content = stripped[len("Common Trap:"):].strip()
            i += 1
            i, extra = _collect_continuation(lines, i)
            if extra:
                content = (content + " " + extra).strip()
            out.append(
                '<div style="margin:10px 0;padding:8px 12px;'
                'background:#fdedec;border-left:4px solid #e74c3c;'
                'border-radius:0 4px 4px 0;">'
                '<span style="font-weight:bold;color:#c0392b;">Common Trap</span>'
                f'<p style="margin:5px 0 0 0;color:#2c3e50;">{_esc(content)}</p></div>'
            )
            continue

        # ------ Fallback: generic paragraph ----------------------------
        out.append(f'<p style="margin:4px 0;color:#333;">{_esc(stripped)}</p>')
        i += 1

    out.append("</div>")
    return "\n".join(out)


def _render_error_html(message: str) -> str:
    """Render an error-state HTML block."""
    safe_msg = _esc(message).replace("\n", "<br>")
    return (
        '<div style="font-family:-apple-system,\'Segoe UI\',Arial,sans-serif;'
        'padding:24px 20px;color:#1a1a1a;">'
        '<p style="font-weight:bold;font-size:14px;color:#c0392b;">Generation Error</p>'
        f'<p style="font-size:13px;color:#444;line-height:1.6;">{safe_msg}</p>'
        '<hr style="border:none;border-top:1px solid #eee;margin:16px 0;">'
        '<p style="font-size:11px;color:#888;">'
        "Click <b>Regenerate</b> to try again, or check the add-on config "
        "(Tools &rarr; Add-ons &rarr; MCAT Question Generator &rarr; Config)."
        "</p></div>"
    )


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

_KNOWN_HEADERS: List[str] = [
    "Based on Current Card:",
    "Question:",
    "Correct Answer:",
    "Why the Correct Answer Is Right:",
    "Why the Other Answers Are Wrong:",
    "MCAT Topic / Category:",
    "High-Yield Takeaway:",
    "Common Trap:",
]

_ANSWER_RE = re.compile(r"^[A-D]\.\s")


def _is_known_header(line: str) -> bool:
    return any(line.startswith(h) for h in _KNOWN_HEADERS)


def _is_answer_choice(line: str) -> bool:
    return bool(_ANSWER_RE.match(line))


def _collect_continuation(lines: List[str], start: int):  # noqa: ANN202
    """
    Collect non-header, non-empty lines starting at `start`.
    Returns (new_index, joined_text).
    One blank line terminates the continuation.
    """
    parts: List[str] = []
    i = start
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            break  # blank line ends continuation
        if _is_known_header(s) or _is_answer_choice(s):
            break
        parts.append(s)
        i += 1
    return i, " ".join(parts)


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
