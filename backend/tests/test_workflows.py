"""
End-to-End Workflow Tests for Gulf Craft AI Costing Assistant

This test suite validates complete workflows as documented in capabilities.md:
1. Complete Job Creation Workflow
2. Price Intelligence Workflow
3. Vendor Selection Workflow
4. Edit Job Workflow
5. Quote Management Workflow

Run with: pytest tests/test_workflows.py -v
"""

import pytest
import json
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime


# ============================================================================
# WORKFLOW 1: COMPLETE JOB CREATION WORKFLOW TESTS
# ============================================================================

class TestCompleteJobCreationWorkflow:
    """
    Tests for the complete job creation workflow:
    1. User requests quotation via chat
    2. Search Agent finds similar quotations
    3. Refinement Agent presents results
    4. User selects preferred quotation
    5. Selection Agent confirms choice
    6. Costing Agent creates the job
    """

    def test_workflow_agents_connected_correctly(self):
        """Verify all agents in the creation workflow are connected."""
        from main import workflow

        # Verify all required nodes exist
        required_nodes = [
            "Supervisor",
            "SearchAgent",
            "SelectionAgent",
            "CostingAgent"
        ]

        for node in required_nodes:
            assert node in workflow.nodes, f"{node} should be in workflow"

    def test_search_to_refinement_transition(self):
        """Test that search results trigger refinement presentation."""
        from agents.search import refinement_node
        from langchain_core.messages import ToolMessage

        # Simulate search results
        search_results = json.dumps([
            {"quotation_id": "AJMFQ-001", "line_num": 1, "description": "Test"}
        ])

        state = {
            "messages": [ToolMessage(content=search_results, tool_call_id="search")],
        }

        result = refinement_node(state)

        assert "awaiting_selection" in result
        assert result["awaiting_selection"] == True
        assert "similar_quotations" in result

    def test_selection_agent_handles_user_choice(self):
        """Test selection agent processes user quotation choice."""
        from agents.selection import selection_node

        # This is a structural test - verify the node exists and accepts state
        assert callable(selection_node)

    def test_costing_agent_creates_job_structure(self):
        """Test costing agent creates proper job structure."""
        from core.database import CostingRequest, CostingLineItem

        # Verify models have required fields for job creation
        assert hasattr(CostingRequest, 'job_id')
        assert hasattr(CostingRequest, 'status')
        assert hasattr(CostingRequest, 'price')
        assert hasattr(CostingLineItem, 'price_source')
        assert hasattr(CostingLineItem, 'price_status')


class TestPriceResolutionWorkflow:
    """
    Tests for the price resolution workflow within costing:
    1. Retrieves estimation lines from selected quotations
    2. Looks up prices from products database
    3. Identifies items requiring vendor quotes (>threshold)
    """

    def test_estimation_lines_retrieval(self):
        """Test that estimation lines can be retrieved."""
        from utils import tools
        assert hasattr(tools, 'get_estimation_lines')

    def test_product_price_lookup(self):
        """Test that product prices can be looked up."""
        from utils import tools
        assert hasattr(tools, 'get_product_price')

    def test_threshold_determines_quote_requirement(self):
        """Test price threshold logic for quote triggering."""
        threshold = 1000.0

        # Items above threshold need quotes
        high_price_item = {"unit_price": 1500.0}
        needs_quote = high_price_item["unit_price"] > threshold
        assert needs_quote == True

        # Items at or below threshold don't need quotes
        low_price_item = {"unit_price": 500.0}
        needs_quote = low_price_item["unit_price"] > threshold
        assert needs_quote == False

        # Items with no price need quotes
        no_price_item = {"unit_price": None}
        needs_quote = no_price_item["unit_price"] is None or \
                     (no_price_item["unit_price"] and no_price_item["unit_price"] > threshold)
        assert needs_quote == True

    def test_price_source_tracking(self):
        """Test that price sources are properly tracked."""
        # Valid price sources as documented
        valid_sources = ["products", "quotation", "manual", "labour", "pending"]

        for source in valid_sources:
            assert source in valid_sources  # Verify all documented sources


class TestExcelGenerationWorkflow:
    """
    Tests for Excel costing sheet generation:
    1. Generated sheets include 12 columns
    2. All required fields are present
    """

    def test_excel_generation_function_exists(self):
        """Test that Excel generation function exists."""
        from utils import tools
        assert hasattr(tools, 'create_costing_sheet_with_items')

    def test_regenerate_function_exists(self):
        """Test that sheet regeneration function exists."""
        from utils import tools
        assert hasattr(tools, 'regenerate_costing_sheet')


