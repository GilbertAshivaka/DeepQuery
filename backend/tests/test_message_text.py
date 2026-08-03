"""
Deep Query — Regression tests for list-content normalization.

When a model reply carries a thinking block, ``AIMessage.content`` is a *list of typed
blocks*, not a ``str`` — so any consumer that reads ``.content`` and calls ``.strip()``
raises ``'list' object has no attribute 'strip'``. These tests pin the two entry points
that must survive that shape: the shared normalizer (``message_text`` /
``content_to_text``) and ``parse_json_object``, which now accepts list content directly.
"""

import pytest

from agents.json_utils import parse_json_object
from agents.models.reasoning import content_to_text, message_text

from langchain_core.messages import AIMessage


def _ai(content):
    """Build the AIMessage shape langchain-anthropic returns for a reply that carries a
    thinking block (chat_models.py:1727-1740) — a list of typed block dicts."""
    return AIMessage(content=content)


# ── message_text / content_to_text ──────────────────────────────────

class TestContentToText:
    def test_plain_string_passthrough(self):
        assert content_to_text("just text") == "just text"

    def test_empty_and_none(self):
        assert content_to_text("") == ""
        assert content_to_text(None) == ""

    def test_single_text_block(self):
        # The one shape langchain-anthropic still collapses to a bare str.
        assert content_to_text([{"type": "text", "text": "hello"}]) == "hello"

    def test_thinking_block_is_dropped(self):
        # thinking + text — the Claude 5 adaptive case.
        assert content_to_text([
            {"type": "thinking", "thinking": "secret", "signature": "x"},
            {"type": "text", "text": "the answer"},
        ]) == "the answer"

    def test_only_thinking_yields_empty(self):
        assert content_to_text([{"type": "thinking", "thinking": "secret"}]) == ""

    def test_unknown_block_types_skipped(self):
        assert content_to_text([
            {"type": "tool_use", "name": "x", "input": {}},
            {"type": "text", "text": "kept"},
        ]) == "kept"

    def test_string_blocks_accepted(self):
        assert content_to_text(["a", "b"]) == "ab"

    def test_non_text_dict_keyed_with_other_keys(self):
        assert content_to_text([{"type": "thinking", "thinking": "t"}]) == ""


class TestMessageText:
    def test_message_with_list_content(self):
        assert message_text(_ai([
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "answer"},
        ])) == "answer"

    def test_message_with_string_content(self):
        assert message_text(_ai("plain")) == "plain"

    def test_object_without_content_falls_back_to_str(self):
        # Preserves the second half of the `... else str(resp)` idiom this replaced, so a
        # provider returning a bare string/object still yields something usable.
        assert message_text("already a string") == "already a string"
        assert message_text(42) == "42"


# ── parse_json_object ──────────────────────────────────────────────

class TestParseJsonObjectListContent:
    def test_list_with_thinking_parses(self):
        # The reported crash: raw .content fed straight into the JSON parser.
        msg = _ai([
            {"type": "thinking", "thinking": "let me think"},
            {"type": "text", "text": '{"outcome": "VERIFIED"}'},
        ])
        assert parse_json_object(msg.content) == {"outcome": "VERIFIED"}

    def test_plain_string_unchanged(self):
        assert parse_json_object('{"intent": "search"}') == {"intent": "search"}

    def test_none_and_empty(self):
        assert parse_json_object(None) is None
        assert parse_json_object("") is None

    def test_non_json_list_content_returns_none(self):
        # The answer isn't JSON; the fallback path (keyword scan) stays reachable.
        msg = _ai([
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "I don't know"},
        ])
        assert parse_json_object(msg.content) is None

    def test_fenced_list_content(self):
        msg = _ai([
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": '```json\n{"a": 1}\n```'},
        ])
        assert parse_json_object(msg.content) == {"a": 1}

    def test_scalar_list_content_returns_none(self):
        # A bare scalar isn't a JSON object — parse miss, not a crash.
        msg = _ai([{"type": "text", "text": "42"}])
        assert parse_json_object(msg.content) is None


# ── groq_client boundary (the reported chat failure) ───────────────

class TestGroqClientReturnsText:
    def test_list_content_becomes_text(self):
        from llm.groq_client import GroqClient

        class _FakeLLM:
            def invoke(self, messages):
                return _ai([
                    {"type": "thinking", "thinking": "hmm"},
                    {"type": "text", "text": "verified"},
                ])

        c = GroqClient()
        c._get_llm = lambda *a, **k: _FakeLLM()
        assert c._call_with_retry([], 0.0) == "verified"

    def test_string_content_passthrough(self):
        from llm.groq_client import GroqClient

        class _FakeLLM:
            def invoke(self, messages):
                return _ai("plain")

        c = GroqClient()
        c._get_llm = lambda *a, **k: _FakeLLM()
        assert c._call_with_retry([], 0.0) == "plain"
