"""
quiz_generator.py — Batch MCAT quiz generation for the pop quiz feature.

Sends all N card concepts in a single API call, asking the model for N
structured MCAT-style questions.  Runs in Anki's background task system
(mw.taskman) so the UI stays responsive during generation.

The output format uses "## Question N" section headers so the parser can
reliably locate each question even if the model adds minor extra whitespace.

Nothing in this module reads or writes the Anki collection.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .logger_util import get_logger
from .prompt_builder import _detect_subject, _SUBJECT_GUIDANCE
from .quiz_buffer import QuizQuestion


# ---------------------------------------------------------------------------
# System prompt for batch quiz generation
# ---------------------------------------------------------------------------

QUIZ_SYSTEM_PROMPT = """\
You are an expert MCAT question writer. You will receive N Anki card concepts \
and must generate exactly N MCAT-style multiple-choice practice questions, \
one question per concept.

CORE REQUIREMENTS:
1. Each question must test APPLICATION and REASONING — not simple definition recall.
2. Exactly 4 answer choices per question (A, B, C, D) with one clearly best answer.
3. Distractors must reflect realistic MCAT confusions, not arbitrary wrong facts.
4. VARY question style across the set: mix direct conceptual questions, brief \
scenario-based questions, mechanism/consequence questions, and discrimination between \
confusable terms. Do not make all 10 questions the same style.
5. Keep each question concise but substantive — this is a timed quiz.
6. Ground every question firmly in its source card concept, but elevate it to \
exam-level thinking when the card concept is simple.

OUTPUT FORMAT — Follow EXACTLY. Use these exact headers. Repeat for each question:

## Question 1

STEM:
[Question text. Include a 1–3 sentence scenario/vignette when it adds value.]

A. [answer choice]
B. [answer choice]
C. [answer choice]
D. [answer choice]

CORRECT: [single uppercase letter A, B, C, or D]

EXPLANATION:
[2–3 sentences: why the correct answer is definitively right and why the most \
tempting distractor(s) are wrong]

TOPIC: [e.g., "Psych/Soc: Identity" or "Biochemistry: Enzyme Kinetics"]

## Question 2