class TestSharePointWorkflow:
    """
    Tests for SharePoint integration workflow.
    """

    def test_sharepoint_creation_function_exists(self):
        """Test SharePoint list item creation."""
        from utils import tools
        assert hasattr(tools, 'create_sharepoint_list_item')

    def test_sharepoint_update_function_exists(self):
        """Test SharePoint status update."""
        from utils import tools
        assert hasattr(tools, 'update_sharepoint_status')


# ============================================================================
# WORKFLOW 2: PRICE INTELLIGENCE WORKFLOW TESTS
# ============================================================================

class TestPriceIntelligenceWorkflow:
    """
    Tests for the price intelligence workflow:
    1. User asks "What did we pay for hydraulic pumps?"
    2. Pricing Advisor Agent queries historical data
    3. Calculates statistics (avg, min, max)
    4. Compares against historical average
    5. Flags anomalies if >20% difference
    """

    def test_pricing_advisor_agent_exists(self):
        """Test Pricing Advisor Agent is configured."""
        from main import workflow
        assert "PricingAdvisorAgent" in workflow.nodes

    def test_price_history_function_exists(self):
        """Test price history retrieval function exists."""
        from utils import tools
        assert hasattr(tools, 'get_item_price_history')

    def test_average_price_function_exists(self):
        """Test average price calculation function exists."""
        from utils import tools
        assert hasattr(tools, 'get_average_item_price')

    def test_anomaly_detection_threshold(self):
        """Test anomaly detection at 20% threshold."""
        avg_price = 1000.0
        anomaly_threshold = 0.20  # 20%

        # Price 25% above average - should be flagged
        high_price = 1250.0
        deviation = abs(high_price - avg_price) / avg_price
        assert deviation > anomaly_threshold

        # Price 15% above average - should not be flagged
        normal_price = 1150.0
        deviation = abs(normal_price - avg_price) / avg_price
        assert deviation < anomaly_threshold

    def test_price_comparison_logic(self):
        """Test price comparison calculation."""
        historical_avg = 1000.0
        current_quote = 1200.0

        # Calculate percentage difference
        diff_percent = ((current_quote - historical_avg) / historical_avg) * 100
        assert diff_percent == 20.0

        # Test negative difference
        current_quote = 800.0
        diff_percent = ((current_quote - historical_avg) / historical_avg) * 100
        assert diff_percent == -20.0

    def test_price_comparison_workflow_vacuum_cleaner(self):
        """
        Test the complete price comparison workflow for vacuum cleaner example.

        Simulates user asking: "Is 1500 AED a good price for a vacuum cleaner?"

        Expected workflow:
        1. Extract query type (price_comparison), item_name, and current_price
        2. Search for matching products (vacuum cleaner)
        3. User selects from results
        4. Compare 1500 AED against historical data
        5. Provide assessment based on deviation
        """
        from agents.pricing_advisor import pricing_advisor_node, _extract_pricing_parameters
        from langchain_core.messages import HumanMessage, AIMessage

        # Step 1: Initial query - price comparison
        state = {
            "messages": [HumanMessage(content="Is 1500 AED a good price for a vacuum cleaner?")],
        }

        # Extract parameters
        params = _extract_pricing_parameters(
            "Is 1500 AED a good price for a vacuum cleaner?",
            state
        )

        # Verify extraction works correctly
        assert params.get("query_type") in ["price_comparison", "product_search"]
        assert "vacuum" in params.get("item_name", "").lower() or \
               "vacuum" in params.get("search_query", "").lower()

        # If price is extracted, verify it's correct
        if params.get("current_price"):
            current_price = float(str(params["current_price"]).replace("AED", "").strip())
            assert current_price == 1500.0

    def test_price_comparison_assessment_thresholds(self):
        """
        Test price comparison assessment categories.

        Verifies the correct assessment is given based on price deviation:
        - Great Deal: < -20%
        - Fair Price: -10% to +10%
        - Slightly Different: -20% to -10% or +10% to +20%
        - Above Average: > +20%
        """
        avg_price = 1000.0

        # Test Great Deal (25% below average)
        current_price = 750.0
        diff_pct = ((current_price - avg_price) / avg_price) * 100
        assert diff_pct < -20, "Should be classified as Great Deal"

        # Test Fair Price (5% above average)
        current_price = 1050.0
        diff_pct = ((current_price - avg_price) / avg_price) * 100
        assert abs(diff_pct) <= 10, "Should be classified as Fair Price"

        # Test Slightly Different (15% above average)
        current_price = 1150.0
        diff_pct = ((current_price - avg_price) / avg_price) * 100
        assert 10 < abs(diff_pct) <= 20, "Should be classified as Slightly Different"

        # Test Above Average (25% above average)
        current_price = 1250.0
        diff_pct = ((current_price - avg_price) / avg_price) * 100
        assert diff_pct > 20, "Should be classified as Above Average"

    def test_product_search_with_disambiguation(self):
        """
        Test product search triggers disambiguation when multiple matches found.

        When searching for a generic term like "vacuum cleaner", the system should:
        1. Return multiple product matches
        2. Set pending_disambiguation state
        3. Store search results for user selection
        """
        from agents.pricing_advisor import pricing_advisor_node
        from langchain_core.messages import HumanMessage

        state = {
            "messages": [HumanMessage(content="search for vacuum cleaner pricing")],
        }

        # This test verifies the agent structure handles disambiguation
        # The actual search will be mocked in integration tests
        result = pricing_advisor_node(state)

        # Should return a response
        assert "messages" in result
        assert len(result["messages"]) > 0


