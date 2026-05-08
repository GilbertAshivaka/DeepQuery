"""
Deep Query — Authentication Endpoints

POST /auth/login
POST /auth/refresh
POST /auth/logout
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_password,
)
from auth.dependencies import get_current_user
from core.database import get_db
from models.database import RefreshToken, User
from models.schemas import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return JWT tokens."""
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    access_token = create_access_token(user.id, user.username, user.role.value)
    refresh_tok = create_refresh_token(user.id)

    # Persist refresh token hash
    exp_timestamp = decode_token(refresh_tok)["exp"]
    rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_tok),
        expires_at=datetime.fromtimestamp(exp_timestamp, tz=timezone.utc),
    )
    db.add(rt)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_tok,
        role=user.role.value,
        username=user.username,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access token pair."""
    payload = decode_token(body.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    token_hash = hash_token(body.refresh_token)
    stored = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash, RefreshToken.is_revoked == False)
        .first()
    )
    if stored is None:
        raise HTTPException(status_code=401, detail="Refresh token revoked or not found.")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")

    # Revoke old refresh token
    stored.is_revoked = True

    # Issue new pair
    new_access = create_access_token(user.id, user.username, user.role.value)
    new_refresh = create_refresh_token(user.id)
    exp_timestamp = decode_token(new_refresh)["exp"]
    rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_refresh),
        expires_at=datetime.fromtimestamp(exp_timestamp, tz=timezone.utc),
    )
    db.add(rt)
    db.commit()

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        role=user.role.value,
        username=user.username,
    )


@router.post("/logout")
def logout(
    body: RefreshRequest,
    db: Session = Depends(get_db),
):
    """Invalidate the refresh token."""
    token_hash = hash_token(body.refresh_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if stored:
        stored.is_revoked = True
        db.commit()
    return {"message": "Logged out successfully."}
