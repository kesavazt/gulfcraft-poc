"""
OCR Matcher Service
Uses LLM to intelligently match OCR-extracted items from vendor quotations
to pending line items in the database, handling variations in naming.
"""
import sys
import json
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure backend package is discoverable
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core import config
from core.database import SessionLocal, CostingRequest, CostingLineItem, PendingQuoteRequest

# Azure OpenAI API configuration
AZURE_OPENAI_ENDPOINT = config.AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_API_KEY = config.AZURE_OPENAI_API_KEY
AZURE_OPENAI_DEPLOYMENT = config.AZURE_OPENAI_MATCHER_DEPLOYMENT_NAME
AZURE_API_VERSION = "2024-08-01-preview"  # Latest API version


def match_ocr_items_to_pending(
    job_id: str,
    extracted_items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Match OCR-extracted items to pending line items using LLM semantic matching.

    Args:
        job_id: The job ID to match items for
        extracted_items: List of items extracted from vendor quotation PDF
                        Each item should have: item_name, unit_price, quantity

    Returns:
        List of matched items with structure:
        [
            {
                "ocr_item": {...},  # Original OCR item
                "matched_line_item_id": int,  # Database ID of matched line item
                "pending_request_id": int,  # Database ID of pending request
                "confidence": float,  # 0.0 to 1.0
                "match_reason": str  # Explanation of why they match
            }
        ]
    """
    if not extracted_items:
        print(f"[OCR Matcher] No items to match for {job_id}")
        return []

    # Get pending line items from database
    pending_items = _get_pending_items(job_id)

    if not pending_items:
        print(f"[OCR Matcher] No pending items found for {job_id}")
        return []

    print(f"[OCR Matcher] Matching {len(extracted_items)} OCR items to {len(pending_items)} pending items")

    # Use LLM to perform semantic matching
    matches = _llm_match_items(extracted_items, pending_items, job_id)

    return matches


def _get_pending_items(job_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve all pending line items for a job from the database.
    """
    session = SessionLocal()
    try:
        # Get the costing request
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            return []

        # Get pending quote requests with their associated line items
        pending_requests = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.job_id == job_id,
            PendingQuoteRequest.status == "pending"
        ).all()

        # Also get all line items for this costing request
        line_items = session.query(CostingLineItem).filter(
            CostingLineItem.costing_request_id == costing_req.id,
            CostingLineItem.price_status == "pending_quote"
        ).all()

        result = []

        # Build a comprehensive list from pending requests
        for req in pending_requests:
            result.append({
                "pending_request_id": req.id,
                "line_item_id": req.costing_line_item_id,
                "item_name": req.item_name,
                "vendor_email": req.vendor_email
            })

        # Add any line items not already in pending requests
        pending_item_names = {item["item_name"] for item in result}
        for li in line_items:
            if li.item_name not in pending_item_names:
                result.append({
                    "pending_request_id": None,
                    "line_item_id": li.id,
                    "item_name": li.item_name,
                    "vendor_email": li.vendor_email
                })

        print(f"[OCR Matcher] Found {len(result)} pending items in database")
        return result

    except Exception as e:
        print(f"[OCR Matcher] Database error: {e}")
        return []
    finally:
        session.close()


