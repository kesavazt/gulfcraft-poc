"""
Fallback Handler

Multi-tier fallback strategy for extraction failures.
Handles cases where parameter extraction returns empty results.
"""

from typing import Dict, Any, Optional, List
from langchain_core.messages import AIMessage
from utils.llm import llm


class FallbackHandler:
    """
    Handles extraction failures with 3-tier fallback strategy.

    Tier 1: Retry with simplified prompt
    Tier 2: Ask targeted clarification questions
    Tier 3: Route to ExplainerAgent for help
    """

    # Simplified extraction prompts for retry
    SIMPLIFIED_PROMPTS = {
        "SearchAgent": """Extract from this message:
1. What work needs to be done? (job description)
2. What is the boat model?

Message: "{user_message}"

Return JSON: {{"job_description": "...", "boat_model": "..."}}""",

        "EditJobAgent": """What does the user want to do?
- add item
- remove item
- update item
- change description

Message: "{user_message}"

Return JSON: {{"operation": "..."}}""",

        "QuoteManagementAgent": """Extract:
1. Operation: enter_quote, resend, or cancel
2. Item name (if applicable)
3. Price (if applicable)

Message: "{user_message}"

Return JSON""",
    }

    # Clarification questions for missing parameters
    CLARIFICATION_QUESTIONS = {
        "SearchAgent": {
            "job_description": "What maintenance or repair work needs to be done?",
            "boat_model": "What is the boat model? (e.g., MAJESTY62, MAJESTY120)"
        },
        "EditJobAgent": {
            "operation": "What would you like to do? (add, remove, or update items)",
            "job_id": "Which job would you like to edit? Please provide the job ID."
        },
        "QuoteManagementAgent": {
            "operation": "What would you like to do with the quote? (enter price, resend request, or cancel)",
            "item_name": "Which item is this quote for?",
            "price": "What is the quoted price?"
        },
        "JobLifecycleAgent": {
            "operation": "What would you like to do? (approve, download, duplicate, cancel, or email)",
            "job_id": "Which job? Please provide the job ID."
        }
    }

    def handle_extraction_failure(
        self,
        user_message: str,
        agent_name: str,
        conversation_context: Dict[str, Any],
        extraction_attempts: int = 0
    ) -> Dict[str, Any]:
        """
        Handle extraction failure with multi-tier fallback.

        Args:
            user_message: User's message
            agent_name: Agent that failed extraction
            conversation_context: Conversation context
            extraction_attempts: Number of previous attempts

        Returns:
            dict: Fallback response with operation type and data
        """
        # Tier 1: Retry with simplified prompt (first attempt)
        if extraction_attempts == 0:
            print(f"[FallbackHandler] Tier 1: Retrying with simplified prompt for {agent_name}")
            return self._tier1_simplified_retry(user_message, agent_name)

        # Tier 2: Targeted clarification questions (second attempt)
        elif extraction_attempts == 1:
            print(f"[FallbackHandler] Tier 2: Asking clarification questions for {agent_name}")
            return self._tier2_clarification(user_message, agent_name, conversation_context)

        # Tier 3: Route to ExplainerAgent (third attempt)
        else:
            print(f"[FallbackHandler] Tier 3: Routing to ExplainerAgent after {extraction_attempts} failures")
            return self._tier3_explainer_route(agent_name)

    def _tier1_simplified_retry(self, user_message: str, agent_name: str) -> Dict[str, Any]:
        """
        Tier 1: Retry extraction with simplified prompt.

        Args:
            user_message: User's message
            agent_name: Agent name

        Returns:
            dict: Retry result or indication to proceed to Tier 2
        """
        simplified_prompt = self.SIMPLIFIED_PROMPTS.get(agent_name)

        if not simplified_prompt:
            # No simplified prompt available, skip to Tier 2
            return {
                "operation": "proceed_to_tier2",
                "reason": "no_simplified_prompt_available"
            }

        try:
            prompt = simplified_prompt.format(user_message=user_message)
            response = llm.invoke([{"role": "user", "content": prompt}])
            content = response.content.strip()

            # Try to parse JSON response
            import json
            # Extract JSON from markdown code blocks if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            params = json.loads(content)

            if params and any(v for v in params.values()):
                # Successfully extracted parameters
                return {
                    "operation": "extraction_success",
                    "parameters": params,
                    "tier": 1
                }
            else:
                # Empty result, proceed to Tier 2
                return {
                    "operation": "proceed_to_tier2",
                    "reason": "empty_extraction"
                }

        except Exception as e:
            print(f"[FallbackHandler] Tier 1 failed: {e}")
            return {
                "operation": "proceed_to_tier2",
                "reason": f"extraction_error: {e}"
            }

    def _tier2_clarification(
        self,
        user_message: str,
        agent_name: str,
        conversation_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Tier 2: Ask targeted clarification questions.

        Args:
            user_message: User's message
            agent_name: Agent name
            conversation_context: Context

        Returns:
            dict: Clarification response
        """
        questions = self.CLARIFICATION_QUESTIONS.get(agent_name, {})

        if not questions:
            # No questions available, skip to Tier 3
            return {
                "operation": "proceed_to_tier3",
                "reason": "no_clarification_questions"
            }

        # Identify which parameters are missing
        missing_params = self._identify_missing_parameters(agent_name, conversation_context)

        if not missing_params:
            # All parameters present (somehow), skip to Tier 3
            return {
                "operation": "proceed_to_tier3",
                "reason": "no_missing_parameters"
            }

        # Generate clarification message
        clarification_messages = []
        for param in missing_params[:2]:  # Ask max 2 questions at a time
            question = questions.get(param, f"Please provide {param}")
            clarification_messages.append(f"- {question}")

        clarification_text = "I need some more information:\n" + "\n".join(clarification_messages)

        return {
            "operation": "clarification_needed",
            "messages": [AIMessage(content=clarification_text)],
            "next": "FINISH",
            "pending_disambiguation": {
                "agent": agent_name.replace("Agent", "").lower(),
                "disambiguation_type": "parameter_clarification",
                "missing_parameters": missing_params,
                "original_message": user_message
            },
            "extraction_failures": 2,  # Increment failure counter
            "tier": 2
        }

    def _tier3_explainer_route(self, agent_name: str) -> Dict[str, Any]:
        """
        Tier 3: Route to ExplainerAgent for help.

        Args:
            agent_name: Original agent name

        Returns:
            dict: Route to ExplainerAgent
        """
        help_message = (
            f"I'm having trouble understanding your request. "
            f"Let me connect you with help to explain how {agent_name.replace('Agent', '')} works. "
            f"You can also try rephrasing your request or providing more details."
        )

        return {
            "operation": "route_to_explainer",
            "messages": [AIMessage(content=help_message)],
            "next": "ExplainerAgent",
            "routing_reason": "extraction_failure_fallback",
            "extraction_failures": 0,  # Reset counter
            "tier": 3
        }

    def _identify_missing_parameters(
        self,
        agent_name: str,
        conversation_context: Dict[str, Any]
    ) -> List[str]:
        """
        Identify which parameters are missing for the agent.

        Args:
            agent_name: Agent name
            conversation_context: Conversation context

        Returns:
            list: Missing parameter names
        """
        # Define required parameters for each agent
        required_params = {
            "SearchAgent": ["job_description", "boat_model"],
            "EditJobAgent": ["operation", "job_id"],
            "QuoteManagementAgent": ["operation"],
            "JobLifecycleAgent": ["operation", "job_id"]
        }

        agent_requirements = required_params.get(agent_name, [])
        missing = []

        for param in agent_requirements:
            # Check if parameter exists in context
            if not conversation_context.get(param):
                missing.append(param)

        return missing

    def should_retry(self, extraction_attempts: int, max_attempts: int = 3) -> bool:
        """
        Determine if extraction should be retried.

        Args:
            extraction_attempts: Current number of attempts
            max_attempts: Maximum allowed attempts

        Returns:
            bool: True if should retry
        """
        return extraction_attempts < max_attempts
