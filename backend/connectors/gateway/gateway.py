"""The Connector Gateway — every connector call passes through here.

Phase 1 scope (guide §15): **routing + audit logging**, with basic timeout and
error isolation so one slow/failing connector can't stall a query. Allowlist
enforcement (Phase 3), credential injection (Phase 2), and action gating
(Phase 4) attach at this same chokepoint later.

The Gateway is async (MCP is anyio-based); synchronous DB work (registry lookups,
audit writes) is offloaded to threads so it never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

from connectors.cache import cache_get, cache_set
from connectors.citations import build_live_citations, build_resource_citation
from connectors.credentials.store import InjectedCredential, credential_store
from connectors.gateway.action_gate import ActionGateError, action_gate
from connectors.gateway.audit import record_call
from connectors.gateway.deployment import DeploymentError, assert_connector_permitted
from connectors.gateway.health import CircuitOpenError, circuit_breaker
from connectors.gateway.registry import ConnectorRef, get_connector_ref, set_connector_icon
from connectors.governance import GovernanceError, check_access
from connectors.mcp_client.client import MCPConnectorClient, MCPClientError
from connectors.mcp_client.transports import STDIO, TransportConfig
from connectors.mcp_client.types import Discovery
from core.database import SessionLocal


# Per-connector concurrency caps (spec §2.7/§6) — one asyncio.Semaphore per connector,
# created lazily inside the running loop. Bounds simultaneous calls to a single provider.
_connector_sems: dict[str, "asyncio.Semaphore"] = {}


def _connector_semaphore(connector_id: str) -> "asyncio.Semaphore":
    from core.config import settings
    sem = _connector_sems.get(connector_id)
    if sem is None:
        sem = asyncio.Semaphore(max(1, settings.agent_connector_max_concurrency))
        _connector_sems[connector_id] = sem
    return sem


def _synthesize_preview(connector_name: str, capability: str, arguments: dict[str, Any]) -> str:
    """Build a human-readable preview for a non-SDK action without calling the tool
    (no dry-run exists for ecosystem servers — calling would execute it). The human
    approves this exact call, which then runs once via ``execute_plain``."""
    args = json.dumps(arguments, indent=2, default=str) if arguments else "{}"
    return f"Run {connector_name}.{capability} with arguments:\n{args}"


class GatewayError(Exception):
    """A connector call could not be completed; carries a user-legible message."""


class ConnectorNotFoundError(GatewayError):
    """The requested connector is not registered."""


class EnvelopeViolation(GatewayError):
    """A parameterized action's materialized arguments fell outside the approved
    constraint envelope (spec §2.4). The gateway refuses to execute — the run must
    re-present a fresh concrete preview for fresh approval."""


def _synthesize_parameterized_preview(connector_name: str, capability: str,
                                      template_args: dict[str, Any], envelope: dict[str, Any]) -> str:
    """Preview for a parameterized action — its concrete args aren't known yet (they
    derive from a prior action's result), so show the template + the approved bounds."""
    args = json.dumps(template_args, indent=2, default=str) if template_args else "{}"
    cons = json.dumps((envelope or {}).get("constraints", {}), indent=2, default=str)
    src = (envelope or {}).get("derived_from", "an earlier action")
    return (f"Run {connector_name}.{capability} once {src} completes, filling in the "
            f"derived values. Template:\n{args}\n\nApproved bounds (enforced at run time):\n{cons}")


