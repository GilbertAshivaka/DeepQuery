"""An SDK 1.1.0 connector exposing MCP resources + a prompt (for the full-loop test).

Proves our SDK emits the resources/prompts primitives that our gateway consumes.

    python connectors/_dev/docs_connector.py   # serves over stdio
"""

from __future__ import annotations

from deepquery_sdk import Connector, mcp_resource, prompt, resource

_ARTICLES = {"mcp-101": "MCP is the Model Context Protocol.", "deepquery": "DeepQuery grounds answers."}


class DocsConnector(Connector):
    name = "docs"
    version = "1.1.0"
    description = "Docs connector exposing resources + a prompt."
    requires_network = False
    air_gapped_capable = True

    @resource(
        description="Search articles by keyword.",
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
    )
    def search(self, q: str):
        hits = [(k, v) for k, v in _ARTICLES.items() if q.lower() in v.lower() or q.lower() in k.lower()]
        return [
            self.cite({"slug": k, "body": v}, source_object_id=k, title_or_label=k, deep_link=f"docs://article/{k}")
            for k, v in hits
        ]

    @mcp_resource(uri="docs://readme", name="README", description="The docs index.", mime_type="text/markdown")
    def readme(self) -> str:
        return "# Docs\n\n- mcp-101\n- deepquery"

    @mcp_resource(uri_template="docs://article/{slug}", name="Article", description="An article by slug.",
                  mime_type="text/markdown")
    def article(self, slug: str) -> str:
        return _ARTICLES.get(slug, f"(no article '{slug}')")

    @prompt(description="Draft a summary request for an article.",
            arguments=[{"name": "slug", "description": "Article slug", "required": True}])
    def summarize(self, slug: str) -> str:
        return f"Summarize the article '{slug}' in two sentences."


if __name__ == "__main__":
    from deepquery_sdk.mcp_emit import run_stdio

    run_stdio(DocsConnector())
