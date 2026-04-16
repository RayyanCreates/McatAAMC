"""quiz_cache.py — Local cache for generated question objects.

Cache is intentionally separate from Anki collection data. It only stores quiz
question JSON in the add-on folder and can be disabled by config.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Dict, List, Optional

from .logger_util import get_logger
from .quiz_buffer import QuizQuestion

_CACHE_PATH = os.path.join(os.path.dirname(__file__), "quiz_cache.json")


def _normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return text


def _fingerprint(source_preview: str, topic_category: str = "") -> str:
    payload = f"{_normalize_text(source_preview)}|{_normalize_text(topic_category)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def load_cache() -> Dict[str, dict]:
    if not os.path.exists(_CACHE_PATH):
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        get_logger().warning(f"Could not load quiz cache: {exc}")
        return {}


def save_cache(cache: Dict[str, dict]) -> None:
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as exc:
        get_logger().warning(f"Could not save quiz cache: {exc}")


def find_cached_questions(sources: List[dict], enabled: bool = True) -> tuple[Dict[str, QuizQuestion], List[dict]]:
    if not enabled:
        return {}, sources

    cache = load_cache()
    hit_map: Dict[str, QuizQuestion] = {}
    misses: List[dict] = []
    for source in sources:
        source_id = str(source.get("source_id", ""))
        fp = _fingerprint(source.get("source_preview", ""), source.get("topic_category", ""))
        cached = cache.get(fp)
        if not cached:
            misses.append(source)
            continue
        try:
            hit_map[source_id] = QuizQuestion(**cached)
        except Exception:
            misses.append(source)
    return hit_map, misses


def update_cache(questions: List[QuizQuestion], enabled: bool = True) -> None:
    if not enabled:
        return
    cache = load_cache()
    for q in questions:
        fp = _fingerprint(q.source_preview, q.topic_category)
        cache[fp] = {
            "source_id": q.source_id,
            "source_preview": q.source_preview,
            "question": q.question,
            "choices": q.choices,
            "correct_answer": q.correct_answer,
            "explanation_correct": q.explanation_correct,
            "explanations_wrong": q.explanations_wrong,
            "topic_category": q.topic_category,
            "high_yield_takeaway": q.high_yield_takeaway,
        }
    # keep cache bounded
    if len(cache) > 500:
        keys = list(cache.keys())[-500:]
        cache = {k: cache[k] for k in keys}
    save_cache(cache)
