"""
MCAT Question Generator — Anki Add-on
======================================
Generates high-quality, MCAT-style practice questions from the card you are
currently reviewing, displayed in a separate pop-out window.

SAFETY GUARANTEES:
  - Strictly read-only with respect to your Anki collection.
  - Does not modify notes, fields, tags, scheduling, ease, due dates,
    intervals, media, or deck structure.
  - Does not auto-save generated content into Anki.
  - The only external write is the HTTPS API request (to Anthropic or OpenAI).

SETUP:
  1. Copy this folder into your Anki addons21 directory as  mcat_question_generator
     (no spaces — the folder name must be a valid Python identifier).
  2. Set your API key:  Tools → Add-ons → MCAT Question Generator → Config
     Set "api_key" to your Anthropic or OpenAI key.
  3. Restart Anki.
  4. During review: click the "MCAT Q" button (bottom-right) or press Ctrl+M.

Version: 1.0.0
"""

from __future__ import annotations

import sys
import traceback

# ---------------------------------------------------------------------------
# Step 1: Logging — wrapped in its own try/except so a broken logger never
#         prevents the rest of the add-on from loading.
# ---------------------------------------------------------------------------
try:
    from .logger_util import setup_logging, get_logger
    setup_logging()
    _log = get_logger()
except Exception:  # pragma: no cover
    # Absolute last resort: a plain stdlib logger
    import logging
    _log = logging.getLogger("mcat_question_generator")
    _log.addHandler(logging.StreamHandler(sys.stderr))

_log.info("MCAT Question Generator: __init__.py loading")


# ---------------------------------------------------------------------------
# Step 2: Profile-open callback — ALL Anki-dependent work is deferred here.
#
# At module-import time Anki has no profile open yet, so mw.col is None and
# creating Qt widgets would crash.  gui_hooks.profile_did_open fires after
# the user has selected a profile and everything is fully ready.
# ---------------------------------------------------------------------------

def _on_profile_open() -> None:
    """
    Called once per session after the Anki profile is open.
    All reviewer hook and shortcut registration happens here.
    """
    _log.info("MCAT Question Generator: profile_did_open fired — running setup")
    try:
        from . import reviewer_hooks
        reviewer_hooks.setup(addon_package=__name__)
        _log.info("MCAT Question Generator: setup complete")
    except Exception:
        tb = traceback.format_exc()
        _log.error(f"MCAT Question Generator: setup failed:\n{tb}")
        # Print to stdout so the error is visible in Anki's debug console
        print(f"\n[MCAT Question Generator] Setup failed:\n{tb}", file=sys.stderr)
        # Show a visible warning dialog so the user knows something is wrong
        try:
            from aqt.utils import showWarning
            showWarning(
                "MCAT Question Generator failed to initialise.\n\n"
                "The add-on loaded but could not register its hooks.\n\n"
                f"Error:\n{tb[:600]}\n\n"
                "Check  ~/.mcat_qgen.log  for the full traceback.",
                title="MCAT Question Generator",
            )
        except Exception:
            pass  # If even the warning dialog fails, we've done what we can


# ---------------------------------------------------------------------------
# Step 3: Register the profile hook — isolated try/except
# ---------------------------------------------------------------------------
try:
    from aqt import gui_hooks
    gui_hooks.profile_did_open.append(_on_profile_open)
    _log.info("MCAT Question Generator: profile_did_open hook registered")
except Exception:
    tb = traceback.format_exc()
    _log.error(f"MCAT Question Generator: could not register profile hook:\n{tb}")
    print(f"\n[MCAT Question Generator] Could not register profile hook:\n{tb}",
          file=sys.stderr)
