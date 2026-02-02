"""
Vendor Info Agent Node

Provides vendor intelligence, performance metrics, and supplier recommendations.
"""

import json
from langchain_core.messages import AIMessage
from core.state import AgentState
from utils import tools
from utils.llm import llm
from utils.prompts import VENDOR_INFO_AGENT_SYSTEM_PROMPT, VENDOR_INFO_EXTRACTION_PROMPT
from utils.langfuse_tracing import trace_agent


def _extract_vendor_parameters(user_message: str, state: AgentState) -> dict:
    """Extract vendor query parameters from user message using LLM."""
    prompt = VENDOR_INFO_EXTRACTION_PROMPT.format(
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
        print(f"[VendorInfoAgent] Extraction error: {e}")
        return {}


@trace_agent
def vendor_info_node(state: AgentState):
    """
    Provides vendor intelligence and performance information.
    """
    user_message = state["messages"][-1].content if state.get("messages") else ""

    # Extract parameters
    params = _extract_vendor_parameters(user_message, state)

    if not params or not params.get("query_type"):
        return {
            "messages": [AIMessage(content=
                "I can provide vendor intelligence! I can help you:\n\n"
                "👤 **Vendor Information** - Get stats on specific vendors\n"
                "🔍 **Find Suppliers** - Discover vendors for specific item types\n"
                "📊 **Performance Metrics** - View response rates and reliability\n\n"
                "Examples:\n"
                "- 'Tell me about vendor@example.com'\n"
                "- 'Who supplies hydraulic parts?'\n"
                "- 'Which vendor is best for electrical items?'\n"
                "- 'Show me Vinod's response rate'"
            )]
        }

    query_type = params.get("query_type")
    vendor_email = params.get("vendor_email")
    item_type = params.get("item_type")
    item_code = params.get("item_code")

    response_msg = ""

    if query_type == "vendor_info" or query_type == "vendor_performance":
        if not vendor_email:
            response_msg = "Please specify a vendor email address to look up their information."
        else:
            vendor_data = tools.get_vendor_info(vendor_email)

            if vendor_data.get("error"):
                response_msg = f"❌ Error retrieving vendor info: {vendor_data.get('error')}"
            else:
                response_rate = vendor_data.get("response_rate", 0)

                # Determine performance rating
                if response_rate >= 80:
                    rating = "⭐⭐⭐ Excellent"
                    rating_color = "🟢"
                elif response_rate >= 60:
                    rating = "⭐⭐ Good"
                    rating_color = "🟡"
                elif response_rate >= 40:
                    rating = "⭐ Fair"
                    rating_color = "🟡"
                else:
                    rating = "⚠️ Poor"
                    rating_color = "🔴"

                response_msg = (
                    f"👤 **Vendor Profile: {vendor_email}**\n\n"
                    f"**Performance Metrics:**\n"
                    f"- Response Rate: {rating_color} **{response_rate}%** {rating}\n"
                    f"- Total Quote Requests: {vendor_data.get('total_quote_requests', 0)}\n"
                    f"- Quotes Received: {vendor_data.get('received_quotes', 0)}\n"
                    f"- Currently Pending: {vendor_data.get('pending_quotes', 0)}\n\n"
                    f"**Supply History:**\n"
                    f"- Total Items Supplied: {vendor_data.get('total_items_supplied', 0)}\n\n"
                )

                if response_rate >= 80:
                    response_msg += "💡 **Recommendation:** Highly reliable vendor, great for urgent quotes!"
                elif response_rate >= 60:
                    response_msg += "💡 **Recommendation:** Reliable vendor, suitable for most projects."
                elif response_rate >= 40:
                    response_msg += "💡 **Recommendation:** Moderate reliability, consider backup vendors for urgent items."
                else:
                    response_msg += "⚠️ **Recommendation:** Low response rate, consider alternative vendors for critical items."

    elif query_type == "vendors_for_item":
        if not item_type and not item_code:
            response_msg = "Please specify an item type or item code to find suitable vendors."
        else:
            vendors = tools.get_vendors_for_item_type(item_type=item_type, item_code=item_code)

            if not vendors:
                search_term = item_type or item_code
                response_msg = (
                    f"🔍 **Vendor Search for '{search_term}'**\n\n"
                    f"No vendors found who have supplied this type of item before. "
                    f"This might be a new item category for your organization."
                )
            else:
                search_term = item_type or item_code
                response_msg = (
                    f"🔍 **Vendors who supply '{search_term}'**\n\n"
                    f"Found **{len(vendors)} vendor(s)** with experience supplying this item:\n\n"
                )

                for i, vendor in enumerate(vendors[:10], 1):
                    # Get additional vendor stats
                    vendor_stats = tools.get_vendor_info(vendor.get("vendor_email"))
                    response_rate = vendor_stats.get("response_rate", 0)

                    if response_rate >= 80:
                        badge = "⭐⭐⭐"
                    elif response_rate >= 60:
                        badge = "⭐⭐"
                    elif response_rate >= 40:
                        badge = "⭐"
                    else:
                        badge = "⚠️"

                    response_msg += (
                        f"{i}. **{vendor.get('vendor_email')}** {badge}\n"
                        f"   - Items Supplied: {vendor.get('items_supplied', 0)}\n"
                        f"   - Response Rate: {response_rate}%\n\n"
                    )

                response_msg += (
                    f"\n💡 **Tip:** Vendors with ⭐⭐⭐ have excellent response rates (>80%)\n\n"
                    f"Ask me about a specific vendor for more details!"
                )

    else:
        response_msg = (
            f"I don't understand the query type '{query_type}'. "
            f"I can help with: vendor_info, vendor_performance, or vendors_for_item."
        )

    return {
        "messages": [AIMessage(content=response_msg)],
        "last_vendor_email": vendor_email if vendor_email else state.get("last_vendor_email"),
        "last_action": "vendor_info"
    }
