"""
Deep Query — Document text extraction for the Agent Layer

Re-parses a document's *extracted* text on demand (per the agreed approach — not
reconstructed from chunks), reusing the ingestion parsers. Used for:
- whole corpus documents (when a query is document-centric and chunks aren't enough)
- user-attached documents in a query

Images are detected/kept by the parsers but not fed to the text generation model yet
(that arrives with the multimodal/Gemini path); they are stored as attachments.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Char budget for a whole document fed into context (keeps the model's context safe;
# we hit context_length_exceeded earlier with an unbounded public payload).
WHOLE_DOC_MAX_CHARS = 12000

_DOC_EXTS = {".pdf", ".docx", ".html", ".htm"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def attachment_kind(extension: str) -> str:
    ext = (extension or "").lower()
    if ext in _IMAGE_EXTS:
        return "image"
    return "document"


def _parser_for(ext: str):
    ext = (ext or "").lower()
    if ext == ".pdf":
        from ingestion.parser_pdf import PDFParser
        return PDFParser()
    if ext == ".docx":
        from ingestion.parser_docx import DOCXParser
        return DOCXParser()
    if ext in (".html", ".htm"):
        from ingestion.parser_html import HTMLParser
        return HTMLParser()
    return None


def extract_text_from_file(path: str | Path, extension: str, *, max_chars: int = WHOLE_DOC_MAX_CHARS) -> str:
    """Parse a file to plain text by concatenating extracted blocks in page order.
    Returns "" if the type is unsupported or parsing fails (callers degrade gracefully)."""
    p = Path(path)
    if not p.exists():
        logger.warning("extract_text_from_file: missing file %s", p)
        return ""
    parser = _parser_for(extension)
    if parser is None:
        return ""
    try:
        blocks = parser.parse(p)
    except Exception as exc:
        logger.warning("Parse failed for %s: %s", p, exc)
        return ""
    ordered = sorted(blocks, key=lambda b: getattr(b, "page_number", 0) or 0)
    text = "\n\n".join(b.text for b in ordered if getattr(b, "text", "").strip())
    if len(text) > max_chars:
        text = text[:max_chars] + " …[truncated]"
    return text


def extract_document_text(db, document_id: str, *, max_chars: int = WHOLE_DOC_MAX_CHARS) -> tuple[str, str]:
    """Re-parse a corpus document's original file to its full extracted text.
    Returns (title, text); ("","") if not found/parseable."""
    from core.config import settings
    from models.database import Document

    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        return ("", "")
    path = Path(settings.document_store_path) / doc.stored_filename
    text = extract_text_from_file(path, doc.file_extension, max_chars=max_chars)
    return (doc.original_filename or document_id, text)
