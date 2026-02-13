"""
State Manager

Handles agent state persistence, versioning, and migration.
Provides state snapshot save/load with automatic schema migration.
"""

from typing import Optional, Dict, Any
import json
from datetime import datetime, timedelta
from core.database import SessionLocal, ConversationState
from sqlalchemy.exc import SQLAlchemyError

# Current state version - increment when AgentState schema changes
STATE_VERSION = "2.0"


class StateManager:
    """
    Manages agent state with versioning, persistence, and migration.

    Features:
    - Save state snapshots to database with version tags
    - Load and auto-migrate state when schema changes
    - Cleanup expired states (30-day TTL)
    """

    STATE_TTL_DAYS = 30  # Keep state for 30 days

    def save_state(self, conversation_id: str, state: dict, user_id: int) -> bool:
        """
        Persist state to database with version tag.

        Args:
            conversation_id: Unique conversation identifier
            state: AgentState dictionary to persist
            user_id: User ID for the conversation

        Returns:
            bool: True if save successful, False otherwise
        """
        db = SessionLocal()
        try:
            # Remove non-serializable fields (messages, etc.)
            serializable_state = self._prepare_state_for_storage(state)

            state_snapshot = ConversationState(
                conversation_id=conversation_id,
                user_id=user_id,
                state_version=STATE_VERSION,
                state_data=json.dumps(serializable_state),
                created_at=datetime.utcnow()
            )
            db.add(state_snapshot)
            db.commit()
            print(f"[StateManager] Saved state for conversation {conversation_id} (v{STATE_VERSION})")
            return True
        except SQLAlchemyError as e:
            print(f"[StateManager] Error saving state: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def load_state(self, conversation_id: str) -> Optional[dict]:
        """
        Load and migrate state if version mismatch.

        Args:
            conversation_id: Unique conversation identifier

        Returns:
            dict: Migrated state or None if not found
        """
        db = SessionLocal()
        try:
            # Get the most recent state snapshot
            snapshot = db.query(ConversationState)\
                .filter_by(conversation_id=conversation_id)\
                .order_by(ConversationState.created_at.desc())\
                .first()

            if not snapshot:
                print(f"[StateManager] No state found for conversation {conversation_id}")
                return None

            state = json.loads(snapshot.state_data)

            # Migrate if old version
            if snapshot.state_version != STATE_VERSION:
                print(f"[StateManager] Migrating state from v{snapshot.state_version} to v{STATE_VERSION}")
                state = self._migrate_state(state, snapshot.state_version, STATE_VERSION)

            return state
        except (SQLAlchemyError, json.JSONDecodeError) as e:
            print(f"[StateManager] Error loading state: {e}")
            return None
        finally:
            db.close()

    def _prepare_state_for_storage(self, state: dict) -> dict:
        """
        Remove non-serializable fields before storage.

        Args:
            state: Raw AgentState dictionary

        Returns:
            dict: Serializable state (without messages, etc.)
        """
        serializable = {}

        # Fields to exclude (non-JSON-serializable)
        exclude_fields = {"messages"}

        for key, value in state.items():
            if key not in exclude_fields:
                # Handle special cases
                if key == "transition_history" and value is None:
                    serializable[key] = []
                else:
                    serializable[key] = value

        return serializable

    def _migrate_state(self, old_state: dict, from_version: str, to_version: str) -> dict:
        """
        Handle state schema migrations between versions.

        Args:
            old_state: State dict from old version
            from_version: Source version
            to_version: Target version

        Returns:
            dict: Migrated state
        """
        migrated = old_state.copy()

        # Migration: v1.0 -> v2.0
        if from_version == "1.0" and to_version == "2.0":
            # Add new fields with defaults
            migrated.setdefault("state_version", "2.0")
            migrated.setdefault("disambiguation_lock", False)
            migrated.setdefault("disambiguation_expires_at", None)
            migrated.setdefault("extraction_failures", 0)
            migrated.setdefault("last_agent", None)
            migrated.setdefault("routing_reason", None)
            migrated.setdefault("routing_context", None)
            migrated.setdefault("transition_history", [])
            migrated.setdefault("handoff_context", None)
            migrated.setdefault("intent_confidence", None)
            migrated.setdefault("clarification_needed", False)

            print(f"[StateManager] Migration 1.0->2.0: Added {len(migrated) - len(old_state)} new fields")

        # Future migrations can be added here:
        # elif from_version == "2.0" and to_version == "3.0":
        #     ...

        return migrated

    def cleanup_expired_states(self) -> int:
        """
        Remove old conversation states beyond TTL.

        Returns:
            int: Number of states deleted
        """
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(days=self.STATE_TTL_DAYS)
            deleted = db.query(ConversationState)\
                .filter(ConversationState.created_at < cutoff)\
                .delete()
            db.commit()
            print(f"[StateManager] Cleaned up {deleted} expired states")
            return deleted
        except SQLAlchemyError as e:
            print(f"[StateManager] Error during cleanup: {e}")
            db.rollback()
            return 0
        finally:
            db.close()

    def get_state_count(self, conversation_id: str) -> int:
        """
        Get number of state snapshots for a conversation.

        Args:
            conversation_id: Unique conversation identifier

        Returns:
            int: Number of snapshots
        """
        db = SessionLocal()
        try:
            count = db.query(ConversationState)\
                .filter_by(conversation_id=conversation_id)\
                .count()
            return count
        finally:
            db.close()
