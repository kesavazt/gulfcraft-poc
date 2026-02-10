"""
Quick test script to verify Langfuse tracing is working with session_id
"""
import time
import uuid
from utils.langfuse_tracing import trace_context, session_context, span_context

# Test basic tracing
print("Testing Langfuse tracing...")

# Use proper 32-char hex trace IDs (required by OpenTelemetry / Langfuse v3)
conversation_id = uuid.uuid4().hex
job_id = f"COST-TEST-{int(time.time())}"

print(f"Creating trace: {conversation_id}")
print(f"Creating session (job): {job_id}")

with trace_context(conversation_id, user_id=999, metadata={"test": "trace"}) as trace:
    print(f"  Inside trace context (span: {trace})")

    with session_context(job_id, metadata={"test": "session"}) as session:
        print(f"    Inside session context - session_id={job_id} set on trace")

        with span_context("test_operation", input_data={"value": 123}) as span:
            print("      Inside span context")
            time.sleep(0.1)
            span.update(output={"result": "success"})
            print("      Span completed")

        with span_context("second_operation", input_data={"step": 2}) as span2:
            print("      Inside second span")
            span2.update(output={"result": "done"})
            print("      Second span completed")

        print("    Session context completed")

    print("  Trace context completed")

print("\nTrace completed successfully!")
print(f"Check Langfuse dashboard for trace: {conversation_id}")
print(f"Session (job) should show as: {job_id}")
print("URL: https://cloud.langfuse.com")
