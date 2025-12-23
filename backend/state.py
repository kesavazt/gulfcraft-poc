from typing import TypedDict, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    messages: List[BaseMessage]
    next: str
    user_id: int
    similar_items: List[Dict[str, Any]]
    selected_item: Optional[Dict[str, Any]]
    job_id: Optional[str]
    price: Optional[float]
    threshold: float
    item_details: Optional[str]
    quotation_requested: bool
    generated_file: Optional[str]
    product_category: Optional[str]
    vendor_emails: Optional[List[str]]
    waiting_for_approval: bool
