"""
Edit Job Agent Node

Handles modifications to existing costing jobs via chat interface.
Supports adding, removing, and updating line items and job descriptions.
"""

import json
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from core.state import AgentState
from utils import tools
from utils.llm import llm
from utils.prompts import EDIT_JOB_AGENT_SYSTEM_PROMPT, EDIT_JOB_EXTRACTION_PROMPT
from utils.langfuse_tracing import trace_agent


def _extract_edit_parameters(user_message: str, state: AgentState) -> dict:
    """Extract edit operation parameters from user message using LLM."""
    last_job_id = state.get("last_mentioned_job_id") or state.get("job_id") or "Not specified"
    context = {
        "awaiting_quotes": state.get("awaiting_quotes", False),
        "last_action": state.get("last_action")
    }

    prompt = EDIT_JOB_EXTRACTION_PROMPT.format(
        user_message=user_message,
        last_job_id=last_job_id,
        context=json.dumps(context)
    )

    try:
        response = llm.invoke([{"role": "user", "content": prompt}])
        # Try to parse JSON from response
        content = response.content

        # Extract JSON from markdown code blocks if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        params = json.loads(content)

        # Use context if job_id not provided
        if not params.get("job_id") and last_job_id != "Not specified":
            params["job_id"] = last_job_id

        return params
    except Exception as e:
        print(f"[EditJobAgent] Extraction error: {e}")
        return {}


@trace_agent
def edit_job_node(state: AgentState):
    """
    Handles job editing operations based on user requests.
    """
    user_message = state["messages"][-1].content if state.get("messages") else ""

    # Extract parameters
    params = _extract_edit_parameters(user_message, state)

    if not params or not params.get("operation"):
        return {
            "messages": [AIMessage(content=
                "I can help you edit a costing job! Please specify:\n"
                "- The job ID (or I can use the last one we discussed)\n"
                "- What you'd like to change (add/remove/update items, change description)\n\n"
                "Examples:\n"
                "- 'Add 50 meters of cable to job COST-00123'\n"
                "- 'Remove the anchor winch from this job'\n"
                "- 'Change the hydraulic pump price to 850 AED'"
            )]
        }

    job_id = params.get("job_id")
    operation = params.get("operation")

    if not job_id:
        return {
            "messages": [AIMessage(content=
                "I need to know which job to edit. Please provide a job ID (e.g., COST-00123456) "
                "or mention 'this job' if we were just discussing one."
            )]
        }

    # Execute the appropriate operation
    result = None
    response_msg = ""

    if operation == "add_item":
        item_name = params.get("item_name")
        if not item_name:
            response_msg = "Please specify the item name to add."
        else:
            result = tools.add_line_item_to_job(
                job_id=job_id,
                item_name=item_name,
                item_code=params.get("item_code", ""),
                quantity=params.get("quantity", 1),
                unit_price=params.get("unit_price"),
                vendor_email=params.get("vendor_email")
            )

            if result.get("success"):
                response_msg = (
                    f"✅ Added **{item_name}** to job **{job_id}**\n\n"
                    f"- Quantity: {result.get('quantity', 1)}\n"
                    f"- Unit Price: {result.get('unit_price') if result.get('unit_price') else 'Pending quote'} AED\n"
                    f"- Status: {result.get('price_status')}\n\n"
                    f"The costing sheet has been regenerated with the updated items."
                )
            else:
                response_msg = f"❌ Failed to add item: {result.get('error', 'Unknown error')}"

    elif operation == "remove_item":
        item_identifier = params.get("item_identifier")
        if not item_identifier:
            response_msg = "Please specify which item to remove (by name or item number)."
        else:
            result = tools.remove_line_item_from_job(
                job_id=job_id,
                item_identifier=item_identifier
            )

            if result.get("success"):
                response_msg = (
                    f"✅ Removed **{result.get('removed_item')}** from job **{job_id}**\n\n"
                    f"The costing sheet has been updated."
                )
            else:
                response_msg = f"❌ Failed to remove item: {result.get('error', 'Unknown error')}"

    elif operation == "update_item":
        item_identifier = params.get("item_identifier")
        if not item_identifier:
            response_msg = "Please specify which item to update."
        else:
            result = tools.update_line_item(
                job_id=job_id,
                item_identifier=item_identifier,
                new_quantity=params.get("new_quantity"),
                new_unit_price=params.get("new_unit_price"),
                new_item_name=params.get("new_item_name"),
                new_item_code=params.get("new_item_code")
            )

            if result.get("success"):
                changes = []
                if params.get("new_quantity"):
                    changes.append(f"quantity → {params['new_quantity']}")
                if params.get("new_unit_price"):
                    changes.append(f"price → {params['new_unit_price']} AED")
                if params.get("new_item_name"):
                    changes.append(f"name → {params['new_item_name']}")
                if params.get("new_item_code"):
                    changes.append(f"code → {params['new_item_code']}")

                response_msg = (
                    f"✅ Updated **{result.get('item_name')}** in job **{job_id}**\n\n"
                    f"Changes: {', '.join(changes)}\n\n"
                    f"Current status:\n"
                    f"- Quantity: {result.get('quantity')}\n"
                    f"- Unit Price: {result.get('unit_price')} AED\n"
                    f"- Price Status: {result.get('price_status')}\n\n"
                    f"The costing sheet has been regenerated."
                )
            else:
                response_msg = f"❌ Failed to update item: {result.get('error', 'Unknown error')}"

    elif operation == "update_description":
        new_description = params.get("new_description")
        if not new_description:
            response_msg = "Please specify the new description for the job."
        else:
            result = tools.update_job_description(
                job_id=job_id,
                new_description=new_description
            )

            if result.get("success"):
                response_msg = (
                    f"✅ Updated description for job **{job_id}**\n\n"
                    f"New description: {new_description}\n\n"
                    f"The costing sheet has been regenerated."
                )
            else:
                response_msg = f"❌ Failed to update description: {result.get('error', 'Unknown error')}"

    else:
        response_msg = f"I don't understand the operation '{operation}'. I can help with: add_item, remove_item, update_item, or update_description."

    # Update state with context
    return {
        "messages": [AIMessage(content=response_msg)],
        "last_mentioned_job_id": job_id,
        "last_action": operation
    }