def _within_envelope(template_args: dict[str, Any], materialized_args: dict[str, Any],
                     envelope: dict[str, Any]) -> tuple[bool, str]:
    """Diff the MATERIALIZED arguments against the approved envelope (the enforcement,
    spec §2.4). Returns (ok, reason). Rules:
      - no fields added or removed vs the approved template (no parameter injection);
      - a field that was a ``${...}`` placeholder must satisfy its constraint
        (``in`` / ``equals`` / ``derived``=just present & non-empty);
      - a field that was concrete in the template must be UNCHANGED, unless a constraint
        explicitly relaxes it."""
    template_args = template_args or {}
    materialized_args = materialized_args or {}
    constraints = (envelope or {}).get("constraints", {}) or {}

    tkeys, mkeys = set(template_args.keys()), set(materialized_args.keys())
    if tkeys != mkeys:
        added = mkeys - tkeys
        removed = tkeys - mkeys
        return False, f"argument fields changed (added={sorted(added)}, removed={sorted(removed)})"

    for field, tval in template_args.items():
        mval = materialized_args.get(field)
        is_placeholder = isinstance(tval, str) and "${" in tval
        rule = constraints.get(field)
        if rule:
            if "in" in rule and mval not in rule["in"]:
                return False, f"field '{field}'={mval!r} not in allowed {rule['in']}"
            if "equals" in rule and mval != rule["equals"]:
                return False, f"field '{field}'={mval!r} must equal {rule['equals']!r}"
            if rule.get("derived") and (mval is None or mval == ""):
                return False, f"derived field '{field}' is empty"
        elif is_placeholder:
            # A placeholder with no explicit constraint: must at least resolve to a value.
            if mval is None or mval == "" or (isinstance(mval, str) and "${" in mval):
                return False, f"derived field '{field}' did not resolve"
        else:
            # Concrete field, no constraint → must be untouched.
            if mval != tval:
                return False, f"field '{field}' changed from {tval!r} to {mval!r}"
    return True, ""


