"""The MCP client — discovery, invocation, capability negotiation, parallel reads.

One client speaks MCP to every connector, public or SDK-built (guide §4). It is a
protocol-faithful transport: it does not decide *whether* to call a connector
(Agent Layer), store credentials (Gateway), or enforce the allowlist (Gateway).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable

from mcp import types
from mcp.client.session import ClientSession
from pydantic import AnyUrl

from connectors.mcp_client.transports import TransportConfig, open_streams
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

# Deep Query metadata keys the SDK emits (mirrors deepquery_sdk.classification).
_DQ_KIND = "dq.kind"
_DQ_MUTATES = "dq.mutates"

# SDK control tools that drive the gated action lifecycle.
_EXECUTE_TOOL = "dq.execute_action"
_REJECT_TOOL = "dq.reject_action"

DEFAULT_TIMEOUT_S = 30.0


class MCPClientError(Exception):
    """A connector call failed at the protocol/transport level."""


def _unwrap_cause(exc: BaseException) -> str:
    """Unwrap ExceptionGroups (anyio / asyncio TaskGroup) down to the real underlying
    cause(s), so a connector failure reads e.g. 'FileNotFoundError: ... duckduckgo-mcp' or
    'connection refused' / 'auth 401' instead of the opaque 'unhandled errors in a
    TaskGroup (1 sub-exception)'."""
    leaves: list[str] = []

    def _is_group(e: BaseException) -> bool:
        # Built-in BaseExceptionGroup (3.11+) or anyio's backport (both expose .exceptions).
        if isinstance(e, BaseExceptionGroup):
            return True
        subs = getattr(e, "exceptions", None)
        return isinstance(subs, (list, tuple))

    def walk(e: BaseException) -> None:
        if _is_group(e):
            for sub in getattr(e, "exceptions", []) or []:
                walk(sub)
            return
        text = (str(e) or "").strip()
        cls = type(e).__name__
        if not text:
            label = cls
        elif cls.lower() in text.lower():
            label = text
        else:
            label = f"{cls}: {text}"
        if label not in leaves:
            leaves.append(label)

    walk(exc)
    return "; ".join(leaves) or (str(exc) or type(exc).__name__)


