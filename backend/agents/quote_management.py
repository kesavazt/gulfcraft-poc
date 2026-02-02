"""
Quote Management Agent Node

Handles manual quote entry, quote request resending, and quote cancellations.
"""

import json
from langchain_core.messages import AIMessage
from core.state import AgentState
from utils import tools
from utils.llm import llm
from utils.prompts import QUOTE_MANAGEMENT_AGENT_SYSTEM_PROMPT, QUOTE_MANAGEMENT_EXTRACTION_PROMPT
from utils.langfuse_tracing import trace_agent


def _extract_quote_parameters(user_message: str, state: AgentState) -> dict:
    """Extract quote management parameters from user message using LLM."""
    last_job_id = state.get("last_mentioned_job_id") or state.get("job_id") or "Not specified"

    # Get pending quotes for context
    pending_quotes = []
    if last_job_id != "Not specified":
        pending_quotes = tools.get_pending_quote_requests(last_job_id)

    prompt = QUOTE_MANAGEMENT_EXTRACTION_PROMPT.format(
        user_message=user_message,
        last_job_id=last_job_id,
        pending_quotes=json.dumps(pending_quotes[:5])  # Limit to 5 for context
    )

    try:
        response = llm.invoke([{"role": "user", "content": prompt}])
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
        print(f"[QuoteManagementAgent] Extraction error: {e}")
        return {}


@trace_agent
def quote_management_node(state: AgentState):
    """
    Handles quote management operations.
    """
    user_message = state["messages"][-1].content if state.get("messages") else ""

    # Extract parameters
    params = _extract_quote_parameters(user_message, state)

    if not params or not params.get("operation"):
        return {
            "messages": [AIMessage(content=
                "I can help you manage vendor quotes! I can:\n\n"
                "📝 **Enter manual quotes** - Enter prices you've received from vendors\n"
                "📧 **Resend quote requests** - Resend emails to vendors\n"
                "❌ **Cancel quote requests** - Cancel pending quote requests\n\n"
                "Examples:\n"
                "- 'The vendor quoted 1200 AED for the hydraulic pump'\n"
                "- 'Resend quote request for the anchor winch'\n"
                "- 'Cancel the quote request for navigation system'"
            )]
        }

    job_id = params.get("job_id")
    operation = params.get("operation")

    if not job_id:
        return {
            "messages": [AIMessage(content=
                "I need to know which job this quote is for. Please provide a job ID "
                "(e.g., COST-00123456) or mention 'this job' if we were just discussing one."
            )]
        }

    # Execute the appropriate operation
    result = None
    response_msg = ""

    if operation == "enter_quote":
        item_identifier = params.get("item_identifier")
        quoted_price = params.get("quoted_price")

        if not item_identifier or quoted_price is None:
            response_msg = (
                "To enter a quote, I need:\n"
                "- The item name or ID\n"
                "- The quoted price\n\n"
                "Example: 'The hydraulic pump was quoted at 1200 AED'"
            )
        else:
            result = tools.enter_manual_quote(
                job_id=job_id,
                item_identifier=item_identifier,
                quoted_price=quoted_price,
                vendor_email=params.get("vendor_email")
            )

            if result.get("success"):
                response_msg = (
                    f"✅ Quote entered successfully for job **{job_id}**\n\n"
                    f"- Item: {item_identifier}\n"
                    f"- Price: {quoted_price} AED\n\n"
                    f"The costing sheet has been updated with the new price. "
                    f"I'll check if all quotes for this job have been received..."
                )

                # Check if all quotes received
                quote_status = tools.check_all_quotes_received(job_id)
                if quote_status.get("all_received"):
                    response_msg += (
                        f"\n\n🎉 **All quotes received!** Job {job_id} is now ready for review."
                    )
                else:
                    pending = quote_status.get("pending_items", [])
                    response_msg += (
                        f"\n\n⏳ Still waiting for {len(pending)} quote(s): "
                        f"{', '.join(pending[:3])}"
                        f"{'...' if len(pending) > 3 else ''}"
                    )
            else:
                response_msg = f"❌ Failed to enter quote: {result.get('error', 'Unknown error')}"

    elif operation == "resend_quote":
        item_name = params.get("item_identifier")

        if not item_name:
            response_msg = "Please specify which item's quote request to resend."
        else:
            result = tools.resend_quote_request(
                job_id=job_id,
                item_name=item_name
            )

            if result.get("success"):
                response_msg = (
                    f"✅ Quote request resent for job **{job_id}**\n\n"
                    f"- Item: {result.get('item_name')}\n"
                    f"- Vendor: {result.get('vendor_email')}\n\n"
                    f"The vendor should receive the email shortly."
                )
            else:
                response_msg = f"❌ Failed to resend quote request: {result.get('error', 'Unknown error')}"

    elif operation == "cancel_quote":
        item_name = params.get("item_identifier")

        if not item_name:
            response_msg = "Please specify which item's quote request to cancel."
        else:
            result = tools.cancel_quote_request(
                job_id=job_id,
                item_name=item_name
            )

            if result.get("success"):
                response_msg = (
                    f"✅ Quote request cancelled for job **{job_id}**\n\n"
                    f"- Item: {item_name}\n\n"
                    f"You can manually enter a price for this item or use a previous price."
                )
            else:
                response_msg = f"❌ Failed to cancel quote request: {result.get('error', 'Unknown error')}"

    else:
        response_msg = (
            f"I don't understand the operation '{operation}'. "
            f"I can help with: enter_quote, resend_quote, or cancel_quote."
        )

    # Update state with context
    return {
        "messages": [AIMessage(content=response_msg)],
        "last_mentioned_job_id": job_id,
        "last_action": operation
    }
