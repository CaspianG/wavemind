"""Optional integrations for external agent frameworks."""

from .anthropic import ANTHROPIC_MEMORY_TOOL, AnthropicMemoryHandler
from .autogen import WaveMindAutoGenMemory
from .crewai import WaveMindCrewAITools
from .langgraph import (
    make_experience_capture_node,
    make_experience_recall_node,
    make_persist_node,
    make_recall_node,
)
from .llamaindex import WaveMindNode, WaveMindRetriever
from .mcp_experience import ExperienceMCPAdapter, build_experience_mcp_server
from .openai_agents import WaveMindAgentsSession, make_experience_input_callback

__all__ = [
    "ANTHROPIC_MEMORY_TOOL",
    "AnthropicMemoryHandler",
    "ExperienceMCPAdapter",
    "WaveMindAutoGenMemory",
    "WaveMindAgentsSession",
    "WaveMindCrewAITools",
    "WaveMindNode",
    "WaveMindRetriever",
    "build_experience_mcp_server",
    "make_experience_capture_node",
    "make_experience_input_callback",
    "make_experience_recall_node",
    "make_persist_node",
    "make_recall_node",
]
