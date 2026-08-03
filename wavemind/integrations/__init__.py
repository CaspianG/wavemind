"""Optional integrations for external agent frameworks."""

from .anthropic import (
    ANTHROPIC_MEMORY_TOOL,
    AnthropicMemoryHandler,
    make_anthropic_experience_hooks,
)
from .autogen import WaveMindAutoGenMemory
from .crewai import WaveMindCrewAITools
from .langgraph import (
    make_experience_capture_node,
    make_experience_recall_node,
    make_experience_runtime_finish_node,
    make_experience_runtime_start_node,
    make_persist_node,
    make_recall_node,
    wrap_experience_runtime_node,
)
from .llamaindex import WaveMindNode, WaveMindRetriever
from .mcp_experience import ExperienceMCPAdapter, build_experience_mcp_server
from .openai_agents import (
    WaveMindAgentsSession,
    make_experience_input_callback,
    make_openai_experience_hooks,
)
from .experience_runtime import AgentExperienceHooks, ProviderExperienceRun
from .state_bench import (
    StateBenchProtocolValidation,
    WaveMindStateBenchLearningAdapter,
    build_state_bench_adapter_artifact,
    validate_state_bench_training_root,
)

__all__ = [
    "ANTHROPIC_MEMORY_TOOL",
    "AnthropicMemoryHandler",
    "AgentExperienceHooks",
    "ExperienceMCPAdapter",
    "ProviderExperienceRun",
    "StateBenchProtocolValidation",
    "WaveMindAutoGenMemory",
    "WaveMindAgentsSession",
    "WaveMindCrewAITools",
    "WaveMindNode",
    "WaveMindRetriever",
    "WaveMindStateBenchLearningAdapter",
    "build_state_bench_adapter_artifact",
    "build_experience_mcp_server",
    "make_experience_capture_node",
    "make_anthropic_experience_hooks",
    "make_experience_input_callback",
    "make_experience_recall_node",
    "make_experience_runtime_finish_node",
    "make_experience_runtime_start_node",
    "make_openai_experience_hooks",
    "make_persist_node",
    "make_recall_node",
    "wrap_experience_runtime_node",
    "validate_state_bench_training_root",
]
