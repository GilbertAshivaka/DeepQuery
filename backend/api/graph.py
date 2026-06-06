"""
Deep Query — Knowledge Graph Endpoints

GET  /api/graph/overview          Top-50 entities + inter-entity edges
GET  /api/graph/search            Subgraph centred on a named entity
GET  /api/graph/entity/{name}     Full entity detail + source documents
GET  /api/graph/entities          Paginated entity list (unchanged)
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth.dependencies import RoleRequired, get_current_user
from core.constants import UserRole
from core.database import get_db
from models.database import Document

router = APIRouter()

graph_access = RoleRequired([UserRole.ADMIN, UserRole.RESEARCHER])


@router.get("/overview", dependencies=[Depends(graph_access)])
async def graph_overview(limit: int = Query(default=50, ge=10, le=200)):
    """Return the top N most-connected entities and their inter-entity relationships."""
    try:
        from knowledge_graph.neo4j_client import neo4j_client
        return neo4j_client.get_overview_graph(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph query failed: {str(e)}")


@router.get("/search", dependencies=[Depends(graph_access)])
async def graph_search(
    entity: str = Query(..., min_length=1),
    depth: int = Query(default=2, ge=1, le=3),
    node_types: Optional[str] = Query(default=None),
    relationship_types: Optional[str] = Query(default=None),
):
    """Return a subgraph centred on the named entity up to `depth` hops away.

    node_types and relationship_types are comma-separated filter lists.
    Omit them to include all types.
    """
    try:
        from knowledge_graph.neo4j_client import neo4j_client

        parsed_node_types: Optional[List[str]] = (
            [t.strip() for t in node_types.split(",") if t.strip()]
            if node_types
            else None
        )
        parsed_rel_types: Optional[List[str]] = (
            [t.strip() for t in relationship_types.split(",") if t.strip()]
            if relationship_types
            else None
        )

        result = neo4j_client.search_entity_graph(
            entity=entity,
            depth=depth,
            node_types=parsed_node_types,
            rel_types=parsed_rel_types,
        )

        if not result["nodes"]:
            raise HTTPException(
                status_code=404,
                detail=f"No entity found matching '{entity}'.",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph query failed: {str(e)}")


@router.get("/entity/{entity_name}", dependencies=[Depends(graph_access)])
async def get_entity_detail(entity_name: str, db: Session = Depends(get_db)):
    """Return full detail for a single entity including source documents."""
    try:
        from knowledge_graph.neo4j_client import neo4j_client

        result = neo4j_client.get_entity_detail(entity_name)
        if result is None:
            raise HTTPException(status_code=404, detail="Entity not found.")

        doc_ids = result.pop("source_document_ids", [])
        if doc_ids:
            docs = (
                db.query(Document)
                .filter(Document.id.in_(doc_ids), Document.is_deleted == False)
                .all()
            )
            result["source_documents"] = [
                {"id": doc.id, "filename": doc.original_filename}
                for doc in docs
            ]
        else:
            result["source_documents"] = []

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph query failed: {str(e)}")


@router.get("/entities", dependencies=[Depends(graph_access)])
async def list_entities(skip: int = 0, limit: int = 50):
    """Return a paginated list of all entities in the knowledge graph."""
    try:
        from knowledge_graph.neo4j_client import neo4j_client
        entities = neo4j_client.get_all_entities(skip=skip, limit=limit)
        return {"entities": entities, "skip": skip, "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph query failed: {str(e)}")
