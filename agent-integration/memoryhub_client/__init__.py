"""Shared REST client used by the MemoryHub CLI, MCP server and plugins."""

from .client import MemoryHubClient, MemoryHubError

__all__ = ["MemoryHubClient", "MemoryHubError"]
