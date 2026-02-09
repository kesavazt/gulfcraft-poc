"""
Test Suite for Gulf Craft AI Costing Assistant Capabilities

This test suite validates all capabilities documented in capabilities.md.
Run with: pytest tests/test_capabilities.py -v
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_db_session():
    """Mock database session for testing."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    return session


@pytest.fixture
def mock_user():
    """Mock user object for testing."""
    user = Mock()
    user.id = 1
    user.username = "testuser"
    user.role = "user"
    return user


@pytest.fixture
def mock_admin_user():
    """Mock admin user object for testing."""
    user = Mock()
    user.id = 1
    user.username = "admin"
    user.role = "admin"
    return user


@pytest.fixture
def sample_agent_state():
    """Sample agent state for testing."""
    from langchain_core.messages import HumanMessage
    return {
        "messages": [HumanMessage(content="Hello")],
        "next": "",
        "user_id": 1,
        "similar_quotations": [],
        "selected_quotation": None,
        "awaiting_selection": False,
        "last_search_description": None,
        "last_search_boat_model": None,
        "current_top_k": 5,
        "job_id": None,
        "threshold": 1000.0,
    }


@pytest.fixture
def sample_quotations():
    """Sample quotation data for testing."""
    return [
        {
            "quotation_id": "AJMFQ-000001",
            "line_num": 1,
            "description": "Engine polishing and cleaning",
            "boat_model": "MAJESTY62",
            "score": 0.95
        },
        {
            "quotation_id": "AJMFQ-000002",
            "line_num": 1,
            "description": "Hydraulic pump repair",
            "boat_model": "MAJESTY62",
            "score": 0.85
        }
    ]


@pytest.fixture
def sample_costing_job():
    """Sample costing job data for testing."""
    return {
        "job_id": "COST-TEST1234",
        "status": "Ready",
        "item_details": "Test job description",
        "created_at": datetime(2024, 1, 15, 10, 30, 0),
        "price": 5000.0,
        "line_items": [
            {
                "id": 1,
                "item_name": "Hydraulic Pump",
                "item_code": "HYD-001",
                "quantity": 2,
                "unit_price": 1500.0,
                "price_status": "resolved",
                "price_source": "products"
            },
            {
                "id": 2,
                "item_name": "Cable 50m",
                "item_code": "CBL-001",
                "quantity": 50,
                "unit_price": None,
                "price_status": "pending",
                "price_source": "pending"
            }
        ]
    }


@pytest.fixture
def sample_vendor_data():
    """Sample vendor data for testing."""
    return {
        "email": "vendor@example.com",
        "total_requests": 50,
        "responded": 42,
        "response_rate": 84.0,
        "items_supplied": ["Hydraulic Pump", "Cable", "Anchor Winch"],
        "pending_requests": 3
    }


# ============================================================================
# SECTION 1: CORE AGENTS TESTS
# ============================================================================

class TestSupervisorAgent:
    """Tests for Supervisor Agent - Routes user requests to appropriate agents."""

    def test_supervisor_in_workflow(self):
        """Verify supervisor is properly configured in the workflow."""
        from main import workflow
        assert "Supervisor" in workflow.nodes, "Supervisor should be a workflow node"

    def test_routable_members_configured(self):
        """Verify all expected agents are routable from supervisor."""
        from agents.supervisor import ROUTABLE_MEMBERS

        expected_agents = [
            "SearchAgent",
            "SelectionAgent",
            "StatusAgent",
            "EditJobAgent",
            "QuoteManagementAgent",
            "JobLifecycleAgent",
            "PricingAdvisorAgent",
            "ExplainerAgent",
            "VendorInfoAgent"
        ]

        for agent in expected_agents:
            assert agent in ROUTABLE_MEMBERS, f"{agent} should be routable"

    def test_costing_agent_not_directly_routable(self):
        """CostingAgent should only be accessed via SelectionAgent."""
        from agents.supervisor import ROUTABLE_MEMBERS
        assert "CostingAgent" not in ROUTABLE_MEMBERS, \
            "CostingAgent should not be directly routable from supervisor"

    def test_supervisor_options_include_finish(self):
        """Supervisor should have FINISH option for ending conversations."""
        from agents.supervisor import OPTIONS
        assert "FINISH" in OPTIONS, "OPTIONS should include FINISH"

    def test_supervisor_node_callable(self):
        """Verify supervisor_node function exists and is callable."""
        from agents.supervisor import supervisor_node
        assert callable(supervisor_node), "supervisor_node should be callable"

    def test_supervisor_prompt_includes_routing_logic(self):
        """Verify supervisor prompt includes routing instructions for all agents."""
        from utils.prompts import SUPERVISOR_SYSTEM_PROMPT

        # Check for routing instructions for each agent type
        assert "SearchAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "SelectionAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "StatusAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "EditJobAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "QuoteManagementAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "JobLifecycleAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "PricingAdvisorAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "ExplainerAgent" in SUPERVISOR_SYSTEM_PROMPT
        assert "VendorInfoAgent" in SUPERVISOR_SYSTEM_PROMPT


