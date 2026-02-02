"""
Explainer Agent Node

Answers "why" questions about costing jobs, pricing decisions, and system logic.
"""

import json
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from core.state import AgentState
from core import config
from utils import tools
from utils.llm import llm
from utils.prompts import EXPLAINER_AGENT_SYSTEM_PROMPT, EXPLAINER_EXTRACTION_PROMPT
from utils.langfuse_tracing import trace_agent


def _extract_explainer_parameters(user_message: str, state: AgentState) -> dict:
    """Extract explanation request parameters from user message using LLM."""
    last_job_id = state.get("last_mentioned_job_id") or state.get("job_id") or "Not specified"
    recent_activity = state.get("last_action", "None")

    prompt = EXPLAINER_EXTRACTION_PROMPT.format(
        user_message=user_message,
        last_job_id=last_job_id,
        recent_activity=recent_activity
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
        print(f"[ExplainerAgent] Extraction error: {e}")
        return {}


@trace_agent
def explainer_node(state: AgentState):
    """
    Explains costing logic, pricing decisions, and system behavior.
    """
    user_message = state["messages"][-1].content if state.get("messages") else ""

    # Extract parameters
    params = _extract_explainer_parameters(user_message, state)

    if not params or not params.get("question_type"):
        return {
            "messages": [AIMessage(content=
                "I can explain how the costing system works! Ask me:\n\n"
                "❓ **Why questions** - Why is an item pending? Why this price?\n"
                "💰 **Pricing logic** - How are profit margins calculated?\n"
                "📊 **Status explanations** - What does each status mean?\n"
                "🔧 **Workflow guidance** - How does the quote process work?\n\n"
                "Examples:\n"
                "- 'Why is this item pending a quote?'\n"
                "- 'Explain the pricing for this job'\n"
                "- 'Why is my job still waiting after 3 days?'\n"
                "- 'How is the selling price calculated?'"
            )]
        }

    question_type = params.get("question_type")
    job_id = params.get("job_id")
    item_name = params.get("item_name")

    response_msg = ""

    if question_type == "why_pending":
        # Explain why an item requires a quote
        threshold = config.PRICE_THRESHOLD

        if item_name and job_id:
            # Get specific item details
            job_statuses = tools.get_costing_job_statuses(user_id=state.get("user_id", 1), job_id=job_id)
            if job_statuses:
                job = job_statuses[0]
                line_items = job.get("line_items", [])
                matching_items = [item for item in line_items if item_name.lower() in item.get("item_name", "").lower()]

                if matching_items:
                    item = matching_items[0]
                    if item.get("price_status") == "pending_quote":
                        response_msg = (
                            f"❓ **Why is '{item.get('item_name')}' pending a quote?**\n\n"
                            f"This item requires a vendor quote because:\n\n"
                            f"1. **Price Threshold:** Our system automatically requests quotes for items "
                            f"costing more than **{threshold} AED**\n\n"
                            f"2. **Product Database:** "
                        )
                        if item.get("unit_price") is None:
                            response_msg += (
                                f"This item wasn't found in our product database, so we don't have "
                                f"a standard price for it.\n\n"
                            )
                        else:
                            response_msg += (
                                f"The item cost (**{item.get('unit_price')} AED**) exceeds the threshold.\n\n"
                            )

                        response_msg += (
                            f"3. **Vendor Contact:** A quote request was sent to **{item.get('vendor_email', 'default vendor')}**\n\n"
                            f"**Next Steps:**\n"
                            f"- Wait for vendor response (system monitors emails automatically)\n"
                            f"- Or manually enter the quote when you receive it\n"
                            f"- Or use 'Pricing Advisor' to check historical prices"
                        )
                    else:
                        response_msg = f"✅ '{item.get('item_name')}' is not pending - it's already resolved with price: {item.get('unit_price')} AED"
                else:
                    response_msg = f"I couldn't find an item named '{item_name}' in job {job_id}."
            else:
                response_msg = f"I couldn't find job {job_id}."
        else:
            # General explanation
            response_msg = (
                f"❓ **When do items require vendor quotes?**\n\n"
                f"Items need quotes in two situations:\n\n"
                f"1. **High-Value Items:** Any item with a unit cost above **{threshold} AED**\n"
                f"   - This threshold ensures we get competitive pricing for expensive items\n"
                f"   - You can customize this threshold per job if needed\n\n"
                f"2. **Unknown Items:** Items not found in our product database\n"
                f"   - New parts or custom items\n"
                f"   - Items without standard pricing\n\n"
                f"**Labour items** (hours) always use the sales price from the quotation and never require vendor quotes.\n\n"
                f"💡 **Tip:** You can manually enter prices to skip the quote process if you already have pricing information!"
            )

    elif question_type == "explain_price" or question_type == "explain_cost":
        # Explain pricing and profit margin calculations
        profit_margin = config.PROFIT_MARGIN
        margin_pct = (profit_margin - 1) * 100

        if job_id:
            job_statuses = tools.get_costing_job_statuses(user_id=state.get("user_id", 1), job_id=job_id)
            if job_statuses:
                job = job_statuses[0]
                line_items = job.get("line_items", [])

                total_cost = 0
                total_selling = 0
                pending_count = 0

                for item in line_items:
                    if item.get("unit_price"):
                        qty = item.get("quantity", 1)
                        item_cost = item.get("unit_price") * qty
                        total_cost += item_cost
                        total_selling += item_cost * profit_margin
                    else:
                        pending_count += 1

                profit = total_selling - total_cost

                response_msg = (
                    f"💰 **Pricing Breakdown for {job_id}**\n\n"
                    f"**Cost Components:**\n"
                    f"- Total Item Cost: {total_cost:.2f} AED\n"
                    f"- Profit Margin: {margin_pct:.0f}% (multiplier: {profit_margin}x)\n"
                    f"- **Total Selling Price:** {total_selling:.2f} AED\n"
                    f"- **Profit:** {profit:.2f} AED\n\n"
                )

                if pending_count > 0:
                    response_msg += (
                        f"⚠️ **Note:** {pending_count} item(s) still pending quotes. "
                        f"Final price will be higher once quotes are received.\n\n"
                    )

                response_msg += (
                    f"**How it works:**\n"
                    f"1. System collects all item costs (unit price × quantity)\n"
                    f"2. Applies {margin_pct:.0f}% profit margin to each item\n"
                    f"3. Sums up selling prices for total\n\n"
                    f"**Example Calculation:**\n"
                    f"- Item costs 1000 AED\n"
                    f"- Selling price = 1000 × {profit_margin} = {1000 * profit_margin:.2f} AED\n"
                    f"- Profit = {1000 * profit_margin:.2f} - 1000 = {(1000 * profit_margin) - 1000:.2f} AED"
                )
            else:
                response_msg = f"I couldn't find job {job_id} to explain its pricing."
        else:
            # General pricing explanation
            response_msg = (
                f"💰 **How Pricing Works**\n\n"
                f"**Cost Calculation:**\n"
                f"1. Each line item has a **unit cost** (from vendor or database)\n"
                f"2. Total cost = unit cost × quantity\n\n"
                f"**Selling Price:**\n"
                f"1. We apply a **{margin_pct:.0f}% profit margin** ({profit_margin}x multiplier)\n"
                f"2. Selling price = cost × {profit_margin}\n"
                f"3. Total selling price = sum of all item selling prices\n\n"
                f"**Example:**\n"
                f"- Hydraulic pump: 1,000 AED cost\n"
                f"- Selling price: 1,000 × {profit_margin} = {1000 * profit_margin:,.0f} AED\n"
                f"- Profit: {(1000 * profit_margin) - 1000:,.0f} AED per unit\n\n"
                f"💡 **Customization:** Profit margins can be adjusted per job if needed."
            )

    elif question_type == "explain_status":
        # Explain job statuses
        if job_id:
            job_statuses = tools.get_costing_job_statuses(user_id=state.get("user_id", 1), job_id=job_id)
            if job_statuses:
                job = job_statuses[0]
                status = job.get("status")

                status_explanations = {
                    "Completed": "✅ All prices resolved, ready for review",
                    "Ready": "✅ All quotes received, ready for approval",
                    "Awaiting Quote": "⏳ Waiting for vendor responses",
                    "Approved": "✅ Job approved, ready to proceed",
                    "Cancelled": "❌ Job cancelled, no longer active"
                }

                explanation = status_explanations.get(status, "Unknown status")

                response_msg = (
                    f"📊 **Status Explanation for {job_id}**\n\n"
                    f"Current Status: **{status}**\n"
                    f"{explanation}\n\n"
                )

                if status == "Awaiting Quote":
                    pending_quotes = job.get("quote_requests", [])
                    pending_items = [q for q in pending_quotes if q.get("status") == "pending"]
                    response_msg += (
                        f"**Why is it waiting?**\n"
                        f"- {len(pending_items)} quote request(s) sent to vendors\n"
                        f"- System monitors emails for responses\n"
                        f"- You can manually enter quotes to speed up the process\n\n"
                        f"**Pending Items:**\n"
                    )
                    for item in pending_items[:3]:
                        response_msg += f"- {item.get('item_name')} (sent {item.get('sent_at', 'recently')})\n"

                elif status in ["Completed", "Ready"]:
                    response_msg += (
                        f"**Next Steps:**\n"
                        f"- Review the costing sheet\n"
                        f"- Make any necessary adjustments\n"
                        f"- Approve the job when ready\n"
                        f"- Email to reviewers if needed"
                    )

            else:
                response_msg = f"I couldn't find job {job_id} to explain its status."
        else:
            # General status explanation
            response_msg = (
                f"📊 **Job Status Meanings**\n\n"
                f"**Completed / Ready** ✅\n"
                f"- All items have prices\n"
                f"- Costing sheet is complete\n"
                f"- Ready for review and approval\n\n"
                f"**Awaiting Quote** ⏳\n"
                f"- Some items need vendor quotes\n"
                f"- System is monitoring for email responses\n"
                f"- You can manually enter quotes\n\n"
                f"**Approved** ✅\n"
                f"- Job has been approved by user\n"
                f"- SharePoint updated\n"
                f"- Ready to proceed with work\n\n"
                f"**Cancelled** ❌\n"
                f"- Job cancelled, no longer active\n"
                f"- Still viewable for reference"
            )

    else:
        # Generic helpful response
        response_msg = (
            f"I can explain various aspects of the costing system. "
            f"Try asking more specific questions like:\n"
            f"- 'Why is [item name] pending?'\n"
            f"- 'Explain the pricing for [job_id]'\n"
            f"- 'What does the status mean?'"
        )

    return {
        "messages": [AIMessage(content=response_msg)],
        "last_action": "explained"
    }
