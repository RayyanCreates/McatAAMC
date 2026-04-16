"""reviewer_hooks.py — Reviewer integration and delayed batched pop-quiz flow."""

from __future__ import annotations

import sys
import traceback
from typing import List, Optional

import aqt

from .card_reader import get_card_data_from_card, get_current_card_data
from .config_manager import load_config
from .dialog import MCATDialog
from .generator import generate_mcat_question
from .logger_util import get_logger
from .prompt_builder import build_prompt
from .quiz_buffer import (
    QuizQuestion,
    add_reviewed_card,
    get_and_reset_batch,
    scramble_answer_choices,
    scramble_question_order,
)
from .quiz_cache import find_cached_questions, update_cache
from .quiz_dialog import MCATQuizDialog
from .quiz_generator import generate_quiz

_dialog: Optional[MCATDialog] = None
_quiz_dialog: Optional[MCATQuizDialog] = None
_addon_package: str = ""
_quiz_in_flight: bool = False

# Batched-quiz state (session-only)
_quiz_in_flight: bool = False
_quiz_ready: bool = False
_quiz_pending: bool = False
_quiz_prompt_shown: bool = False
_prepared_quiz_questions: List[QuizQuestion] = []

def setup(addon_package: str) -> None:
    global _addon_package
    _addon_package = addon_package
    logger = get_logger()

    try:
        from aqt import gui_hooks
        gui_hooks.reviewer_did_show_question.append(_on_reviewer_show_question)
        logger.info("reviewer_did_show_question hook registered")
    except Exception:
        logger.error(f"Could not register reviewer_did_show_question:\n{traceback.format_exc()}")

    try:
        from aqt import gui_hooks
        gui_hooks.webview_did_receive_js_message.append(_on_webview_message)
        logger.info("webview_did_receive_js_message hook registered")
    except Exception:
        logger.error(f"Could not register webview_did_receive_js_message:\n{traceback.format_exc()}")

    try:
        from aqt import gui_hooks
        gui_hooks.reviewer_did_answer_card.append(_on_reviewer_answer_card)
        logger.info("reviewer_did_answer_card hook registered")
    except Exception:
        logger.error(f"Could not register reviewer_did_answer_card:\n{traceback.format_exc()}")

    try:
        _setup_shortcut()
    except Exception:
        logger.error(f"Could not set up shortcut:\n{traceback.format_exc()}")

    try:
        _setup_menu()
    except Exception:
        logger.error(f"Could not set up menu:\n{traceback.format_exc()}")


def _on_reviewer_show_question(card) -> None:  # noqa: ANN001
    try:
        config = _load_config_safe()
        if not config.get("show_button_in_reviewer", True):
            return
        _inject_reviewer_button(config.get("button_label", "MCAT Q"))
    except Exception:
        get_logger().error(f"_on_reviewer_show_question error:\n{traceback.format_exc()}")


def _on_webview_message(handled, message: str, context) -> tuple:  # noqa: ANN001
    if message == "mcat_generate":
        trigger_generation()
        return (True, None)
    return handled


def _on_reviewer_answer_card(reviewer, card, ease) -> None:  # noqa: ANN001
    """Count only answered cards; trigger one batched quiz at interval."""
    global _quiz_in_flight
    try:
        if _quiz_in_flight:
            return
        config = _load_config_safe()
        quiz_interval = int(config.get("quiz_interval_count", 10))
        quiz_size = int(config.get("quiz_size", 10))

        card_data = get_card_data_from_card(card)
        if card_data is None:
            return
        should_trigger = add_reviewed_card(card_data, quiz_interval=quiz_interval)
        if not should_trigger:
            return

        batch = get_and_reset_batch(batch_size=quiz_size)
        if not batch:
            return

        _quiz_in_flight = True
        _start_batched_quiz(batch, config)
    except Exception:
        _quiz_in_flight = False
        get_logger().error(f"_on_reviewer_answer_card error:\n{traceback.format_exc()}")


