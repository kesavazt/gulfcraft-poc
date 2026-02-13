"""
Transition Logger

Logs and visualizes agent transitions for debugging and analytics.
Provides insights into conversation flow and agent usage patterns.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from core.database import SessionLocal, AgentTransitionLog
from sqlalchemy.exc import SQLAlchemyError


class TransitionLogger:
    """
    Logs and visualizes agent transitions for debugging.

    Features:
    - Log transitions to database
    - Generate ASCII flow diagrams
    - Provide transition analytics
    """

    def log_transition(
        self,
        conversation_id: str,
        from_agent: Optional[str],
        to_agent: str,
        routing_reason: Optional[str] = None
    ) -> bool:
        """
        Save transition to database for analysis.

        Args:
            conversation_id: Conversation ID
            from_agent: Source agent (None for entry point)
            to_agent: Target agent
            routing_reason: Why transition happened

        Returns:
            bool: True if logged successfully
        """
        db = SessionLocal()
        try:
            log = AgentTransitionLog(
                conversation_id=conversation_id,
                from_agent=from_agent,
                to_agent=to_agent,
                routing_reason=routing_reason,
                timestamp=datetime.utcnow()
            )
            db.add(log)
            db.commit()
            return True
        except SQLAlchemyError as e:
            print(f"[TransitionLogger] Error logging transition: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def visualize_flow(self, conversation_id: str) -> str:
        """
        Generate ASCII flow diagram of agent transitions.

        Args:
            conversation_id: Conversation ID

        Returns:
            str: ASCII flow diagram
        """
        db = SessionLocal()
        try:
            logs = db.query(AgentTransitionLog)\
                .filter_by(conversation_id=conversation_id)\
                .order_by(AgentTransitionLog.timestamp)\
                .all()

            if not logs:
                return "No transitions found for this conversation."

            # Build flow diagram
            flow = "Agent Transition Flow:\n"
            flow += "=" * 60 + "\n\n"

            for i, log in enumerate(logs):
                from_node = log.from_agent or "START"
                to_node = log.to_agent
                reason = log.routing_reason or "user_requested"

                # Format timestamp
                timestamp = log.timestamp.strftime("%H:%M:%S")

                # Build transition line
                flow += f"[{timestamp}] {from_node:20} → {to_node:20} ({reason})\n"

            flow += "\n" + "=" * 60

            return flow
        finally:
            db.close()

    def get_raw_transitions(self, conversation_id: str) -> List[Dict[str, Any]]:
        """
        Get raw transition data for a conversation.

        Args:
            conversation_id: Conversation ID

        Returns:
            list: Transition records
        """
        db = SessionLocal()
        try:
            logs = db.query(AgentTransitionLog)\
                .filter_by(conversation_id=conversation_id)\
                .order_by(AgentTransitionLog.timestamp)\
                .all()

            return [{
                "id": log.id,
                "from_agent": log.from_agent,
                "to_agent": log.to_agent,
                "routing_reason": log.routing_reason,
                "timestamp": log.timestamp.isoformat()
            } for log in logs]
        finally:
            db.close()

    def get_agent_usage_stats(self, limit_conversations: int = 100) -> Dict[str, Any]:
        """
        Get agent usage statistics across recent conversations.

        Args:
            limit_conversations: Number of recent conversations to analyze

        Returns:
            dict: Agent usage statistics
        """
        db = SessionLocal()
        try:
            # Get recent conversation IDs
            recent_conversations = db.query(AgentTransitionLog.conversation_id)\
                .distinct()\
                .order_by(AgentTransitionLog.timestamp.desc())\
                .limit(limit_conversations)\
                .all()

            conversation_ids = [c[0] for c in recent_conversations]

            if not conversation_ids:
                return {"total_transitions": 0, "agent_usage": {}, "common_flows": []}

            # Count transitions per agent
            logs = db.query(AgentTransitionLog)\
                .filter(AgentTransitionLog.conversation_id.in_(conversation_ids))\
                .all()

            # Agent usage counts
            agent_usage = {}
            for log in logs:
                agent = log.to_agent
                agent_usage[agent] = agent_usage.get(agent, 0) + 1

            # Common transition patterns
            transition_counts = {}
            for log in logs:
                from_agent = log.from_agent or "START"
                to_agent = log.to_agent
                key = f"{from_agent} → {to_agent}"
                transition_counts[key] = transition_counts.get(key, 0) + 1

            # Sort and get top 10 transitions
            common_flows = sorted(
                transition_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]

            return {
                "total_transitions": len(logs),
                "conversations_analyzed": len(conversation_ids),
                "agent_usage": agent_usage,
                "common_flows": [
                    {"flow": flow, "count": count}
                    for flow, count in common_flows
                ]
            }
        finally:
            db.close()

    def get_conversation_complexity(self, conversation_id: str) -> Dict[str, Any]:
        """
        Analyze conversation complexity based on transitions.

        Args:
            conversation_id: Conversation ID

        Returns:
            dict: Complexity metrics
        """
        db = SessionLocal()
        try:
            logs = db.query(AgentTransitionLog)\
                .filter_by(conversation_id=conversation_id)\
                .order_by(AgentTransitionLog.timestamp)\
                .all()

            if not logs:
                return {
                    "total_transitions": 0,
                    "unique_agents": 0,
                    "avg_transitions_per_agent": 0,
                    "complexity_score": 0
                }

            # Count unique agents
            unique_agents = set()
            for log in logs:
                if log.from_agent:
                    unique_agents.add(log.from_agent)
                unique_agents.add(log.to_agent)

            # Calculate metrics
            total_transitions = len(logs)
            unique_agent_count = len(unique_agents)
            avg_transitions = total_transitions / max(1, unique_agent_count)

            # Complexity score (0-100)
            # Based on: transitions + unique agents + back-and-forth patterns
            back_forth_count = 0
            for i in range(len(logs) - 1):
                if logs[i].to_agent == logs[i+1].from_agent and \
                   logs[i].from_agent == logs[i+1].to_agent:
                    back_forth_count += 1

            complexity_score = min(100, (
                (total_transitions * 2) +
                (unique_agent_count * 5) +
                (back_forth_count * 10)
            ))

            return {
                "total_transitions": total_transitions,
                "unique_agents": unique_agent_count,
                "avg_transitions_per_agent": round(avg_transitions, 2),
                "back_forth_patterns": back_forth_count,
                "complexity_score": complexity_score,
                "complexity_level": (
                    "Low" if complexity_score < 30 else
                    "Medium" if complexity_score < 70 else
                    "High"
                )
            }
        finally:
            db.close()

    def get_transition_timeline(self, conversation_id: str) -> List[Dict[str, Any]]:
        """
        Get timeline of transitions with duration between each.

        Args:
            conversation_id: Conversation ID

        Returns:
            list: Timeline with durations
        """
        db = SessionLocal()
        try:
            logs = db.query(AgentTransitionLog)\
                .filter_by(conversation_id=conversation_id)\
                .order_by(AgentTransitionLog.timestamp)\
                .all()

            timeline = []
            for i, log in enumerate(logs):
                duration_seconds = None
                if i > 0:
                    prev_log = logs[i-1]
                    duration = log.timestamp - prev_log.timestamp
                    duration_seconds = duration.total_seconds()

                timeline.append({
                    "from_agent": log.from_agent,
                    "to_agent": log.to_agent,
                    "routing_reason": log.routing_reason,
                    "timestamp": log.timestamp.isoformat(),
                    "duration_since_last_seconds": duration_seconds
                })

            return timeline
        finally:
            db.close()
