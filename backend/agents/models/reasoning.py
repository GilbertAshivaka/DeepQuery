"""
Deep Query — Provider-agnostic reasoning / answer extraction

Different vendors expose chain-of-thought ("thinking") differently:

  - Groq (gpt-oss, reasoning_format="parsed") → additional_kwargs["reasoning_content"]
  - Ollama (reasoning=True)                   → additional_kwargs["reasoning_content"]
  - DeepSeek-R1 / Qwen QwQ / vLLM (OpenAI API) → additional_kwargs["reasoning_content"]
        (recovered by ReasoningChatOpenAI; stock langchain-openai drops it)
  - Anthropic (extended thinking)             → content blocks of type "thinking"
  - OpenAI o-series, Gemini                   → CoT not exposed over the standard APIs

These helpers normalize a streamed ``BaseMessageChunk`` into two clean deltas — the
thinking text and the answer text — so the streaming consumers (orchestrator graph,
resumable controller) stay provider-agnostic.
"""

from __future__ import annotations

from typing import Any

# Content-block types that carry chain-of-thought rather than the answer.
_THINKING_BLOCK_TYPES = {"thinking", "reasoning", "reasoning_content", "redacted_thinking"}
# Content-block types that carry answer text.
_TEXT_BLOCK_TYPES = {None, "text", "text_delta", "output_text"}


def extract_reasoning_delta(chunk: Any) -> str:
    """Return the thinking/CoT text in a streamed chunk (``""`` if none)."""
    ak = getattr(chunk, "additional_kwargs", None) or {}
    rc = ak.get("reasoning_content") or ak.get("reasoning")
    if isinstance(rc, str) and rc:
        return rc

    # Anthropic / standardized reasoning: content is a list of typed blocks.
    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in _THINKING_BLOCK_TYPES:
                out.append(
                    block.get("thinking") or block.get("reasoning") or block.get("text") or ""
                )
        if out:
            return "".join(out)
    return ""


def extract_text_delta(chunk: Any) -> str:
    """Return the answer-text in a streamed chunk, excluding thinking blocks.

    Handles both plain-string content (most providers) and list-of-blocks content
    (Anthropic with extended thinking), so thinking never leaks into the answer."""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, str):
                out.append(block)
            elif isinstance(block, dict) and block.get("type") in _TEXT_BLOCK_TYPES:
                out.append(block.get("text") or "")
        return "".join(out)
    return ""
