"""
card_reader.py — Read-only extraction of the currently active reviewer card.

SAFETY GUARANTEE:
  This module is strictly read-only with respect to Anki data.
  It calls no mutation methods (flush, save, set_field, etc.) on any Anki object.
  It only accesses attributes and calls read-only accessor methods.

HOW CURRENT-CARD DETECTION WORKS:
  Anki's main window object (mw) exposes mw.reviewer, the active reviewer
  instance.  During a review session, mw.reviewer.card holds the Card object
  that is currently displayed.  This is the live, authoritative source of
  the on-screen card — not a random note from the collection.

  We read:
    mw.reviewer.card          → Card object
    card.note()               → Note object (read-only access to fields)
    note.note_type()          → NoteType dict (or note.model() in older Anki)
    note.items()              → list of (field_name, field_value) tuples
    note.tags                 → list of tag strings
    mw.col.decks.name(card.did) → deck name string
    card.template()           → card template dict

  Nothing is written back.  The note and card objects are touched only through
  their read-only property accessors.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .logger_util import get_logger


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_current_card_data() -> Optional[Dict[str, Any]]:
    """
    Return a dict of read-only metadata for the currently reviewed card.

    Returns None (and logs a warning) if:
      - Anki is not in review state
      - mw or mw.reviewer is None
      - mw.reviewer.card is None
      - Any unexpected exception occurs during reading

    The returned dict has the shape:
    {
        "card_id":        int,
        "note_id":        int,
        "note_type_name": str,
        "deck_name":      str,
        "fields":         { field_name: {"raw": str, "text": str}, ... },
        "tags":           [str, ...],
        "template_name":  str,
    }
    """
    logger = get_logger()

    try:
        from aqt import mw  # local import; mw may not exist at module-load time
    except ImportError:
        logger.error("Could not import aqt.mw — are we running inside Anki?")
        return None

    # ------------------------------------------------------------------
    # Guard: must be in an active review session
    # ------------------------------------------------------------------
    if mw is None:
        logger.warning("get_current_card_data: mw is None")
        return None

    reviewer = getattr(mw, "reviewer", None)
    if reviewer is None:
        logger.warning("get_current_card_data: mw.reviewer is None — not reviewing")
        return None

    card = getattr(reviewer, "card", None)
    if card is None:
        logger.warning("get_current_card_data: reviewer.card is None — no active card")
        return None

    # ------------------------------------------------------------------
    # Read card and note data (all reads, no writes)
    # ------------------------------------------------------------------
    try:
        note = card.note()
        if note is None:
            logger.warning("get_current_card_data: card.note() returned None")
            return None

        note_type_name = _safe_note_type_name(note)
        deck_name = _safe_deck_name(card, mw)
        fields = _safe_read_fields(note)
        tags = _safe_read_tags(note)
        template_name = _safe_template_name(card)

        card_data: Dict[str, Any] = {
            "card_id": int(card.id),
            "note_id": int(note.id),
            "note_type_name": note_type_name,
            "deck_name": deck_name,
            "fields": fields,
            "tags": tags,
            "template_name": template_name,
        }

        logger.debug(
            f"Card data read: card_id={card.id}, note_type={note_type_name!r}, "
            f"deck={deck_name!r}, fields={list(fields.keys())}, tags={tags}"
        )
        return card_data

    except Exception as exc:
        logger.error(f"get_current_card_data: unexpected error while reading card: {exc}")
        return None


# ---------------------------------------------------------------------------
# Internal helpers — all read-only
# ---------------------------------------------------------------------------

def _safe_note_type_name(note) -> str:
    """Return the note type (model) name, compatible with Anki 2.1.45+."""
    try:
        # Anki 2.1.45+ exposes note_type()
        nt = note.note_type()
        if nt is not None:
            return str(nt.get("name", "Unknown"))
    except AttributeError:
        pass

    try:
        # Older Anki versions used note.model()
        m = note.model()
        if m is not None:
            return str(m.get("name", "Unknown"))
    except AttributeError:
        pass

    return "Unknown"


def _safe_deck_name(card, mw) -> str:
    """Return the deck name for the card's deck ID."""
    try:
        return str(mw.col.decks.name(card.did))
    except Exception:
        return "Unknown"


def _safe_read_fields(note) -> Dict[str, Dict[str, str]]:
    """
    Return all note fields as a dict of { field_name: {raw, text} }.

    'raw'  is the original HTML/text from the field.
    'text' is a clean plain-text version (HTML stripped, whitespace normalised).
    """
    fields: Dict[str, Dict[str, str]] = {}
    try:
        for field_name, field_value in note.items():
            raw = str(field_value) if field_value is not None else ""
            clean = strip_html(raw)
            fields[str(field_name)] = {"raw": raw, "text": clean}
    except Exception as exc:
        get_logger().warning(f"_safe_read_fields: error reading fields: {exc}")
    return fields


def _safe_read_tags(note) -> List[str]:
    """Return a list of tag strings from the note (no writes)."""
    try:
        return [str(t) for t in note.tags]
    except Exception:
        return []


def _safe_template_name(card) -> str:
    """Return the card template name (e.g. 'Card 1', 'Forward')."""
    try:
        tmpl = card.template()
        if tmpl is not None:
            return str(tmpl.get("name", "Unknown"))
    except Exception:
        pass
    return "Unknown"


def strip_html(text: str) -> str:
    """
    Strip HTML tags from text and decode common HTML entities.
    Returns a normalised plain-text string.
    """
    if not text:
        return ""
    # Remove HTML comments
    clean = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    # Remove script/style blocks entirely
    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", clean, flags=re.DOTALL | re.IGNORECASE)
    # Remove all remaining HTML tags
    clean = re.sub(r"<[^>]+>", " ", clean)
    # Decode common HTML entities
    entity_map = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&apos;": "'",
        "&nbsp;": " ", "&#160;": " ", "&hellip;": "...",
        "&mdash;": "—", "&ndash;": "–",
    }
    for entity, char in entity_map.items():
        clean = clean.replace(entity, char)
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean
