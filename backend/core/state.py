"""
Agent State Definition

Defines the TypedDict for LangGraph workflow state.
"""

from typing import TypedDict, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage


class AgentState(TypedDict, total=False):
    """
    State object for Gulf Craft Costing Agent workflow.
    
    All fields are optional (total=False) except for core conversation fields.
    """
    
    # =========================================================================
    # Core Conversation State
    # =========================================================================
    messages: List[BaseMessage]  # Conversation message history
    next: str  # Next agent to route to
    user_id: int  # Current user ID
    
    # =========================================================================
    # Search Workflow State
    # =========================================================================
    similar_quotations: List[Dict[str, Any]]  # Results from search_similar_quotations
    selected_quotation: Optional[Dict[str, Any]]  # User's selected quotation
    awaiting_selection: bool  # True when waiting for user to select a quotation
    
    # Search parameters (for "show more" functionality)
    last_search_description: Optional[str]  # Last searched job description
    last_search_boat_model: Optional[str]  # Last searched boat model
    current_top_k: int  # Current top_k value for search
    
    # =========================================================================
    # Costing Workflow State
    # =========================================================================
    job_id: Optional[str]  # Generated costing job ID (e.g., COST-XXXXXXXX)
    job_description_override: Optional[str]  # Optional user-provided description override
    estimation_items: List[Dict[str, Any]]  # Items from EstimationLines
    costing_items: List[Dict[str, Any]]  # Items with prices (resolved or pending)
    pending_quote_items: List[Dict[str, Any]]  # Items requiring price quotes (> threshold)
    
    # =========================================================================
    # Pricing State
    # =========================================================================
    threshold: float  # Price threshold for triggering quote requests (default 1000)
    price: Optional[float]  # Total calculated price
    
    # =========================================================================
    # Output State
    # =========================================================================
    generated_file: Optional[str]  # Path to generated costing sheet
    sharepoint_url: Optional[str]  # URL of uploaded costing sheet
    
    # =========================================================================
    # Email State
    # =========================================================================
    emails_sent: bool  # True if price request emails have been sent
    awaiting_quotes: bool  # True if waiting for vendor quote responses
