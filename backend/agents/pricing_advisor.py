"""
Pricing Advisor Agent Node

Provides historical pricing intelligence and price comparison capabilities.
"""

import json
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


@trace_agent
def pricing_advisor_node(state: AgentState):
    """
    Provides pricing intelligence and historical data.
    """
    user_message = state["messages"][-1].content if state.get("messages") else ""

    # Extract parameters
    params = _extract_pricing_parameters(user_message, state)

    if not params or not params.get("query_type"):
        return {
            "messages": [AIMessage(content=
                "I can provide pricing intelligence! I can help you:\n\n"
                "📊 **View price history** - See past prices for specific items\n"
                "📈 **Calculate averages** - Get average, min, and max prices\n"
                "🔍 **Compare prices** - Check if current quotes are reasonable\n\n"
                "Examples:\n"
                "- 'What did we pay for hydraulic pumps in the past?'\n"
                "- 'What's the average price for item code XYZ-123?'\n"
                "- 'Is 1500 AED a good price for this anchor winch?'"
            )]
        }

    query_type = params.get("query_type")
    item_code = params.get("item_code")
    item_name = params.get("item_name")

    response_msg = ""

    if query_type == "price_history":
        if not item_code and not item_name:
            response_msg = "Please specify an item code or item name to look up price history."
        else:
            # If only name provided, try to find item code from recent jobs
            if not item_code:
                response_msg = f"To show price history, I need an item code. Could you provide the item code for '{item_name}'?"
            else:
                history = tools.get_item_price_history(item_code, limit=10)

                if not history:
                    response_msg = (
                        f"📊 **Price History for {item_code}**\n\n"
                        f"No historical pricing data found for this item. "
                        f"This might be a new item or it hasn't been quoted before."
                    )
                else:
                    response_msg = f"📊 **Price History for {item_code}**\n\n"
                    response_msg += f"Found {len(history)} previous purchases:\n\n"

                    for i, record in enumerate(history[:5], 1):
                        response_msg += (
                            f"{i}. **{record.get('unit_price', 'N/A')} AED** - "
                            f"{record.get('item_name', 'Unknown item')}\n"
                            f"   Job: {record.get('job_id')} | "
                            f"Qty: {record.get('quantity', 'N/A')} | "
                            f"Vendor: {record.get('vendor_email', 'Unknown')}\n"
                            f"   Date: {record.get('date', 'Unknown')}\n\n"
                        )

                    if len(history) > 5:
                        response_msg += f"... and {len(history) - 5} more records.\n\n"

                    # Calculate quick stats
                    prices = [r.get('unit_price') for r in history if r.get('unit_price')]
                    if prices:
                        avg_price = sum(prices) / len(prices)
                        response_msg += (
                            f"**Quick Stats:**\n"
                            f"- Average: {avg_price:.2f} AED\n"
                            f"- Range: {min(prices):.2f} - {max(prices):.2f} AED"
                        )

    elif query_type == "average_price":
        if not item_code:
            response_msg = "To calculate average price, I need an item code. Please provide the item code."
        else:
            avg_data = tools.get_average_item_price(item_code)

            if avg_data.get("error"):
                response_msg = (
                    f"📈 **Pricing Statistics for {item_code}**\n\n"
                    f"❌ {avg_data.get('error')}\n\n"
                    f"This item hasn't been purchased before or doesn't exist in our records."
                )
            else:
                response_msg = (
                    f"📈 **Pricing Statistics for {item_code}**\n\n"
                    f"Based on **{avg_data.get('sample_count')} historical purchases**:\n\n"
                    f"- **Average Price:** {avg_data.get('average_price', 'N/A')} AED\n"
                    f"- **Lowest Price:** {avg_data.get('min_price', 'N/A')} AED\n"
                    f"- **Highest Price:** {avg_data.get('max_price', 'N/A')} AED\n\n"
                    f"💡 Use these stats to evaluate vendor quotes!"
                )

    elif query_type == "price_comparison":
        if not item_code:
            response_msg = "To compare prices, I need an item code. Please provide the item code."
        else:
            current_price = params.get("current_price")
            # Sanitize price: strip currency symbols/text and convert to float
            if current_price is not None:
                try:
                    import re
                    cleaned = re.sub(r'[^\d.]', '', str(current_price))
                    current_price = float(cleaned)
                except (ValueError, TypeError):
                    current_price = None
            if current_price is None:
                response_msg = "Please specify the price you want to compare (e.g., 'Is 1500 AED reasonable?')"
            else:
                avg_data = tools.get_average_item_price(item_code)

                if avg_data.get("error"):
                    response_msg = (
                        f"🔍 **Price Comparison for {item_code}**\n\n"
                        f"Current quote: **{current_price} AED**\n\n"
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
            f"I can help with: price_history, average_price, or price_comparison."
        )

    return {
        "messages": [AIMessage(content=response_msg)],
        "last_action": query_type
    }