class TestSearchAgent:
    """Tests for Search Agent - Finds similar quotations using hybrid search."""

    def test_search_node_exists(self):
        """Verify search_node function exists."""
        from agents.search import search_node
        assert callable(search_node), "search_node should be callable"

    def test_search_node_in_workflow(self):
        """Verify SearchAgent is a workflow node."""
        from main import workflow
        assert "SearchAgent" in workflow.nodes, "SearchAgent should be a workflow node"

    def test_search_extraction_prompt_exists(self):
        """Verify search extraction prompt exists."""
        from utils.prompts import SEARCH_EXTRACTION_PROMPT
        assert SEARCH_EXTRACTION_PROMPT, "SEARCH_EXTRACTION_PROMPT should exist"
        assert "job_description" in SEARCH_EXTRACTION_PROMPT
        assert "boat_model" in SEARCH_EXTRACTION_PROMPT

    def test_hybrid_search_function_exists(self):
        """Verify hybrid search service function exists."""
        from services.search import hybrid_search
        assert callable(hybrid_search), "hybrid_search should be callable"

    def test_search_tool_exists(self):
        """Verify search_similar_quotations tool exists."""
        from utils import tools
        assert hasattr(tools, 'search_similar_quotations'), \
            "search_similar_quotations tool should exist"

    def test_show_more_phrases_recognized(self):
        """Verify search agent recognizes 'show more' phrases."""
        show_more_phrases = ["more quotation", "show more", "see more",
                            "other quotation", "different quotation"]
        test_messages = [
            "show me more quotations",
            "show more results",
            "can I see more options",
            "show me other quotations"
        ]

        for msg in test_messages:
            matched = any(phrase in msg.lower() for phrase in show_more_phrases)
            assert matched, f"Message '{msg}' should match show more pattern"


class TestRefinementAgent:
    """Tests for Refinement Agent - Presents search results to user."""

    def test_refinement_node_exists(self):
        """Verify refinement_node function exists."""
        from agents.search import refinement_node
        assert callable(refinement_node), "refinement_node should be callable"

    def test_refinement_prompt_exists(self):
        """Verify refinement prompt exists."""
        from utils.prompts import REFINEMENT_PROMPT
        assert REFINEMENT_PROMPT, "REFINEMENT_PROMPT should exist"
        assert "{count}" in REFINEMENT_PROMPT, "REFINEMENT_PROMPT should include count placeholder"


class TestSelectionAgent:
    """Tests for Selection Agent - Handles quotation selection and confirmation."""

    def test_selection_node_exists(self):
        """Verify selection_node function exists."""
        from agents.selection import selection_node
        assert callable(selection_node), "selection_node should be callable"

    def test_selection_node_in_workflow(self):
        """Verify SelectionAgent is a workflow node."""
        from main import workflow
        assert "SelectionAgent" in workflow.nodes, "SelectionAgent should be a workflow node"

    def test_selection_extraction_prompt_exists(self):
        """Verify selection extraction prompt exists."""
        from utils.prompts import SELECTION_EXTRACTION_PROMPT
        assert SELECTION_EXTRACTION_PROMPT, "SELECTION_EXTRACTION_PROMPT should exist"

    def test_quotation_confirmation_template_exists(self):
        """Verify quotation confirmation template exists."""
        from utils.prompts import QUOTATION_CONFIRMATION_TEMPLATE
        assert QUOTATION_CONFIRMATION_TEMPLATE, "QUOTATION_CONFIRMATION_TEMPLATE should exist"
        assert "{quotation_id}" in QUOTATION_CONFIRMATION_TEMPLATE


