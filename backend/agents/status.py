"""
Status Agent Node

Provides conversational job status summaries and pending/available product lists.
"""

import re
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from core.state import AgentState
from utils import tools
from utils.llm import llm
from utils.prompts import STATUS_AGENT_SYSTEM_PROMPT
from utils.langfuse_tracing import trace_agent


def _extract_job_id(message: str) -> str:
    """Extract a job_id like COST-XXXXXXXX from the message."""
    if not message:
        return ""
    match = re.search(r"(COST-[A-Z0-9]+)", message, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _status_label(status: str) -> str:
    """Map internal status to user-facing label."""
    normalized = (status or "").strip().lower()
    if normalized in ["approved"]:
        return "Complete and sent"
    if normalized in ["completed", "ready"]:
        return "Ready to review"
    if normalized in ["awaiting quote", "awaiting quotes", "pending"]:
        return "Waiting for quotes"
    return status or "Unknown"


def _truncate(text: str, max_len: int = 60) -> str:
    """Truncate text to max length with ellipsis."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return f"{text[:max_len - 3]}..."


def _build_status_context(job_statuses: list, specific_job_id: str = None, wants_details: bool = False) -> str:
    """
    Build a structured context string for the LLM to present conversationally.
    """
    if specific_job_id:
        # Single job detail view
        job = job_statuses[0]
        job_id = job.get('job_id')
        status = _status_label(job.get('status'))
        created_at = job.get('created_at') or 'N/A'
        description = job.get('item_details') or 'N/A'

        # Count items by status
        line_items = job.get("line_items", [])
        pending_items = [item for item in line_items if (item.get("price_status") or "").lower() != "resolved"]
        available_items = [item for item in line_items if (item.get("price_status") or "").lower() == "resolved"]

        context_parts = [
            f"Job ID: {job_id}",
            f"Status: {status}",
            f"Created: {created_at}",
            f"Description: {description}",
            f"Total Items: {len(line_items)}",
            f"Pending Products: {len(pending_items)}",
            f"Available Products: {len(available_items)}"
        ]

        # Add detailed quote information if requested
        if wants_details:
            quote_requests = job.get("quote_requests", [])
            pending_quotes = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "pending"]
            received_quotes = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "received"]

            if pending_quotes:
                context_parts.append("\nPending Quote Requests:")
                for item in pending_quotes:
                    sent_at = item.get("sent_at") or "unknown"
                    context_parts.append(f"  - {item.get('item_name')} (sent {sent_at})")

            if received_quotes:
                context_parts.append("\nQuotes Received:")
                for item in received_quotes:
                    received_at = item.get("received_at") or "unknown"
                    context_parts.append(f"  - {item.get('item_name')} (received {received_at})")

        return "\n".join(context_parts)

    else:
        # Multiple jobs overview
        context_parts = [f"Total Jobs: {len(job_statuses)}\n"]

        # Group by status
        ready_jobs = [j for j in job_statuses if _status_label(j.get("status")) == "Ready to review"]
        waiting_jobs = [j for j in job_statuses if _status_label(j.get("status")) == "Waiting for quotes"]
        complete_jobs = [j for j in job_statuses if _status_label(j.get("status")) == "Complete and sent"]

        if ready_jobs:
            context_parts.append(f"Ready to Review ({len(ready_jobs)} jobs):")
            for job in ready_jobs[:3]:  # Show top 3
                context_parts.append(f"  - {job.get('job_id')}: {_truncate(job.get('item_details') or 'N/A', 50)}")
            if len(ready_jobs) > 3:
                context_parts.append(f"  ... and {len(ready_jobs) - 3} more")

        if waiting_jobs:
            context_parts.append(f"\nWaiting for Quotes ({len(waiting_jobs)} jobs):")
            for job in waiting_jobs[:3]:
                context_parts.append(f"  - {job.get('job_id')}: {_truncate(job.get('item_details') or 'N/A', 50)}")
            if len(waiting_jobs) > 3:
                context_parts.append(f"  ... and {len(waiting_jobs) - 3} more")

        if complete_jobs:
            context_parts.append(f"\nCompleted ({len(complete_jobs)} jobs):")
            for job in complete_jobs[:2]:
                context_parts.append(f"  - {job.get('job_id')}: {_truncate(job.get('item_details') or 'N/A', 50)}")
            if len(complete_jobs) > 2:
                context_parts.append(f"  ... and {len(complete_jobs) - 2} more")

        # Add detailed breakdown if requested
        if wants_details and waiting_jobs:
            context_parts.append("\n=== Detailed Pending Items ===")
            for job in waiting_jobs:
                context_parts.append(f"\n{job.get('job_id')}:")
                quote_requests = job.get("quote_requests", [])
                pending_items = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "pending"]
                received_items = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "received"]

                if pending_items:
                    for item in pending_items:
                        sent_at = item.get("sent_at") or "unknown"
                        context_parts.append(f"  • {item.get('item_name')} - Pending (sent {sent_at})")

                if received_items:
                    for item in received_items:
                        received_at = item.get("received_at") or "unknown"
                        context_parts.append(f"  • {item.get('item_name')} - Received ({received_at})")

        # Add helpful footer
        context_parts.append("\nNote: User can ask for details on a specific job by providing the job ID.")

        return "\n".join(context_parts)


# Build conversational prompt
_status_prompt = ChatPromptTemplate.from_messages([
    ("system", STATUS_AGENT_SYSTEM_PROMPT),
    ("system", """Here is the job status information:

{status_context}

Present this information to the user in a conversational, helpful manner. Follow these guidelines:
1. Start with a brief summary (e.g., "You have X jobs in total")
2. Highlight any urgent items (jobs ready for review, long-pending quotes)
3. Use markdown tables ONLY for multiple jobs overview (Job ID | Status | Created | Description)
4. For single job details, be more conversational with bullet points
5. End with a helpful next step or offer to help further
6. Keep it concise but informative

User's original query: {user_query}"""),
])

_status_chain = _status_prompt | llm


@trace_agent
def status_node(state: AgentState):
    """
    Returns conversational status summaries for the user's costing jobs.
    """
    user_id = state.get("user_id", 1)
    user_message = state["messages"][-1].content if state.get("messages") else ""
    job_id = _extract_job_id(user_message)
    msg_lower = (user_message or "").lower()
    wants_details = any(k in msg_lower for k in ["detail", "details", "items", "pending", "quotes", "quote status", "breakdown"])

    # Fetch job statuses
    job_statuses = tools.get_costing_job_statuses(user_id=user_id, job_id=job_id or None)

    # Handle no jobs found
    if not job_statuses:
        if job_id:
            response = f"I couldn't find job **{job_id}**. Would you like to see all your jobs instead? Just ask 'show my job status' or 'list my jobs'."
        else:
            response = "You don't have any costing jobs yet. Would you like to create one? Just describe the work you need done and provide your boat model!"
        return {
            "messages": [AIMessage(content=response)],
            "last_mentioned_job_id": job_id if job_id else None,
        }

    # Build structured context
    status_context = _build_status_context(job_statuses, job_id, wants_details)

    # Generate conversational response using LLM
    try:
        result = _status_chain.invoke({
            "status_context": status_context,
            "user_query": user_message
        })

        response = result.content

    except Exception as e:
        print(f"[StatusAgent] LLM error: {e}")
        # Fallback to structured response if LLM fails
        response = f"Here's your job status:\n\n{status_context}"

    return {
        "messages": [AIMessage(content=response)],
        "last_mentioned_job_id": job_id if job_id else None,
    }
