"""
Deep Query — API Router

Central router that mounts all sub-routers.
"""

from fastapi import APIRouter

from api.auth import router as auth_router
from api.documents import router as documents_router
from api.query import router as query_router
from api.admin import router as admin_router
from api.graph import router as graph_router
from api.connectors import router as connectors_router
from api.agents import router as agents_router
from api.skills import router as skills_router
from api.model_config import router as model_config_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(documents_router, prefix="/api/documents", tags=["Documents"])
api_router.include_router(query_router, prefix="/api/query", tags=["Query"])
api_router.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
api_router.include_router(model_config_router, prefix="/api/admin", tags=["Model Config"])
api_router.include_router(graph_router, prefix="/api/graph", tags=["Knowledge Graph"])
api_router.include_router(connectors_router, prefix="/api/connectors", tags=["Connectors"])
api_router.include_router(agents_router, prefix="/api/agents", tags=["Agents"])
api_router.include_router(skills_router, prefix="/api/skills", tags=["Skills"])
