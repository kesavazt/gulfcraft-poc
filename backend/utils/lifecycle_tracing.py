"""
Job Lifecycle Tracing Module

Provides duration tracking and lifecycle event logging for costing jobs.
Uses Langfuse for trace storage and database timestamps for persistence.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from enum import Enum
import uuid

from utils.langfuse_tracing import _get_langfuse_client, span_context, trace_operation


class JobLifecycleEvent(str, Enum):
    """Enumeration of job lifecycle events."""
    JOB_CREATED = "job.created"
    QUOTE_REQUESTED = "job.quote_requested"
    QUOTE_RECEIVED = "job.quote_received"
    ALL_QUOTES_RECEIVED = "job.all_quotes_received"
    JOB_READY = "job.ready"
    JOB_APPROVED = "job.approved"
    JOB_CANCELLED = "job.cancelled"
    JOB_DUPLICATED = "job.duplicated"
    SHEET_GENERATED = "job.sheet_generated"
    SHEET_EMAILED = "job.sheet_emailed"


def log_lifecycle_event(
    job_id: str,
    event: JobLifecycleEvent,
    user_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Logs a job lifecycle event to Langfuse.

    Args:
        job_id: The costing job ID
        event: The lifecycle event type
        user_id: Optional user ID
        metadata: Optional additional metadata
    """
    client = _get_langfuse_client()
    if not client:
        return

    try:
        event_metadata = {
            "event_type": "lifecycle",
            "job_id": job_id,
            "event": event.value,
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            **(metadata or {})
        }

        # Create an observation for this lifecycle event
        event_metadata["session_id"] = job_id  # Track job grouping in metadata
        observation = client.start_observation(
            name=event.value,
            as_type="event",
            metadata=event_metadata
        )
        observation.end()
        client.flush()

        print(f"[Lifecycle] {event.value} logged for {job_id}")

    except Exception as e:
        print(f"[Lifecycle] Error logging event {event.value}: {e}")


def log_quote_request_sent(
    job_id: str,
    item_name: str,
    vendor_email: str,
    item_code: Optional[str] = None,
    user_id: Optional[int] = None
) -> None:
    """Logs when a quote request email is sent."""
    log_lifecycle_event(
        job_id=job_id,
        event=JobLifecycleEvent.QUOTE_REQUESTED,
        user_id=user_id,
        metadata={
            "item_name": item_name,
            "item_code": item_code,
            "vendor_email": vendor_email
        }
    )


def log_quote_received(
    job_id: str,
    item_name: str,
    price: float,
    vendor_email: Optional[str] = None,
    user_id: Optional[int] = None
) -> None:
    """Logs when a quote is received for an item."""
    log_lifecycle_event(
        job_id=job_id,
        event=JobLifecycleEvent.QUOTE_RECEIVED,
        user_id=user_id,
        metadata={
            "item_name": item_name,
            "price": price,
            "vendor_email": vendor_email
        }
    )


def log_job_created(
    job_id: str,
    user_id: int,
    quotation_id: Optional[str] = None,
    description: Optional[str] = None,
    item_count: int = 0,
    pending_quote_count: int = 0
) -> None:
    """Logs when a new costing job is created."""
    log_lifecycle_event(
        job_id=job_id,
        event=JobLifecycleEvent.JOB_CREATED,
        user_id=user_id,
        metadata={
            "quotation_id": quotation_id,
            "description": description,
            "item_count": item_count,
            "pending_quote_count": pending_quote_count
        }
    )


def log_job_ready(
    job_id: str,
    user_id: Optional[int] = None,
    total_price: Optional[float] = None
) -> None:
    """Logs when all quotes are received and job is ready."""
    log_lifecycle_event(
        job_id=job_id,
        event=JobLifecycleEvent.JOB_READY,
        user_id=user_id,
        metadata={
            "total_price": total_price
        }
    )


