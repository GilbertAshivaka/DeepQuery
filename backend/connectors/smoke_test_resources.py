"""Resource + prompt consumption smoke test (agentless).

Exercises the connector layer's consumption of the other two MCP primitives —
resources/read and prompts/get — through the Gateway, against the public MCP
reference "everything" server (which advertises tools + resources + prompts).
Verifies content flows through with a URI-based live citation, caching works for
resources, prompts come back marked untrusted, and calls are audited.

Run from the backend/ directory:
    python -m connectors.smoke_test_resources
"""

from __future__ import annotations

import asyncio
import json
import logging

from connectors.gateway import ConnectorGateway, register_connector
from connectors.mcp_client.types import ToolKind
from core.database import SessionLocal, init_db
from models.database import ConnectorAuditLog

logging.disable(logging.INFO)


def _setup() -> None:
    db = SessionLocal()
    try:
        register_connector(
            db, name="everything", transport="stdio",
            endpoint={"command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"]},
            version="1.0.0", requires_network=False, auth_method="none", cache_ttl_seconds=30,
        )
    finally:
        db.close()


def _dump_audit() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(ConnectorAuditLog)
            .filter(ConnectorAuditLog.connector_name == "everything")
            .order_by(ConnectorAuditLog.created_at.desc())
            .limit(6)
            .all()
        )
        print("\n  audit trail (everything):")
        for r in rows:
            print(f"    {r.created_at:%H:%M:%S}  {r.capability_name:<28} {r.kind:<6} {r.outcome:<7} {r.latency_ms}ms")
    finally:
        db.close()


async def main() -> int:
    init_db()
    _setup()
    gw = ConnectorGateway(timeout_s=120.0)
    passed = True

    print("=" * 70 + "\n[1] DISCOVER all primitives\n" + "=" * 70)
    _ref, disc = await gw.discover(name="everything")
    print(f"  server={disc.server_label}  supports={disc.supports}")
    print(f"  tools={len(disc.tools)} resources={len(disc.resources)} prompts={len(disc.prompts)}")
    concrete = [r for r in disc.resources if not r.is_template]
    if not (disc.supports["resources"] and concrete):
        print("  ! server advertised no concrete resources; cannot continue"); return 1

    print("\n" + "=" * 70 + "\n[2] READ A RESOURCE (resources/read) + live citation\n" + "=" * 70)
    target = concrete[0]
    print(f"  reading uri: {target.uri}")
    r1 = await gw.read_resource(name="everything", uri=target.uri, conversation_id="c1", enforce_governance=False)
    body = r1["contents"][0]
    snippet = (body.get("text") or "")[:80]
    cit = r1["citations"][0]
    print(f"  content mime={body['mime_type']} text/blob={'text' if body.get('text') else 'blob'} snippet={snippet!r}")
    print(f"  citation: source_object_id={cit['source_object_id']} retrieved_at={cit['retrieved_at']} synthesized={cit['is_synthesized']}")
    read_ok = bool(r1["contents"]) and cit["source_object_id"] == target.uri and r1["cache_hit"] is False
    print(f"  -> {'PASS' if read_ok else 'FAIL'}")
    passed &= read_ok

    print("\n" + "=" * 70 + "\n[3] RESOURCE CACHE within TTL\n" + "=" * 70)
    r2 = await gw.read_resource(name="everything", uri=target.uri, conversation_id="c1", enforce_governance=False)
    cache_ok = r2["cache_hit"] is True and r2["citations"][0]["retrieved_at"] == cit["retrieved_at"]
    print(f"  second read cache_hit={r2['cache_hit']} (same retrieved_at={r2['citations'][0]['retrieved_at'] == cit['retrieved_at']})")
    print(f"  -> {'PASS' if cache_ok else 'FAIL'}")
    passed &= cache_ok

    print("\n" + "=" * 70 + "\n[4] GET A PROMPT (prompts/get) — marked untrusted\n" + "=" * 70)
    if disc.supports["prompts"] and disc.prompts:
        prompt = next((p for p in disc.prompts if not p.arguments), disc.prompts[0])
        args = {a["name"]: "test" for a in prompt.arguments}  # fill any required args
        print(f"  getting prompt: {prompt.name}  args={args}")
        pr = await gw.get_prompt(name="everything", prompt_name=prompt.name, arguments=args, enforce_governance=False)
        print(f"  description={pr['description']!r}  messages={len(pr['messages'])}  untrusted={pr['untrusted']}")
        if pr["messages"]:
            print(f"  first message: role={pr['messages'][0]['role']} text={pr['messages'][0]['text'][:60]!r}")
        prompt_ok = pr["untrusted"] is True and bool(pr["messages"])
        print(f"  -> {'PASS' if prompt_ok else 'FAIL'}")
        passed &= prompt_ok
    else:
        print("  ! server advertised no prompts; skipping")

    _dump_audit()

    print("\n" + "=" * 70)
    print(f"RESOURCE/PROMPT CONSUMPTION: {'ALL PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
