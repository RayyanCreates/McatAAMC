"""
reviewer_hooks.py — Anki reviewer integration for the MCAT Question Generator.

Responsibilities:
  1. Inject a floating "MCAT Q" button into the reviewer web view on each card.
  2. Listen for pycmd('mcat_generate') messages from that button.
  3. Provide trigger_generation() — called by the button, the hotkey, and the menu.
  4. Manage the lifecycle of the MCATDialog (singleton per session).

KEY DESIGN DECISIONS FOR COMPATIBILITY:
  - No module-level aqt imports other than `import aqt` for the mw reference.
    All Qt class imports are deferred to inside the functions that need them
    so that a single missing class never kills the entire module load.
  - Every hook registration is individually try/except'd so one failure does
    not silence the others.
  - `aqt.mw` is accessed as an attribute at call time (not captured at import
    time) so we always get the live main-window object.

SAFETY:
  This module only reads card data (via card_reader) and displays a dialog.
  It never writes to notes, cards, scheduling, or the collection.
"""

from __future__ import annotations

import sys
import traceback
from typing import Optional

# `import aqt` is safe at module level — aqt is always present inside Anki.
# We access `aqt.mw` at call time (not import time) to get the live object.
import aqt

from .card_reader import get_current_card_data
from .config_manager import load_config
from .dialog import MCATDialog
from .generator import generate_mcat_question
from .logger_util import get_logger
from .prompt_builder import build_prompt

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Singleton dialog — reused across generations within one session
_dialog: Optional[MCATDialog] = None

# Add-on package name, set by setup() from __init__.py
_addon_package: str = ""


# ---------------------------------------------------------------------------
# Public setup entry point — called from __init__._on_profile_open
# ---------------------------------------------------------------------------

def setup(addon_package: str) -> None:
    """
    Register all reviewer hooks, keyboard shortcuts, and menu items.
    Must be called once after Anki's profile is open and mw is ready.

    Each registration is individually guarded so one failure does not
    prevent the others from working.
    """
    global _addon_package
    _addon_package = addon_package
    logger = get_logger()

    # ---- Hook: inject button on each new question ----------------------
    try:
        from aqt import gui_hooks
        gui_hooks.reviewer_did_show_question.append(_on_reviewer_show_question)
        logger.info("reviewer_did_show_question hook registered")
    except Exception:
        logger.error(f"Could not register reviewer_did_show_question:\n"
                     f"{traceback.format_exc()}")

    # ---- Hook: handle pycmd() messages from the reviewer webview -------
    try:
        from aqt import gui_hooks
        gui_hooks.webview_did_receive_js_message.append(_on_webview_message)
        logger.info("webview_did_receive_js_message hook registered")
    except Exception:
        logger.error(f"Could not register webview_did_receive_js_message:\n"
                     f"{traceback.format_exc()}")

    # ---- Keyboard shortcut ---------------------------------------------
    try:
        _setup_shortcut()
    except Exception:
        logger.error(f"Could not set up shortcut:\n{traceback.format_exc()}")

    # ---- Tools menu item -----------------------------------------------
    try:
        _setup_menu()
    except Exception:
        logger.error(f"Could not set up menu:\n{traceback.format_exc()}")

    logger.info("setup() complete")


# ---------------------------------------------------------------------------
# Reviewer hooks
# ---------------------------------------------------------------------------

def _on_reviewer_show_question(card) -> None:  # noqa: ANN001
    """
    Called by Anki each time a new question is displayed.
    Injects a floating 'MCAT Q' button into the reviewer web view.
    """
    try:
        config = _load_config_safe()
        if not config.get("show_button_in_reviewer", True):
            return
        label = config.get("button_label", "MCAT Q")
        _inject_reviewer_button(label)
    except Exception:
        get_logger().error(
            f"_on_reviewer_show_question error:\n{traceback.format_exc()}"
        )


