"""Tests for tiny_mcp_skel (MCP server skeleton)."""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO

# Make the tiny-* siblings importable when they are checked out next to
# this repository (local development). In CI they are pip-installed, so the
# path below usually does not exist and the installed packages are used.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_HERE)
for sub in ("tiny-router", "tiny-validator"):
    _p = os.path.join(_PARENT, sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from tiny_mcp_skel import (  # noqa: E402
    McpCallError,
    McpRequest,
    McpResponse,
    McpSkelServer,
    make_server,
    run_stdio,
)
from tiny_validator import Schema, String, Integer  # noqa: E402
from tiny_validator_mcp import McpServer, validate_mcp_manifest  # noqa: E402


class TestMcpRequest(unittest.TestCase):
    def test_basic(self):
        r = McpRequest({"id": 1, "method": "ping", "params": {}})
        self.assertEqual(r.id, 1)
        self.assertEqual(r.method, "ping")
        self.assertEqual(r.params, {})

    def test_missing_params(self):
        r = McpRequest({"id": 1, "method": "ping"})
        self.assertEqual(r.params, {})

    def test_to_dict(self):
        r = McpRequest({"id": 7, "method": "x", "params": {"a": 1}})
        self.assertEqual(r.to_dict(), {"id": 7, "method": "x", "params": {"a": 1}})


class TestMcpResponse(unittest.TestCase):
    def test_result(self):
        r = McpResponse(1, result={"ok": True})
        d = r.to_dict()
        self.assertEqual(d["jsonrpc"], "2.0")
        self.assertEqual(d["id"], 1)
        self.assertEqual(d["result"], {"ok": True})
        self.assertNotIn("error", d)

    def test_error(self):
        r = McpResponse(2, error={"code": -32601, "message": "no method"})
        d = r.to_dict()
        self.assertEqual(d["error"]["code"], -32601)
        self.assertNotIn("result", d)

    def test_to_json(self):
        r = McpResponse(3, result="ok")
        j = r.to_json()
        self.assertIn('"jsonrpc":"2.0"', j)
        self.assertIn('"id":3', j)
        # Round-trips through json.loads
        parsed = json.loads(j)
        self.assertEqual(parsed["result"], "ok")


class TestMakeServer(unittest.TestCase):
    def test_minimal(self):
        s = make_server(name="x", version="0.1.0")
        self.assertEqual(s.name, "x")
        self.assertEqual(s.version, "0.1.0")
        self.assertEqual(s.title, None)
        self.assertEqual(s.description, None)

    def test_with_title(self):
        s = make_server(name="x", version="0.1.0", title="X")
        self.assertEqual(s.title, "X")

    def test_invalid_name_raises(self):
        with self.assertRaises(Exception):
            make_server(name="X!", version="0.1.0")


class TestServerTool(unittest.TestCase):
    def test_register_tool(self):
        s = make_server(name="t", version="0.1.0")
        @s.tool(name="echo", description="echo")
        def echo(params):
            return {"content": [{"type": "text", "text": params["text"]}]}
        self.assertEqual([t.name for t, _ in s._tools], ["echo"])

    def test_register_multiple_tools(self):
        s = make_server(name="t", version="0.1.0")
        @s.tool(name="a", description="A")
        def a(params):
            return {"content": []}
        @s.tool(name="b", description="B")
        def b(params):
            return {"content": []}
        self.assertEqual([t.name for t, _ in s._tools], ["a", "b"])

    def test_manifest_rebuilt_on_tool_add(self):
        s = make_server(name="t", version="0.1.0")
        m_before = s.manifest.to_dict()
        self.assertNotIn("tools", m_before)
        @s.tool(name="echo", description="echo")
        def echo(params):
            return {"content": []}
        m_after = s.manifest.to_dict()
        self.assertIn("tools", m_after)
        self.assertEqual(len(m_after["tools"]), 1)

    def test_manifest_validates(self):
        s = make_server(name="t", version="0.1.0")
        @s.tool(name="echo", description="echo")
        def echo(params):
            return {"content": []}
        errors = validate_mcp_manifest(s.manifest.to_dict())
        self.assertEqual(errors, [])


class TestCallTool(unittest.TestCase):
    def setUp(self):
        self.s = make_server(name="t", version="0.1.0")
        @self.s.tool(name="echo", description="echo")
        def echo(params):
            return {"content": [{"type": "text", "text": params["text"]}]}
        @self.s.tool(name="add", description="add")
        def add(params):
            return {"content": [{"type": "text", "text": str(params["a"] + params["b"])}]}

    def test_call_known_tool(self):
        result = self.s.call_tool("echo", {"text": "hi"})
        self.assertEqual(result["content"][0]["text"], "hi")

    def test_call_add(self):
        result = self.s.call_tool("add", {"a": 2, "b": 3})
        self.assertEqual(result["content"][0]["text"], "5")

    def test_call_unknown_tool(self):
        with self.assertRaises(McpCallError):
            self.s.call_tool("ghost", {})

    def test_call_handler_exception(self):
        @self.s.tool(name="boom", description="boom")
        def boom(params):
            raise ValueError("kaboom")
        with self.assertRaises(McpCallError):
            self.s.call_tool("boom", {})


class TestHandle(unittest.TestCase):
    def setUp(self):
        self.s = make_server(name="t", version="0.1.0")
        @self.s.tool(name="echo", description="echo")
        def echo(params):
            return {"content": [{"type": "text", "text": params["text"]}]}

    def test_initialize(self):
        r = self.s.handle(McpRequest({"id": 1, "method": "initialize", "params": {}}))
        self.assertIn("serverInfo", r.result)
        self.assertEqual(r.result["serverInfo"]["name"], "t")
        self.assertEqual(r.result["serverInfo"]["version"], "0.1.0")
        self.assertIn("protocolVersion", r.result)

    def test_tools_list(self):
        r = self.s.handle(McpRequest({"id": 2, "method": "tools/list", "params": {}}))
        self.assertEqual(len(r.result["tools"]), 1)
        self.assertEqual(r.result["tools"][0]["name"], "echo")

    def test_tools_call(self):
        r = self.s.handle(McpRequest({"id": 3, "method": "tools/call", "params": {"name": "echo", "arguments": {"text": "x"}}}))
        self.assertEqual(r.result["content"][0]["text"], "x")

    def test_ping_is_removed_from_the_protocol(self):
        # ping was removed as a core method in the 2026-07-28 revision.
        r = self.s.handle(McpRequest({"id": 4, "method": "ping", "params": {}}))
        self.assertIsNone(r.result)
        self.assertEqual(r.error["code"], -32601)

    def test_server_discover(self):
        r = self.s.handle(
            McpRequest({"id": 40, "method": "server/discover", "params": {}})
        )
        self.assertIn("2026-07-28", r.result["supportedVersions"])
        self.assertEqual(r.result["resultType"], "complete")
        self.assertIn("capabilities", r.result)
        # Discover is cacheable, so it carries ttlMs and cacheScope.
        self.assertIn("ttlMs", r.result)
        self.assertIn("cacheScope", r.result)

    def test_server_discover_requires_params(self):
        # The schema marks params as required on DiscoverRequest.
        r = self.s.handle(
            McpRequest({"id": 41, "method": "server/discover", "params": {}})
        )
        self.assertIsNotNone(r.result)

    def test_every_result_carries_result_type(self):
        for method, params in (
            ("server/discover", {}),
            ("tools/list", {}),
            (
                "tools/call",
                {"name": "echo", "arguments": {"text": "x"}},
            ),
        ):
            r = self.s.handle(McpRequest({"id": 9, "method": method, "params": params}))
            self.assertEqual(r.result["resultType"], "complete", method)

    def test_every_result_carries_server_info_meta(self):
        r = self.s.handle(McpRequest({"id": 10, "method": "tools/list", "params": {}}))
        meta = r.result["_meta"]
        self.assertEqual(
            meta["io.modelcontextprotocol/serverInfo"],
            {"name": "t", "version": "0.1.0"},
        )

    def test_tools_list_is_cacheable(self):
        r = self.s.handle(McpRequest({"id": 11, "method": "tools/list", "params": {}}))
        self.assertIn("ttlMs", r.result)
        self.assertEqual(r.result["cacheScope"], "public")

    def test_supported_protocol_version_in_meta_is_accepted(self):
        r = self.s.handle(
            McpRequest(
                {
                    "id": 12,
                    "method": "tools/list",
                    "params": {
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "2026-07-28"
                        }
                    },
                }
            )
        )
        self.assertIsNone(r.error)

    def test_unsupported_protocol_version_is_rejected(self):
        r = self.s.handle(
            McpRequest(
                {
                    "id": 13,
                    "method": "tools/list",
                    "params": {
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "1999-01-01"
                        }
                    },
                }
            )
        )
        self.assertEqual(r.error["code"], -32022)
        self.assertEqual(r.error["data"]["requested"], "1999-01-01")
        self.assertIn("2026-07-28", r.error["data"]["supported"])

    def test_legacy_initialize_still_answered(self):
        # Legacy clients must degrade gracefully, not hit a dead end.
        r = self.s.handle(
            McpRequest({"id": 14, "method": "initialize", "params": {}})
        )
        self.assertEqual(r.result["protocolVersion"], "2026-07-28")
        self.assertEqual(r.result["serverInfo"]["name"], "t")
        self.assertEqual(r.result["resultType"], "complete")

    def test_unknown_method(self):
        r = self.s.handle(McpRequest({"id": 5, "method": "x/y"}))
        self.assertEqual(r.error["code"], -32601)

    def test_tools_call_invalid_params(self):
        r = self.s.handle(McpRequest({"id": 6, "method": "tools/call", "params": {}}))
        self.assertEqual(r.error["code"], -32602)

    def test_tools_call_unknown_tool(self):
        r = self.s.handle(McpRequest({"id": 7, "method": "tools/call", "params": {"name": "ghost"}}))
        self.assertEqual(r.error["code"], -32601)


