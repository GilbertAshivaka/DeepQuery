"""Shared value types for the MCP client."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ToolKind(str, Enum):
    RESOURCE = "resource"  # read-only (dq.mutates == False)
    ACTION = "action"  # mutating (dq.mutates == True), gated
    CONTROL = "control"  # SDK control tool (dq.execute_action / dq.reject_action)
    UNKNOWN = "unknown"  # a non-SDK tool with no dq.* classification


@dataclass
class DiscoveredTool:
    """One advertised tool, with Deep Query's classification extracted."""

    name: str
    description: str
    input_schema: dict[str, Any]
    kind: ToolKind
    mutates: bool
    connector: str


@dataclass
class DiscoveredResource:
    """An MCP `resources` primitive: application-controlled, URI-addressed data."""

    uri: str
    name: str
    description: str
    mime_type: Optional[str]
    connector: str
    is_template: bool = False  # True for a resource *template* (parameterized URI)


@dataclass
class DiscoveredPrompt:
    """An MCP `prompts` primitive: a user-controlled prompt template/workflow."""

    name: str
    description: str
    arguments: list[dict[str, Any]]  # [{name, description, required}]
    connector: str


@dataclass
class Discovery:
    """The full advertised capability set of a connector across all primitives."""

    connector: str
    server_label: str
    supports: dict[str, bool] = field(default_factory=dict)  # {"tools","resources","prompts"}
    tools: list["DiscoveredTool"] = field(default_factory=list)
    resources: list["DiscoveredResource"] = field(default_factory=list)
    prompts: list["DiscoveredPrompt"] = field(default_factory=list)


@dataclass
class ResourceContent:
    """One content piece returned by reading an MCP resource (by URI)."""

    uri: str
    mime_type: Optional[str] = None
    text: Optional[str] = None
    blob_base64: Optional[str] = None


@dataclass
class PromptMessageView:
    role: str
    text: str


@dataclass
class PromptResult:
    """The result of fetching an MCP prompt template (prompts/get)."""

    name: str
    description: str
    messages: list[PromptMessageView] = field(default_factory=list)


@dataclass
class ReadRecord:
    """One record from a read. SDK connectors supply a provenance envelope;
    ecosystem servers don't, so `provenance` may be None and is synthesized
    downstream by the citations layer."""

    data: Any
    provenance: Optional[dict[str, Any]] = None


@dataclass
class ReadResult:
    connector: str
    capability: str
    records: list[ReadRecord] = field(default_factory=list)
    # True when the connector returned the SDK provenance envelope.
    has_sdk_provenance: bool = False
    text_blocks: list[str] = field(default_factory=list)
