"""The Gateway action gate — non-bypassable preview -> approve -> execute (guide §5, §12).

`execute` is refused unless it carries a valid approval token issued by an
explicit approval step. The Agent Layer is the *issuer* (it calls `approve` after
a human confirms); the Gateway is the *enforcer* (it verifies the token before
forwarding the execute to the connector). State lives in Redis with a short TTL,
so a half-approved action leaves no durable trace. Actions are never cached.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Optional

from core.redis_client import redis_client

_PREFIX = "dq:conn:action:"
_IDEM_PREFIX = "dq:conn:action:idem:"
_TTL_S = 600  # 10 minutes to drive preview -> approve -> execute

_UNAVAILABLE = "the approval subsystem is temporarily unavailable; please try again"


class ActionGateError(Exception):
    pass


def _args_hash(arguments: dict[str, Any] | None) -> str:
    return hashlib.sha256(json.dumps(arguments or {}, sort_keys=True, default=str).encode()).hexdigest()


def _missing_reason() -> str:
    """A previewed action wasn't found: distinguish a real Redis outage (fail
    closed, honest message) from a genuinely unknown/expired pending id."""
    return "unknown or expired action" if redis_client.ping() else _UNAVAILABLE


class ActionGate:
    """Redis-backed lifecycle store for pending (gated) actions."""

    def request(
        self,
        *,
        connector_id: str,
        connector_name: str,
        capability: str,
        arguments: dict[str, Any] | None,
        user_id: Optional[str],
        preview: str,
        mode: str = "sdk",
        idempotency_key: Optional[str] = None,
        envelope: Optional[dict[str, Any]] = None,
        preview_status: str = "resolved",
    ) -> str:
        pending_id = secrets.token_urlsafe(18)
        stored = redis_client.set_json(
            _PREFIX + pending_id,
            {
                "connector_id": connector_id,
                "connector_name": connector_name,
                "capability": capability,
                "arguments": arguments or {},
                "args_hash": _args_hash(arguments),
                "user_id": user_id,
                "preview": preview,
                # "sdk" = SDK two-phase preview/execute; "plain" = a single call on a
                # non-SDK (ecosystem) tool, executed once on approval.
                "mode": mode,
                # "resolved" = concrete args; "parameterized" = args derive from a prior
                # action's result, enforced against `envelope` at execute time (spec §2.4).
                "preview_status": preview_status,
                "envelope": envelope or None,
                "status": "previewed",
                "approver_id": None,
                "approval_token": None,
            },
            ttl_seconds=_TTL_S,
        )
        # Fail closed: if the pending action can't be persisted, refuse the flow
        # now (clearly) rather than failing confusingly at approve/execute time.
        if not stored:
            raise ActionGateError(_UNAVAILABLE)
        if idempotency_key:
            redis_client.set_json(
                _IDEM_PREFIX + idempotency_key, {"pending_id": pending_id}, ttl_seconds=_TTL_S
            )
        return pending_id

    def find_by_idempotency_key(
        self, idempotency_key: str, *, args_match: dict[str, Any] | None = None
    ) -> Optional[dict[str, Any]]:
        """The still-pending record previously minted under this key, or None (also
        None if it was consumed/expired, or if the arguments differ — a changed
        action is a NEW action and must get a fresh preview)."""
        ref = redis_client.get_json(_IDEM_PREFIX + idempotency_key)
        if not ref:
            return None
        rec = self.get(ref.get("pending_id", ""))
        if rec is None or rec.get("status") != "previewed":
            return None
        if args_match is not None and rec.get("args_hash") != _args_hash(args_match):
            return None
        return {**rec, "pending_id": ref["pending_id"]}

    def get(self, pending_id: str) -> Optional[dict[str, Any]]:
        return redis_client.get_json(_PREFIX + pending_id)

    def approve(self, pending_id: str, approver_id: str) -> str:
        """Mark PREVIEWED -> APPROVED and mint a single-use approval token."""
        rec = self._require(pending_id, "previewed")
        token = secrets.token_urlsafe(24)
        rec.update(status="approved", approver_id=approver_id, approval_token=token)
        redis_client.set_json(_PREFIX + pending_id, rec, ttl_seconds=_TTL_S)
        return token

    def reject(self, pending_id: str, approver_id: str) -> dict[str, Any]:
        rec = self._require(pending_id, "previewed")
        rec.update(status="rejected", approver_id=approver_id)
        redis_client.set_json(_PREFIX + pending_id, rec, ttl_seconds=_TTL_S)
        return rec

    def consume_for_execute(self, pending_id: str, approval_token: str) -> dict[str, Any]:
        """Verify the action is approved and the token matches, then consume it
        (single use). Raises ActionGateError otherwise — this is the enforcement."""
        rec = self.get(pending_id)
        if rec is None:
            raise ActionGateError(_missing_reason())
        if rec["status"] != "approved":
            raise ActionGateError(f"action is not approved (status: {rec['status']})")
        if not approval_token or approval_token != rec.get("approval_token"):
            raise ActionGateError("invalid approval token")
        redis_client.delete(_PREFIX + pending_id)  # single-use
        return rec

    def _require(self, pending_id: str, status: str) -> dict[str, Any]:
        rec = self.get(pending_id)
        if rec is None:
            raise ActionGateError(_missing_reason())
        if rec["status"] != status:
            raise ActionGateError(f"action already {rec['status']}")
        return rec


action_gate = ActionGate()
