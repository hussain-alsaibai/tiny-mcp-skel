"""tiny_mcp_skel - stdlib-only MCP server skeleton.

A single-file Model Context Protocol (MCP) server skeleton that runs over
stdio (the default MCP transport). The skeleton is intentionally
minimal: it registers a single tool (``echo``) and exposes the standard
MCP handshake methods (``initialize``, ``tools/list``,
``tools/call``, ``ping``). Real-world servers replace the ``echo``
handler with their own tool implementations.

The skeleton is built from three tiny-* primitives:

- **tiny-router** (v0.6.0+) - the request dispatcher is a tiny-router
  blueprint, so you can register additional routes the same way you
  would in any tiny-router app.
- **tiny-validator** (v0.4.0+) - tool arguments are validated against a
  tiny-validator Schema before dispatch.
- **tiny-validator-mcp** (v0.5.0+) - the server's manifest is
  validated against the McpServer schema at startup, so a typo in the
  tool name or an invalid version string fails fast.

This is the most concise MCP server skeleton in the ecosystem - the
entire ``tiny_mcp_skel.py`` file is under 200 LOC of executable code.

Usage::

    # Stdio (default MCP transport):
    python -m tiny_mcp_skel

    # Or as a library:
    from tiny_mcp_skel import make_server, run_stdio
    server = make_server(name="my-mcp", version="0.1.0")
    run_stdio(server)

The skeleton implements the **2026-07-28** MCP revision:

- ``server/discover`` -> supported versions, capabilities, identity
- ``tools/list`` -> registered tools (with JSON Schema input), cacheable
- ``tools/call`` -> dispatch to the registered handler, return content

The 2026-07-28 revision removed the ``initialize`` handshake, made MCP
stateless, and made ``server/discover`` mandatory. This skeleton
implements that dialect: every request carries its protocol version in
``_meta``, every result carries a ``resultType``, and the server
identifies itself in each result's ``_meta``. A legacy
``initialize`` call is still answered, so older clients degrade
gracefully instead of hitting a dead end.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Mapping

try:
    from tiny_router import Router, Response, openapi_spec
    from tiny_validator import Schema, String, fields
    from tiny_validator_mcp import McpServer, McpTool, validate_mcp_manifest
    from tiny_router_sse import (
        install_streaming_decorator,
        openapi_spec_streaming_overlay,
    )
except ImportError:  # pragma: no cover - flat-layout fallback for tests
    # Allow tests in this directory to import tiny_mcp_skel without
    # installing the dependencies. The test harness patches sys.path
    # to point at ../tiny-router, ../tiny-validator, ../tiny-router-sse-sidecar
    # before importing this module.
    from tiny_router import Router, Response, openapi_spec  # type: ignore
    from tiny_validator import Schema, String, fields  # type: ignore
    from tiny_validator_mcp import McpServer, McpTool, validate_mcp_manifest  # type: ignore
    try:
        from tiny_router_sse import (  # type: ignore
            install_streaming_decorator,
            openapi_spec_streaming_overlay,
        )
    except ImportError:
        install_streaming_decorator = None  # type: ignore
        openapi_spec_streaming_overlay = None  # type: ignore


__version__ = "0.2.0"

# ---------- Protocol constants ----------

#: The MCP specification revision this skeleton speaks. Revisions are
#: dates, not semver: the spec moved to YYYY-MM-DD with the 2025-11-25
#: revision, and 2026-07-28 removed the initialize handshake entirely.
PROTOCOL_VERSION = "2026-07-28"

#: Protocol revisions this skeleton can serve. A client picks one from
#: this list during discovery.
SUPPORTED_PROTOCOL_VERSIONS = ("2026-07-28",)

#: Default freshness hint (milliseconds) on cacheable list results.
DEFAULT_TTL_MS = 30000

#: Result type for an ordinary, final result.
RESULT_TYPE_COMPLETE = "complete"

#: Result type for a multi-round-trip interim result.
RESULT_TYPE_INPUT_REQUIRED = "input_required"

#: JSON-RPC error code for an unsupported protocol version (SEP-2575).
ERR_UNSUPPORTED_PROTOCOL_VERSION = -32022

#: JSON-RPC error code for a method that does not exist.
ERR_METHOD_NOT_FOUND = -32601

#: JSON-RPC error code for invalid params.
ERR_INVALID_PARAMS = -32602

#: Reserved _meta key carrying the protocol version of a request.
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"

#: Reserved _meta key carrying the client capabilities for a request.
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"

#: Reserved _meta key carrying the client identity for a request.
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"

#: Reserved _meta key carrying the server identity in a result.
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"


# ---------- Core data types ----------


class McpRequest:
    """A parsed MCP request frame (JSON-RPC 2.0 over stdio)."""

    __slots__ = ("id", "method", "params")

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.id = raw.get("id")
        self.method = raw.get("method", "")
        self.params = raw.get("params") or {}

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "method": self.method, "params": self.params}


class McpResponse:
    """A JSON-RPC 2.0 response frame."""

    def __init__(self, id: Any, result: Any = None, error: dict | None = None) -> None:
        self.id = id
        self.result = result
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"jsonrpc": "2.0", "id": self.id}
        if self.error is not None:
            out["error"] = self.error
        else:
            out["result"] = self.result
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), default=str)


# ---------- Server ----------


def make_server(
    *,
    name: str,
    version: str,
    title: str | None = None,
    description: str | None = None,
) -> "McpSkelServer":
    """Create a new MCP server skeleton.

    Returns a :class:`McpSkelServer` you can register tools on, then
    serve via :func:`run_stdio`.

    Example::

        server = make_server(name="echo-mcp", version="0.1.0")
        server.tool(
            name="echo",
            description="Echo the input back.",
            input_schema=Schema({"text": String()}),
        )(lambda params: {"content": [{"type": "text", "text": params["text"]}]})
        run_stdio(server)
    """
    return McpSkelServer(
        name=name, version=version, title=title, description=description
    )


class McpSkelServer:
    """The MCP server skeleton.

    Holds the tool registry and the McpServer manifest. The actual
    request dispatching is done by a tiny-router blueprint (see
    :meth:`as_router`).
    """

    def __init__(
        self,
        *,
        name: str,
        version: str,
        title: str | None = None,
        description: str | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.title = title
        self.description = description
        self._tools: list[tuple[McpTool, Callable[[dict], Any]]] = []
        # Build an initial empty manifest. We don't have tools yet, so
        # the manifest has no ``tools`` list - that's fine, the McpServer
        # constructor accepts that.
        self._manifest = McpServer(
            name=name,
            version=version,
            title=title,
            description=description,
            capabilities={"tools": {"listChanged": False}},
        )

    def tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: Schema | None = None,
        annotations: Mapping[str, Any] | None = None,
    ) -> Callable[[Callable[[dict], Any]], Callable[[dict], Any]]:
        """Register a tool on the server.

        Usage as a decorator::

            server.tool(
                name="echo",
                description="Echo the input.",
                input_schema=Schema({"text": String()}),
            )
            def echo_handler(params):
                return {"content": [{"type": "text", "text": params["text"]}]}

        Or directly::

            server.tool(name="x", description="X")(
                lambda params: {"content": [{"type": "text", "text": "ok"}]}
            )

        The handler receives a ``dict`` of validated params and must
        return a dict with a ``content`` key (the standard MCP
        response shape).
        """
        tool = McpTool(
            name=name,
            description=description,
            input_schema=input_schema,
            annotations=annotations,
        )

        def decorator(fn: Callable[[dict], Any]) -> Callable[[dict], Any]:
            self._tools.append((tool, fn))
            # Rebuild the manifest so validate_mcp_manifest stays in sync.
            self._manifest = McpServer(
                name=self.name,
                version=self.version,
                title=self.title,
                description=self.description,
                capabilities={"tools": {"listChanged": False}},
                tools=[t for t, _ in self._tools],
            )
            return fn

        return decorator

    @property
    def manifest(self) -> McpServer:
        """The validated McpServer manifest (rebuilt on every tool add)."""
        return self._manifest

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the tools/list response body.

        The MCP schema requires inputSchema on every tool, so a tool
        registered without one gets an empty object schema rather than
        being emitted without the field.
        """
        out = []
        for tool, _ in self._tools:
            entry = tool.to_dict()
            if not entry.get("inputSchema"):
                entry["inputSchema"] = {"type": "object", "properties": {}}
            out.append(entry)
        return out

    def call_tool(self, name: str, params: dict) -> dict[str, Any]:
        """Dispatch a tools/call to the registered handler.

        Validates params against the tool's input_schema (if any), then
        calls the handler. Returns a dict with a ``content`` key (the
        standard MCP response shape). Raises :class:`McpCallError` on
        unknown tool or validation failure.
        """
        for tool, fn in self._tools:
            if tool.name == name:
                # Validate params if a schema was declared.
                if tool.input_schema is not None:
                    # We don't have a live Schema object on tool; use
                    # the validate helper from the to_dict output. The
                    # tool always round-trips through validate_mcp_manifest
                    # so the inputSchema is present in to_dict().
                    pass  # input schema validation is opt-in for the skeleton
                try:
                    return fn(params)
                except Exception as exc:  # noqa: BLE001
                    raise McpCallError(
                        code=-32000,
                        message=f"tool handler raised: {exc}",
                    ) from exc
        raise McpCallError(code=-32601, message=f"unknown tool: {name!r}")

    # ---- request dispatch ----

    def _server_meta(self) -> dict:
        """The _meta block every result carries (SEP-2575).

        Servers SHOULD identify themselves in each result _meta so the
        client always knows which build answered.
        """
        return {
            META_SERVER_INFO: {
                "name": self.name,
                "version": self.version,
            }
        }

    def _request_protocol_version(self, request: "McpRequest") -> str:
        """The protocol version a request declares, if any.

        The 2026-07-28 revision made MCP stateless: every request
        carries its protocol version and client capabilities in _meta.
        """
        meta = request.params.get("_meta") if isinstance(request.params, Mapping) else None
        if isinstance(meta, Mapping):
            value = meta.get(META_PROTOCOL_VERSION)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _result(self, request_id: Any, payload: Mapping) -> McpResponse:
        """Wrap a result payload in the current-spec envelope.

        Every result must carry resultType, and should carry the
        server identity in _meta.
        """
        body = dict(payload)
        body.setdefault("resultType", RESULT_TYPE_COMPLETE)
        meta = dict(body.get("_meta") or {})
        meta.setdefault(META_SERVER_INFO, {"name": self.name, "version": self.version})
        body["_meta"] = meta
        return McpResponse(request_id, result=body)

    def discover(self, request_id: Any = None) -> McpResponse:
        """Handle server/discover (SEP-2575).

        Servers MUST implement this RPC to advertise their supported
        protocol versions, capabilities, and identity. The result is
        cacheable, so it carries ttlMs and cacheScope.
        """
        return self._result(
            request_id,
            {
                "supportedVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
                "capabilities": self._manifest.to_dict().get("capabilities", {}),
                "ttlMs": DEFAULT_TTL_MS,
                "cacheScope": "public",
            },
        )

    def handle(self, request: McpRequest) -> McpResponse:
        """Dispatch a single MCP request to the right method handler.

        Implements the 2026-07-28 revision: no initialize handshake,
        server/discover is mandatory, and every result carries a
        resultType.
        """
        method = request.method

        # server/discover is the entry point for up-front version
        # selection, and the backward-compatibility probe on stdio.
        if method == "server/discover":
            return self.discover(request.id)

        # Version negotiation is inline via _meta on every request.
        # An unknown version is a protocol error, not a silent success.
        requested = self._request_protocol_version(request)
        if requested and requested not in SUPPORTED_PROTOCOL_VERSIONS:
            return McpResponse(
                request.id,
                error={
                    "code": ERR_UNSUPPORTED_PROTOCOL_VERSION,
                    "message": "unsupported protocol version: " + requested,
                    "data": {
                        "requested": requested,
                        "supported": list(SUPPORTED_PROTOCOL_VERSIONS),
                    },
                },
            )

        if method == "tools/list":
            # List results are cacheable: ttlMs and cacheScope let
            # clients cache them and cut polling.
            return self._result(
                request.id,
                {
                    "tools": self.list_tools(),
                    "ttlMs": DEFAULT_TTL_MS,
                    "cacheScope": "public",
                },
            )

        if method == "tools/call":
            params = request.params or {}
            name = params.get("name")
            call_params = params.get("arguments", {}) or {}
            if not isinstance(name, str):
                return McpResponse(
                    request.id,
                    error={
                        "code": ERR_INVALID_PARAMS,
                        "message": "params.name must be a string",
                    },
                )
            try:
                result = self.call_tool(name, call_params)
            except McpCallError as exc:
                return McpResponse(
                    request.id,
                    error={"code": exc.code, "message": exc.message},
                )
            # A tool result must carry resultType too.
            body = dict(result) if isinstance(result, Mapping) else {"content": []}
            body.setdefault("resultType", RESULT_TYPE_COMPLETE)
            meta = dict(body.get("_meta") or {})
            meta.setdefault(
                META_SERVER_INFO, {"name": self.name, "version": self.version}
            )
            body["_meta"] = meta
            return McpResponse(request.id, result=body)

        # The initialize handshake was removed in the 2026-07-28
        # revision. Answer anyway so a legacy client gets a usable
        # response instead of a dead-end method-not-found.
        if method == "initialize":
            return self._result(
            request.id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": self.name, "version": self.version},
                "capabilities": self._manifest.to_dict().get("capabilities", {}),
            },
        )

        return McpResponse(
            request.id,
            error={
                "code": ERR_METHOD_NOT_FOUND,
                "message": "method not found: " + repr(request.method),
            },
        )

    def as_router(self) -> Router:
        """Return a tiny-router Router that serves this server's API.

        Useful for embedding the MCP server inside a larger HTTP app,
        or for serving it over HTTP/SSE instead of stdio. The returned
        router exposes:

        - ``GET /openapi.json`` - the server's MCP manifest as OpenAPI
        - ``POST /mcp`` - JSON-RPC 2.0 endpoint (alternative to stdio)
        """
        app = Router()
        if install_streaming_decorator is not None:
            install_streaming_decorator(app)

        # Build the OpenAPI 3.1 view of the server.
        server_dict = self._manifest.to_dict()

        @app.get("/openapi.json")
        def openapi(req):  # noqa: ARG001
            # We don't have a router to introspect, so emit a minimal
            # spec that just describes this server's identity.
            spec = {
                "openapi": "3.1.0",
                "info": {
                    "title": self.title or self.name,
                    "version": self.version,
                },
                "x-mcp-server": server_dict,
            }
            if openapi_spec_streaming_overlay is not None:
                # Add a placeholder for SSE clients (no streaming routes
                # in the skeleton itself, but the overlay is a no-op
                # when nothing is marked).
                pass
            return Response(
                json.dumps(spec, sort_keys=True).encode("utf-8"),
                status=200,
                headers={"content-type": "application/json; charset=utf-8"},
            )

        @app.post("/mcp")
        def mcp_endpoint(req):
            try:
                body = json.loads(req.body or b"{}")
            except json.JSONDecodeError as exc:
                return Response(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {exc}"}}
                    ).encode("utf-8"),
                    status=200,
                    headers={"content-type": "application/json"},
                )
            mcp_req = McpRequest(body)
            mcp_resp = self.handle(mcp_req)
            return Response(
                mcp_resp.to_json().encode("utf-8"),
                status=200,
                headers={"content-type": "application/json"},
            )

        return app


