"""
Tests for Job Lifecycle Duration Tracking

Tests the lifecycle tracing module and job duration metrics functionality.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch


class TestJobLifecycleEvents:
    """Tests for lifecycle event logging functions."""

    def test_job_lifecycle_event_enum(self):
        """Test that all expected lifecycle events are defined."""
        from utils.lifecycle_tracing import JobLifecycleEvent

        expected_events = [
            "job.created",
            "job.quote_requested",
            "job.quote_received",
            "job.all_quotes_received",
            "job.ready",
            "job.approved",
            "job.cancelled",
            "job.duplicated",
            "job.sheet_generated",
            "job.sheet_emailed"
        ]

        for event_value in expected_events:
            assert any(e.value == event_value for e in JobLifecycleEvent), f"Missing event: {event_value}"

    @patch('utils.lifecycle_tracing._get_langfuse_client')
    def test_log_job_created(self, mock_get_client):
        """Test logging job creation event."""
        from utils.lifecycle_tracing import log_job_created

        mock_client = MagicMock()
        mock_observation = MagicMock()
        mock_client.start_observation.return_value = mock_observation
        mock_get_client.return_value = mock_client

        log_job_created(
            job_id="COST-TEST1234",
            user_id=1,
            quotation_id="AJMFQ-000001",
            description="Test job"
        )

        mock_client.start_observation.assert_called_once()
        call_kwargs = mock_client.start_observation.call_args[1]
        assert call_kwargs["name"] == "job.created"
        assert call_kwargs["session_id"] == "COST-TEST1234"
        mock_observation.end.assert_called_once()
        mock_client.flush.assert_called_once()

    @patch('utils.lifecycle_tracing._get_langfuse_client')
    def test_log_quote_request_sent(self, mock_get_client):
        """Test logging quote request event."""
        from utils.lifecycle_tracing import log_quote_request_sent

        mock_client = MagicMock()
        mock_observation = MagicMock()
        mock_client.start_observation.return_value = mock_observation
        mock_get_client.return_value = mock_client

        log_quote_request_sent(
            job_id="COST-TEST1234",
            item_name="Hydraulic Pump",
            vendor_email="vendor@example.com",
            item_code="HYD-001"
        )

        mock_client.start_observation.assert_called_once()
        call_kwargs = mock_client.start_observation.call_args[1]
        assert call_kwargs["name"] == "job.quote_requested"
        assert "item_name" in call_kwargs["metadata"]

    @patch('utils.lifecycle_tracing._get_langfuse_client')
    def test_log_job_approved(self, mock_get_client):
        """Test logging job approval event."""
        from utils.lifecycle_tracing import log_job_approved

        mock_client = MagicMock()
        mock_observation = MagicMock()
        mock_client.start_observation.return_value = mock_observation
        mock_get_client.return_value = mock_client

        log_job_approved(
            job_id="COST-TEST1234",
            user_id=1,
            final_price=5000.0
        )

        mock_client.start_observation.assert_called_once()
        call_kwargs = mock_client.start_observation.call_args[1]
        assert call_kwargs["name"] == "job.approved"

    @patch('utils.lifecycle_tracing._get_langfuse_client')
    def test_graceful_handling_when_langfuse_unavailable(self, mock_get_client):
        """Test that logging functions handle missing Langfuse gracefully."""
        from utils.lifecycle_tracing import log_job_created

        mock_get_client.return_value = None

        # Should not raise any exception
        log_job_created(
            job_id="COST-TEST1234",
            user_id=1
        )


class TestDurationCalculations:
    """Tests for duration calculation functions."""

    def test_calculate_job_durations_with_all_timestamps(self):
        """Test duration calculations with complete lifecycle timestamps."""
        from utils.lifecycle_tracing import calculate_job_durations

        now = datetime.utcnow()
        created_at = now - timedelta(days=5)
        quotes_requested_at = now - timedelta(days=4, hours=12)
        all_quotes_received_at = now - timedelta(days=2)
        approved_at = now - timedelta(hours=6)

        durations = calculate_job_durations(
            created_at=created_at,
            quotes_requested_at=quotes_requested_at,
            all_quotes_received_at=all_quotes_received_at,
            approved_at=approved_at
        )

        assert "creation_to_quote_request" in durations
        assert "quote_request_to_all_received" in durations
        assert "ready_to_approval" in durations
        assert "total_time_to_approval" in durations

        # Verify seconds are positive
        assert durations["creation_to_quote_request"]["seconds"] > 0
        assert durations["total_time_to_approval"]["seconds"] > 0

        # Verify formatted strings exist
        assert "formatted" in durations["total_time_to_approval"]

    def test_calculate_job_durations_partial_timestamps(self):
        """Test duration calculations with partial timestamps (in-progress job)."""
        from utils.lifecycle_tracing import calculate_job_durations

        now = datetime.utcnow()
        created_at = now - timedelta(hours=2)

        durations = calculate_job_durations(created_at=created_at)

        # Should have time_since_creation for in-progress jobs
        assert "time_since_creation" in durations
        assert durations["time_since_creation"]["seconds"] > 0

    def test_calculate_job_durations_cancelled(self):
        """Test duration calculations for cancelled job."""
        from utils.lifecycle_tracing import calculate_job_durations

        now = datetime.utcnow()
        created_at = now - timedelta(days=1)
        cancelled_at = now - timedelta(hours=1)

        durations = calculate_job_durations(
            created_at=created_at,
            cancelled_at=cancelled_at
        )

        assert "total_time_to_cancellation" in durations
        assert durations["total_time_to_cancellation"]["seconds"] > 0

    def test_format_duration_output(self):
        """Test that duration formatting is human-readable."""
        from utils.lifecycle_tracing import calculate_job_durations

        now = datetime.utcnow()
        # 2 days, 5 hours, 30 minutes ago
        created_at = now - timedelta(days=2, hours=5, minutes=30)
        approved_at = now

        durations = calculate_job_durations(
            created_at=created_at,
            approved_at=approved_at
        )

        formatted = durations["total_time_to_approval"]["formatted"]
        assert "2d" in formatted
        assert "5h" in formatted


class TestJobMetrics:
    """Tests for job metrics retrieval."""

    @patch('core.database.SessionLocal')
    def test_get_job_metrics_returns_complete_metrics(self, mock_session_local):
        """Test that get_job_metrics returns all expected fields."""
        from utils.lifecycle_tracing import get_job_metrics

        # Setup mock
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        mock_request = Mock()
        mock_request.job_id = "COST-TEST1234"
        mock_request.status = "Completed"
        mock_request.user_id = 1
        mock_request.created_at = datetime.utcnow() - timedelta(days=1)
        mock_request.updated_at = datetime.utcnow()
        mock_request.quotes_requested_at = datetime.utcnow() - timedelta(hours=20)
        mock_request.all_quotes_received_at = datetime.utcnow() - timedelta(hours=2)
        mock_request.approved_at = None
        mock_request.cancelled_at = None
        mock_request.original_job_id = None
        mock_request.id = 1

        mock_session.query.return_value.filter.return_value.first.return_value = mock_request
        mock_session.query.return_value.filter.return_value.all.return_value = []

        metrics = get_job_metrics("COST-TEST1234")

        assert metrics is not None
        assert metrics["job_id"] == "COST-TEST1234"
        assert "item_metrics" in metrics
        assert "quote_metrics" in metrics
        assert "durations" in metrics

    @patch('core.database.SessionLocal')
    def test_get_job_metrics_job_not_found(self, mock_session_local):
        """Test get_job_metrics returns None for non-existent job."""
        from utils.lifecycle_tracing import get_job_metrics

        mock_session = MagicMock()
        mock_session_local.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        metrics = get_job_metrics("COST-NONEXISTENT")

        assert metrics is None


class TestAggregateMetrics:
    """Tests for aggregate metrics calculation."""

    @patch('core.database.SessionLocal')
    def test_get_aggregate_metrics_basic(self, mock_session_local):
        """Test basic aggregate metrics calculation."""
        from utils.lifecycle_tracing import get_aggregate_metrics

        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        # Create mock jobs
        mock_jobs = []
        for i, status in enumerate(["Completed", "Completed", "Approved", "Awaiting Quote"]):
            mock_job = Mock()
            mock_job.status = status
            mock_job.created_at = datetime.utcnow() - timedelta(days=i)
            mock_job.approved_at = datetime.utcnow() if status == "Approved" else None
            mock_job.quotes_requested_at = datetime.utcnow() - timedelta(days=i, hours=1) if i > 0 else None
            mock_job.all_quotes_received_at = datetime.utcnow() - timedelta(hours=i) if status in ["Completed", "Approved"] else None
            mock_jobs.append(mock_job)

        mock_session.query.return_value.filter.return_value.all.return_value = mock_jobs

        metrics = get_aggregate_metrics(days=30)

        assert metrics["total_jobs"] == 4
        assert "status_breakdown" in metrics
        assert metrics["status_breakdown"]["Completed"] == 2
        assert metrics["status_breakdown"]["Approved"] == 1
        assert metrics["jobs_approved"] == 1

    @patch('core.database.SessionLocal')
    def test_get_aggregate_metrics_empty_period(self, mock_session_local):
        """Test aggregate metrics when no jobs in period."""
        from utils.lifecycle_tracing import get_aggregate_metrics

        mock_session = MagicMock()
        mock_session_local.return_value = mock_session
        mock_session.query.return_value.filter.return_value.all.return_value = []

        metrics = get_aggregate_metrics(days=7)

        assert metrics["total_jobs"] == 0
        assert "message" in metrics


class TestDatabaseTimestampFields:
    """Tests for database model timestamp fields."""

    def test_costing_request_has_lifecycle_fields(self):
        """Test that CostingRequest model has all lifecycle timestamp fields."""
        from core.database import CostingRequest

        # Check that columns exist
        columns = [c.name for c in CostingRequest.__table__.columns]

        lifecycle_fields = [
            "quotes_requested_at",
            "all_quotes_received_at",
            "approved_at",
            "cancelled_at",
            "original_job_id"
        ]

        for field in lifecycle_fields:
            assert field in columns, f"Missing field: {field}"


class TestToolsLifecycleIntegration:
    """Tests for lifecycle tracing integration in tools.py."""

    @patch('utils.tools.log_job_created')
    @patch('utils.tools.SessionLocal')
    def test_create_costing_request_logs_event(self, mock_session_local, mock_log_created):
        """Test that create_costing_request logs lifecycle event."""
        from utils.tools import create_costing_request

        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        job_id = create_costing_request(
            user_id=1,
            quotation_id="AJMFQ-000001",
            line_num=1,
            item_details="Test job"
        )

        mock_log_created.assert_called_once()
        call_kwargs = mock_log_created.call_args[1]
        assert call_kwargs["user_id"] == 1
        assert call_kwargs["quotation_id"] == "AJMFQ-000001"

    @patch('utils.tools.log_job_approved')
    @patch('utils.tools.update_sharepoint_status')
    @patch('utils.tools.SessionLocal')
    def test_approve_costing_job_sets_timestamp_and_logs(self, mock_session_local, mock_sharepoint, mock_log_approved):
        """Test that approve_costing_job sets approved_at and logs event."""
        from utils.tools import approve_costing_job

        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        mock_request = Mock()
        mock_request.job_id = "COST-TEST1234"
        mock_request.status = "Completed"
        mock_request.price = 5000.0
        mock_session.query.return_value.filter.return_value.first.return_value = mock_request

        result = approve_costing_job("COST-TEST1234", user_id=1)

        assert result["success"] is True
        assert mock_request.approved_at is not None
        mock_log_approved.assert_called_once()

    @patch('utils.tools.log_job_cancelled')
    @patch('utils.tools.update_sharepoint_status')
    @patch('utils.tools.SessionLocal')
    def test_cancel_costing_job_sets_timestamp_and_logs(self, mock_session_local, mock_sharepoint, mock_log_cancelled):
        """Test that cancel_costing_job sets cancelled_at and logs event."""
        from utils.tools import cancel_costing_job

        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        mock_request = Mock()
        mock_request.job_id = "COST-TEST1234"
        mock_request.status = "Completed"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_request

        result = cancel_costing_job("COST-TEST1234", user_id=1)

        assert result["success"] is True
        assert mock_request.cancelled_at is not None
        mock_log_cancelled.assert_called_once()


class TestCostingJobCreationWithLifecycleTracing:
    """
    Integration tests for costing job creation with full Langfuse lifecycle tracing.

    Tests the complete flow from job creation through lifecycle events.
    """

    @patch('utils.lifecycle_tracing._get_langfuse_client')
    @patch('core.database.SessionLocal')
    def test_costing_job_creation_logs_lifecycle_event_to_langfuse(
        self, mock_session_local, mock_get_langfuse
    ):
        """
        Test that creating a costing job logs a job.created lifecycle event to Langfuse.

        Verifies:
        - Langfuse client is called with correct event type
        - Session ID is set to job_id for grouping
        - Metadata includes job details
        """
        from utils.tools import create_costing_request

        # Setup mock database session
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        # Setup mock Langfuse client
        mock_langfuse = MagicMock()
        mock_observation = MagicMock()
        mock_langfuse.start_observation.return_value = mock_observation
        mock_get_langfuse.return_value = mock_langfuse

        # Create costing request
        job_id = create_costing_request(
            user_id=1,
            quotation_id="AJMFQ-TEST001",
            line_num=1,
            item_details="Test costing job for lifecycle tracing"
        )

        # Verify job was created
        assert job_id.startswith("COST-")

        # Verify Langfuse was called for lifecycle event
        mock_langfuse.start_observation.assert_called()
        call_kwargs = mock_langfuse.start_observation.call_args[1]

        # Check event name is job.created
        assert call_kwargs["name"] == "job.created"

        # Check session_id is set to job_id for event grouping
        assert call_kwargs["session_id"] == job_id

        # Check metadata contains job details
        assert call_kwargs["metadata"]["event_type"] == "lifecycle"
        assert call_kwargs["metadata"]["job_id"] == job_id
        assert call_kwargs["metadata"]["user_id"] == 1
        assert call_kwargs["metadata"]["quotation_id"] == "AJMFQ-TEST001"

        # Verify observation was ended and flushed
        mock_observation.end.assert_called_once()
        mock_langfuse.flush.assert_called()

    @patch('utils.lifecycle_tracing._get_langfuse_client')
    def test_lifecycle_event_sequence_for_complete_job(self, mock_get_langfuse):
        """
        Test the complete sequence of lifecycle events for a costing job.

        Simulates: created -> quote_requested -> quote_received -> ready -> approved
        """
        from utils.lifecycle_tracing import (
            log_job_created, log_quote_request_sent, log_quote_received,
            log_job_ready, log_job_approved
        )

        mock_langfuse = MagicMock()
        mock_observation = MagicMock()
        mock_langfuse.start_observation.return_value = mock_observation
        mock_get_langfuse.return_value = mock_langfuse

        job_id = "COST-LIFECYCLE01"

        # Step 1: Job created
        log_job_created(
            job_id=job_id,
            user_id=1,
            quotation_id="AJMFQ-000001",
            description="Complete lifecycle test",
            item_count=3,
            pending_quote_count=1
        )

        # Step 2: Quote requested
        log_quote_request_sent(
            job_id=job_id,
            item_name="Hydraulic Pump",
            vendor_email="vendor@example.com",
            item_code="HYD-001"
        )

        # Step 3: Quote received
        log_quote_received(
            job_id=job_id,
            item_name="Hydraulic Pump",
            price=1500.0,
            vendor_email="vendor@example.com"
        )

        # Step 4: Job ready (all quotes received)
        log_job_ready(
            job_id=job_id,
            total_price=5000.0
        )

        # Step 5: Job approved
        log_job_approved(
            job_id=job_id,
            user_id=1,
            final_price=5000.0,
            created_at=datetime.utcnow() - timedelta(days=2)
        )

        # Verify all lifecycle events were logged (5 main events + duration scores)
        assert mock_langfuse.start_observation.call_count >= 5

        # Collect all event names
        event_names = [
            call[1]["name"]
            for call in mock_langfuse.start_observation.call_args_list
        ]

        # Verify all expected events were logged
        assert "job.created" in event_names
        assert "job.quote_requested" in event_names
        assert "job.quote_received" in event_names
        assert "job.ready" in event_names
        assert "job.approved" in event_names

        # Verify all events use same session_id for grouping
        session_ids = [
            call[1]["session_id"]
            for call in mock_langfuse.start_observation.call_args_list
        ]
        assert all(sid == job_id for sid in session_ids)

    @patch('utils.lifecycle_tracing._get_langfuse_client')
    def test_duration_scores_logged_on_approval(self, mock_get_langfuse):
        """
        Test that duration scores are logged to Langfuse when a job is approved.

        Verifies:
        - time_to_approval_hours score is logged
        - quote_wait_time_hours score is logged (if applicable)
        - approval_delay_hours score is logged (if applicable)
        """
        from utils.lifecycle_tracing import log_job_approved

        mock_langfuse = MagicMock()
        mock_observation = MagicMock()
        mock_langfuse.start_observation.return_value = mock_observation
        mock_get_langfuse.return_value = mock_langfuse

        job_id = "COST-DURATION01"
        now = datetime.utcnow()

        log_job_approved(
            job_id=job_id,
            user_id=1,
            final_price=7500.0,
            created_at=now - timedelta(days=3),
            quotes_requested_at=now - timedelta(days=2, hours=12),
            all_quotes_received_at=now - timedelta(days=1)
        )

        # Verify duration scores were logged
        score_calls = mock_langfuse.score.call_args_list
        score_names = [call[1]["name"] for call in score_calls]

        assert "time_to_approval_hours" in score_names
        assert "quote_wait_time_hours" in score_names
        assert "approval_delay_hours" in score_names

        # Verify trace_id is set to job_id
        for call in score_calls:
            assert call[1]["trace_id"] == job_id

    @patch('utils.lifecycle_tracing._get_langfuse_client')
    def test_cancelled_job_lifecycle(self, mock_get_langfuse):
        """Test lifecycle events for a cancelled job."""
        from utils.lifecycle_tracing import log_job_created, log_job_cancelled

        mock_langfuse = MagicMock()
        mock_observation = MagicMock()
        mock_langfuse.start_observation.return_value = mock_observation
        mock_get_langfuse.return_value = mock_langfuse

        job_id = "COST-CANCEL01"

        # Create and then cancel
        log_job_created(job_id=job_id, user_id=1)
        log_job_cancelled(job_id=job_id, user_id=1, reason="Customer request")

        # Verify both events were logged
        event_names = [
            call[1]["name"]
            for call in mock_langfuse.start_observation.call_args_list
        ]

        assert "job.created" in event_names
        assert "job.cancelled" in event_names

        # Verify cancellation reason in metadata
        cancel_call = [
            call for call in mock_langfuse.start_observation.call_args_list
            if call[1]["name"] == "job.cancelled"
        ][0]
        assert cancel_call[1]["metadata"]["reason"] == "Customer request"

    @patch('utils.lifecycle_tracing._get_langfuse_client')
    def test_duplicated_job_lifecycle(self, mock_get_langfuse):
        """Test lifecycle events when a job is duplicated."""
        from utils.lifecycle_tracing import log_job_created, log_job_duplicated

        mock_langfuse = MagicMock()
        mock_observation = MagicMock()
        mock_langfuse.start_observation.return_value = mock_observation
        mock_get_langfuse.return_value = mock_langfuse

        original_job_id = "COST-ORIG01"
        new_job_id = "COST-DUP01"

        # Create original job
        log_job_created(job_id=original_job_id, user_id=1)

        # Duplicate it
        log_job_duplicated(
            original_job_id=original_job_id,
            new_job_id=new_job_id,
            user_id=1
        )

        # Find the duplication event
        dup_call = [
            call for call in mock_langfuse.start_observation.call_args_list
            if call[1]["name"] == "job.duplicated"
        ][0]

        # Verify new job gets the event (session_id = new_job_id)
        assert dup_call[1]["session_id"] == new_job_id

        # Verify original_job_id is in metadata for traceability
        assert dup_call[1]["metadata"]["original_job_id"] == original_job_id
