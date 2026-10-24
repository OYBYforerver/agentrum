"""Agentrum — multi-tenant registry for AI agents, MCP servers, skills and prompts."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agentrum")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.1"
