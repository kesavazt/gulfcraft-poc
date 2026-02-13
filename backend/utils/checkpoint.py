"""
Checkpoint Manager

Creates recovery points for multi-step workflows (quote requests, job creation).
Enables recovery if agent crashes mid-workflow.
"""

from typing import Optional, Dict, Any
import json
from datetime import datetime
from core.database import SessionLocal, StateCheckpoint
from sqlalchemy.exc import SQLAlchemyError


class CheckpointManager:
    """
    Creates and manages checkpoints for long-running workflows.

    Checkpoint types:
    - quotes_sent: After sending quote request emails
    - costing_sheet_generated: After generating Excel file
    - sharepoint_synced: After SharePoint upload
    - job_created: After creating costing request in DB
    """

    def create_checkpoint(
        self,
        job_id: str,
        checkpoint_type: str,
        state: dict
    ) -> Optional[int]:
        """
        Save checkpoint with type (e.g., "quotes_sent", "costing_generated").
        Enables recovery if agent crashes mid-workflow.

        Args:
            job_id: Costing job ID
            checkpoint_type: Type of checkpoint (quotes_sent, costing_sheet_generated, etc.)
            state: State snapshot to save

        Returns:
            int: Checkpoint ID if successful, None otherwise
        """
        db = SessionLocal()
        try:
            # Prepare state for storage (remove non-serializable fields)
            serializable_state = self._prepare_state_for_storage(state)

            checkpoint = StateCheckpoint(
                job_id=job_id,
                checkpoint_type=checkpoint_type,
                state_snapshot=json.dumps(serializable_state),
                created_at=datetime.utcnow()
            )
            db.add(checkpoint)
            db.commit()
            db.refresh(checkpoint)

            print(f"[Checkpoint] Created checkpoint '{checkpoint_type}' for job {job_id} (ID: {checkpoint.id})")
            return checkpoint.id
        except SQLAlchemyError as e:
            print(f"[Checkpoint] Error creating checkpoint: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def recover_from_checkpoint(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Load last checkpoint for recovery.

        Args:
            job_id: Costing job ID to recover

        Returns:
            dict: Checkpoint data with type, state, and timestamp, or None if not found
        """
        db = SessionLocal()
        try:
            checkpoint = db.query(StateCheckpoint)\
                .filter_by(job_id=job_id)\
                .order_by(StateCheckpoint.created_at.desc())\
                .first()

            if checkpoint:
                state = json.loads(checkpoint.state_snapshot)
                recovery_data = {
                    "checkpoint_id": checkpoint.id,
                    "type": checkpoint.checkpoint_type,
                    "state": state,
                    "timestamp": checkpoint.created_at.isoformat()
                }
                print(f"[Checkpoint] Recovered checkpoint '{checkpoint.checkpoint_type}' for job {job_id}")
                return recovery_data
            else:
                print(f"[Checkpoint] No checkpoints found for job {job_id}")
                return None
        except (SQLAlchemyError, json.JSONDecodeError) as e:
            print(f"[Checkpoint] Error recovering checkpoint: {e}")
            return None
        finally:
            db.close()

    def get_checkpoints(self, job_id: str) -> list:
        """
        Get all checkpoints for a job (for debugging/auditing).

        Args:
            job_id: Costing job ID

        Returns:
            list: All checkpoints for the job
        """
        db = SessionLocal()
        try:
            checkpoints = db.query(StateCheckpoint)\
                .filter_by(job_id=job_id)\
                .order_by(StateCheckpoint.created_at)\
                .all()

            result = []
            for cp in checkpoints:
                result.append({
                    "id": cp.id,
                    "type": cp.checkpoint_type,
                    "timestamp": cp.created_at.isoformat()
                })

            return result
        finally:
            db.close()

    def cleanup_checkpoints(self, job_id: str) -> int:
        """
        Delete all checkpoints for a job (called when job is approved/cancelled).

        Args:
            job_id: Costing job ID

        Returns:
            int: Number of checkpoints deleted
        """
        db = SessionLocal()
        try:
            deleted = db.query(StateCheckpoint)\
                .filter_by(job_id=job_id)\
                .delete()
            db.commit()
            print(f"[Checkpoint] Deleted {deleted} checkpoints for job {job_id}")
            return deleted
        except SQLAlchemyError as e:
            print(f"[Checkpoint] Error cleaning up checkpoints: {e}")
            db.rollback()
            return 0
        finally:
            db.close()

    def _prepare_state_for_storage(self, state: dict) -> dict:
        """
        Remove non-serializable fields before storage.

        Args:
            state: Raw state dictionary

        Returns:
            dict: Serializable state
        """
        serializable = {}

        # Fields to exclude (non-JSON-serializable)
        exclude_fields = {"messages"}

        for key, value in state.items():
            if key not in exclude_fields:
                serializable[key] = value

        return serializable

    def get_checkpoint_by_type(self, job_id: str, checkpoint_type: str) -> Optional[Dict[str, Any]]:
        """
        Load specific checkpoint type for a job.

        Args:
            job_id: Costing job ID
            checkpoint_type: Type of checkpoint to retrieve

        Returns:
            dict: Checkpoint data or None if not found
        """
        db = SessionLocal()
        try:
            checkpoint = db.query(StateCheckpoint)\
                .filter_by(job_id=job_id, checkpoint_type=checkpoint_type)\
                .order_by(StateCheckpoint.created_at.desc())\
                .first()

            if checkpoint:
                state = json.loads(checkpoint.state_snapshot)
                return {
                    "checkpoint_id": checkpoint.id,
                    "type": checkpoint.checkpoint_type,
                    "state": state,
                    "timestamp": checkpoint.created_at.isoformat()
                }
            return None
        except (SQLAlchemyError, json.JSONDecodeError) as e:
            print(f"[Checkpoint] Error retrieving checkpoint: {e}")
            return None
        finally:
            db.close()
