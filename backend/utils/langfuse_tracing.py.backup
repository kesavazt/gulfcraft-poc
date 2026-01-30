"""
Langfuse Tracing Module

Provides hierarchical tracing for the Gulf Craft Costing Agent:
- Trace Level: Conversation (spans multiple messages)
- Session Level: Costing Job (groups all operations for a single job)
- Span Level: Individual operations (agent nodes, tool calls)

Compatible with Langfuse SDK >= 3.0

Usage:
    # In main.py (invoke_agent):
    with trace_context(conversation_id, user_id=user_id):
        # agent execution

    # In costing_node:
    with session_context(job_id, metadata={...}):
        # costing operations

    # For individual operations:
    with span_context("operation_name", input_data, metadata={...}):
        # do work
        return output
"""

import functools
import traceback
from contextvars import ContextVar
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

# Context variables for storing current trace/session/span
_current_trace = ContextVar("current_trace", default=None)
_current_session = ContextVar("current_session", default=None)
_current_span = ContextVar("current_span", default=None)

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


class trace_context:
    """
    Context manager for conversation-level traces.

    Usage:
        with trace_context("conv_123", user_id=1):
            # conversation logic
    """

    def __init__(self, trace_id: str, user_id: Optional[int] = None, metadata: Optional[Dict] = None):
        self.trace_id = trace_id
        self.user_id = user_id
        self.metadata = metadata or {}
        self.trace = None
        self.token = None

    def __enter__(self):
        client = _get_langfuse_client()
        if not client:
            return None

        try:
            # Create trace with metadata
            trace_metadata = {
                "session_type": "conversation",
                **self.metadata
            }

            self.trace = client.trace(
                id=self.trace_id,
                name="conversation",
                metadata=trace_metadata,
                user_id=str(self.user_id) if self.user_id else None
            )

            # Set in context
            self.token = _current_trace.set(self.trace)

        except Exception as e:
            print(f"[Langfuse] Trace context error: {e}")
            return None

        return self.trace

    def __exit__(self, exc_type, exc_val, exc_tb):
        client = _get_langfuse_client()

        if self.trace:
            try:
                # Mark trace as errored if exception occurred
                if exc_type:
                    self.trace.update(
                        status_message=str(exc_val),
                        level="ERROR"
                    )
            except Exception as e:
                print(f"[Langfuse] Trace update error: {e}")

        # Reset context
        if self.token:
            _current_trace.reset(self.token)

        # Flush to ensure traces are sent to Langfuse
        if client:
            try:
                client.flush()
            except Exception as e:
                print(f"[Langfuse] Flush error: {e}")


class session_context:
    """
    Context manager for job-level sessions (nested under traces).

    Usage:
        with session_context("COST-ABC123", metadata={...}):
            # job operations
    """

    def __init__(self, session_id: str, metadata: Optional[Dict] = None):
        self.session_id = session_id
        self.metadata = metadata or {}
        self.session = None
        self.token = None

    def __enter__(self):
        client = _get_langfuse_client()
        trace = _current_trace.get()

        if not client or not trace:
            return None

        try:
            # Create session as a span under the trace
            self.session = trace.span(
                id=self.session_id,
                name=f"job_{self.session_id}",
                metadata={
                    "session_type": "costing_job",
                    "job_id": self.session_id,
                    **self.metadata
                },
                level="DEFAULT"
            )

            # Set in context
            self.token = _current_session.set(self.session)

        except Exception as e:
            print(f"[Langfuse] Session context error: {e}")
            return None

        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            try:
                if exc_type:
                    self.session.end(
                        status_message=str(exc_val),
                        level="ERROR"
                    )
                else:
                    self.session.end()
            except Exception as e:
                print(f"[Langfuse] Session end error: {e}")

        # Reset context
        if self.token:
            _current_session.reset(self.token)


class span_context:
    """
    Context manager for individual operation spans (under sessions or traces).

    Usage:
        with span_context("send_email", input_data, metadata={...}) as span:
            # operation logic
            span.update(output=result)
    """

    def __init__(
        self,
        name: str,
        input_data: Optional[Any] = None,
        metadata: Optional[Dict] = None,
        span_type: str = "tool"  # "agent", "tool", "llm"
    ):
        self.name = name
        self.input_data = input_data
        self.metadata = metadata or {}
        self.span_type = span_type
        self.span = None
        self.token = None

    def __enter__(self):
        client = _get_langfuse_client()

        # Try to get parent: session > trace
        parent = _current_session.get() or _current_trace.get()

        if not client or not parent:
            return self

        try:
            # Create span under parent
            self.span = parent.span(
                name=self.name,
                input=self.input_data,
                metadata={
                    "type": self.span_type,
                    **self.metadata
                },
                level="DEFAULT"
            )

            # Set in context for nested spans
            self.token = _current_span.set(self.span)

        except Exception as e:
            print(f"[Langfuse] Span context error ({self.name}): {e}")

        return self

    def update(self, output: Optional[Any] = None, metadata: Optional[Dict] = None):
        """Update span with output or additional metadata."""
        if self.span:
            try:
                update_args = {}
                if output is not None:
                    update_args["output"] = output
                if metadata:
                    # Merge with existing metadata
                    existing_metadata = getattr(self.span, 'metadata', {}) or {}
                    update_args["metadata"] = {**existing_metadata, **metadata}
                if update_args:
                    self.span.update(**update_args)
            except Exception as e:
                print(f"[Langfuse] Span update error ({self.name}): {e}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            try:
                if exc_type:
                    self.span.end(
                        output={"error": str(exc_val), "traceback": traceback.format_exc()},
                        status_message=str(exc_val),
                        level="ERROR"
                    )
                else:
                    self.span.end()
            except Exception as e:
                print(f"[Langfuse] Span end error ({self.name}): {e}")

        # Reset context
        if self.token:
            _current_span.reset(self.token)


def trace_agent(func: Callable) -> Callable:
    """
    Decorator for agent node functions.

    Usage:
        @trace_agent
        def costing_node(state: AgentState):
            ...
    """
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

            # Update with output metadata
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
    """
    Decorator for tool functions.

    Usage:
        @trace_tool
        def send_email(to, subject, body):
            ...
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Build input data from args/kwargs
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


# Convenience function for manual tracing (backward compatibility)
def trace_operation(name: str, input_payload: Any, output_payload: Any = None, error: Exception = None):
    """
    Manual tracing function for operations (backward compatible).

    Prefer using context managers or decorators instead.
    """
    client = _get_langfuse_client()
    parent = _current_session.get() or _current_trace.get()

    if not client or not parent:
        return

    try:
        event_data = {
            "name": name,
            "input": input_payload,
            "metadata": {"source": "manual_trace"}
        }

        if error:
            event_data["output"] = {"error": str(error)}
            event_data["status_message"] = str(error)
            event_data["level"] = "ERROR"
        elif output_payload is not None:
            event_data["output"] = output_payload

        parent.event(**event_data)

    except Exception as e:
        print(f"[Langfuse] Manual trace error ({name}): {e}")
