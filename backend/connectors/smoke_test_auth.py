"""Phase 2 exit smoke test — Credentials & Per-User Auth (agentless).

Proves the exit criterion: two users enable the same connector and each reads
only what *their own* credential grants. Also exercises the OAuth auth-code
exchange (against an inline mock token endpoint), transparent refresh, and revoke.

Run from the backend/ directory:
    python -m connectors.smoke_test_auth
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from connectors.credentials import credential_store
from connectors.gateway import ConnectorGateway, GatewayError, register_connector
from core.database import SessionLocal, init_db
from models.database import ConnectorCredential, User

logging.disable(logging.INFO)

ECHO_CONNECTOR = Path(__file__).resolve().parent / "_dev" / "echo_connector.py"


# --------------------------------------------------------------------------- #
# Inline mock OAuth token endpoint (authorization_code + refresh_token grants).
# --------------------------------------------------------------------------- #
class _TokenHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode())
        grant = params.get("grant_type", [""])[0]
        if grant == "authorization_code":
            body = {"access_token": "oauth-access-1", "refresh_token": "refresh-1", "token_type": "Bearer", "expires_in": 3600}
        elif grant == "refresh_token":
            body = {"access_token": "oauth-access-2", "refresh_token": "refresh-2", "token_type": "Bearer", "expires_in": 3600}
        else:
            body = {"error": "unsupported_grant_type"}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silence
        pass


def _start_mock_token_server() -> tuple[str, HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), _TokenHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    return f"http://127.0.0.1:{port}/token", server


# --------------------------------------------------------------------------- #
# Test fixtures
# --------------------------------------------------------------------------- #
def _ensure_user(db, uid: str, username: str) -> str:
    if db.query(User).filter(User.id == uid).first() is None:
        db.add(User(id=uid, username=username, email=f"{username}@test.local",
                    hashed_password="x", full_name=username))
        db.commit()
    return uid


def _setup(token_url: str) -> tuple[str, str, str]:
    db = SessionLocal()
    try:
        ua = _ensure_user(db, "user-aaa", "alice_conn_test")
        ub = _ensure_user(db, "user-bbb", "bob_conn_test")
        # The echo connector requires auth (api_key) so the gateway must inject a credential.
        # cache_ttl_seconds=0: this smoke exercises credential dynamics (refresh,
        # revoke), which a read-cache would mask; disable caching for it.
        ref = register_connector(
            db, name="echo-auth", transport="stdio",
            endpoint={"command": sys.executable, "args": [str(ECHO_CONNECTOR)]},
            version="1.0.0", requires_network=False, auth_method="api_key", cache_ttl_seconds=0,
        )
        # Register an OAuth variant of the same echo connector for the OAuth tests.
        register_connector(
            db, name="echo-oauth", transport="stdio",
            endpoint={"command": sys.executable, "args": [str(ECHO_CONNECTOR)]},
            version="1.0.0", requires_network=False, auth_method="oauth2", cache_ttl_seconds=0,
            auth_config={"token_endpoint": token_url, "authorize_endpoint": "http://x/authorize",
                         "client_id": "mock-client", "scopes": ["read"]},
        )
        return ua, ub, ref.id
    finally:
        db.close()


def _set_api_key(user_id: str, connector_name: str, token: str) -> None:
    db = SessionLocal()
    try:
        from connectors.gateway.registry import get_connector_ref
        ref = get_connector_ref(db, name=connector_name)
        credential_store.set_credential(db, user_id=user_id, connector_id=ref.id, method="api_key", payload={"token": token})
    finally:
        db.close()


async def _whoami(gw: ConnectorGateway, *, user_id: str, connector: str):
    # This smoke targets credential injection, not governance; bypass the latter.
    result = await gw.read(
        name=connector, capability="whoami", user_id=user_id, enforce_governance=False
    )
    return result["records"][0]["data"]["injected_token"]


# --------------------------------------------------------------------------- #
async def main() -> int:
    init_db()
    token_url, server = _start_mock_token_server()
    ua, ub, _echo_id = _setup(token_url)
    gw = ConnectorGateway(timeout_s=45.0)
    passed = True

    print("=" * 70 + "\n[1] PER-USER ISOLATION (the exit criterion)\n" + "=" * 70)
    _set_api_key(ua, "echo-auth", "token-ALICE")
    _set_api_key(ub, "echo-auth", "token-BOB")
    a_sees = await _whoami(gw, user_id=ua, connector="echo-auth")
    b_sees = await _whoami(gw, user_id=ub, connector="echo-auth")
    print(f"  alice's read injected: {a_sees}")
    print(f"  bob's   read injected: {b_sees}")
    iso_ok = a_sees == "token-ALICE" and b_sees == "token-BOB"
    print(f"  -> isolation: {'PASS' if iso_ok else 'FAIL'}")
    passed &= iso_ok

    print("\n" + "=" * 70 + "\n[2] AUTH REQUIRED WITHOUT A CREDENTIAL\n" + "=" * 70)
    try:
        await _whoami(gw, user_id="user-nocred", connector="echo-auth")
        print("  -> FAIL (expected refusal)")
        passed = False
    except GatewayError as exc:
        print(f"  refused as expected: {exc}")
        print("  -> PASS")

    print("\n" + "=" * 70 + "\n[3] OAUTH EXCHANGE + TRANSPARENT REFRESH\n" + "=" * 70)
    # Exchange: simulate the post-consent token exchange directly against the mock.
    from connectors.credentials import oauth as oauth_flow
    from connectors.gateway.registry import get_connector_ref

    db = SessionLocal()
    try:
        oref = get_connector_ref(db, name="echo-oauth")
        # Seed pending state as begin_authorization would, then complete it.
        from core.redis_client import redis_client
        have_redis = redis_client.ping()
        if have_redis:
            state = "teststate123"
            redis_client.set_json(f"dq:oauth:pending:{state}",
                                  {"user_id": ua, "connector_id": oref.id, "code_verifier": "v"}, ttl_seconds=300)
            oauth_flow.complete_authorization(db, state=state, code="auth-code")
            print("  completed OAuth code exchange (via mock token endpoint)")
        else:
            # Redis unavailable: store the exchanged credential directly so the
            # rest of the OAuth path still runs.
            credential_store.set_credential(db, user_id=ua, connector_id=oref.id, method="oauth2",
                                            payload={"access_token": "oauth-access-1", "refresh_token": "refresh-1",
                                                     "token_type": "Bearer"},
                                            expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
            print("  (Redis down) seeded OAuth credential directly")
    finally:
        db.close()

    first = await _whoami(gw, user_id=ua, connector="echo-oauth")
    print(f"  read after exchange injected: {first}")
    exch_ok = first == "oauth-access-1"

    # Force expiry so the next read triggers a transparent refresh.
    db = SessionLocal()
    try:
        row = db.query(ConnectorCredential).filter(
            ConnectorCredential.user_id == ua, ConnectorCredential.connector_id == oref.id
        ).first()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.commit()
    finally:
        db.close()

    refreshed = await _whoami(gw, user_id=ua, connector="echo-oauth")
    print(f"  read after forced-expiry injected: {refreshed} (expect refreshed token)")
    refresh_ok = refreshed == "oauth-access-2"
    print(f"  -> oauth exchange: {'PASS' if exch_ok else 'FAIL'} | refresh: {'PASS' if refresh_ok else 'FAIL'}")
    passed &= exch_ok and refresh_ok

    print("\n" + "=" * 70 + "\n[4] REVOKE\n" + "=" * 70)
    db = SessionLocal()
    try:
        credential_store.delete_credential(db, user_id=ua, connector_id=get_connector_ref(db, name="echo-auth").id)
    finally:
        db.close()
    try:
        await _whoami(gw, user_id=ua, connector="echo-auth")
        print("  -> FAIL (expected refusal after revoke)")
        passed = False
    except GatewayError:
        print("  refused after revoke -> PASS")

    server.shutdown()
    print("\n" + "=" * 70)
    print(f"PHASE 2 RESULT: {'ALL PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