def _on_webview_message(handled, message: str, context) -> tuple:  # noqa: ANN001
    """
    Called whenever JavaScript in a reviewer WebView calls pycmd().
    We intercept 'mcat_generate'; everything else is passed through unchanged.
    """
    if message == "mcat_generate":
        try:
            trigger_generation()
        except Exception:
            get_logger().error(
                f"_on_webview_message: trigger_generation failed:\n"
                f"{traceback.format_exc()}"
            )
        return (True, None)
    return handled


# ---------------------------------------------------------------------------
# Generation trigger — called by button, hotkey, and menu
# ---------------------------------------------------------------------------

def trigger_generation() -> None:
    """
    Main entry point: read the current card, build the prompt, show the dialog,
    and kick off background AI generation.

    Fails safely with a dialog message if not in review state.
    """
    logger = get_logger()
    mw = aqt.mw  # always get the live reference

    # ------------------------------------------------------------------
    # 1. Verify we are in an active review session
    # ------------------------------------------------------------------
    if mw is None or mw.reviewer is None or mw.reviewer.card is None:
        _show_not_reviewing_error()
        return

    # ------------------------------------------------------------------
    # 2. Read the current card (strictly read-only)
    # ------------------------------------------------------------------
    card_data = get_current_card_data()
    if card_data is None:
        _show_card_read_error()
        return

    # ------------------------------------------------------------------
    # 3. Get or create the dialog
    # ------------------------------------------------------------------
    dialog = _get_or_create_dialog()
    dialog.show_loading()
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()

    # ------------------------------------------------------------------
    # 4. Build the prompt (pure data transformation, no collection writes)
    # ------------------------------------------------------------------
    try:
        config = _load_config_safe()
        user_message = build_prompt(card_data, config)
    except ValueError as exc:
        logger.warning(f"build_prompt failed: {exc}")
        dialog.show_error(
            f"Could not extract useful content from this card:\n\n{exc}\n\n"
            "The card fields may be empty or contain only formatting."
        )
        return
    except Exception as exc:
        logger.error(f"Unexpected error building prompt:\n{traceback.format_exc()}")
        dialog.show_error(f"Error preparing the question prompt:\n\n{exc}")
        return

    note_type = card_data.get("note_type_name", "")
    deck = card_data.get("deck_name", "")

    # ------------------------------------------------------------------
    # 5. Start background AI generation
    # ------------------------------------------------------------------
    def on_result(text: str) -> None:
        dialog.show_result(text, source_note_type=note_type, source_deck=deck)

    def on_error(message: str) -> None:
        dialog.show_error(message)

    generate_mcat_question(user_message, config, on_result, on_error)


# ---------------------------------------------------------------------------
# Dialog lifecycle
# ---------------------------------------------------------------------------

def _get_or_create_dialog() -> MCATDialog:
    """Return the existing visible dialog, or create a fresh one."""
    global _dialog
    mw = aqt.mw

    if _dialog is not None and _dialog.isVisible():
        return _dialog

    _dialog = MCATDialog(parent=mw, on_regenerate=_on_regenerate)
    return _dialog


def _on_regenerate() -> None:
    """Invoked when the user clicks Regenerate inside the dialog."""
    trigger_generation()


# ---------------------------------------------------------------------------
# Floating button injection via JavaScript
# ---------------------------------------------------------------------------

