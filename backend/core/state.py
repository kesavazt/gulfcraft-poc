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

    # =========================================================================
    # Context Tracking (for multi-turn conversations)
    # =========================================================================
    last_mentioned_job_id: Optional[str]  # Last job ID mentioned in conversation
    last_action: Optional[str]  # Last action performed (e.g., "created_job", "edited_item")
    last_item_id: Optional[int]  # Last line item ID modified
    last_vendor_email: Optional[str]  # Last vendor mentioned
    conversation_context: Optional[Dict[str, Any]]  # Additional context for agent decisions
    pending_disambiguation: Optional[Dict[str, Any]]  # Holds disambiguation state when multiple items match

    # =========================================================================
    # State Management & Versioning
    # =========================================================================
    state_version: str  # State schema version (e.g., "2.0") for migration support
    disambiguation_lock: bool  # Prevents race conditions during disambiguation flows
    disambiguation_expires_at: Optional[str]  # ISO timestamp when disambiguation times out (5 min)
    extraction_failures: int  # Counter for consecutive extraction failures (triggers repair)

    # =========================================================================
    # Agent Transition Metadata
    # =========================================================================
    last_agent: Optional[str]  # Previously active agent (for handoff context)
    routing_reason: Optional[str]  # Why agent was routed (user_requested, auto_delegation, pending_disambiguation)
    routing_context: Optional[Dict[str, Any]]  # Additional context passed to receiving agent
    transition_history: List[Dict[str, Any]]  # Log of agent transitions in this conversation
    handoff_context: Optional[Dict[str, Any]]  # Context prepared during agent handoff

    # =========================================================================
    # NLU Enhancement
    # =========================================================================
    intent_confidence: Optional[float]  # Confidence score (0-1) for routing decision
    clarification_needed: bool  # Flag indicating clarification is required
