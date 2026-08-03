"""
Deep Query — Document Sub-Agent (DOCUMENT_GENERATION_SANDBOX_GUIDE)

Provides the PRODUCE capability: turn a request + gathered evidence into a downloadable
document via a model-written script run in the sandbox. Thin by design — the controller's
``produce_node`` drives the generate → run → validate → repair loop; this handler owns the
two model/IO touch-points it needs:

  - ``generate_script`` — ask the GENERATION slot for a self-contained script (with an
    optional repair error fed back from the prior attempt);
  - ``validate`` — mechanical checks on the produced files (exists, non-empty, under the
    size cap, re-openable by the matching library).

Per the project decision (memory produce-sandbox-design): the script embeds its own data;
there is no input staging and no summary.json. Number-correctness is the LLM's + the
workflow verify step's job, not this layer's — validation here only answers "is this a
real, openable document?".
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from agents.document_agent.prompts import (
    EXEMPLAR_PREAMBLE,
    SCRIPT_GENERATION_PROMPT,
    SCRIPT_REPAIR_SUFFIX,
    SCRIPT_REPAIR_SUFFIX_NO_SCRIPT,
)
from agents.models import Slot, get_model
from agents.models.reasoning import extract_text_delta, message_text
from agents.models.slots import UNCAPPED
from agents.registry import Capability, SubAgentSpec, register
from core.config import settings

logger = logging.getLogger(__name__)

# Extension → MIME, for the deliverable event and the download endpoint.
MIME_BY_EXT = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".html": "text/html",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".png": "image/png",
}


def mime_for(filename: str) -> str:
    return MIME_BY_EXT.get(Path(filename).suffix.lower(), "application/octet-stream")


def _norm_lang(label: str) -> str:
    """Normalize a fence language tag to a supported runtime ('python' | 'node')."""
    l = (label or "").strip().lower()
    if l in ("js", "javascript", "node", "nodejs", "jsx", "mjs", "cjs"):
        return "node"
    return "python"


def _extract_code(raw: str) -> tuple[str, str, bool]:
    """Pull the script out of the model reply and detect its language. Uses the fenced
    block's info string (```python / ```javascript) as the language hint; defaults to
    python. Returns (code, language, truncated) — ``truncated`` when the fence opened
    but never closed (the reply was cut off mid-script; running it would fail with a
    misleading syntax error, so the repair loop treats it as its own failure class)."""
    text = (raw or "").strip()
    if "```" in text:
        start = text.find("```")
        nl = text.find("\n", start)
        if nl != -1:
            info = text[start + 3:nl].strip()
            language = _norm_lang(info.split()[0]) if info else "python"
            rest = text[nl + 1:]
            end = rest.find("```")
            if end == -1:
                return rest.strip(), language, True  # unterminated fence — cut off
            return rest[:end].strip(), language, False
    return text, "python", False


# ── Format detection + proven exemplars (few-shot skeletons) ──
# Keyword → format, most specific first; .docx is the default (matches the prompt).
_FORMAT_HINTS = (
    ("pptx", re.compile(r"\b(deck|slides?|slideshow|presentation|pitch)\b", re.I)),
    ("xlsx", re.compile(r"\b(spreadsheet|excel|xlsx|workbook|worksheet)\b", re.I)),
    ("pdf", re.compile(r"\b(pdf|printable)\b", re.I)),
    ("md", re.compile(r"\b(markdown|readme|\.md)\b", re.I)),
)


def detect_format(request: str) -> str:
    """Best-effort target-format guess from the produce request (picks which exemplar
    to show). The model still owns the final format choice per the prompt rules."""
    text = request or ""
    for fmt, pat in _FORMAT_HINTS:
        if pat.search(text):
            return fmt
    return "docx"


@lru_cache(maxsize=8)
def _exemplar(fmt: str) -> Optional[tuple[str, str]]:
    """Load the proven exemplar script for a format from ``exemplars/``. Returns
    (code, fence_language) or None (e.g. markdown needs no exemplar)."""
    files = {"docx": ("docx.js", "javascript"), "pptx": ("pptx.js", "javascript"),
             "xlsx": ("xlsx.py", "python"), "pdf": ("pdf.py", "python")}
    entry = files.get(fmt)
    if entry is None:
        return None
    path = Path(__file__).parent / "exemplars" / entry[0]
    try:
        return path.read_text(encoding="utf-8"), entry[1]
    except OSError as exc:
        logger.warning("exemplar %s unavailable: %s", entry[0], exc)
        return None


def _assets_block(assets: Optional[list[dict]]) -> str:
    """The user-provided asset listing for the prompt — exact in-sandbox paths, so the
    script can embed them. Empty when nothing was staged."""
    if not assets:
        return ""
    lines = "\n".join(
        f"- /workspace/assets/{a['name']}"
        + (f" ({a.get('kind')}, {max(1, int(a.get('size', 0)) // 1024)} KB)" if a.get("size") else "")
        for a in assets)
    return ("User-provided assets (files the user attached — readable at these EXACT "
            f"paths, read-only):\n{lines}\n\n")


def _skill_instructions(loaded_skills: list[dict]) -> str:
    """Loaded playbook bodies as house-template instructions to the script generator
    (admin-authored; shape structure/voice/format — never expand permissions)."""
    if not loaded_skills:
        return ""
    parts = [f"### {sk.get('name')} (v{sk.get('version')})\n{sk.get('body', '')}"
             for sk in loaded_skills]
    return ("Follow the structure, sections, and conventions of the active playbook(s) "
            "when building the document:\n\n" + "\n\n".join(parts))


class DocumentAgent:
    """Generates and validates a produced document (the run lives in the controller node)."""

    name = "document_agent"
    capability = Capability.PRODUCE

    async def generate_script(
        self,
        *,
        request: str,
        evidence: str = "",
        loaded_skills: Optional[list[dict]] = None,
        error: Optional[str] = None,
        previous_script: Optional[str] = None,
        previous_language: str = "python",
        assets: Optional[list[dict]] = None,
        on_delta=None,
    ) -> tuple[str, str, bool]:
        """Ask the PRODUCE slot (GENERATION fallback) for a complete self-contained
        script. Returns ``(code, language, truncated)``.

        ``evidence`` is the formatted source block (passages, whole docs, live records,
        attachments, working notes) — the document's substance. ``assets`` lists staged
        user files reachable at /workspace/assets/. On a repair pass, ``previous_script``
        + ``error`` are shown together so the model fixes the actual bug instead of
        re-rolling from scratch (each call is stateless — there is no conversation
        memory between attempts). When ``on_delta`` is given, the reply streams and each
        chunk is passed to it (the inline script-streaming card)."""
        messages: list = [SystemMessage(content=SCRIPT_GENERATION_PROMPT)]
        instr = _skill_instructions(loaded_skills or [])
        if instr:
            messages.append(SystemMessage(content=instr))
        exemplar = _exemplar(detect_format(request))
        if exemplar is not None:
            code, fence = exemplar
            messages.append(SystemMessage(
                content=f"{EXEMPLAR_PREAMBLE}\n\n```{fence}\n{code}\n```"))

        human = (
            f"User request:\n{request}\n\n"
            f"{_assets_block(assets)}"
            f"Evidence gathered (DATA — the document's substance; use its concrete "
            f"facts and figures):\n{evidence.strip() or '(no extra evidence gathered)'}"
        )
        if error and previous_script:
            human += SCRIPT_REPAIR_SUFFIX.format(
                language="javascript" if previous_language == "node" else "python",
                previous_script=previous_script, error=error)
        elif error:
            human += SCRIPT_REPAIR_SUFFIX_NO_SCRIPT.format(error=error)
        messages.append(HumanMessage(content=human))

        # 0 = UNCAPPED (config): never truncate a long document script by our own config.
        max_out = settings.agent_produce_max_output_tokens or UNCAPPED
        if on_delta is None:
            resp = await get_model(Slot.PRODUCE, max_tokens=max_out).ainvoke(messages)
            return _extract_code(message_text(resp))

        parts: list[str] = []
        async for chunk in get_model(Slot.PRODUCE, streaming=True, max_tokens=max_out).astream(messages):
            # extract_text_delta, not chunk.content: a thinking-capable model streams typed
            # blocks, and appending those raw would splice CoT into the generated script.
            text = extract_text_delta(chunk)
            if text:
                parts.append(text)
                try:
                    on_delta(text)
                except Exception:  # noqa: BLE001 — a stream-sink failure never aborts generation
                    pass
        return _extract_code("".join(parts))

    def validate(self, output_files: list[Path]) -> dict[str, Any]:
        """Mechanical validation (§6) — NOT truth-tracking. Every file must be non-empty,
        under the size cap, and re-openable by the library matching its extension. Returns
        ``{ok, error}``; on failure ``error`` is a clean, model-feedable line."""
        if not output_files:
            return {"ok": False, "error": "No document was written to /workspace/output/."}
        cap = max(1, settings.agent_sandbox_output_max_mb) * 1024 * 1024
        for p in output_files:
            try:
                size = p.stat().st_size
            except OSError as exc:
                return {"ok": False, "error": f"Output file '{p.name}' is unreadable: {exc}"}
            if size == 0:
                return {"ok": False, "error": f"Output file '{p.name}' is empty."}
            if size > cap:
                return {"ok": False, "error": (
                    f"Output file '{p.name}' is {size // (1024*1024)} MB, over the "
                    f"{settings.agent_sandbox_output_max_mb} MB limit.")}
            err = _reopen_error(p)
            if err:
                return {"ok": False, "error": f"Output file '{p.name}' did not re-open: {err}"}
        return {"ok": True, "error": ""}


def _reopen_error(p: Path) -> str:
    """Try to re-open a produced file with the library that should have written it. Returns
    '' on success or a short error string. If the matching library isn't importable in the
    backend, the re-open check is skipped (not failed) — the non-empty + size checks still
    apply — so produce keeps working on a deployment that didn't install it. Unknown
    extensions skip the re-open check entirely."""
    ext = p.suffix.lower()
    try:
        if ext == ".xlsx":
            try:
                import openpyxl
            except ImportError:
                logger.warning("openpyxl not installed in backend — skipping xlsx re-open check")
                return ""
            wb = openpyxl.load_workbook(p, read_only=True)
            wb.close()
        elif ext == ".docx":
            try:
                import docx
            except ImportError:
                logger.warning("python-docx not installed in backend — skipping docx re-open check")
                return ""
            docx.Document(str(p))
        elif ext == ".pptx":
            try:
                import pptx
            except ImportError:
                logger.warning("python-pptx not installed in backend — skipping pptx re-open check")
                return ""
            pptx.Presentation(str(p))
        elif ext == ".pdf":
            with open(p, "rb") as fh:
                if fh.read(5) != b"%PDF-":
                    return "not a valid PDF (bad header)"
        # csv/html/md/txt/png: non-empty + size checks suffice.
        return ""
    except Exception as exc:  # noqa: BLE001 — any open failure is a validation failure
        return str(exc)[:300]


# ── Module-level singleton + registration ────────────────────
document_agent = DocumentAgent()

register(
    SubAgentSpec(
        capability=Capability.PRODUCE,
        name=document_agent.name,
        handler=document_agent,
        description="Generates a user-deliverable document via a sandboxed model-written script.",
    )
)
