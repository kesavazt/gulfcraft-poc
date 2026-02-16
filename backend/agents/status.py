"""
Status Agent Node

Provides conversational job status summaries and pending/available product lists.
Supports follow-up queries: awaiting quotes, wait duration, vendor info.
"""

import re
from datetime import datetime, timezone
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


def _format_price(value) -> str:
    """Format a price value for display."""
    if value is None:
        return "-"
    return f"{value:,.2f}"


def _time_ago(iso_str: str) -> str:
    """Convert ISO datetime string to a human-readable 'time ago' string."""
    if not iso_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        days = delta.days
        hours = delta.seconds // 3600

        if days > 0:
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif hours > 0:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    except (ValueError, TypeError):
        return "unknown"


def _detect_focus(msg_lower: str) -> str:
    """Detect what specific aspect the user is asking about.

    Returns one of: 'awaiting_quotes', 'vendors', 'waiting_duration', 'all_details', or ''.
    """
    if any(k in msg_lower for k in [
        "awaiting quote", "awaiting quotes", "waiting for quote",
        "pending quote", "which items are awaiting", "what is pending",
        "what's pending", "still waiting"
    ]):
        return "awaiting_quotes"

    if any(k in msg_lower for k in [
        "vendor", "vendors", "who was sent", "which vendor",
        "sent to whom", "supplier", "who did we send"
    ]):
        return "vendors"

    if any(k in msg_lower for k in [
        "how long", "waiting time", "wait time", "since when",
        "how many days", "duration", "overdue"
    ]):
        return "waiting_duration"

    return ""


def _build_line_items_table(line_items: list) -> str:
    """Build a markdown table of line items from costing_line_items data."""
    if not line_items:
        return "No line items found."

    rows = []
    rows.append("| # | Item Name | Item Code | Qty | Unit Price | Price Status | Price Source |")
    rows.append("|---|-----------|-----------|-----|------------|--------------|-------------|")

    for idx, item in enumerate(line_items, 1):
        name = item.get("item_name") or "N/A"
        code = item.get("item_code") or "-"
        qty = item.get("quantity") or 1
        price = _format_price(item.get("unit_price"))
        status = item.get("price_status") or "unknown"
        source = item.get("price_source") or "-"
        rows.append(f"| {idx} | {name} | {code} | {qty} | {price} | {status} | {source} |")

    return "\n".join(rows)


def _build_awaiting_quotes_context(job: dict) -> str:
    """Build context focused on items awaiting quotes."""
    quote_requests = job.get("quote_requests", [])
    pending_quotes = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "pending"]
    received_quotes = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "received"]

    parts = [f"Job ID: {job.get('job_id')}", f"Description: {job.get('item_details') or 'N/A'}", ""]

    if pending_quotes:
        parts.append(f"### Items Awaiting Quotes ({len(pending_quotes)})")
        parts.append("| # | Item Name | Vendor Email | Sent | Waiting |")
        parts.append("|---|-----------|-------------|------|---------|")
        for idx, qr in enumerate(pending_quotes, 1):
            name = qr.get("item_name") or "N/A"
            vendor = qr.get("vendor_email") or "-"
            sent_at = qr.get("sent_at") or ""
            waiting = _time_ago(sent_at) if sent_at else "-"
            sent_display = sent_at[:10] if sent_at else "-"
            parts.append(f"| {idx} | {name} | {vendor} | {sent_display} | {waiting} |")
    else:
        parts.append("No items are currently awaiting quotes.")

    if received_quotes:
        parts.append(f"\n### Quotes Already Received ({len(received_quotes)})")
        parts.append("| # | Item Name | Price Received | Vendor | Received |")
        parts.append("|---|-----------|---------------|--------|----------|")
        for idx, qr in enumerate(received_quotes, 1):
            name = qr.get("item_name") or "N/A"
            price = _format_price(qr.get("received_price"))
            vendor = qr.get("vendor_email") or "-"
            received_at = qr.get("received_at") or ""
            received_display = received_at[:10] if received_at else "-"
            parts.append(f"| {idx} | {name} | {price} | {vendor} | {received_display} |")

    return "\n".join(parts)


