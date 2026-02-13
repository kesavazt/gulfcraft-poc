"""
Conversation Summarizer

Generates summaries of conversations to manage token limits.
Compresses long conversation histories while preserving key information.
"""

from typing import List, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from utils.llm import llm


class ConversationSummarizer:
    """
    Generates summaries of conversations.

    Features:
    - LLM-based summarization
    - Keeps recent messages intact
    - Focuses on key facts and actions
    """

    SUMMARIZATION_THRESHOLD = 15  # Summarize after 15 messages
    KEEP_RECENT_COUNT = 5  # Always keep last 5 messages

    SUMMARY_PROMPT = """Summarize this conversation into key facts (max 200 words):

{conversation_text}

Focus on:
1. **Jobs created/discussed** - Job IDs and their status
2. **Actions taken** - Quotes sent, items edited, jobs approved, etc.
3. **Current status** - What's pending, what's complete
4. **User requirements** - What the user needs or wants

**Format as bullet points.** Be concise and factual.

Summary:"""

    def should_summarize(self, messages: List[BaseMessage]) -> bool:
        """
        Check if conversation needs summarization.

        Args:
            messages: Conversation messages

        Returns:
            bool: True if should summarize
        """
        return len(messages) > self.SUMMARIZATION_THRESHOLD

    def summarize(self, messages: List[BaseMessage]) -> str:
        """
        Generate a concise summary of conversation history.

        Args:
            messages: All messages except last few

        Returns:
            str: Summary text
        """
        # Build conversation text
        history_text = ""
        for msg in messages:
            role = "User" if isinstance(msg, HumanMessage) else "Assistant"
            content = msg.content if hasattr(msg, 'content') else str(msg)
            history_text += f"{role}: {content}\n\n"

        # Generate summary using LLM
        try:
            prompt = self.SUMMARY_PROMPT.format(conversation_text=history_text)
            response = llm.invoke([{"role": "user", "content": prompt}])
            summary = response.content.strip()

            print(f"[Summarizer] Generated summary ({len(summary)} chars) from {len(messages)} messages")
            return summary
        except Exception as e:
            print(f"[Summarizer] Error generating summary: {e}")
            # Fallback: simple truncation
            return f"[Previous conversation: {len(messages)} messages exchanged about costing jobs and quotations]"

    def compress_history(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Replace old messages with a summary message.

        Args:
            messages: Full message history

        Returns:
            list: Compressed messages (summary + recent messages)
        """
        if not self.should_summarize(messages):
            return messages

        # Split into old (to summarize) and recent (to keep)
        split_point = len(messages) - self.KEEP_RECENT_COUNT
        old_messages = messages[:split_point]
        recent_messages = messages[split_point:]

        # Generate summary of old messages
        summary_text = self.summarize(old_messages)

        # Create summary message
        summary_message = AIMessage(content=f"**[Conversation Summary]**\n{summary_text}")

        # Return compressed history
        compressed = [summary_message] + recent_messages

        print(f"[Summarizer] Compressed {len(messages)} messages to {len(compressed)} messages")
        return compressed

    def extract_key_facts(self, messages: List[BaseMessage]) -> dict:
        """
        Extract structured key facts from conversation.

        Args:
            messages: Conversation messages

        Returns:
            dict: Key facts (job_ids, actions, etc.)
        """
        facts = {
            "job_ids": [],
            "actions": [],
            "quotations": []
        }

        # Simple regex-based extraction
        import re

        for msg in messages:
            if not hasattr(msg, 'content'):
                continue

            content = msg.content

            # Extract job IDs
            job_ids = re.findall(r'COST-[A-Z0-9]{8}', content)
            facts["job_ids"].extend(job_ids)

            # Extract quotation IDs
            quot_ids = re.findall(r'AJMFQ-\d{6}', content)
            facts["quotations"].extend(quot_ids)

            # Extract actions
            action_keywords = ["created", "approved", "updated", "sent", "received", "cancelled"]
            for keyword in action_keywords:
                if keyword in content.lower():
                    facts["actions"].append(keyword)

        # Deduplicate
        facts["job_ids"] = list(set(facts["job_ids"]))
        facts["quotations"] = list(set(facts["quotations"]))
        facts["actions"] = list(set(facts["actions"]))

        return facts

    def should_trigger_summarization(self, message_count: int) -> bool:
        """
        Quick check if summarization should be triggered.

        Args:
            message_count: Number of messages in history

        Returns:
            bool: True if should summarize
        """
        return message_count > self.SUMMARIZATION_THRESHOLD