def _llm_match_items(
    ocr_items: List[Dict[str, Any]],
    pending_items: List[Dict[str, Any]],
    job_id: str
) -> List[Dict[str, Any]]:
    """
    Use Azure OpenAI GPT-4.1 mini to semantically match OCR items to pending items.
    """
    if not AZURE_OPENAI_API_KEY or not AZURE_OPENAI_ENDPOINT:
        print("[OCR Matcher] Azure OpenAI not configured, falling back to simple matching")
        return _fallback_simple_match(ocr_items, pending_items)

    # Prepare the matching prompt
    matching_prompt = _build_matching_prompt(ocr_items, pending_items)

    # Azure OpenAI endpoint format
    url = f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version={AZURE_API_VERSION}"

    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_OPENAI_API_KEY
    }

    payload = {
        "messages": [
            {
                "role": "user",
                "content": matching_prompt
            }
        ],
        "temperature": 0.1,  # Low temperature for consistent matching
        "max_tokens": 2000
    }

    try:
        print(f"[OCR Matcher] Calling Azure OpenAI GPT-4.1 mini for semantic matching...")
        response = requests.post(url, headers=headers, json=payload, timeout=60)

        if response.status_code != 200:
            print(f"[OCR Matcher] API Error {response.status_code}: {response.text}")
            return _fallback_simple_match(ocr_items, pending_items)

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Parse the JSON response
        matches = _parse_match_response(content, ocr_items, pending_items)

        print(f"[OCR Matcher] Successfully matched {len(matches)} items using LLM")
        return matches

    except requests.exceptions.Timeout:
        print("[OCR Matcher] API timeout, using fallback matching")
        return _fallback_simple_match(ocr_items, pending_items)
    except Exception as e:
        print(f"[OCR Matcher] Error during LLM matching: {e}")
        return _fallback_simple_match(ocr_items, pending_items)


def _build_matching_prompt(
    ocr_items: List[Dict[str, Any]],
    pending_items: List[Dict[str, Any]]
) -> str:
    """
    Build the prompt for LLM-based item matching.
    """
    prompt = """You are an intelligent item matching system for a marine manufacturing company. Your task is to match items extracted from vendor quotation PDFs to items in our pending purchase requests.

**OCR EXTRACTED ITEMS (from vendor quotation):**
"""

    for i, item in enumerate(ocr_items):
        prompt += f"\nOCR_{i}: {item.get('item_name', 'Unknown')}"
        if item.get('quantity'):
            prompt += f" (Qty: {item['quantity']})"
        if item.get('unit_price'):
            prompt += f" (Price: {item['unit_price']})"

    prompt += "\n\n**PENDING ITEMS (items we requested quotes for):**\n"

    for i, item in enumerate(pending_items):
        prompt += f"\nPENDING_{i}: {item['item_name']}"

    prompt += """

**INSTRUCTIONS:**
1. Match each OCR item to the most appropriate PENDING item
2. Items may be named differently but refer to the same product (e.g., "Marine Paint 5L" = "5 Liter Marine Coating")
3. Consider semantic similarity, abbreviations, specifications, and product codes
4. Assign a confidence score (0.0 to 1.0) for each match:
   - 0.9-1.0: Very likely the same item
   - 0.7-0.89: Probably the same item
   - 0.5-0.69: Possibly the same item
   - Below 0.5: Unlikely match (do not include)
5. Only include matches with confidence >= 0.5
6. If an OCR item doesn't match any pending item, skip it
7. Each pending item can only be matched ONCE (choose the best OCR match)

**OUTPUT FORMAT (JSON only, no other text):**
[
  {
    "ocr_index": 0,
    "pending_index": 2,
    "confidence": 0.95,
    "reason": "Both refer to marine-grade stainless steel bolts with same specifications"
  }
]

Return ONLY the JSON array, nothing else.
"""

    return prompt


