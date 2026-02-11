"""
Edit Job Agent Node

Handles modifications to existing costing jobs via chat interface.
Supports adding, removing, and updating line items and job descriptions.
Includes product search when adding items and disambiguation for multiple matches.
"""

import json
import os
import re
from langchain_core.messages import AIMessage
from core.state import AgentState
from core import config
from utils import tools
from utils.llm import llm
from utils.prompts import EDIT_JOB_AGENT_SYSTEM_PROMPT, EDIT_JOB_EXTRACTION_PROMPT
from utils.langfuse_tracing import trace_agent


def _get_generated_file_path(job_id: str):
    """Return the costing sheet file path if it exists on disk."""
    file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, f"costing_{job_id}.xlsx")
    return file_path if os.path.exists(file_path) else None


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


def _sanitize_price(value) -> float | None:
    """Strip currency symbols/text from a price value and return float."""
    if value is None:
        return None
    try:
        cleaned = re.sub(r'[^\d.]', '', str(value))
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def _handle_disambiguation_response(user_message: str, pending: dict, job_id: str) -> dict:
    """Handle user's selection from a disambiguation prompt."""
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
            if str(item.get("id", "")) == selection:
                selected_item = item
                break

    if not selected_item:
        return {
            "messages": [AIMessage(content=f"Please select a valid item number (1-{len(items)}) from the list above.")],
            "last_mentioned_job_id": job_id,
            "pending_disambiguation": pending,
        }

    disambiguation_type = pending.get("disambiguation_type")

    if disambiguation_type == "add_item_search":
        # User selected a product from search results to add
        product = selected_item
        quantity = pending.get("quantity", 1)
        unit_price = _sanitize_price(pending.get("unit_price")) or product.get("unit_cost")

        result = tools.add_line_item_to_job(
            job_id=job_id,
            item_name=product.get("item_name", ""),
            item_code=product.get("item_code", ""),
            quantity=quantity,
            unit_price=unit_price,
            vendor_email=product.get("vendor_email")
        )

        if result.get("success"):
            price_display = f"{result.get('unit_price')} AED" if result.get('unit_price') else "Pending quote"
            response_msg = (
                f"✅ Added **{product.get('item_name')}** to job **{job_id}**\n\n"
                f"- Item Code: {product.get('item_code') or 'N/A'}\n"
                f"- Quantity: {quantity}\n"
                f"- Unit Price: {price_display}\n"
                f"- Status: {result.get('price_status')}\n\n"
                f"The costing sheet has been regenerated."
            )
        else:
            response_msg = f"❌ Failed to add item: {result.get('error', 'Unknown error')}"

        return {
            "messages": [AIMessage(content=response_msg)],
            "last_mentioned_job_id": job_id,
            "last_action": "add_item",
            "pending_disambiguation": None,
            "generated_file": _get_generated_file_path(job_id),
        }

    elif disambiguation_type == "remove_item":
        # User selected which item to remove
        result = tools.remove_line_item_from_job(
            job_id=job_id,
            item_identifier=str(selected_item["id"])
        )

        if result.get("success"):
            response_msg = (
                f"✅ Removed **{selected_item['item_name']}** from job **{job_id}**\n\n"
                f"The costing sheet has been updated."
            )
        else:
            response_msg = f"❌ Failed to remove item: {result.get('error', 'Unknown error')}"

        return {
            "messages": [AIMessage(content=response_msg)],
            "last_mentioned_job_id": job_id,
            "last_action": "remove_item",
            "pending_disambiguation": None,
            "generated_file": _get_generated_file_path(job_id),
        }

    elif disambiguation_type == "update_item":
        # User selected which item to update
        update_params = pending.get("update_params", {})
        result = tools.update_line_item(
            job_id=job_id,
            item_identifier=str(selected_item["id"]),
            new_quantity=update_params.get("new_quantity"),
            new_unit_price=_sanitize_price(update_params.get("new_unit_price")),
            new_item_name=update_params.get("new_item_name"),
            new_item_code=update_params.get("new_item_code")
        )

        if result.get("success"):
            changes = []
            if update_params.get("new_quantity"):
                changes.append(f"quantity → {update_params['new_quantity']}")
            if update_params.get("new_unit_price"):
                changes.append(f"price → {_sanitize_price(update_params['new_unit_price'])} AED")
            if update_params.get("new_item_name"):
                changes.append(f"name → {update_params['new_item_name']}")
            if update_params.get("new_item_code"):
                changes.append(f"code → {update_params['new_item_code']}")

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

        return {
            "messages": [AIMessage(content=response_msg)],
            "last_mentioned_job_id": job_id,
            "last_action": "update_item",
            "pending_disambiguation": None,
            "generated_file": _get_generated_file_path(job_id),
        }

    # Unknown disambiguation type
    return {
        "messages": [AIMessage(content="Something went wrong. Please try your request again.")],
        "last_mentioned_job_id": job_id,
        "pending_disambiguation": None,
    }


