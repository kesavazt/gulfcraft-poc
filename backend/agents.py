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
    "\n2. If the user wants to create a job or is requesting a quotation, route to 'SearchAgent'. Only route if the information is complete. The user query must have a job_description and boat_model (e.g MAJESTY62, MAJESTY100, etc)"
    "\n3. If the user is selecting a quotation (providing a quotation ID like 'AJMFQ-000001' or saying 'I select option 1'), route to 'SelectionAgent'"
    "\n4. If the user asks to see more quotations, route to 'SearchAgent'"
    "\n5. If a quotation has been selected and we need to generate costing, route to 'CostingAgent'"
)

options = ["FINISH"] + members
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
).partial(options=str(options), members=", ".join(members))

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

    # Extract description and boat model using LLM
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

    return {"messages": [result]}


def refinement_node(state: AgentState):
    """Presents search results to user and asks for selection."""
    fetched_quotations = state["messages"][-1].content
    print(state["messages"][-1].content)

    presentation_prompt = [
        ("system",
         f'''
Following is a list of quotations:
{fetched_quotations}

Present each of these to the user. Mention all attributes of each quotation. Don't skip anything.
Use bulleted list, don't use numbers when presenting.
Ask the user to select one of these quotations by entering the selected quotation's id.
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

    # Extract quotation ID from user message using regex
    quotation_id_match = re.search(r'(AJMFQ-\d+)', user_message, re.IGNORECASE)

    selected = None

    # First, try to find in similar_quotations if available
    if similar_quotations:
        for q in similar_quotations:
            if q.get("quotation_id") in user_message or q.get("id") in user_message:
                selected = q
                break

    # If not found in similar_quotations but we have a quotation ID, fetch directly from DB
    if not selected and quotation_id_match:
        quotation_id = quotation_id_match.group(1).upper()
        selected = tools.get_quotation_by_id(quotation_id)

    # If still not found, use LLM to extract and try again
    if not selected:
        extraction_prompt = [
            ("system",
             f"""
The user has selected a quotation. Their message is: "{user_message}"

Extract the quotation ID from the user's message. Quotation IDs follow the pattern "AJMFQ-XXXXXX" (e.g., "AJMFQ-000001").

If the user says something like "option 1" or "the first one", explain that you need the actual quotation ID.

Return ONLY the quotation ID if found, or explain what you need if not found.
"""),
        ]
        result = llm.invoke(extraction_prompt)

        # Try to extract ID from LLM response
        llm_match = re.search(r'(AJMFQ-\d+)', result.content, re.IGNORECASE)
        if llm_match:
            quotation_id = llm_match.group(1).upper()
            selected = tools.get_quotation_by_id(quotation_id)

    # If we found a selection, confirm and move to costing
    if selected:
        confirmation_msg = f"""I've selected quotation **{selected.get('quotation_id')}**:
- Description: {selected.get('description')}
- Boat Model: {selected.get('boat_model') or selected.get('afz_boat_model_id')}
- Line Number: {selected.get('line_num')}

Now I'll retrieve the items for this quotation and generate a costing sheet."""

        return {
            "messages": [AIMessage(content=confirmation_msg)],
            "selected_quotation": selected,
            "awaiting_selection": False,
            "next": "CostingAgent"
        }
    else:
        return {
            "messages": [AIMessage(content="I couldn't identify which quotation you selected. Please provide the quotation ID (e.g., AJMFQ-000001).")],
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
    costing_items = []
    pending_quote_items = []

    for item in estimation_items:
        item_name = item.get("item_name", "")
        product_info = tools.get_product_price(item_name)

        costing_item = {
            "item_name": item_name,
            "item_code": item.get("item_code"),
            "quantity": item.get("quantity", 1),
            "unit_price": product_info.get("unit_cost"),
            "vendor_email": product_info.get("vendor_email", "vinod.ihava@gulfcraftinc.com")
        }

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

    # Step 7: Upload to SharePoint
    sharepoint_url = None
    if file_path:
        tools.upload_to_sharepoint(file_path)
        sharepoint_url = f"{config.SHAREPOINT_SITE_URL}/costing_{job_id}.xlsx"

    # Build response message
    resolved_count = len([i for i in costing_items if i["price_status"] == "resolved"])
    pending_count = len(pending_quote_items)

    response_parts = [
        f"**Costing Job Created: {job_id}**\n",
        f"- Quotation: {quotation_id}",
        f"- Total Items: {len(costing_items)}",
        f"- Items with resolved prices: {resolved_count}",
        f"- Items pending quotes: {pending_count}",
    ]

    if pending_quote_items:
        response_parts.append(f"\n**Items Requiring Price Quotes (>{threshold} AED):**")
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


# --- Email Agent (kept for backwards compatibility) ---
email_tools = [
    tools.get_vendor_emails,
    tools.save_vendor_email,
    tools.create_sharepoint_job,
    tools.send_email,
    tools.check_email_replies,
    tools.update_sharepoint_job
]
email_agent = create_react_agent(llm, tools=email_tools)


def email_node(state: AgentState):
    result = email_agent.invoke(state)
    return {"messages": result["messages"]}


# --- SharePoint Agent (kept for backwards compatibility) ---
sharepoint_tools = [
    tools.generate_costing_sheet,
    tools.upload_to_sharepoint
]
sharepoint_agent = create_react_agent(llm, tools=sharepoint_tools)


def sharepoint_node(state: AgentState):
    result = sharepoint_agent.invoke(state)
    return {"messages": result["messages"]}