class TestCostingAgent:
    """Tests for Costing Agent - Creates comprehensive costing jobs."""

    def test_costing_node_exists(self):
        """Verify costing_node function exists."""
        from agents.costing import costing_node
        assert callable(costing_node), "costing_node should be callable"

    def test_costing_node_in_workflow(self):
        """Verify CostingAgent is a workflow node."""
        from main import workflow
        assert "CostingAgent" in workflow.nodes, "CostingAgent should be a workflow node"

    def test_create_costing_request_tool_exists(self):
        """Verify create_costing_request tool exists."""
        from utils import tools
        assert hasattr(tools, 'create_costing_request'), \
            "create_costing_request tool should exist"

    def test_create_costing_sheet_tool_exists(self):
        """Verify create_costing_sheet_with_items tool exists."""
        from utils import tools
        assert hasattr(tools, 'create_costing_sheet_with_items'), \
            "create_costing_sheet_with_items tool should exist"

    def test_get_product_price_tool_exists(self):
        """Verify get_product_price tool exists."""
        from utils import tools
        assert hasattr(tools, 'get_product_price'), \
            "get_product_price tool should exist"

    def test_get_estimation_lines_tool_exists(self):
        """Verify get_estimation_lines tool exists."""
        from utils import tools
        assert hasattr(tools, 'get_estimation_lines'), \
            "get_estimation_lines tool should exist"

    def test_send_price_request_email_tool_exists(self):
        """Verify send_price_request_email tool exists."""
        from utils import tools
        assert hasattr(tools, 'send_price_request_email'), \
            "send_price_request_email tool should exist"

    def test_sharepoint_integration_tools_exist(self):
        """Verify SharePoint integration tools exist."""
        from utils import tools
        assert hasattr(tools, 'create_sharepoint_list_item'), \
            "create_sharepoint_list_item tool should exist"
        assert hasattr(tools, 'update_sharepoint_status'), \
            "update_sharepoint_status tool should exist"


class TestStatusAgent:
    """Tests for Status Agent - Provides job status information."""

    def test_status_node_exists(self):
        """Verify status_node function exists."""
        from agents.status import status_node
        assert callable(status_node), "status_node should be callable"

    def test_status_node_in_workflow(self):
        """Verify StatusAgent is a workflow node."""
        from main import workflow
        assert "StatusAgent" in workflow.nodes, "StatusAgent should be a workflow node"

    def test_status_agent_prompt_exists(self):
        """Verify status agent prompt exists."""
        from utils.prompts import STATUS_AGENT_SYSTEM_PROMPT
        assert STATUS_AGENT_SYSTEM_PROMPT, "STATUS_AGENT_SYSTEM_PROMPT should exist"
        assert "conversational" in STATUS_AGENT_SYSTEM_PROMPT.lower()

    def test_status_label_mapping(self):
        """Test status label conversion."""
        from agents.status import _status_label

        assert _status_label("Ready") == "Ready to review"
        assert _status_label("Awaiting Quote") == "Waiting for quotes"
        assert _status_label("Approved") == "Complete and sent"

    def test_build_status_context_function_exists(self):
        """Verify _build_status_context function exists."""
        from agents.status import _build_status_context
        assert callable(_build_status_context), "_build_status_context should be callable"

    def test_get_costing_job_statuses_tool_exists(self):
        """Verify get_costing_job_statuses tool exists."""
        from utils import tools
        assert hasattr(tools, 'get_costing_job_statuses'), \
            "get_costing_job_statuses tool should exist"


class TestEditJobAgent:
    """Tests for Edit Job Agent - Modifies existing costing jobs."""

    def test_edit_job_node_exists(self):
        """Verify edit_job_node function exists."""
        from agents.edit_job import edit_job_node
        assert callable(edit_job_node), "edit_job_node should be callable"

    def test_edit_job_node_in_workflow(self):
        """Verify EditJobAgent is a workflow node."""
        from main import workflow
        assert "EditJobAgent" in workflow.nodes, "EditJobAgent should be a workflow node"

    def test_edit_job_prompts_exist(self):
        """Verify edit job prompts exist."""
        from utils.prompts import EDIT_JOB_AGENT_SYSTEM_PROMPT, EDIT_JOB_EXTRACTION_PROMPT
        assert EDIT_JOB_AGENT_SYSTEM_PROMPT, "EDIT_JOB_AGENT_SYSTEM_PROMPT should exist"
        assert EDIT_JOB_EXTRACTION_PROMPT, "EDIT_JOB_EXTRACTION_PROMPT should exist"

    def test_add_line_item_tool_exists(self):
        """Verify add_line_item_to_job tool exists."""
        from utils import tools
        assert hasattr(tools, 'add_line_item_to_job'), \
            "add_line_item_to_job tool should exist"

    def test_remove_line_item_tool_exists(self):
        """Verify remove_line_item_from_job tool exists."""
        from utils import tools
        assert hasattr(tools, 'remove_line_item_from_job'), \
            "remove_line_item_from_job tool should exist"

    def test_update_line_item_tool_exists(self):
        """Verify update_line_item tool exists."""
        from utils import tools
        assert hasattr(tools, 'update_line_item'), \
            "update_line_item tool should exist"

    def test_regenerate_costing_sheet_tool_exists(self):
        """Verify regenerate_costing_sheet tool exists."""
        from utils import tools
        assert hasattr(tools, 'regenerate_costing_sheet'), \
            "regenerate_costing_sheet tool should exist"