def _handle_add_item_custom_confirm(pending: dict, job_id: str) -> dict:
    """Handle user confirming they want to add a custom item (not in catalog)."""
    item_name = pending.get("item_name", "")
    item_code = pending.get("item_code", "")
    quantity = pending.get("quantity", 1)
    unit_price = _sanitize_price(pending.get("unit_price"))
    vendor_email = pending.get("vendor_email")

    result = tools.add_line_item_to_job(
        job_id=job_id,
        item_name=item_name,
        item_code=item_code,
        quantity=quantity,
        unit_price=unit_price,
        vendor_email=vendor_email
    )

    if result.get("success"):
        price_display = f"{result.get('unit_price')} AED" if result.get('unit_price') else "Pending quote"
        response_msg = (
            f"✅ Added custom item **{item_name}** to job **{job_id}**\n\n"
            f"- Item Code: {item_code or 'N/A'}\n"
            f"- Quantity: {quantity}\n"
            f"- Unit Price: {price_display}\n"
            f"- Status: {result.get('price_status')}\n\n"
            f"The costing sheet has been regenerated."
        )
    else:
        response_msg = f"❌ Failed to add item: {result.get('error', 'Unknown error')}"

    return {
        "messages": [AIMessage(content=response_msg)],
        "last_mentioned_job_id": job_id,
        "last_action": "add_item",
        "pending_disambiguation": None,
        "generated_file": _get_generated_file_path(job_id),
    }


