"""
Proactive Suggestions

Generates context-aware suggestions based on conversation state.
Helps users discover next actions and optimize workflow.
"""

from typing import List, Dict, Any


class ProactiveSuggestions:
    """
    Generates contextual suggestions based on current state.

    Features:
    - Job completion suggestions
    - Quote management hints
    - Edit reminders
    - Pricing optimization tips
    """

    def generate_suggestions(self, state: Dict[str, Any]) -> List[str]:
        """
        Returns list of proactive suggestions based on current state.

        Args:
            state: Agent state

        Returns:
            list: Suggestion strings (with emoji icons)
        """
        suggestions = []

        # Job completion suggestions
        if self._should_suggest_approval(state):
            job_id = state.get("job_id") or state.get("last_mentioned_job_id")
            suggestions.append(
                f"💡 **All quotes received for {job_id}!** Would you like to approve this job?"
            )

        # Quote management suggestions
        if self._should_suggest_quote_management(state):
            pending_count = len(state.get("pending_quote_items", []))
            suggestions.append(
                f"💡 **You have {pending_count} pending quotes.** I can resend quote requests if vendors haven't responded."
            )

        # Edit suggestions after job creation
        if self._should_suggest_edit(state):
            job_id = state.get("job_id")
            suggestions.append(
                f"💡 **Job {job_id} created!** You can edit items, check status, or add more items anytime."
            )

        # Pricing optimization suggestions
        if self._should_suggest_pricing_check(state):
            suggestions.append(
                "💡 **Want to compare prices?** I can search for alternative suppliers with better pricing."
            )

        # Download reminder
        if self._should_suggest_download(state):
            job_id = state.get("job_id") or state.get("last_mentioned_job_id")
            suggestions.append(
                f"💡 **Costing sheet ready for {job_id}!** You can download it anytime."
            )

        # Status check reminder
        if self._should_suggest_status_check(state):
            suggestions.append(
                "💡 **Need an update?** I can show you the current status of your jobs."
            )

        return suggestions

    def _should_suggest_approval(self, state: Dict[str, Any]) -> bool:
        """Check if should suggest job approval."""
        return (
            not state.get("awaiting_quotes", True) and
            state.get("job_id") is not None and
            state.get("last_action") != "approved_job"
        )

    def _should_suggest_quote_management(self, state: Dict[str, Any]) -> bool:
        """Check if should suggest quote management."""
        pending_count = len(state.get("pending_quote_items", []))
        return (
            pending_count > 3 and
            state.get("last_action") != "quote_management"
        )

    def _should_suggest_edit(self, state: Dict[str, Any]) -> bool:
        """Check if should suggest edit after job creation."""
        return (
            state.get("last_action") == "created_job" and
            state.get("job_id") is not None
        )

    def _should_suggest_pricing_check(self, state: Dict[str, Any]) -> bool:
        """Check if should suggest pricing comparison."""
        return (
            state.get("last_action") == "price_comparison" or
            (state.get("awaiting_quotes") and len(state.get("pending_quote_items", [])) > 5)
        )

    def _should_suggest_download(self, state: Dict[str, Any]) -> bool:
        """Check if should suggest download."""
        return (
            state.get("generated_file") is not None and
            state.get("last_action") != "downloaded_sheet"
        )

    def _should_suggest_status_check(self, state: Dict[str, Any]) -> bool:
        """Check if should suggest status check."""
        return (
            state.get("emails_sent", False) and
            state.get("last_action") not in ["status_check", "created_job"]
        )

    def format_suggestions(self, suggestions: List[str]) -> str:
        """
        Format suggestions as a nice message block.

        Args:
            suggestions: List of suggestion strings

        Returns:
            str: Formatted suggestions
        """
        if not suggestions:
            return ""

        if len(suggestions) == 1:
            return f"\n\n{suggestions[0]}"

        # Multiple suggestions
        formatted = "\n\n**💡 Suggestions:**"
        for suggestion in suggestions:
            formatted += f"\n{suggestion}"

        return formatted

    def get_next_action_suggestions(self, last_action: str) -> List[str]:
        """
        Get suggestions based on last action.

        Args:
            last_action: Last action performed

        Returns:
            list: Contextual next action suggestions
        """
        next_actions = {
            "created_job": [
                "Check job status",
                "Edit items if needed",
                "Add more items"
            ],
            "sent_quotes": [
                "Check quote status later",
                "Resend if no response",
                "View pending items"
            ],
            "approved_job": [
                "Download costing sheet",
                "Email to reviewers",
                "Create another quotation"
            ],
            "edited_items": [
                "Check updated status",
                "Continue editing",
                "Approve when ready"
            ],
            "received_quote": [
                "Check if all quotes received",
                "Approve job if complete",
                "Request more quotes if needed"
            ]
        }

        return next_actions.get(last_action, [])
