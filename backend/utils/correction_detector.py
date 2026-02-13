"""
Correction Detector

Detects when users are correcting the system's understanding.
Stores corrections for learning and improving NLU over time.
"""

import re
from typing import Optional, Dict, Any, List
from langchain_core.messages import BaseMessage, HumanMessage
from core.database import SessionLocal, UserCorrection


class CorrectionDetector:
    """
    Detects user corrections and stores them for learning.

    Correction patterns:
    - "no, i meant..."
    - "actually, ..."
    - "not X, Y"
    - "wrong, ..."
    - "i said..."
    """

    CORRECTION_PHRASES = [
        r"\bno,?\s+i\s+meant\b",
        r"\bactually\b",
        r"\bi\s+said\b",
        r"\bnot\s+.+?,?\s+.+\b",
        r"\bwrong\b",
        r"\bthat'?s?\s+not\s+what\s+i\s+wanted\b",
        r"\bi\s+didn'?t\s+mean\b",
        r"\binstead\s+of\b",
        r"\blet\s+me\s+clarify\b",
        r"\bto\s+be\s+clear\b"
    ]

    def detect_correction(
        self,
        user_message: str,
        conversation_history: List[BaseMessage],
        last_agent: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if user is correcting previous extraction.

        Args:
            user_message: Current user message
            conversation_history: Recent conversation
            last_agent: Previously active agent

        Returns:
            dict: Correction details or None
                {
                    "is_correction": True,
                    "original_input": "...",
                    "correction_type": "intent" | "entity" | "parameter",
                    "suggested_agent": "...",
                    "confidence": 0.0-1.0
                }
        """
        user_lower = user_message.lower()

        # Check for correction phrases
        has_correction_phrase = any(
            re.search(pattern, user_lower)
            for pattern in self.CORRECTION_PHRASES
        )

        if not has_correction_phrase:
            return None

        # Get previous user message (if available)
        original_input = None
        for i in range(len(conversation_history) - 1, -1, -1):
            msg = conversation_history[i]
            if isinstance(msg, HumanMessage):
                original_input = msg.content
                break

        # Determine correction type based on content
        correction_type = self._classify_correction_type(user_message, last_agent)

        return {
            "is_correction": True,
            "original_input": original_input or "unknown",
            "correction_type": correction_type,
            "last_agent": last_agent,
            "confidence": 0.85 if has_correction_phrase else 0.5
        }

    def _classify_correction_type(self, user_message: str, last_agent: Optional[str]) -> str:
        """
        Classify type of correction.

        Args:
            user_message: User's correction message
            last_agent: Previously active agent

        Returns:
            str: "intent", "entity", or "parameter"
        """
        user_lower = user_message.lower()

        # Intent correction - user wants different agent
        intent_keywords = ["not search", "not status", "not add", "not edit", "don't want"]
        if any(kw in user_lower for kw in intent_keywords):
            return "intent"

        # Entity correction - wrong item/job/quotation
        entity_keywords = ["wrong job", "wrong item", "different quotation", "other job"]
        if any(kw in user_lower for kw in entity_keywords):
            return "entity"

        # Parameter correction - wrong value
        parameter_keywords = ["not that", "different", "instead", "should be"]
        if any(kw in user_lower for kw in parameter_keywords):
            return "parameter"

        # Default to parameter correction
        return "parameter"

    def store_correction(
        self,
        user_id: int,
        conversation_id: str,
        original_input: str,
        extracted_intent: str,
        corrected_intent: str,
        correction_type: str
    ) -> bool:
        """
        Store correction in database for learning.

        Args:
            user_id: User ID
            conversation_id: Conversation ID
            original_input: Original user message
            extracted_intent: What system extracted
            corrected_intent: What user actually meant
            correction_type: Type of correction

        Returns:
            bool: True if stored successfully
        """
        db = SessionLocal()
        try:
            correction = UserCorrection(
                user_id=user_id,
                conversation_id=conversation_id,
                original_input=original_input,
                extracted_intent=extracted_intent,
                corrected_intent=corrected_intent,
                correction_type=correction_type
            )
            db.add(correction)
            db.commit()
            print(f"[CorrectionDetector] Stored {correction_type} correction")
            return True
        except Exception as e:
            print(f"[CorrectionDetector] Error storing correction: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def get_recent_corrections(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent corrections for analysis.

        Args:
            limit: Maximum number of corrections to retrieve

        Returns:
            list: Recent corrections
        """
        db = SessionLocal()
        try:
            corrections = db.query(UserCorrection)\
                .order_by(UserCorrection.created_at.desc())\
                .limit(limit)\
                .all()

            return [{
                "id": c.id,
                "original_input": c.original_input,
                "extracted_intent": c.extracted_intent,
                "corrected_intent": c.corrected_intent,
                "correction_type": c.correction_type,
                "created_at": c.created_at.isoformat()
            } for c in corrections]
        finally:
            db.close()

    def get_correction_stats(self) -> Dict[str, Any]:
        """
        Get statistics on corrections for monitoring.

        Returns:
            dict: Correction statistics
        """
        db = SessionLocal()
        try:
            total = db.query(UserCorrection).count()

            # Count by type
            intent_count = db.query(UserCorrection)\
                .filter_by(correction_type="intent")\
                .count()
            entity_count = db.query(UserCorrection)\
                .filter_by(correction_type="entity")\
                .count()
            parameter_count = db.query(UserCorrection)\
                .filter_by(correction_type="parameter")\
                .count()

            return {
                "total_corrections": total,
                "by_type": {
                    "intent": intent_count,
                    "entity": entity_count,
                    "parameter": parameter_count
                },
                "correction_rate": round(total / max(1, total) * 100, 2)  # Placeholder
            }
        finally:
            db.close()

    def generate_few_shot_examples(self, correction_type: str, limit: int = 5) -> List[str]:
        """
        Generate few-shot examples from corrections for prompt enhancement.

        Args:
            correction_type: Type of correction to generate examples for
            limit: Maximum number of examples

        Returns:
            list: Few-shot example strings
        """
        db = SessionLocal()
        try:
            corrections = db.query(UserCorrection)\
                .filter_by(correction_type=correction_type)\
                .order_by(UserCorrection.created_at.desc())\
                .limit(limit)\
                .all()

            examples = []
            for c in corrections:
                example = f"Input: '{c.original_input}' → Correct intent: '{c.corrected_intent}'"
                examples.append(example)

            return examples
        finally:
            db.close()
