"""
Quick test script to verify Langfuse tracing is working
"""
import time
from utils.langfuse_tracing import trace_context, session_context, span_context

# Test basic tracing
print("Testing Langfuse tracing...")

conversation_id = f"test_conv_{int(time.time())}"
job_id = f"TEST-JOB-{int(time.time())}"

print(f"Creating trace: {conversation_id}")
print(f"Creating session: {job_id}")

with trace_context(conversation_id, user_id=999, metadata={"test": "trace"}):
    print("  Inside trace context")

    with session_context(job_id, metadata={"test": "session"}):
        print("    Inside session context")

        with span_context("test_operation", input_data={"value": 123}) as span:
            print("      Inside span context")
            # Simulate some work
            time.sleep(0.1)
            span.update(output={"result": "success"})
            print("      Span completed")

        print("    Session context completed")

    print("  Trace context completed")

print("\n✓ Trace completed successfully!")
print(f"Check Langfuse dashboard for trace: {conversation_id}")
print("URL: https://cloud.langfuse.com")