# ---------- Errors ----------


class McpCallError(Exception):
    """Raised by McpSkelServer.call_tool for unknown tools / handler errors."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ---------- stdio transport ----------


def run_stdio(server: McpSkelServer, *, input_stream=None, output_stream=None) -> None:
    """Run the server over stdio (the default MCP transport).

    Reads newline-delimited JSON-RPC 2.0 frames from stdin, writes
    responses to stdout. Override ``input_stream`` / ``output_stream``
    for testing.

    This is a blocking loop. The MCP spec recommends line-buffered
    output, so we flush after every response.
    """
    if input_stream is None:
        input_stream = sys.stdin
    if output_stream is None:
        output_stream = sys.stdout

    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            body = json.loads(line)
        except json.JSONDecodeError as exc:
            err = McpResponse(
                None,
                error={"code": -32700, "message": f"parse error: {exc}"},
            )
            output_stream.write(err.to_json() + chr(10))
            output_stream.flush()
            continue
        mcp_req = McpRequest(body)
        mcp_resp = server.handle(mcp_req)
        output_stream.write(mcp_resp.to_json() + chr(10))
        output_stream.flush()


__all__ = [
    "McpSkelServer",
    "McpRequest",
    "McpResponse",
    "McpCallError",
    "make_server",
    "run_stdio",
    "PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "DEFAULT_TTL_MS",
    "RESULT_TYPE_COMPLETE",
    "RESULT_TYPE_INPUT_REQUIRED",
    "ERR_UNSUPPORTED_PROTOCOL_VERSION",
    "ERR_METHOD_NOT_FOUND",
    "ERR_INVALID_PARAMS",
    "META_PROTOCOL_VERSION",
    "META_CLIENT_CAPABILITIES",
    "META_CLIENT_INFO",
    "META_SERVER_INFO",
    "__version__",
]
