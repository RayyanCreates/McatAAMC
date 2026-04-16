"""quiz_generator.py — Cost-efficient batched quiz generation (single API call)."""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List

from .logger_util import get_logger
from .prompt_builder import _detect_subject, _SUBJECT_GUIDANCE
from .quiz_buffer import QuizQuestion

QUIZ_SYSTEM_PROMPT = (
    "You write MCAT multiple-choice questions. Return strict JSON only. "
    "No markdown, no prose outside JSON."
)


def generate_quiz(
    sources: List[Dict[str, Any]],
    config: Dict[str, Any],
    on_result: Callable[[List[QuizQuestion]], None],
    on_error: Callable[[str], None],
) -> None:
    logger = get_logger()
    try:
        from aqt import mw
    except ImportError:
        on_error("Cannot import Anki's main window. Is this running inside Anki?")
        return
    if mw is None:
        on_error("Anki main window is not available.")
        return
    if not sources:
        on_result([])
        return

    def background_task() -> List[QuizQuestion]:
        provider = config.get("api_provider", "anthropic").lower().strip()
        api_key = config.get("api_key", "").strip()
        if not api_key:
            raise _ConfigError("No API key is configured in add-on settings.")

        prompt = build_quiz_prompt(sources, config)
        logger.info(f"Batch quiz request with {len(sources)} source concepts")
        if provider == "anthropic":
            raw = _call_anthropic(prompt, config, api_key)
        elif provider == "openai":
            raw = _call_openai(prompt, config, api_key)
        else:
            raise _ConfigError(f"Unknown api_provider: {provider!r}")

        questions = parse_quiz_response(raw)
        if not questions:
            raise _ParseError("Could not parse JSON quiz response from model.")
        return questions

    def on_done(future) -> None:
        try:
            on_result(future.result())
        except (_ConfigError, _ParseError, _APIError) as exc:
            on_error(str(exc))
        except Exception as exc:
            logger.exception("Unexpected quiz generation error")
            on_error(f"Unexpected quiz generation error: {exc}")

    mw.taskman.run_in_background(background_task, on_done)


def build_quiz_prompt(sources: List[Dict[str, Any]], config: Dict[str, Any]) -> str:
    n = len(sources)
    verbosity = config.get("explanation_verbosity", "standard")
    include_wrong = bool(config.get("include_wrong_answer_rationales", False))
    mode = str(config.get("generation_mode", "cheap")).lower()

    if verbosity == "brief":
        expl = "Keep explanations <=1 sentence."
    elif verbosity == "detailed":
        expl = "Use 2 concise sentences."
    else:
        expl = "Use concise explanations."

    fields = "Include explanations_wrong only if requested; else keep as empty object."
    if include_wrong:
        fields = "Include short explanations_wrong for each choice letter."

    combined = " ".join(s.get("source_preview", "") for s in sources).lower()
    subject_guidance = _SUBJECT_GUIDANCE.get(_detect_subject(combined), "")

    payload = {
        "count": n,
        "mode": mode,
        "requirements": [
            "One question per source_id",
            "4 answer choices A-D",
            "Realistic MCAT distractors",
            expl,
            fields,
        ],
        "output_schema": {
            "questions": [
                {
                    "source_id": "string",
                    "source_preview": "string",
                    "question": "string",
                    "choices": {"A": "string", "B": "string", "C": "string", "D": "string"},
                    "correct_answer": "A|B|C|D",
                    "explanation_correct": "string",
                    "explanations_wrong": {"A": "string", "B": "string", "C": "string", "D": "string"},
                    "topic_category": "string",
                    "high_yield_takeaway": "string",
                }
            ]
        },
        "sources": sources,
        "subject_guidance": subject_guidance,
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_quiz_response(text: str) -> List[QuizQuestion]:
    data = _extract_json_obj(text)
    arr = data.get("questions", []) if isinstance(data, dict) else []
    out: List[QuizQuestion] = []
    for obj in arr:
        if not isinstance(obj, dict):
            continue
        choices = obj.get("choices", {})
        if not isinstance(choices, dict):
            continue
        correct = str(obj.get("correct_answer", "")).upper()
        if correct not in {"A", "B", "C", "D"}:
            continue
        out.append(
            QuizQuestion(
                source_id=str(obj.get("source_id", "")),
                source_preview=str(obj.get("source_preview", "")),
                question=str(obj.get("question", "")).strip(),
                choices={k: str(v) for k, v in choices.items() if k in {"A", "B", "C", "D"}},
                correct_answer=correct,
                explanation_correct=str(obj.get("explanation_correct", "")).strip(),
                explanations_wrong={
                    k: str(v) for k, v in (obj.get("explanations_wrong", {}) or {}).items() if k in {"A", "B", "C", "D"}
                },
                topic_category=str(obj.get("topic_category", "")).strip(),
                high_yield_takeaway=str(obj.get("high_yield_takeaway", "")).strip(),
            )
        )
    return out


def _extract_json_obj(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}


def _call_anthropic(user_message: str, config: Dict[str, Any], api_key: str) -> str:
    timeout = int(config.get("timeout_seconds", 45))
    model = config.get("model", "claude-sonnet-4-6")
    quiz_tokens = int(config.get("quiz_max_tokens", config.get("max_tokens", 1800)))
    payload = {
        "model": model,
        "max_tokens": quiz_tokens,
        "system": QUIZ_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }
    req = _make_request(
        "https://api.anthropic.com/v1/messages",
        payload,
        {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    body = _send_request(req, timeout, "Anthropic")
    for block in body.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "").strip()
            if text:
                return text
    raise _APIError("Anthropic returned unexpected response structure.")


def _call_openai(user_message: str, config: Dict[str, Any], api_key: str) -> str:
    timeout = int(config.get("timeout_seconds", 45))
    model = config.get("model", "gpt-4o")
    quiz_tokens = int(config.get("quiz_max_tokens", config.get("max_tokens", 1800)))
    payload = {
        "model": model,
        "max_tokens": quiz_tokens,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": QUIZ_SYSTEM_PROMPT}, {"role": "user", "content": user_message}],
    }
    req = _make_request(
        "https://api.openai.com/v1/chat/completions",
        payload,
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    body = _send_request(req, timeout, "OpenAI")
    choices = body.get("choices", [])
    if choices:
        text = choices[0].get("message", {}).get("content", "").strip()
        if text:
            return text
    raise _APIError("OpenAI returned unexpected response structure.")


def _make_request(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> urllib.request.Request:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(url, data=data, headers=headers, method="POST")


def _send_request(req: urllib.request.Request, timeout: int, provider: str) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _APIError(f"{provider} API error (HTTP {exc.code}).")
    except urllib.error.URLError as exc:
        raise _APIError(f"Network error contacting {provider}: {exc.reason}")
    except (TimeoutError, socket.timeout):
        raise _APIError(f"{provider} request timed out after {timeout}s")
    except json.JSONDecodeError as exc:
        raise _APIError(f"{provider} returned non-JSON response: {exc}")


class _ConfigError(Exception):
    pass


class _ParseError(Exception):
    pass


class _APIError(Exception):
    pass