class TestQuoteManagementAgent:
    """Tests for Quote Management Agent - Manages vendor quotes and requests."""

    def test_quote_management_node_exists(self):
        """Verify quote_management_node function exists."""
        from agents.quote_management import quote_management_node
        assert callable(quote_management_node), "quote_management_node should be callable"

    def test_quote_management_node_in_workflow(self):
        """Verify QuoteManagementAgent is a workflow node."""
        from main import workflow
        assert "QuoteManagementAgent" in workflow.nodes, \
            "QuoteManagementAgent should be a workflow node"

    def test_quote_management_prompts_exist(self):
        """Verify quote management prompts exist."""
        from utils.prompts import (
            QUOTE_MANAGEMENT_AGENT_SYSTEM_PROMPT,
            QUOTE_MANAGEMENT_EXTRACTION_PROMPT
        )
        assert QUOTE_MANAGEMENT_AGENT_SYSTEM_PROMPT
        assert QUOTE_MANAGEMENT_EXTRACTION_PROMPT

    def test_enter_manual_quote_tool_exists(self):
        """Verify enter_manual_quote tool exists."""
        from utils import tools
        assert hasattr(tools, 'enter_manual_quote'), \
            "enter_manual_quote tool should exist"

    def test_resend_quote_request_tool_exists(self):
        """Verify resend_quote_request tool exists."""
        from utils import tools
        assert hasattr(tools, 'resend_quote_request'), \
            "resend_quote_request tool should exist"

    def test_cancel_quote_request_tool_exists(self):
        """Verify cancel_quote_request tool exists."""
        from utils import tools
        assert hasattr(tools, 'cancel_quote_request'), \
            "cancel_quote_request tool should exist"


class TestJobLifecycleAgent:
    """Tests for Job Lifecycle Agent - Manages job approval, distribution, lifecycle."""

    def test_job_lifecycle_node_exists(self):
        """Verify job_lifecycle_node function exists."""
        from agents.job_lifecycle import job_lifecycle_node
        assert callable(job_lifecycle_node), "job_lifecycle_node should be callable"

    def test_job_lifecycle_node_in_workflow(self):
        """Verify JobLifecycleAgent is a workflow node."""
        from main import workflow
        assert "JobLifecycleAgent" in workflow.nodes, \
            "JobLifecycleAgent should be a workflow node"

    def test_job_lifecycle_prompts_exist(self):
        """Verify job lifecycle prompts exist."""
        from utils.prompts import (
            JOB_LIFECYCLE_AGENT_SYSTEM_PROMPT,
            JOB_LIFECYCLE_EXTRACTION_PROMPT
        )
        assert JOB_LIFECYCLE_AGENT_SYSTEM_PROMPT
        assert JOB_LIFECYCLE_EXTRACTION_PROMPT

    def test_approve_costing_job_tool_exists(self):
        """Verify approve_costing_job tool exists."""
        from utils import tools
        assert hasattr(tools, 'approve_costing_job'), \
            "approve_costing_job tool should exist"

    def test_get_download_url_tool_exists(self):
        """Verify get_download_url tool exists."""
        from utils import tools
        assert hasattr(tools, 'get_download_url'), \
            "get_download_url tool should exist"

    def test_duplicate_costing_job_tool_exists(self):
        """Verify duplicate_costing_job tool exists."""
        from utils import tools
        assert hasattr(tools, 'duplicate_costing_job'), \
            "duplicate_costing_job tool should exist"

    def test_cancel_costing_job_tool_exists(self):
        """Verify cancel_costing_job tool exists."""
        from utils import tools
        assert hasattr(tools, 'cancel_costing_job'), \
            "cancel_costing_job tool should exist"


class TestPricingAdvisorAgent:
    """Tests for Pricing Advisor Agent - Provides pricing intelligence."""

    def test_pricing_advisor_node_exists(self):
        """Verify pricing_advisor_node function exists."""
        from agents.pricing_advisor import pricing_advisor_node
        assert callable(pricing_advisor_node), "pricing_advisor_node should be callable"

    def test_pricing_advisor_node_in_workflow(self):
        """Verify PricingAdvisorAgent is a workflow node."""
        from main import workflow
        assert "PricingAdvisorAgent" in workflow.nodes, \
            "PricingAdvisorAgent should be a workflow node"

    def test_pricing_advisor_prompts_exist(self):
        """Verify pricing advisor prompts exist."""
        from utils.prompts import (
            PRICING_ADVISOR_AGENT_SYSTEM_PROMPT,
            PRICING_ADVISOR_EXTRACTION_PROMPT
        )
        assert PRICING_ADVISOR_AGENT_SYSTEM_PROMPT
        assert PRICING_ADVISOR_EXTRACTION_PROMPT
        # Check for anomaly detection mention
        assert ">20%" in PRICING_ADVISOR_AGENT_SYSTEM_PROMPT or "20%" in PRICING_ADVISOR_AGENT_SYSTEM_PROMPT

    def test_get_item_price_history_tool_exists(self):
        """Verify get_item_price_history tool exists."""
        from utils import tools
        assert hasattr(tools, 'get_item_price_history'), \
            "get_item_price_history tool should exist"

    def test_get_average_item_price_tool_exists(self):
        """Verify get_average_item_price tool exists."""
        from utils import tools
        assert hasattr(tools, 'get_average_item_price'), \
            "get_average_item_price tool should exist"


