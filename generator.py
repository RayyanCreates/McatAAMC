"""
generator.py — AI question generation via the Anthropic or OpenAI API.

Uses Python's built-in urllib so no third-party HTTP library is required.
Generation is always run in Anki's background task system (mw.taskman) so
the UI never freezes while waiting for a response.

This module makes no calls to any Anki collection or card data — it only
sends/receives data over HTTP.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict

from .logger_util import get_logger
from .prompt_builder import SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_mcat_question(
    user_message: str,
    config: Dict[str, Any],
    on_result: Callable[[str], None],
    on_error: Callable[[str], None],
) -> None:
    """
    Generate an MCAT-style question asynchronously using the configured AI provider.

    The API call runs in a background thread via mw.taskman so Anki's UI
    remains responsive.  Callbacks are invoked on the main (Qt) thread.

    Args:
        user_message: The prompt built by prompt_builder.build_prompt().
        config:       Validated config dict from config_manager.load_config().
        on_result:    Called with the generated text string on success.
        on_error:     Called with a human-readable error message on failure.
    """
    logger = get_logger()

    try:
        from aqt import mw
    except ImportError:
        on_error("Cannot import Anki's main window (mw). Is this running inside Anki?")
        return

    if mw is None:
        on_error("Anki main window is not available.")
        return

    def background_task() -> str:
        """Runs in Anki's background thread — performs the HTTP call."""
        provider = config.get("api_provider", "anthropic").lower().strip()
        api_key = config.get("api_key", "").strip()

        if not api_key:
            raise _ConfigError(
                "No API key is configured.\n\n"
                "Go to:  Tools → Add-ons → MCAT Question Generator → Config\n"
                "Then set the  \"api_key\"  field to your API key.\n\n"
                "Anthropic keys: https://console.anthropic.com/\n"
                "OpenAI keys:    https://platform.openai.com/api-keys"
            )

        logger.info(f"Starting generation: provider={provider!r}, model={config.get('model')!r}")

        if provider == "anthropic":
            return _call_anthropic(user_message, config, api_key)
        elif provider == "openai":
            return _call_openai(user_message, config, api_key)
        else:
            raise _ConfigError(
                f"Unknown api_provider: {provider!r}.\n"
                "Valid values are \"anthropic\" or \"openai\"."
            )

    def on_done(future) -> None:
        """Runs on Anki's main thread when the background task finishes."""
        try:
            result: str = future.result()
            logger.info("Generation completed successfully")
            on_result(result)
        except _ConfigError as exc:
            logger.warning(f"Config error: {exc}")
            on_error(str(exc))
        except _APIError as exc:
            logger.error(f"API error: {exc}")
            on_error(str(exc))
        except Exception as exc:
            logger.exception(f"Unexpected generation error: {exc}")
            on_error(
                f"An unexpected error occurred during generation:\n\n{exc}\n\n"
                "Please check the add-on log file for details."
            )

    mw.taskman.run_in_background(background_task, on_done)


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _call_anthropic(user_message: str, config: Dict[str, Any], api_key: str) -> str:
    """Call the Anthropic Messages API (api.anthropic.com/v1/messages)."""
    model = config.get("model", "claude-sonnet-4-6")
    max_tokens = int(config.get("max_tokens", 1800))
    timeout = int(config.get("timeout_seconds", 45))

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_message}
        ],
    }

    req = _make_request(
        url="https://api.anthropic.com/v1/messages",
        payload=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )

    body = _send_request(req, timeout, provider="Anthropic")

    # Extract text from Anthropic response format
    content_blocks = body.get("content", [])
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    return text

    raise _APIError(
        f"Anthropic returned an unexpected response structure: {str(body)[:300]}"
    )


def _call_openai(user_message: str, config: Dict[str, Any], api_key: str) -> str:
    """Call the OpenAI Chat Completions API (api.openai.com/v1/chat/completions)."""
    model = config.get("model", "gpt-4o")
    max_tokens = int(config.get("max_tokens", 1800))
    timeout = int(config.get("timeout_seconds", 45))

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }

    req = _make_request(
        url="https://api.openai.com/v1/chat/completions",
        payload=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    body = _send_request(req, timeout, provider="OpenAI")

    # Extract text from OpenAI response format
    choices = body.get("choices", [])
    if choices and isinstance(choices, list):
        message = choices[0].get("message", {})
        text = message.get("content", "").strip()
        if text:
            return text

    raise _APIError(
        f"OpenAI returned an unexpected response structure: {str(body)[:300]}"
    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _make_request(url: str, payload: Dict, headers: Dict) -> urllib.request.Request:
    """Build a urllib Request object."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(url, data=data, headers=headers, method="POST")


def _send_request(
    req: urllib.request.Request,
    timeout: int,
    provider: str,
) -> Dict:
    """
    Send the HTTP request and return the parsed JSON response body.

    Raises _APIError on HTTP errors or network failures.
    """
    logger = get_logger()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            body = json.loads(raw.decode("utf-8"))
            return body

    except urllib.error.HTTPError as exc:
        # Read the error body for a useful message
        try:
            error_raw = exc.read().decode("utf-8", errors="replace")
            error_json = json.loads(error_raw)
            if provider == "Anthropic":
                api_msg = error_json.get("error", {}).get("message", error_raw[:400])
            else:
                api_msg = error_json.get("error", {}).get("message", error_raw[:400])
        except Exception:
            api_msg = f"(could not parse error body)"

        logger.error(f"{provider} HTTP {exc.code}: {api_msg}")

        if exc.code == 401:
            raise _APIError(
                f"{provider} API key is invalid or unauthorised (HTTP 401).\n"
                "Check your api_key in the add-on config."
            )
        elif exc.code == 429:
            raise _APIError(
                f"{provider} rate limit exceeded (HTTP 429).\n"
                "Wait a moment, then try regenerating."
            )
        elif exc.code == 400:
            raise _APIError(
                f"{provider} rejected the request (HTTP 400): {api_msg}\n"
                "The model name or request format may be incorrect."
            )
        elif exc.code == 529:
            raise _APIError(
                f"{provider} is overloaded (HTTP 529).\n"
                "Wait a moment, then try regenerating."
            )
        else:
            raise _APIError(
                f"{provider} API error (HTTP {exc.code}): {api_msg}"
            )

    except urllib.error.URLError as exc:
        logger.error(f"{provider} network error: {exc.reason}")
        raise _APIError(
            f"Network error contacting {provider}: {exc.reason}\n"
            "Check your internet connection."
        )

    except (TimeoutError, socket.timeout):
        logger.error(f"{provider} request timed out after {timeout}s")
        raise _APIError(
            f"{provider} request timed out after {timeout} seconds.\n"
            "Try increasing timeout_seconds in the add-on config, or try again."
        )

    except json.JSONDecodeError as exc:
        logger.error(f"{provider} returned non-JSON response: {exc}")
        raise _APIError(
            f"{provider} returned an unreadable response (not valid JSON).\n"
            "This may be a temporary provider issue — try again."
        )


# ---------------------------------------------------------------------------
# Custom exceptions (internal use only)
# ---------------------------------------------------------------------------

class _ConfigError(Exception):
    """Raised when the add-on config prevents generation (missing key, bad provider, etc.)."""
    pass


class _APIError(Exception):
    """Raised when the AI provider returns an error or unexpected response."""
    pass
