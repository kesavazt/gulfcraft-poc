from typing import Dict, Any
from state import AgentState
import tools
import config
import templates
from langchain_core.messages import AIMessage


def search_node(state: AgentState) -> Dict[str, Any]:
    """Node to search for similar items based on user inquiry."""
    last_message = state["messages"][-1].content
    items = tools.search_similar_items(last_message)
    
    # Format the items for the user
    response = "I found these similar items:\n"
    for i, item in enumerate(items):
        response += f"{i+1}. {item['name']} (ID: {item['d365_id']}) - ${item['price']}\n"
    response += "\nPlease confirm which item you are referring to, or provide more details if it's a new item."
    
    return {
        "messages": [AIMessage(content=response)],
        "similar_items": items
    }

def create_job_node(state: AgentState) -> Dict[str, Any]:
    """Node to create a costing job."""
    # Assume the user selected an item or provided details
    # For simplicity, we'll take the last message as details if no item selected
    details = state.get("item_details") or state["messages"][-1].content
    user_id = state.get("user_id", 1) # Default to 1 if not set
    
    job_id = tools.create_sharepoint_job(details, user_id)
    
    return {
        "messages": [AIMessage(content=f"Created Costing Job: {job_id}")],
        "job_id": job_id,
        "item_details": details
    }

def check_price_logic(state: AgentState) -> str:
    """Conditional edge to determine next step based on price/threshold."""
    # If we have a selected item, check its price
    selected_item = state.get("selected_item")
    price = state.get("price")
    
    if selected_item:
        price = selected_item["price"]
    
    # If price is unknown (new item), we might need to estimate or quote
    # For this logic:
    # If Price < Threshold -> Auto Approve (Fetch D365)
    # If Price > Threshold -> Request Quotation
    
    threshold = state.get("threshold", config.PRICE_THRESHOLD)
    
    if price and price < threshold:
        return "fetch_price"
    else:
        return "request_quotation"

def fetch_price_node(state: AgentState) -> Dict[str, Any]:
    """Node to fetch price from D365 and update job."""
    job_id = state["job_id"]
    selected_item = state.get("selected_item")
    
    if selected_item:
        price = tools.get_d365_price(selected_item["d365_id"])
    else:
        # Fallback for new item, maybe use average of similar?
        price = 500.0 # Mock
        
    tools.update_sharepoint_job(job_id, {"price": price, "status": "Completed"})
    
    return {
        "messages": [AIMessage(content=f"Price fetched from D365: ${price}. Job updated.")],
        "price": price
    }

def request_quotation_node(state: AgentState) -> Dict[str, Any]:
    """Node to send quotation email."""
    job_id = state["job_id"]
    details = state["item_details"]
    
    # Send email
    body = templates.QUOTATION_TEMPLATE.format(
        job_id=job_id,
        item_name="New Item", # Placeholder
        item_description=details,
        quantity=1
    )
    tools.send_email("supplier@example.com", f"Quotation Request - JobID: {job_id}", body)
    
    tools.update_sharepoint_job(job_id, {"status": "Quotation Requested"})
    
    return {
        "messages": [AIMessage(content=f"Price is above threshold. Sent quotation request to supplier. Job ID: {job_id}")],
        "quotation_requested": True
    }

def process_quotation_node(state: AgentState) -> Dict[str, Any]:
    """Node to process received quotation (Mock)."""
    job_id = state["job_id"]
    
    # Simulate reading email
    price = tools.read_email_quotation(job_id)
    
    if price:
        tools.update_sharepoint_job(job_id, {"price": price, "status": "Quotation Received"})
        return {
            "messages": [AIMessage(content=f"Received quotation from supplier: ${price}. Job updated.")],
            "price": price
        }
    else:
        return {
            "messages": [AIMessage(content="Still waiting for quotation...")]
        }

def notify_sales_node(state: AgentState) -> Dict[str, Any]:
    """Node to notify sales team."""
    job_id = state["job_id"]
    price = state["price"]
    
    tools.send_email("sales@gulfcraft.com", f"Costing Completed - {job_id}", f"The costing for job {job_id} is complete. Final Price: ${price}")
    
    return {
        "messages": [AIMessage(content="Notified Sales team. Process Complete.")]
    }
