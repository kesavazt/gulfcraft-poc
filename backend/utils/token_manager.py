"""
Token Manager

Manages conversation token limits and pruning.
Ensures conversations fit within model context windows.
"""

from typing import List
from langchain_core.messages import BaseMessage, SystemMessage
import tiktoken


class TokenManager:
    """
    Manages conversation token limits.

    Features:
    - Token counting for GPT models
    - Message pruning to fit limits
    - Preserves recent messages
    """

    MAX_TOKENS = 120000  # Leave room for response (128k context limit for GPT-4)
    MODEL_NAME = "gpt-4"  # Default model for token counting

    def __init__(self, model: str = None):
        """
        Initialize TokenManager.

        Args:
            model: Model name for tiktoken encoding (default: gpt-4)
        """
        self.model = model or self.MODEL_NAME
        try:
            self.encoding = tiktoken.encoding_for_model(self.model)
        except KeyError:
            # Fallback to cl100k_base (used by gpt-4 and gpt-3.5-turbo)
            print(f"[TokenManager] Model {self.model} not found, using cl100k_base encoding")
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, messages: List[BaseMessage]) -> int:
        """
        Count total tokens in message history.

        Args:
            messages: List of messages

        Returns:
            int: Total token count
        """
        total = 0

        for msg in messages:
            # Message overhead (role, name, etc.): ~4 tokens per message
            total += 4

            # Message content
            if hasattr(msg, 'content') and msg.content:
                total += len(self.encoding.encode(msg.content))

        # Additional overhead for formatting
        total += 2

        return total

    def prune_messages(
        self,
        messages: List[BaseMessage],
        target_tokens: int = None
    ) -> List[BaseMessage]:
        """
        Remove oldest messages to fit within token limit.

        Preservation rules:
        - Always keeps system message (if present)
        - Always keeps last 5 messages
        - Removes from middle, oldest first

        Args:
            messages: Full message history
            target_tokens: Target token count (default: MAX_TOKENS)

        Returns:
            list: Pruned messages
        """
        target = target_tokens or self.MAX_TOKENS
        current_tokens = self.count_tokens(messages)

        if current_tokens <= target:
            return messages  # No pruning needed

        print(f"[TokenManager] Pruning {current_tokens} tokens to fit {target} limit")

        # Identify system message
        system_msg = None
        msg_start_idx = 0
        if messages and isinstance(messages[0], SystemMessage):
            system_msg = messages[0]
            msg_start_idx = 1

        # Always keep last 5 messages
        keep_recent = messages[-5:]
        middle_messages = messages[msg_start_idx:-5] if len(messages) > 5 else []

        # Calculate tokens for kept messages
        keep_tokens = self.count_tokens(keep_recent)
        if system_msg:
            keep_tokens += self.count_tokens([system_msg])

        available_tokens = target - keep_tokens

        # Add messages from middle until token limit
        pruned_middle = []
        for msg in reversed(middle_messages):
            msg_tokens = self.count_tokens([msg])
            if msg_tokens <= available_tokens:
                pruned_middle.insert(0, msg)
                available_tokens -= msg_tokens
            else:
                break

        # Build final result
        result = []
        if system_msg:
            result.append(system_msg)
        result.extend(pruned_middle)
        result.extend(keep_recent)

        final_tokens = self.count_tokens(result)
        print(f"[TokenManager] Pruned from {len(messages)} to {len(result)} messages ({current_tokens} → {final_tokens} tokens)")

        return result

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate tokens for a text string.

        Args:
            text: Text to count

        Returns:
            int: Estimated token count
        """
        return len(self.encoding.encode(text))

    def fits_in_context(self, messages: List[BaseMessage], max_tokens: int = None) -> bool:
        """
        Check if messages fit within token limit.

        Args:
            messages: Message list
            max_tokens: Maximum tokens (default: MAX_TOKENS)

        Returns:
            bool: True if fits
        """
        max_limit = max_tokens or self.MAX_TOKENS
        current = self.count_tokens(messages)
        return current <= max_limit

    def get_token_stats(self, messages: List[BaseMessage]) -> dict:
        """
        Get detailed token statistics.

        Args:
            messages: Message list

        Returns:
            dict: Token statistics
        """
        total_tokens = self.count_tokens(messages)
        utilization = (total_tokens / self.MAX_TOKENS) * 100

        return {
            "total_tokens": total_tokens,
            "max_tokens": self.MAX_TOKENS,
            "available_tokens": max(0, self.MAX_TOKENS - total_tokens),
            "utilization_percent": round(utilization, 2),
            "message_count": len(messages),
            "avg_tokens_per_message": round(total_tokens / max(1, len(messages)), 2),
            "needs_pruning": total_tokens > self.MAX_TOKENS
        }