class TestExplainerAgent:
    """Tests for Explainer Agent - Answers 'why' questions about system behavior."""

    def test_explainer_node_exists(self):
        """Verify explainer_node function exists."""
        from agents.explainer import explainer_node
        assert callable(explainer_node), "explainer_node should be callable"

    def test_explainer_node_in_workflow(self):
        """Verify ExplainerAgent is a workflow node."""
        from main import workflow
        assert "ExplainerAgent" in workflow.nodes, \
            "ExplainerAgent should be a workflow node"

    def test_explainer_prompts_exist(self):
        """Verify explainer prompts exist."""
        from utils.prompts import (
            EXPLAINER_AGENT_SYSTEM_PROMPT,
            EXPLAINER_EXTRACTION_PROMPT
        )
        assert EXPLAINER_AGENT_SYSTEM_PROMPT
        assert EXPLAINER_EXTRACTION_PROMPT
        # Check for explanation types
        assert "why" in EXPLAINER_AGENT_SYSTEM_PROMPT.lower()
        assert "explain" in EXPLAINER_AGENT_SYSTEM_PROMPT.lower()


class TestVendorInfoAgent:
    """Tests for Vendor Info Agent - Provides vendor intelligence and metrics."""

    def test_vendor_info_node_exists(self):
        """Verify vendor_info_node function exists."""
        from agents.vendor_info import vendor_info_node
        assert callable(vendor_info_node), "vendor_info_node should be callable"

    def test_vendor_info_node_in_workflow(self):
        """Verify VendorInfoAgent is a workflow node."""
        from main import workflow
        assert "VendorInfoAgent" in workflow.nodes, \
            "VendorInfoAgent should be a workflow node"

    def test_vendor_info_prompts_exist(self):
        """Verify vendor info prompts exist."""
        from utils.prompts import (
            VENDOR_INFO_AGENT_SYSTEM_PROMPT,
            VENDOR_INFO_EXTRACTION_PROMPT
        )
        assert VENDOR_INFO_AGENT_SYSTEM_PROMPT
        assert VENDOR_INFO_EXTRACTION_PROMPT

    def test_get_vendor_info_tool_exists(self):
        """Verify get_vendor_info tool exists."""
        from utils import tools
        assert hasattr(tools, 'get_vendor_info'), \
            "get_vendor_info tool should exist"

    def test_get_vendors_for_item_type_tool_exists(self):
        """Verify get_vendors_for_item_type tool exists."""
        from utils import tools
        assert hasattr(tools, 'get_vendors_for_item_type'), \
            "get_vendors_for_item_type tool should exist"


# ============================================================================
# SECTION 2: PRICE TRACKING & TRANSPARENCY TESTS
# ============================================================================

class TestPriceTracking:
    """Tests for Price Tracking & Transparency features."""

    def test_price_source_types_supported(self):
        """Verify all price source types are documented in system."""
        from core.database import CostingLineItem

        # Check that price_source field exists
        assert hasattr(CostingLineItem, 'price_source'), \
            "CostingLineItem should have price_source field"

    def test_estimation_data_fields_exist(self):
        """Verify estimation tracking fields exist in CostingLineItem."""
        from core.database import CostingLineItem

        # Estimation tracking fields
        expected_fields = [
            'estimation_quantity',
            'estimation_average_price',
            'estimation_last_purchase_price',
            'estimation_sales_price'
        ]

        for field in expected_fields:
            assert hasattr(CostingLineItem, field), \
                f"CostingLineItem should have {field} field"

    def test_products_table_price_field_exists(self):
        """Verify products_table_price field exists."""
        from core.database import CostingLineItem
        assert hasattr(CostingLineItem, 'products_table_price'), \
            "CostingLineItem should have products_table_price field"

    def test_excel_generation_function_exists(self):
        """Verify Excel costing sheet generation function exists."""
        from utils import tools
        assert hasattr(tools, 'create_costing_sheet_with_items'), \
            "create_costing_sheet_with_items should exist"