def _start_batched_quiz(batch: List[dict], config: dict) -> None:
    """Cache-first, single API call for misses, local quiz flow thereafter."""
    global _quiz_in_flight
    sources = [_card_to_source(c) for c in batch]
    cache_enabled = bool(config.get("cache_enabled", True))
    cached_map, misses = find_cached_questions(sources, enabled=cache_enabled)

    if not misses:
        questions = [cached_map[s["source_id"]] for s in sources if s["source_id"] in cached_map]
        _show_quiz_questions(questions, config)
        _quiz_in_flight = False
        return

    def on_result(generated_questions: List[QuizQuestion]) -> None:
        try:
            update_cache(generated_questions, enabled=cache_enabled)
            generated_map = {q.source_id: q for q in generated_questions}
            merged: List[QuizQuestion] = []
            for src in sources:
                sid = src["source_id"]
                if sid in cached_map:
                    merged.append(cached_map[sid])
                elif sid in generated_map:
                    merged.append(generated_map[sid])
            _show_quiz_questions(merged, config)
        finally:
            _quiz_in_flight = False

    def on_error(message: str) -> None:
        global _quiz_in_flight
        _quiz_in_flight = False
        try:
            from aqt.utils import showWarning
            showWarning(f"Quiz generation failed:\n\n{message}", title="MCAT Pop Quiz")
        except Exception:
            print(f"[MCAT QGen] Quiz generation failed: {message}", file=sys.stderr)

    generate_quiz(misses, config, on_result, on_error)


def _card_to_source(card_data: dict) -> dict:
    card_id = str(card_data.get("card_id", ""))
    note_type = str(card_data.get("note_type_name", ""))
    deck = str(card_data.get("deck_name", ""))
    fields = card_data.get("fields", {})
    field_preview = " | ".join(
        f"{k}: {v.get('text', '')}" for k, v in fields.items() if v.get("text")
    )
    preview = (field_preview[:350] + "…") if len(field_preview) > 350 else field_preview
    return {
        "source_id": card_id,
        "source_preview": preview,
        "topic_category": note_type or deck,
    }


def _show_quiz_questions(questions: List[QuizQuestion], config: dict) -> None:
    global _quiz_dialog
    if not questions:
        return
    if bool(config.get("scramble_answer_choices", True)):
        for q in questions:
            scramble_answer_choices(q)
    if bool(config.get("scramble_question_order", True)):
        questions = scramble_question_order(questions)

    mw = aqt.mw
    if _quiz_dialog is None or not _quiz_dialog.isVisible():
        _quiz_dialog = MCATQuizDialog(parent=mw)
    _quiz_dialog.load_quiz(questions)
    _quiz_dialog.show()
    _quiz_dialog.raise_()
    _quiz_dialog.activateWindow()


def trigger_generation() -> None:
    logger = get_logger()
    mw = aqt.mw
    if mw is None or mw.reviewer is None or mw.reviewer.card is None:
        _show_not_reviewing_error()
        return

    card_data = get_current_card_data()
    if card_data is None:
        _show_card_read_error()
        return

    dialog = _get_or_create_dialog()
    dialog.show_loading()
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()

    try:
        config = _load_config_safe()
        user_message = build_prompt(card_data, config)
    except ValueError as exc:
        logger.warning(f"build_prompt failed: {exc}")
        dialog.show_error(f"Could not extract useful content from this card:\n\n{exc}")
        return
    except Exception as exc:
        logger.error(f"Unexpected error building prompt:\n{traceback.format_exc()}")
        dialog.show_error(f"Error preparing the question prompt:\n\n{exc}")
        return

    note_type = card_data.get("note_type_name", "")
    deck = card_data.get("deck_name", "")

    def on_result(text: str) -> None:
        dialog.show_result(text, source_note_type=note_type, source_deck=deck)

    def on_error(message: str) -> None:
        dialog.show_error(message)

    generate_mcat_question(user_message, config, on_result, on_error)


def _get_or_create_dialog() -> MCATDialog:
    global _dialog
    mw = aqt.mw
    if _dialog is not None and _dialog.isVisible():
        return _dialog
    _dialog = MCATDialog(parent=mw, on_regenerate=_on_regenerate)
    return _dialog


def _on_regenerate() -> None:
    trigger_generation()