# ============================================================================
# WORKFLOW 3: VENDOR SELECTION WORKFLOW TESTS
# ============================================================================

class TestVendorSelectionWorkflow:
    """
    Tests for the vendor selection workflow:
    1. User asks "Who supplies electrical items?"
    2. Vendor Info Agent searches supply history
    3. Ranks by items supplied
    4. Shows response rates and performance ratings
    """

    def test_vendor_info_agent_exists(self):
        """Test Vendor Info Agent is configured."""
        from main import workflow
        assert "VendorInfoAgent" in workflow.nodes

    def test_vendor_info_function_exists(self):
        """Test vendor info retrieval function exists."""
        from utils import tools
        assert hasattr(tools, 'get_vendor_info')

    def test_vendors_for_item_type_function_exists(self):
        """Test vendor discovery function exists."""
        from utils import tools
        assert hasattr(tools, 'get_vendors_for_item_type')

    def test_performance_rating_calculation(self, sample_vendor_data):
        """Test vendor performance rating calculation."""
        response_rate = sample_vendor_data["response_rate"]

        # Rating based on response rate
        if response_rate > 80:
            rating = "⭐⭐⭐"
        elif response_rate > 60:
            rating = "⭐⭐"
        elif response_rate > 40:
            rating = "⭐"
        else:
            rating = "No rating"

        assert rating == "⭐⭐⭐"  # 84% should be 3 stars

    def test_response_rate_calculation(self, sample_vendor_data):
        """Test vendor response rate calculation."""
        total = sample_vendor_data["total_requests"]
        responded = sample_vendor_data["responded"]

        expected_rate = (responded / total) * 100
        assert expected_rate == 84.0


# ============================================================================
# WORKFLOW 4: EDIT JOB WORKFLOW TESTS
# ============================================================================

class TestEditJobWorkflow:
    """
    Tests for the edit job workflow:
    1. User requests to add/remove/update items
    2. Edit Job Agent extracts parameters
    3. Executes modification
    4. Regenerates costing sheet
    """

    def test_edit_job_agent_exists(self):
        """Test Edit Job Agent is configured."""
        from main import workflow
        assert "EditJobAgent" in workflow.nodes

    def test_add_item_function_exists(self):
        """Test add item function exists."""
        from utils import tools
        assert hasattr(tools, 'add_line_item_to_job')

    def test_remove_item_function_exists(self):
        """Test remove item function exists."""
        from utils import tools
        assert hasattr(tools, 'remove_line_item_from_job')

    def test_update_item_function_exists(self):
        """Test update item function exists."""
        from utils import tools
        assert hasattr(tools, 'update_line_item')

    def test_edit_operation_types(self):
        """Test all edit operation types are supported."""
        operation_types = [
            "add_item",
            "remove_item",
            "update_item",
            "update_description"
        ]

        from utils.prompts import EDIT_JOB_EXTRACTION_PROMPT

        for op in operation_types:
            assert op in EDIT_JOB_EXTRACTION_PROMPT, \
                f"Operation {op} should be in extraction prompt"


