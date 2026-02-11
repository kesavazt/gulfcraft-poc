"""
Centralized LLM Configuration

Provides a single source of truth for LLM instances used across the agent system.
"""

from functools import lru_cache
from langchain_openai import AzureChatOpenAI
from core import config


def _get_langfuse_callbacks():
    """Get Langfuse callback handler for LLM cost tracking."""
    try:
        from utils.langfuse_tracing import get_langfuse_callback
        handler = get_langfuse_callback()
        return [handler] if handler else None
    except Exception:
        return None


@lru_cache(maxsize=4)
def get_llm(temperature: float = 0.0) -> AzureChatOpenAI:
    """
    Get a cached LLM instance with the specified temperature.

    Args:
        temperature: LLM temperature (0.0 = deterministic, 1.0 = creative)

    Returns:
        AzureChatOpenAI instance
    """
    return AzureChatOpenAI(
        azure_deployment=config.AZURE_OPENAI_CHAT_DEPLOYMENT_NAME,
        temperature=temperature,
        openai_api_key=config.OPENAI_API_KEY,
        api_version=config.OPENAI_API_VERSION,
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        callbacks=_get_langfuse_callbacks(),
    )


# Default LLM instance (temperature=0 for deterministic responses)
llm = get_llm(temperature=0.0)
