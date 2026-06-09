"""Deep Query MCP client — the universal interface to every connector."""

from connectors.mcp_client.client import MCPClientError, MCPConnectorClient, gather_reads
from connectors.mcp_client.transports import TransportConfig
from connectors.mcp_client.types import (
    DiscoveredPrompt,
    DiscoveredResource,
    DiscoveredTool,
    Discovery,
    PromptMessageView,
    PromptResult,
    ReadRecord,
    ReadResult,
    ResourceContent,
    ToolKind,
)

__all__ = [
    "MCPConnectorClient",
    "MCPClientError",
    "gather_reads",
    "TransportConfig",
    "Discovery",
    "DiscoveredTool",
    "DiscoveredResource",
    "DiscoveredPrompt",
    "ReadRecord",
    "ReadResult",
    "ResourceContent",
    "PromptResult",
    "PromptMessageView",
    "ToolKind",
]