[...continue through Question N with the same format]
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_quiz(
    card_data_list: List[Dict[str, Any]],
    config: Dict[str, Any],
    on_result: Callable[[List[QuizQuestion]], None],
    on_error: Callable[[str], None],
) -> None:
    """
    Generate all quiz questions in a single background API call.

    The entire batch (N cards → N questions) is sent as one request so the
    total wait time is much shorter than N sequential calls would be.

    Args:
        card_data_list: list of card data dicts from quiz_buffer.get_and_reset_batch()
        config:         validated add-on config dict
        on_result:      called on the main thread with List[QuizQuestion] on success
        on_error:       called on the main thread with an error string on failure
    """
    logger = get_logger()

    try:
        from aqt import mw
    except ImportError:
        on_error("Cannot import Anki's main window. Is this running inside Anki?")
        return

    if mw is None:
        on_error("Anki main window is not available.")
        return

    n = len(card_data_list)
    if n == 0:
        on_error("No card data available for quiz generation.")
        return

    def background_task() -> List[QuizQuestion]:
        provider = config.get("api_provider", "anthropic").lower().strip()
        api_key = config.get("api_key", "").strip()

        if not api_key:
            raise _ConfigError(
                "No API key is configured.\n\n"
                "Go to:  Tools → Add-ons → MCAT Question Generator → Config\n"
                "Set the \"api_key\" field to your Anthropic or OpenAI key.\n\n"
                "Anthropic keys: https://console.anthropic.com/\n"
                "OpenAI keys:    https://platform.openai.com/api-keys"
            )

        logger.info(
            f"Batch quiz generation: {n} questions, provider={provider!r}, "
            f"model={config.get('model')!r}"
        )

        prompt = build_quiz_prompt(card_data_list, config)

        if provider == "anthropic":
            raw = _call_anthropic(prompt, config, api_key, n)
        elif provider == "openai":
            raw = _call_openai(prompt, config, api_key, n)
        else:
            raise _ConfigError(
                f"Unknown api_provider: {provider!r}. "
                "Valid values are \"anthropic\" or \"openai\"."
            )

        questions = parse_quiz_response(raw)
        logger.info(f"Parsed {len(questions)} questions from API response (requested {n})")

        if not questions:
            raise _ParseError(
                "The AI returned a response that could not be parsed into quiz questions.\n\n"
                "This occasionally happens when the model deviates from the expected format. "
                "Please try again — the next attempt usually succeeds."
            )

        return questions

    def on_done(future) -> None:
        try:
            questions = future.result()
            on_result(questions)
        except (_ConfigError, _ParseError) as exc:
            logger.warning(f"Quiz generation non-fatal error: {exc}")
            on_error(str(exc))
        except Exception as exc:
            import traceback
            logger.exception(f"Unexpected quiz generation error: {exc}")
            on_error(
                f"An unexpected error occurred during quiz generation:\n\n{exc}\n\n"
                "Check ~/.mcat_qgen.log for the full traceback."
            )

    mw.taskman.run_in_background(background_task, on_done)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_quiz_prompt(
    card_data_list: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> str:
    """
    Build the user-turn message for the batch quiz API call.

    Includes all N card concepts in numbered blocks so the model can
    generate one question per concept.
    """
    n = len(card_data_list)
    preferred_fields: List[str] = config.get("preferred_fields", [])

    # Build one card block per entry
    card_blocks: List[str] = []
    for idx, card_data in enumerate(card_data_list, start=1):
        note_type = card_data.get("note_type_name", "Unknown")
        deck = card_data.get("deck_name", "Unknown")
        tags: List[str] = card_data.get("tags", [])
        fields: Dict[str, Dict[str, str]] = card_data.get("fields", {})

        # Build field lines (honour preferred_fields if set)
        field_lines: List[str] = []
        if preferred_fields:
            for fname in preferred_fields:
                if fname in fields:
                    text = fields[fname].get("text", "").strip()
                    if text:
                        field_lines.append(f"  {fname}: {text}")
        if not field_lines:
            for fname, fdata in fields.items():
                text = fdata.get("text", "").strip()
                if text:
                    field_lines.append(f"  {fname}: {text}")
        fields_block = "\n".join(field_lines) if field_lines else "  (empty)"

        # Filter internal Anki tags
        skip = ("marked", "leech", "is:")
        clean_tags = [t for t in tags if not any(t.lower().startswith(p) for p in skip)]
        tags_str = ", ".join(clean_tags) if clean_tags else "None"

        card_blocks.append(
            f"=== CARD {idx} ===\n"
            f"Note Type: {note_type}\n"
            f"Deck: {deck}\n"
            f"Tags: {tags_str}\n"
            f"Fields:\n{fields_block}\n"
            f"=== END CARD {idx} ==="
        )

    cards_section = "\n\n".join(card_blocks)

    # Detect dominant subject for additional guidance
    combined_text = " ".join(
        " ".join(v.get("text", "") for v in cd.get("fields", {}).values())
        + " " + cd.get("deck_name", "")
        + " " + " ".join(cd.get("tags", []))
        for cd in card_data_list
    ).lower()
    subject_key = _detect_subject(combined_text)
    subject_guidance = _SUBJECT_GUIDANCE.get(subject_key, "")

    # Verbosity instruction
    verbosity = config.get("explanation_verbosity", "standard")
    if verbosity == "brief":
        verbosity_instr = "Keep explanations SHORT: 1-2 sentences each."
    elif verbosity == "detailed":
        verbosity_instr = "Provide THOROUGH explanations: 3-4 sentences covering mechanism and reasoning."
    else:
        verbosity_instr = "Keep explanations FOCUSED: 2-3 sentences each."

    parts = [
        f"Generate exactly {n} MCAT-style quiz questions — one per card concept below.\n",
        cards_section,
        "",
        f"EXPLANATION STYLE: {verbosity_instr}",
    ]
    if subject_guidance:
        parts += ["", f"SUBJECT GUIDANCE FOR THIS BATCH:\n{subject_guidance}"]
    parts += [
        "",
        "QUALITY REMINDERS:",
        "- Do NOT ask 'What is [term]?' — test reasoning, application, or discrimination.",
        "- Distractors must reflect actual MCAT confusions between related concepts.",
        f"- Vary the style across the {n} questions (some direct, some scenario-based).",
        f"- Output EXACTLY {n} questions numbered 1 through {n} using the prescribed format.",
    ]

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_quiz_response(text: str) -> List[QuizQuestion]:
    """
    Parse the batch API response into a list of QuizQuestion objects.

    Splits on '## Question N' section headers and parses each section
    independently.  Sections that fail to parse are skipped with a warning
    rather than aborting the entire quiz.
    """
    logger = get_logger()
    questions: List[QuizQuestion] = []

    # Split on "## Question N" (case-insensitive, tolerant of extra spaces)
    raw_sections = re.split(r"\n?##\s+Question\s+\d+\s*\n", text, flags=re.IGNORECASE)

    # The first element is any text before "## Question 1" — skip it
    sections = [s.strip() for s in raw_sections[1:] if s.strip()]

    for i, section in enumerate(sections, start=1):
        q = _parse_single_question(section)
        if q is not None:
            questions.append(q)
        else:
            logger.warning(f"parse_quiz_response: could not parse question section {i}")

    return questions


def _parse_single_question(text: str) -> Optional[QuizQuestion]:
    """
    Parse one question section into a QuizQuestion.

    The section is the text AFTER a '## Question N' header and BEFORE the
    next '## Question' header (or end of string).
    """
    try:
        # ---- STEM -------------------------------------------------------
        # "STEM:" followed by text up to the first "A." answer choice line
        stem_match = re.search(
            r"STEM:\s*\n?(.*?)(?=\n\s*A\.)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if not stem_match:
            # Try "STEM:" with content on the same line
            stem_match = re.search(
                r"STEM:\s*(.+?)(?=\n\s*A\.)",
                text,
                re.DOTALL | re.IGNORECASE,
            )
        stem = stem_match.group(1).strip() if stem_match else ""
        stem = re.sub(r"\s+", " ", stem).strip()
        if not stem:
            return None

        # ---- CHOICES A-D ------------------------------------------------
        choices: Dict[str, str] = {}
        # Match each choice: letter + period + content, stopping at the next
        # letter or at CORRECT:
        choice_re = re.compile(
            r"^([A-D])\.\s+(.+?)(?=\n[A-D]\.\s|\nCORRECT:|\Z)",
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        for m in choice_re.finditer(text):
            letter = m.group(1).upper()
            choice_text = re.sub(r"\s+", " ", m.group(2)).strip()
            if choice_text:
                choices[letter] = choice_text

        if len(choices) < 2:
            return None

        # ---- CORRECT ANSWER ---------------------------------------------
        correct_match = re.search(
            r"CORRECT:\s*([A-D])", text, re.IGNORECASE
        )
        if not correct_match:
            return None
        correct_key = correct_match.group(1).upper()
        if correct_key not in choices:
            return None

        # ---- EXPLANATION ------------------------------------------------
        exp_match = re.search(
            r"EXPLANATION:\s*\n?(.*?)(?=\nTOPIC:|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        explanation = ""
        if exp_match:
            explanation = re.sub(r"\s+", " ", exp_match.group(1)).strip()

        # ---- TOPIC ------------------------------------------------------
        topic_match = re.search(
            r"TOPIC:\s*(.+?)$", text, re.MULTILINE | re.IGNORECASE
        )
        topic = topic_match.group(1).strip() if topic_match else ""

        return QuizQuestion(
            source_concept="",   # not tracked at this level
            stem=stem,
            choices=choices,
            correct_key=correct_key,
            explanation=explanation,
            topic=topic,
        )

    except Exception as exc:
        get_logger().warning(f"_parse_single_question: {exc}")
        return None


# ---------------------------------------------------------------------------
# HTTP — Anthropic
# ---------------------------------------------------------------------------

def _call_anthropic(
    user_message: str,
    config: Dict[str, Any],
    api_key: str,
    n: int,
) -> str:
    # For batch generation we need more tokens than a single question
    base_tokens = int(config.get("max_tokens", 1800))
    quiz_max_tokens = int(config.get("quiz_max_tokens", max(base_tokens * 2, 5000)))
    timeout = int(config.get("timeout_seconds", 45))
    model = config.get("model", "claude-sonnet-4-6")

    payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": quiz_max_tokens,
        "system": QUIZ_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }
    req = _make_request(
        "https://api.anthropic.com/v1/messages",
        payload,
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    body = _send_request(req, timeout, "Anthropic")
    for block in body.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "").strip()
            if text:
                return text
    raise _APIError(f"Anthropic returned unexpected structure: {str(body)[:300]}")


# ---------------------------------------------------------------------------
# HTTP — OpenAI
# ---------------------------------------------------------------------------

def _call_openai(
    user_message: str,
    config: Dict[str, Any],
    api_key: str,
    n: int,
) -> str:
    base_tokens = int(config.get("max_tokens", 1800))
    quiz_max_tokens = int(config.get("quiz_max_tokens", max(base_tokens * 2, 5000)))
    timeout = int(config.get("timeout_seconds", 45))
    model = config.get("model", "gpt-4o")

    payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": quiz_max_tokens,
        "messages": [
            {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }
    req = _make_request(
        "https://api.openai.com/v1/chat/completions",
        payload,
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    body = _send_request(req, timeout, "OpenAI")
    choices = body.get("choices", [])
    if choices:
        text = choices[0].get("message", {}).get("content", "").strip()
        if text:
            return text
    raise _APIError(f"OpenAI returned unexpected structure: {str(body)[:300]}")


# ---------------------------------------------------------------------------
# Shared HTTP helpers
# ---------------------------------------------------------------------------

def _make_request(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
) -> urllib.request.Request:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(url, data=data, headers=headers, method="POST")


def _send_request(
    req: urllib.request.Request,
    timeout: int,
    provider: str,
) -> Dict[str, Any]:
    logger = get_logger()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        try:
            error_json = json.loads(exc.read().decode("utf-8", errors="replace"))
            api_msg = error_json.get("error", {}).get("message", "")
        except Exception:
            api_msg = "(could not parse error body)"
        logger.error(f"{provider} HTTP {exc.code}: {api_msg}")
        if exc.code == 401:
            raise _APIError(f"{provider} API key invalid or unauthorised (HTTP 401). "
                            "Check api_key in the add-on config.")
        if exc.code == 429:
            raise _APIError(f"{provider} rate limit exceeded (HTTP 429). "
                            "Wait a moment, then try again.")
        raise _APIError(f"{provider} API error (HTTP {exc.code}): {api_msg}")

    except urllib.error.URLError as exc:
        logger.error(f"{provider} network error: {exc.reason}")
        raise _APIError(f"Network error contacting {provider}: {exc.reason}. "
                        "Check your internet connection.")

    except (TimeoutError, socket.timeout):
        logger.error(f"{provider} timed out after {timeout}s")
        raise _APIError(f"{provider} request timed out after {timeout}s. "
                        "Try increasing timeout_seconds in config, or try again.")

    except json.JSONDecodeError as exc:
        raise _APIError(f"{provider} returned non-JSON response: {exc}")


# ---------------------------------------------------------------------------
# Internal exceptions
# ---------------------------------------------------------------------------

class _ConfigError(Exception):
    """Bad or missing config prevents generation."""

class _ParseError(Exception):
    """Response could not be parsed into quiz questions."""

class _APIError(Exception):
    """API returned an error or unexpected format."""
