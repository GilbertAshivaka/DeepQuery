"""
Deep Query — Document Management Endpoints (Admin only)

POST   /api/documents/upload
GET    /api/documents/
GET    /api/documents/{document_id}
DELETE /api/documents/{document_id}
GET    /api/documents/status/{job_id}
"""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from auth.dependencies import RoleRequired, get_current_user
from core.config import settings
from core.constants import SUPPORTED_EXTENSIONS, Collection, UserRole
from core.database import get_db
from models.database import Document, IngestionJob, User
from models.schemas import (
    DocumentListResponse,
    DocumentResponse,
    JobStatusResponse,
    UploadResponse,
)

router = APIRouter()


def _doc_to_response(doc: Document) -> DocumentResponse:
    """Convert a Document ORM object to a response schema."""
    tags = []
    if doc.topic_tags:
        try:
            tags = json.loads(doc.topic_tags)
        except (json.JSONDecodeError, TypeError):
            tags = []
    return DocumentResponse(
        id=doc.id,
        original_filename=doc.original_filename,
        file_extension=doc.file_extension,
        file_size_bytes=doc.file_size_bytes,
        document_type=doc.document_type.value if doc.document_type else None,
        collection=doc.collection,
        summary=doc.summary,
        topic_tags=tags,
        category=doc.category,
        page_count=doc.page_count,
        chunk_count=doc.chunk_count,
        uploader_id=doc.uploader_id,
        upload_timestamp=doc.upload_timestamp,
    )


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_document(
    file: UploadFile = File(...),
    collection: str = Form(default="academic"),
    user: User = Depends(RoleRequired([UserRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Upload a document and enqueue it for ingestion."""
    # Validate extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {SUPPORTED_EXTENSIONS}",
        )

    # Validate collection
    valid_collections = [c.value for c in Collection]
    if collection not in valid_collections:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid collection '{collection}'. Allowed: {valid_collections}",
        )

    # Save file to document_store
    stored_filename = f"{uuid.uuid4()}{ext}"
    store_path = settings.document_store_dir / stored_filename
    content = file.file.read()
    store_path.write_bytes(content)

    # Create Document record
    doc = Document(
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_extension=ext,
        file_size_bytes=len(content),
        collection=collection,
        uploader_id=user.id,
    )
    db.add(doc)
    db.flush()

    # Create IngestionJob
    job = IngestionJob(document_id=doc.id)
    db.add(job)
    db.commit()
    db.refresh(doc)
    db.refresh(job)

    # Enqueue Celery task
    try:
        from tasks.ingestion_task import run_ingestion_pipeline

        task = run_ingestion_pipeline.delay(doc.id, job.id)
        job.celery_task_id = task.id
        db.commit()
    except Exception:
        # If Celery is not running, the job stays PENDING for manual processing
        pass

    return UploadResponse(document_id=doc.id, job_id=job.id)


@router.get("/", response_model=DocumentListResponse)
def list_documents(
    page: int = 1,
    per_page: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all documents (paginated). Admins see all; others see their role's collections."""
    query = db.query(Document).filter(Document.is_deleted == False)

    if user.role != UserRole.ADMIN.value:
        from core.constants import ROLE_COLLECTIONS

        allowed = [c.value for c in ROLE_COLLECTIONS.get(UserRole(user.role), [])]
        query = query.filter(Document.collection.in_(allowed))

    total = query.count()
    docs = (
        query.order_by(Document.upload_timestamp.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return DocumentListResponse(
        documents=[_doc_to_response(d) for d in docs],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/status/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check the status of an ingestion job."""
    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobStatusResponse(
        job_id=job.id,
        document_id=job.document_id,
        status=job.status.value,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get metadata for a specific document."""
    doc = db.query(Document).filter(
        Document.id == document_id, Document.is_deleted == False
    ).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return _doc_to_response(doc)


@router.get("/{document_id}/file")
def download_document_file(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve the original uploaded file for viewing/download."""
    doc = db.query(Document).filter(
        Document.id == document_id, Document.is_deleted == False
    ).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    file_path = settings.document_store_dir / doc.stored_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk.")

    # Map extensions to MIME types
    mime_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".txt": "text/plain",
        ".csv": "text/csv",
    }
    media_type = mime_map.get(doc.file_extension, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=doc.original_filename,
    )


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    user: User = Depends(RoleRequired([UserRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Soft-delete a document and remove it from vector store and knowledge graph."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    doc.is_deleted = True
    db.commit()

    # TODO: Remove embeddings from ChromaDB and entities from Neo4j
    # This will be implemented when the vector store and graph modules are ready.

    return {"message": f"Document '{doc.original_filename}' deleted."}
