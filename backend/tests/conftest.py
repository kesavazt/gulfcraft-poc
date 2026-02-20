"""
Pytest Configuration and Shared Fixtures

This module provides shared fixtures for testing the Gulf Craft AI Costing Assistant.
"""

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

# Add backend directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ============================================================================
# DATABASE FIXTURES
# ============================================================================

@pytest.fixture
def mock_db_session():
    """
    Mock database session for testing.

    Provides a MagicMock that simulates SQLAlchemy session behavior.
    """
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.close = MagicMock()
    return session


@pytest.fixture
def mock_db_session_with_data(mock_db_session, sample_costing_job):
    """Mock database session pre-populated with sample data."""
    from core.database import CostingRequest, CostingLineItem

    # Create mock costing request
    mock_request = Mock(spec=CostingRequest)
    mock_request.job_id = sample_costing_job["job_id"]
    mock_request.status = sample_costing_job["status"]
    mock_request.item_details = sample_costing_job["item_details"]
    mock_request.price = sample_costing_job["price"]
    mock_request.created_at = sample_costing_job["created_at"]

    # Create mock line items
    mock_items = []
    for item in sample_costing_job["line_items"]:
        mock_item = Mock(spec=CostingLineItem)
        for key, value in item.items():
            setattr(mock_item, key, value)
        mock_items.append(mock_item)

    mock_request.line_items = mock_items

    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_request
    return mock_db_session


# ============================================================================
# USER FIXTURES
# ============================================================================

@pytest.fixture
def mock_user():
    """
    Mock regular user object for testing.

    Returns a Mock with standard user attributes.
    """
    user = Mock()
    user.id = 1
    user.username = "testuser"
    user.role = "user"
    user.hashed_password = "$2b$12$mockhashedpassword"
    return user


@pytest.fixture
def mock_admin_user():
    """
    Mock admin user object for testing.

    Returns a Mock with admin role attributes.
    """
    user = Mock()
    user.id = 1
    user.username = "admin"
    user.role = "admin"
    user.hashed_password = "$2b$12$mockhashedpassword"
    return user


# ============================================================================
# AGENT STATE FIXTURES
# ============================================================================

@pytest.fixture
def sample_agent_state():
    """
    Sample agent state for testing agent nodes.

    Returns a dictionary matching AgentState TypedDict structure.
    """
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
        "job_description_override": None,
        "estimation_items": [],
        "costing_items": [],
        "pending_quote_items": [],
        "threshold": 1000.0,
        "price": None,
        "generated_file": None,
        "sharepoint_url": None,
        "emails_sent": False,
        "awaiting_quotes": False,
        "last_mentioned_job_id": None,
        "last_action": None,
        "last_item_id": None,
        "last_vendor_email": None,
        "conversation_context": None,
    }


@pytest.fixture
def search_agent_state(sample_agent_state):
    """Agent state for testing search agent."""
    from langchain_core.messages import HumanMessage

    state = sample_agent_state.copy()
    state["messages"] = [
        HumanMessage(content="I need a quotation for polishing work. Boat: MAJESTY62")
    ]
    return state


@pytest.fixture
def selection_agent_state(sample_agent_state, sample_quotations):
    """Agent state for testing selection agent."""
    from langchain_core.messages import HumanMessage

    state = sample_agent_state.copy()
    state["messages"] = [HumanMessage(content="I'll take option 1")]
    state["similar_quotations"] = sample_quotations
    state["awaiting_selection"] = True
    return state


@pytest.fixture
def status_agent_state(sample_agent_state):
    """Agent state for testing status agent."""
    from langchain_core.messages import HumanMessage

    state = sample_agent_state.copy()
    state["messages"] = [HumanMessage(content="Show my job status")]
    return state


@pytest.fixture
def edit_job_agent_state(sample_agent_state):
    """Agent state for testing edit job agent."""
    from langchain_core.messages import HumanMessage

    state = sample_agent_state.copy()
    state["messages"] = [
        HumanMessage(content="Add 50 meters of cable to COST-TEST1234")
    ]
    state["last_mentioned_job_id"] = "COST-TEST1234"
    return state


# ============================================================================
# DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_quotations():
    """
    Sample quotation data for testing.

    Returns a list of quotation dictionaries matching search results format.
    """
    return [
        {
            "quotation_id": "AJMFQ-000001",
            "line_num": 1,
            "description": "Engine polishing and cleaning",
            "boat_model": "MAJESTY62",
            "score": 0.95,
            "combined_score": 0.92
        },
        {
            "quotation_id": "AJMFQ-000002",
            "line_num": 1,
            "description": "Hydraulic pump repair and replacement",
            "boat_model": "MAJESTY62",
            "score": 0.85,
            "combined_score": 0.82
        },
        {
            "quotation_id": "AJMFQ-000003",
            "line_num": 2,
            "description": "Hull cleaning and antifouling",
            "boat_model": "MAJESTY62",
            "score": 0.75,
            "combined_score": 0.72
        }
    ]


