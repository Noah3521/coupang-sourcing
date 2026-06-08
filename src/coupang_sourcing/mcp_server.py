"""MCP server exposing coupang-sourcing as typed tools for OpenClaw agents.

Run as a stdio MCP server and register it with OpenClaw (see docs/OPENCLAW.md):

    openclaw mcp add coupang --command /path/.venv/bin/python \
      --arg -m --arg coupang_sourcing.mcp_server --env COUPANG_SOURCING_DB=...

The agent then gets typed tools (find_products, product_info, collect_seller, query_db,
list_categories, refresh_cookies). All logic lives in `service.py` (shared with the
dashboard); here we only register those functions as MCP tools.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import service

mcp = FastMCP("coupang-sourcing")

# Register the shared operations as typed MCP tools (schema derived from each function's
# signature + docstring).
mcp.tool()(service.find_products)
mcp.tool()(service.product_info)
mcp.tool()(service.collect_seller)
mcp.tool()(service.query_db)
mcp.tool()(service.list_categories)
mcp.tool()(service.refresh_cookies)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
