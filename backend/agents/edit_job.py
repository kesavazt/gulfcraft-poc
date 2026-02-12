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
    """Return the costing sheet filename if it exists on disk."""
    filename = f"costing_{job_id}.xlsx"
    file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)
    return filename if os.path.exists(file_path) else None


def _extract_edit_parameters(user_message: str, state: AgentState) -> dict:
    """Extract edit operation parameters from user message using LLM."""
    last_job_id = state.get("last_mentioned_job_id") or state.get("job_id") or "Not specified"
    context = {
        "awaiting_quotes": state.get("awaiting_quotes", False),
        "last_action": state.get("last_action")
    }

    print(f"[DEBUG extraction] user_message: {user_message!r}, last_job_id: {last_job_id}, context: {context}")

    prompt = EDIT_JOB_EXTRACTION_PROMPT.format(
        user_message=user_message,
        last_job_id=last_job_id,
        context=json.dumps(context)
    )

    try:
        response = llm.invoke([{"role": "user", "content": prompt}])
        content = response.content
        print(f"[DEBUG extraction] LLM raw response: {content!r}")

        # Extract JSON from markdown code blocks if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        params = json.loads(content)
        print(f"[DEBUG extraction] Parsed params: {params}")

        # Normalize field name: LLM may return 'operation_type' but code expects 'operation'
        if 'operation_type' in params and 'operation' not in params:
            params['operation'] = params.pop('operation_type')
            print(f"[DEBUG extraction] Normalized 'operation_type' to 'operation': {params.get('operation')}")

        # Use context if job_id not provided
        if not params.get("job_id") and last_job_id != "Not specified":
            params["job_id"] = last_job_id
            print(f"[DEBUG extraction] Added job_id from context: {last_job_id}")

        print(f"[DEBUG extraction] Final params: {params}")
        return params
    except Exception as e:
        print(f"[EditJobAgent] Extraction error: {e}")
        print(f"[DEBUG extraction] Error details - content was: {content if 'content' in locals() else 'N/A'}")
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


def _match_item_with_llm(user_message: str, items: list) -> dict:
    """Use LLM to match user's description to one of the items in the list."""
    items_description = "\n".join([
        f"{i+1}. {item['item_name']} (Code: {item.get('item_code') or 'N/A'})"
        for i, item in enumerate(items)
    ])

    prompt = f"""The user is trying to select an item from this list:

{items_description}

Their message is: "{user_message}"

If the message is a number (1, 2, 3, etc.), return that number.
If the message describes an item from the list, return the number (1-{len(items)}) that best matches.
If you cannot determine a match, return "NONE".

Return ONLY the number or "NONE", nothing else."""

    try:
        response = llm.invoke([{"role": "user", "content": prompt}])
        match_result = response.content.strip().upper()
        print(f"[DEBUG LLM match] LLM response: {match_result!r}")

        if match_result == "NONE":
            return None

        if match_result.isdigit():
            idx = int(match_result) - 1
            if 0 <= idx < len(items):
                return items[idx]

        return None
    except Exception as e:
        print(f"[DEBUG LLM match] Error: {e}")
        return None


