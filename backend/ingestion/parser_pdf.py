"""
Deep Query — PDF Parser (PyMuPDF)

Extracts text, images, and tables from PDF documents.
Handles both text-layer PDFs and scanned pages.
"""

import base64
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class ExtractedBlock:
    """A block of content extracted from a document."""

    text: str = ""
    block_type: str = "text"  # "text", "image", "table", "mixed"
    page_number: int = 0
    image_bytes: Optional[bytes] = None
    image_format: str = "png"
    caption: str = ""
    heading_context: str = ""
    is_scanned_page: bool = False
    metadata: dict = field(default_factory=dict)


class PDFParser:
    """Parse PDF documents using PyMuPDF (fitz).

    Extracts:
    - Text blocks with page numbers and heading context
    - Images as separate assets for multimodal embedding
    - Tables (simple → structured text, complex → image)
    - Detects scanned pages (no text layer)
    """

    # Minimum characters on a page to consider it "has text"
    SCANNED_PAGE_TEXT_THRESHOLD = 30

    def parse(self, file_path: Path) -> List[ExtractedBlock]:
        """Parse a PDF file and return extracted blocks."""
        doc = fitz.open(str(file_path))
        blocks: List[ExtractedBlock] = []
        current_heading = ""

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_number = page_num + 1

            # ── Extract text ──────────────────────────────────
            page_text = page.get_text("text").strip()
            is_scanned = len(page_text) < self.SCANNED_PAGE_TEXT_THRESHOLD

            if is_scanned:
                # Scanned page: store the page image for direct embedding
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("png")
                blocks.append(
                    ExtractedBlock(
                        text="",
                        block_type="image",
                        page_number=page_number,
                        image_bytes=img_bytes,
                        image_format="png",
                        is_scanned_page=True,
                        heading_context=current_heading,
                        metadata={"source": "scanned_page"},
                    )
                )
            else:
                # Text page: extract structured blocks
                text_dict = page.get_text("dict")
                page_blocks = self._extract_text_blocks(
                    text_dict, page_number, current_heading
                )
                blocks.extend(page_blocks)

                # Update heading context from this page
                heading = self._detect_heading(text_dict)
                if heading:
                    current_heading = heading

            # ── Extract images ────────────────────────────────
            image_blocks = self._extract_images(page, page_number, current_heading)
            blocks.extend(image_blocks)

            # ── Extract tables ────────────────────────────────
            table_blocks = self._extract_tables(page, page_number, current_heading)
            blocks.extend(table_blocks)

        page_count = len(doc)
        doc.close()
        logger.info(f"Parsed PDF: {file_path.name} → {len(blocks)} blocks from {page_count} pages")
        return blocks

    def _extract_text_blocks(
        self, text_dict: dict, page_number: int, heading_context: str
    ) -> List[ExtractedBlock]:
        """Extract text blocks from a page dict preserving paragraph structure."""
        blocks = []
        page_text_parts = []

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # 0 = text block
                continue

            block_text_parts = []
            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                if line_text.strip():
                    block_text_parts.append(line_text.strip())

            if block_text_parts:
                page_text_parts.append(" ".join(block_text_parts))

        # Combine all text from the page into one block
        # (chunking will split it further downstream)
        if page_text_parts:
            combined_text = "\n\n".join(page_text_parts)
            blocks.append(
                ExtractedBlock(
                    text=combined_text,
                    block_type="text",
                    page_number=page_number,
                    heading_context=heading_context,
                )
            )

        return blocks

    def _detect_heading(self, text_dict: dict) -> str:
        """Detect the most prominent heading on a page by font size."""
        max_size = 0
        heading = ""

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0)
                    text = span.get("text", "").strip()
                    flags = span.get("flags", 0)
                    is_bold = flags & 2 ** 4  # Bold flag
                    if size > max_size and len(text) > 3 and (size > 14 or is_bold):
                        max_size = size
                        heading = text

        return heading

    def _extract_images(
        self, page: fitz.Page, page_number: int, heading_context: str
    ) -> List[ExtractedBlock]:
        """Extract embedded images from a page."""
        blocks = []
        image_list = page.get_images(full=True)

        for img_index, img in enumerate(image_list):
            xref = img[0]
            try:
                base_image = page.parent.extract_image(xref)
                if base_image is None:
                    continue

                img_bytes = base_image["image"]
                img_ext = base_image.get("ext", "png")

                # Skip very small images (likely icons/bullets)
                if len(img_bytes) < 5000:
                    continue

                # Try to find caption text near the image
                caption = self._find_nearby_caption(page, img_index)

                blocks.append(
                    ExtractedBlock(
                        text=caption,
                        block_type="mixed" if caption else "image",
                        page_number=page_number,
                        image_bytes=img_bytes,
                        image_format=img_ext,
                        caption=caption,
                        heading_context=heading_context,
                        metadata={"image_index": img_index},
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to extract image {xref} on page {page_number}: {e}")

        return blocks

    def _find_nearby_caption(self, page: fitz.Page, img_index: int) -> str:
        """Attempt to find figure caption text near an image."""
        text = page.get_text("text")
        lines = text.split("\n")
        for line in lines:
            lower = line.strip().lower()
            if lower.startswith(("figure", "fig.", "fig ", "table", "chart", "diagram")):
                return line.strip()
        return ""

    def _extract_tables(
        self, page: fitz.Page, page_number: int, heading_context: str
    ) -> List[ExtractedBlock]:
        """Extract tables from a page.

        Simple tables → structured text.
        Complex tables → page image crop for multimodal embedding.
        """
        blocks = []

        try:
            tables = page.find_tables()
            if not tables or len(tables.tables) == 0:
                return blocks

            for table in tables:
                try:
                    # Extract table as structured text
                    rows = table.extract()
                    if not rows:
                        continue

                    # Build a markdown-style table
                    text_rows = []
                    for row in rows:
                        cleaned = [str(cell).strip() if cell else "" for cell in row]
                        text_rows.append(" | ".join(cleaned))

                    table_text = "\n".join(text_rows)

                    if len(table_text) > 50:  # Skip trivially small tables
                        blocks.append(
                            ExtractedBlock(
                                text=table_text,
                                block_type="table",
                                page_number=page_number,
                                heading_context=heading_context,
                                metadata={"is_table": True},
                            )
                        )
                except Exception as e:
                    logger.warning(f"Failed to extract table on page {page_number}: {e}")

        except Exception as e:
            logger.debug(f"No table extraction support or error on page {page_number}: {e}")

        return blocks

    def get_page_count(self, file_path: Path) -> int:
        """Return the total number of pages in a PDF."""
        doc = fitz.open(str(file_path))
        count = len(doc)
        doc.close()
        return count
