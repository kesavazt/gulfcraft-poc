"""
Costing Agent Node

Handles the complete costing workflow:
1. Get estimation lines for selected quotation
2. Look up prices for each item
3. Create costing sheet
4. Send emails for items needing quotes
5. Upload to SharePoint
"""

import logging
from langchain_core.messages import AIMessage
from core.state import AgentState
from utils import tools
from core import config

logger = logging.getLogger(__name__)


def _get_estimation_items(quotation_id: str, line_num: int):
    """Retrieve estimation lines for the quotation."""
    return tools.get_estimation_lines(quotation_id, line_num)


def _resolve_prices(estimation_items: list, threshold: float):
    """
    Resolve prices for all items.
    
    Returns:
        tuple: (costing_items, pending_quote_items)
    """
    costing_items = []
    pending_quote_items = []

    for item in estimation_items:
        item_name = item.get("item_name", "")
        item_type = item.get("item_type", "")
        is_labour = item_type.lower() == "hour"

        costing_item = {
            "item_name": item_name,
            "item_code": item.get("item_code"),
            "item_type": item_type,
            "quantity": item.get("quantity", 1),
            "is_labour": is_labour
        }

        if is_labour:
            costing_item["unit_price"] = item.get("sales_price")
            costing_item["price_status"] = "resolved"
            costing_item["vendor_email"] = None
        else:
            item_code = item.get("item_code", "")
            product_info = tools.get_product_price(item_code)
            costing_item["unit_price"] = product_info.get("unit_cost")
            costing_item["vendor_email"] = product_info.get("vendor_email", "vinod.ihava@gulfcraftinc.com")
            
            if product_info.get("unit_cost") is not None and product_info.get("unit_cost") <= threshold:
                costing_item["price_status"] = "resolved"
            else:
                costing_item["price_status"] = "pending_quote"
                pending_quote_items.append(costing_item)

        costing_items.append(costing_item)

    return costing_items, pending_quote_items


def _send_quote_emails(job_id: str, pending_items: list):
    """Send price request emails for pending items."""
    for item in pending_items:
        try:
            tools.send_price_request_email(
                job_id=job_id,
                item_name=item["item_name"],
                item_code=item.get("item_code", "N/A"),
                quantity=item.get("quantity", 1),
                vendor_email=item["vendor_email"]
            )
        except Exception as e:
            logger.error(f"Failed to send email for {item['item_name']}: {e}")


def _update_sharepoint(job_id: str, description: str, costing_items: list, has_pending: bool):
    """Create SharePoint list item for the costing job."""
    try:
        total_selling_price = 0
        profit_margin = config.PROFIT_MARGIN
        
        for item in costing_items:
            unit_cost = item.get("unit_price")
            if unit_cost is not None:
                quantity = item.get("quantity", 1)
                total_selling_price += (unit_cost * quantity * profit_margin)
        
        sp_status = "Awaiting Quote" if has_pending else "Ready"
        sp_title = description[:250] if description else f"Costing for {job_id}"
        
        tools.create_sharepoint_list_item(
            job_id=job_id,
            title=sp_title,
            price=round(total_selling_price, 2),
            status=sp_status
        )
    except Exception as e:
        logger.error(f"SharePoint update failed for {job_id}: {e}")


def _build_response(job_id: str, quotation_id: str, line_num: int, 
                    costing_items: list, pending_items: list, 
                    file_path: str, sharepoint_url: str, threshold: float):
    """Build the response message for the user."""
    labour_items = [i for i in costing_items if i.get("is_labour")]
    non_labour_resolved = [i for i in costing_items if not i.get("is_labour") and i["price_status"] == "resolved"]

    response_parts = [
        f"**Costing Job Created: {job_id}**\n",
        f"- Quotation: {quotation_id}",
        f"- Line Number: {line_num}",
        f"- Total Items: {len(costing_items)}",
        f"- Labour Items: {len(labour_items)} (price from estimation)",
        f"- Non-Labour Items with resolved prices: {len(non_labour_resolved)}",
        f"- Items pending quotes: {len(pending_items)}",
    ]

    if pending_items:
        response_parts.append(f"\n**Items Requiring Price Quotes (>{threshold} AED or not found in Products):**")
        for item in pending_items:
            response_parts.append(f"  - {item['item_name']} (email sent to {item['vendor_email']})")

    # Removed links from response as per user request to keep chat clean.
    # The frontend still receives file_path and sharepoint_url in the state.

    if pending_items:
        response_parts.append("\nI've sent price quotation requests to the vendors. The system will monitor for incoming responses and update the costing sheet automatically.")

    return "\n".join(response_parts)


def costing_node(state: AgentState):
    """
    Main costing workflow node.
    
    Orchestrates the complete costing process from quotation selection to SharePoint upload.
    """
    selected = state.get("selected_quotation")
    user_id = state.get("user_id", 1)
    threshold = state.get("threshold", config.PRICE_THRESHOLD)

    if not selected:
        return {
            "messages": [AIMessage(content="No quotation selected. Please select a quotation first.")]
        }

    quotation_id = selected.get("quotation_id")
    line_num = selected.get("line_num")
    description = selected.get("description", "")

    # Step 1: Get estimation lines
    estimation_items = _get_estimation_items(quotation_id, line_num)
    if not estimation_items:
        return {
            "messages": [AIMessage(content=f"No estimation lines found for quotation {quotation_id}, line {line_num}. This quotation may not have associated items.")]
        }

    # Step 2: Create costing request
    job_id = tools.create_costing_request(user_id, quotation_id, line_num, description)
    if not job_id:
        return {
            "messages": [AIMessage(content="Failed to create costing request. Please try again.")]
        }

    # Step 3: Resolve prices
    costing_items, pending_quote_items = _resolve_prices(estimation_items, threshold)

    # Step 4: Save costing line items
    tools.save_costing_line_items(job_id, costing_items)

    # Step 5: Generate costing sheet
    file_path = tools.create_costing_sheet_with_items(
        job_id, costing_items, quotation_id, description
    )

    # Step 6: Send emails for pending items
    if pending_quote_items:
        _send_quote_emails(job_id, pending_quote_items)

    # Step 7: Set download URL
    sharepoint_url = f"/costing-sheets/{file_path}" if file_path else None

    # Step 8: Update SharePoint
    _update_sharepoint(job_id, description, costing_items, bool(pending_quote_items))

    # Build response
    response = _build_response(
        job_id, quotation_id, line_num, costing_items, pending_quote_items,
        file_path, sharepoint_url, threshold
    )

    return {
        "messages": [AIMessage(content=response)],
        "job_id": job_id,
        "estimation_items": estimation_items,
        "costing_items": costing_items,
        "pending_quote_items": pending_quote_items,
        "generated_file": file_path,
        "sharepoint_url": sharepoint_url,
        "emails_sent": len(pending_quote_items) > 0,
        "awaiting_quotes": len(pending_quote_items) > 0
    }
