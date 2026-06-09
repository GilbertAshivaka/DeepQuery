"""Phase 3 exit smoke test — Cache, Citations & Governance (agentless).

Proves the exit criterion: an admin approves a connector, a user enables it,
reads are cached within TTL and return timestamped live citations. Also covers
role restriction, version-pin re-review, and revocation.

Run from the backend/ directory:
    python -m connectors.smoke_test_governance
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from connectors.gateway import ConnectorGateway, GatewayError, register_connector
from connectors.gateway.registry import get_connector_ref
from connectors.governance import (
    GovernanceError,
    approve_connector,
    enable_for_user,
    revoke_approval,
)
from core.constants import UserRole
from core.database import SessionLocal, init_db
from core.redis_client import redis_client
from models.database import User

logging.disable(logging.INFO)

DEMO = Path(__file__).resolve().parent / "_dev" / "demo_connector.py"


def _ensure_user(db, uid, username, role):
    u = db.query(User).filter(User.id == uid).first()
    if u is None:
        db.add(User(id=uid, username=username, email=f"{username}@t.local",
                    hashed_password="x", full_name=username, role=role))
        db.commit()
    else:
        u.role = role
        db.commit()
    return uid


def _setup() -> tuple[str, str, str, str]:
    db = SessionLocal()
    try:
        admin = _ensure_user(db, "gov-admin", "gov_admin", UserRole.ADMIN)
        researcher = _ensure_user(db, "gov-researcher", "gov_researcher", UserRole.RESEARCHER)
        student = _ensure_user(db, "gov-student", "gov_student", UserRole.STUDENT)
        ref = register_connector(
            db, name="demo-tickets", transport="stdio",
            endpoint={"command": sys.executable, "args": [str(DEMO)]},
            version="1.0.0", requires_network=False, auth_method="none", cache_ttl_seconds=60,
        )
        return admin, researcher, student, ref.id
    finally:
        db.close()


async def _read(gw, *, user_id, query="login"):
    return await gw.read(
        name="demo-tickets", capability="search_tickets", arguments={"query": query},
        user_id=user_id, conversation_id="conv-1",
    )


async def main() -> int:
    init_db()
    admin, researcher, student, conn_id = _setup()
    gw = ConnectorGateway(timeout_s=45.0)
    has_redis = redis_client.ping()
    passed = True

    print("=" * 70 + "\n[1] NOT APPROVED -> refused\n" + "=" * 70)
    try:
        await _read(gw, user_id=researcher)
        print("  -> FAIL (expected refusal)"); passed = False
    except GatewayError as exc:
        print(f"  refused: {exc}\n  -> PASS")

    print("\n" + "=" * 70 + "\n[2] ADMIN APPROVES (role-restricted to 'researcher')\n" + "=" * 70)
    db = SessionLocal()
    try:
        approve_connector(db, connector_id=conn_id, approved_by=admin, allowed_roles=["researcher"])
        ref = get_connector_ref(db, connector_id=conn_id)
        # student (wrong role) cannot enable
        try:
            enable_for_user(db, user_id=student, connector_ref=ref)
            print("  -> FAIL (student should be denied)"); passed = False
        except GovernanceError as exc:
            print(f"  student enable denied: {exc}")
        # researcher enables
        enable_for_user(db, user_id=researcher, connector_ref=ref)
        print("  researcher enabled the connector")
    finally:
        db.close()

    print("\n" + "=" * 70 + "\n[3] APPROVED + ENABLED -> read with live citations\n" + "=" * 70)
    r1 = await _read(gw, user_id=researcher)
    ok_read = bool(r1["records"]) and bool(r1["citations"]) and r1["cache_hit"] is False
    cit = r1["citations"][0]
    print(f"  records: {len(r1['records'])}  cache_hit: {r1['cache_hit']}")
    print(f"  citation: connector={cit['connector_name']} title={cit['title_or_label'][:32]!r} "
          f"retrieved_at={cit['retrieved_at']}")
    print(f"  -> {'PASS' if ok_read else 'FAIL'}")
    passed &= ok_read

    print("\n" + "=" * 70 + "\n[4] STUDENT (wrong role) -> refused\n" + "=" * 70)
    try:
        await _read(gw, user_id=student)
        print("  -> FAIL (expected refusal)"); passed = False
    except GatewayError as exc:
        print(f"  refused: {exc}\n  -> PASS")

    print("\n" + "=" * 70 + "\n[5] EPHEMERAL CACHE within TTL\n" + "=" * 70)
    if has_redis:
        r2 = await _read(gw, user_id=researcher)
        cache_ok = r2["cache_hit"] is True and r2["citations"][0]["retrieved_at"] == cit["retrieved_at"]
        print(f"  second read cache_hit: {r2['cache_hit']}  (same retrieved_at: "
              f"{r2['citations'][0]['retrieved_at'] == cit['retrieved_at']})")
        print(f"  -> {'PASS' if cache_ok else 'FAIL'}")
        passed &= cache_ok
    else:
        print("  ! Redis unavailable — skipping cache assertion")

    print("\n" + "=" * 70 + "\n[6] VERSION-PIN RE-REVIEW (major bump)\n" + "=" * 70)
    db = SessionLocal()
    try:
        register_connector(  # bump to a new major; approval is pinned at 1.0.0
            db, name="demo-tickets", transport="stdio",
            endpoint={"command": sys.executable, "args": [str(DEMO)]},
            version="2.0.0", requires_network=False, auth_method="none", cache_ttl_seconds=60,
        )
    finally:
        db.close()
    try:
        await _read(gw, user_id=researcher, query="export")  # new args to dodge cache
        print("  -> FAIL (expected re-review refusal)"); passed = False
    except GatewayError as exc:
        print(f"  refused pending re-review: {exc}\n  -> PASS")

    print("\n" + "=" * 70 + "\n[7] REVOKE APPROVAL -> refused + purged\n" + "=" * 70)
    db = SessionLocal()
    try:
        revoke_approval(db, connector_id=conn_id)
    finally:
        db.close()
    try:
        await _read(gw, user_id=researcher, query="login2")
        print("  -> FAIL (expected refusal)"); passed = False
    except GatewayError as exc:
        print(f"  refused after revoke: {exc}\n  -> PASS")

    print("\n" + "=" * 70)
    print("Note: actions are never cached — the gateway only caches in read(); there is")
    print("no cache path for action execution (action gating arrives in Phase 4).")
    print(f"\nPHASE 3 RESULT: {'ALL PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