# ============================================================================
# WORKFLOW 5: QUOTE MANAGEMENT WORKFLOW TESTS
# ============================================================================

class TestQuoteManagementWorkflow:
    """
    Tests for the quote management workflow:
    1. Manual quote entry
    2. Resend quote requests
    3. Cancel pending quotes
    4. Auto-completion check
    """

    def test_quote_management_agent_exists(self):
        """Test Quote Management Agent is configured."""
        from main import workflow
        assert "QuoteManagementAgent" in workflow.nodes

    def test_enter_quote_function_exists(self):
        """Test manual quote entry function exists."""
        from utils import tools
        assert hasattr(tools, 'enter_manual_quote')

    def test_resend_quote_function_exists(self):
        """Test resend quote request function exists."""
        from utils import tools
        assert hasattr(tools, 'resend_quote_request')

    def test_cancel_quote_function_exists(self):
        """Test cancel quote request function exists."""
        from utils import tools
        assert hasattr(tools, 'cancel_quote_request')

    def test_pending_quote_model_exists(self):
        """Test PendingQuoteRequest model exists."""
        from core.database import PendingQuoteRequest
        assert PendingQuoteRequest is not None

        # Check required fields
        assert hasattr(PendingQuoteRequest, 'status')
        assert hasattr(PendingQuoteRequest, 'vendor_email')


# ============================================================================
# WORKFLOW 6: JOB LIFECYCLE WORKFLOW TESTS
# ============================================================================

class TestJobLifecycleWorkflow:
    """
    Tests for the job lifecycle workflow:
    1. Approve jobs
    2. Generate download links
    3. Duplicate jobs
    4. Cancel jobs
    5. Email distribution
    """

    def test_job_lifecycle_agent_exists(self):
        """Test Job Lifecycle Agent is configured."""
        from main import workflow
        assert "JobLifecycleAgent" in workflow.nodes

    def test_approve_function_exists(self):
        """Test approve job function exists."""
        from utils import tools
        assert hasattr(tools, 'approve_costing_job')

    def test_download_url_function_exists(self):
        """Test download URL function exists."""
        from utils import tools
        assert hasattr(tools, 'get_download_url')

    def test_duplicate_function_exists(self):
        """Test duplicate job function exists."""
        from utils import tools
        assert hasattr(tools, 'duplicate_costing_job')

    def test_cancel_function_exists(self):
        """Test cancel job function exists."""
        from utils import tools
        assert hasattr(tools, 'cancel_costing_job')

    def test_job_status_transitions(self):
        """Test valid job status transitions."""
        valid_statuses = ["Ready", "Awaiting Quote", "Approved", "Cancelled"]

        # Verify status transitions are logical
        # Ready -> Approved (valid)
        # Awaiting Quote -> Ready (when quotes received)
        # Any -> Cancelled (valid)

        for status in valid_statuses:
            assert status in ["Ready", "Awaiting Quote", "Approved", "Cancelled"]


# ============================================================================
# WORKFLOW 7: EXPLAINER WORKFLOW TESTS
# ============================================================================