class ConnectorGateway:
    def __init__(self, *, timeout_s: float = 30.0) -> None:
        self.timeout_s = timeout_s

    # -- routing ----------------------------------------------------------
    async def _resolve(self, *, connector_id: Optional[str], name: Optional[str]) -> ConnectorRef:
        ref = await asyncio.to_thread(self._load_ref, connector_id, name)
        if ref is None:
            raise ConnectorNotFoundError(f"connector not found: {connector_id or name!r}")
        return ref

    @staticmethod
    def _load_ref(connector_id: Optional[str], name: Optional[str]) -> Optional[ConnectorRef]:
        db = SessionLocal()
        try:
            return get_connector_ref(db, connector_id=connector_id, name=name)
        finally:
            db.close()

    # -- governance enforcement (guide §9) --------------------------------
    @staticmethod
    def _check_governance(ref: ConnectorRef, user_id: str) -> None:
        """Refuse the call unless the user may use this connector (approved +
        role-permitted + version-compatible + enabled). Runs sync; call in a thread."""
        db = SessionLocal()
        try:
            check_access(db, user_id=user_id, connector_ref=ref)
        except GovernanceError as exc:
            raise GatewayError(str(exc)) from exc
        finally:
            db.close()

    # -- deployment mode + circuit breaker (guide §11, §12) ---------------
    @staticmethod
    def _assert_deployment(ref: ConnectorRef) -> None:
        """Refuse a connector not permissible under the current deployment mode
        (e.g. a network connector in air-gapped mode)."""
        try:
            assert_connector_permitted(ref)
        except DeploymentError as exc:
            raise GatewayError(str(exc)) from exc

    @staticmethod
    def _breaker_check(ref: ConnectorRef) -> None:
        """Fast-fail if the connector's circuit is open (repeated failures)."""
        try:
            circuit_breaker.check(ref.name)
        except CircuitOpenError as exc:
            raise GatewayError(
                f"the '{ref.name}' connector is temporarily unavailable "
                f"(circuit open after repeated failures); try again shortly"
            ) from exc

    @staticmethod
    def _audit_action(ref, capability, phase, outcome, user_id, approver_id, error) -> None:
        db = SessionLocal()
        try:
            record_call(
                db, connector_id=ref.id, connector_name=ref.name, capability_name=capability,
                kind="action", action_phase=phase, approved_by=approver_id, outcome=outcome,
                user_id=user_id, error_message=error,
            )
        finally:
            db.close()

    def health(self, connector_name: str) -> dict[str, Any]:
        return circuit_breaker.health(connector_name)

    # -- per-user credential injection (guide §6) -------------------------
    @staticmethod
    def _resolve_credential(ref: ConnectorRef, user_id: Optional[str]) -> Optional[InjectedCredential]:
        """Resolve (and transparently refresh) the requesting user's credential
        for this connector. Runs sync DB + httpx, so call it via a thread."""
        if user_id is None:
            return None
        db = SessionLocal()
        try:
            return credential_store.resolve_injected(db, user_id=user_id, connector_ref=ref)
        finally:
            db.close()

    async def _make_client(self, ref: ConnectorRef, user_id: Optional[str]) -> MCPConnectorClient:
        """Build an MCP client for the connector, injecting the requesting user's
        credential (stdio -> env vars; http/sse -> Authorization header)."""
        injected = await asyncio.to_thread(self._resolve_credential, ref, user_id)
        if ref.auth_method != "none" and injected is None:
            raise GatewayError(
                f"you have not connected your '{ref.name}' account; enable the connector first."
            )
        config = TransportConfig.from_registry(name=ref.name, transport=ref.transport, endpoint=ref.endpoint)
        if injected is not None:
            if ref.transport == STDIO:
                config.env = {**(config.env or {}), **injected.env()}
            else:  # sse / http
                config.headers = {**(config.headers or {}), **injected.headers()}
        return MCPConnectorClient(config, timeout_s=self.timeout_s)

    # -- discovery (not audited; a capability handshake, not a data call) --
    async def discover(
        self, *, connector_id: Optional[str] = None, name: Optional[str] = None, user_id: Optional[str] = None
    ) -> tuple[ConnectorRef, Discovery]:
        """Discover a connector's full advertised capability set across all MCP
        primitives (tools, resources, prompts)."""
        ref = await self._resolve(connector_id=connector_id, name=name)
        self._assert_deployment(ref)
        # Discovery shares the read path's circuit breaker (keyed by connector name): a
        # connector that repeatedly fails to even handshake fast-fails instead of making
        # every query wait out its connect timeout again.
        self._breaker_check(ref)
        client = await self._make_client(ref, user_id)
        try:
            discovery = await client.discover()
        except MCPClientError as exc:
            circuit_breaker.record_failure(ref.name, str(exc))
            raise GatewayError(f"the '{ref.name}' connector is unavailable: {exc}") from exc
        circuit_breaker.record_success(ref.name)
        # Cache the server's self-declared icon (only writes when it changed).
        if discovery.server_icon:
            await asyncio.to_thread(self._persist_icon, ref.id, discovery.server_icon)
        return ref, discovery

    @staticmethod
    def _persist_icon(connector_id: str, icon_url: str) -> None:
        db = SessionLocal()
        try:
            set_connector_icon(db, connector_id=connector_id, icon_url=icon_url)
        except Exception:  # icon caching is best-effort; never fail discovery over it
            db.rollback()
        finally:
            db.close()

    # -- read path --------------------------------------------------------
    async def read(
        self,
        *,
        capability: str,
        arguments: Optional[dict[str, Any]] = None,
        connector_id: Optional[str] = None,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        enforce_governance: bool = True,
    ) -> dict[str, Any]:
        """Route a read to the right connector, enforcing governance, serving from
        the ephemeral cache when possible, auditing, and returning records +
        timestamped live citations.

        `enforce_governance=False` is for trusted system/agentless calls that have
        no requesting user; real agent calls always enforce it.
        """
        ref = await self._resolve(connector_id=connector_id, name=name)

        # 1. Governance: allowlist + role + version + enablement (guide §9).
        if enforce_governance and user_id is not None:
            await asyncio.to_thread(self._check_governance, ref, user_id)

        # 2. Deployment-mode egress policy (guide §11).
        self._assert_deployment(ref)

        # 3. Ephemeral cache (reads only, per-connector TTL, user+conversation scoped).
        cache_enabled = ref.cache_ttl_seconds > 0
        if cache_enabled:
            cached = await asyncio.to_thread(
                cache_get, connector=ref.name, capability=capability, arguments=arguments,
                user_id=user_id, conversation_id=conversation_id,
            )
            if cached is not None:
                await asyncio.to_thread(self._audit, ref, capability, "success", user_id, None, 0)
                return {**cached, "cache_hit": True}

        # 4. Circuit breaker, then inject the user's credential and call the connector.
        #    A per-connector concurrency cap (spec §2.7/§6) bounds simultaneous live calls
        #    so a wide controller read fan-out can't trip provider rate limits.
        self._breaker_check(ref)
        client = await self._make_client(ref, user_id)
        started = time.perf_counter()
        try:
            async with _connector_semaphore(ref.id):
                result = await client.read(capability, arguments or {})
        except MCPClientError as exc:
            circuit_breaker.record_failure(ref.name, str(exc))
            latency = int((time.perf_counter() - started) * 1000)
            await asyncio.to_thread(self._audit, ref, capability, "error", user_id, str(exc), latency)
            raise GatewayError(f"the '{ref.name}' connector is unavailable: {exc}") from exc

        circuit_breaker.record_success(ref.name)
        latency = int((time.perf_counter() - started) * 1000)
        await asyncio.to_thread(self._audit, ref, capability, "success", user_id, None, latency)

        citations = build_live_citations(ref.name, result.records)
        payload = {
            "connector": ref.name,
            "capability": capability,
            "has_sdk_provenance": result.has_sdk_provenance,
            "records": [{"data": r.data, "provenance": r.provenance} for r in result.records],
            "citations": [c.to_dict() for c in citations],
            "latency_ms": latency,
            "cache_hit": False,
        }

        # 4. Populate the cache (the stored copy keeps cache_hit=False until served).
        if cache_enabled:
            await asyncio.to_thread(
                cache_set, connector=ref.name, capability=capability, arguments=arguments,
                user_id=user_id, conversation_id=conversation_id, value=payload, ttl_seconds=ref.cache_ttl_seconds,
            )
        return payload

    # -- resources & prompts (the other two MCP primitives) ---------------
    async def read_resource(
        self,
        *,
        uri: str,
        connector_id: Optional[str] = None,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        enforce_governance: bool = True,
    ) -> dict[str, Any]:
        """Read an MCP resource by URI — same policy path as a tool read, with a
        URI-based live citation so the content stays citeable."""
        ref = await self._resolve(connector_id=connector_id, name=name)
        if enforce_governance and user_id is not None:
            await asyncio.to_thread(self._check_governance, ref, user_id)
        self._assert_deployment(ref)

        cap = f"resource:{uri}"[:200]
        cache_enabled = ref.cache_ttl_seconds > 0
        if cache_enabled:
            cached = await asyncio.to_thread(
                cache_get, connector=ref.name, capability="__resource__", arguments={"uri": uri},
                user_id=user_id, conversation_id=conversation_id,
            )
            if cached is not None:
                await asyncio.to_thread(self._audit, ref, cap, "success", user_id, None, 0)
                return {**cached, "cache_hit": True}

        self._breaker_check(ref)
        client = await self._make_client(ref, user_id)
        started = time.perf_counter()
        try:
            contents = await client.read_resource(uri)
        except MCPClientError as exc:
            circuit_breaker.record_failure(ref.name, str(exc))
            latency = int((time.perf_counter() - started) * 1000)
            await asyncio.to_thread(self._audit, ref, cap, "error", user_id, str(exc), latency)
            raise GatewayError(f"the '{ref.name}' connector is unavailable: {exc}") from exc

        circuit_breaker.record_success(ref.name)
        latency = int((time.perf_counter() - started) * 1000)
        await asyncio.to_thread(self._audit, ref, cap, "success", user_id, None, latency)

        payload = {
            "connector": ref.name,
            "uri": uri,
            "contents": [
                {"uri": c.uri, "mime_type": c.mime_type, "text": c.text, "blob_base64": c.blob_base64}
                for c in contents
            ],
            "citations": [
                build_resource_citation(ref.name, uri=c.uri, mime_type=c.mime_type).to_dict() for c in contents
            ],
            "latency_ms": latency,
            "cache_hit": False,
        }
        if cache_enabled:
            await asyncio.to_thread(
                cache_set, connector=ref.name, capability="__resource__", arguments={"uri": uri},
                user_id=user_id, conversation_id=conversation_id, value=payload, ttl_seconds=ref.cache_ttl_seconds,
            )
        return payload

    async def get_prompt(
        self,
        *,
        prompt_name: str,
        arguments: Optional[dict[str, str]] = None,
        connector_id: Optional[str] = None,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        enforce_governance: bool = True,
    ) -> dict[str, Any]:
        """Fetch an MCP prompt template. Prompt content is an injection surface, so
        it is returned marked untrusted (guide §12) — never executed as instructions."""
        ref = await self._resolve(connector_id=connector_id, name=name)
        if enforce_governance and user_id is not None:
            await asyncio.to_thread(self._check_governance, ref, user_id)
        self._assert_deployment(ref)
        self._breaker_check(ref)
        client = await self._make_client(ref, user_id)
        cap = f"prompt:{prompt_name}"[:200]
        started = time.perf_counter()
        try:
            result = await client.get_prompt(prompt_name, arguments or {})
        except MCPClientError as exc:
            circuit_breaker.record_failure(ref.name, str(exc))
            await asyncio.to_thread(
                self._audit, ref, cap, "error", user_id, str(exc), int((time.perf_counter() - started) * 1000)
            )
            raise GatewayError(f"the '{ref.name}' connector is unavailable: {exc}") from exc

        circuit_breaker.record_success(ref.name)
        await asyncio.to_thread(
            self._audit, ref, cap, "success", user_id, None, int((time.perf_counter() - started) * 1000)
        )
        return {
            "connector": ref.name,
            "prompt": prompt_name,
            "description": result.description,
            "messages": [{"role": m.role, "text": m.text} for m in result.messages],
            "untrusted": True,
        }

    # -- gated action lifecycle (guide §5, §12) ---------------------------
    async def preview_action(
        self,
        *,
        capability: str,
        arguments: Optional[dict[str, Any]] = None,
        connector_id: Optional[str] = None,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        enforce_governance: bool = True,
        gated_mode: str = "sdk",
        idempotency_key: Optional[str] = None,
        envelope: Optional[dict[str, Any]] = None,
        preview_status: str = "resolved",
    ) -> dict[str, Any]:
        """Preview an action (no execution) and open a pending-approval record.

        ``gated_mode="sdk"`` — the connector implements the SDK two-phase protocol, so
        we call its preview to obtain a real dry-run preview. ``gated_mode="plain"`` —
        an ecosystem tool with no dry-run; we SYNTHESIZE the preview from the call and
        never touch the tool here (calling it would execute it). It runs once on
        approval via ``execute_plain``."""
        ref = await self._resolve(connector_id=connector_id, name=name)
        if enforce_governance and user_id is not None:
            await asyncio.to_thread(self._check_governance, ref, user_id)
        self._assert_deployment(ref)
        self._breaker_check(ref)
        # Idempotent preview (RESUMABLE_AGENT_SPEC_V2 §2.3): a durable run keys its
        # preview on (thread_id, step) so a replayed/re-run prepare step returns the
        # existing pending record instead of minting a duplicate.
        if idempotency_key:
            existing = await asyncio.to_thread(
                action_gate.find_by_idempotency_key, idempotency_key,
                args_match=arguments,
            )
            if existing is not None:
                return {"pending_id": existing["pending_id"], "connector": ref.name,
                        "capability": capability, "preview": existing["preview"]}
        if preview_status == "parameterized":
            # Concrete args aren't known yet (they derive from a prior action's result);
            # we can't dry-run. Show the template + the envelope; the GATEWAY enforces the
            # materialized args against that envelope at execute time.
            preview = _synthesize_parameterized_preview(ref.name, capability, arguments or {}, envelope or {})
        elif gated_mode == "plain":
            preview = _synthesize_preview(ref.name, capability, arguments or {})
        else:
            client = await self._make_client(ref, user_id)
            try:
                preview = await client.preview_action(capability, arguments or {})
            except MCPClientError as exc:
                circuit_breaker.record_failure(ref.name, str(exc))
                await asyncio.to_thread(self._audit_action, ref, capability, "preview", "error", user_id, None, str(exc))
                raise GatewayError(f"the '{ref.name}' connector is unavailable: {exc}") from exc
            circuit_breaker.record_success(ref.name)
        pending_id = await asyncio.to_thread(
            action_gate.request, connector_id=ref.id, connector_name=ref.name,
            capability=capability, arguments=arguments, user_id=user_id, preview=preview, mode=gated_mode,
            idempotency_key=idempotency_key, envelope=envelope, preview_status=preview_status,
        )
        await asyncio.to_thread(self._audit_action, ref, capability, "preview", "success", user_id, None, None)
        return {"pending_id": pending_id, "connector": ref.name, "capability": capability, "preview": preview}

    async def approve_action(self, *, pending_id: str, approver_id: str) -> dict[str, Any]:
        """Issue an approval token (the Agent Layer calls this after a human confirms)."""
        try:
            token = await asyncio.to_thread(action_gate.approve, pending_id, approver_id)
        except ActionGateError as exc:
            raise GatewayError(str(exc)) from exc
        return {"pending_id": pending_id, "approval_token": token}

    async def reject_action(self, *, pending_id: str, approver_id: str) -> dict[str, Any]:
        try:
            await asyncio.to_thread(action_gate.reject, pending_id, approver_id)
        except ActionGateError as exc:
            raise GatewayError(str(exc)) from exc
        return {"pending_id": pending_id, "status": "rejected"}

    async def execute_action(self, *, pending_id: str, approval_token: str, user_id: Optional[str] = None,
                             materialized_args: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Execute a previewed action — refused unless it carries a valid approval
        token (the enforcement). For a PARAMETERIZED action (spec §2.4) the caller passes
        the now-concrete ``materialized_args``; the gateway diffs them against the approved
        envelope and REFUSES (``EnvelopeViolation``) if they fall outside — the run must
        re-present a fresh concrete preview. Forwards execute to the connector and audits."""
        try:
            rec = await asyncio.to_thread(action_gate.consume_for_execute, pending_id, approval_token)
        except ActionGateError as exc:
            raise GatewayError(str(exc)) from exc

        run_args = rec["arguments"]
        if rec.get("preview_status") == "parameterized":
            run_args = materialized_args if materialized_args is not None else rec["arguments"]
            ok, reason = _within_envelope(rec["arguments"], run_args, rec.get("envelope") or {})
            if not ok:
                ref = await self._resolve(connector_id=rec["connector_id"], name=None)
                await asyncio.to_thread(
                    self._audit_action, ref, rec["capability"], "execute", "blocked",
                    rec.get("user_id"), rec.get("approver_id"), f"envelope violation: {reason}",
                )
                raise EnvelopeViolation(reason)

        ref = await self._resolve(connector_id=rec["connector_id"], name=None)
        self._assert_deployment(ref)
        self._breaker_check(ref)
        client = await self._make_client(ref, rec.get("user_id") or user_id)
        try:
            if rec.get("mode") == "plain":
                # Non-SDK tool: a single approved call (no two-phase protocol exists).
                result = await client.execute_plain(rec["capability"], run_args)
            else:
                result = await client.execute_gated_action(rec["capability"], run_args)
        except MCPClientError as exc:
            circuit_breaker.record_failure(ref.name, str(exc))
            await asyncio.to_thread(
                self._audit_action, ref, rec["capability"], "execute", "error",
                rec.get("user_id"), rec.get("approver_id"), str(exc),
            )
            raise GatewayError(f"the '{ref.name}' connector is unavailable: {exc}") from exc
        circuit_breaker.record_success(ref.name)
        await asyncio.to_thread(
            self._audit_action, ref, rec["capability"], "execute", "success",
            rec.get("user_id"), rec.get("approver_id"), None,
        )
        return {"status": "executed", "result": result, "approved_by": rec.get("approver_id")}

    # -- audit helper (sync, runs in a thread) ----------------------------
    @staticmethod
    def _audit(
        ref: ConnectorRef,
        capability: str,
        outcome: str,
        user_id: Optional[str],
        error: Optional[str],
        latency_ms: int,
    ) -> None:
        db = SessionLocal()
        try:
            record_call(
                db,
                connector_id=ref.id,
                connector_name=ref.name,
                capability_name=capability,
                kind="read",
                outcome=outcome,
                user_id=user_id,
                error_message=error,
                latency_ms=latency_ms,
            )
        finally:
            db.close()