class TestStdioTransport(unittest.TestCase):
    def setUp(self):
        self.s = make_server(name="t", version="0.1.0")
        @self.s.tool(name="echo", description="echo")
        def echo(params):
            return {"content": [{"type": "text", "text": params["text"]}]}

    def test_basic_loop(self):
        inp = StringIO(
            chr(10).join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "echo", "arguments": {"text": "hi"}}}),
            ]) + chr(10)
        )
        out = StringIO()
        run_stdio(self.s, input_stream=inp, output_stream=out)
        lines = [l for l in out.getvalue().split(chr(10)) if l]
        self.assertEqual(len(lines), 2)
        r1 = json.loads(lines[0])
        r2 = json.loads(lines[1])
        self.assertIn("2026-07-28", r1["result"]["supportedVersions"])
        self.assertEqual(r2["result"]["content"][0]["text"], "hi")

    def test_blank_lines_skipped(self):
        inp = StringIO(
            chr(10)
            + chr(10)
            + json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}}
            )
            + chr(10)
        )
        out = StringIO()
        run_stdio(self.s, input_stream=inp, output_stream=out)
        self.assertEqual(len([l for l in out.getvalue().split(chr(10)) if l]), 1)

    def test_parse_error(self):
        inp = StringIO("not json" + chr(10))
        out = StringIO()
        run_stdio(self.s, input_stream=inp, output_stream=out)
        lines = [l for l in out.getvalue().split(chr(10)) if l]
        self.assertEqual(len(lines), 1)
        r = json.loads(lines[0])
        self.assertEqual(r["error"]["code"], -32700)


