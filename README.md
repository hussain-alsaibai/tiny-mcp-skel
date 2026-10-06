# tiny-mcp-skel - Stdlib-Only MCP Server Skeleton

> **Like FastMCP, but in 150 LOC. Zero external runtime dependencies.**

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero Runtime Deps](https://img.shields.io/badge/runtime-deps-tiny--router%20%2B%20tiny--validator-brightgreen.svg)](#dependencies)
[![Part of the tiny-* ecosystem](https://img.shields.io/badge/tiny--*-ecosystem-purple.svg)](#ecosystem)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](tiny_mcp_skel.py)

`tiny-mcp-skel` is a single-file, stdlib-only Model Context Protocol (MCP) server skeleton. The whole skeleton is under 200 LOC of executable code, and runs over stdio (the default MCP transport) out of the box.

The skeleton is built from three tiny-* primitives:

- **tiny-router** (v0.6.0+) - request dispatch uses a tiny-router blueprint
- **tiny-validator** (v0.4.0+) - tool argument validation
- **tiny-validator-mcp** (v0.5.0+) - server manifest validation against the McpServer schema
- **tiny-router-sse** (v0.7.0+, optional) - SSE overlay for streaming responses

## Quick Start

```python
from tiny_mcp_skel import make_server, run_stdio
from tiny_validator import Schema, String

server = make_server(name="echo-mcp", version="0.1.0", title="Echo MCP")

@server.tool(
    name="echo",
    description="Echo the input back to the caller.",
    input_schema=Schema({"text": String(min_length=1)}),
)
def echo_handler(params):
    return {"content": [{"type": "text", "text": params["text"]}]}

if __name__ == "__main__":
    run_stdio(server)
```

## Features

- **Zero external runtime dependencies** - depends only on `tiny-router` and `tiny-validator`
- **Single file** - drop `tiny_mcp_skel.py` anywhere
- **JSON-RPC 2.0 over stdio** - the default MCP transport
- **HTTP transport** - `server.as_router()` returns a tiny-router `Router` with `GET /openapi.json` and `POST /mcp`
- **Eager manifest validation** - tool registrations rebuild the McpServer manifest and run `validate_mcp_manifest`; a typo in a tool name fails fast
- **Standard MCP methods** - `initialize`, `tools/list`, `tools/call`, `ping`
- **Streaming-ready** - integrates with `tiny-router-sse` for SSE-aware OpenAPI export

## Installation

```bash
pip install tiny-router tiny-validator
# then drop tiny_mcp_skel.py into your project, or:
pip install tiny-mcp-skel  # once published
```

## Why this exists

The Model Context Protocol server ecosystem has been wildly inconsistent on packaging. Through August 2026, the average MCP server was either a 1,400-LOC FastAPI app with an `sse-starlette` wrapper, or a 200-LOC ad-hoc stdlib script.

The September 2026 MCP-Registry v1 schema forced consolidation on three things:
- A `mcp.server.json` manifest with `name`, `version`, `tools: [{name, description, inputSchema}]`
- An `initialize` handler that returns server metadata + supported protocol versions
- A `tools/list` handler that emits the registered tools in the registry-expected shape

The stdlib-first MCP server skeletons that landed that week (`mcpskel/zero`, `pymcp-min`, `mcpbox/lite`) are all essentially the same shape - and `tiny-mcp-skel` is the most concise of them. The full server is under 200 LOC, the test suite is 30 tests, and the only runtime dependencies are two other tiny-* repos that together add another ~70 KB of single-file code.

## API

### `make_server(*, name, version, title=None, description=None) -> McpSkelServer`

Create a new server. Validates `name` against `SERVER_NAME_PATTERN` and `version` against SemVer.

### `server.tool(*, name, description, input_schema=None, annotations=None)`

Decorator that registers a tool. The handler receives a `dict` of validated params and must return a dict with a `content` key (the standard MCP response shape):

```python
@server.tool(
    name="add",
    description="Add two numbers.",
    input_schema=Schema({"a": Integer(), "b": Integer()}),
)
def add_handler(params):
    return {"content": [{"type": "text", "text": str(params["a"] + params["b"])}]}
```

### `server.handle(request)`

Dispatch a single `McpRequest` and return an `McpResponse`. The methods supported are `initialize`, `tools/list`, `tools/call`, `ping`. Unknown methods return a JSON-RPC 2.0 error with code -32601.

### `server.as_router() -> Router`

Return a tiny-router `Router` exposing:
- `GET /openapi.json` - OpenAPI 3.1 spec with the server's MCP manifest under `x-mcp-server`
- `POST /mcp` - JSON-RPC 2.0 endpoint (alternative to stdio)

### `run_stdio(server)`

Read newline-delimited JSON-RPC 2.0 frames from stdin, write responses to stdout. Blocking; the MCP spec recommends line-buffered output, so we flush after every response.

## Ecosystem

- [**tiny-router**](https://github.com/hussain-alsaibai/tiny-router) - zero-dependency HTTP router (76K req/s)
- [**tiny-validator**](https://github.com/hussain-alsaibai/tiny-validator) - zero-dependency input validation (247K val/s)
- [**tiny-validator-mcp**](https://github.com/hussain-alsaibai/tiny-validator) - MCP manifest schemas (sidecar, v0.5.0+)
- [**tiny-router-sse**](https://github.com/hussain-alsaibai/tiny-router) - SSE sidecar (v0.7.0+)
- [**tiny-mcp**](https://github.com/hussain-alsaibai/tiny-mcp) - the original MCP server library
- [**tiny-mcp-registry**](https://github.com/hussain-alsaibai/tiny-mcp-registry) - MCP registry client

## License

MIT
