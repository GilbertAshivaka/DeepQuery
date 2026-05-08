"""
Deep Query — Authentication Dependencies

FastAPI dependency injection for JWT validation and role checking.
"""

from typing import List

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from auth.jwt_handler import decode_token
from core.constants import UserRole
from core.database import get_db
from models.database import User
from models.schemas import TokenPayload

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate the current user from the JWT token."""
    token = credentials.credentials
    payload = decode_token(token)

    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    return user


def get_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    """Extract token payload without DB lookup (for lightweight checks)."""
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        )
    return TokenPayload(
        user_id=payload["sub"],
        username=payload["username"],
        role=payload["role"],
        allowed_collections=payload.get("allowed_collections", []),
    )


class RoleRequired:
    """Dependency that enforces minimum role access.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(RoleRequired([UserRole.ADMIN]))])
    """

    def __init__(self, allowed_roles: List[UserRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_user)):
        if user.role not in [r.value for r in self.allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' does not have access to this resource.",
            )
        return user
