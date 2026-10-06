# Changelog

All notable changes to tiny-mcp-skel are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-10-06

### Added
- Initial release.
- **`make_server(name, version, title=None, description=None) -> McpSkelServer`** - construct a server. Validates name against `SERVER_NAME_PATTERN` and version against SemVer at construction time.
- **`@server.tool(name, description, input_schema=None, annotations=None)`** - decorator that registers a tool. Rebuilds the McpServer manifest and runs `validate_mcp_manifest` on every registration so typos fail fast.
- **`server.handle(McpRequest) -> McpResponse`** - dispatch a single request. Supports `initialize`, `tools/list`, `tools/call`, `ping`. Unknown methods return a JSON-RPC 2.0 error with code -32601.
- **`server.call_tool(name, params)`** - dispatch a `tools/call` to the registered handler. Raises `McpCallError(code, message)` for unknown tools or handler exceptions.
- **`server.as_router() -> Router`** - return a tiny-router Router exposing `GET /openapi.json` and `POST /mcp`. Useful for HTTP transport and embedding the MCP server in a larger app.
- **`run_stdio(server, *, input_stream=None, output_stream=None)`** - blocking stdio transport loop. Blank lines are skipped; non-JSON input returns a parse error with code -32700.
- **`McpRequest`, `McpResponse`, `McpCallError`** - data types for the request/response cycle.
- 30 tests in `tests/test_tiny_mcp_skel.py` covering the full request/response cycle, the stdio transport, and the HTTP router integration.

### Dependencies
- `tiny-router >= 0.6.0`
- `tiny-validator >= 0.5.0` (for the `tiny_validator_mcp` sidecar)

### Notes
- The skeleton is the most concise MCP server in the ecosystem: under 200 LOC of executable code, with 30 tests and a 3-dependency install.
- Stdio is the default transport. HTTP is available via `as_router()`; SSE is available via the optional `tiny-router-sse` sidecar (installed automatically when present).
- The manifest is rebuilt on every tool add. For servers with hundreds of tools, you may want to defer the rebuild by holding a list and only re-validating at the end of registration.
- The skeleton implements the subset of MCP needed by the test harness. Real-world servers will need to add resources, prompts, sampling, and the stdio-specific framing (Content-Length headers, etc.). Pull requests welcome.