@trace_agent
def edit_job_node(state: AgentState):
    """
    Handles job editing operations based on user requests.
    Supports disambiguation for multiple matches and product search for adding items.
    """
    user_message = state["messages"][-1].content if state.get("messages") else ""

    # Check if disambiguation is pending
    pending = state.get("pending_disambiguation")
    if pending and pending.get("agent") == "edit_job":
        disambiguation_type = pending.get("disambiguation_type")
        job_id = pending.get("job_id")

        # Check if user wants to confirm adding a custom item
        if disambiguation_type == "add_item_not_found":
            user_lower = user_message.strip().lower()
            if user_lower in ("yes", "y", "ok", "sure", "go ahead", "add it", "proceed"):
                return _handle_add_item_custom_confirm(pending, job_id)
            else:
                return {
                    "messages": [AIMessage(content="Got it, the item was not added. Let me know if you'd like to search for a different product or try a different item code.")],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": None,
                }

        # Handle item selection from disambiguation list
        # First check if the LLM extracted a new operation — if so, don't treat as disambiguation
        params = _extract_edit_parameters(user_message, state)
        if params and params.get("operation"):
            # User started a new operation, clear disambiguation and proceed normally
            pending = None
        else:
            return _handle_disambiguation_response(user_message, pending, job_id)

    # Extract parameters (if not already extracted above)
    if pending is None or not pending:
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
    response_msg = ""

    if operation == "add_item":
        item_name = params.get("item_name")
        if not item_name:
            response_msg = "Please specify the item name or item code to add."
        else:
            # Search the product catalog first
            search_result = tools.search_products_for_agent(item_name)
            item_code = params.get("item_code", "")
            quantity = params.get("quantity", 1)
            unit_price = _sanitize_price(params.get("unit_price"))
            vendor_email = params.get("vendor_email")

            # Also search by item_code if provided and different from item_name
            if item_code and item_code != item_name and not search_result.get("found"):
                search_result = tools.search_products_for_agent(item_code)

            if search_result.get("found"):
                results = search_result["results"]

                if len(results) == 1:
                    # Single match — add it directly using catalog details
                    product = results[0]
                    final_price = unit_price or product.get("unit_cost")

                    result = tools.add_line_item_to_job(
                        job_id=job_id,
                        item_name=product.get("item_name", item_name),
                        item_code=product.get("item_code", item_code),
                        quantity=quantity,
                        unit_price=final_price,
                        vendor_email=product.get("vendor_email") or vendor_email
                    )

                    if result.get("success"):
                        price_display = f"{result.get('unit_price')} AED" if result.get('unit_price') else "Pending quote"
                        response_msg = (
                            f"✅ Added **{product.get('item_name')}** to job **{job_id}**\n\n"
                            f"- Item Code: {product.get('item_code') or 'N/A'}\n"
                            f"- Quantity: {quantity}\n"
                            f"- Unit Price: {price_display}\n"
                            f"- Status: {result.get('price_status')}\n\n"
                            f"The costing sheet has been regenerated."
                        )
                    else:
                        response_msg = f"❌ Failed to add item: {result.get('error', 'Unknown error')}"

                else:
                    # Multiple matches — ask user to pick
                    def _truncate_name(name, max_len=80):
                        return name[:max_len] + "..." if len(name) > max_len else name

                    options = "\n".join([
                        f"  {i+1}. **{_truncate_name(p['item_name'])}** (Code: {p.get('item_code') or 'N/A'}, "
                        f"Price: {p.get('unit_cost') or 'N/A'} AED)"
                        for i, p in enumerate(results[:10])
                    ])

                    response_msg = (
                        f"I found **{len(results)} products** matching '**{item_name}**':\n\n"
                        f"{options}\n\n"
                        f"Which product would you like to add to job **{job_id}**? "
                        f"Reply with the number (1-{min(len(results), 10)})."
                    )

                    return {
                        "messages": [AIMessage(content=response_msg)],
                        "last_mentioned_job_id": job_id,
                        "pending_disambiguation": {
                            "agent": "edit_job",
                            "disambiguation_type": "add_item_search",
                            "items": results[:10],
                            "job_id": job_id,
                            "quantity": quantity,
                            "unit_price": unit_price,
                        },
                    }

            else:
                # No product found — inform user and offer to add as custom item
                response_msg = (
                    f"⚠️ No products found matching '**{item_name}**' in the catalog.\n\n"
                    f"💡 **Tip:** Many products only have item codes (e.g., `ABC-123`) without "
                    f"descriptive names. Try searching by item code if you have one.\n\n"
                    f"Would you like me to add '**{item_name}**' as a custom item to job **{job_id}** anyway? "
                    f"Reply **yes** to confirm or provide a different item name/code to search again."
                )

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "agent": "edit_job",
                        "disambiguation_type": "add_item_not_found",
                        "job_id": job_id,
                        "item_name": item_name,
                        "item_code": item_code,
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "vendor_email": vendor_email,
                    },
                }

    elif operation == "remove_item":
        item_identifier = params.get("item_identifier")
        if not item_identifier:
            response_msg = "Please specify which item to remove (by name or item number)."
        else:
            # Use disambiguation-aware matching
            match_result = tools.find_matching_line_items(job_id, item_identifier)

            if match_result["match"] == "multiple":
                items = match_result["items"]
                options = "\n".join([
                    f"  {i+1}. **{item['item_name']}** (ID: {item['id']}, "
                    f"Code: {item.get('item_code') or 'N/A'}, Qty: {item.get('quantity', 'N/A')})"
                    for i, item in enumerate(items)
                ])
                response_msg = (
                    f"I found **{len(items)} items** matching '**{item_identifier}**' in job **{job_id}**:\n\n"
                    f"{options}\n\n"
                    f"Which item would you like to remove? Reply with the number (1-{len(items)})."
                )
                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "agent": "edit_job",
                        "disambiguation_type": "remove_item",
                        "items": items,
                        "job_id": job_id,
                    },
                }

            elif match_result["match"] == "exact":
                item = match_result["items"][0]
                result = tools.remove_line_item_from_job(
                    job_id=job_id,
                    item_identifier=str(item["id"])
                )

                if result.get("success"):
                    response_msg = (
                        f"✅ Removed **{item['item_name']}** from job **{job_id}**\n\n"
                        f"The costing sheet has been updated."
                    )
                else:
                    response_msg = f"❌ Failed to remove item: {result.get('error', 'Unknown error')}"

            else:
                response_msg = f"❌ No item matching '**{item_identifier}**' found in job **{job_id}**."

    elif operation == "update_item":
        item_identifier = params.get("item_identifier")
        if not item_identifier:
            response_msg = "Please specify which item to update."
        else:
            # Use disambiguation-aware matching
            match_result = tools.find_matching_line_items(job_id, item_identifier)

            new_unit_price = _sanitize_price(params.get("new_unit_price"))
            update_params = {
                "new_quantity": params.get("new_quantity"),
                "new_unit_price": new_unit_price,
                "new_item_name": params.get("new_item_name"),
                "new_item_code": params.get("new_item_code"),
            }

            if match_result["match"] == "multiple":
                items = match_result["items"]
                options = "\n".join([
                    f"  {i+1}. **{item['item_name']}** (ID: {item['id']}, "
                    f"Code: {item.get('item_code') or 'N/A'}, "
                    f"Price: {item.get('unit_price') or 'N/A'} AED, Qty: {item.get('quantity', 'N/A')})"
                    for i, item in enumerate(items)
                ])
                response_msg = (
                    f"I found **{len(items)} items** matching '**{item_identifier}**' in job **{job_id}**:\n\n"
                    f"{options}\n\n"
                    f"Which item would you like to update? Reply with the number (1-{len(items)})."
                )
                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "agent": "edit_job",
                        "disambiguation_type": "update_item",
                        "items": items,
                        "job_id": job_id,
                        "update_params": update_params,
                    },
                }

            elif match_result["match"] == "exact":
                item = match_result["items"][0]
                result = tools.update_line_item(
                    job_id=job_id,
                    item_identifier=str(item["id"]),
                    new_quantity=update_params.get("new_quantity"),
                    new_unit_price=update_params.get("new_unit_price"),
                    new_item_name=update_params.get("new_item_name"),
                    new_item_code=update_params.get("new_item_code")
                )

                if result.get("success"):
                    changes = []
                    if update_params.get("new_quantity"):
                        changes.append(f"quantity → {update_params['new_quantity']}")
                    if update_params.get("new_unit_price"):
                        changes.append(f"price → {update_params['new_unit_price']} AED")
                    if update_params.get("new_item_name"):
                        changes.append(f"name → {update_params['new_item_name']}")
                    if update_params.get("new_item_code"):
                        changes.append(f"code → {update_params['new_item_code']}")

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

            else:
                response_msg = f"❌ No item matching '**{item_identifier}**' found in job **{job_id}**."

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

    elif operation == "search_product":
        search_query = params.get("search_query", "")
        if not search_query:
            response_msg = "Please provide a description to search for (e.g., 'hydraulic pump', 'marine engine')."
        else:
            search_result = tools.search_products_for_agent(search_query)

            if search_result.get("found"):
                results = search_result["results"]
                options = "\n".join([
                    f"  {i+1}. **{p['item_name']}** (Code: {p.get('item_code') or 'N/A'}, "
                    f"Price: {p.get('unit_cost') or 'N/A'} AED)"
                    for i, p in enumerate(results[:10])
                ])

                response_msg = (
                    f"🔍 Found **{len(results)} products** matching '**{search_query}**':\n\n"
                    f"{options}\n\n"
                    f"To add one of these to job **{job_id}**, reply with the number (1-{min(len(results), 10)})."
                )

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "agent": "edit_job",
                        "disambiguation_type": "add_item_search",
                        "items": results[:10],
                        "job_id": job_id,
                        "quantity": 1,
                        "unit_price": None,
                    },
                }
            else:
                response_msg = f"No products found matching '**{search_query}**'. Try a different description or item code."

    else:
        response_msg = f"I don't understand the operation '{operation}'. I can help with: add_item, remove_item, update_item, update_description, or search_product."

    # Update state with context
    return {
        "messages": [AIMessage(content=response_msg)],
        "last_mentioned_job_id": job_id,
        "last_action": operation,
        "pending_disambiguation": None,
        "generated_file": _get_generated_file_path(job_id),
    }
