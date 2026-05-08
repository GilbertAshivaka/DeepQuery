"""
Deep Query — Knowledge Graph Endpoints

GET /api/graph/entities
GET /api/graph/entity/{entity_id}
"""

from fastapi import APIRouter, Depends, HTTPException

from auth.dependencies import RoleRequired
from core.constants import UserRole

router = APIRouter()

graph_access = RoleRequired([UserRole.ADMIN, UserRole.RESEARCHER])


@router.get("/entities", dependencies=[Depends(graph_access)])
async def list_entities(skip: int = 0, limit: int = 50):
    """Return a paginated list of all entities in the knowledge graph."""
    try:
        from knowledge_graph.neo4j_client import neo4j_client

        entities = neo4j_client.get_all_entities(skip=skip, limit=limit)
        return {"entities": entities, "skip": skip, "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph query failed: {str(e)}")


@router.get("/entity/{entity_id}", dependencies=[Depends(graph_access)])
async def get_entity(entity_id: str):
    """Return a specific entity and its direct relationships."""
    try:
        from knowledge_graph.neo4j_client import neo4j_client

        result = neo4j_client.get_entity_with_relationships(entity_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Entity not found.")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph query failed: {str(e)}")