class TestAsRouter(unittest.TestCase):
    def test_returns_router(self):
        from tiny_router import Router
        s = make_server(name="t", version="0.1.0")
        @s.tool(name="echo", description="echo")
        def echo(params):
            return {"content": []}
        router = s.as_router()
        self.assertIsInstance(router, Router)
        # The router should have /openapi.json and POST /mcp
        paths = [r["pattern"] for r in router.get_routes()]
        self.assertTrue(any("openapi" in p for p in paths))
        self.assertTrue(any("mcp" in p for p in paths))

    def test_router_openapi_endpoint(self):
        s = make_server(name="t", version="0.1.0", title="T")
        @s.tool(name="echo", description="echo")
        def echo(params):
            return {"content": []}
        router = s.as_router()
        # Use the router's WSGI adapter to fetch /openapi.json
        from urllib.parse import urlparse
        import json as _json

        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        body = b"".join(router.wsgi(
            {"REQUEST_METHOD": "GET", "PATH_INFO": "/openapi.json", "QUERY_STRING": "", "wsgi.input": type("I", (), {"read": lambda self, n: b""})()},
            start_response,
        ))
        spec = _json.loads(body)
        self.assertEqual(spec["info"]["title"], "T")
        self.assertIn("x-mcp-server", spec)
        self.assertEqual(spec["x-mcp-server"]["name"], "t")

    def test_router_mcp_endpoint(self):
        s = make_server(name="t", version="0.1.0")
        @s.tool(name="echo", description="echo")
        def echo(params):
            return {"content": [{"type": "text", "text": params["text"]}]}
        router = s.as_router()
        import json as _json

        class FakeInput:
            def __init__(self, data):
                self.data = data
            def read(self, n):
                return self.data

        body = b"".join(router.wsgi(
            {
                "REQUEST_METHOD": "POST",
                "PATH_INFO": "/mcp",
                "QUERY_STRING": "",
                "CONTENT_LENGTH": str(len(b'{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{}}')),
                "wsgi.input": FakeInput(b'{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{}}'),
            },
            lambda s, h: None,
        ))
        r = _json.loads(body)
        self.assertIn("2026-07-28", r["result"]["supportedVersions"])


