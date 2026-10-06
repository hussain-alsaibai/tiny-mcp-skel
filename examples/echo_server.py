"""echo_server.py - A minimal MCP echo server using tiny-mcp-skel.

Run with::

    python echo_server.py

The server will read JSON-RPC 2.0 frames from stdin and write responses
to stdout. Connect it to an MCP client (e.g. Claude Desktop, or any
JSON-RPC 2.0 client) to test.
"""
import sys
import os

# Add the tiny-* family to sys.path when running this file directly.
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
for sub in ("tiny-router", "tiny-validator"):
    p = os.path.join(BASE, sub)
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.insert(0, HERE)

from tiny_mcp_skel import make_server, run_stdio
from tiny_validator import Schema, String, Integer


server = make_server(
    name="echo-mcp",
    version="0.1.0",
    title="Echo MCP",
    description="A tiny MCP server that echoes input and does basic arithmetic.",
    )


@server.tool(
    name="echo",
    description="Echo the input back to the caller.",
    input_schema=Schema({"text": String(min_length=1, max_length=2048)}),
    )
def echo_handler(params):
    return {
        "content": [
            {"type": "text", "text": params["text"]},
        ],
    }


@server.tool(
    name="add",
    description="Add two integers and return the sum.",
    input_schema=Schema({"a": Integer(), "b": Integer()}),
    )
def add_handler(params):
    return {
        "content": [
            {"type": "text", "text": str(params["a"] + params["b"])},
        ],
    }


@server.tool(
    name="reverse",
    description="Reverse the input string.",
    input_schema=Schema({"text": String()}),
    )
def reverse_handler(params):
    return {
        "content": [
            {"type": "text", "text": params["text"][::-1]},
        ],
    }


if __name__ == "__main__":
    run_stdio(server)