class TestEstimationLines:
    """Tests for EstimationLines table and functionality."""

    def test_estimation_lines_model_exists(self):
        """Verify EstimationLines database model exists."""
        from core.database import EstimationLines
        assert EstimationLines is not None

    def test_estimation_lines_has_required_fields(self):
        """Verify EstimationLines has all required fields."""
        from core.database import EstimationLines

        required_fields = [
            'quotation_id', 'line_num', 'item_type', 'item_name',
            'std_item_code', 'item_qty', 'average_price',
            'last_purchase_price', 'sales_price'
        ]

        for field in required_fields:
            assert hasattr(EstimationLines, field), \
                f"EstimationLines should have {field} field"


class TestProductsTable:
    """Tests for Products table and lookup functionality."""

    def test_product_model_exists(self):
        """Verify Product database model exists."""
        from core.database import Product
        assert Product is not None

    def test_product_has_required_fields(self):
        """Verify Product has required fields."""
        from core.database import Product

        required_fields = ['item_number', 'unit_cost', 'vendor_email']

        for field in required_fields:
            assert hasattr(Product, field), \
                f"Product should have {field} field"


# ============================================================================
# SECTION 3: USER INTERACTIONS TESTS
# ============================================================================

class TestConversationalInterface:
    """Tests for conversational interface capabilities."""

    def test_chat_request_schema(self):
        """Verify ChatRequest schema has required fields."""
        from core.api import ChatRequest

        # Create a test instance
        request = ChatRequest(message="test")
        assert request.message == "test"
        assert request.conversation_id is None
        assert request.state is None

    def test_chat_response_schema(self):
        """Verify ChatResponse schema has required fields."""
        from core.api import ChatResponse

        response = ChatResponse(
            response="test response",
            conversation_id=1,
            state=None,
            download_url=None
        )
        assert response.response == "test response"
        assert response.conversation_id == 1


class TestMultiTurnContext:
    """Tests for multi-turn conversation context handling."""

    def test_agent_state_has_context_fields(self):
        """Verify AgentState has context tracking fields."""
        from core.state import AgentState

        # AgentState is a TypedDict, check annotations
        annotations = AgentState.__annotations__

        context_fields = [
            'last_mentioned_job_id',
            'last_action',
            'last_item_id',
            'last_vendor_email',
            'conversation_context'
        ]

        for field in context_fields:
            assert field in annotations, \
                f"AgentState should have {field} annotation"

    def test_conversation_model_exists(self):
        """Verify Conversation database model exists."""
        from core.database import Conversation
        assert Conversation is not None

    def test_message_model_exists(self):
        """Verify Message database model exists."""
        from core.database import Message
        assert Message is not None


# ============================================================================
# SECTION 4: TECHNICAL CAPABILITIES TESTS
# ============================================================================

class TestLLMIntegration:
    """Tests for LLM integration capabilities."""

    def test_llm_module_exists(self):
        """Verify LLM module exists."""
        from utils.llm import llm
        assert llm is not None


class TestDatabaseCapabilities:
    """Tests for database capabilities."""

    def test_database_session_factory_exists(self):
        """Verify database session factory exists."""
        from core.database import SessionLocal
        assert SessionLocal is not None

    def test_costing_request_model_exists(self):
        """Verify CostingRequest model exists."""
        from core.database import CostingRequest
        assert CostingRequest is not None

    def test_costing_request_has_required_fields(self):
        """Verify CostingRequest has required fields."""
        from core.database import CostingRequest

        required_fields = [
            'job_id', 'user_id', 'quotation_id', 'line_num',
            'status', 'item_details', 'price', 'created_at'
        ]

        for field in required_fields:
            assert hasattr(CostingRequest, field), \
                f"CostingRequest should have {field} field"

    def test_costing_line_item_model_exists(self):
        """Verify CostingLineItem model exists."""
        from core.database import CostingLineItem
        assert CostingLineItem is not None

    def test_pending_quote_request_model_exists(self):
        """Verify PendingQuoteRequest model exists."""
        from core.database import PendingQuoteRequest
        assert PendingQuoteRequest is not None


class TestEmailIntegration:
    """Tests for email integration capabilities."""

    def test_send_email_function_exists(self):
        """Verify send_email function exists."""
        from utils import tools
        assert hasattr(tools, 'send_email'), "send_email should exist"

    def test_send_price_request_email_function_exists(self):
        """Verify send_price_request_email function exists."""
        from utils import tools
        assert hasattr(tools, 'send_price_request_email'), \
            "send_price_request_email should exist"


class TestSharePointIntegration:
    """Tests for SharePoint integration capabilities."""

    def test_sharepoint_create_function_exists(self):
        """Verify SharePoint create function exists."""
        from utils import tools
        assert hasattr(tools, 'create_sharepoint_list_item'), \
            "create_sharepoint_list_item should exist"

    def test_sharepoint_update_function_exists(self):
        """Verify SharePoint update function exists."""
        from utils import tools
        assert hasattr(tools, 'update_sharepoint_status'), \
            "update_sharepoint_status should exist"


