"""Turn a returned record into a timestamped live citation (guide §8).

A live citation must encode *when* it was true, because the source can change.
SDK-built connectors supply a full provenance envelope; ecosystem servers don't,
so we synthesize one (stamping the retrieval time and labelling it clearly) and
mark it ``is_synthesized`` so the UI/agent knows the provenance was inferred.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Optional

from deepquery_sdk.provenance import now_iso  # reuse the SDK's ISO-8601 stamp

from connectors.mcp_client.types import ReadRecord


@dataclass
class LiveCitation:
    """The structured object the UI renders as a (visually distinct) live citation."""

    connector_name: str
    retrieved_at: str
    title_or_label: str
    source_object_id: Optional[str] = None
    deep_link: Optional[str] = None
    mutability_note: Optional[str] = None
    # True when the connector did not supply an SDK provenance envelope and we
    # had to synthesize the citation from the raw content.
    is_synthesized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label_from_data(data: Any, *, fallback: str) -> str:
    text = data if isinstance(data, str) else json.dumps(data, default=str)
    text = text.strip()
    if not text:
        return fallback
    return text[:80] + "…" if len(text) > 80 else text


def build_live_citation(connector_name: str, record: ReadRecord) -> LiveCitation:
    """Build one live citation from a record, using its envelope when present."""
    prov = record.provenance
    if prov:
        return LiveCitation(
            connector_name=prov.get("connector_name") or connector_name,
            retrieved_at=prov.get("retrieved_at") or now_iso(),
            title_or_label=prov.get("title_or_label") or _label_from_data(record.data, fallback=connector_name),
            source_object_id=prov.get("source_object_id"),
            deep_link=prov.get("deep_link"),
            mutability_note=prov.get("mutability_note"),
            is_synthesized=False,
        )
    # Ecosystem connector: synthesize, honest about the missing envelope.
    return LiveCitation(
        connector_name=connector_name,
        retrieved_at=now_iso(),
        title_or_label=_label_from_data(record.data, fallback=connector_name),
        source_object_id=None,
        deep_link=None,
        mutability_note="live data — no provenance envelope supplied by this connector",
        is_synthesized=True,
    )


def build_live_citations(connector_name: str, records: list[ReadRecord]) -> list[LiveCitation]:
    return [build_live_citation(connector_name, r) for r in records]


def build_resource_citation(
    connector_name: str,
    *,
    uri: str,
    title: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> LiveCitation:
    """Build a live citation for an MCP resource read by URI. The URI is a real
    source identifier, so this is a proper (non-synthesized) citation."""
    is_http = uri.startswith("http://") or uri.startswith("https://")
    return LiveCitation(
        connector_name=connector_name,
        retrieved_at=now_iso(),
        title_or_label=title or uri,
        source_object_id=uri,
        deep_link=uri if is_http else None,
        mutability_note=f"live resource ({mime_type})" if mime_type else "live resource",
        is_synthesized=False,
    )
