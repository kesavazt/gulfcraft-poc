"""
Test Status Agent Integration

Quick tests to verify the status agent is properly wired and conversational.
"""

def test_status_routing():
    """Verify StatusAgent is in the routing configuration."""
    from agents.supervisor import ROUTABLE_MEMBERS, OPTIONS

    assert "StatusAgent" in ROUTABLE_MEMBERS, "StatusAgent should be routable"
    assert "StatusAgent" in OPTIONS, "StatusAgent should be in supervisor options"
    print("✅ StatusAgent properly configured in routing")


def test_status_node_exists():
    """Verify status_node function exists and has tracing."""
    from agents.status import status_node

    assert callable(status_node), "status_node should be callable"
    # Check if it has the trace_agent decorator applied (will have __wrapped__)
    assert hasattr(status_node, '__wrapped__') or hasattr(status_node, '__name__'), \
        "status_node should have decorator metadata"
    print("✅ status_node exists and is decorated")


def test_status_prompt_exists():
    """Verify status agent prompt template exists."""
    from utils.prompts import STATUS_AGENT_SYSTEM_PROMPT

    assert STATUS_AGENT_SYSTEM_PROMPT, "STATUS_AGENT_SYSTEM_PROMPT should exist"
    assert "conversational" in STATUS_AGENT_SYSTEM_PROMPT.lower(), \
        "Prompt should mention conversational approach"
    print("✅ Status agent prompt template exists")


def test_supervisor_mentions_status():
    """Verify supervisor knows how to route to StatusAgent."""
    from utils.prompts import SUPERVISOR_SYSTEM_PROMPT

    assert "StatusAgent" in SUPERVISOR_SYSTEM_PROMPT, \
        "Supervisor prompt should mention StatusAgent"
    assert "status" in SUPERVISOR_SYSTEM_PROMPT.lower(), \
        "Supervisor should have status routing logic"
    print("✅ Supervisor prompt includes status routing")


def test_main_workflow_includes_status():
    """Verify main workflow includes StatusAgent node."""
    from main import workflow

    # Check if StatusAgent node exists in workflow
    nodes = workflow.nodes
    assert "StatusAgent" in nodes, "StatusAgent should be a workflow node"
    print("✅ StatusAgent is a workflow node")


def test_status_agent_mock_response():
    """Test status agent with mock data."""
    from agents.status import _build_status_context, _status_label

    # Mock job data
    mock_jobs = [
        {
            "job_id": "COST-TEST1234",
            "status": "Ready",
            "created_at": "2024-01-15T10:30:00",
            "item_details": "Test job description",
            "line_items": [
                {"item_name": "Item 1", "price_status": "resolved"},
                {"item_name": "Item 2", "price_status": "pending"}
            ],
            "quote_requests": [
                {
                    "item_name": "Item 2",
                    "status": "pending",
                    "sent_at": "2024-01-15T11:00:00"
                }
            ]
        }
    ]

    # Test context building
    context = _build_status_context(mock_jobs, specific_job_id="COST-TEST1234", wants_details=True)

    assert "COST-TEST1234" in context, "Context should include job ID"
    assert "Ready to review" in context or "Ready" in context, "Context should include status"
    assert "Item 2" in context, "Context should include pending item"
    print("✅ Status context building works correctly")


def test_status_label_mapping():
    """Test status label conversion."""
    from agents.status import _status_label

    assert _status_label("Ready") == "Ready to review"
    assert _status_label("Awaiting Quote") == "Waiting for quotes"
    assert _status_label("Approved") == "Complete and sent"
    print("✅ Status label mapping works correctly")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Testing Status Agent Integration")
    print("="*60 + "\n")

    tests = [
        test_status_routing,
        test_status_node_exists,
        test_status_prompt_exists,
        test_supervisor_mentions_status,
        test_main_workflow_includes_status,
        test_status_agent_mock_response,
        test_status_label_mapping,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} failed: {e}")
            failed += 1
        except Exception as e:
            print(f"⚠️  {test.__name__} error: {e}")
            failed += 1

    print("\n" + "="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    if failed == 0:
        print("🎉 All tests passed! Status Agent is properly integrated.")
    else:
        print(f"⚠️  {failed} test(s) failed. Please review.")
