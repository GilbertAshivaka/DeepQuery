"""
Deep Query — Shared JSON parsing for model outputs.

A single, tolerant ``parse_json_object`` used by every place that coerces a JSON object
out of a model reply (orchestrator graph, controller, live retrieval, action agent).
Previously each module carried its own identical copy; centralizing it keeps the
fence-stripping and error handling consistent.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def parse_json_object(text: Any) -> Optional[dict]:
    """Parse a JSON object from a model response, tolerating ```json fences.

    Accepts either the text itself or a raw ``AIMessage.content`` value — which is a list
    of typed blocks rather than a ``str`` whenever the reply carries a thinking block
    (Anthropic extended/adaptive thinking). List content is flattened to its answer text
    first, so callers can keep passing ``resp.content`` directly.

    Returns the dict, or ``None`` when the text is empty, isn't valid JSON, or isn't a
    JSON object (a list/scalar yields ``None`` so callers can treat it as a parse miss).
    """
    if not text:
        return None
    if not isinstance(text, str):
        # Lazy import keeps this module dependency-free at import time.
        from agents.models.reasoning import content_to_text

        text = content_to_text(text)
        if not text:
            return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        nl = cleaned.find("\n")
        cleaned = cleaned[nl + 1:] if nl != -1 else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