def _parse_match_response(
    content: str,
    ocr_items: List[Dict[str, Any]],
    pending_items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Parse the LLM response and build the match result structure.
    """
    try:
        # Extract JSON from response
        start = content.find("[")
        end = content.rfind("]") + 1

        if start < 0 or end <= start:
            print("[OCR Matcher] No JSON array found in LLM response")
            return []

        json_str = content[start:end]
        matches_raw = json.loads(json_str)

        # Build final match structure
        matches = []
        used_pending_indices = set()

        for match in matches_raw:
            ocr_idx = match.get("ocr_index")
            pending_idx = match.get("pending_index")
            confidence = match.get("confidence", 0.0)
            reason = match.get("reason", "")

            # Validate indices
            if (ocr_idx is None or pending_idx is None or
                ocr_idx >= len(ocr_items) or pending_idx >= len(pending_items)):
                continue

            # Skip if confidence too low
            if confidence < 0.5:
                continue

            # Skip if pending item already matched (use best match only)
            if pending_idx in used_pending_indices:
                continue

            used_pending_indices.add(pending_idx)

            ocr_item = ocr_items[ocr_idx]
            pending_item = pending_items[pending_idx]

            matches.append({
                "ocr_item": ocr_item,
                "matched_line_item_id": pending_item["line_item_id"],
                "pending_request_id": pending_item.get("pending_request_id"),
                "confidence": confidence,
                "match_reason": reason
            })

        return matches

    except json.JSONDecodeError as e:
        print(f"[OCR Matcher] JSON parse error: {e}")
        print(f"[OCR Matcher] Response content: {content[:500]}...")
        return []
    except Exception as e:
        print(f"[OCR Matcher] Error parsing match response: {e}")
        return []


def _fallback_simple_match(
    ocr_items: List[Dict[str, Any]],
    pending_items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Fallback to simple substring matching if LLM is unavailable.
    """
    print("[OCR Matcher] Using fallback simple string matching")
    matches = []
    used_pending = set()

    for ocr_item in ocr_items:
        ocr_name = ocr_item.get("item_name", "").lower().strip()
        if not ocr_name:
            continue

        best_match = None
        best_score = 0.0

        for pending_item in pending_items:
            if pending_item["line_item_id"] in used_pending:
                continue

            pending_name = pending_item["item_name"].lower().strip()

            # Simple substring matching
            if ocr_name in pending_name or pending_name in ocr_name:
                score = 0.8
            elif any(word in pending_name for word in ocr_name.split() if len(word) > 3):
                score = 0.6
            else:
                score = 0.0

            if score > best_score:
                best_score = score
                best_match = pending_item

        if best_match and best_score >= 0.5:
            used_pending.add(best_match["line_item_id"])
            matches.append({
                "ocr_item": ocr_item,
                "matched_line_item_id": best_match["line_item_id"],
                "pending_request_id": best_match.get("pending_request_id"),
                "confidence": best_score,
                "match_reason": "Substring match (fallback)"
            })

    return matches


# Test function for development
def test_matcher(job_id: str = None):
    """
    Test the matcher with sample data or real job data.
    """
    if job_id:
        # Test with real job
        session = SessionLocal()
        try:
            pending_items = session.query(PendingQuoteRequest).filter(
                PendingQuoteRequest.job_id == job_id,
                PendingQuoteRequest.status == "pending"
            ).all()

            print(f"[Test] Found {len(pending_items)} pending items for {job_id}")
            for item in pending_items:
                print(f"  - {item.item_name}")
        finally:
            session.close()
    else:
        # Test with mock data
        mock_ocr_items = [
            {"item_name": "Marine Grade SS Bolt M8x40", "unit_price": 2.5, "quantity": 100},
            {"item_name": "5L Anti-Fouling Paint - Blue", "unit_price": 85.0, "quantity": 10},
            {"item_name": "12V LED Light 50W", "unit_price": 35.0, "quantity": 20}
        ]

        mock_pending_items = [
            {"line_item_id": 1, "pending_request_id": 1, "item_name": "Stainless Steel Bolt 8mm x 40mm", "vendor_email": "vendor1@example.com"},
            {"line_item_id": 2, "pending_request_id": 2, "item_name": "Anti Fouling Marine Paint 5 Liter Blue", "vendor_email": "vendor2@example.com"},
            {"line_item_id": 3, "pending_request_id": 3, "item_name": "LED Lighting 12 Volt 50 Watt", "vendor_email": "vendor3@example.com"}
        ]

        print("[Test] Testing with mock data...")
        matches = _llm_match_items(mock_ocr_items, mock_pending_items, "TEST-JOB")

        print(f"\n[Test] Found {len(matches)} matches:")
        for match in matches:
            print(f"\n  OCR: {match['ocr_item']['item_name']}")
            print(f"  Matched to Line Item ID: {match['matched_line_item_id']}")
            print(f"  Confidence: {match['confidence']:.2f}")
            print(f"  Reason: {match['match_reason']}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        test_job_id = sys.argv[1]
        test_matcher(test_job_id)
    else:
        test_matcher()
