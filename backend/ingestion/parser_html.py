"""
Deep Query — HTML Parser (BeautifulSoup)

Strips boilerplate and extracts main content body from HTML documents.
"""

import logging
from pathlib import Path
from typing import List

from bs4 import BeautifulSoup, Tag

from ingestion.parser_pdf import ExtractedBlock

logger = logging.getLogger(__name__)

# Tags to strip from content (navigation, boilerplate, etc.)
STRIP_TAGS = {
    "nav", "header", "footer", "aside", "script", "style", "noscript",
    "iframe", "svg", "form", "button", "input", "select", "textarea",
}

# Heading tags
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class HTMLParser:
    """Parse HTML documents using BeautifulSoup.

    Extracts:
    - Main content body with boilerplate stripped
    - Preserves link context where meaningful
    - Respects heading hierarchy
    """

    def parse(self, file_path: Path) -> List[ExtractedBlock]:
        """Parse an HTML file and return extracted blocks."""
        html_content = file_path.read_text(encoding="utf-8", errors="replace")
        return self.parse_string(html_content, source_name=file_path.name)

    def parse_string(self, html_content: str, source_name: str = "") -> List[ExtractedBlock]:
        """Parse an HTML string and return extracted blocks."""
        soup = BeautifulSoup(html_content, "lxml")

        # Strip unwanted tags
        for tag_name in STRIP_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Try to find the main content area
        main_content = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", class_="content")
            or soup.find("div", id="content")
            or soup.find("body")
            or soup
        )

        blocks: List[ExtractedBlock] = []
        current_heading = ""

        for element in main_content.children:
            if not isinstance(element, Tag):
                # Bare text node
                text = element.strip()
                if text and len(text) > 20:
                    blocks.append(
                        ExtractedBlock(
                            text=text,
                            block_type="text",
                            page_number=0,
                            heading_context=current_heading,
                        )
                    )
                continue

            tag_name = element.name

            # Handle headings
            if tag_name in HEADING_TAGS:
                current_heading = element.get_text(strip=True)
                continue

            # Handle paragraphs and div blocks
            if tag_name in {"p", "div", "section", "blockquote", "li"}:
                text = self._extract_text_with_links(element)
                if text and len(text.strip()) > 10:
                    blocks.append(
                        ExtractedBlock(
                            text=text.strip(),
                            block_type="text",
                            page_number=0,
                            heading_context=current_heading,
                            metadata={"html_tag": tag_name},
                        )
                    )

            # Handle tables
            elif tag_name == "table":
                table_text = self._extract_table(element)
                if table_text and len(table_text) > 30:
                    blocks.append(
                        ExtractedBlock(
                            text=table_text,
                            block_type="table",
                            page_number=0,
                            heading_context=current_heading,
                            metadata={"is_table": True},
                        )
                    )

            # Handle lists
            elif tag_name in {"ul", "ol"}:
                items = element.find_all("li")
                list_text = "\n".join(
                    f"• {li.get_text(strip=True)}" for li in items if li.get_text(strip=True)
                )
                if list_text:
                    blocks.append(
                        ExtractedBlock(
                            text=list_text,
                            block_type="text",
                            page_number=0,
                            heading_context=current_heading,
                        )
                    )

            # Handle pre/code blocks
            elif tag_name in {"pre", "code"}:
                code_text = element.get_text()
                if code_text and len(code_text.strip()) > 10:
                    blocks.append(
                        ExtractedBlock(
                            text=code_text.strip(),
                            block_type="text",
                            page_number=0,
                            heading_context=current_heading,
                            metadata={"is_code": True},
                        )
                    )

        logger.info(f"Parsed HTML: {source_name} → {len(blocks)} blocks")
        return blocks

    def _extract_text_with_links(self, element: Tag) -> str:
        """Extract text while preserving meaningful link context.

        Links like 'click here' are stripped. Links with descriptive text
        like 'Department of Marine Biology' are preserved.
        """
        parts = []
        for child in element.descendants:
            if isinstance(child, str):
                parts.append(child)
            elif isinstance(child, Tag) and child.name == "a":
                link_text = child.get_text(strip=True)
                href = child.get("href", "")
                # Keep the link text if it's descriptive (not generic like 'click here')
                generic_patterns = {"click", "here", "more", "read", "link", "this"}
                if link_text and not any(p in link_text.lower() for p in generic_patterns):
                    parts.append(link_text)

        return " ".join(parts)

    def _extract_table(self, table_element: Tag) -> str:
        """Convert an HTML table to markdown-style text."""
        rows = []
        for tr in table_element.find_all("tr"):
            cells = []
            for td in tr.find_all(["td", "th"]):
                cells.append(td.get_text(strip=True))
            if cells:
                rows.append(" | ".join(cells))
        return "\n".join(rows)