def _handle_disambiguation_response(user_message: str, pending: dict, job_id: str) -> dict:
    """Handle user's selection from a disambiguation prompt."""
    print(f"[DEBUG disambiguation] user_message: {user_message!r}, pending: {pending}, job_id: {job_id}")
    selection = user_message.strip()
    items = pending.get("items", [])
    selected_item = None
    print(f"[DEBUG disambiguation] selection: {selection!r}, items count: {len(items)}")

    # Try numeric selection (1, 2, 3...)
    if selection.isdigit():
        idx = int(selection) - 1
        print(f"[DEBUG disambiguation] Numeric selection detected, idx: {idx}")
        if 0 <= idx < len(items):
            selected_item = items[idx]
            print(f"[DEBUG disambiguation] Selected item by index: {selected_item}")

    # Try direct ID match
    if not selected_item:
        print(f"[DEBUG disambiguation] Trying direct ID match")
        for item in items:
            if str(item.get("id", "")) == selection:
                selected_item = item
                print(f"[DEBUG disambiguation] Selected item by ID: {selected_item}")
                break

    # Try LLM-based matching if user provided a description
    if not selected_item:
        print(f"[DEBUG disambiguation] Trying LLM-based item matching")
        selected_item = _match_item_with_llm(user_message, items)
        if selected_item:
            print(f"[DEBUG disambiguation] LLM matched item: {selected_item}")

    if not selected_item:
        print(f"[DEBUG disambiguation] No valid selection found, asking user to try again")
        return {
            "messages": [AIMessage(content=f"I couldn't identify which item you meant. Please select by number (1-{len(items)}) from the list above.")],
            "last_mentioned_job_id": job_id,
            "pending_disambiguation": pending,
        }

    disambiguation_type = pending.get("disambiguation_type")
    print(f"[DEBUG disambiguation] disambiguation_type: {disambiguation_type}")

    # Legacy "add_item_search" - no longer supported, reset state
    if disambiguation_type == "add_item_search":
        print(f"[DEBUG disambiguation] Legacy add_item_search detected, resetting")
        return {
            "messages": [AIMessage(content=
                "That operation timed out. Let's start fresh.\n\n"
                "What would you like to do with this job?"
            )],
            "last_mentioned_job_id": job_id,
            "pending_disambiguation": None,
        }

    elif disambiguation_type == "remove_item":
        print(f"[DEBUG disambiguation] Handling remove_item for selected_item: {selected_item}")
        # User selected which item to remove
        result = tools.remove_line_item_from_job(
            job_id=job_id,
            item_identifier=str(selected_item["id"])
        )
        print(f"[DEBUG disambiguation] Remove result: {result}")

        if result.get("success"):
            response_msg = (
                f"✅ Removed **{selected_item['item_name']}** from job **{job_id}**\n\n"
                f"The costing sheet has been updated."
            )
        else:
            response_msg = f"❌ Failed to remove item: {result.get('error', 'Unknown error')}"

        print(f"[DEBUG disambiguation] Returning from remove_item disambiguation")
        return {
            "messages": [AIMessage(content=response_msg)],
            "last_mentioned_job_id": job_id,
            "last_action": "remove_item",
            "pending_disambiguation": None,
            "generated_file": result.get("file_path"),
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
            "generated_file": result.get("file_path"),
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
        "generated_file": result.get("file_path"),
    }


