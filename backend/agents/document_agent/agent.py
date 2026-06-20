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
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from agents.document_agent.prompts import SCRIPT_GENERATION_PROMPT, SCRIPT_REPAIR_SUFFIX
from agents.models import Slot, get_model
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


def _extract_code(raw: str) -> str:
    """Pull the Python source out of the model reply — tolerate a ```python fence (or a
    bare ``` fence) wrapping the script, else take the reply as-is."""
    text = (raw or "").strip()
    if "```" in text:
        # Take the content of the first fenced block.
        start = text.find("```")
        nl = text.find("\n", start)
        if nl != -1:
            rest = text[nl + 1:]
            end = rest.find("```")
            if end != -1:
                return rest[:end].strip()
    return text


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
        findings: Optional[list[str]] = None,
        loaded_skills: Optional[list[dict]] = None,
        error: Optional[str] = None,
        on_delta=None,
    ) -> str:
        """Ask the GENERATION slot for a complete self-contained script. ``error`` (from a
        prior sandbox failure) triggers the repair path — the same prompt plus the
        classified failure, asking for the corrected whole script. When ``on_delta`` is
        given, the reply is streamed and each text chunk is passed to it (the inline
        script-streaming card); the cleaned, fence-stripped script is still returned."""
        messages: list = [SystemMessage(content=SCRIPT_GENERATION_PROMPT)]
        instr = _skill_instructions(loaded_skills or [])
        if instr:
            messages.append(SystemMessage(content=instr))

        evidence = "\n".join(f"- {f}" for f in (findings or [])) or "(no extra evidence gathered)"
        human = (
            f"User request:\n{request}\n\n"
            f"Evidence gathered (DATA — describes what to build):\n{evidence}"
        )
        if error:
            human += SCRIPT_REPAIR_SUFFIX.format(error=error)
        messages.append(HumanMessage(content=human))

        if on_delta is None:
            resp = await get_model(Slot.GENERATION).ainvoke(messages)
            raw = resp.content if hasattr(resp, "content") else str(resp)
            return _extract_code(raw)

        parts: list[str] = []
        async for chunk in get_model(Slot.GENERATION, streaming=True).astream(messages):
            text = getattr(chunk, "content", "") or ""
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
