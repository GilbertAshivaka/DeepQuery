"""Phase 4 exit smoke test — Action Gating & Deployment Modes (agentless).

Proves: the Gateway refuses an ungated execute, drives preview -> approve ->
execute (and reject), refuses a network connector in air-gapped mode while
permitting a local one, and isolates a failing connector with a circuit breaker
that fast-fails instead of stalling.

Run from the backend/ directory:
    python -m connectors.smoke_test_actions
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

from connectors.gateway import ConnectorGateway, GatewayError, register_connector
from connectors.gateway.registry import get_connector_ref
from connectors.governance import GovernanceError, approve_connector
from core.config import settings
from core.database import SessionLocal, init_db
from core.redis_client import redis_client

logging.disable(logging.INFO)
DEMO = Path(__file__).resolve().parent / "_dev" / "demo_connector.py"


def _setup() -> None:
    db = SessionLocal()
    try:
        register_connector(
            db, name="demo-tickets", transport="stdio",
            endpoint={"command": sys.executable, "args": [str(DEMO)]},
            version="1.0.0", requires_network=False, auth_method="none", cache_ttl_seconds=0,
        )
        register_connector(  # network-dependent: refused in air-gapped mode
            db, name="remote-thing", transport="http",
            endpoint={"url": "https://example.com/mcp"},
            version="1.0.0", requires_network=True, auth_method="none",
        )
        register_connector(  # exits immediately -> every call fails (circuit breaker)
            db, name="broken", transport="stdio",
            endpoint={"command": sys.executable, "args": ["-c", "import sys; sys.exit(1)"]},
            version="1.0.0", requires_network=False, auth_method="none", cache_ttl_seconds=0,
        )
    finally:
        db.close()


async def main() -> int:
    init_db()
    _setup()
    if not redis_client.ping():
        print("Redis is required for the action gate — aborting.")
        return 1
    gw = ConnectorGateway(timeout_s=10.0)
    passed = True

    print("=" * 70 + "\n[1] ACTION GATING: preview -> approve -> execute\n" + "=" * 70)
    prev = await gw.preview_action(name="demo-tickets", capability="create_ticket",
                                   arguments={"summary": "Add dark mode"}, enforce_governance=False)
    pid = prev["pending_id"]
    print(f"  preview: {prev['preview']!r}  pending_id={pid[:10]}…")

    # execute WITHOUT approval -> refused (the enforcement)
    try:
        await gw.execute_action(pending_id=pid, approval_token="not-a-real-token")
        print("  -> FAIL (ungated execute should be refused)"); passed = False
    except GatewayError as exc:
        print(f"  ungated execute refused: {exc}")

    # approve then execute -> runs
    appr = await gw.approve_action(pending_id=pid, approver_id="human-approver-1")
    res = await gw.execute_action(pending_id=pid, approval_token=appr["approval_token"])
    exec_ok = res["status"] == "executed" and res["result"]["created"].startswith("OPS-") and res["approved_by"] == "human-approver-1"
    print(f"  executed: {res['result']}  approved_by={res['approved_by']}")

    # single-use: replaying the token -> refused
    try:
        await gw.execute_action(pending_id=pid, approval_token=appr["approval_token"])
        print("  -> FAIL (token should be single-use)"); passed = False
        exec_ok = False
    except GatewayError:
        print("  token replay refused (single-use)")
    print(f"  -> {'PASS' if exec_ok else 'FAIL'}")
    passed &= exec_ok

    print("\n" + "=" * 70 + "\n[2] ACTION REJECT -> never executes\n" + "=" * 70)
    prev2 = await gw.preview_action(name="demo-tickets", capability="create_ticket",
                                    arguments={"summary": "should not happen"}, enforce_governance=False)
    await gw.reject_action(pending_id=prev2["pending_id"], approver_id="human-approver-1")
    try:
        await gw.approve_action(pending_id=prev2["pending_id"], approver_id="human-approver-1")
        print("  -> FAIL (rejected action should not be approvable)"); passed = False
    except GatewayError as exc:
        print(f"  rejected action cannot be approved/run: {exc}\n  -> PASS")

    print("\n" + "=" * 70 + "\n[3] AIR-GAPPED MODE: refuse network, permit local\n" + "=" * 70)
    settings.deployment_mode = "air-gapped"
    try:
        # network connector refused at call time
        try:
            await gw.read(name="remote-thing", capability="anything", enforce_governance=False)
            print("  -> FAIL (network connector should be refused)"); passed = False
        except GatewayError as exc:
            print(f"  network connector refused at call: {exc}")
        # and refused at approval time
        db = SessionLocal()
        try:
            rid = get_connector_ref(db, name="remote-thing").id
            try:
                approve_connector(db, connector_id=rid)
                print("  -> FAIL (network connector should not be approvable)"); passed = False
            except GovernanceError as exc:
                print(f"  network connector refused at approval: {exc}")
        finally:
            db.close()
        # local stdio connector still permitted (no deployment error)
        ok_local = await gw.preview_action(name="demo-tickets", capability="create_ticket",
                                           arguments={"summary": "local ok"}, enforce_governance=False)
        print(f"  local stdio connector permitted (preview ok: {bool(ok_local['pending_id'])})\n  -> PASS")
    finally:
        settings.deployment_mode = "cloud"

    print("\n" + "=" * 70 + "\n[4] CIRCUIT BREAKER: isolate a failing connector\n" + "=" * 70)
    for i in range(3):  # prime failures up to the threshold
        try:
            await gw.read(name="broken", capability="x", enforce_governance=False)
        except GatewayError:
            pass
    t0 = time.perf_counter()
    try:
        await gw.read(name="broken", capability="x", enforce_governance=False)
        print("  -> FAIL (expected fast-fail)"); passed = False
    except GatewayError as exc:
        dt = time.perf_counter() - t0
        h = gw.health("broken")
        fast = dt < 0.5
        opened = h["state"] == "open"
        print(f"  after 3 failures: circuit state={h['state']} consecutive_failures={h['consecutive_failures']}")
        print(f"  4th call fast-failed in {dt*1000:.0f}ms (<500ms): {fast}  msg: {exc}")
        cb_ok = fast and opened
        print(f"  -> {'PASS' if cb_ok else 'FAIL'}")
        passed &= cb_ok

    print("\n" + "=" * 70)
    print(f"PHASE 4 RESULT: {'ALL PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