class MCPConnectorClient:
    """Talks MCP to a single connector over its configured transport."""

    def __init__(self, config: TransportConfig, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.config = config
        self.timeout_s = timeout_s

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[tuple[ClientSession, types.InitializeResult]]:
        """Open a transport, start a session, and run the MCP initialize
        handshake (capability negotiation). Yields (session, init result) so
        callers can see the server's advertised capabilities. Raises
        MCPClientError on failure."""
        try:
            async with open_streams(self.config) as (read, write):
                async with ClientSession(read, write) as session:
                    try:
                        async with asyncio.timeout(self.timeout_s):
                            init = await session.initialize()
                    except Exception as exc:  # incompatible/raising server
                        raise MCPClientError(
                            f"connector {self.config.name!r}: MCP initialize/negotiation failed: {_unwrap_cause(exc)}"
                        ) from exc
                    yield session, init
        except MCPClientError:
            raise
        except Exception as exc:  # transport/connection failure
            raise MCPClientError(
                f"connector {self.config.name!r}: transport error ({self.config.transport}): {_unwrap_cause(exc)}"
            ) from exc

    # -- discovery --------------------------------------------------------
    async def discover(self) -> Discovery:
        """Probe every MCP primitive the server *advertises* — tools, resources,
        and prompts — guarded by the capabilities from the initialize handshake,
        so we never call a method a server doesn't support."""
        async with self._session() as (session, init):
            caps = init.capabilities
            label = getattr(init.serverInfo, "name", None) or self.config.name
            supports = {
                "tools": caps.tools is not None,
                "resources": caps.resources is not None,
                "prompts": caps.prompts is not None,
            }

            tools: list[DiscoveredTool] = []
            resources: list[DiscoveredResource] = []
            prompts: list[DiscoveredPrompt] = []

            if supports["tools"]:
                tools = await self._safe_list_tools(session)
            if supports["resources"]:
                resources = await self._safe_list_resources(session)
            if supports["prompts"]:
                prompts = await self._safe_list_prompts(session)

            return Discovery(
                connector=self.config.name,
                server_label=label,
                supports=supports,
                tools=tools,
                resources=resources,
                prompts=prompts,
            )

    async def _safe_list_tools(self, session: ClientSession) -> list[DiscoveredTool]:
        try:
            async with asyncio.timeout(self.timeout_s):
                listed = await session.list_tools()
        except Exception:
            return []
        return [self._classify(t) for t in listed.tools]

    async def _safe_list_resources(self, session: ClientSession) -> list[DiscoveredResource]:
        out: list[DiscoveredResource] = []
        try:
            async with asyncio.timeout(self.timeout_s):
                listed = await session.list_resources()
            out += [
                DiscoveredResource(
                    uri=str(r.uri), name=r.name or "", description=r.description or "",
                    mime_type=r.mimeType, connector=self.config.name, is_template=False,
                )
                for r in listed.resources
            ]
        except Exception:
            pass
        try:  # resource templates are a separate, optional list
            async with asyncio.timeout(self.timeout_s):
                templated = await session.list_resource_templates()
            out += [
                DiscoveredResource(
                    uri=r.uriTemplate, name=r.name or "", description=r.description or "",
                    mime_type=r.mimeType, connector=self.config.name, is_template=True,
                )
                for r in templated.resourceTemplates
            ]
        except Exception:
            pass
        return out

    async def _safe_list_prompts(self, session: ClientSession) -> list[DiscoveredPrompt]:
        try:
            async with asyncio.timeout(self.timeout_s):
                listed = await session.list_prompts()
        except Exception:
            return []
        return [
            DiscoveredPrompt(
                name=p.name,
                description=p.description or "",
                arguments=[
                    {"name": a.name, "description": a.description or "", "required": bool(a.required)}
                    for a in (p.arguments or [])
                ],
                connector=self.config.name,
            )
            for p in listed.prompts
        ]

    # -- read -------------------------------------------------------------
    async def read(self, capability: str, arguments: dict[str, Any] | None = None) -> ReadResult:
        """Call a resource (read) and normalize the result."""
        async with self._session() as (session, _init):
            try:
                async with asyncio.timeout(self.timeout_s):
                    result = await session.call_tool(capability, arguments or {})
            except Exception as exc:
                raise MCPClientError(
                    f"connector {self.config.name!r}: read {capability!r} failed: {_unwrap_cause(exc)}"
                ) from exc
        if result.isError:
            text = next((b.text for b in result.content if getattr(b, "text", None)), "")
            raise MCPClientError(f"connector {self.config.name!r}: read {capability!r} errored: {text}")
        return self._parse_read(capability, result)

    # -- resources & prompts (the other two MCP primitives) ---------------
    async def read_resource(self, uri: str) -> list[ResourceContent]:
        """Read an MCP resource by URI (resources/read)."""
        async with self._session() as (session, _init):
            try:
                async with asyncio.timeout(self.timeout_s):
                    result = await session.read_resource(AnyUrl(uri))
            except Exception as exc:
                raise MCPClientError(f"connector {self.config.name!r}: read_resource {uri!r} failed: {_unwrap_cause(exc)}") from exc
        out: list[ResourceContent] = []
        for c in result.contents:
            out.append(
                ResourceContent(
                    uri=str(c.uri),
                    mime_type=getattr(c, "mimeType", None),
                    text=getattr(c, "text", None),
                    blob_base64=getattr(c, "blob", None),
                )
            )
        return out

    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> PromptResult:
        """Fetch an MCP prompt template (prompts/get)."""
        async with self._session() as (session, _init):
            try:
                async with asyncio.timeout(self.timeout_s):
                    result = await session.get_prompt(name, arguments or {})
            except Exception as exc:
                raise MCPClientError(f"connector {self.config.name!r}: get_prompt {name!r} failed: {_unwrap_cause(exc)}") from exc
        messages: list[PromptMessageView] = []
        for m in result.messages:
            text = getattr(m.content, "text", None) or ""
            messages.append(PromptMessageView(role=str(m.role), text=text))
        return PromptResult(name=name, description=result.description or "", messages=messages)

    # -- gated actions ----------------------------------------------------
    async def preview_action(self, capability: str, arguments: dict[str, Any] | None = None) -> str:
        """Call an action tool to obtain its preview. Does NOT execute."""
        async with self._session() as (session, _init):
            try:
                async with asyncio.timeout(self.timeout_s):
                    result = await session.call_tool(capability, arguments or {})
            except Exception as exc:
                raise MCPClientError(f"connector {self.config.name!r}: preview {capability!r} failed: {_unwrap_cause(exc)}") from exc
        if result.isError:
            text = next((b.text for b in result.content if getattr(b, "text", None)), "")
            raise MCPClientError(f"connector {self.config.name!r}: preview {capability!r} errored: {text}")
        sc = result.structuredContent or {}
        if sc.get("status") != "preview":
            raise MCPClientError(f"connector {self.config.name!r}: {capability!r} is not a gated action")
        return sc.get("preview", "")

    async def execute_gated_action(self, capability: str, arguments: dict[str, Any] | None = None) -> Any:
        """Within a single session: preview the action (mint the connector's token)
        then execute it. The gateway calls this only after human approval, so the
        connector's own preview->execute gate is satisfied atomically here."""
        async with self._session() as (session, _init):
            try:
                async with asyncio.timeout(self.timeout_s):
                    preview = await session.call_tool(capability, arguments or {})
            except Exception as exc:
                raise MCPClientError(f"connector {self.config.name!r}: action {capability!r} failed: {_unwrap_cause(exc)}") from exc
            if preview.isError:
                text = next((b.text for b in preview.content if getattr(b, "text", None)), "")
                raise MCPClientError(f"connector {self.config.name!r}: action {capability!r} errored: {text}")
            token = (preview.structuredContent or {}).get("approval_token")
            if not token:
                raise MCPClientError(f"connector {self.config.name!r}: {capability!r} returned no approval token")
            try:
                async with asyncio.timeout(self.timeout_s):
                    executed = await session.call_tool(_EXECUTE_TOOL, {"approval_token": token})
            except Exception as exc:
                raise MCPClientError(f"connector {self.config.name!r}: execute {capability!r} failed: {_unwrap_cause(exc)}") from exc
            if executed.isError:
                text = next((b.text for b in executed.content if getattr(b, "text", None)), "")
                raise MCPClientError(f"connector {self.config.name!r}: execute {capability!r} errored: {text}")
            return (executed.structuredContent or {}).get("result")

    async def execute_plain(self, capability: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a non-SDK (ecosystem) tool once and return its result. These servers
        have no two-phase preview/execute protocol — there's no dry-run, so calling IS
        executing. The Gateway invokes this only after a human approved the previewed
        call, so the single call here is the approved action."""
        async with self._session() as (session, _init):
            try:
                async with asyncio.timeout(self.timeout_s):
                    result = await session.call_tool(capability, arguments or {})
            except Exception as exc:
                raise MCPClientError(f"connector {self.config.name!r}: action {capability!r} failed: {_unwrap_cause(exc)}") from exc
        if result.isError:
            text = next((b.text for b in result.content if getattr(b, "text", None)), "")
            raise MCPClientError(f"connector {self.config.name!r}: action {capability!r} errored: {text}")
        if result.structuredContent:
            return result.structuredContent
        texts = [b.text for b in result.content if getattr(b, "text", None)]
        return "\n".join(texts) if texts else None

    # -- helpers ----------------------------------------------------------
    def _classify(self, tool: types.Tool) -> DiscoveredTool:
        meta = tool.meta or {}
        ann = tool.annotations
        if _DQ_MUTATES in meta:  # SDK-built connector: authoritative classification
            mutates = bool(meta[_DQ_MUTATES])
            kind_raw = meta.get(_DQ_KIND, "action" if mutates else "resource")
            kind = {
                "resource": ToolKind.RESOURCE,
                "action": ToolKind.ACTION,
                "control": ToolKind.CONTROL,
            }.get(kind_raw, ToolKind.UNKNOWN)
        else:
            # Ecosystem server without dq.* tags: infer from MCP annotations.
            read_only = bool(ann and ann.readOnlyHint)
            destructive = bool(ann and ann.destructiveHint)
            mutates = destructive or not read_only
            kind = ToolKind.RESOURCE if read_only else ToolKind.UNKNOWN
        return DiscoveredTool(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.inputSchema or {},
            kind=kind,
            mutates=mutates,
            connector=self.config.name,
        )

    def _parse_read(self, capability: str, result: types.CallToolResult) -> ReadResult:
        text_blocks = [b.text for b in result.content if getattr(b, "text", None)]
        structured = result.structuredContent or {}

        # SDK connectors return {"records": [{"data", "provenance"}, ...]}.
        if isinstance(structured, dict) and isinstance(structured.get("records"), list):
            records = [
                ReadRecord(data=r.get("data"), provenance=r.get("provenance"))
                for r in structured["records"]
            ]
            return ReadResult(self.config.name, capability, records, has_sdk_provenance=True, text_blocks=text_blocks)

        # Ecosystem server: no provenance envelope. Wrap content as records;
        # the citations layer synthesizes provenance from registry + timestamp.
        if text_blocks:
            records = [ReadRecord(data=tb, provenance=None) for tb in text_blocks]
        elif structured:
            records = [ReadRecord(data=structured, provenance=None)]
        else:
            records = []
        return ReadResult(self.config.name, capability, records, has_sdk_provenance=False, text_blocks=text_blocks)


async def gather_reads(*reads: Awaitable[ReadResult]) -> list[ReadResult | MCPClientError]:
    """Run independent reads in parallel so total latency is bounded by the
    slowest connector, not the sum (guide §4 perf note). Failures are returned
    in place (not raised) so one bad connector doesn't sink the others."""
    results = await asyncio.gather(*reads, return_exceptions=True)
    out: list[ReadResult | MCPClientError] = []
    for r in results:
        if isinstance(r, ReadResult):
            out.append(r)
        elif isinstance(r, MCPClientError):
            out.append(r)
        elif isinstance(r, Exception):
            out.append(MCPClientError(str(r)))
    return out
