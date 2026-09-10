"""Lazy MCP initialization shared by optional transport builders."""


def require_fastmcp() -> tuple[type, type]:
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.fastmcp.server import Settings

    Settings.model_rebuild()
    return FastMCP, Context