# ---------- Schema conformance ----------

# The authoritative MCP JSON Schema for the revision this skeleton
# speaks. Pinning it in the test suite means a response shape can never
# silently drift from the spec again.
#
# The schema lives in the upstream repository:
#   https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2026-07-28/schema.json
#
# The test is skipped when the schema file is not available locally, so
# the suite still runs in an offline environment.
SCHEMA_PATH = os.environ.get(
    "MCP_SCHEMA_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "tests", "schema-2026-07-28.json"),
)


def _load_schema():
    if not os.path.exists(SCHEMA_PATH):
        return None
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class TestSchemaConformance(unittest.TestCase):
    """Validate real responses against the upstream MCP JSON Schema."""

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("jsonschema is not installed")
        cls.schema = _load_schema()
        if cls.schema is None:
            raise unittest.SkipTest("MCP schema file not available at " + SCHEMA_PATH)
        cls.defs = cls.schema.get("$defs", {})

    def _validator(self, defname):
        import jsonschema

        sub = {
            "$schema": self.schema["$schema"],
            "$ref": "#/$defs/" + defname,
            "$defs": self.defs,
        }
        return jsonschema.Draft202012Validator(sub)

    def _server(self):
        s = make_server(name="skel-test", version="0.2.0")

        @s.tool(name="echo", description="Echo the input back to the caller.")
        def echo(params):
            return {"content": [{"type": "text", "text": params["text"]}]}

        @s.tool(name="noop", description="A tool that takes no arguments.")
        def noop(params):
            return {"content": []}

        return s

    def test_discover_result_matches_schema(self):
        s = self._server()
        r = s.handle(McpRequest({"id": 1, "method": "server/discover", "params": {}}))
        errors = list(self._validator("DiscoverResult").iter_errors(r.result))
        self.assertEqual(errors, [], [e.message for e in errors])

    def test_tools_list_result_matches_schema(self):
        s = self._server()
        r = s.handle(McpRequest({"id": 2, "method": "tools/list", "params": {}}))
        errors = list(self._validator("ListToolsResult").iter_errors(r.result))
        self.assertEqual(errors, [], [e.message for e in errors])

    def test_tools_call_result_matches_schema(self):
        s = self._server()
        r = s.handle(
            McpRequest(
                {
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "echo", "arguments": {"text": "hi"}},
                }
            )
        )
        errors = list(self._validator("CallToolResult").iter_errors(r.result))
        self.assertEqual(errors, [], [e.message for e in errors])

    def test_jsonrpc_envelope_matches_schema(self):
        import jsonschema

        s = self._server()
        r = s.handle(McpRequest({"id": 4, "method": "server/discover", "params": {}}))
        validator = jsonschema.Draft202012Validator(
            {
                "$schema": self.schema["$schema"],
                "$ref": "#/$defs/JSONRPCResultResponse",
                "$defs": self.defs,
            }
        )
        errors = list(validator.iter_errors(r.to_dict()))
        self.assertEqual(errors, [], [e.message for e in errors])

    def test_tool_without_input_schema_still_emits_one(self):
        """The MCP schema requires inputSchema on every tool."""
        s = self._server()
        r = s.handle(McpRequest({"id": 5, "method": "tools/list", "params": {}}))
        for tool in r.result["tools"]:
            self.assertIn("inputSchema", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")


if __name__ == "__main__":
    unittest.main(verbosity=2)