@pytest.fixture
def sample_costing_job():
    """
    Sample costing job data for testing.

    Returns a dictionary representing a complete costing job.
    """
    return {
        "job_id": "COST-TEST1234",
        "status": "Ready",
        "item_details": "Test job description - Engine maintenance",
        "created_at": datetime(2024, 1, 15, 10, 30, 0),
        "updated_at": datetime(2024, 1, 15, 11, 0, 0),
        "price": 5000.0,
        "quotation_id": "AJMFQ-000001",
        "line_num": 1,
        "user_id": 1,
        "line_items": [
            {
                "id": 1,
                "item_name": "Hydraulic Pump",
                "item_code": "HYD-001",
                "quantity": 2,
                "unit_price": 1500.0,
                "price_status": "resolved",
                "price_source": "products",
                "vendor_email": "vendor1@example.com",
                "item_type": "Item",
                "estimation_quantity": 2,
                "estimation_average_price": 1400.0,
                "products_table_price": 1500.0
            },
            {
                "id": 2,
                "item_name": "Cable 50m",
                "item_code": "CBL-001",
                "quantity": 50,
                "unit_price": None,
                "price_status": "pending",
                "price_source": "pending",
                "vendor_email": "vendor2@example.com",
                "item_type": "Item",
                "estimation_quantity": 50,
                "estimation_average_price": 10.0,
                "products_table_price": None
            },
            {
                "id": 3,
                "item_name": "Labour - Installation",
                "item_code": None,
                "quantity": 8,
                "unit_price": 100.0,
                "price_status": "resolved",
                "price_source": "labour",
                "vendor_email": None,
                "item_type": "Labour",
                "estimation_quantity": 8,
                "estimation_average_price": 100.0,
                "products_table_price": None
            }
        ],
        "quote_requests": [
            {
                "id": 1,
                "item_name": "Cable 50m",
                "vendor_email": "vendor2@example.com",
                "status": "pending",
                "sent_at": datetime(2024, 1, 15, 11, 0, 0)
            }
        ]
    }


@pytest.fixture
def sample_estimation_lines():
    """Sample estimation lines data for testing."""
    return [
        {
            "quotation_id": "AJMFQ-000001",
            "line_num": 1,
            "item_type": "Item",
            "item_name": "Hydraulic Pump",
            "std_item_code": "HYD-001",
            "item_qty": 2,
            "average_price": 1400.0,
            "last_purchase_price": 1450.0,
            "sales_price": 2100.0
        },
        {
            "quotation_id": "AJMFQ-000001",
            "line_num": 1,
            "item_type": "Item",
            "item_name": "Cable 50m",
            "std_item_code": "CBL-001",
            "item_qty": 50,
            "average_price": 10.0,
            "last_purchase_price": 12.0,
            "sales_price": 15.0
        }
    ]


@pytest.fixture
def sample_vendor_data():
    """
    Sample vendor data for testing.

    Returns vendor performance metrics dictionary.
    """
    return {
        "email": "vendor@example.com",
        "total_requests": 50,
        "responded": 42,
        "response_rate": 84.0,
        "avg_response_time_days": 2.5,
        "items_supplied": ["Hydraulic Pump", "Cable", "Anchor Winch", "Filter"],
        "pending_requests": 3,
        "performance_rating": "⭐⭐⭐"
    }


@pytest.fixture
def sample_price_history():
    """Sample price history data for testing."""
    return [
        {"date": "2024-01-01", "price": 1400.0, "vendor": "vendor1@example.com"},
        {"date": "2024-01-15", "price": 1450.0, "vendor": "vendor1@example.com"},
        {"date": "2024-02-01", "price": 1500.0, "vendor": "vendor2@example.com"},
        {"date": "2024-02-15", "price": 1480.0, "vendor": "vendor1@example.com"},
    ]


@pytest.fixture
def sample_vacuum_cleaner_products():
    """
    Sample vacuum cleaner product data for testing price comparison.

    Returns a list of vacuum cleaner products with varying specifications.
    """
    return [
        {
            "item_code": "VAC-001",
            "item_name": "Industrial Vacuum Cleaner 1200W",
            "description": "Heavy-duty industrial vacuum cleaner with 1200W motor",
            "unit_cost": 1250.0,
            "category": "Cleaning Equipment"
        },
        {
            "item_code": "VAC-002",
            "item_name": "Wet/Dry Vacuum Cleaner 1500W",
            "description": "Wet and dry vacuum cleaner with 1500W motor and 30L tank",
            "unit_cost": 1450.0,
            "category": "Cleaning Equipment"
        },
        {
            "item_code": "VAC-003",
            "item_name": "Commercial Vacuum Cleaner 2000W",
            "description": "Commercial grade vacuum cleaner 2000W with HEPA filter",
            "unit_cost": 1800.0,
            "category": "Cleaning Equipment"
        },
        {
            "item_code": "VAC-004",
            "item_name": "Compact Vacuum Cleaner 800W",
            "description": "Compact vacuum cleaner for small spaces, 800W motor",
            "unit_cost": 850.0,
            "category": "Cleaning Equipment"
        }
    ]