def log_job_approved(
    job_id: str,
    user_id: int,
    final_price: Optional[float] = None,
    created_at: Optional[datetime] = None,
    quotes_requested_at: Optional[datetime] = None,
    all_quotes_received_at: Optional[datetime] = None
) -> None:
    """Logs when a job is approved and records duration scores."""
    log_lifecycle_event(
        job_id=job_id,
        event=JobLifecycleEvent.JOB_APPROVED,
        user_id=user_id,
        metadata={
            "final_price": final_price
        }
    )

    # Log duration scores to Langfuse for dashboard analytics
    client = _get_langfuse_client()
    if client and created_at:
        try:
            approved_at = datetime.now(timezone.utc)

            # Ensure created_at is timezone-aware for subtraction
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            # Generate a valid 32-char hex trace ID from job_id
            trace_id = uuid.uuid5(uuid.NAMESPACE_URL, f"job_{job_id}").hex

            # Total time to approval (hours)
            total_hours = (approved_at - created_at).total_seconds() / 3600
            client.score(
                name="time_to_approval_hours",
                value=round(total_hours, 2),
                trace_id=trace_id,
                comment=f"Job {job_id}: {total_hours:.1f}h from creation to approval"
            )

            # Quote wait time (if applicable)
            if quotes_requested_at and all_quotes_received_at:
                if quotes_requested_at.tzinfo is None:
                    quotes_requested_at = quotes_requested_at.replace(tzinfo=timezone.utc)
                if all_quotes_received_at.tzinfo is None:
                    all_quotes_received_at = all_quotes_received_at.replace(tzinfo=timezone.utc)
                quote_wait_hours = (all_quotes_received_at - quotes_requested_at).total_seconds() / 3600
                client.score(
                    name="quote_wait_time_hours",
                    value=round(quote_wait_hours, 2),
                    trace_id=trace_id,
                    comment=f"Job {job_id}: Waited {quote_wait_hours:.1f}h for all quotes"
                )

            # Time from ready to approval
            if all_quotes_received_at:
                if all_quotes_received_at.tzinfo is None:
                    all_quotes_received_at = all_quotes_received_at.replace(tzinfo=timezone.utc)
                approval_delay_hours = (approved_at - all_quotes_received_at).total_seconds() / 3600
                client.score(
                    name="approval_delay_hours",
                    value=round(approval_delay_hours, 2),
                    trace_id=trace_id,
                    comment=f"Job {job_id}: Ready to approved: {approval_delay_hours:.1f}h"
                )

            client.flush()
        except Exception as e:
            print(f"[Lifecycle] Error logging duration scores: {e}")


def log_job_cancelled(
    job_id: str,
    user_id: int,
    reason: Optional[str] = None
) -> None:
    """Logs when a job is cancelled."""
    log_lifecycle_event(
        job_id=job_id,
        event=JobLifecycleEvent.JOB_CANCELLED,
        user_id=user_id,
        metadata={
            "reason": reason
        }
    )


def log_job_duplicated(
    original_job_id: str,
    new_job_id: str,
    user_id: int
) -> None:
    """Logs when a job is duplicated."""
    log_lifecycle_event(
        job_id=new_job_id,
        event=JobLifecycleEvent.JOB_DUPLICATED,
        user_id=user_id,
        metadata={
            "original_job_id": original_job_id
        }
    )