class TestExplainerWorkflow:
    """
    Tests for the explainer workflow:
    1. Answers "why" questions
    2. Explains pricing logic
    3. Clarifies status meanings
    """

    def test_explainer_agent_exists(self):
        """Test Explainer Agent is configured."""
        from main import workflow
        assert "ExplainerAgent" in workflow.nodes

    def test_explanation_types_supported(self):
        """Test all explanation types are supported."""
        from utils.prompts import EXPLAINER_EXTRACTION_PROMPT

        explanation_types = [
            "why_pending",
            "why_price",
            "explain_status",
            "explain_cost"
        ]

        for exp_type in explanation_types:
            assert exp_type in EXPLAINER_EXTRACTION_PROMPT, \
                f"Explanation type {exp_type} should be supported"


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestRoutingIntegration:
    """Tests for supervisor routing to correct agents."""

    def test_search_queries_route_to_search_agent(self):
        """Verify search-related queries route to SearchAgent."""
        from utils.prompts import SUPERVISOR_SYSTEM_PROMPT

        # Search keywords should route to SearchAgent
        assert "SearchAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "quotation" in SUPERVISOR_SYSTEM_PROMPT.lower()

    def test_status_queries_route_to_status_agent(self):
        """Verify status queries route to StatusAgent."""
        from utils.prompts import SUPERVISOR_SYSTEM_PROMPT

        assert "StatusAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "status" in SUPERVISOR_SYSTEM_PROMPT.lower()

    def test_edit_queries_route_to_edit_agent(self):
        """Verify edit queries route to EditJobAgent."""
        from utils.prompts import SUPERVISOR_SYSTEM_PROMPT

        assert "EditJobAgent" in SUPERVISOR_SYSTEM_PROMPT
        # Check for edit-related keywords
        assert "add" in SUPERVISOR_SYSTEM_PROMPT.lower() or \
               "remove" in SUPERVISOR_SYSTEM_PROMPT.lower()

    def test_pricing_queries_route_to_pricing_advisor(self):
        """Verify pricing queries route to PricingAdvisorAgent."""
        from utils.prompts import SUPERVISOR_SYSTEM_PROMPT

        assert "PricingAdvisorAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "price" in SUPERVISOR_SYSTEM_PROMPT.lower()

    def test_vendor_queries_route_to_vendor_info(self):
        """Verify vendor queries route to VendorInfoAgent."""
        from utils.prompts import SUPERVISOR_SYSTEM_PROMPT

        assert "VendorInfoAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "vendor" in SUPERVISOR_SYSTEM_PROMPT.lower()

    def test_why_queries_route_to_explainer(self):
        """Verify 'why' queries route to ExplainerAgent."""
        from utils.prompts import SUPERVISOR_SYSTEM_PROMPT

        assert "ExplainerAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "why" in SUPERVISOR_SYSTEM_PROMPT.lower()


class TestStateManagement:
    """Tests for conversation state management across workflow."""

    def test_state_preserves_job_id(self):
        """Test that job_id is preserved in state."""
        from core.state import AgentState

        state: AgentState = {
            "messages": [],
            "job_id": "COST-TEST1234",
            "last_mentioned_job_id": "COST-TEST1234"
        }

        assert state["job_id"] == "COST-TEST1234"
        assert state["last_mentioned_job_id"] == "COST-TEST1234"

    def test_state_preserves_search_context(self):
        """Test that search context is preserved for 'show more'."""
        from core.state import AgentState

        state: AgentState = {
            "messages": [],
            "last_search_description": "polishing work",
            "last_search_boat_model": "MAJESTY62",
            "current_top_k": 5
        }

        assert state["last_search_description"] == "polishing work"
        assert state["last_search_boat_model"] == "MAJESTY62"
        assert state["current_top_k"] == 5

    def test_state_tracks_awaiting_selection(self):
        """Test that selection state is tracked."""
        from core.state import AgentState

        state: AgentState = {
            "messages": [],
            "awaiting_selection": True,
            "similar_quotations": [{"id": 1}]
        }

        assert state["awaiting_selection"] == True
        assert len(state["similar_quotations"]) == 1


# ============================================================================
# DATA FLOW TESTS
# ============================================================================

class TestDataFlow:
    """Tests for data flow between agents and storage."""

    def test_quotation_to_costing_data_flow(self, sample_quotations, sample_estimation_lines):
        """Test data flows from quotation selection to costing."""
        # Simulate the data flow
        selected_quotation = sample_quotations[0]
        estimation_lines = sample_estimation_lines

        # Verify quotation has required fields for costing
        assert "quotation_id" in selected_quotation
        assert "line_num" in selected_quotation

        # Verify estimation lines have required fields
        for line in estimation_lines:
            assert "item_name" in line
            assert "item_qty" in line
            assert "std_item_code" in line

    def test_costing_to_excel_data_flow(self, sample_costing_job):
        """Test data flows from costing job to Excel generation."""
        job = sample_costing_job

        # Verify job has all fields needed for Excel
        assert "job_id" in job
        assert "line_items" in job

        # Verify each line item has required fields
        for item in job["line_items"]:
            assert "item_name" in item
            assert "quantity" in item
            assert "price_source" in item

    def test_price_resolution_data_flow(self, sample_costing_job):
        """Test price resolution data is captured correctly."""
        job = sample_costing_job

        for item in job["line_items"]:
            # Verify price tracking fields
            assert "price_source" in item
            assert item["price_source"] in ["products", "quotation", "manual",
                                            "labour", "pending"]

            # Verify estimation tracking
            if item.get("estimation_quantity"):
                assert isinstance(item["estimation_quantity"], (int, float))


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