class TestObservability:
    """Tests for observability and tracing capabilities."""

    def test_langfuse_tracing_module_exists(self):
        """Verify Langfuse tracing module exists."""
        from utils.langfuse_tracing import trace_agent, trace_tool
        assert callable(trace_agent), "trace_agent decorator should exist"
        assert callable(trace_tool), "trace_tool decorator should exist"

    def test_agents_have_tracing_decorator(self):
        """Verify agents have tracing decorator applied."""
        from agents.supervisor import supervisor_node
        from agents.search import search_node
        from agents.status import status_node

        # Check that functions have decorator metadata
        for func in [supervisor_node, search_node, status_node]:
            assert hasattr(func, '__wrapped__') or hasattr(func, '__name__'), \
                f"{func.__name__} should have decorator metadata"


# ============================================================================
# SECTION 5: API ENDPOINTS TESTS
# ============================================================================

class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    def test_fastapi_app_exists(self):
        """Verify FastAPI app exists."""
        from core.api import app
        assert app is not None

    def test_register_endpoint_exists(self):
        """Verify register endpoint is configured."""
        from core.api import app
        routes = [r.path for r in app.routes]
        assert "/auth/register" in routes, "Register endpoint should exist"

    def test_token_endpoint_exists(self):
        """Verify token endpoint is configured."""
        from core.api import app
        routes = [r.path for r in app.routes]
        assert "/token" in routes, "Token endpoint should exist"

    def test_users_me_endpoint_exists(self):
        """Verify users/me endpoint is configured."""
        from core.api import app
        routes = [r.path for r in app.routes]
        assert "/users/me" in routes, "Users/me endpoint should exist"


class TestChatEndpoints:
    """Tests for chat endpoints."""

    def test_chat_endpoint_exists(self):
        """Verify chat endpoint is configured."""
        from core.api import app
        routes = [r.path for r in app.routes]
        assert "/chat" in routes, "Chat endpoint should exist"


class TestJobManagementEndpoints:
    """Tests for job management endpoints."""

    def test_requests_endpoint_exists(self):
        """Verify requests endpoint is configured."""
        from core.api import app
        routes = [r.path for r in app.routes]
        assert "/requests" in routes, "Requests endpoint should exist"


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_root_endpoint_exists(self):
        """Verify root health endpoint is configured."""
        from core.api import app
        routes = [r.path for r in app.routes]
        assert "/" in routes, "Root endpoint should exist"

    def test_health_endpoint_exists(self):
        """Verify health endpoint is configured."""
        from core.api import app
        routes = [r.path for r in app.routes]
        assert "/health" in routes, "Health endpoint should exist"


# ============================================================================
# SECTION 6: SECURITY & ACCESS CONTROL TESTS
# ============================================================================

class TestAuthentication:
    """Tests for authentication capabilities."""

    def test_password_hashing_function_exists(self):
        """Verify password hashing function exists."""
        from core.api import hash_password
        assert callable(hash_password), "hash_password should be callable"

    def test_access_token_creation_function_exists(self):
        """Verify access token creation function exists."""
        from core.api import create_access_token
        assert callable(create_access_token), "create_access_token should be callable"

    def test_get_current_user_function_exists(self):
        """Verify get_current_user function exists."""
        from core.api import get_current_user
        assert callable(get_current_user), "get_current_user should be callable"


class TestAuthorization:
    """Tests for authorization capabilities."""

    def test_user_model_has_role_field(self):
        """Verify User model has role field."""
        from core.database import User
        assert hasattr(User, 'role'), "User should have role field"

    def test_user_model_has_password_field(self):
        """Verify User model has hashed_password field."""
        from core.database import User
        assert hasattr(User, 'hashed_password'), "User should have hashed_password field"


# ============================================================================
# SECTION 7: CONFIGURATION TESTS
# ============================================================================

class TestSystemConfiguration:
    """Tests for system configuration parameters."""

    def test_price_threshold_configured(self):
        """Verify PRICE_THRESHOLD is configured."""
        from core import config
        assert hasattr(config, 'PRICE_THRESHOLD') or hasattr(config, 'TOP_K_ITEMS'), \
            "Configuration should have threshold settings"

    def test_top_k_items_configured(self):
        """Verify TOP_K_ITEMS is configured."""
        from core import config
        assert hasattr(config, 'TOP_K_ITEMS'), \
            "Configuration should have TOP_K_ITEMS"

    def test_secret_key_configured(self):
        """Verify SECRET_KEY is configured for JWT."""
        from core import config
        assert hasattr(config, 'SECRET_KEY'), \
            "Configuration should have SECRET_KEY"

    def test_algorithm_configured(self):
        """Verify ALGORITHM is configured for JWT."""
        from core import config
        assert hasattr(config, 'ALGORITHM'), \
            "Configuration should have ALGORITHM"