def calculate_job_durations(
    created_at: datetime,
    quotes_requested_at: Optional[datetime] = None,
    all_quotes_received_at: Optional[datetime] = None,
    approved_at: Optional[datetime] = None,
    cancelled_at: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Calculates duration metrics for a job lifecycle.

    Returns:
        Dictionary with duration metrics in seconds and human-readable format
    """
    durations = {}

    def format_duration(td: timedelta) -> str:
        """Format timedelta as human-readable string."""
        total_seconds = int(td.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if seconds > 0 or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    # Time from creation to first quote request
    if quotes_requested_at:
        duration = quotes_requested_at - created_at
        durations["creation_to_quote_request"] = {
            "seconds": duration.total_seconds(),
            "formatted": format_duration(duration)
        }

    # Time from first quote request to all quotes received
    if quotes_requested_at and all_quotes_received_at:
        duration = all_quotes_received_at - quotes_requested_at
        durations["quote_request_to_all_received"] = {
            "seconds": duration.total_seconds(),
            "formatted": format_duration(duration)
        }

    # Time from all quotes received to approval
    if all_quotes_received_at and approved_at:
        duration = approved_at - all_quotes_received_at
        durations["ready_to_approval"] = {
            "seconds": duration.total_seconds(),
            "formatted": format_duration(duration)
        }

    # Total time from creation to approval
    if approved_at:
        duration = approved_at - created_at
        durations["total_time_to_approval"] = {
            "seconds": duration.total_seconds(),
            "formatted": format_duration(duration)
        }

    # Total time from creation to cancellation
    if cancelled_at:
        duration = cancelled_at - created_at
        durations["total_time_to_cancellation"] = {
            "seconds": duration.total_seconds(),
            "formatted": format_duration(duration)
        }

    # Current status duration (if still in progress)
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if not approved_at and not cancelled_at:
        duration = now - created_at
        durations["time_since_creation"] = {
            "seconds": duration.total_seconds(),
            "formatted": format_duration(duration)
        }

        if quotes_requested_at and not all_quotes_received_at:
            duration = now - quotes_requested_at
            durations["time_awaiting_quotes"] = {
                "seconds": duration.total_seconds(),
                "formatted": format_duration(duration)
            }

    return durations


def get_job_metrics(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves comprehensive metrics for a job including durations.

    Args:
        job_id: The costing job ID

    Returns:
        Dictionary with job metrics or None if job not found
    """
    from core.database import SessionLocal, CostingRequest, CostingLineItem, PendingQuoteRequest

    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            return None

        # Get line items
        line_items = session.query(CostingLineItem).filter(
            CostingLineItem.costing_request_id == costing_req.id
        ).all()

        # Get quote requests
        quote_requests = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.costing_request_id == costing_req.id
        ).all()

        # Count items by status
        total_items = len(line_items)
        resolved_items = sum(1 for li in line_items if li.price_status == "resolved")
        pending_items = sum(1 for li in line_items if li.price_status in ("pending", "pending_quote"))

        # Quote request stats
        total_quote_requests = len(quote_requests)
        pending_quotes = sum(1 for qr in quote_requests if qr.status == "pending")
        received_quotes = sum(1 for qr in quote_requests if qr.status == "received")

        # Calculate durations
        durations = calculate_job_durations(
            created_at=costing_req.created_at,
            quotes_requested_at=costing_req.quotes_requested_at,
            all_quotes_received_at=costing_req.all_quotes_received_at,
            approved_at=costing_req.approved_at,
            cancelled_at=costing_req.cancelled_at
        )

        # Calculate average quote response time
        quote_response_times = []
        for qr in quote_requests:
            if qr.status == "received" and qr.received_at and qr.email_sent_at:
                response_time = (qr.received_at - qr.email_sent_at).total_seconds()
                quote_response_times.append(response_time)

        avg_quote_response_time = None
        if quote_response_times:
            avg_seconds = sum(quote_response_times) / len(quote_response_times)
            hours = int(avg_seconds // 3600)
            minutes = int((avg_seconds % 3600) // 60)
            avg_quote_response_time = {
                "seconds": avg_seconds,
                "formatted": f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            }

        return {
            "job_id": job_id,
            "status": costing_req.status,
            "created_at": costing_req.created_at.isoformat() if costing_req.created_at else None,
            "updated_at": costing_req.updated_at.isoformat() if costing_req.updated_at else None,
            "quotes_requested_at": costing_req.quotes_requested_at.isoformat() if costing_req.quotes_requested_at else None,
            "all_quotes_received_at": costing_req.all_quotes_received_at.isoformat() if costing_req.all_quotes_received_at else None,
            "approved_at": costing_req.approved_at.isoformat() if costing_req.approved_at else None,
            "cancelled_at": costing_req.cancelled_at.isoformat() if costing_req.cancelled_at else None,
            "original_job_id": costing_req.original_job_id,
            "item_metrics": {
                "total_items": total_items,
                "resolved_items": resolved_items,
                "pending_items": pending_items,
                "completion_percentage": round((resolved_items / total_items * 100), 1) if total_items > 0 else 100
            },
            "quote_metrics": {
                "total_quote_requests": total_quote_requests,
                "pending_quotes": pending_quotes,
                "received_quotes": received_quotes,
                "avg_response_time": avg_quote_response_time
            },
            "durations": durations
        }

    except Exception as e:
        print(f"[Metrics] Error getting metrics for {job_id}: {e}")
        return None
    finally:
        session.close()


def get_aggregate_metrics(
    user_id: Optional[int] = None,
    days: int = 30
) -> Dict[str, Any]:
    """
    Retrieves aggregate metrics across multiple jobs.

    Args:
        user_id: Optional user ID to filter by
        days: Number of days to look back

    Returns:
        Dictionary with aggregate metrics
    """
    from core.database import SessionLocal, CostingRequest
    from sqlalchemy import func

    session = SessionLocal()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        query = session.query(CostingRequest).filter(
            CostingRequest.created_at >= cutoff_date
        )

        if user_id:
            query = query.filter(CostingRequest.user_id == user_id)

        jobs = query.all()

        if not jobs:
            return {
                "period_days": days,
                "total_jobs": 0,
                "message": "No jobs found in the specified period"
            }

        # Count by status
        status_counts = {}
        for job in jobs:
            status_counts[job.status] = status_counts.get(job.status, 0) + 1

        # Calculate average durations for completed/approved jobs
        approval_times = []
        quote_wait_times = []

        for job in jobs:
            if job.approved_at and job.created_at:
                approval_times.append((job.approved_at - job.created_at).total_seconds())

            if job.all_quotes_received_at and job.quotes_requested_at:
                quote_wait_times.append((job.all_quotes_received_at - job.quotes_requested_at).total_seconds())

        def format_avg_duration(seconds_list: List[float]) -> Optional[Dict[str, Any]]:
            if not seconds_list:
                return None
            avg_seconds = sum(seconds_list) / len(seconds_list)
            days = int(avg_seconds // 86400)
            hours = int((avg_seconds % 86400) // 3600)
            minutes = int((avg_seconds % 3600) // 60)

            parts = []
            if days > 0:
                parts.append(f"{days}d")
            if hours > 0:
                parts.append(f"{hours}h")
            if minutes > 0:
                parts.append(f"{minutes}m")

            return {
                "seconds": avg_seconds,
                "formatted": " ".join(parts) if parts else "< 1m",
                "sample_count": len(seconds_list)
            }

        return {
            "period_days": days,
            "total_jobs": len(jobs),
            "status_breakdown": status_counts,
            "avg_time_to_approval": format_avg_duration(approval_times),
            "avg_quote_wait_time": format_avg_duration(quote_wait_times),
            "jobs_pending_quotes": sum(1 for j in jobs if j.status == "Awaiting Quote"),
            "jobs_ready": sum(1 for j in jobs if j.status == "Completed"),
            "jobs_approved": sum(1 for j in jobs if j.status == "Approved")
        }

    except Exception as e:
        print(f"[Metrics] Error getting aggregate metrics: {e}")
        return {"error": str(e)}
    finally:
        session.close()
