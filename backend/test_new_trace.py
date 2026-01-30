"""Test new Langfuse SDK 3.x tracing"""
import time
import uuid
import sys
sys.path.insert(0, 'utils')
from langfuse_tracing_new import trace_context, span_context

# Generate valid 32-char hex trace ID
conv_id = uuid.uuid4().hex
print(f"Testing with conversation: {conv_id}")

with trace_context(conv_id, user_id=999):
    with span_context("test_op", {"value": 123}) as span:
        span.update(output={"result": "ok"})
        print("Trace sent successfully!")

print("Check Langfuse dashboard at: https://cloud.langfuse.com")
