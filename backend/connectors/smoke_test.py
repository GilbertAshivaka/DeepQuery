"""Phase 1 exit smoke test (agentless).

Through the Gateway, read a resource from BOTH:
  1. a local SDK-built connector over stdio (provenance envelope flows intact), and
  2. a real public MCP server over HTTP/SSE (DeepWiki),
then dump the audit-log rows the calls produced.

Run from the backend/ directory:
    python -m connectors.smoke_test
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from connectors.gateway import ConnectorGateway, register_connector
from connectors.mcp_client.types import ToolKind
from core.database import SessionLocal, init_db
from models.database import ConnectorAuditLog

# Quiet the dev SQLAlchemy echo (engine is created with echo=True in dev). A
# blunt disable of INFO-level logging keeps this smoke script's output readable.
logging.disable(logging.INFO)

DEMO_CONNECTOR = Path(__file__).resolve().parent / "_dev" / "demo_connector.py"
# Public, auth-free remote MCP server. DeepWiki serves streamable HTTP at /mcp
# (its older /sse endpoint is now 410 Gone — SSE is being deprecated MCP-wide).
PUBLIC_HTTP_URL = "https://mcp.deepwiki.com/mcp"


def _seed_registry() -> None:
    """Register the two smoke-test connectors (idempotent)."""
    db = SessionLocal()
    try:
        register_connector(
            db,
            name="demo-tickets",
            transport="stdio",
            endpoint={"command": sys.executable, "args": [str(DEMO_CONNECTOR)]},
            version="1.0.0",
            requires_network=False,
        )
        register_connector(
            db,
            name="deepwiki",
            transport="http",
            endpoint={"url": PUBLIC_HTTP_URL},
            version="public",
            requires_network=True,
        )
    finally:
        db.close()


def _print_discovered(label: str, disc) -> None:
    s = disc.supports
    print(
        f"\n  {label} (server: {disc.server_label}) — advertises: "
        f"tools={s['tools']} resources={s['resources']} prompts={s['prompts']}"
    )
    print(f"    tools ({len(disc.tools)}):")
    for t in disc.tools:
        print(f"      - {t.name:<22} [{t.kind.value}] mutates={t.mutates}")
    print(f"    resources ({len(disc.resources)}):")
    for r in disc.resources[:5]:
        print(f"      - {r.uri}{' (template)' if r.is_template else ''}")
    print(f"    prompts ({len(disc.prompts)}):")
    for p in disc.prompts[:5]:
        print(f"      - {p.name}  args={[a['name'] for a in p.arguments]}")


async def _read_local(gw: ConnectorGateway) -> dict | None:
    print("\n" + "=" * 70 + "\n[1] LOCAL SDK CONNECTOR over stdio  (demo-tickets)\n" + "=" * 70)
    _ref, disc = await gw.discover(name="demo-tickets")
    _print_discovered("demo-tickets", disc)
    result = await gw.read(name="demo-tickets", capability="search_tickets", arguments={"query": "login"})
    print("\n  read search_tickets(query='login') ->")
    print("    has_sdk_provenance:", result["has_sdk_provenance"])
    print("    records:", json.dumps(result["records"], indent=6, default=str))
    print("    live citations:", json.dumps(result["citations"], indent=6, default=str))
    return result


async def _read_public(gw: ConnectorGateway) -> dict | None:
    print("\n" + "=" * 70 + "\n[2] PUBLIC MCP SERVER over HTTP/SSE  (deepwiki)\n" + "=" * 70)
    try:
        _ref, disc = await gw.discover(name="deepwiki")
    except Exception as exc:
        print(f"  ! public server unreachable (network?): {exc}")
        return None
    _print_discovered("deepwiki", disc)

    # Pick a read tool and call it. DeepWiki's reads take a `repoName`.
    read_tools = [t for t in disc.tools if t.kind in (ToolKind.RESOURCE, ToolKind.UNKNOWN)]
    target = next((t for t in read_tools if t.name == "read_wiki_structure"), read_tools[0] if read_tools else None)
    if target is None:
        print("  ! no read-like tool advertised; skipping read.")
        return None
    try:
        result = await gw.read(
            name="deepwiki",
            capability=target.name,
            arguments={"repoName": "modelcontextprotocol/python-sdk"},
        )
    except Exception as exc:
        print(f"  ! read {target.name!r} failed: {exc}")
        return None
    print(f"\n  read {target.name}(repoName='modelcontextprotocol/python-sdk') ->")
    print("    has_sdk_provenance:", result["has_sdk_provenance"], "(public server has no SDK envelope -> synthesized)")
    preview = result["records"][:1]
    print("    first record (truncated):", json.dumps(preview, indent=6, default=str)[:600])
    print("    live citations (first):", json.dumps(result["citations"][:1], indent=6, default=str))
    return result


def _dump_audit() -> None:
    print("\n" + "=" * 70 + "\nAUDIT LOG (control-plane trail)\n" + "=" * 70)
    db = SessionLocal()
    try:
        rows = db.query(ConnectorAuditLog).order_by(ConnectorAuditLog.created_at.desc()).limit(10).all()
        for r in rows:
            print(
                f"  {r.created_at:%H:%M:%S}  {r.connector_name:<14} {r.capability_name:<20} "
                f"{r.kind:<6} {r.outcome:<7} {r.latency_ms}ms"
                + (f"  err={r.error_message[:60]}" if r.error_message else "")
            )
    finally:
        db.close()


async def main() -> int:
    init_db()  # ensure the connectors + audit tables exist
    _seed_registry()
    gw = ConnectorGateway(timeout_s=45.0)

    local = await _read_local(gw)
    public = await _read_public(gw)
    _dump_audit()

    print("\n" + "=" * 70)
    ok_local = bool(local and local["records"] and local["has_sdk_provenance"])
    print(f"LOCAL stdio + SDK provenance: {'PASS' if ok_local else 'FAIL'}")
    print(f"PUBLIC HTTP/SSE read:         {'PASS' if public else 'UNREACHABLE/SKIPPED'}")
    return 0 if ok_local else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
