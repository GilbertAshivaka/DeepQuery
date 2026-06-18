"""
Deep Query — Ingestion Pipeline Orchestrator

Coordinates the full ingestion flow:
1. Parse document (PDF / DOCX / HTML)
2. Chunk extracted content
3. Run OCR on scanned pages (for BM25 only)
4. Generate embeddings (Gemini Embedding 2)
5. Extract entities & relationships (Llama 3 → Neo4j)
6. Generate metadata (Llama 3 → summary, tags, category)
7. Store in ChromaDB + update SQLite metadata
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from core.config import settings
from core.constants import DocumentType, JobStatus
from ingestion.chunker import DocumentChunk, SemanticChunker
from ingestion.ocr_module import OCRModule
from ingestion.parser_docx import DOCXParser
from ingestion.parser_html import HTMLParser
from ingestion.parser_pdf import ExtractedBlock, PDFParser

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Orchestrates the complete document ingestion process."""

    def __init__(self):
        self.pdf_parser = PDFParser()
        self.docx_parser = DOCXParser()
        self.html_parser = HTMLParser()
        self.chunker = SemanticChunker()
        self.ocr = OCRModule()

    def run(self, document_id: str, job_id: str) -> dict:
        """Run the full ingestion pipeline for a document.

        Args:
            document_id: UUID of the Document record.
            job_id: UUID of the IngestionJob record.

        Returns:
            dict with pipeline results and statistics.
        """
        from core.database import SessionLocal
        from models.database import Document, IngestionJob

        db = SessionLocal()
        try:
            # Load document metadata
            doc = db.query(Document).filter(Document.id == document_id).first()
            job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()

            if not doc or not job:
                raise ValueError(f"Document {document_id} or Job {job_id} not found.")

            # Update job status
            job.status = JobStatus.PROCESSING
            job.started_at = datetime.now(timezone.utc)
            db.commit()

            file_path = settings.document_store_dir / doc.stored_filename
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            # ── Stage 1: Parse ────────────────────────────────
            logger.info(f"[{document_id}] Stage 1: Parsing {doc.file_extension}")
            blocks = self._parse_document(file_path, doc.file_extension)

            if doc.file_extension == ".pdf":
                doc.page_count = self.pdf_parser.get_page_count(file_path)

            # ── Stage 2: Chunk ────────────────────────────────
            logger.info(f"[{document_id}] Stage 2: Chunking {len(blocks)} blocks")
            chunks = self.chunker.chunk_blocks(blocks, document_id)

            # ── Stage 3: OCR for scanned pages (BM25 only) ───
            logger.info(f"[{document_id}] Stage 3: OCR for scanned pages")
            self._run_ocr_for_bm25(chunks)

            # ── Stage 4a: Generate embeddings ─────────────────
            logger.info(f"[{document_id}] Stage 4a: Generating embeddings")
            embeddings = self._generate_embeddings(chunks)

            # ── Stage 4b: Extract entities & relationships ────
            logger.info(f"[{document_id}] Stage 4b: Entity extraction")
            entity_results = self._extract_entities(chunks, document_id)

            # ── Stage 4c: Generate metadata ───────────────────
            logger.info(f"[{document_id}] Stage 4c: Metadata generation")
            metadata_results = self._generate_metadata(chunks)

            # ── Stage 5: Store in ChromaDB ────────────────────
            logger.info(f"[{document_id}] Stage 5: Storing in ChromaDB")
            self._store_in_vectordb(
                chunks, embeddings, metadata_results, doc
            )

            # ── Stage 6: Store entities in Neo4j ──────────────
            logger.info(f"[{document_id}] Stage 6: Storing in Neo4j")
            self._store_in_graph(entity_results, document_id)

            # ── Update document record ────────────────────────
            doc.chunk_count = len(chunks)
            if metadata_results:
                # Use first chunk's metadata as document-level metadata
                first_meta = metadata_results[0] if metadata_results else {}
                doc.summary = first_meta.get("summary", "")
                doc.topic_tags = json.dumps(
                    self._aggregate_tags(metadata_results)
                )
                doc.category = first_meta.get("category", "")
                doc.category_confidence = str(
                    first_meta.get("category_confidence", "")
                )

                # Map category to document_type enum
                category = self._most_common_category(metadata_results)
                try:
                    doc.document_type = DocumentType(category)
                except ValueError:
                    doc.document_type = DocumentType.OTHER

            # Mark job complete
            job.status = JobStatus.COMPLETE
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

            result = {
                "document_id": document_id,
                "blocks_extracted": len(blocks),
                "chunks_created": len(chunks),
                "embeddings_generated": len(embeddings),
                "entities_extracted": len(entity_results),
                "status": "complete",
            }
            logger.info(f"[{document_id}] Ingestion complete: {result}")
            return result

        except Exception as e:
            logger.error(f"[{document_id}] Ingestion failed: {e}", exc_info=True)
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
            raise

        finally:
            db.close()

    def _parse_document(
        self, file_path: Path, extension: str
    ) -> List[ExtractedBlock]:
        """Route to the correct parser based on file extension."""
        ext = extension.lower()
        if ext == ".pdf":
            return self.pdf_parser.parse(file_path)
        elif ext == ".docx":
            return self.docx_parser.parse(file_path)
        elif ext in (".html", ".htm"):
            return self.html_parser.parse(file_path)
        else:
            raise ValueError(f"Unsupported file extension: {ext}")

    def _run_ocr_for_bm25(self, chunks: List[DocumentChunk]) -> None:
        """Run OCR on scanned page images to produce text for BM25 index.

        This text is ONLY used for BM25 sparse retrieval.
        It is never sent to the embedding API.
        """
        for chunk in chunks:
            if chunk.is_scanned_page and chunk.image_bytes:
                result = self.ocr.process_image(
                    chunk.image_bytes, chunk.page_number
                )
                chunk.ocr_text = result.text
                chunk.ocr_confidence = result.confidence
                chunk.ocr_usable = result.is_usable

    def _generate_embeddings(
        self, chunks: List[DocumentChunk]
    ) -> List[Optional[List[float]]]:
        """Generate embeddings for all chunks using Gemini Embedding 2."""
        try:
            from embeddings.gemini_embedder import gemini_embedder

            return gemini_embedder.embed_chunks(chunks)
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return [None] * len(chunks)

    def _extract_entities(
        self, chunks: List[DocumentChunk], document_id: str
    ) -> List[dict]:
        """Extract entities and relationships from text chunks."""
        try:
            from llm.groq_client import groq_client

            results = []
            for chunk in chunks:
                # Use text_for_index so scanned pages (OCR text) also feed the graph.
                text = chunk.text_for_index
                if text.strip():
                    extraction = groq_client.extract_entities(text)
                    if extraction:
                        extraction["source_chunk_id"] = chunk.chunk_id
                        extraction["document_id"] = document_id
                        results.append(extraction)
            return results
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return []

    def _generate_metadata(
        self, chunks: List[DocumentChunk]
    ) -> List[dict]:
        """Generate metadata (summary, tags, category) for each chunk."""
        try:
            from llm.groq_client import groq_client

            results = []
            for chunk in chunks:
                # Use text_for_index so scanned pages (OCR text) get summary/tags.
                text = chunk.text_for_index
                if text.strip():
                    meta = groq_client.generate_metadata(text)
                    results.append(meta or {})
                else:
                    results.append({})
            return results
        except Exception as e:
            logger.error(f"Metadata generation failed: {e}")
            return [{}] * len(chunks)

    def _store_in_vectordb(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[Optional[List[float]]],
        metadata_results: List[dict],
        doc,
    ) -> None:
        """Store chunk embeddings and metadata in ChromaDB."""
        try:
            from vectorstore.chroma_store import chroma_store

            chroma_store.upsert_chunks(
                chunks=chunks,
                embeddings=embeddings,
                metadata_list=metadata_results,
                collection_name=doc.collection,
                document=doc,
            )
        except Exception as e:
            logger.error(f"ChromaDB storage failed: {e}")

    def _store_in_graph(
        self, entity_results: List[dict], document_id: str
    ) -> None:
        """Store extracted entities and relationships in Neo4j."""
        try:
            from knowledge_graph.neo4j_client import neo4j_client

            for result in entity_results:
                entities = result.get("entities", [])
                relationships = result.get("relationships", [])
                neo4j_client.upsert_entities(entities, document_id)
                neo4j_client.upsert_relationships(relationships, document_id)
        except Exception as e:
            logger.error(f"Neo4j storage failed: {e}")

    def _aggregate_tags(self, metadata_results: List[dict]) -> List[str]:
        """Aggregate unique topic tags across all chunks."""
        all_tags = set()
        for meta in metadata_results:
            tags = meta.get("topic_tags", [])
            if isinstance(tags, list):
                all_tags.update(tags)
        return sorted(all_tags)[:20]  # Cap at 20 tags per document

    def _most_common_category(self, metadata_results: List[dict]) -> str:
        """Pick the most frequently assigned category across all chunks."""
        from collections import Counter
        categories = [
            meta.get("category", "other")
            for meta in metadata_results
            if meta.get("category")
        ]
        if not categories:
            return "other"
        return Counter(categories).most_common(1)[0][0]
