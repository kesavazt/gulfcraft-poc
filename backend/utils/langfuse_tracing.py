"""
Langfuse Tracing Module (Updated for SDK 3.x)

Provides hierarchical tracing for the Gulf Craft Costing Agent using Langfuse SDK 3.x API.
"""

import functools
import traceback
from contextlib import contextmanager
from typing import Any, Dict, Optional, Callable

# Import Langfuse SDK
try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
except ImportError:
    Langfuse = None
    LANGFUSE_AVAILABLE = False

# Import config
from core import config

# Global Langfuse client
_langfuse_client = None


def _get_langfuse_client() -> Optional[Langfuse]:
    """Get or initialize the Langfuse client."""
    global _langfuse_client

    if not LANGFUSE_AVAILABLE:
        return None

    if not all([config.LANGFUSE_PUBLIC_KEY, config.LANGFUSE_SECRET_KEY]):
        return None

    if _langfuse_client is None:
        try:
            _langfuse_client = Langfuse(
                public_key=config.LANGFUSE_PUBLIC_KEY,
                secret_key=config.LANGFUSE_SECRET_KEY,
                host=config.LANGFUSE_HOST,
            )
        except Exception as e:
            print(f"[Langfuse] Initialization error: {e}")
            return None

    return _langfuse_client


@contextmanager
def trace_context(trace_id: str, user_id: Optional[int] = None, metadata: Optional[Dict] = None):
    """Context manager for conversation-level traces (SDK 3.x)."""
    from langfuse.types import TraceContext

    client = _get_langfuse_client()
    if not client:
        yield None
        return

    observation = None
    try:
        trace_metadata = {
            "session_type": "conversation",
            "user_id": user_id,
            **(metadata or {})
        }

        # Create trace context
        trace_ctx = TraceContext(trace_id=trace_id, user_id=str(user_id) if user_id else None)

        observation = client.start_observation(
            trace_context=trace_ctx,
            name="conversation",
            as_type="span",
            metadata=trace_metadata
        )

        yield observation

    except Exception as e:
        print(f"[Langfuse] Trace context error: {e}")
        if observation:
            try:
                observation.end(output={"error": str(e)}, status_message=str(e), level="ERROR")
            except:
                pass
        yield None

    finally:
        if observation:
            try:
                observation.end()
            except Exception as e:
                print(f"[Langfuse] Trace end error: {e}")
        if client:
            try:
                client.flush()
            except Exception as e:
                print(f"[Langfuse] Flush error: {e}")


@contextmanager
def session_context(session_id: str, metadata: Optional[Dict] = None):
    """Context manager for job-level sessions (SDK 3.x)."""
    client = _get_langfuse_client()
    if not client:
        yield None
        return

    observation = None
    try:
        session_metadata = {
            "session_type": "costing_job",
            "job_id": session_id,
            **(metadata or {})
        }

        observation = client.start_observation(
            name=f"job_{session_id}",
            as_type="span",
            metadata=session_metadata
        )

        yield observation

    except Exception as e:
        print(f"[Langfuse] Session context error: {e}")
        if observation:
            try:
                observation.end(output={"error": str(e)}, status_message=str(e), level="ERROR")
            except:
                pass
        yield None

    finally:
        if observation:
            try:
                observation.end()
            except Exception as e:
                print(f"[Langfuse] Session end error: {e}")


class span_context:
    """Context manager for individual operation spans (SDK 3.x)."""

    def __init__(self, name: str, input_data: Optional[Any] = None, metadata: Optional[Dict] = None, span_type: str = "tool"):
        self.name = name
        self.input_data = input_data
        self.metadata = metadata or {}
        self.span_type = span_type
        self.observation = None

    def __enter__(self):
        client = _get_langfuse_client()
        if not client:
            return self

        try:
            self.observation = client.start_observation(
                name=self.name,
                as_type="span",
                input=self.input_data,
                metadata={"type": self.span_type, **self.metadata}
            )
        except Exception as e:
            print(f"[Langfuse] Span context error ({self.name}): {e}")

        return self

    def update(self, output: Optional[Any] = None, metadata: Optional[Dict] = None):
        """Update span with output or additional metadata."""
        if self.observation:
            try:
                if output is not None:
                    self.observation.update(output=output)
                if metadata:
                    updated_metadata = {**self.metadata, **metadata}
                    self.observation.update(metadata=updated_metadata)
                    self.metadata = updated_metadata
            except Exception as e:
                print(f"[Langfuse] Span update error ({self.name}): {e}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.observation:
            try:
                if exc_type:
                    self.observation.end(output={"error": str(exc_val), "traceback": traceback.format_exc()}, status_message=str(exc_val), level="ERROR")
                else:
                    self.observation.end()
            except Exception as e:
                print(f"[Langfuse] Span end error ({self.name}): {e}")


def trace_agent(func: Callable) -> Callable:
    """Decorator for agent node functions."""
    @functools.wraps(func)
    def wrapper(state, *args, **kwargs):
        agent_name = func.__name__.replace("_node", "").replace("_", " ").title()

        with span_context(
            name=func.__name__,
            input_data={"messages_count": len(state.get("messages", []))},
            metadata={"agent": agent_name, "user_id": state.get("user_id")},
            span_type="agent"
        ) as span:
            result = func(state, *args, **kwargs)

            output_metadata = {}
            if isinstance(result, dict):
                if "job_id" in result:
                    output_metadata["job_id"] = result["job_id"]
                if "next" in result:
                    output_metadata["next_agent"] = result["next"]

            if output_metadata:
                span.update(metadata=output_metadata)

            return result

    return wrapper


def trace_tool(func: Callable) -> Callable:
    """Decorator for tool functions."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        import inspect
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        input_data = dict(bound.arguments)

        with span_context(
            name=func.__name__,
            input_data=input_data,
            span_type="tool"
        ) as span:
            result = func(*args, **kwargs)
            span.update(output=result)
            return result

    return wrapper


def trace_operation(name: str, input_payload: Any, output_payload: Any = None, error: Exception = None):
    """Manual tracing function for operations (backward compatible with SDK 3.x)."""
    client = _get_langfuse_client()
    if not client:
        return

    try:
        event_data = {
            "name": name,
            "as_type": "span",
            "input": input_payload,
            "metadata": {"source": "manual_trace"}
        }

        if error:
            event_data["output"] = {"error": str(error)}
            event_data["status_message"] = str(error)
            event_data["level"] = "ERROR"
        elif output_payload is not None:
            event_data["output"] = output_payload

        observation = client.start_observation(**event_data)
        observation.end()

    except Exception as e:
        print(f"[Langfuse] Manual trace error ({name}): {e}")
