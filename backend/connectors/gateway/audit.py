"""Audit logging — one row per connector call (guide §5, §12).

Deep Query supplies the enterprise audit trail the raw MCP ecosystem lacks:
who called which connector capability, when, read-or-action, and the outcome.
Essential for regulated verticals and incident investigation.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from models.database import ConnectorAuditLog


def record_call(
    db: Session,
    *,
    connector_name: str,
    capability_name: str,
    kind: str,  # "read" | "action"
    outcome: str,  # "success" | "error"
    connector_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action_phase: Optional[str] = None,  # "preview" | "execute"
    approved_by: Optional[str] = None,
    error_message: Optional[str] = None,
    latency_ms: Optional[int] = None,
) -> str:
    """Persist an audit entry and return its id."""
    entry = ConnectorAuditLog(
        connector_id=connector_id,
        connector_name=connector_name,
        capability_name=capability_name,
        kind=kind,
        action_phase=action_phase,
        approved_by=approved_by,
        outcome=outcome,
        error_message=error_message,
        latency_ms=latency_ms,
        user_id=user_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry.id
