"""
Langfuse Tracing Module (SDK v3.x)

Provides hierarchical tracing for the Gulf Craft Costing Agent:
- Trace Level: Conversation (spans multiple messages)
- Session Level: Costing Job (groups all operations for a single job)
- Span Level: Individual operations (agent nodes, tool calls)

Uses SDK v3.x OpenTelemetry-based API:
- client.start_as_current_span() for automatic parent-child nesting
- client.update_current_trace() for setting session_id/user_id on traces
"""

import functools
import traceback
import uuid
from typing import Any, Dict, Optional, Callable

# Import Langfuse SDK
try:
    from langfuse import Langfuse
    from langfuse.types import TraceContext
    LANGFUSE_AVAILABLE = True
except ImportError:
    Langfuse = None
    TraceContext = None
    LANGFUSE_AVAILABLE = False

# Import config
from core import config

# Global Langfuse client
_langfuse_client = None
_langfuse_callback = None


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


def get_langfuse_callback():
    """
    Get a Langfuse CallbackHandler for LangChain integration.

    This enables automatic capture of model name, token usage, and cost
    for every LLM call made through LangChain. The callback handler
    integrates with the existing OTel-based trace context, so generations
    nest under the current span automatically.
    """
    global _langfuse_callback

    if _langfuse_callback is not None:
        return _langfuse_callback

    if not LANGFUSE_AVAILABLE:
        return None

    if not all([config.LANGFUSE_PUBLIC_KEY, config.LANGFUSE_SECRET_KEY]):
        return None

    # Get the Langfuse client first
    client = _get_langfuse_client()
    if not client:
        return None

    try:
        # Try the callback module first (newer SDK versions)
        from langfuse.callback import CallbackHandler
        # In SDK v3.x, CallbackHandler can accept the client directly
        try:
            _langfuse_callback = CallbackHandler(client=client)
            print("[Langfuse] LangChain CallbackHandler initialized for cost tracking (callback module)")
            return _langfuse_callback
        except TypeError:
            # Fallback to environment variables if client parameter not supported
            import os
            os.environ["LANGFUSE_PUBLIC_KEY"] = config.LANGFUSE_PUBLIC_KEY
            os.environ["LANGFUSE_SECRET_KEY"] = config.LANGFUSE_SECRET_KEY
            os.environ["LANGFUSE_HOST"] = config.LANGFUSE_HOST
            _langfuse_callback = CallbackHandler()
            print("[Langfuse] LangChain CallbackHandler initialized for cost tracking (env vars)")
            return _langfuse_callback
    except ImportError:
        pass
    except Exception as e:
        print(f"[Langfuse] CallbackHandler (callback module) initialization error: {e}")

    try:
        # Try the langchain module (older SDK versions)
        from langfuse.langchain import CallbackHandler
        try:
            _langfuse_callback = CallbackHandler(client=client)
            print("[Langfuse] LangChain CallbackHandler initialized for cost tracking (langchain module)")
            return _langfuse_callback
        except TypeError:
            # Fallback to environment variables
            import os
            os.environ["LANGFUSE_PUBLIC_KEY"] = config.LANGFUSE_PUBLIC_KEY
            os.environ["LANGFUSE_SECRET_KEY"] = config.LANGFUSE_SECRET_KEY
            os.environ["LANGFUSE_HOST"] = config.LANGFUSE_HOST
            _langfuse_callback = CallbackHandler()
            print("[Langfuse] LangChain CallbackHandler initialized for cost tracking (env vars)")
            return _langfuse_callback
    except ImportError:
        print("[Langfuse] CallbackHandler not available - install langfuse with LangChain support")
        return None
    except Exception as e:
        print(f"[Langfuse] CallbackHandler initialization error: {e}")
        return None


def _ensure_hex_trace_id(trace_id: str) -> str:
    """Ensure trace_id is a valid 32-char lowercase hex string for OpenTelemetry."""
    clean = trace_id.lower().replace("-", "")
    if len(clean) == 32:
        try:
            int(clean, 16)
            return clean
        except ValueError:
            pass
    # Convert non-hex IDs to a deterministic 32-char hex via uuid5
    return uuid.uuid5(uuid.NAMESPACE_URL, trace_id).hex