def _build_vendors_context(job: dict) -> str:
    """Build context focused on which vendors were contacted."""
    quote_requests = job.get("quote_requests", [])
    line_items = job.get("line_items", [])

    parts = [f"Job ID: {job.get('job_id')}", f"Description: {job.get('item_details') or 'N/A'}", ""]

    # Group by vendor
    vendor_map = {}
    for qr in quote_requests:
        vendor = qr.get("vendor_email") or "Unknown"
        if vendor not in vendor_map:
            vendor_map[vendor] = []
        vendor_map[vendor].append(qr)

    if vendor_map:
        parts.append("### Vendors Contacted")
        for vendor, items in vendor_map.items():
            pending_count = sum(1 for i in items if (i.get("status") or "").lower() == "pending")
            received_count = sum(1 for i in items if (i.get("status") or "").lower() == "received")
            parts.append(f"\n**{vendor}** — {len(items)} item(s) ({pending_count} pending, {received_count} received)")
            parts.append("| Item | Status | Sent | Received Price |")
            parts.append("|------|--------|------|---------------|")
            for qr in items:
                name = qr.get("item_name") or "N/A"
                status = qr.get("status") or "unknown"
                sent_at = (qr.get("sent_at") or "")[:10] or "-"
                price = _format_price(qr.get("received_price")) if qr.get("received_price") else "-"
                parts.append(f"| {name} | {status} | {sent_at} | {price} |")
    else:
        # Fall back to vendor_email on line items
        vendors_from_items = set()
        for li in line_items:
            v = li.get("vendor_email")
            if v:
                vendors_from_items.add(v)
        if vendors_from_items:
            parts.append("### Assigned Vendors")
            for v in sorted(vendors_from_items):
                items_for_v = [li for li in line_items if li.get("vendor_email") == v]
                parts.append(f"- **{v}**: {', '.join(li.get('item_name') or 'N/A' for li in items_for_v)}")
        else:
            parts.append("No vendor quote requests have been sent for this job yet.")

    return "\n".join(parts)


def _build_waiting_duration_context(job: dict) -> str:
    """Build context focused on how long quotes have been waiting."""
    quote_requests = job.get("quote_requests", [])
    pending_quotes = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "pending"]

    parts = [f"Job ID: {job.get('job_id')}", f"Description: {job.get('item_details') or 'N/A'}", ""]

    if pending_quotes:
        parts.append(f"### Waiting Duration for Pending Quotes ({len(pending_quotes)})")
        parts.append("| # | Item Name | Vendor | Sent On | Waiting Since |")
        parts.append("|---|-----------|--------|---------|--------------|")

        # Sort by longest waiting first
        def _sort_key(qr):
            sent = qr.get("sent_at") or ""
            return sent  # Earlier date = longer wait = sorts first

        for idx, qr in enumerate(sorted(pending_quotes, key=_sort_key), 1):
            name = qr.get("item_name") or "N/A"
            vendor = qr.get("vendor_email") or "-"
            sent_at = qr.get("sent_at") or ""
            sent_display = sent_at[:10] if sent_at else "-"
            waiting = _time_ago(sent_at) if sent_at else "-"
            parts.append(f"| {idx} | {name} | {vendor} | {sent_display} | {waiting} |")

        # Flag long-waiting items
        now = datetime.now(timezone.utc)
        overdue = []
        for qr in pending_quotes:
            sent_at = qr.get("sent_at")
            if sent_at:
                try:
                    dt = datetime.fromisoformat(sent_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if (now - dt).days >= 3:
                        overdue.append(qr)
                except (ValueError, TypeError):
                    pass

        if overdue:
            parts.append(f"\n⚠️ **{len(overdue)} item(s) have been waiting 3+ days** — consider sending a reminder.")
    else:
        parts.append("No items are currently awaiting quotes — all quotes have been received or no requests were sent.")

    return "\n".join(parts)


def _build_status_context(job_statuses: list, specific_job_id: str = None, wants_details: bool = False, focus: str = "") -> str:
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

        # Focused sub-queries
        if focus == "awaiting_quotes":
            return _build_awaiting_quotes_context(job)
        if focus == "vendors":
            return _build_vendors_context(job)
        if focus == "waiting_duration":
            return _build_waiting_duration_context(job)

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

        # Always show line items table when querying a specific job
        if line_items:
            context_parts.append("\n### Line Items")
            context_parts.append(_build_line_items_table(line_items))

            # Calculate total
            total = sum((item.get("unit_price") or 0) * (item.get("quantity") or 1) for item in line_items)
            context_parts.append(f"\n**Total Estimated Cost: {_format_price(total)}**")

        # Add detailed quote information if requested
        if wants_details:
            quote_requests = job.get("quote_requests", [])
            pending_quotes = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "pending"]
            received_quotes = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "received"]

            if pending_quotes:
                context_parts.append("\n### Pending Quote Requests")
                context_parts.append("| Item | Vendor | Sent | Waiting |")
                context_parts.append("|------|--------|------|---------|")
                for qr in pending_quotes:
                    name = qr.get("item_name") or "N/A"
                    vendor = qr.get("vendor_email") or "-"
                    sent_at = qr.get("sent_at") or ""
                    sent_display = sent_at[:10] if sent_at else "-"
                    waiting = _time_ago(sent_at) if sent_at else "-"
                    context_parts.append(f"| {name} | {vendor} | {sent_display} | {waiting} |")

            if received_quotes:
                context_parts.append("\n### Quotes Received")
                context_parts.append("| Item | Vendor | Price | Received |")
                context_parts.append("|------|--------|-------|----------|")
                for qr in received_quotes:
                    name = qr.get("item_name") or "N/A"
                    vendor = qr.get("vendor_email") or "-"
                    price = _format_price(qr.get("received_price"))
                    received_at = (qr.get("received_at") or "")[:10] or "-"
                    context_parts.append(f"| {name} | {vendor} | {price} | {received_at} |")

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
                        vendor = item.get("vendor_email") or "unknown vendor"
                        waiting = _time_ago(sent_at) if sent_at != "unknown" else "unknown"
                        context_parts.append(f"  • {item.get('item_name')} — sent to {vendor} ({waiting})")

                if received_items:
                    for item in received_items:
                        received_at = item.get("received_at") or "unknown"
                        vendor = item.get("vendor_email") or "unknown vendor"
                        price = _format_price(item.get("received_price"))
                        context_parts.append(f"  • {item.get('item_name')} — received from {vendor} at {price}")

        # Add helpful footer
        context_parts.append("\nNote: User can ask for details on a specific job by providing the job ID.")

        return "\n".join(context_parts)