def _inject_reviewer_button(label: str) -> None:
    """
    Inject a fixed-position button into the reviewer's web view.
    The button calls pycmd('mcat_generate') when clicked.
    A unique id prevents double-injection across card flips.
    """
    mw = aqt.mw
    # Sanitise the label for embedding in a JS string literal
    safe_label = (
        label
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "")
        .replace("\r", "")
    )

    js = f"""
    (function() {{
        var old = document.getElementById('mcat-qgen-btn');
        if (old) {{ old.remove(); }}

        var btn = document.createElement('button');
        btn.id = 'mcat-qgen-btn';
        btn.textContent = '{safe_label}';
        btn.title = 'Generate an MCAT-style question from this card (Ctrl+M)';
        btn.setAttribute('aria-label', 'Generate MCAT Question');

        var styles = [
            'position: fixed',
            'bottom: 22px',
            'right: 22px',
            'z-index: 99999',
            'padding: 7px 15px',
            'background: #2980b9',
            'color: #fff',
            'border: none',
            'border-radius: 6px',
            'cursor: pointer',
            'font-size: 12px',
            'font-weight: bold',
            'font-family: -apple-system, \\"Segoe UI\\", Arial, sans-serif',
            'box-shadow: 0 2px 8px rgba(0,0,0,0.25)',
            'opacity: 0.92',
            'letter-spacing: 0.3px',
            'transition: opacity 0.15s ease'
        ];
        btn.style.cssText = styles.join('; ');

        btn.addEventListener('mouseenter', function() {{ btn.style.opacity = '1'; }});
        btn.addEventListener('mouseleave', function() {{ btn.style.opacity = '0.92'; }});
        btn.addEventListener('click', function(e) {{
            e.preventDefault();
            e.stopPropagation();
            pycmd('mcat_generate');
        }});

        document.body.appendChild(btn);
    }})();
    """

    try:
        if mw and mw.reviewer and hasattr(mw.reviewer, "web"):
            mw.reviewer.web.eval(js)
    except Exception:
        get_logger().warning(
            f"_inject_reviewer_button: JS eval failed:\n{traceback.format_exc()}"
        )


# ---------------------------------------------------------------------------
# Keyboard shortcut
# ---------------------------------------------------------------------------

def _setup_shortcut() -> None:
    """Register the configurable keyboard shortcut on the main window."""
    from aqt.qt import QKeySequence, QShortcut  # deferred import

    mw = aqt.mw
    config = _load_config_safe()
    hotkey = str(config.get("hotkey", "Ctrl+M")).strip()
    if not hotkey:
        return

    shortcut = QShortcut(QKeySequence(hotkey), mw)
    shortcut.activated.connect(trigger_generation)
    get_logger().info(f"Hotkey registered: {hotkey!r}")


# ---------------------------------------------------------------------------
# Tools menu item
# ---------------------------------------------------------------------------

def _setup_menu() -> None:
    """Add 'Generate MCAT Question' to Anki's Tools menu."""
    from aqt.qt import QAction  # deferred import

    mw = aqt.mw
    if mw is None:
        return

    action = QAction("Generate MCAT Question", mw)
    action.setStatusTip(
        "Generate a high-quality MCAT-style question from the current review card"
    )
    action.triggered.connect(trigger_generation)

    # mw.form.menuTools is the standard Tools menu in all modern Anki versions
    try:
        mw.form.menuTools.addAction(action)
        get_logger().info("Tools menu item added")
    except AttributeError:
        # Fallback: add to the menubar directly if menuTools is missing
        try:
            mw.menuBar().addAction(action)
            get_logger().warning(
                "mw.form.menuTools not found; action added directly to menubar"
            )
        except Exception:
            get_logger().error(
                f"Could not add menu action:\n{traceback.format_exc()}"
            )


# ---------------------------------------------------------------------------
# Error dialogs — use aqt.utils helpers; fall back to print on failure
# ---------------------------------------------------------------------------

def _show_not_reviewing_error() -> None:
    try:
        from aqt.utils import showInfo
        showInfo(
            "No card is currently being reviewed.\n\n"
            "Start a review session and trigger the generator while a card "
            "is on screen.",
            title="MCAT Question Generator",
        )
    except Exception:
        print("[MCAT QGen] Not in review session.", file=sys.stderr)


def _show_card_read_error() -> None:
    try:
        from aqt.utils import showWarning
        showWarning(
            "Could not read the current card's data.\n\n"
            "This should not happen during a normal review session. "
            "Check  ~/.mcat_qgen.log  for details.\n\n"
            "No data was modified.",
            title="MCAT Question Generator — Card Read Error",
        )
    except Exception:
        print("[MCAT QGen] Card read error.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

def _load_config_safe() -> dict:
    """Load config, falling back to defaults on any error."""
    try:
        return load_config(_addon_package)
    except Exception:
        get_logger().error(f"_load_config_safe failed:\n{traceback.format_exc()}")
        from .config_manager import _DEFAULTS
        return dict(_DEFAULTS)
