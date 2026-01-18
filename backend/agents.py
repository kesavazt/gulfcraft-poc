from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_openai import AzureChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from state import AgentState
import tools
import config
import re

# --- LLM Setup ---
llm = AzureChatOpenAI(azure_deployment=config.AZURE_OPENAI_CHAT_DEPLOYMENT_NAME,
                        temperature=0,
                        openai_api_key=config.OPENAI_API_KEY,
                        api_version=config.OPENAI_API_VERSION,
                        azure_endpoint=config.AZURE_OPENAI_ENDPOINT)

# --- Supervisor ---
members = ["SearchAgent", "SelectionAgent", "CostingAgent"]
system_prompt = (
    "You are a supervisor tasked with managing a conversation between the"
    " following workers: {members}. Given the following user request,"
    " respond with the worker to act next. Each worker will perform a"
    " task and respond with their results and status. When finished,"
    " respond with FINISH."
    "\n\n"
    "Logic:"
    "\n1. If the user input is casual (e.g., 'hello', 'how are you', 'hi'), respond with a friendly greeting and respond with FINISH"
    "\n2. If the user wants to create a NEW job or is requesting a NEW quotation (mentions job description and boat model), ALWAYS route to 'SearchAgent'. This applies even if a previous quotation was generated in the conversation."
    "\n3. If the user is selecting a quotation (providing quotation_id:line_num like 'AJMFQ-000001:1'), route to 'SelectionAgent'"
    "\n4. If the user asks to see more quotations, route to 'SearchAgent'"
    "\n5. NEVER route directly to 'CostingAgent' - it is only called after SelectionAgent confirms a selection"
    "\n\nIMPORTANT: Each new quotation request with a job description should start fresh with SearchAgent, regardless of conversation history."
)

# CostingAgent is not directly routable from Supervisor - it's called from SelectionAgent
routable_members = ["SearchAgent", "SelectionAgent"]
options = ["FINISH"] + routable_members
function_def = {
    "name": "route",
    "description": "Select the next role.",
    "parameters": {
        "title": "routeSchema",
        "type": "object",
        "properties": {
            "next": {
                "title": "Next",
                "anyOf": [
                    {"enum": options},
                ],
            },
            "greeting_response": {
                "title": "GreetingResponse",
                "type": "string",
                "description": "If this is a casual greeting, provide a friendly response here"
            }
        },
        "required": ["next"],
    },
}
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        (
            "system",
            "Given the conversation above, who should act next?"
            " Or should we FINISH? Select one of: {options}",
        ),
    ]
).partial(options=str(options), members=", ".join(routable_members))

supervisor_chain = (
    prompt
    | llm.with_structured_output(function_def)
)


def supervisor_node(state: AgentState):
    result = supervisor_chain.invoke(state)

    # If it's a greeting, add the greeting response to messages
    if result["next"] == "FINISH" and result.get("greeting_response"):
        return {
            "next": result["next"],
            "messages": [AIMessage(content=result["greeting_response"])]
        }

    return {"next": result["next"]}

# --- Search Agent ---
def search_node(state: AgentState):
    """Searches for similar quotations based on user's job description and boat model."""
    user_query = state["messages"][-1].content

    # Check if this is a "show more" request
    show_more_phrases = ["more quotation", "show more", "see more", "other quotation", "different quotation"]
    is_show_more = any(phrase in user_query.lower() for phrase in show_more_phrases)

    # Get previous search parameters if available
    last_description = state.get("last_search_description")
    last_boat_model = state.get("last_search_boat_model")
    current_top_k = state.get("current_top_k", config.TOP_K_ITEMS)

    if is_show_more and last_description and last_boat_model:
        # Increase top_k and use previous search parameters
        new_top_k = current_top_k + 5
        search_results = tools.search_similar_quotations(last_description, last_boat_model, top_k=new_top_k)

        # Create a message with the results
        result_content = str(search_results) if search_results else "No additional quotations found."

        return {
            "messages": [AIMessage(content=result_content)],
            "current_top_k": new_top_k,
            "selected_quotation": None  # Clear previous selection when showing more
        }
    else:
        # Extract description and boat model using LLM for new search
        extraction_prompt = [
            ("system",
             f"""
The user has asked the following query: {user_query}

The user wants a job done. He has provided a description and boat model. Extract the description and boat model and
use the search_similar_quotations tool to get a list of similar quotations. When extracting description, don't miss important keywords like fitting,
leaking, plumbing etc from the description if there are any.
"""),
        ]
        llm_with_tools = llm.bind_tools([tools.search_similar_quotations])
        result = llm_with_tools.invoke(extraction_prompt)

        # Try to extract the parameters from the tool call for future "show more" requests
        new_description = None
        new_boat_model = None
        if result.tool_calls:
            for tool_call in result.tool_calls:
                if tool_call.get("name") == "search_similar_quotations":
                    args = tool_call.get("args", {})
                    new_description = args.get("job_description")
                    new_boat_model = args.get("boat_model")
                    break

        return {
            "messages": [result],
            "last_search_description": new_description,
            "last_search_boat_model": new_boat_model,
            "current_top_k": config.TOP_K_ITEMS,
            "selected_quotation": None,  # Clear previous selection for new search
            "job_id": None,  # Clear previous job
            "generated_file": None,  # Clear previous file
            "awaiting_selection": False  # Reset selection state
        }