# Build conversational prompt
_status_prompt = ChatPromptTemplate.from_messages([
    ("system", STATUS_AGENT_SYSTEM_PROMPT),
    ("system", """Here is the job status information:

{status_context}

Present this information to the user in a conversational, helpful manner. Follow these guidelines:
1. Start with a brief summary
2. Highlight any urgent items (jobs ready for review, long-pending quotes 3+ days)
3. Use markdown tables for multiple jobs overview (Job ID | Status | Created | Description)
4. For single job details, include the line items / quote markdown tables exactly as provided above - do NOT reformat or omit them
5. End with a helpful next step or offer to help further (e.g. "would you like to resend a reminder?")
6. Keep it concise but informative
7. Preserve all markdown formatting (tables, bold text) from the status context

User's original query: {user_query}"""),
])

_status_chain = _status_prompt | llm


@trace_agent
def status_node(state: AgentState):
    """
    Returns conversational status summaries for the user's costing jobs.
    Supports focused follow-up queries about quotes, vendors, and wait times.
    """
    user_id = state.get("user_id", 1)
    user_message = state["messages"][-1].content if state.get("messages") else ""
    job_id = _extract_job_id(user_message)
    msg_lower = (user_message or "").lower()
    wants_details = any(k in msg_lower for k in [
        "detail", "details", "items", "pending", "quotes", "quote status",
        "breakdown", "line items", "show me", "what's in",
        "awaiting", "vendor", "how long", "waiting", "overdue"
    ])

    # Detect focused sub-query
    focus = _detect_focus(msg_lower)

    # Fall back to last_mentioned_job_id if user asks for details without specifying a job ID
    if not job_id and (wants_details or focus):
        job_id = state.get("last_mentioned_job_id") or ""

    # Detect "first job", "second job", etc. references
    job_index = None
    if "first job" in msg_lower or "1st job" in msg_lower:
        job_index = 0
    elif "second job" in msg_lower or "2nd job" in msg_lower:
        job_index = 1
    elif "third job" in msg_lower or "3rd job" in msg_lower:
        job_index = 2

    # Fetch job statuses
    job_statuses = tools.get_costing_job_statuses(user_id=user_id, job_id=job_id or None)

    # If user referenced a job by index (e.g., "first job"), extract that job's ID
    if job_index is not None and not job_id and job_statuses and len(job_statuses) > job_index:
        job_id = job_statuses[job_index].get("job_id")
        print(f"[StatusAgent] Detected job index {job_index}, extracted job_id: {job_id}")
        print(f"[StatusAgent] Total jobs before re-fetch: {len(job_statuses)}")
        # Re-fetch to get just this job's details
        job_statuses = tools.get_costing_job_statuses(user_id=user_id, job_id=job_id)
        print(f"[StatusAgent] After re-fetch, jobs count: {len(job_statuses)}, first job: {job_statuses[0].get('job_id') if job_statuses else 'None'}")

    # Handle no jobs found
    if not job_statuses:
        if job_id:
            response = f"I couldn't find job **{job_id}**. Would you like to see all your jobs instead? Just ask 'show my job status' or 'list my jobs'."
        else:
            response = "You don't have any costing jobs yet. Would you like to create one? Just describe the work you need done and provide your boat model!"
        return {
            "messages": [AIMessage(content=response)],
            "last_mentioned_job_id": job_id if job_id else state.get("last_mentioned_job_id"),
        }

    # Build structured context
    status_context = _build_status_context(job_statuses, job_id, wants_details, focus)

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

    # Debug logging
    final_job_id = job_id if job_id else state.get("last_mentioned_job_id")
    print(f"[StatusAgent] Setting last_mentioned_job_id to: {final_job_id}")

    return {
        "messages": [AIMessage(content=response)],
        "last_mentioned_job_id": final_job_id,
    }
