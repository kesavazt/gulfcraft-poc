"""
Selection Agent Node

Handles user's quotation selection and confirmation workflow.
"""

import re
from langchain_core.messages import AIMessage
from core.state import AgentState
from utils.llm import llm
from utils.prompts import SELECTION_EXTRACTION_PROMPT, QUOTATION_CONFIRMATION_TEMPLATE
from utils import tools


def _extract_description_override(user_message: str) -> str:
    """Extract an explicit job description override from the user's confirmation message."""
    match = re.search(
        r"(?:new\s+job\s+description|job\s+description|new\s+description|description|desc)\s*[:\-]\s*(.+)$",
        user_message,
        re.IGNORECASE
    )
    if not match:
        return ""
    return match.group(1).strip().strip('"').strip("'")


def _check_confirmation(user_message: str, state: AgentState):
    """Check if user is responding to a confirmation prompt."""
    if not state.get("selected_quotation"):
        return None
    
    msg = user_message.lower()
    if any(w in msg for w in ["yes", "y", "confirm", "proceed", "go ahead"]):
        description_override = _extract_description_override(user_message)
        response = "Proceeding to create costing job..."
        if description_override:
            response = f"Proceeding to create costing job with updated description: {description_override}"
        return {
            "messages": [AIMessage(content=response)],
            "job_description_override": description_override or None,
            "next": "CostingAgent"
        }
    elif any(w in msg for w in ["no", "n", "cancel", "stop"]):
        return {
            "messages": [AIMessage(content="Cancelled. Would you like to see other options or start a new search?")],
            "selected_quotation": None,
            "job_description_override": None,
            "next": "__end__"
        }
    return None


def _try_number_selection(user_message: str, similar_quotations: list):
    """Try to match a simple number selection (1-10)."""
    number_match = re.search(r'^\s*(\d+)\s*$', user_message)
    if number_match:
        try:
            index = int(number_match.group(1)) - 1
            if similar_quotations and 0 <= index < len(similar_quotations):
                return similar_quotations[index]
        except ValueError:
            pass
    return None


def _try_id_selection(user_message: str, similar_quotations: list):
    """Try to match quotation_id:line_num format."""
    selection_match = re.search(r'(AJMFQ-\d+):(\d+)', user_message, re.IGNORECASE)
    if not selection_match:
        return None
    
    quotation_id = selection_match.group(1).upper()
    line_num = int(selection_match.group(2))

    # First check in similar_quotations
    if similar_quotations:
        for q in similar_quotations:
            if q.get("quotation_id") == quotation_id and q.get("line_num") == line_num:
                return q

    # Fallback to DB lookup
    return tools.get_quotation_by_id(quotation_id, line_num)


def _try_llm_extraction(user_message: str, similar_quotations: list):
    """Use LLM to extract selection from ambiguous input."""
    options_context = ""
    if similar_quotations:
        options_context = "Available options:\n"
        for idx, q in enumerate(similar_quotations):
            options_context += f"{idx+1}. ID: {q.get('quotation_id')}:{q.get('line_num')} - {q.get('description')}\n"
    
    extraction_prompt = [
        ("system", SELECTION_EXTRACTION_PROMPT.format(
            user_message=user_message,
            options_context=options_context
        ))
    ]
    result = llm.invoke(extraction_prompt)
    content = result.content.strip()

    if not content or content == "NOT_FOUND":
        return None

    llm_match = re.search(r'(AJMFQ-\d+):(\d+)', content, re.IGNORECASE)
    if not llm_match:
        return None
    
    quotation_id = llm_match.group(1).upper()
    line_num = int(llm_match.group(2))
    
    # Check options first
    if similar_quotations:
        for q in similar_quotations:
            if q.get("quotation_id") == quotation_id and q.get("line_num") == line_num:
                return q
    
    return tools.get_quotation_by_id(quotation_id, line_num)


def selection_node(state: AgentState):
    """
    Handles user's quotation selection and extracts quotation details.
    
    Supports:
    - Confirmation responses (Yes/No)
    - Number selection (1, 2, 3...)
    - ID selection (AJMFQ-000001:1)
    - Natural language description matching
    """
    user_message = state["messages"][-1].content
    similar_quotations = state.get("similar_quotations", [])
    trace_input = {
        "user_message": user_message,
        "similar_count": len(similar_quotations),
        "awaiting_selection": state.get("awaiting_selection", False)
    }
    
    # Check for pending confirmation first
    confirmation_result = _check_confirmation(user_message, state)
    if confirmation_result:
        tools._trace_tool(
            name="selection_node_confirmation",
            input_payload=trace_input,
            output_payload={"next": confirmation_result.get("next")}
        )
        return confirmation_result
    
    # Try selection methods in order of specificity
    selected = None
    selected = selected or _try_number_selection(user_message, similar_quotations)
    selected = selected or _try_id_selection(user_message, similar_quotations)
    selected = selected or _try_llm_extraction(user_message, similar_quotations)

    if selected:
        # Fetch detailed estimation lines for the selected quotation
        quotation_id = selected.get('quotation_id')
        line_num = selected.get('line_num')
        estimation_lines = tools.get_estimation_lines(quotation_id, line_num)
        tools._trace_tool(
            name="selection_node_match",
            input_payload=trace_input,
            output_payload={
                "quotation_id": quotation_id,
                "line_num": line_num,
                "items_count": len(estimation_lines)
            }
        )
        
        details_text = ""
        total_price = selected.get('price', 0) or selected.get('sales_price', 0)
        
        if estimation_lines:
            details_text = "\n\n**Included Items:**\n\n"
            details_text += "| Item Description | Quantity | Price (AED) |\n"
            details_text += "| :--- | :---: | ---: |\n"
            for item in estimation_lines:
                qty = item.get('quantity', 1)
                uom = item.get('uom', 'EA')
                price = item.get('sales_price', 0)
                desc = item.get('item_name', 'N/A')
                details_text += f"| {desc} | {qty} {uom} | {price:,.2f} |\n"

        
        confirmation_msg = f"""I've selected quotation **{quotation_id}** (Line {line_num}):
- **Description:** {selected.get('description')}
- **Boat Model:** {selected.get('boat_model') or selected.get('afz_boat_model_id')}
- **Total Price:** {total_price:,.2f} AED{details_text}

Do you want to create a costing job for this quotation? (Yes/No)

If you want to use a different job description, reply like:
Yes, description: <your new description>"""

        return {
            "messages": [AIMessage(content=confirmation_msg)],
            "selected_quotation": selected,
            "job_description_override": None,
            "awaiting_selection": False,
            "next": "FINISH" # Wait for user confirmation
        }
    else:
        tools._trace_tool(
            name="selection_node_no_match",
            input_payload=trace_input,
            output_payload={"matched": False}
        )
        return {
            "messages": [AIMessage(content="I couldn't identify your selection. Please select one of the options by number (e.g., '1') or provide the Quotation ID.")],
            "awaiting_selection": True,
            "next": "__end__"
        }
