"""A tiny SDK-built connector used as the stdio smoke-test target.

Runs as a real MCP server over stdio (the Gateway spawns it as a subprocess).
Returns provenance-wrapped records so we can prove the SDK provenance envelope
flows intact through MCP Client → Gateway → live citation.

    python connectors/_dev/demo_connector.py   # serves over stdio
"""

from __future__ import annotations

from deepquery_sdk import Connector, action, resource

_TICKETS = [
    {"id": "OPS-12", "summary": "Login fails on Safari", "status": "In Review"},
    {"id": "OPS-18", "summary": "Export to CSV is slow", "status": "Open"},
]


class DemoTicketsConnector(Connector):
    name = "demo-tickets"
    version = "1.0.0"
    description = "An in-memory demo ticket system for Deep Query connector smoke tests."
    requires_network = False
    air_gapped_capable = True

    @resource(
        description="Search demo tickets by free-text over summary and id.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    def search_tickets(self, query: str):
        q = (query or "").lower()
        hits = [t for t in _TICKETS if q in t["summary"].lower() or q in t["id"].lower()]
        return [
            self.cite(
                t,
                source_object_id=t["id"],
                title_or_label=f"{t['id']} — {t['summary']}",
                deep_link=f"https://demo.local/tickets/{t['id']}",
                mutability_note="live status field — may change after retrieval",
            )
            for t in hits
        ]

    @action(
        description="Create a new ticket.",
        input_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    )
    def create_ticket(self, summary: str):
        # Only reached after the gateway's approval gate confirms the preview.
        new_id = f"OPS-{len(_TICKETS) + 1}"
        return {"created": new_id, "summary": summary, "status": "Open"}

    @create_ticket.preview
    def _(self, summary: str) -> str:
        return f"Create a new ticket titled '{summary}'."


if __name__ == "__main__":
    from deepquery_sdk.mcp_emit import run_stdio

    run_stdio(DemoTicketsConnector())
