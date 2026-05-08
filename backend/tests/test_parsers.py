"""
Deep Query — Unit Tests for Document Parsers
"""

import tempfile
from pathlib import Path

import pytest


class TestPDFParser:
    """Tests for the PDF parser module."""

    def test_parse_returns_blocks(self, tmp_path):
        """Parser should return a list of ExtractedBlock objects."""
        from ingestion.parser_pdf import PDFParser

        parser = PDFParser()
        # This will be tested with actual PDF files when available
        # For now, verify the class can be instantiated
        assert parser is not None
        assert parser.SCANNED_PAGE_TEXT_THRESHOLD == 30

    def test_get_page_count_requires_valid_file(self):
        """get_page_count should raise on non-existent file."""
        from ingestion.parser_pdf import PDFParser

        parser = PDFParser()
        with pytest.raises(Exception):
            parser.get_page_count(Path("/nonexistent/file.pdf"))


class TestDOCXParser:
    """Tests for the DOCX parser module."""

    def test_parser_instantiation(self):
        from ingestion.parser_docx import DOCXParser

        parser = DOCXParser()
        assert parser is not None


class TestHTMLParser:
    """Tests for the HTML parser module."""

    def test_parse_simple_html(self, tmp_path):
        from ingestion.parser_html import HTMLParser

        parser = HTMLParser()

        html_content = """
        <html>
        <body>
            <nav>Navigation to ignore</nav>
            <main>
                <h1>Test Heading</h1>
                <p>This is a test paragraph with enough content to pass the minimum length filter.</p>
                <p>Another paragraph of meaningful text for the semantic chunker to process.</p>
            </main>
            <footer>Footer to ignore</footer>
        </body>
        </html>
        """

        html_file = tmp_path / "test.html"
        html_file.write_text(html_content)

        blocks = parser.parse(html_file)
        assert len(blocks) > 0

        # Navigation and footer should be stripped
        all_text = " ".join(b.text for b in blocks)
        assert "Navigation to ignore" not in all_text
        assert "Footer to ignore" not in all_text

    def test_parse_string(self):
        from ingestion.parser_html import HTMLParser

        parser = HTMLParser()
        blocks = parser.parse_string(
            "<html><body><p>Test content for HTML parser validation here.</p></body></html>",
            source_name="test",
        )
        assert isinstance(blocks, list)


class TestSemanticChunker:
    """Tests for the semantic chunking module."""

    def test_chunk_text_blocks(self):
        from ingestion.chunker import SemanticChunker
        from ingestion.parser_pdf import ExtractedBlock

        chunker = SemanticChunker(chunk_size_tokens=100, chunk_overlap_tokens=20)

        blocks = [
            ExtractedBlock(
                text="This is a test paragraph. " * 50,
                block_type="text",
                page_number=1,
                heading_context="Test Section",
            ),
        ]

        chunks = chunker.chunk_blocks(blocks, "test-doc-id")
        assert len(chunks) > 0
        assert chunks[0].heading_context == "Test Section"
        assert chunks[0].chunk_type == "text"

    def test_image_blocks_not_split(self):
        from ingestion.chunker import SemanticChunker
        from ingestion.parser_pdf import ExtractedBlock

        chunker = SemanticChunker()

        blocks = [
            ExtractedBlock(
                text="",
                block_type="image",
                page_number=1,
                image_bytes=b"fake image data",
                image_format="png",
                caption="Figure 1: Test diagram",
            ),
        ]

        chunks = chunker.chunk_blocks(blocks, "test-doc-id")
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "image"
        assert chunks[0].image_bytes == b"fake image data"

    def test_table_blocks_atomic(self):
        from ingestion.chunker import SemanticChunker
        from ingestion.parser_pdf import ExtractedBlock

        chunker = SemanticChunker(chunk_size_tokens=500)

        table_text = "Col1 | Col2 | Col3\nVal1 | Val2 | Val3\nVal4 | Val5 | Val6"
        blocks = [
            ExtractedBlock(
                text=table_text,
                block_type="table",
                page_number=2,
                metadata={"is_table": True},
            ),
        ]

        chunks = chunker.chunk_blocks(blocks, "test-doc-id")
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "table"


class TestOCRModule:
    """Tests for the OCR module."""

    def test_ocr_module_instantiation(self):
        from ingestion.ocr_module import OCRModule

        ocr = OCRModule()
        assert ocr.lang == "eng"
        assert ocr.MIN_CONFIDENCE_THRESHOLD == 40.0
