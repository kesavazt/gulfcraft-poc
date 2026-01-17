from typing import TypedDict, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # Core conversation state
    messages: List[BaseMessage]
    next: str
    user_id: int

    # Search workflow state
    similar_quotations: List[Dict[str, Any]]  # Results from search_similar_quotations
    selected_quotation: Optional[Dict[str, Any]]  # User's selected quotation
    awaiting_selection: bool  # True when waiting for user to select a quotation

    # Search parameters (for "show more" functionality)
    last_search_description: Optional[str]  # Last searched job description
    last_search_boat_model: Optional[str]  # Last searched boat model
    current_top_k: int  # Current top_k value for search

    # Costing workflow state
    job_id: Optional[str]  # Generated costing job ID (e.g., COST-XXXXXXXX)
    estimation_items: List[Dict[str, Any]]  # Items from EstimationLines
    costing_items: List[Dict[str, Any]]  # Items with prices (resolved or pending)
    pending_quote_items: List[Dict[str, Any]]  # Items requiring price quotes (> threshold)

    # Pricing state
    threshold: float  # Price threshold (default 1000)
    price: Optional[float]  # Total calculated price

    # File/SharePoint state
    generated_file: Optional[str]  # Path to generated costing sheet
    sharepoint_url: Optional[str]  # URL of uploaded costing sheet

    # Email state
    emails_sent: bool  # True if price request emails have been sent
    awaiting_quotes: bool  # True if waiting for vendor quote responses

    # Legacy fields (for backwards compatibility)
    item_details: Optional[str]
    quotation_requested: bool
    product_category: Optional[str]
    vendor_emails: Optional[List[str]]
    waiting_for_approval: bool