def _inject_reviewer_button(label: str) -> None:
    mw = aqt.mw
    safe_label = label.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", "").replace("\r", "")
    js = f"""
    (function() {{
        var old = document.getElementById('mcat-qgen-btn');
        if (old) {{ old.remove(); }}
        var btn = document.createElement('button');
        btn.id = 'mcat-qgen-btn';
        btn.textContent = '{safe_label}';
        btn.title = 'Generate an MCAT-style question from this card (Ctrl+M)';
        var styles = [
            'position: fixed','bottom: 22px','right: 22px','z-index: 99999','padding: 7px 15px',
            'background: #2980b9','color: #fff','border: none','border-radius: 6px','cursor: pointer',
            'font-size: 12px','font-weight: bold','font-family: -apple-system, "Segoe UI", Arial, sans-serif',
            'box-shadow: 0 2px 8px rgba(0,0,0,0.25)','opacity: 0.92','letter-spacing: 0.3px',
            'transition: opacity 0.15s ease'
        ];
        btn.style.cssText = styles.join('; ');
        btn.addEventListener('mouseenter', function() {{ btn.style.opacity = '1'; }});
        btn.addEventListener('mouseleave', function() {{ btn.style.opacity = '0.92'; }});
        btn.addEventListener('click', function(e) {{ e.preventDefault(); e.stopPropagation(); pycmd('mcat_generate'); }});
        document.body.appendChild(btn);

        var startBtn = document.createElement('button');
        startBtn.id = 'mcat-start-quiz-btn';
        startBtn.textContent = 'Start Quiz';
        startBtn.title = 'Start pending MCAT pop quiz';
        var s = [
            'display: {start_quiz_display}','position: fixed','bottom: 60px','right: 22px','z-index: 99999',
            'padding: 6px 13px','background: #16a085','color: #fff','border: none','border-radius: 6px',
            'cursor: pointer','font-size: 12px','font-weight: bold',
            'font-family: -apple-system, "Segoe UI", Arial, sans-serif','box-shadow: 0 2px 8px rgba(0,0,0,0.25)','opacity: 0.92'
        ];
        startBtn.style.cssText = s.join('; ');
        startBtn.addEventListener('click', function(e) {{ e.preventDefault(); e.stopPropagation(); pycmd('mcat_start_quiz'); }});
        document.body.appendChild(startBtn);
    }})();
    """
    try:
        if mw and mw.reviewer and hasattr(mw.reviewer, "web"):
            mw.reviewer.web.eval(js)
    except Exception:
        get_logger().warning(f"_inject_reviewer_button: JS eval failed:\n{traceback.format_exc()}")


def _setup_shortcut() -> None:
    from aqt.qt import QKeySequence, QShortcut
    mw = aqt.mw
    config = _load_config_safe()
    hotkey = str(config.get("hotkey", "Ctrl+M")).strip()
    if not hotkey:
        return
    shortcut = QShortcut(QKeySequence(hotkey), mw)
    shortcut.activated.connect(trigger_generation)


def _setup_menu() -> None:
    from aqt.qt import QAction
    mw = aqt.mw
    if mw is None:
        return
    action = QAction("Generate MCAT Question", mw)
    action.triggered.connect(trigger_generation)
    try:
        mw.form.menuTools.addAction(action)
    except AttributeError:
        mw.menuBar().addAction(action)


def _show_not_reviewing_error() -> None:
    try:
        from aqt.utils import showInfo
        showInfo("No card is currently being reviewed.", title="MCAT Question Generator")
    except Exception:
        print("[MCAT QGen] Not in review session.", file=sys.stderr)


def _show_card_read_error() -> None:
    try:
        from aqt.utils import showWarning
        showWarning("Could not read the current card's data. No data was modified.", title="MCAT Question Generator — Card Read Error")
    except Exception:
        print("[MCAT QGen] Card read error.", file=sys.stderr)


def _load_config_safe() -> dict:
    try:
        return load_config(_addon_package)
    except Exception:
        get_logger().error(f"_load_config_safe failed:\n{traceback.format_exc()}")
        from .config_manager import _DEFAULTS

        return dict(_DEFAULTS)
