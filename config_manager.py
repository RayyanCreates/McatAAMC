"""
config_manager.py — Configuration loading and validation for the MCAT Question Generator.

Reads from Anki's built-in add-on config system (meta.json / config.json).
The user edits config via: Tools > Add-ons > MCAT Question Generator > Config.

All writes go through Anki's own config mechanism and do NOT touch notes, cards,
scheduling, or any other collection data.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from .logger_util import get_logger

# The defaults here match config.json and serve as a fallback if config is missing.
_DEFAULTS: Dict[str, Any] = {
    "api_provider": "anthropic",
    "api_key": "",
    "model": "claude-sonnet-4-6",
    "hotkey": "Ctrl+M",
    "button_label": "MCAT Q",
    "show_button_in_reviewer": True,
    "question_style": "auto",
    "explanation_verbosity": "standard",
    "show_topic_category": True,
    "show_high_yield_takeaway": True,
    "show_common_trap": True,
    "preferred_fields": [],
    "timeout_seconds": 45,
    "max_tokens": 1800,
}

# Valid value sets for validated keys
_VALID_VALUES: Dict[str, Any] = {
    "api_provider": {"anthropic", "openai"},
    "question_style": {"auto", "discrete", "scenario"},
    "explanation_verbosity": {"brief", "standard", "detailed"},
}


def load_config(addon_package: str) -> Dict[str, Any]:
    """
    Load the add-on config from Anki's config system.

    Merges user config over defaults so that new keys added in updates
    are always present even if the user's stored config pre-dates them.

    Args:
        addon_package: The add-on package name, i.e. the value of __name__
                       in __init__.py (e.g. "mcat_question_generator").

    Returns:
        Validated config dict.  Falls back to defaults on any error.
    """
    logger = get_logger()
    config = dict(_DEFAULTS)

    try:
        from aqt import mw

        if mw is None:
            logger.warning("mw is None during config load — using defaults")
            return config

        user_config: Optional[Dict[str, Any]] = mw.addonManager.getConfig(addon_package)
        if user_config is None:
            logger.info("No user config found — using defaults")
            return config

        # Merge user values over defaults
        for key, value in user_config.items():
            config[key] = value

    except Exception as exc:
        logger.error(f"Failed to load config: {exc} — using defaults")
        return config

    # Validate and sanitise
    config = _validate(config)
    return config


def _validate(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate config values, replacing invalid entries with defaults.
    """
    logger = get_logger()

    for key, valid in _VALID_VALUES.items():
        val = config.get(key)
        if val not in valid:
            logger.warning(
                f"Config key '{key}' has invalid value {val!r}; "
                f"falling back to default {_DEFAULTS[key]!r}"
            )
            config[key] = _DEFAULTS[key]

    # Numeric bounds
    for key, (lo, hi) in [("timeout_seconds", (5, 300)), ("max_tokens", (200, 8000))]:
        try:
            val = int(config.get(key, _DEFAULTS[key]))
            config[key] = max(lo, min(hi, val))
        except (TypeError, ValueError):
            config[key] = _DEFAULTS[key]

    # Ensure preferred_fields is a list of strings
    pf = config.get("preferred_fields", [])
    if not isinstance(pf, list):
        config["preferred_fields"] = []
    else:
        config["preferred_fields"] = [str(f) for f in pf]

    # Ensure boolean flags are actually booleans
    for key in ("show_button_in_reviewer", "show_topic_category",
                "show_high_yield_takeaway", "show_common_trap"):
        config[key] = bool(config.get(key, _DEFAULTS[key]))

    # Ensure strings are strings
    for key in ("api_provider", "api_key", "model", "hotkey", "button_label",
                "question_style", "explanation_verbosity"):
        val = config.get(key, _DEFAULTS[key])
        config[key] = str(val) if val is not None else _DEFAULTS[key]

    return config