class trace_context:
    """
    Context manager for conversation-level traces.

    Creates a root span linked to a specific trace_id via TraceContext,
    and sets user_id on the trace. Child spans created inside this
    context automatically nest under it via OpenTelemetry propagation.
    """

    def __init__(self, trace_id: str, user_id: Optional[int] = None, metadata: Optional[Dict] = None):
        # TraceContext requires a valid 32-char lowercase hex string (OpenTelemetry trace ID)
        self.trace_id = _ensure_hex_trace_id(trace_id)
        self.user_id = user_id
        self.metadata = metadata or {}
        self._cm = None
        self._span = None

    def __enter__(self):
        client = _get_langfuse_client()
        if not client:
            return None

        try:
            trace_metadata = {
                "session_type": "conversation",
                **self.metadata
            }

            # Create root span linked to this trace_id
            trace_ctx = TraceContext(
                trace_id=self.trace_id,
                user_id=str(self.user_id) if self.user_id else None
            )

            self._cm = client.start_as_current_span(
                name="conversation",
                trace_context=trace_ctx,
                metadata=trace_metadata
            )
            self._span = self._cm.__enter__()

            # Set user_id on the trace
            client.update_current_trace(
                user_id=str(self.user_id) if self.user_id else None,
                metadata=trace_metadata
            )

            return self._span

        except Exception as e:
            print(f"[Langfuse] Trace context error: {e}")
            return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        client = _get_langfuse_client()

        # End the span context manager
        if self._cm:
            try:
                if exc_type and self._span:
                    self._span.update(
                        output={"error": str(exc_val)},
                        level="ERROR",
                        status_message=str(exc_val)
                    )
                self._cm.__exit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                print(f"[Langfuse] Trace exit error: {e}")

        # Flush to ensure traces are sent
        if client:
            try:
                client.flush()
            except Exception as e:
                print(f"[Langfuse] Flush error: {e}")


class session_context:
    """
    Context manager for job-level sessions (nested under traces).

    Sets session_id on the parent trace so Langfuse groups traces
    by job, and creates a child span for the job's operations.
    """

    def __init__(self, session_id: str, metadata: Optional[Dict] = None):
        self.session_id = session_id
        self.metadata = metadata or {}
        self._cm = None
        self._span = None

    def __enter__(self):
        client = _get_langfuse_client()
        if not client:
            return None

        try:
            # Set session_id on the trace so Langfuse groups it into a session
            client.update_current_trace(session_id=self.session_id)

            # Create a child span for this job's operations
            self._cm = client.start_as_current_span(
                name=f"job_{self.session_id}",
                metadata={
                    "session_type": "costing_job",
                    "job_id": self.session_id,
                    **self.metadata
                }
            )
            self._span = self._cm.__enter__()

            return self._span

        except Exception as e:
            print(f"[Langfuse] Session context error: {e}")
            return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._cm:
            try:
                if exc_type and self._span:
                    self._span.update(
                        output={"error": str(exc_val)},
                        level="ERROR",
                        status_message=str(exc_val)
                    )
                self._cm.__exit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                print(f"[Langfuse] Session exit error: {e}")


class span_context:
    """
    Context manager for individual operation spans.

    Automatically nests under the current span via OpenTelemetry propagation.
    """

    def __init__(
        self,
        name: str,
        input_data: Optional[Any] = None,
        metadata: Optional[Dict] = None,
        span_type: str = "tool"
    ):
        self.name = name
        self.input_data = input_data
        self.metadata = metadata or {}
        self.span_type = span_type
        self._cm = None
        self.span = None

    def __enter__(self):
        client = _get_langfuse_client()
        if not client:
            return self

        try:
            self._cm = client.start_as_current_span(
                name=self.name,
                input=self.input_data,
                metadata={
                    "type": self.span_type,
                    **self.metadata
                }
            )
            self.span = self._cm.__enter__()
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
                    update_args["metadata"] = {**self.metadata, **metadata}
                if update_args:
                    self.span.update(**update_args)
            except Exception as e:
                print(f"[Langfuse] Span update error ({self.name}): {e}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._cm:
            try:
                if exc_type and self.span:
                    self.span.update(
                        output={"error": str(exc_val), "traceback": traceback.format_exc()},
                        level="ERROR",
                        status_message=str(exc_val)
                    )
                self._cm.__exit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                print(f"[Langfuse] Span exit error ({self.name}): {e}")


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
    """Manual tracing function for one-off operations."""
    client = _get_langfuse_client()
    if not client:
        return

    try:
        with client.start_as_current_span(
            name=name,
            input=input_payload,
            metadata={"source": "manual_trace"}
        ) as span:
            if error:
                span.update(
                    output={"error": str(error)},
                    level="ERROR",
                    status_message=str(error)
                )
            elif output_payload is not None:
                span.update(output=output_payload)
    except Exception as e:
        print(f"[Langfuse] Manual trace error ({name}): {e}")
