
import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from contextvars import ContextVar

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock config before importing langfuse_tracing to avoid import errors if config is missing
with patch.dict(os.environ, {
    "LANGFUSE_PUBLIC_KEY": "pk-test", 
    "LANGFUSE_SECRET_KEY": "sk-test", 
    "LANGFUSE_HOST": "https://test.langfuse.com"
}):
    from utils import langfuse_tracing
    from utils.langfuse_tracing import (
        trace_context, 
        session_context, 
        span_context, 
        trace_agent, 
        trace_tool,
        _current_trace,
        _current_session,
        _current_span
    )

class TestLangfuseTracing(unittest.TestCase):
    
    def setUp(self):
        # Reset context variables
        _current_trace.set(None)
        _current_session.set(None)
        _current_span.set(None)
        
        # Mock Langfuse client
        self.mock_client = MagicMock()
        langfuse_tracing._langfuse_client = self.mock_client
        
    def tearDown(self):
        langfuse_tracing._langfuse_client = None

    def test_trace_context(self):
        """Test top-level trace context creation."""
        # Setup mock client to return a trace object
        mock_trace = MagicMock()
        self.mock_client.trace.return_value = mock_trace

        with trace_context("conv_123", user_id=1, metadata={"role": "test"}):
            # Check context var set
            self.assertIsNotNone(_current_trace.get())
            # Check client called
            self.mock_client.trace.assert_called()
            call_kwargs = self.mock_client.trace.call_args[1]
            self.assertEqual(call_kwargs["id"], "conv_123")
            self.assertEqual(call_kwargs["name"], "conversation")
            
        # Check context var reset
        self.assertIsNone(_current_trace.get())

    def test_session_context(self):
        """Test session context creation under trace."""
        mock_trace = MagicMock()
        mock_session = MagicMock()
        self.mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_session
        
        # Manually set trace context to simulate being inside a trace
        token = _current_trace.set(mock_trace)
        
        try:
            with session_context("job_123", metadata={"foo": "bar"}):
                # Check session context var set
                self.assertIsNotNone(_current_session.get())
                # Check trace.span called
                mock_trace.span.assert_called()
                call_kwargs = mock_trace.span.call_args[1]
                self.assertEqual(call_kwargs["name"], "job_job_123")
                self.assertEqual(call_kwargs["metadata"]["session_type"], "costing_job")
        finally:
            _current_trace.reset(token)
            
        # Check session context var reset
        self.assertIsNone(_current_session.get())

    def test_span_context(self):
        """Test span context creation under session."""
        mock_session = MagicMock()
        mock_span = MagicMock()
        
        # Manually set session context
        token = _current_session.set(mock_session)
        mock_session.span.return_value = mock_span
        
        try:
            with span_context("op_1", input_data={"a": 1}, span_type="tool") as span:
                # Check span context var set
                self.assertIsNotNone(_current_span.get())
                # Check session.span called
                mock_session.span.assert_called()
                
                # Test update
                span.update(output={"b": 2})
                mock_span.update.assert_called_with(output={"b": 2})
        finally:
            _current_session.reset(token)

if __name__ == '__main__':
    unittest.main()
