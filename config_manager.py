"""
config_manager.py — Configuration loading and validation for the MCAT Question Generator.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from .logger_util import get_logger

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
    "quiz_interval_count": 10,
    "quiz_size": 10,
    "scramble_question_order": True,
    "scramble_answer_choices": True,
    "quiz_max_tokens": 3200,
    "cache_enabled": True,
    "generation_mode": "cheap",
    "include_wrong_answer_rationales": False,
}

_VALID_VALUES: Dict[str, Any] = {
    "api_provider": {"anthropic", "openai"},
    "question_style": {"auto", "discrete", "scenario"},
    "explanation_verbosity": {"brief", "standard", "detailed"},
    "generation_mode": {"cheap", "balanced", "rich"},
}


def load_config(addon_package: str) -> Dict[str, Any]:
    logger = get_logger()
    config = dict(_DEFAULTS)

    try:
        from aqt import mw
        if mw is None:
            return config
        user_config: Optional[Dict[str, Any]] = mw.addonManager.getConfig(addon_package)
        if user_config:
            config.update(user_config)
    except Exception as exc:
        logger.error(f"Failed to load config: {exc} — using defaults")
        return config

    return _validate(config)


def _validate(config: Dict[str, Any]) -> Dict[str, Any]:
    logger = get_logger()

    for key, valid in _VALID_VALUES.items():
        if config.get(key) not in valid:
            logger.warning(f"Config key {key!r} invalid; using default")
            config[key] = _DEFAULTS[key]

    for key, (lo, hi) in [
        ("timeout_seconds", (5, 300)),
        ("max_tokens", (200, 8000)),
        ("quiz_max_tokens", (500, 12000)),
        ("quiz_interval_count", (1, 100)),
        ("quiz_size", (1, 50)),
    ]:
        try:
            config[key] = max(lo, min(hi, int(config.get(key, _DEFAULTS[key]))))
        except (TypeError, ValueError):
            config[key] = _DEFAULTS[key]

    pf = config.get("preferred_fields", [])
    config["preferred_fields"] = [str(f) for f in pf] if isinstance(pf, list) else []

    for key in (
        "show_button_in_reviewer", "show_topic_category", "show_high_yield_takeaway",
        "show_common_trap", "scramble_question_order", "scramble_answer_choices",
        "cache_enabled", "include_wrong_answer_rationales",
    ):
        config[key] = bool(config.get(key, _DEFAULTS[key]))

    for key in (
        "api_provider", "api_key", "model", "hotkey", "button_label",
        "question_style", "explanation_verbosity", "generation_mode",
    ):
        val = config.get(key, _DEFAULTS[key])
        config[key] = str(val) if val is not None else _DEFAULTS[key]

    return config
