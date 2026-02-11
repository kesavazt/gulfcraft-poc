"""
Quote Management Agent Node

Handles manual quote entry, quote request resending, and quote cancellations.
"""

import json
import os
from langchain_core.messages import AIMessage
from core.state import AgentState
from core import config
from utils import tools
from utils.llm import llm
from utils.prompts import QUOTE_MANAGEMENT_AGENT_SYSTEM_PROMPT, QUOTE_MANAGEMENT_EXTRACTION_PROMPT
from utils.langfuse_tracing import trace_agent


def _get_generated_file_path(job_id: str):
    """Return the costing sheet file path if it exists on disk."""
    file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, f"costing_{job_id}.xlsx")
    return file_path if os.path.exists(file_path) else None


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

    # If disambiguation is pending and user didn't trigger a new operation, treat as disambiguation response
    pending = state.get("pending_disambiguation")
    if pending and (not params or not params.get("operation")):
        params = {"operation": pending.get("operation", "enter_quote"), "job_id": pending.get("job_id")}

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

        # Sanitize price: strip currency symbols/text and convert to float
        if quoted_price is not None:
            try:
                import re
                cleaned = re.sub(r'[^\d.]', '', str(quoted_price))
                quoted_price = float(cleaned)
            except (ValueError, TypeError):
                quoted_price = None

        # Check if user is responding to a disambiguation prompt
        pending = state.get("pending_disambiguation")
        if pending and pending.get("operation") == "enter_quote":
            # User is selecting from disambiguation options
            selection = user_message.strip()
            items = pending.get("items", [])
            selected_item = None

            # Try numeric selection (1, 2, 3...)
            if selection.isdigit():
                idx = int(selection) - 1
                if 0 <= idx < len(items):
                    selected_item = items[idx]

            # Try direct ID match
            if not selected_item:
                for item in items:
                    if str(item["id"]) == selection:
                        selected_item = item
                        break

            if selected_item:
                price = pending.get("quoted_price", quoted_price)
                success = tools.mark_quote_received_by_id(
                    line_item_id=selected_item["id"],
                    price=price,
                    job_id=pending.get("job_id", job_id)
                )
                if success:
                    response_msg = (
                        f"✅ Quote entered for job **{pending.get('job_id', job_id)}**\n\n"
                        f"- Item: {selected_item['item_name']}\n"
                        f"- Price: {price} AED\n\n"
                        f"The costing sheet has been updated."
                    )
                    quote_status = tools.check_all_quotes_received(pending.get("job_id", job_id))
                    if quote_status.get("all_received"):
                        response_msg += f"\n\n🎉 **All quotes received!** Job is now ready for review."
                    else:
                        pending_items = quote_status.get("pending_items", [])
                        response_msg += (
                            f"\n\n⏳ Still waiting for {len(pending_items)} quote(s): "
                            f"{', '.join(pending_items[:3])}"
                            f"{'...' if len(pending_items) > 3 else ''}"
                        )
                else:
                    response_msg = f"❌ Failed to apply quote to {selected_item['item_name']}."
                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": pending.get("job_id", job_id),
                    "last_action": operation,
                    "pending_disambiguation": None,
                    "generated_file": _get_generated_file_path(pending.get("job_id", job_id)),
                }
            else:
                response_msg = (
                    f"Please select a valid item number (1-{len(items)}) from the list above."
                )
                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": pending.get("job_id", job_id),
                    "pending_disambiguation": pending,
                }

        if not item_identifier or quoted_price is None:
            response_msg = (
                "To enter a quote, I need:\n"
                "- The item name or ID\n"
                "- The quoted price\n\n"
                "Example: 'The hydraulic pump was quoted at 1200 AED'"
            )
        else:
            # Check for ambiguous matches before applying
            match_result = tools.find_matching_line_items(job_id, item_identifier)

            if match_result["match"] == "multiple":
                items = match_result["items"]
                options = "\n".join([
                    f"  {i+1}. **{item['item_name']}** (ID: {item['id']}, "
                    f"Status: {item.get('price_status', 'unknown')})"
                    for i, item in enumerate(items)
                ])
                response_msg = (
                    f"I found **{len(items)} items** matching '{item_identifier}' "
                    f"in job **{job_id}**:\n\n{options}\n\n"
                    f"Which item should I apply the **{quoted_price} AED** quote to? "
                    f"Reply with the item number (1-{len(items)})."
                )
                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "items": items,
                        "quoted_price": quoted_price,
                        "job_id": job_id,
                        "operation": "enter_quote",
                    },
                }
            elif match_result["match"] == "exact":
                item = match_result["items"][0]
                success = tools.mark_quote_received_by_id(
                    line_item_id=item["id"],
                    price=quoted_price,
                    job_id=job_id
                )
                if success:
                    response_msg = (
                        f"✅ Quote entered for job **{job_id}**\n\n"
                        f"- Item: {item['item_name']}\n"
                        f"- Price: {quoted_price} AED\n\n"
                        f"The costing sheet has been updated."
                    )
                    quote_status = tools.check_all_quotes_received(job_id)
                    if quote_status.get("all_received"):
                        response_msg += f"\n\n🎉 **All quotes received!** Job {job_id} is now ready for review."
                    else:
                        pending_items = quote_status.get("pending_items", [])
                        response_msg += (
                            f"\n\n⏳ Still waiting for {len(pending_items)} quote(s): "
                            f"{', '.join(pending_items[:3])}"
                            f"{'...' if len(pending_items) > 3 else ''}"
                        )
                else:
                    response_msg = f"❌ Failed to enter quote for {item['item_name']}."
            else:
                fallback_msg = f'No item matching "{item_identifier}" found in job {job_id}.'
                response_msg = f"❌ {match_result.get('error', fallback_msg)}"

    elif operation == "resend_quote":
        item_name = params.get("item_identifier")
        resend_all = params.get("resend_all", False)

        # Check if user is responding to a disambiguation prompt
        pending = state.get("pending_disambiguation")
        if pending and pending.get("operation") == "resend_quote":
            selection = user_message.strip().lower()
            items = pending.get("items", [])

            # Handle "all" — resend all items from the list
            if selection in ("all", "resend all", "all of them", "everything"):
                sent = []
                failed = []
                resend_job = pending.get("job_id", job_id)
                for pq in items:
                    result = tools.resend_quote_request(
                        job_id=resend_job,
                        item_name=pq["item_name"]
                    )
                    if result.get("success"):
                        sent.append(f"- {result.get('item_name')} → {result.get('vendor_email')}")
                    else:
                        failed.append(f"- {pq['item_name']}: {result.get('error', 'Unknown error')}")

                response_msg = f"Resent **{len(sent)}** quote request(s) for job **{resend_job}**:\n\n"
                response_msg += "\n".join(sent)
                if failed:
                    response_msg += f"\n\n❌ Failed to resend {len(failed)} item(s):\n" + "\n".join(failed)
                else:
                    response_msg += "\n\nAll vendors should receive the emails shortly."
                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": resend_job,
                    "last_action": operation,
                    "pending_disambiguation": None,
                }

            selected_item = None

            # Try numeric selection (1, 2, 3...)
            if selection.isdigit():
                idx = int(selection) - 1
                if 0 <= idx < len(items):
                    selected_item = items[idx]

            # Try name match
            if not selected_item:
                for item in items:
                    if selection in item["item_name"].lower():
                        selected_item = item
                        break

            if selected_item:
                result = tools.resend_quote_request(
                    job_id=pending.get("job_id", job_id),
                    item_name=selected_item["item_name"]
                )
                if result.get("success"):
                    response_msg = (
                        f"✅ Quote request resent for job **{pending.get('job_id', job_id)}**\n\n"
                        f"- Item: {result.get('item_name')}\n"
                        f"- Vendor: {result.get('vendor_email')}\n\n"
                        f"The vendor should receive the email shortly."
                    )
                else:
                    response_msg = f"❌ Failed to resend: {result.get('error', 'Unknown error')}"
                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": pending.get("job_id", job_id),
                    "last_action": operation,
                    "pending_disambiguation": None,
                }
            else:
                response_msg = (
                    f"Please select a valid item number (1-{len(items)}) from the list above."
                )
                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": pending.get("job_id", job_id),
                    "pending_disambiguation": pending,
                }

        # Handle "resend all" — resend every pending quote for this job
        if resend_all:
            pending_quotes = tools.get_pending_quote_requests(job_id)
            if not pending_quotes:
                response_msg = f"There are no pending quote requests for job **{job_id}**."
            else:
                sent = []
                failed = []
                for pq in pending_quotes:
                    result = tools.resend_quote_request(
                        job_id=job_id,
                        item_name=pq["item_name"]
                    )
                    if result.get("success"):
                        sent.append(f"- {result.get('item_name')} → {result.get('vendor_email')}")
                    else:
                        failed.append(f"- {pq['item_name']}: {result.get('error', 'Unknown error')}")

                response_msg = f"Resent **{len(sent)}** quote request(s) for job **{job_id}**:\n\n"
                response_msg += "\n".join(sent)
                if failed:
                    response_msg += f"\n\n❌ Failed to resend {len(failed)} item(s):\n" + "\n".join(failed)
                else:
                    response_msg += "\n\nAll vendors should receive the emails shortly."

        # No item specified — show pending quotes and let user pick
        elif not item_name:
            pending_quotes = tools.get_pending_quote_requests(job_id)
            if not pending_quotes:
                response_msg = f"There are no pending quote requests for job **{job_id}**."
            else:
                options = "\n".join([
                    f"  {i+1}. **{pq['item_name']}** (Vendor: {pq.get('vendor_email', 'N/A')})"
                    for i, pq in enumerate(pending_quotes)
                ])
                response_msg = (
                    f"Here are the **{len(pending_quotes)} pending quote(s)** for job **{job_id}**:\n\n"
                    f"{options}\n\n"
                    f"Which item would you like to resend? Reply with the **number**, or say **'all'** to resend all."
                )
                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "items": pending_quotes,
                        "job_id": job_id,
                        "operation": "resend_quote",
                    },
                }

        # Specific item — use disambiguation like enter_quote
        else:
            match_result = tools.find_matching_line_items(job_id, item_name)

            if match_result["match"] == "multiple":
                # Filter to only pending_quote items
                pending_items = [
                    item for item in match_result["items"]
                    if item.get("price_status") == "pending_quote"
                ]
                if not pending_items:
                    response_msg = f"No pending quote items matching '{item_name}' found in job **{job_id}**."
                elif len(pending_items) == 1:
                    result = tools.resend_quote_request(
                        job_id=job_id,
                        item_name=pending_items[0]["item_name"]
                    )
                    if result.get("success"):
                        response_msg = (
                            f"✅ Quote request resent for job **{job_id}**\n\n"
                            f"- Item: {result.get('item_name')}\n"
                            f"- Vendor: {result.get('vendor_email')}\n\n"
                            f"The vendor should receive the email shortly."
                        )
                    else:
                        response_msg = f"❌ Failed to resend: {result.get('error', 'Unknown error')}"
                else:
                    options = "\n".join([
                        f"  {i+1}. **{item['item_name']}** (Status: {item.get('price_status', 'unknown')})"
                        for i, item in enumerate(pending_items)
                    ])
                    response_msg = (
                        f"I found **{len(pending_items)} pending items** matching '{item_name}' "
                        f"in job **{job_id}**:\n\n{options}\n\n"
                        f"Which item should I resend the quote request for? Reply with the item number."
                    )
                    return {
                        "messages": [AIMessage(content=response_msg)],
                        "last_mentioned_job_id": job_id,
                        "pending_disambiguation": {
                            "items": pending_items,
                            "job_id": job_id,
                            "operation": "resend_quote",
                        },
                    }
            elif match_result["match"] == "exact":
                item = match_result["items"][0]
                result = tools.resend_quote_request(
                    job_id=job_id,
                    item_name=item["item_name"]
                )
                if result.get("success"):
                    response_msg = (
                        f"✅ Quote request resent for job **{job_id}**\n\n"
                        f"- Item: {result.get('item_name')}\n"
                        f"- Vendor: {result.get('vendor_email')}\n\n"
                        f"The vendor should receive the email shortly."
                    )
                else:
                    response_msg = f"❌ Failed to resend: {result.get('error', 'Unknown error')}"
            else:
                response_msg = f"❌ No item matching '{item_name}' found in job **{job_id}**."

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
        "last_action": operation,
        "pending_disambiguation": None,
        "generated_file": _get_generated_file_path(job_id),
    }
