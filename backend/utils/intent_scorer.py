"""
Intent Confidence Scorer

Scores supervisor routing decisions with confidence metrics.
Uses multiple signals: keyword matching, context coherence, and LLM confidence.
"""

from typing import List, Dict, Any, Optional
from langchain_core.messages import BaseMessage


class IntentConfidenceScorer:
    """
    Scores routing decisions with confidence metrics.

    Signals used:
    1. Keyword matching - Does user message contain agent-specific keywords?
    2. Context coherence - Does routing align with conversation flow?
    3. LLM confidence - Logprobs from structured output (future enhancement)
    """

    # Agent-specific keyword dictionaries
    AGENT_KEYWORDS = {
        "SearchAgent": [
            "search", "find", "quotation", "quote", "job description", "boat model",
            "polishing", "cleaning", "repair", "maintenance", "work"
        ],
        "SelectionAgent": [
            "select", "choose", "option", "pick", "yes", "no", "confirm",
            "1", "2", "3", "4", "5"  # Number selections
        ],
        "StatusAgent": [
            "status", "pending", "waiting", "how long", "which items", "awaiting",
            "check", "show", "jobs", "progress", "update"
        ],
        "EditJobAgent": [
            "add", "remove", "delete", "update", "change", "modify", "edit",
            "quantity", "item", "insert", "replace"
        ],
        "QuoteManagementAgent": [
            "quote", "quoted", "price", "enter", "resend", "cancel",
            "vendor", "supplier", "received", "aed"
        ],
        "JobLifecycleAgent": [
            "approve", "download", "duplicate", "cancel", "copy", "email",
            "send", "costing sheet", "get"
        ],
        "PricingAdvisorAgent": [
            "price history", "average", "cost", "pricing", "how much",
            "typical", "compare", "good price", "expensive", "cheap"
        ],
        "ExplainerAgent": [
            "why", "explain", "how", "what does", "what is", "clarify",
            "understand", "meaning", "help"
        ],
        "VendorInfoAgent": [
            "vendor", "supplier", "who supplies", "which vendor", "performance",
            "stats", "best vendor", "find supplier"
        ]
    }

    # Context flow patterns - what agent typically follows what
    CONTEXT_FLOWS = {
        "SearchAgent": ["SelectionAgent", "SearchAgent"],  # Search -> Select or Show More
        "SelectionAgent": ["CostingAgent", "SearchAgent"],  # Select -> Cost or Back to Search
        "StatusAgent": ["EditJobAgent", "QuoteManagementAgent", "JobLifecycleAgent"],
        "EditJobAgent": ["StatusAgent", "EditJobAgent"],
        "QuoteManagementAgent": ["StatusAgent", "JobLifecycleAgent"],
        "JobLifecycleAgent": ["SearchAgent", "StatusAgent"],
        "PricingAdvisorAgent": ["EditJobAgent", "SearchAgent"],
        "ExplainerAgent": ["SearchAgent", "StatusAgent"],
        "VendorInfoAgent": ["QuoteManagementAgent", "SearchAgent"]
    }

    def score_intent(
        self,
        user_message: str,
        routed_agent: str,
        conversation_history: List[BaseMessage],
        last_action: Optional[str] = None,
        last_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Score routing decision with multiple signals.

        Args:
            user_message: User's input message
            routed_agent: Agent that Supervisor routed to
            conversation_history: Recent conversation messages
            last_action: Last action performed (e.g., "created_job")
            last_agent: Previously active agent

        Returns:
            dict: {
                "intent": agent_name,
                "confidence": 0.0-1.0,
                "signals": {
                    "keyword_match": 0.0-1.0,
                    "context_coherence": 0.0-1.0,
                    "llm_confidence": 0.0-1.0 (placeholder)
                },
                "fallback_required": bool,
                "threshold": "high" | "medium" | "low"
            }
        """
        user_lower = user_message.lower()

        # Signal 1: Keyword matching
        keyword_score = self._calculate_keyword_match(user_lower, routed_agent)

        # Signal 2: Context coherence
        context_score = self._calculate_context_coherence(routed_agent, last_agent, last_action)

        # Signal 3: LLM confidence (placeholder - requires logprobs from LLM)
        llm_score = 0.9  # Default high confidence (future: extract from model output)

        # Weighted average: 40% keywords, 30% context, 30% LLM
        overall_confidence = (
            0.4 * keyword_score +
            0.3 * context_score +
            0.3 * llm_score
        )

        # Determine threshold level
        if overall_confidence >= 0.8:
            threshold = "high"
            fallback_required = False
        elif overall_confidence >= 0.5:
            threshold = "medium"
            fallback_required = False  # But should add clarification
        else:
            threshold = "low"
            fallback_required = True

        return {
            "intent": routed_agent,
            "confidence": round(overall_confidence, 3),
            "signals": {
                "keyword_match": round(keyword_score, 3),
                "context_coherence": round(context_score, 3),
                "llm_confidence": round(llm_score, 3)
            },
            "fallback_required": fallback_required,
            "threshold": threshold
        }

    def _calculate_keyword_match(self, user_message_lower: str, agent: str) -> float:
        """
        Calculate keyword match score for agent.

        Args:
            user_message_lower: Lowercased user message
            agent: Agent name

        Returns:
            float: Score 0.0-1.0
        """
        if agent not in self.AGENT_KEYWORDS:
            return 0.5  # Neutral score if agent not in dictionary

        keywords = self.AGENT_KEYWORDS[agent]
        matches = sum(1 for keyword in keywords if keyword in user_message_lower)

        if matches == 0:
            return 0.3  # Low but not zero (LLM might still be correct)
        elif matches == 1:
            return 0.6  # One match is decent
        elif matches == 2:
            return 0.8  # Two matches is strong
        else:
            return 1.0  # Multiple matches is very strong

    def _calculate_context_coherence(
        self,
        routed_agent: str,
        last_agent: Optional[str],
        last_action: Optional[str]
    ) -> float:
        """
        Calculate context coherence - does routing make sense given conversation flow?

        Args:
            routed_agent: Agent being routed to
            last_agent: Previously active agent
            last_action: Last action performed

        Returns:
            float: Score 0.0-1.0
        """
        # If no previous context, neutral score
        if not last_agent:
            return 0.7

        # Check if routed_agent is in expected flow from last_agent
        expected_agents = self.CONTEXT_FLOWS.get(last_agent, [])

        if routed_agent in expected_agents:
            return 1.0  # Perfect coherence
        elif routed_agent == last_agent:
            # Staying in same agent can be valid (multi-turn interactions)
            return 0.8
        else:
            # Unexpected transition - lower score but not zero
            return 0.5

    def should_clarify(self, confidence: float, threshold_level: str) -> bool:
        """
        Determine if clarification message should be added.

        Args:
            confidence: Confidence score 0.0-1.0
            threshold_level: "high", "medium", or "low"

        Returns:
            bool: True if clarification needed
        """
        return threshold_level == "medium"

    def should_trigger_fallback(self, confidence: float, threshold_level: str) -> bool:
        """
        Determine if fallback flow should be triggered.

        Args:
            confidence: Confidence score 0.0-1.0
            threshold_level: "high", "medium", or "low"

        Returns:
            bool: True if fallback needed
        """
        return threshold_level == "low"

    def generate_clarification_message(self, agent: str, user_message: str) -> str:
        """
        Generate clarification message for medium confidence scenarios.

        Args:
            agent: Agent being routed to
            user_message: User's message

        Returns:
            str: Clarification message
        """
        clarifications = {
            "SearchAgent": "I think you want to search for a quotation. Is that correct?",
            "SelectionAgent": "I think you're selecting a quotation. Is that what you meant?",
            "StatusAgent": "I think you want to check the status of a job. Correct?",
            "EditJobAgent": "I think you want to edit a costing job. Should I proceed?",
            "QuoteManagementAgent": "I think you want to manage vendor quotes. Is that right?",
            "JobLifecycleAgent": "I think you want to perform a lifecycle operation (approve/download/etc). Correct?",
            "PricingAdvisorAgent": "I think you want pricing information. Is that what you need?",
            "ExplainerAgent": "I think you have a question that needs explanation. Correct?",
            "VendorInfoAgent": "I think you want information about vendors. Is that right?"
        }

        return clarifications.get(agent, "I'm not entirely sure what you need. Could you clarify?")
