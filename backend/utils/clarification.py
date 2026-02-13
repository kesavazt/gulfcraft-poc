"""
Clarification Flow

Multi-turn clarification dialogs for missing parameters.
Guides users through step-by-step parameter collection.
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import AIMessage


class ClarificationFlow:
    """
    Manages multi-turn clarification dialogs.

    Features:
    - Predefined flows for common scenarios
    - Step-by-step parameter collection
    - Progress tracking
    """

    # Predefined clarification flows
    CLARIFICATION_FLOWS = {
        "job_creation": [
            {
                "field": "job_description",
                "prompt": "What maintenance or repair work needs to be done?",
                "examples": ["polishing", "engine repair", "electrical work"],
                "optional": False
            },
            {
                "field": "boat_model",
                "prompt": "What's the boat model?",
                "examples": ["MAJESTY62", "MAJESTY120", "NOMAD95"],
                "optional": False
            },
            {
                "field": "confirm",
                "prompt": "Create quotation for '{job_description}' on {boat_model}? (Yes/No)",
                "optional": False
            }
        ],
        "quote_entry": [
            {
                "field": "item_name",
                "prompt": "Which item is this quote for?",
                "examples": ["hydraulic pump", "anchor winch", "electrical cable"],
                "optional": False
            },
            {
                "field": "quoted_price",
                "prompt": "What price did the vendor quote (in AED)?",
                "examples": ["1200", "850.50", "3500"],
                "optional": False
            },
            {
                "field": "vendor_email",
                "prompt": "Which vendor sent this quote? (email address, or type 'skip')",
                "examples": ["vendor@example.com", "skip"],
                "optional": True
            },
            {
                "field": "confirm",
                "prompt": "Enter quote of {quoted_price} AED for '{item_name}'? (Yes/No)",
                "optional": False
            }
        ],
        "job_edit": [
            {
                "field": "operation",
                "prompt": "What would you like to do?",
                "examples": ["add item", "remove item", "update quantity"],
                "optional": False
            },
            {
                "field": "job_id",
                "prompt": "Which job ID? (or type 'my job' for last mentioned job)",
                "examples": ["COST-12345678", "my job"],
                "optional": False
            },
            {
                "field": "details",
                "prompt": "Please provide details for this operation",
                "examples": ["Add 50 meters of cable", "Remove item 3", "Change quantity to 10"],
                "optional": False
            }
        ]
    }

    def start_flow(
        self,
        flow_name: str,
        initial_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Start a clarification flow.

        Args:
            flow_name: Name of flow to start
            initial_data: Pre-filled data (optional)

        Returns:
            dict: Flow state with next prompt
        """
        if flow_name not in self.CLARIFICATION_FLOWS:
            return {
                "flow_complete": True,
                "error": f"Unknown flow: {flow_name}"
            }

        flow = self.CLARIFICATION_FLOWS[flow_name]
        data = initial_data or {}
        current_step = 0

        # Find first missing field
        while current_step < len(flow):
            step = flow[current_step]
            field = step["field"]

            # Skip optional fields if user wants
            if step.get("optional") and data.get(field) == "skip":
                data[field] = None
                current_step += 1
                continue

            # Check if field is missing
            if field not in data or data[field] is None or data[field] == "":
                break

            current_step += 1

        # Check if flow is complete
        if current_step >= len(flow):
            return {"flow_complete": True, "data": data}

        # Generate prompt for current step
        step = flow[current_step]
        prompt_text = self._format_prompt(step, data)

        return {
            "flow_complete": False,
            "messages": [AIMessage(content=prompt_text)],
            "pending_disambiguation": {
                "agent": "clarification_flow",
                "flow_name": flow_name,
                "current_step": current_step,
                "data": data,
                "total_steps": len(flow)
            },
            "clarification_needed": True
        }

    def process_response(
        self,
        user_input: str,
        pending: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process user response in clarification flow.

        Args:
            user_input: User's message
            pending: Pending flow state

        Returns:
            dict: Updated flow state
        """
        flow_name = pending["flow_name"]
        current_step = pending["current_step"]
        data = pending.get("data", {})
        flow = self.CLARIFICATION_FLOWS[flow_name]

        # Get current step
        step = flow[current_step]
        field = step["field"]

        # Handle confirmation steps
        if field == "confirm":
            user_lower = user_input.lower().strip()
            if any(word in user_lower for word in ["yes", "sure", "ok", "confirm", "proceed"]):
                data[field] = True
            elif any(word in user_lower for word in ["no", "cancel", "stop"]):
                data[field] = False
                return {
                    "flow_complete": True,
                    "flow_cancelled": True,
                    "data": data
                }
            else:
                # Unclear response - ask again
                return {
                    "flow_complete": False,
                    "messages": [AIMessage(content="Please answer 'yes' or 'no'.")],
                    "pending_disambiguation": pending
                }
        else:
            # Regular field - save user input
            data[field] = user_input.strip()

        # Move to next step
        return self.start_flow(flow_name, data)

    def _format_prompt(
        self,
        step: Dict[str, Any],
        data: Dict[str, Any]
    ) -> str:
        """
        Format prompt with examples and context.

        Args:
            step: Flow step definition
            data: Current data

        Returns:
            str: Formatted prompt
        """
        prompt = step["prompt"]

        # Format with current data
        try:
            prompt = prompt.format(**data)
        except KeyError:
            pass  # Some variables not yet available

        # Add examples if available
        if "examples" in step and step["examples"]:
            examples_text = ", ".join(f'"{ex}"' for ex in step["examples"])
            prompt += f"\n\nExamples: {examples_text}"

        # Add optional indicator
        if step.get("optional"):
            prompt += "\n(Type 'skip' to skip this field)"

        return prompt

    def is_flow_in_progress(self, state: Dict[str, Any]) -> bool:
        """
        Check if a clarification flow is currently in progress.

        Args:
            state: Agent state

        Returns:
            bool: True if flow is active
        """
        pending = state.get("pending_disambiguation", {})
        return pending.get("agent") == "clarification_flow"

    def get_flow_progress(self, pending: Dict[str, Any]) -> str:
        """
        Get flow progress as a string.

        Args:
            pending: Pending flow state

        Returns:
            str: Progress indicator (e.g., "Step 2/4")
        """
        current = pending.get("current_step", 0) + 1
        total = pending.get("total_steps", 1)
        return f"Step {current}/{total}"