@pytest.fixture
def sample_vacuum_price_history():
    """
    Sample price history for vacuum cleaner (VAC-002) for testing comparisons.

    Returns historical purchase data showing price trends over time.
    """
    return [
        {
            "item_code": "VAC-002",
            "item_name": "Wet/Dry Vacuum Cleaner 1500W",
            "unit_price": 1400.0,
            "quantity": 2,
            "job_id": "COST-001",
            "vendor_email": "cleaning@supplier1.com",
            "date": "2024-01-15"
        },
        {
            "item_code": "VAC-002",
            "item_name": "Wet/Dry Vacuum Cleaner 1500W",
            "unit_price": 1420.0,
            "quantity": 1,
            "job_id": "COST-045",
            "vendor_email": "cleaning@supplier2.com",
            "date": "2024-02-20"
        },
        {
            "item_code": "VAC-002",
            "item_name": "Wet/Dry Vacuum Cleaner 1500W",
            "unit_price": 1380.0,
            "quantity": 3,
            "job_id": "COST-089",
            "vendor_email": "cleaning@supplier1.com",
            "date": "2024-03-10"
        },
        {
            "item_code": "VAC-002",
            "item_name": "Wet/Dry Vacuum Cleaner 1500W",
            "unit_price": 1450.0,
            "quantity": 1,
            "job_id": "COST-112",
            "vendor_email": "cleaning@supplier3.com",
            "date": "2024-04-05"
        }
    ]


@pytest.fixture
def pricing_advisor_agent_state(sample_agent_state):
    """Agent state for testing pricing advisor agent."""
    from langchain_core.messages import HumanMessage

    state = sample_agent_state.copy()
    state["messages"] = [
        HumanMessage(content="Is 1500 AED a good price for a vacuum cleaner?")
    ]
    return state


# ============================================================================
# API TESTING FIXTURES
# ============================================================================

@pytest.fixture
def test_client():
    """
    FastAPI test client for API endpoint testing.

    Returns a TestClient instance for the FastAPI app.
    """
    from fastapi.testclient import TestClient
    from core.api import app

    return TestClient(app)


@pytest.fixture
def auth_headers(mock_user):
    """
    Authentication headers for API testing.

    Returns headers dict with Bearer token.
    """
    from core.api import create_access_token

    token = create_access_token(data={"sub": mock_user.username})
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# MOCK EXTERNAL SERVICES
# ============================================================================

@pytest.fixture
def mock_llm():
    """Mock LLM for testing without API calls."""
    mock = MagicMock()
    mock.invoke.return_value = MagicMock(
        content="Mock LLM response",
        tool_calls=[]
    )
    return mock


@pytest.fixture
def mock_email_service():
    """Mock email service for testing."""
    with patch('utils.tools.send_email') as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def mock_sharepoint_service():
    """Mock SharePoint service for testing."""
    with patch('utils.tools.create_sharepoint_list_item') as mock_create, \
         patch('utils.tools.update_sharepoint_status') as mock_update:
        mock_create.return_value = True
        mock_update.return_value = True
        yield {"create": mock_create, "update": mock_update}


@pytest.fixture
def mock_search_service(sample_quotations):
    """Mock search service for testing."""
    with patch('services.search.hybrid_search') as mock:
        mock.return_value = sample_quotations
        yield mock


# ============================================================================
# CONFIGURATION FIXTURES
# ============================================================================

@pytest.fixture
def test_config():
    """Test configuration with safe defaults."""
    return {
        "TOP_K_ITEMS": 5,
        "PRICE_THRESHOLD": 1000.0,
        "PROFIT_MARGIN": 1.5,
        "SECRET_KEY": "test-secret-key",
        "ALGORITHM": "HS256",
    }


# ============================================================================
# CLEANUP FIXTURES
# ============================================================================

@pytest.fixture(autouse=True)
def reset_state():
    """Reset any global state between tests."""
    yield
    # Cleanup happens after test


# ============================================================================
# MARKERS
# ============================================================================

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )
    config.addinivalue_line(
        "markers", "api: marks tests as API tests"
    )
    config.addinivalue_line(
        "markers", "agent: marks tests as agent tests"
    )