def refinement_node(state: AgentState):
    """Presents search results to user and asks for selection."""
    # Get the tool output from messages - could be ToolMessage or regular message
    messages = state.get("messages", [])

    fetched_quotations = ""
    # Look for the tool message with search results (iterate from end)
    for msg in reversed(messages):
        if hasattr(msg, 'content') and msg.content:
            fetched_quotations = msg.content
            break

    if not fetched_quotations:
        return {
            "messages": [AIMessage(content="I couldn't find any quotations. Please try again with a different description or boat model.")],
            "awaiting_selection": False
        }

    presentation_prompt = [
        ("system",
         f'''
Following is a list of quotations:
{fetched_quotations}

Present each of these to the user. Mention all attributes of each quotation including the quotation_id and line_num. Don't skip anything.
Use bulleted list, don't use numbers when presenting.
Ask the user to select one of these quotations by entering the selection in the format: **quotation_id:line_num** (e.g., AJMFQ-000001:1).
They can also ask to see more quotations if none of these match their needs.
'''
         )
    ]
    result = llm.invoke(presentation_prompt)

    return {
        "messages": [result],
        "awaiting_selection": True
    }


def selection_node(state: AgentState):
    """Handles user's quotation selection and extracts quotation details."""
    user_message = state["messages"][-1].content
    similar_quotations = state.get("similar_quotations", [])

    # Extract quotation ID and line number in format quotation_id:line_num
    # e.g., "AJMFQ-000001:1" or "AJMFQ-000001:10"
    selection_match = re.search(r'(AJMFQ-\d+):(\d+)', user_message, re.IGNORECASE)

    selected = None

    if selection_match:
        quotation_id = selection_match.group(1).upper()
        line_num = int(selection_match.group(2))

        # First, try to find in similar_quotations if available
        if similar_quotations:
            for q in similar_quotations:
                if q.get("quotation_id") == quotation_id and q.get("line_num") == line_num:
                    selected = q
                    break

        # If not found in similar_quotations, fetch directly from DB
        if not selected:
            selected = tools.get_quotation_by_id(quotation_id, line_num)

    # If still not found, use LLM to extract and try again
    if not selected:
        extraction_prompt = [
            ("system",
             f"""
The user has selected a quotation. Their message is: "{user_message}"

Extract the quotation ID and line number from the user's message.
The format should be: quotation_id:line_num (e.g., "AJMFQ-000001:1")

If the user provides just a quotation ID without a line number, or says something like "option 1",
explain that they need to provide both the quotation ID and line number in the format quotation_id:line_num.

Return ONLY the quotation_id:line_num if found, or explain what format is needed.
"""),
        ]
        result = llm.invoke(extraction_prompt)

        # Try to extract ID:line_num from LLM response
        llm_match = re.search(r'(AJMFQ-\d+):(\d+)', result.content, re.IGNORECASE)
        if llm_match:
            quotation_id = llm_match.group(1).upper()
            line_num = int(llm_match.group(2))
            selected = tools.get_quotation_by_id(quotation_id, line_num)

    # If we found a selection, confirm and move to costing
    if selected:
        confirmation_msg = f"""I've selected quotation **{selected.get('quotation_id')}** (Line {selected.get('line_num')}):
- Description: {selected.get('description')}
- Boat Model: {selected.get('boat_model') or selected.get('afz_boat_model_id')}

Now I'll retrieve the items for this quotation and generate a costing sheet."""

        return {
            "messages": [AIMessage(content=confirmation_msg)],
            "selected_quotation": selected,
            "awaiting_selection": False,
            "next": "CostingAgent"
        }
    else:
        return {
            "messages": [AIMessage(content="I couldn't identify your selection. Please provide both the quotation ID and line number in the format **quotation_id:line_num** (e.g., AJMFQ-000001:1).")],
            "awaiting_selection": True,
            "next": "__end__"  # Explicitly set to end so it doesn't use stale value from Supervisor
        }


