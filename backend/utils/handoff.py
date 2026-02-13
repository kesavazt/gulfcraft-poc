"""
Agent Handoff Protocol

Manages smooth transitions between agents with context preservation.
Generates contextual handoff messages to improve conversation flow.
"""

from typing import Dict, Any, Optional
from core.state import AgentState


class AgentHandoff:
    """
    Manages smooth transitions between agents with context preservation.

    Features:
    - Context-aware handoff messages
    - Context preparation for receiving agent
    - Transition metadata tracking
    """

    # Handoff message templates for common transitions
    HANDOFF_TEMPLATES = {
        # Search flow
        "SearchAgent → SelectionAgent": "I found {count} matching quotations. Let me help you select one.",
        "SearchAgent → SearchAgent": "Let me show you {count} more results.",

        # Selection flow
        "SelectionAgent → CostingAgent": "Great choice! I'll create a costing job for quotation {quotation_id}.",
        "SelectionAgent → SearchAgent": "Let me search again with updated criteria.",

        # Status flow
        "StatusAgent → EditJobAgent": "I can help you edit job {job_id}. What would you like to change?",
        "StatusAgent → QuoteManagementAgent": "I see you have {pending_count} pending quotes. Let me help manage those.",
        "StatusAgent → JobLifecycleAgent": "I can help with operations on job {job_id}.",

        # Edit flow
        "EditJobAgent → StatusAgent": "Job {job_id} has been updated. Let me show you the current status.",
        "EditJobAgent → EditJobAgent": "I'll help you with that additional edit to job {job_id}.",

        # Quote management flow
        "QuoteManagementAgent → StatusAgent": "Quote updated. Let me show you the current job status.",
        "QuoteManagementAgent → JobLifecycleAgent": "All quotes are in. Ready to approve job {job_id}?",

        # Lifecycle flow
        "JobLifecycleAgent → SearchAgent": "Job {job_id} processed. Need to create another quotation?",
        "JobLifecycleAgent → StatusAgent": "Job {job_id} {operation} successfully. Here's the status.",

        # Pricing advisor flow
        "PricingAdvisorAgent → EditJobAgent": "Based on pricing analysis, would you like to update items in job {job_id}?",
        "PricingAdvisorAgent → SearchAgent": "I can help you find alternative quotations with better pricing.",

        # Explainer flow
        "ExplainerAgent → SearchAgent": "Now that you understand the process, let's create a quotation.",
        "ExplainerAgent → StatusAgent": "Let me show you the actual status of your job.",

        # Vendor info flow
        "VendorInfoAgent → QuoteManagementAgent": "Ready to request quotes from these vendors?",
        "VendorInfoAgent → SearchAgent": "Let me find quotations from {vendor_name}.",
    }

    # Fallback template
    DEFAULT_TEMPLATE = "I'm transferring you to {to_agent} to help with this request."

    def create_handoff_message(
        self,
        from_agent: str,
        to_agent: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Generate contextual handoff message.

        Args:
            from_agent: Source agent name
            to_agent: Target agent name
            context: Context dictionary with variables for template

        Returns:
            str: Formatted handoff message
        """
        # Build transition key
        key = f"{from_agent} → {to_agent}"

        # Get template (use fallback if not found)
        template = self.HANDOFF_TEMPLATES.get(key, self.DEFAULT_TEMPLATE)

        try:
            # Format with context
            message = template.format(
                to_agent=to_agent.replace("Agent", ""),
                from_agent=from_agent.replace("Agent", ""),
                **context
            )
            return message
        except KeyError as e:
            # Missing context variable - use fallback
            print(f"[Handoff] Missing context variable {e} for {key}")
            return self.DEFAULT_TEMPLATE.format(to_agent=to_agent.replace("Agent", ""))

    def prepare_handoff_context(self, state: AgentState, to_agent: str) -> Dict[str, Any]:
        """
        Extract relevant context for receiving agent.

        Args:
            state: Current agent state
            to_agent: Target agent name

        Returns:
            dict: Context dictionary with relevant information
        """
        context = {
            # Common context
            "job_id": state.get("last_mentioned_job_id") or state.get("job_id"),
            "last_action": state.get("last_action"),
            "user_intent": state.get("conversation_context", {}).get("intent"),
        }

        # Agent-specific context preparation
        if to_agent == "SelectionAgent":
            context["count"] = len(state.get("similar_quotations", []))
            context["quotations"] = state.get("similar_quotations", [])

        elif to_agent == "QuoteManagementAgent":
            context["pending_count"] = len(state.get("pending_quote_items", []))
            context["pending_items"] = state.get("pending_quote_items", [])

        elif to_agent == "StatusAgent":
            context["awaiting_quotes"] = state.get("awaiting_quotes", False)
            context["emails_sent"] = state.get("emails_sent", False)

        elif to_agent == "CostingAgent":
            selected_quotation = state.get("selected_quotation", {})
            context["quotation_id"] = selected_quotation.get("quotation_id")
            context["line_num"] = selected_quotation.get("line_num")

        elif to_agent == "EditJobAgent":
            context["has_pending_quotes"] = len(state.get("pending_quote_items", [])) > 0

        elif to_agent == "JobLifecycleAgent":
            context["operation"] = state.get("last_action", "").replace("_", " ")
            context["job_status"] = "pending" if state.get("awaiting_quotes") else "ready"

        elif to_agent == "PricingAdvisorAgent":
            context["last_item_id"] = state.get("last_item_id")

        elif to_agent == "VendorInfoAgent":
            context["vendor_name"] = state.get("last_vendor_email", "").split("@")[0]

        return context

    def should_show_handoff(self, from_agent: Optional[str], to_agent: str) -> bool:
        """
        Determine if handoff message should be shown.

        Args:
            from_agent: Source agent (None if entry point)
            to_agent: Target agent

        Returns:
            bool: True if handoff message should be shown
        """
        # Don't show handoff for:
        # 1. Same agent (staying in same agent)
        # 2. Entry point (no previous agent)
        # 3. FINISH route

        if not from_agent:
            return False

        if from_agent == to_agent:
            return False

        if to_agent == "FINISH":
            return False

        return True

    def build_transition_record(
        self,
        from_agent: Optional[str],
        to_agent: str,
        routing_reason: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build transition record for logging.

        Args:
            from_agent: Source agent
            to_agent: Target agent
            routing_reason: Why transition happened
            context: Transition context

        Returns:
            dict: Transition record
        """
        return {
            "from": from_agent,
            "to": to_agent,
            "reason": routing_reason,
            "context_keys": list(context.keys()),
            "has_handoff": self.should_show_handoff(from_agent, to_agent)
        }