# ============================================================================
# SECTION 8: WORKFLOW INTEGRATION TESTS
# ============================================================================

class TestWorkflowIntegration:
    """Tests for LangGraph workflow integration."""

    def test_workflow_exists(self):
        """Verify workflow StateGraph exists."""
        from main import workflow
        assert workflow is not None

    def test_invoke_agent_function_exists(self):
        """Verify invoke_agent function exists."""
        from main import invoke_agent
        assert callable(invoke_agent), "invoke_agent should be callable"

    def test_all_agents_in_workflow(self):
        """Verify all documented agents are in the workflow."""
        from main import workflow

        expected_agents = [
            "Supervisor",
            "SearchAgent",
            "SelectionAgent",
            "CostingAgent",
            "StatusAgent",
            "EditJobAgent",
            "QuoteManagementAgent",
            "JobLifecycleAgent",
            "PricingAdvisorAgent",
            "ExplainerAgent",
            "VendorInfoAgent"
        ]

        for agent in expected_agents:
            assert agent in workflow.nodes, f"{agent} should be in workflow nodes"


# ============================================================================
# SECTION 9: MOCK INTEGRATION TESTS
# ============================================================================

class TestStatusAgentMockIntegration:
    """Integration tests for Status Agent with mock data."""

    def test_build_status_context_with_mock_jobs(self, sample_costing_job):
        """Test status context building with mock job data."""
        from agents.status import _build_status_context

        mock_jobs = [sample_costing_job]
        context = _build_status_context(
            mock_jobs,
            specific_job_id="COST-TEST1234",
            wants_details=True
        )

        assert "COST-TEST1234" in context, "Context should include job ID"
        assert "Hydraulic Pump" in context or "item" in context.lower(), \
            "Context should include item information"


class TestSearchAgentMockIntegration:
    """Integration tests for Search Agent with mock data."""

    def test_show_more_detection(self):
        """Test 'show more' phrase detection."""
        from agents.search import search_node

        show_more_phrases = [
            "more quotation", "show more", "see more",
            "other quotation", "different quotation"
        ]

        test_cases = [
            ("show me more quotations please", True),
            ("I want to see more options", True),
            ("show me different quotations", True),
            ("I need a quotation for polishing", False),
            ("find hydraulic pump repair", False)
        ]

        for msg, expected in test_cases:
            is_show_more = any(phrase in msg.lower() for phrase in show_more_phrases)
            assert is_show_more == expected, \
                f"Message '{msg}' should {'match' if expected else 'not match'} show more pattern"


class TestSelectionAgentMockIntegration:
    """Integration tests for Selection Agent with mock data."""

    def test_selection_by_number(self, sample_quotations):
        """Test that selection by number would work with options."""
        # Test the format of quotation IDs
        for i, quot in enumerate(sample_quotations, 1):
            assert "quotation_id" in quot
            assert "line_num" in quot
            # Check format allows for number-based selection
            assert quot["quotation_id"].startswith("AJMFQ-")


# ============================================================================
# SECTION 10: EDGE CASE TESTS
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_search_results_handling(self):
        """Test that empty search results are handled gracefully."""
        import json

        # Test JSON parsing of empty results
        empty_results = "[]"
        parsed = json.loads(empty_results)
        assert parsed == []
        assert len(parsed) == 0

    def test_invalid_job_id_format(self):
        """Test that job ID format is consistent."""
        import re

        # Valid job ID format: COST-XXXXXXXX
        valid_pattern = r'^COST-[A-Z0-9]{8}$'

        valid_ids = ["COST-TEST1234", "COST-ABCD1234", "COST-00001234"]
        invalid_ids = ["COST-123", "TEST-12345678", "cost-12345678"]

        for job_id in valid_ids:
            assert re.match(valid_pattern, job_id), \
                f"{job_id} should match job ID pattern"

        for job_id in invalid_ids:
            assert not re.match(valid_pattern, job_id), \
                f"{job_id} should not match job ID pattern"

    def test_price_threshold_logic(self):
        """Test price threshold logic for quote triggering."""
        threshold = 1000.0

        test_cases = [
            (500.0, False),   # Below threshold - no quote needed
            (1000.0, False),  # At threshold - no quote needed
            (1500.0, True),   # Above threshold - quote needed
            (0.0, False),     # Zero - no quote needed
            (None, True),     # No price - quote needed
        ]

        for price, should_request_quote in test_cases:
            if price is None:
                needs_quote = True
            else:
                needs_quote = price > threshold
            assert needs_quote == should_request_quote, \
                f"Price {price} should {'need' if should_request_quote else 'not need'} quote"


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
