"""
Deep Query — ChromaDB Vector Store

Manages collections, upserts, and queries against ChromaDB.
Four RBAC collections: academic, departmental, administrative, management.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import chromadb

from core.config import settings
from core.constants import Collection
from embeddings.identity import (
    active_embedding_identity,
    describe,
    extract_identity,
    identity_matches,
)

logger = logging.getLogger(__name__)


class ChromaIdentityError(RuntimeError):
    """Raised when a collection's recorded embedding identity does not match the
    active one — i.e. the configured embedder cannot safely query this collection's
    vector space. Switching embedders requires a re-index (see
    MODEL_VENDOR_PICKING_PLAN.md §7), not a config flip."""


class ChromaStore:
    """ChromaDB wrapper for vector storage and retrieval."""

    def __init__(self):
        self._client = None
        self._collections: Dict[str, Any] = {}
        self._active_version: str = ""        # active physical collection suffix
        self._version_stamp: Any = None       # config version the above was read at

    @property
    def client(self):
        if self._client is None:
            try:
                self._client = chromadb.HttpClient(
                    host=settings.chroma_host,
                    port=settings.chroma_port,
                )
                logger.info(f"Connected to ChromaDB at {settings.chroma_host}:{settings.chroma_port}")
            except Exception:
                # Fallback to persistent local client for development
                logger.info("Falling back to local persistent ChromaDB")
                self._client = chromadb.PersistentClient(
                    path=settings.chroma_persist_directory
                )
        return self._client

    def _active_collection_version(self) -> str:
        """The active physical-collection suffix. Read from the active embedding config
        (``collection_version`` param), set atomically by a completed re-index; falls
        back to the env default. Cached against the config version — when that bumps and
        the suffix changes, cached collection handles are dropped so the next access
        resolves to the new physical collections."""
        try:
            from agents.models import config_store

            stamp = config_store.current_version()
            if self._version_stamp != stamp:
                ver = ""
                row = config_store.resolve_role("embedding")
                if row:
                    ver = str((row.get("params") or {}).get("collection_version") or "")
                ver = (ver or settings.embedding_collection_version or "").strip()
                if ver != self._active_version:
                    self._collections.clear()
                self._active_version = ver
                self._version_stamp = stamp
            return self._active_version
        except Exception:
            return (settings.embedding_collection_version or "").strip()

    def _physical_name(self, logical_name: str) -> str:
        """Resolve a logical collection name (the RBAC names — academic, …) to its
        physical name. Empty version = bare logical name (current/legacy layout); a
        re-index migration sets a version suffix (e.g. ``academic__v2``) and flips the
        active pointer once verified."""
        version = self._active_collection_version()
        return f"{logical_name}__{version}" if version else logical_name

    def get_physical_collection(self, physical_name: str, identity: Optional[Dict] = None):
        """Direct handle to a collection by exact physical name — no logical→physical
        resolution and no identity assertion. Used by the re-index job to write shadow
        collections before they become active. Records the given embedding identity."""
        meta = {"hnsw:space": "cosine"}
        if identity:
            meta.update(identity)
        return self.client.get_or_create_collection(name=physical_name, metadata=meta)

    def _verify_identity(self, collection, active: dict) -> None:
        """Assert the collection's recorded embedding identity matches the active one.

        - No recorded identity → legacy collection (predates the guard); backfill the
          active identity (all legacy collections were built with the historical
          embedder) so future switches are caught.
        - Recorded but mismatched → hard error (wrong vector space).
        """
        if not settings.embedding_identity_guard:
            return
        recorded = extract_identity(getattr(collection, "metadata", None))
        if recorded is None:
            try:
                merged = dict(getattr(collection, "metadata", None) or {})
                merged.update(active)
                collection.modify(metadata=merged)
                logger.info(
                    "Backfilled embedding identity %s onto collection '%s'",
                    describe(active),
                    collection.name,
                )
            except Exception as e:
                logger.warning(
                    "Could not backfill embedding identity on '%s': %s",
                    collection.name,
                    e,
                )
            return
        if not identity_matches(recorded, active):
            raise ChromaIdentityError(
                f"Embedding identity mismatch on collection '{collection.name}': "
                f"recorded {describe(recorded)} != active {describe(active)}. "
                f"Switching embedders requires a re-index "
                f"(see MODEL_VENDOR_PICKING_PLAN.md §7)."
            )

    def get_collection(self, name: str):
        """Get or create a ChromaDB collection (by logical RBAC name), verifying its
        embedding identity matches the active embedder."""
        physical = self._physical_name(name)
        if physical not in self._collections:
            active = active_embedding_identity()
            collection = self.client.get_or_create_collection(
                name=physical,
                metadata={"hnsw:space": "cosine", **active},
            )
            self._verify_identity(collection, active)
            self._collections[physical] = collection
        return self._collections[physical]

    def ensure_collections(self) -> None:
        """Ensure all four RBAC collections exist."""
        for collection in Collection:
            self.get_collection(collection.value)
            logger.info(f"Ensured collection: {collection.value}")

    def upsert_chunks(
        self,
        chunks,
        embeddings: List[Optional[List[float]]],
        metadata_list: List[dict],
        collection_name: str,
        document,
    ) -> int:
        """Upsert chunk embeddings and metadata into a ChromaDB collection.

        Args:
            chunks: List of DocumentChunk objects.
            embeddings: Corresponding embedding vectors.
            metadata_list: LLM-generated metadata per chunk.
            collection_name: Target collection (academic, departmental, etc.).
            document: Document ORM object for source metadata.

        Returns:
            Number of successfully upserted chunks.
        """
        collection = self.get_collection(collection_name)

        ids = []
        valid_embeddings = []
        documents = []
        metadatas = []

        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            if emb is None:
                continue

            meta = metadata_list[i] if i < len(metadata_list) else {}

            chunk_metadata = {
                "source_document_id": document.id,
                "original_filename": document.original_filename,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "document_type": document.document_type.value if hasattr(document.document_type, 'value') else str(document.document_type),
                "access_role": collection_name,
                "summary": meta.get("summary", ""),
                "topic_tags": json.dumps(meta.get("topic_tags", [])),
                "upload_timestamp": document.upload_timestamp.isoformat() if document.upload_timestamp else "",
                "has_image": chunk.image_bytes is not None,
                "ocr_flag": chunk.ocr_usable,
                "uploader_id": document.uploader_id,
                "heading_context": chunk.heading_context,
            }

            ids.append(chunk.chunk_id)
            valid_embeddings.append(emb)
            # Store the full text for retrieval display + text-based downstream
            # stages (Skill Sync reads this). Prefers native text, falls back to
            # usable OCR text for scanned pages (embedding stays image-native).
            documents.append(chunk.text_for_index or chunk.caption or "[Image content]")
            metadatas.append(chunk_metadata)

        if not ids:
            logger.warning(f"No valid embeddings to upsert for document {document.id}")
            return 0

        # Upsert in batches of 100
        BATCH_SIZE = 100
        total_upserted = 0
        for batch_start in range(0, len(ids), BATCH_SIZE):
            batch_end = batch_start + BATCH_SIZE
            try:
                collection.upsert(
                    ids=ids[batch_start:batch_end],
                    embeddings=valid_embeddings[batch_start:batch_end],
                    documents=documents[batch_start:batch_end],
                    metadatas=metadatas[batch_start:batch_end],
                )
                total_upserted += len(ids[batch_start:batch_end])
            except Exception as e:
                logger.error(f"ChromaDB upsert batch failed: {e}")

        logger.info(f"Upserted {total_upserted} chunks into '{collection_name}'")
        return total_upserted

    def query_collection(
        self,
        collection_name: str,
        query_embedding: List[float],
        n_results: int = 20,
        where_filter: Optional[Dict] = None,
    ) -> Dict:
        """Query a ChromaDB collection by embedding vector.

        Args:
            collection_name: Collection to search.
            query_embedding: Query vector.
            n_results: Number of results to return.
            where_filter: Optional metadata filter dict.

        Returns:
            ChromaDB query result dict.
        """
        collection = self.get_collection(collection_name)

        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where_filter:
            kwargs["where"] = where_filter

        return collection.query(**kwargs)

    def query_multiple_collections(
        self,
        collection_names: List[str],
        query_embedding: List[float],
        n_results: int = 20,
        where_filter: Optional[Dict] = None,
    ) -> List[Dict]:
        """Query multiple collections and merge results.

        Args:
            collection_names: List of collections to search.
            query_embedding: Query vector.
            n_results: Results per collection.
            where_filter: Optional metadata filter.

        Returns:
            Merged list of result dicts with distances.
        """
        all_results = []

        for name in collection_names:
            try:
                result = self.query_collection(
                    name, query_embedding, n_results, where_filter
                )

                # Flatten results
                if result and result.get("ids"):
                    for i in range(len(result["ids"][0])):
                        all_results.append({
                            "id": result["ids"][0][i],
                            "document": result["documents"][0][i] if result.get("documents") else "",
                            "metadata": result["metadatas"][0][i] if result.get("metadatas") else {},
                            "distance": result["distances"][0][i] if result.get("distances") else 1.0,
                            "collection": name,
                        })
            except Exception as e:
                logger.error(f"Query failed for collection '{name}': {e}")

        # Sort by distance (lower is better for cosine)
        all_results.sort(key=lambda x: x["distance"])
        return all_results[:n_results]

    def delete_document_chunks(
        self, document_id: str, collection_name: str
    ) -> None:
        """Remove all chunks for a document from a collection."""
        collection = self.get_collection(collection_name)
        try:
            collection.delete(
                where={"source_document_id": document_id}
            )
            logger.info(f"Deleted chunks for document {document_id} from '{collection_name}'")
        except Exception as e:
            logger.error(f"Failed to delete chunks: {e}")

    def get_all_chunk_texts(
        self, collection_names: List[str]
    ) -> List[Dict[str, str]]:
        """Get all chunk texts from specified collections for BM25 index building.

        Returns list of dicts with 'id', 'text', 'collection'.
        """
        all_chunks = []
        for name in collection_names:
            try:
                collection = self.get_collection(name)
                result = collection.get(include=["documents", "metadatas"])
                if result and result.get("ids"):
                    for i, chunk_id in enumerate(result["ids"]):
                        text = result["documents"][i] if result.get("documents") else ""
                        meta = result["metadatas"][i] if result.get("metadatas") else {}
                        # Include OCR text for scanned pages
                        all_chunks.append({
                            "id": chunk_id,
                            "text": text,
                            "collection": name,
                            "metadata": meta,
                        })
            except Exception as e:
                logger.error(f"Failed to get chunks from '{name}': {e}")

        return all_chunks


# ── Module-level singleton ───────────────────────────────────
chroma_store = ChromaStore()
