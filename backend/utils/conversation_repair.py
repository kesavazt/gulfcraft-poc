"""
Conversation Repair

Detects and repairs conversation breakdowns.
Provides recovery strategies when user gets confused or frustrated.
"""

from typing import List, Dict, Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage


class ConversationRepair:
    """
    Detects and repairs conversation breakdowns.

    Breakdown indicators:
    - User confusion phrases ("i don't understand", "confused")
    - Repetitive clarifications
    - Multiple extraction failures
    """

    BREAKDOWN_INDICATORS = [
        "i don't understand",
        "that doesn't make sense",
        "you're not helping",
        "this isn't working",
        "confused",
        "what do you mean",
        "i'm lost",
        "not working",
        "doesn't work",
        "help me"
    ]

    def detect_breakdown(self, messages: List[BaseMessage], state: Dict[str, Any]) -> bool:
        """
        Detect if conversation is broken.

        Signals:
        - User frustration phrases
        - Repetitive clarifications (same question 3+ times)
        - Multiple extraction failures (3+)

        Args:
            messages: Conversation history
            state: Agent state

        Returns:
            bool: True if breakdown detected
        """
        # Check last 3 user messages for breakdown indicators
        recent_user_messages = []
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                recent_user_messages.append(msg.content.lower())
                if len(recent_user_messages) >= 3:
                    break

        # Signal 1: Frustration phrases
        for msg in recent_user_messages:
            if any(indicator in msg for indicator in self.BREAKDOWN_INDICATORS):
                print(f"[ConversationRepair] Breakdown detected: frustration phrase")
                return True

        # Signal 2: Repetitive extraction failures
        extraction_failures = state.get("extraction_failures", 0)
        if extraction_failures >= 3:
            print(f"[ConversationRepair] Breakdown detected: {extraction_failures} extraction failures")
            return True

        # Signal 3: Same clarification question repeated
        if len(recent_user_messages) >= 3:
            # Check if user is asking the same thing repeatedly
            if recent_user_messages[0] == recent_user_messages[1] == recent_user_messages[2]:
                print(f"[ConversationRepair] Breakdown detected: repetitive questions")
                return True

        return False

    def repair_strategy(
        self,
        messages: List[BaseMessage],
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate repair response based on context.

        Strategies:
        1. Provide examples for current context
        2. Route to ExplainerAgent
        3. Offer structured input format
        4. Reset conversation with fresh start

        Args:
            messages: Conversation history
            state: Agent state

        Returns:
            dict: Repair routing with messages
        """
        last_agent = state.get("last_agent")

        # Strategy selection based on context
        extraction_failures = state.get("extraction_failures", 0)

        # Strategy 1: Provide examples (first breakdown)
        if extraction_failures < 3:
            return self._strategy_provide_examples(last_agent, state)

        # Strategy 2: Route to ExplainerAgent (second breakdown)
        elif extraction_failures < 5:
            return self._strategy_route_explainer(last_agent)

        # Strategy 3: Offer reset (multiple breakdowns)
        else:
            return self._strategy_offer_reset()

    def _strategy_provide_examples(
        self,
        last_agent: Optional[str],
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Strategy 1: Provide concrete examples for the user.

        Args:
            last_agent: Last active agent
            state: Agent state

        Returns:
            dict: Repair response with examples
        """
        # Agent-specific examples
        examples = {
            "SearchAgent": """Let me help you with that. To search for quotations, I need:

**1. Job description** - What work needs to be done?
   Examples: "polishing", "engine repair", "electrical work"

**2. Boat model** - Which boat?
   Examples: "MAJESTY62", "MAJESTY120", "NOMAD95"

Try something like: "I need a quotation for polishing work. My boat is MAJESTY62"
""",
            "EditJobAgent": """Let me clarify what you can do:

**Add items:** "Add 50 meters of cable to job COST-12345678"
**Remove items:** "Remove the anchor winch from my job"
**Update items:** "Change quantity to 10 for item 3"

Please specify what you'd like to do.""",

            "QuoteManagementAgent": """Here's what I can help with:

**Enter received quote:** "Vendor quoted 1200 AED for the hydraulic pump"
**Resend quote request:** "Resend quote request for item 5"
**Cancel quote request:** "Cancel quote request for anchor winch"

What would you like to do?""",

            "StatusAgent": """I can show you job status. Try:

**Single job:** "Show me status of job COST-12345678"
**All jobs:** "Show me my jobs"
**Specific info:** "Which items are awaiting quotes in COST-12345678?"
""",
        }

        example_text = examples.get(
            last_agent,
            "Let me help. Please rephrase your request with more details about what you need."
        )

        return {
            "next": "FINISH",
            "messages": [AIMessage(content=example_text)],
            "extraction_failures": 0,  # Reset counter
            "last_action": "conversation_repair_examples"
        }

    def _strategy_route_explainer(self, last_agent: Optional[str]) -> Dict[str, Any]:
        """
        Strategy 2: Route to ExplainerAgent for detailed help.

        Args:
            last_agent: Last active agent

        Returns:
            dict: Route to ExplainerAgent
        """
        agent_name = (last_agent or "the system").replace("Agent", "")

        message = f"""I'm having trouble understanding your request. Let me connect you with help to explain how {agent_name} works.

Alternatively, you can:
- Rephrase your request with more details
- Ask specific questions about what you need
- Start fresh with a clear description"""

        return {
            "next": "ExplainerAgent",
            "messages": [AIMessage(content=message)],
            "routing_reason": "conversation_repair_explainer",
            "extraction_failures": 0  # Reset counter
        }

    def _strategy_offer_reset(self) -> Dict[str, Any]:
        """
        Strategy 3: Offer conversation reset.

        Returns:
            dict: Reset offer
        """
        message = """It seems we're having difficulty. Would you like to:

1. **Start fresh** - Begin a new conversation
2. **Get help** - I'll explain how the system works
3. **Try specific action** - Tell me exactly what you need

Just let me know which option you prefer, or describe what you need in detail."""

        return {
            "next": "FINISH",
            "messages": [AIMessage(content=message)],
            "pending_disambiguation": {
                "agent": "supervisor",
                "disambiguation_type": "reset_or_continue",
                "options": ["start_fresh", "get_help", "continue"]
            },
            "extraction_failures": 0
        }

    def should_trigger_repair(self, state: Dict[str, Any]) -> bool:
        """
        Quick check if repair should be triggered.

        Args:
            state: Agent state

        Returns:
            bool: True if should trigger repair
        """
        return state.get("extraction_failures", 0) >= 2
