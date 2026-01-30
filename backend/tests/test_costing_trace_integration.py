
import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import json
from datetime import datetime

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock config
with patch.dict(os.environ, {
    "LANGFUSE_PUBLIC_KEY": "pk-test", 
    "LANGFUSE_SECRET_KEY": "sk-test", 
    "LANGFUSE_HOST": "https://test.langfuse.com",
    "PROFIT_MARGIN": "1.2",
    "MS_GRAPH_TENANT_ID": "mock",
    "MS_GRAPH_CLIENT_ID": "mock", 
    "MS_GRAPH_CLIENT_SECRET": "mock",
    "SHAREPOINT_SITE_ID": "mock",
    "SHAREPOINT_LIST_NAME": "mock"
}):
    from main import invoke_agent
    from utils import langfuse_tracing
    from utils import tools
    from core.state import AgentState

class TestCostingTraceIntegration(unittest.TestCase):
    
    def setUp(self):
        # Reset tracing context
        langfuse_tracing._current_trace.set(None)
        langfuse_tracing._current_session.set(None)
        langfuse_tracing._current_span.set(None)
        
        # Mock Langfuse client
        self.mock_client = MagicMock()
        langfuse_tracing._langfuse_client = self.mock_client
        
        # Setup common mocks
        self.smtp_patch = patch('smtplib.SMTP')
        self.mock_smtp = self.smtp_patch.start()
        
        self.requests_patch = patch('requests.post')
        self.mock_post = self.requests_patch.start()
        self.mock_post.return_value.status_code = 200
        self.mock_post.return_value.json.return_value = {"id": "sp_item_123", "access_token": "mock_token"}
        
        # Mock specific tools internals to avoid DB/File operations if possible, 
        # or just rely on them being robust enough (SQLite). 
        # For 'create_costing_request', it writes to DB. We can mock the DB session or just let it write to test DB.
        # Given complexity, let's mock the internal tool helpers usage in costing.py if possible,
        # OR just mock the 'tools.create_costing_request' but then we lose the inner trace testing of that tool.
        # Better: Mock lower level DB operations or use a temporary DB. 
        # For integration test, let's mock the tool functions in 'agents.costing' to verify ORCHESTRATION tracing,
        # AND check that the tool wrappers work.
        
        # Actually, let's just mock the 'tools' functions that access external resources, 
        # but KEEP the @trace_tool decorator logic?
        # If I patch 'utils.tools.send_email', I patch the decorated function.
        # I want to verify the decorator works.
        # So I patched smtplib (above) which is INSIDE send_email.
        
        # Patch `tools.create_sharepoint_list_item` internal request logic is handled by `requests.post` patch.
        # Patch `tools.search_similar_quotations` (hybrid_search)
        self.search_patch = patch('utils.tools.hybrid_search')
        self.mock_search = self.search_patch.start()
        self.mock_search.return_value = [{"quotation_id": "Q1", "line_num": 1, "description": "Test"}]

        # Patch `tools.get_estimation_lines` (DB)
        self.est_lines_patch = patch('utils.tools.get_estimation_lines')
        self.mock_est_lines = self.est_lines_patch.start()
        self.mock_est_lines.return_value = [
            {"item_name": "Labor", "item_type": "hour", "sales_price": 100, "quantity": 5},
            {"item_name": "Part", "item_type": "material", "item_code": "P1", "quantity": 1}
        ]
        
        # Patch `tools.get_product_price` (DB)
        self.prod_price_patch = patch('utils.tools.get_product_price')
        self.mock_prod_price = self.prod_price_patch.start()
        self.mock_prod_price.return_value = {"unit_cost": 5000, "vendor_email": "v@test.com"} # triggers pending quote (>1000 threshold)

        # Patch `tools.create_costing_request` (DB) - we need it to return a job_id
        self.create_req_patch = patch('utils.tools.create_costing_request')
        self.mock_create_req = self.create_req_patch.start()
        self.mock_create_req.return_value = "COST-TEST-123"

        # Patch `tools.save_costing_line_items`
        self.save_items_patch = patch('utils.tools.save_costing_line_items')
        self.mock_save = self.save_items_patch.start()
        
        # Patch `tools.create_costing_sheet_with_items`
        self.create_sheet_patch = patch('utils.tools.create_costing_sheet_with_items')
        self.mock_sheet = self.create_sheet_patch.start()
        self.mock_sheet.return_value = "costing_test.xlsx"
        
        # Patch `tools.update_sharepoint_status`
        self.update_sp_patch = patch('utils.tools.update_sharepoint_status')
        self.mock_update_sp = self.update_sp_patch.start()

    def tearDown(self):
        patch.stopall()
        langfuse_tracing._langfuse_client = None

    def test_costing_workflow_tracing(self):
        """Test full costing workflow generates correct trace hierarchy."""
        
        # Setup session state to simulate a selected quotation ready for confirmation
        state = {
            "selected_quotation": {
                "quotation_id": "Q1", 
                "line_num": 1, 
                "description": "Test Job"
            },
            "next": "SelectionAgent" # We'll start by confirming selection
        }
        
        # Invoke agent with "Yes" to trigger costing
        # This routes: SelectionAgent -> CostingAgent -> End
        result = invoke_agent(
            message="Yes, proceed",
            user_id=123,
            session_state=state,
            conversation_id="conv_test_1"
        )
        
        # --- Verification ---
        
        # 1. Verify Top-Level Trace created
        self.mock_client.trace.assert_called()
        trace_call = self.mock_client.trace.call_args[1]
        self.assertEqual(trace_call["id"], "conv_test_1")
        self.assertEqual(trace_call["user_id"], "123")
        
        mock_trace = self.mock_client.trace.return_value
        
        # 2. Verify Agent Spans created (SelectionAgent, CostingAgent)
        # Note: Depending on routing, Supervisor might be skipped if we injected state? 
        # invoke_agent calls `app.stream(inputs)`.
        # With "Yes" and state, it should hit SelectionAgent then CostingAgent.
        # `trace_agent` decorator creates spans on the TRACE (since no session yet for Selection).
        
        # Check SelectionAgent span
        # It's hard to check exact order in mock calls easily, but we can verify calls exist
        agent_spans = [
            c[1]["name"] for c in mock_trace.span.call_args_list 
            if c[1].get("metadata", {}).get("type") == "agent"
        ]
        self.assertIn("selection_node", agent_spans)
        self.assertIn("costing_node", agent_spans)
        
        # 3. Verify Job Session created
        # In costing_node, we enter `session_context("COST-TEST-123")`.
        # This creates a span on the trace with specific metadata.
        session_calls = [
            c[1] for c in mock_trace.span.call_args_list 
            if c[1].get("metadata", {}).get("session_type") == "costing_job"
        ]
        self.assertEqual(len(session_calls), 1)
        self.assertEqual(session_calls[0]["id"], "COST-TEST-123")
        
        # Get the mock session object
        mock_session = mock_trace.span.return_value
        
        # 4. Verify Workflow Step Spans (under session)
        # These are created via `span_context` inside costing.py
        # e.g. "resolve_prices", "save_line_items", "generate_sheet"
        # They are children of the SESSION span.
        
        # WAIT: `mock_trace.span()` returns a NEW Mock object. 
        # But `session_context` uses `trace.span()` to create the session.
        # Then `span_context` uses `session.span()` to create child spans.
        # Since `mock_trace.span` returns a factory-created mock, subsequent calls return SAME mock?
        # standard MagicMock behavior: return_value is same object unless changed.
        # So `mock_session` IS capturing the calls made on it.
        
        step_spans = [
            c[1]["name"] for c in mock_session.span.call_args_list
        ]
        
        expected_steps = [
            "resolve_prices", 
            "save_line_items", 
            "generate_sheet", 
            "send_quote_emails", 
            "update_sharepoint"
        ]
        for step in expected_steps:
            self.assertIn(step, step_spans)
            
        # 5. Verify Tool Spans (under steps or session)
        # Tool calls decorated with @trace_tool call `span_context`.
        # If called inside a step (which is a span), they should be children of the step span?
        # `span_context` logic: `parent = _current_session.get() or _current_trace.get()`.
        # It does NOT automatically pick up the current SPAN as parent unless I updated logic?
        # Let's check `langfuse_tracing.py`.
        # `parent = _current_session.get() or _current_trace.get()`.
        # Implementation Detail: Currently `span_context` attaches to session if available, else trace.
        # It does NOT create hierarchical spans within the session (spans under spans).
        # So "Tools" called inside "Steps" will be siblings of "Steps" under the Start Session.
        # This is fine for now (flat list of operations under session).
        
        # Check tool spans exist in the session call list too
        self.assertIn("send_email", step_spans) # From _send_quote_emails calling send_email
        # self.assertIn("create_costing_sheet_with_items", step_spans) # From generate_sheet calling tool
        
        # Wait, I mocked `tools.create_costing_sheet_with_items` with a patch.
        # So the real decorated function is NOT called. The patch replaces it.
        # So `create_costing_sheet_with_items` span won't appear because the decorator is on the real function.
        # BUT `send_email` calls inside `_send_quote_emails`. `_send_quote_emails` is internal to costing.py.
        # `_send_quote_emails` calls `tools.send_price_request_email`.
        # I didn't mock `tools.send_price_request_email`. I patched `smtplib`.
        # So `tools.send_price_request_email` (decorated) executes.
        # So "send_price_request_email" span SHOULD exist.
        
        # However, `tools.send_price_request_email` calls `send_email`.
        # `send_email` is decorated.
        # So "send_email" span SHOULD exist.
        
        self.assertIn("send_price_request_email", step_spans)
        self.assertIn("send_email", step_spans)

if __name__ == '__main__':
    unittest.main()