def costing_node(state: AgentState):
    """
    Main costing workflow node:
    1. Get estimation lines for selected quotation
    2. Look up prices for each item in Product table
    3. Create costing sheet (items > threshold marked as 'pending')
    4. Send emails for items needing quotes
    5. Upload to SharePoint
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
    estimation_items = tools.get_estimation_lines(quotation_id, line_num)

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

    # Step 3: Look up prices for each item
    # Labour items use sales_price from estimation_lines
    # Non-labour items get price from Products table
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
            # For labour items, use sales_price from estimation_lines
            costing_item["unit_price"] = item.get("sales_price")
            costing_item["price_status"] = "resolved"
            costing_item["vendor_email"] = None
        else:
            # For non-labour items, get price from Products table using item_code
            item_code = item.get("item_code", "")
            product_info = tools.get_product_price(item_code)
            costing_item["unit_price"] = product_info.get("unit_cost")
            costing_item["vendor_email"] = product_info.get("vendor_email", "vinod.ihava@gulfcraftinc.com")
            # Check if price exists and is below threshold
            if product_info.get("unit_cost") is not None and product_info.get("unit_cost") <= threshold:
                costing_item["price_status"] = "resolved"
            else:
                costing_item["price_status"] = "pending_quote"
                pending_quote_items.append(costing_item)

        costing_items.append(costing_item)

    # Step 4: Save costing line items
    tools.save_costing_line_items(job_id, costing_items)

    # Step 5: Generate costing sheet
    file_path = tools.create_costing_sheet_with_items(
        job_id, costing_items, quotation_id, description
    )

    # Step 6: Send emails for items needing quotes
    emails_sent = False
    if pending_quote_items:
        for item in pending_quote_items:
            tools.send_price_request_email(
                job_id=job_id,
                item_name=item["item_name"],
                item_code=item.get("item_code", "N/A"),
                quantity=item.get("quantity", 1),
                vendor_email=item["vendor_email"]
            )
        emails_sent = True

    # Step 7: Set download URL for the costing sheet
    sharepoint_url = None
    if file_path:
        sharepoint_url = f"/costing-sheets/{file_path}"

    # Build response message
    labour_items = [i for i in costing_items if i.get("is_labour")]
    non_labour_resolved = [i for i in costing_items if not i.get("is_labour") and i["price_status"] == "resolved"]
    pending_count = len(pending_quote_items)

    response_parts = [
        f"**Costing Job Created: {job_id}**\n",
        f"- Quotation: {quotation_id}",
        f"- Line Number: {line_num}",
        f"- Total Items: {len(costing_items)}",
        f"- Labour Items: {len(labour_items)} (price from estimation)",
        f"- Non-Labour Items with resolved prices: {len(non_labour_resolved)}",
        f"- Items pending quotes: {pending_count}",
    ]

    if pending_quote_items:
        response_parts.append(f"\n**Items Requiring Price Quotes (>{threshold} AED or not found in Products):**")
        for item in pending_quote_items:
            response_parts.append(f"  - {item['item_name']} (email sent to {item['vendor_email']})")

    if file_path:
        response_parts.append(f"\n**Costing Sheet:** {file_path}")

    if sharepoint_url:
        response_parts.append(f"**SharePoint URL:** {sharepoint_url}")

    if pending_quote_items:
        response_parts.append("\nI've sent price quotation requests to the vendors. The system will monitor for incoming responses and update the costing sheet automatically.")

    return {
        "messages": [AIMessage(content="\n".join(response_parts))],
        "job_id": job_id,
        "estimation_items": estimation_items,
        "costing_items": costing_items,
        "pending_quote_items": pending_quote_items,
        "generated_file": file_path,
        "sharepoint_url": sharepoint_url,
        "emails_sent": emails_sent,
        "awaiting_quotes": len(pending_quote_items) > 0
    }


