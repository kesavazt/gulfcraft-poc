"""
Pricing Advisor Agent Node

Provides historical pricing intelligence and price comparison capabilities.
Supports searching products by description using hybrid search.
"""

import json
import re
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from core.state import AgentState
from utils import tools
from utils.llm import llm
from utils.prompts import PRICING_ADVISOR_AGENT_SYSTEM_PROMPT, PRICING_ADVISOR_EXTRACTION_PROMPT
from utils.langfuse_tracing import trace_agent


def _extract_pricing_parameters(user_message: str, state: AgentState) -> dict:
    """Extract pricing query parameters from user message using LLM."""
    prompt = PRICING_ADVISOR_EXTRACTION_PROMPT.format(
        user_message=user_message
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
        return params
    except Exception as e:
        print(f"[PricingAdvisorAgent] Extraction error: {e}")
        return {}


def _truncate(text: str, max_len: int = 80) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def _format_cost(value) -> str:
    if value is not None:
        return f"{value:,.2f} AED"
    return "N/A"


def _sanitize_price(value) -> float | None:
    if value is None:
        return None
    try:
        cleaned = re.sub(r'[^\d.]', '', str(value))
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def _build_history_table(history: list) -> str:
    """Format price history as a markdown table."""
    rows = history[:10]
    table = f"**Price History** ({len(history)} records):\n\n"
    table += "| # | Item Name | Item Code | Unit Price | Qty | Job | Vendor | Date |\n"
    table += "|---|-----------|-----------|------------|-----|-----|--------|------|\n"
    for i, r in enumerate(rows, 1):
        name = (r.get('item_name') or 'Unknown')[:40]
        code = r.get('item_code') or '-'
        price = f"{r['unit_price']:,.2f} AED" if r.get('unit_price') is not None else 'N/A'
        qty = r.get('quantity') or '-'
        job = r.get('job_id') or '-'
        vendor = (r.get('vendor_email') or '-').split('@')[0]
        date = (r.get('date') or '-')[:10]
        table += f"| {i} | {name} | {code} | {price} | {qty} | {job} | {vendor} | {date} |\n"
    return table


def _search_products_for_name(item_name: str) -> list:
    """Search products by description and return results."""
    search_result = tools.search_products_by_description(item_name, limit=10)
    if search_result.get("found"):
        return search_result["results"]
    return []


@trace_agent
def pricing_advisor_node(state: AgentState):
    """
    Provides pricing intelligence and historical data.
    Supports product search by description for price lookups.
    """
    user_message = state["messages"][-1].content if state.get("messages") else ""

    # Handle disambiguation response (user selecting from search results or providing search term)
    pending = state.get("pending_disambiguation")
    if pending and pending.get("agent") == "pricing_advisor":
        # Handle case where we're waiting for user to provide search term
        if pending.get("query_type") == "product_search_awaiting_input":
            search_query = user_message.strip()
            if not search_query:
                return {
                    "messages": [AIMessage(content="Please provide a product description to search for.")],
                    "pending_disambiguation": pending
                }

            # Execute product search
            search_result = tools.search_products_by_description(search_query, limit=10)

            if search_result.get("found"):
                results = search_result["results"]
                response_msg = f"🔎 Found **{len(results)} products** matching '**{search_query}**'. Please select one to see detailed pricing."

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "pending_disambiguation": {
                        "agent": "pricing_advisor",
                        "items": results[:10],
                        "last_search_query": search_query  # Store for refinement/pagination
                    },
                    "last_action": "product_search",
                }
            else:
                return {
                    "messages": [AIMessage(content=f"No products found matching '**{search_query}**'. Try a different description or item code.")],
                    "pending_disambiguation": None,
                    "last_action": "product_search"
                }

        # Handle case where user is selecting from search results OR refining search
        selection = user_message.strip()
        items = pending.get("items", [])
        selected_item = None

        # Check if user is refining their search instead of selecting
        user_lower = selection.lower()
        prev_query = pending.get("last_search_query", "")

        # Detect refinement patterns: "show me more", brand names, additional criteria
        is_show_more = "show" in user_lower and "more" in user_lower
        is_refinement = (
            is_show_more or
            (not selection.isdigit() and len(selection.split()) >= 1 and len(selection) > 3)
        )

        # If user is refining the search, execute new search
        if is_refinement and not selection.isdigit():
            if is_show_more:
                # Increase limit to show more results
                search_result = tools.search_products_by_description(prev_query, limit=20)
                response_msg_prefix = f"🔎 Showing **more results** for '**{prev_query}**'."
            else:
                # User is refining with additional criteria (e.g., brand name)
                refined_query = selection
                search_result = tools.search_products_by_description(refined_query, limit=10)
                response_msg_prefix = f"🔎 Found products matching '**{refined_query}**'."

            if search_result.get("found"):
                results = search_result["results"]
                response_msg = f"{response_msg_prefix} Please select one to see detailed pricing."

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "pending_disambiguation": {
                        "agent": "pricing_advisor",
                        "items": results[:20],  # Show more results
                        "last_search_query": refined_query if not is_show_more else prev_query
                    },
                    "last_action": "product_search",
                }
            else:
                return {
                    "messages": [AIMessage(content=f"No products found matching your search. Please try again or select from the original list (1-{len(items)}).")],
                    "pending_disambiguation": pending,
                }

        # Handle numeric selection
        if selection.isdigit():
            idx = int(selection) - 1
            if 0 <= idx < len(items):
                selected_item = items[idx]

        if not selected_item:
            return {
                "messages": [AIMessage(content=f"Please select a valid number (1-{len(items)}) from the list above, or refine your search with additional criteria.")],
                "pending_disambiguation": pending,
            }

        # Show pricing info for the selected product
        item_code = selected_item.get("item_code", "")
        item_name = selected_item.get("item_name", "")
        unit_cost = selected_item.get("unit_cost")

        # Get current price from Products table
        current_product = tools.get_current_product_price(item_code) if item_code else {"found": False}
        current_price = _format_cost(current_product.get("unit_cost")) if current_product.get("found") else _format_cost(unit_cost)

        response_msg = f"📊 **Product Pricing: {_truncate(item_name)}**\n\n"
        response_msg += f"- **Item Code:** {item_code or 'N/A'}\n"
        response_msg += f"- **Current Price (Products Table):** {current_price}\n\n"

        # Try to get historical pricing
        history = tools.get_item_price_history(item_code, item_name=item_name, limit=10)
        avg_data = tools.get_average_item_price(item_code, item_name=item_name)

        if history:
            response_msg += _build_history_table(history)

        if avg_data and not avg_data.get("error"):
            response_msg += (
                f"\n**Statistics** (from {avg_data.get('sample_count')} purchases):\n"
                f"- Average: {_format_cost(avg_data.get('average_price'))}\n"
                f"- Range: {_format_cost(avg_data.get('min_price'))} - {_format_cost(avg_data.get('max_price'))}\n"
            )
        elif not history:
            response_msg += "No historical pricing data found for this item.\n"

        return {
            "messages": [AIMessage(content=response_msg)],
            "pending_disambiguation": None,
            "last_action": "product_search",
            "last_viewed_product": {
                "item_code": item_code,
                "item_name": item_name,
                "unit_price": unit_cost
            }
        }

    # Extract parameters
    params = _extract_pricing_parameters(user_message, state)

    if not params or not params.get("query_type"):
        return {
            "messages": [AIMessage(content=
                "I can provide pricing intelligence! I can help you:\n\n"
                "📊 **View price history** - See past prices for specific items\n"
                "📈 **Calculate averages** - Get average, min, and max prices\n"
                "🔍 **Compare prices** - Check if current quotes are reasonable\n"
                "🔎 **Search products** - Find products by description and see their pricing\n\n"
                "Examples:\n"
                "- 'What did we pay for hydraulic pumps in the past?'\n"
                "- 'What's the average price for item code XYZ-123?'\n"
                "- 'Is 1500 AED a good price for this anchor winch?'\n"
                "- 'Search for marine engine pricing'\n"
                "- 'How much does a bilge pump cost?'"
            )]
        }

    query_type = params.get("query_type")
    item_code = params.get("item_code")
    item_name = params.get("item_name")
    search_query = params.get("search_query")

    response_msg = ""

    if query_type == "product_search":
        query_text = search_query or item_name or ""
        if not query_text:
            # Ask for search term and set pending state to capture response
            return {
                "messages": [AIMessage(content="Please describe the product you want to search for (e.g., 'hydraulic pump', 'marine engine', 'anchor winch').")],
                "pending_disambiguation": {
                    "agent": "pricing_advisor",
                    "query_type": "product_search_awaiting_input"
                },
                "last_action": "product_search"
            }
        else:
            search_result = tools.search_products_by_description(query_text, limit=10)

            if search_result.get("found"):
                results = search_result["results"]
                response_msg = f"🔎 Found **{len(results)} products** matching '**{query_text}**'. Please select one to see detailed pricing."

                return {
                    "messages": [AIMessage(content=response_msg)],
                    "pending_disambiguation": {
                        "agent": "pricing_advisor",
                        "items": results[:10],
                        "last_search_query": query_text  # Store for refinement/pagination
                    },
                    "last_action": "product_search",
                }
            else:
                response_msg = f"No products found matching '**{query_text}**'. Try a different description."

    elif query_type == "price_history":
        if not item_code and not item_name:
            response_msg = "Please specify an item code or item name to look up price history."
        else:
            # If only name provided, search for matching products
            if not item_code and item_name:
                products = _search_products_for_name(item_name)
                if products:
                    if len(products) == 1:
                        item_code = products[0].get("item_code")
                    else:
                        response_msg = f"🔎 Found **{len(products)} products** matching '**{item_name}**'. Please select one to see its price history."
                        return {
                            "messages": [AIMessage(content=response_msg)],
                            "pending_disambiguation": {
                                "agent": "pricing_advisor",
                                "items": products[:10],
                                "last_search_query": item_name
                            },
                            "last_action": "price_history",
                        }
                else:
                    response_msg = f"No products found matching '{item_name}'. Please provide an item code directly."

            if item_code and not response_msg:
                history = tools.get_item_price_history(item_code, item_name=item_name, limit=10)
                current_product = tools.get_current_product_price(item_code)

                response_msg = f"📊 **Price History for {item_code}**\n\n"

                # Show current price from Products table
                if current_product.get("found"):
                    desc = current_product.get("description") or ""
                    response_msg += f"**Current Price (Products Table):** {_format_cost(current_product.get('unit_cost'))}"
                    if desc:
                        response_msg += f" — {_truncate(desc)}"
                    response_msg += "\n\n"

                if not history:
                    response_msg += (
                        "No historical pricing data found for this item. "
                        "This might be a new item or it hasn't been quoted before."
                    )
                else:
                    response_msg += _build_history_table(history)

                    # Quick stats
                    prices = [r.get('unit_price') for r in history if r.get('unit_price')]
                    if prices:
                        avg_price = sum(prices) / len(prices)
                        response_msg += (
                            f"\n**Quick Stats:**\n"
                            f"- Average: {avg_price:,.2f} AED\n"
                            f"- Range: {min(prices):,.2f} - {max(prices):,.2f} AED"
                        )

    elif query_type == "average_price":
        if not item_code and item_name:
            # Try to resolve name to code via search
            products = _search_products_for_name(item_name)
            if products:
                if len(products) == 1:
                    item_code = products[0].get("item_code")
                else:
                    response_msg = f"🔎 Found **{len(products)} products** matching '**{item_name}**'. Please select one to see its average pricing."
                    return {
                        "messages": [AIMessage(content=response_msg)],
                        "pending_disambiguation": {
                            "agent": "pricing_advisor",
                            "items": products[:10],
                            "last_search_query": item_name
                        },
                        "last_action": "average_price",
                    }

        if not item_code:
            response_msg = "To calculate average price, I need an item code or product description. Please provide one."
        else:
            avg_data = tools.get_average_item_price(item_code, item_name=item_name)
            current_product = tools.get_current_product_price(item_code)

            response_msg = f"📈 **Pricing Statistics for {item_code}**\n\n"

            # Show current price from Products table
            if current_product.get("found"):
                desc = current_product.get("description") or ""
                response_msg += f"**Current Price (Products Table):** {_format_cost(current_product.get('unit_cost'))}"
                if desc:
                    response_msg += f" — {_truncate(desc)}"
                response_msg += "\n\n"

            if avg_data.get("error"):
                response_msg += (
                    f"❌ {avg_data.get('error')}\n\n"
                    f"This item hasn't been purchased before or doesn't exist in our records."
                )
            else:
                response_msg += (
                    f"Based on **{avg_data.get('sample_count')} historical purchases**:\n\n"
                    f"- **Average Price:** {_format_cost(avg_data.get('average_price'))}\n"
                    f"- **Lowest Price:** {_format_cost(avg_data.get('min_price'))}\n"
                    f"- **Highest Price:** {_format_cost(avg_data.get('max_price'))}\n\n"
                    f"💡 Use these stats to evaluate vendor quotes!"
                )

    elif query_type == "price_comparison":
        if not item_code and item_name:
            # Try to resolve name to code via search
            products = _search_products_for_name(item_name)
            if products:
                if len(products) == 1:
                    item_code = products[0].get("item_code")
                else:
                    response_msg = f"🔎 Found **{len(products)} products** matching '**{item_name}**'. Please select one to compare pricing."
                    return {
                        "messages": [AIMessage(content=response_msg)],
                        "pending_disambiguation": {
                            "agent": "pricing_advisor",
                            "items": products[:10],
                            "last_search_query": item_name
                        },
                        "last_action": "price_comparison",
                    }

        if not item_code:
            response_msg = "To compare prices, I need an item code or product description. Please provide one."
        else:
            current_price = _sanitize_price(params.get("current_price"))
            if current_price is None:
                response_msg = "Please specify the price you want to compare (e.g., 'Is 1500 AED reasonable?')"
            else:
                avg_data = tools.get_average_item_price(item_code, item_name=item_name)
                current_product = tools.get_current_product_price(item_code)

                if avg_data.get("error"):
                    response_msg = f"🔍 **Price Comparison for {item_code}**\n\n"
                    if current_product.get("found"):
                        response_msg += f"**Current Price (Products Table):** {_format_cost(current_product.get('unit_cost'))}\n"
                    response_msg += (
                        f"Current quote: **{current_price:,.2f} AED**\n\n"
                        f"⚠️ No historical data available for comparison. "
                        f"This might be a new item or first-time purchase."
                    )
                else:
                    avg_price = avg_data.get('average_price', 0)
                    min_price = avg_data.get('min_price', 0)
                    max_price = avg_data.get('max_price', 0)

                    # Calculate percentage difference
                    if avg_price > 0:
                        diff_pct = ((current_price - avg_price) / avg_price) * 100
                    else:
                        diff_pct = 0

                    # Determine assessment
                    if diff_pct > 20:
                        assessment = "⚠️ **Above Average** - This price is significantly higher than historical average"
                    elif diff_pct < -20:
                        assessment = "✅ **Great Deal** - This price is significantly lower than historical average"
                    elif abs(diff_pct) <= 10:
                        assessment = "✅ **Fair Price** - This price is in line with historical average"
                    else:
                        assessment = "ℹ️ **Slightly Different** - Minor variance from historical average"

                    response_msg = (
                        f"🔍 **Price Comparison for {item_code}**\n\n"
                        f"**Current Quote:** {current_price} AED\n"
                        f"**Historical Average:** {avg_price:.2f} AED\n"
                        f"**Difference:** {diff_pct:+.1f}%\n\n"
                        f"{assessment}\n\n"
                        f"**Historical Range:** {min_price:.2f} - {max_price:.2f} AED\n"
                        f"**Sample Size:** {avg_data.get('sample_count')} purchases\n\n"
                        f"💡 Consider negotiating if the price is significantly above average!"
                    )

    else:
        response_msg = (
            f"I don't understand the query type '{query_type}'. "
            f"I can help with: price_history, average_price, price_comparison, or product_search."
        )

    return {
        "messages": [AIMessage(content=response_msg)],
        "last_action": query_type
    }
