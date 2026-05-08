"""
Deep Query — Semantic Chunker

Splits extracted document content into semantically coherent chunks
for embedding and retrieval.

Strategy:
- RecursiveCharacterTextSplitter as base
- Split on paragraph → sentence → character boundaries
- Target 400–600 tokens (~2000–3000 characters)
- Overlap 50–80 tokens (~250–400 characters)
- Tables are atomic (never split mid-table)
- Heading context is prepended to each chunk
- Images are their own standalone chunks
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.config import settings
from ingestion.parser_pdf import ExtractedBlock

logger = logging.getLogger(__name__)

# Approximate chars per token for English text
CHARS_PER_TOKEN = 4


@dataclass
class DocumentChunk:
    """A semantic chunk ready for embedding and storage."""

    chunk_id: str = ""
    text: str = ""
    chunk_type: str = "text"  # "text", "image", "mixed", "table"
    page_number: int = 0
    chunk_index: int = 0
    heading_context: str = ""
    image_bytes: Optional[bytes] = None
    image_format: str = "png"
    caption: str = ""
    is_scanned_page: bool = False
    ocr_text: str = ""  # OCR output for BM25 only (not for embedding)
    ocr_confidence: float = 0.0
    ocr_usable: bool = False
    metadata: dict = field(default_factory=dict)


class SemanticChunker:
    """Split extracted blocks into semantic chunks for embedding."""

    def __init__(
        self,
        chunk_size_tokens: Optional[int] = None,
        chunk_overlap_tokens: Optional[int] = None,
    ):
        size_tokens = chunk_size_tokens or settings.chunk_size_tokens
        overlap_tokens = chunk_overlap_tokens or settings.chunk_overlap_tokens

        self.chunk_size = size_tokens * CHARS_PER_TOKEN
        self.chunk_overlap = overlap_tokens * CHARS_PER_TOKEN

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=[
                "\n\n\n",   # Triple newline (section break)
                "\n\n",     # Double newline (paragraph break)
                "\n",       # Single newline
                ". ",       # Sentence boundary
                "? ",       # Question
                "! ",       # Exclamation
                "; ",       # Semicolon
                ", ",       # Comma
                " ",        # Word boundary
                "",         # Character (last resort)
            ],
            length_function=len,
            is_separator_regex=False,
        )

    def chunk_blocks(
        self,
        blocks: List[ExtractedBlock],
        document_id: str,
    ) -> List[DocumentChunk]:
        """Convert extracted blocks into semantic chunks.

        Args:
            blocks: List of ExtractedBlock from document parsers.
            document_id: UUID of the source document.

        Returns:
            List of DocumentChunk ready for embedding.
        """
        chunks: List[DocumentChunk] = []
        chunk_index = 0

        for block in blocks:
            if block.block_type == "image":
                # Images are standalone chunks — never split
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{document_id}_chunk_{chunk_index}",
                        text=block.caption or "",
                        chunk_type="image",
                        page_number=block.page_number,
                        chunk_index=chunk_index,
                        heading_context=block.heading_context,
                        image_bytes=block.image_bytes,
                        image_format=block.image_format,
                        caption=block.caption,
                        is_scanned_page=block.is_scanned_page,
                        metadata=block.metadata,
                    )
                )
                chunk_index += 1

            elif block.block_type == "mixed":
                # Mixed content (caption + image) — keep together
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{document_id}_chunk_{chunk_index}",
                        text=block.text,
                        chunk_type="mixed",
                        page_number=block.page_number,
                        chunk_index=chunk_index,
                        heading_context=block.heading_context,
                        image_bytes=block.image_bytes,
                        image_format=block.image_format,
                        caption=block.caption,
                        metadata=block.metadata,
                    )
                )
                chunk_index += 1

            elif block.block_type == "table":
                # Tables are atomic — don't split mid-table
                table_text = block.text
                if block.heading_context:
                    table_text = f"[{block.heading_context}]\n\n{table_text}"

                if len(table_text) <= self.chunk_size * 1.5:
                    # Table fits in one chunk
                    chunks.append(
                        DocumentChunk(
                            chunk_id=f"{document_id}_chunk_{chunk_index}",
                            text=table_text,
                            chunk_type="table",
                            page_number=block.page_number,
                            chunk_index=chunk_index,
                            heading_context=block.heading_context,
                            metadata={**block.metadata, "is_table": True},
                        )
                    )
                    chunk_index += 1
                else:
                    # Very large table — split but preserve row boundaries
                    rows = table_text.split("\n")
                    current_chunk = ""
                    for row in rows:
                        if len(current_chunk) + len(row) + 1 > self.chunk_size:
                            if current_chunk:
                                chunks.append(
                                    DocumentChunk(
                                        chunk_id=f"{document_id}_chunk_{chunk_index}",
                                        text=current_chunk.strip(),
                                        chunk_type="table",
                                        page_number=block.page_number,
                                        chunk_index=chunk_index,
                                        heading_context=block.heading_context,
                                        metadata={**block.metadata, "is_table": True},
                                    )
                                )
                                chunk_index += 1
                            current_chunk = row + "\n"
                        else:
                            current_chunk += row + "\n"

                    if current_chunk.strip():
                        chunks.append(
                            DocumentChunk(
                                chunk_id=f"{document_id}_chunk_{chunk_index}",
                                text=current_chunk.strip(),
                                chunk_type="table",
                                page_number=block.page_number,
                                chunk_index=chunk_index,
                                heading_context=block.heading_context,
                                metadata={**block.metadata, "is_table": True},
                            )
                        )
                        chunk_index += 1

            else:
                # Regular text — use RecursiveCharacterTextSplitter
                text = block.text
                if not text.strip():
                    continue

                # Prepend heading context
                if block.heading_context:
                    text = f"[{block.heading_context}]\n\n{text}"

                split_texts = self.text_splitter.split_text(text)

                for split_text in split_texts:
                    chunks.append(
                        DocumentChunk(
                            chunk_id=f"{document_id}_chunk_{chunk_index}",
                            text=split_text,
                            chunk_type="text",
                            page_number=block.page_number,
                            chunk_index=chunk_index,
                            heading_context=block.heading_context,
                            metadata=block.metadata,
                        )
                    )
                    chunk_index += 1

        logger.info(
            f"Chunked document {document_id}: {len(blocks)} blocks → {len(chunks)} chunks"
        )
        return chunks
