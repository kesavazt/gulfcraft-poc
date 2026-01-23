"""
Status Agent Node

Provides job status summaries and pending/available product lists.
"""

import re
from langchain_core.messages import AIMessage
from core.state import AgentState
from utils import tools


def _extract_job_id(message: str) -> str:
    """Extract a job_id like COST-XXXXXXXX from the message."""
    if not message:
        return ""
    match = re.search(r"(COST-[A-Z0-9]+)", message, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _group_items(line_items: list):
    """Split line items into pending vs available buckets."""
    pending = []
    available = []
    for item in line_items:
        status = (item.get("price_status") or "").lower()
        if status == "resolved":
            available.append(item)
        else:
            pending.append(item)
    return pending, available


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
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return f"{text[:max_len - 3]}..."


def status_node(state: AgentState):
    """
    Returns status summaries for the user's costing jobs.
    """
    user_id = state.get("user_id", 1)
    user_message = state["messages"][-1].content if state.get("messages") else ""
    job_id = _extract_job_id(user_message)
    msg_lower = (user_message or "").lower()
    wants_details = any(k in msg_lower for k in ["detail", "details", "items", "pending", "quotes", "quote status"])

    job_statuses = tools.get_costing_job_statuses(user_id=user_id, job_id=job_id or None)
    if not job_statuses:
        if job_id:
            response = f"I couldn't find a job with ID {job_id}. If you want all jobs, just ask for your job status."
        else:
            response = "I couldn't find any costing jobs yet. Create a quotation request to get started."
        return {"messages": [AIMessage(content=response)]}

    response_lines = []

    if not job_id:
        response_lines.append("Here are your costing jobs:")
        response_lines.append("| Job ID | Status | Created | Description |")
        response_lines.append("| --- | --- | --- | --- |")
        for job in job_statuses:
            response_lines.append(
                f"| {job.get('job_id')} | {_status_label(job.get('status'))} | {job.get('created_at') or 'N/A'} | {_truncate(job.get('item_details') or '', 60) or 'N/A'} |"
            )

        if wants_details:
            awaiting_jobs = [
                j for j in job_statuses
                if _status_label(j.get("status")) == "Waiting for quotes"
            ]
            if awaiting_jobs:
                response_lines.append("")
                response_lines.append("Pending job details:")
                for job in awaiting_jobs:
                    response_lines.append(f"**{job.get('job_id')}**")
                    quote_requests = job.get("quote_requests", [])
                    pending_items = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "pending"]
                    received_items = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "received"]
                    if pending_items:
                        response_lines.append("Pending items:")
                        for item in pending_items:
                            sent_at = item.get("sent_at") or "unknown"
                            response_lines.append(f"- {item.get('item_name')} (request sent {sent_at})")
                    if received_items:
                        response_lines.append("Quotes received:")
                        for item in received_items:
                            received_at = item.get("received_at") or "unknown"
                            response_lines.append(f"- {item.get('item_name')} (received {received_at})")
                    if not pending_items and not received_items:
                        response_lines.append("No pending or received quote items recorded yet.")
                    response_lines.append("")
            else:
                response_lines.append("")
                response_lines.append("No jobs are currently waiting for quotes.")

        response_lines.append("Want details on a specific job? Just share the job ID (e.g., COST-XXXXXXX).")
        return {"messages": [AIMessage(content="\n".join(response_lines).strip())]}

    job = job_statuses[0]
    pending, available = _group_items(job.get("line_items", []))
    response_lines.append(f"Here’s the status for **{job.get('job_id')}**:")
    response_lines.append(f"- Status: {_status_label(job.get('status'))}")
    response_lines.append(f"- Pending products: {len(pending)}")
    response_lines.append(f"- Available products: {len(available)}")

    if wants_details:
        quote_requests = job.get("quote_requests", [])
        pending_items = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "pending"]
        received_items = [qr for qr in quote_requests if (qr.get("status") or "").lower() == "received"]
        if pending_items:
            response_lines.append("")
            response_lines.append("Pending items:")
            for item in pending_items:
                sent_at = item.get("sent_at") or "unknown"
                response_lines.append(f"- {item.get('item_name')} (request sent {sent_at})")
        if received_items:
            response_lines.append("")
            response_lines.append("Quotes received:")
            for item in received_items:
                received_at = item.get("received_at") or "unknown"
                response_lines.append(f"- {item.get('item_name')} (received {received_at})")

    return {"messages": [AIMessage(content="\n".join(response_lines).strip())]}
