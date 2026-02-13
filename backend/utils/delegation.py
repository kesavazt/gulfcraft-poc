"""
Agent Delegation

Allows agents to suggest/delegate tasks to other agents.
Enables inter-agent collaboration and workflow optimization.
"""

from typing import Dict, Any, Optional
from langchain_core.messages import AIMessage


class AgentDelegation:
    """
    Allows agents to suggest/delegate tasks to other agents.

    Features:
    - Automatic delegation (direct routing)
    - Suggested delegation (asks user for confirmation)
    - Context-aware delegation reasons
    """

    # Delegation suggestion templates
    DELEGATION_TEMPLATES = {
        # From StatusAgent
        "StatusAgent → QuoteManagementAgent": (
            "You have {pending_count} pending quotes. "
            "Would you like me to help you manage those quote requests? (Yes/No)"
        ),
        "StatusAgent → EditJobAgent": (
            "I can help you edit items in job {job_id}. "
            "Would you like to add, remove, or update items? (Yes/No)"
        ),
        "StatusAgent → JobLifecycleAgent": (
            "All quotes are received for job {job_id}. "
            "Would you like to approve this job? (Yes/No)"
        ),

        # From PricingAdvisorAgent
        "PricingAdvisorAgent → EditJobAgent": (
            "I found a better price for {item_name} ({new_price} AED vs {old_price} AED). "
            "Would you like to update the item in your job? (Yes/No)"
        ),
        "PricingAdvisorAgent → SearchAgent": (
            "I can help you find alternative quotations with better pricing. "
            "Would you like me to search? (Yes/No)"
        ),

        # From VendorInfoAgent
        "VendorInfoAgent → QuoteManagementAgent": (
            "{vendor_name} has good response rates for {item_type}. "
            "Would you like to request a quote from them? (Yes/No)"
        ),

        # From ExplainerAgent
        "ExplainerAgent → SearchAgent": (
            "Now that you understand the process, would you like to create a quotation? (Yes/No)"
        ),

        # From QuoteManagementAgent
        "QuoteManagementAgent → JobLifecycleAgent": (
            "All quotes have been received for job {job_id}. "
            "Ready to approve? (Yes/No)"
        ),

        # From EditJobAgent
        "EditJobAgent → StatusAgent": (
            "Items updated. Would you like to see the current status of job {job_id}? (Yes/No)"
        ),
    }

    DEFAULT_TEMPLATE = "I can help with that. Would you like me to proceed? (Yes/No)"

    def suggest_delegation(
        self,
        current_agent: str,
        target_agent: str,
        reason: str,
        context: Dict[str, Any] = None,
        auto_accept: bool = False
    ) -> Dict[str, Any]:
        """
        Creates a delegation suggestion or automatic delegation.

        Args:
            current_agent: Agent making the delegation
            target_agent: Agent to delegate to
            reason: Why delegation is suggested
            context: Context dictionary for template formatting
            auto_accept: If True, immediately route to target agent without confirmation

        Returns:
            dict: Delegation result with routing information
        """
        context = context or {}

        if auto_accept:
            # Automatic delegation - route immediately
            return {
                "next": target_agent,
                "messages": [AIMessage(content=f"{reason} I'll handle that for you.")],
                "delegation_source": current_agent,
                "routing_reason": "auto_delegation",
                "routing_context": {
                    "delegated_from": current_agent,
                    "delegation_reason": reason,
                    **context
                }
            }
        else:
            # Suggested delegation - ask user for confirmation
            delegation_message = self._generate_delegation_message(
                current_agent,
                target_agent,
                reason,
                context
            )

            return {
                "next": "FINISH",
                "messages": [AIMessage(content=delegation_message)],
                "pending_disambiguation": {
                    "agent": "supervisor",
                    "disambiguation_type": "delegation_confirm",
                    "target_agent": target_agent,
                    "source_agent": current_agent,
                    "delegation_reason": reason,
                    "delegation_context": context
                },
                "routing_reason": "delegation_suggested"
            }

    def _generate_delegation_message(
        self,
        current_agent: str,
        target_agent: str,
        reason: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Generate delegation confirmation message.

        Args:
            current_agent: Source agent
            target_agent: Target agent
            reason: Delegation reason
            context: Context for template

        Returns:
            str: Formatted delegation message
        """
        # Build delegation key
        key = f"{current_agent} → {target_agent}"

        # Get template
        template = self.DELEGATION_TEMPLATES.get(key, self.DEFAULT_TEMPLATE)

        try:
            # Format with context
            message = template.format(**context)
            return message
        except KeyError as e:
            # Missing context variable - use reason
            print(f"[Delegation] Missing context variable {e} for {key}")
            return f"{reason} Would you like me to help? (Yes/No)"

    def handle_delegation_response(
        self,
        user_response: str,
        pending_delegation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process user's response to delegation suggestion.

        Args:
            user_response: User's message (yes/no)
            pending_delegation: Pending delegation from state

        Returns:
            dict: Routing decision
        """
        user_lower = user_response.lower().strip()

        # Check for affirmative responses
        affirmative = ["yes", "sure", "ok", "okay", "go ahead", "proceed", "yep", "yeah"]
        negative = ["no", "nope", "cancel", "don't", "skip"]

        if any(word in user_lower for word in affirmative):
            # User accepted delegation
            target_agent = pending_delegation.get("target_agent")
            return {
                "next": target_agent,
                "routing_reason": "delegation_accepted",
                "routing_context": pending_delegation.get("delegation_context", {}),
                "messages": [AIMessage(content=f"Great! I'll help you with that.")]
            }
        elif any(word in user_lower for word in negative):
            # User declined delegation
            return {
                "next": "FINISH",
                "messages": [AIMessage(content="Got it. What else can I help you with?")],
                "pending_disambiguation": None  # Clear pending state
            }
        else:
            # Unclear response - ask again
            return {
                "next": "FINISH",
                "messages": [AIMessage(content="I didn't quite catch that. Would you like me to help with this? Please say yes or no.")]
            }

    def should_suggest_delegation(
        self,
        current_agent: str,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Determine if delegation should be suggested based on context.

        Args:
            current_agent: Current agent
            context: State context

        Returns:
            dict: Delegation suggestion or None
        """
        # StatusAgent → QuoteManagementAgent (many pending quotes)
        if current_agent == "StatusAgent":
            pending_count = len(context.get("pending_quote_items", []))
            if pending_count > 3:
                return {
                    "target_agent": "QuoteManagementAgent",
                    "reason": f"You have {pending_count} pending quotes",
                    "context": {"pending_count": pending_count},
                    "auto_accept": False
                }

            # StatusAgent → JobLifecycleAgent (all quotes received)
            if not context.get("awaiting_quotes") and context.get("job_id"):
                return {
                    "target_agent": "JobLifecycleAgent",
                    "reason": "All quotes received",
                    "context": {"job_id": context["job_id"]},
                    "auto_accept": False
                }

        # QuoteManagementAgent → JobLifecycleAgent (all quotes in)
        if current_agent == "QuoteManagementAgent":
            if not context.get("awaiting_quotes") and context.get("job_id"):
                return {
                    "target_agent": "JobLifecycleAgent",
                    "reason": "All quotes received",
                    "context": {"job_id": context["job_id"]},
                    "auto_accept": False
                }

        return None