@trace_agent
def edit_job_node(state: AgentState):
    """
    Handles job editing operations based on user requests.
    Supports interactive job selection, product search, quantity input, and confirmation.
    """
    user_message = state["messages"][-1].content if state.get("messages") else ""
    print(f"[DEBUG edit_job_node] user_message: {user_message!r}")

    # Check if disambiguation/interactive flow is pending
    pending = state.get("pending_disambiguation")
    print(f"[DEBUG edit_job_node] pending_disambiguation: {pending}")
    if pending and pending.get("agent") == "edit_job":
        disambiguation_type = pending.get("disambiguation_type")
        job_id = pending.get("job_id")

        # Handle job selection method (list jobs or enter ID)
        if disambiguation_type == "job_selection_method":
            user_lower = user_message.strip().lower()
            if "list" in user_lower or "show" in user_lower or "1" in user_lower:
                # Show list of recent jobs
                recent_jobs = tools.list_recent_jobs(limit=15)
                if not recent_jobs:
                    return {
                        "messages": [AIMessage(content="No jobs found in the system.")],
                        "pending_disambiguation": None,
                    }

                job_list = "\n".join([
                    f"  {i+1}. **{job['job_id']}** - {job['description']}\n"
                    f"     Status: {job['status']} | Items: {job['line_items_count']} | Created: {job['created_at']}"
                    for i, job in enumerate(recent_jobs)
                ])

                return {
                    "messages": [AIMessage(content=
                        f"📋 **Recent Jobs:**\n\n{job_list}\n\n"
                        f"Which job would you like to edit? Reply with the number (1-{len(recent_jobs)}) or job ID."
                    )],
                    "pending_disambiguation": {
                        "agent": "edit_job",
                        "disambiguation_type": "job_list_selection",
                        "jobs": recent_jobs,
                    },
                }
            elif "enter" in user_lower or "know" in user_lower or "2" in user_lower or user_lower.startswith("cost-"):
                # User wants to enter job ID or has entered it
                # Try to extract job ID from message
                if user_lower.startswith("cost-"):
                    job_id = user_message.strip().upper()
                    return {
                        "messages": [AIMessage(content=
                            f"Great! Working with job **{job_id}**.\n\n"
                            f"What would you like to do?\n"
                            f"1. Edit existing line items (quantity, price, etc.)\n"
                            f"2. Search for a product to add to this job"
                        )],
                        "last_mentioned_job_id": job_id,
                        "pending_disambiguation": {
                            "agent": "edit_job",
                            "disambiguation_type": "action_selection",
                            "job_id": job_id,
                        },
                    }
                else:
                    return {
                        "messages": [AIMessage(content="Please enter the job ID (e.g., COST-00123456):")],
                        "pending_disambiguation": {
                            "agent": "edit_job",
                            "disambiguation_type": "job_id_input",
                        },
                    }
            else:
                return {
                    "messages": [AIMessage(content=
                        "Please choose one of these options:\n"
                        "1. Show me a list of recent jobs\n"
                        "2. I know the job ID"
                    )],
                    "pending_disambiguation": pending,
                }

        # Handle job ID input
        elif disambiguation_type == "job_id_input":
            job_id = user_message.strip().upper()
            if not job_id.startswith("COST-"):
                return {
                    "messages": [AIMessage(content="Invalid job ID format. Job IDs should start with 'COST-'. Please try again:")],
                    "pending_disambiguation": pending,
                }

            return {
                "messages": [AIMessage(content=
                    f"Great! Working with job **{job_id}**.\n\n"
                    f"What would you like to do?\n"
                    f"1. Edit existing line items (quantity, price, etc.)\n"
                    f"2. Search for a product to add to this job"
                )],
                "last_mentioned_job_id": job_id,
                "pending_disambiguation": {
                    "agent": "edit_job",
                    "disambiguation_type": "action_selection",
                    "job_id": job_id,
                },
            }

        # Handle job selection from list
        elif disambiguation_type == "job_list_selection":
            jobs = pending.get("jobs", [])
            selection = user_message.strip()

            # Try numeric selection
            selected_job = None
            if selection.isdigit():
                idx = int(selection) - 1
                if 0 <= idx < len(jobs):
                    selected_job = jobs[idx]

            # Try job ID match
            if not selected_job:
                for job in jobs:
                    if job["job_id"].upper() == selection.upper():
                        selected_job = job
                        break

            if not selected_job:
                return {
                    "messages": [AIMessage(content=f"Please select a valid job number (1-{len(jobs)}) or enter a valid job ID.")],
                    "pending_disambiguation": pending,
                }

            job_id = selected_job["job_id"]
            return {
                "messages": [AIMessage(content=
                    f"Great! Working with job **{job_id}**.\n\n"
                    f"What would you like to do?\n"
                    f"1. Edit existing line items (quantity, price, etc.)\n"
                    f"2. Search for a product to add to this job"
                )],
                "last_mentioned_job_id": job_id,
                "pending_disambiguation": {
                    "agent": "edit_job",
                    "disambiguation_type": "action_selection",
                    "job_id": job_id,
                },
            }

        # Handle action selection (edit or add)
        elif disambiguation_type == "action_selection":
            user_lower = user_message.strip().lower()
            if "1" in user_lower or "edit" in user_lower:
                # User wants to edit existing items - switch to regular edit flow
                return {
                    "messages": [AIMessage(content=
                        f"Which item would you like to update? Please provide the item name, code, or tell me what to change.\n\n"
                        f"Examples:\n"
                        f"- 'Update the hydraulic pump quantity to 5'\n"
                        f"- 'Change cable price to 850 AED'\n"
                        f"- 'Remove the anchor winch'"
                    )],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": None,  # Clear to allow normal operation extraction
                }
            elif "2" in user_lower or "search" in user_lower or "add" in user_lower:
                # User wants to search for products
                return {
                    "messages": [AIMessage(content="What product would you like to search for? Enter a description or item code:")],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "agent": "edit_job",
                        "disambiguation_type": "product_search_query",
                        "job_id": job_id,
                    },
                }
            else:
                return {
                    "messages": [AIMessage(content=
                        "Please choose one of these options:\n"
                        "1. Edit existing line items\n"
                        "2. Search for a product to add"
                    )],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": pending,
                }

        # Handle product search query input
        elif disambiguation_type == "product_search_query":
            search_query = user_message.strip()
            search_result = tools.search_products_for_agent(search_query)

            if search_result.get("found"):
                results = search_result["results"][:10]

                def _truncate_name(name, max_len=80):
                    return name[:max_len] + "..." if len(name) > max_len else name

                options = "\n".join([
                    f"  {i+1}. **{_truncate_name(p['item_name'])}**\n"
                    f"     Code: {p.get('item_code') or 'N/A'} | Price: {p.get('unit_cost') or 'N/A'} AED"
                    for i, p in enumerate(results)
                ])

                return {
                    "messages": [AIMessage(content=
                        f"🔍 Found **{len(results)} products** matching '**{search_query}**':\n\n"
                        f"{options}\n\n"
                        f"Which product would you like to add? Reply with the number (1-{len(results)})."
                    )],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "agent": "edit_job",
                        "disambiguation_type": "product_selection",
                        "items": results,
                        "job_id": job_id,
                    },
                }
            else:
                return {
                    "messages": [AIMessage(content=
                        f"⚠️ No products found matching '**{search_query}**'.\n\n"
                        f"💡 Try searching by item code if you have one, or try a different description.\n\n"
                        f"You can also type 'cancel' to go back."
                    )],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": pending,
                }

        # Handle product selection from search results
        elif disambiguation_type == "product_selection":
            items = pending.get("items", [])
            selection = user_message.strip()

            if selection.lower() in ("cancel", "back", "exit"):
                return {
                    "messages": [AIMessage(content="Cancelled. What else can I help you with?")],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": None,
                }

            selected_item = None
            if selection.isdigit():
                idx = int(selection) - 1
                if 0 <= idx < len(items):
                    selected_item = items[idx]

            if not selected_item:
                return {
                    "messages": [AIMessage(content=f"Please select a valid product number (1-{len(items)}).")],
                    "pending_disambiguation": pending,
                }

            # Ask for quantity
            return {
                "messages": [AIMessage(content=
                    f"How many units of **{selected_item['item_name']}** would you like to add?\n"
                    f"(Enter a number, or type 'cancel' to go back)"
                )],
                "last_mentioned_job_id": job_id,
                "pending_disambiguation": {
                    "agent": "edit_job",
                    "disambiguation_type": "quantity_input",
                    "job_id": job_id,
                    "selected_product": selected_item,
                },
            }

        # Handle quantity input
        elif disambiguation_type == "quantity_input":
            if user_message.strip().lower() in ("cancel", "back", "exit"):
                return {
                    "messages": [AIMessage(content="Cancelled. What else can I help you with?")],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": None,
                }

            try:
                quantity = int(user_message.strip())
                if quantity <= 0:
                    return {
                        "messages": [AIMessage(content="Please enter a positive number for quantity:")],
                        "pending_disambiguation": pending,
                    }

                selected_product = pending.get("selected_product")
                unit_price = selected_product.get("unit_cost")
                price_display = f"{unit_price} AED" if unit_price else "Pending quote"

                # Ask for confirmation
                return {
                    "messages": [AIMessage(content=
                        f"Please confirm you want to add:\n\n"
                        f"**Item:** {selected_product['item_name']}\n"
                        f"**Item Code:** {selected_product.get('item_code') or 'N/A'}\n"
                        f"**Quantity:** {quantity}\n"
                        f"**Unit Price:** {price_display}\n\n"
                        f"Reply **yes** to confirm or **no** to cancel."
                    )],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "agent": "edit_job",
                        "disambiguation_type": "add_confirmation",
                        "job_id": job_id,
                        "selected_product": selected_product,
                        "quantity": quantity,
                    },
                }

            except ValueError:
                return {
                    "messages": [AIMessage(content="Please enter a valid number for quantity:")],
                    "pending_disambiguation": pending,
                }

        # Handle add confirmation
        elif disambiguation_type == "add_confirmation":
            user_lower = user_message.strip().lower()
            if user_lower in ("yes", "y", "ok", "sure", "confirm", "go ahead", "add it", "proceed"):
                selected_product = pending.get("selected_product")
                quantity = pending.get("quantity", 1)

                result = tools.add_line_item_to_job(
                    job_id=job_id,
                    item_name=selected_product.get("item_name", ""),
                    item_code=selected_product.get("item_code", ""),
                    quantity=quantity,
                    unit_price=selected_product.get("unit_cost"),
                    vendor_email=selected_product.get("vendor_email")
                )

                if result.get("success"):
                    price_display = f"{result.get('unit_price')} AED" if result.get('unit_price') else "Pending quote"
                    response_msg = (
                        f"✅ Added **{selected_product.get('item_name')}** to job **{job_id}**\n\n"
                        f"- Item Code: {selected_product.get('item_code') or 'N/A'}\n"
                        f"- Quantity: {quantity}\n"
                        f"- Unit Price: {price_display}\n"
                        f"- Status: {result.get('price_status')}\n\n"
                        f"The costing sheet has been regenerated.\n\n"
                        f"Would you like to add another item? (yes/no)"
                    )
                else:
                    response_msg = f"❌ Failed to add item: {result.get('error', 'Unknown error')}"

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "last_action": "add_item",
                    "pending_disambiguation": None,
                    "generated_file": result.get("file_path"),
                }
            else:
                return {
                    "messages": [AIMessage(content="Cancelled. What else can I help you with?")],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": None,
                }

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

        # Handle item selection from disambiguation list (for edit/remove operations)
        # Only allow cancellation during disambiguation, not new operations
        user_lower = user_message.strip().lower()
        print(f"[DEBUG edit_job_node] Checking for cancel keywords, user_lower: {user_lower!r}")
        if user_lower in ("cancel", "back", "exit", "quit", "stop"):
            print(f"[DEBUG edit_job_node] Cancel detected, clearing pending_disambiguation")
            return {
                "messages": [AIMessage(content="Cancelled. What else can I help you with?")],
                "last_mentioned_job_id": job_id,
                "pending_disambiguation": None,
            }

        print(f"[DEBUG edit_job_node] Calling _handle_disambiguation_response")
        return _handle_disambiguation_response(user_message, pending, job_id)

    # Extract parameters (if not already extracted above)
    if pending is None or not pending:
        params = _extract_edit_parameters(user_message, state)
        print(f"[DEBUG edit_job_node] Extracted params: {params}")
    else:
        params = {}
        print(f"[DEBUG edit_job_node] Skipping extraction, pending exists: {pending}")

    # Check if this is a generic "edit job" request without details
    print(f"[DEBUG edit_job_node] Checking params: params={params}, operation={params.get('operation') if params else None}")
    if not params or not params.get("operation"):
        # Check if user is saying they want to edit a job
        user_lower = user_message.lower()
        if any(phrase in user_lower for phrase in ["edit job", "edit a job", "modify job", "change job", "update job"]):
            # Start interactive flow
            return {
                "messages": [AIMessage(content=
                    "I can help you edit a costing job!\n\n"
                    "Would you like to:\n"
                    "1. See a list of recent jobs\n"
                    "2. Enter a job ID directly"
                )],
                "pending_disambiguation": {
                    "agent": "edit_job",
                    "disambiguation_type": "job_selection_method",
                },
            }

        return {
            "messages": [AIMessage(content=
                "I can help you edit a costing job! Please specify:\n"
                "- The job ID (or I can use the last one we discussed)\n"
                "- What you'd like to change (add/remove/update items, change description)\n\n"
                "Examples:\n"
                "- 'Add 50 meters of cable to job COST-00123'\n"
                "- 'Remove the anchor winch from this job'\n"
                "- 'Change the hydraulic pump price to 850 AED'\n\n"
                "Or simply say 'I want to edit a job' for a guided experience."
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

                        return {
                            "messages": [AIMessage(content=response_msg)],
                            "last_mentioned_job_id": job_id,
                            "last_action": "add_item",
                            "pending_disambiguation": None,
                            "generated_file": result.get("file_path"),
                        }
                    else:
                        response_msg = f"❌ Failed to add item: {result.get('error', 'Unknown error')}"

                        return {
                            "messages": [AIMessage(content=response_msg)],
                            "last_mentioned_job_id": job_id,
                            "last_action": "add_item",
                            "pending_disambiguation": None,
                        }

                else:
                    # Multiple matches — ask user to pick (will then ask for quantity and confirmation)
                    def _truncate_name(name, max_len=80):
                        return name[:max_len] + "..." if len(name) > max_len else name

                    options = "\n".join([
                        f"  {i+1}. **{_truncate_name(p['item_name'])}**\n"
                        f"     Code: {p.get('item_code') or 'N/A'} | Price: {p.get('unit_cost') or 'N/A'} AED"
                        for i, p in enumerate(results[:10])
                    ])

                    response_msg = (
                        f"I found **{len(results)} products** matching '**{item_name}**':\n\n"
                        f"{options}\n\n"
                        f"Which product would you like to add? Reply with the number (1-{min(len(results), 10)})."
                    )

                    return {
                        "messages": [AIMessage(content=response_msg)],
                        "last_mentioned_job_id": job_id,
                        "pending_disambiguation": {
                            "agent": "edit_job",
                            "disambiguation_type": "product_selection",
                            "items": results[:10],
                            "job_id": job_id,
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
        print(f"[DEBUG remove_item] item_identifier received: {item_identifier!r}, job_id: {job_id}")

        if not item_identifier:
            response_msg = "Please specify which item to remove (by name or item number)."
        else:
            # If user provided an ID, remove directly
            is_digit = str(item_identifier).isdigit()
            print(f"[DEBUG remove_item] is_digit: {is_digit}")

            if is_digit:
                print(f"[DEBUG remove_item] Removing by ID: {item_identifier}")
                result = tools.remove_line_item_from_job(
                    job_id=job_id,
                    item_identifier=str(item_identifier)
                )
                print(f"[DEBUG remove_item] Removal result: {result}")

                if result.get("success"):
                    response_msg = (
                        f"✅ Removed item from job **{job_id}**\n\n"
                        f"The costing sheet has been updated."
                    )
                else:
                    response_msg = f"❌ Failed to remove item: {result.get('error', 'Unknown error')}"

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "last_action": "remove_item",
                    "pending_disambiguation": None,
                    "generated_file": result.get("file_path"),
                }

            # Name-based search: Get all line items for the job first
            print(f"[DEBUG remove_item] Performing name-based search for: {item_identifier}")
            match_result = tools.find_matching_line_items(job_id, item_identifier)
            print(f"[DEBUG remove_item] match_result: {match_result}")

            # If no matches with basic search, try LLM-based semantic matching on ALL job items
            if match_result["match"] == "none":
                print(f"[DEBUG remove_item] No basic matches, trying LLM semantic matching")
                # Get all items for this job
                job_statuses = tools.get_costing_job_statuses(user_id=state.get("user_id", 1), job_id=job_id)
                if job_statuses and len(job_statuses) > 0:
                    all_items = job_statuses[0].get("line_items", [])
                    if all_items:
                        print(f"[DEBUG remove_item] Found {len(all_items)} total items in job, trying LLM match")
                        # Format items for LLM matching
                        items_for_matching = [{
                            "id": item["id"],
                            "item_name": item["item_name"],
                            "item_code": item.get("item_code"),
                            "quantity": item.get("quantity"),
                            "unit_price": item.get("unit_price"),
                            "price_status": item.get("price_status")
                        } for item in all_items]

                        matched_item = _match_item_with_llm(item_identifier, items_for_matching)
                        if matched_item:
                            print(f"[DEBUG remove_item] LLM found semantic match: {matched_item}")
                            match_result = {"match": "exact", "items": [matched_item]}
                        else:
                            print(f"[DEBUG remove_item] LLM could not find match")

            if match_result["match"] == "none":
                print(f"[DEBUG remove_item] No matches found (after LLM attempt)")
                response_msg = f"❌ No item matching '**{item_identifier}**' found in job **{job_id}**."

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "last_action": "remove_item",
                    "pending_disambiguation": None,
                }

            items = match_result["items"]
            print(f"[DEBUG remove_item] Found {len(items)} matching items")

            # If exact match (single item), remove directly
            if match_result["match"] == "exact" and len(items) == 1:
                print(f"[DEBUG remove_item] Exact match with single item, removing directly")
                result = tools.remove_line_item_from_job(
                    job_id=job_id,
                    item_identifier=str(items[0]["id"])
                )
                print(f"[DEBUG remove_item] Direct removal result: {result}")

                if result.get("success"):
                    response_msg = (
                        f"✅ Removed **{items[0]['item_name']}** from job **{job_id}**\n\n"
                        f"The costing sheet has been updated."
                    )
                else:
                    response_msg = f"❌ Failed to remove item: {result.get('error', 'Unknown error')}"

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "last_action": "remove_item",
                    "pending_disambiguation": None,
                    "generated_file": result.get("file_path"),
                }

            # Multiple matches - show disambiguation list
            print(f"[DEBUG remove_item] Multiple matches, presenting disambiguation")
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
            print(f"[DEBUG remove_item] Setting pending_disambiguation with {len(items)} items")
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

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "last_action": "update_item",
                    "pending_disambiguation": None,
                    "generated_file": result.get("file_path"),
                }

            else:
                response_msg = f"❌ No item matching '**{item_identifier}**' found in job **{job_id}**."

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "last_action": "update_item",
                    "pending_disambiguation": None,
                }

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
            return {
                "messages": [AIMessage(content=response_msg)],
                "last_mentioned_job_id": job_id,
                "last_action": "update_description",
                "pending_disambiguation": None,
                "generated_file": result.get("file_path"),
            }

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
                    f"Which product would you like to add? Reply with the number (1-{min(len(results), 10)})."
                )

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "last_mentioned_job_id": job_id,
                    "pending_disambiguation": {
                        "agent": "edit_job",
                        "disambiguation_type": "product_selection",
                        "items": results[:10],
                        "job_id": job_id,
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
