"""
Test script for OCR Matcher
Tests the LLM-based semantic matching of invoice items to database items
"""
import sys
import os
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from services.ocr_matcher import match_ocr_items_to_pending, _llm_match_items


def test_llm_matching():
    """
    Test LLM matching with various naming variations
    """
    print("=" * 80)
    print("Testing OCR Matcher - LLM Semantic Matching")
    print("=" * 80)

    # Simulate OCR extracted items (from vendor quotation)
    ocr_items = [
        {
            "item_name": "Marine Grade SS Bolt M8x40mm",
            "quantity": 100,
            "unit_price": 2.50
        },
        {
            "item_name": "5L Anti-Fouling Paint - International Blue",
            "quantity": 10,
            "unit_price": 85.00
        },
        {
            "item_name": "LED Navigation Light 12V 50W",
            "quantity": 20,
            "unit_price": 35.00
        },
        {
            "item_name": "Stainless Steel Anchor Chain 8mm x 10m",
            "quantity": 5,
            "unit_price": 150.00
        },
        {
            "item_name": "Marine Grade Epoxy Resin 1 Gallon",
            "quantity": 15,
            "unit_price": 45.00
        }
    ]

    # Simulate pending items in database (what we requested)
    pending_items = [
        {
            "line_item_id": 101,
            "pending_request_id": 201,
            "item_name": "Stainless Steel Bolt 8mm x 40mm - Marine Grade",
            "vendor_email": "bolts@supplier.com"
        },
        {
            "line_item_id": 102,
            "pending_request_id": 202,
            "item_name": "Anti Fouling Marine Paint 5 Liter International Blue",
            "vendor_email": "paint@supplier.com"
        },
        {
            "line_item_id": 103,
            "pending_request_id": 203,
            "item_name": "12 Volt LED Navigation Lighting 50 Watt",
            "vendor_email": "lights@supplier.com"
        },
        {
            "line_item_id": 104,
            "pending_request_id": 204,
            "item_name": "SS Anchor Chain 8mm - 10 meter length",
            "vendor_email": "chain@supplier.com"
        },
        {
            "line_item_id": 105,
            "pending_request_id": 205,
            "item_name": "Epoxy Resin Marine Grade 1 Gal",
            "vendor_email": "resin@supplier.com"
        }
    ]

    print(f"\n📄 OCR Extracted Items ({len(ocr_items)} items):")
    print("-" * 80)
    for i, item in enumerate(ocr_items, 1):
        print(f"{i}. {item['item_name']}")
        print(f"   Qty: {item['quantity']}, Price: ${item['unit_price']:.2f}")

    print(f"\n📋 Pending Database Items ({len(pending_items)} items):")
    print("-" * 80)
    for i, item in enumerate(pending_items, 1):
        print(f"{i}. {item['item_name']}")

    print(f"\n🤖 Running LLM Matcher...")
    print("-" * 80)

    # Run the LLM matching
    matches = _llm_match_items(ocr_items, pending_items, "TEST-JOB-001")

    if matches:
        print(f"\n✅ Successfully matched {len(matches)}/{len(ocr_items)} items\n")
        print("=" * 80)
        print("MATCHING RESULTS")
        print("=" * 80)

        for i, match in enumerate(matches, 1):
            ocr = match["ocr_item"]
            line_id = match["matched_line_item_id"]
            confidence = match["confidence"]
            reason = match["match_reason"]

            # Find the pending item name
            pending_name = next(
                (p["item_name"] for p in pending_items if p["line_item_id"] == line_id),
                "Unknown"
            )

            print(f"\n{i}. MATCH (Confidence: {confidence:.1%})")
            print(f"   OCR:     {ocr['item_name']}")
            print(f"   Pending: {pending_name}")
            print(f"   Line ID: {line_id}")
            print(f"   Price:   ${ocr.get('unit_price', 0):.2f}")
            print(f"   Reason:  {reason}")

        print("\n" + "=" * 80)
    else:
        print("\n❌ No matches found or LLM matching failed")
        print("   Check your MISTRAL_API_KEY in .env file")

    print("\n✓ Test completed")


def test_with_real_job(job_id: str):
    """
    Test with a real job from the database
    """
    print("=" * 80)
    print(f"Testing with Real Job: {job_id}")
    print("=" * 80)

    from core.database import SessionLocal, PendingQuoteRequest

    session = SessionLocal()
    try:
        pending = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.job_id == job_id,
            PendingQuoteRequest.status == "pending"
        ).all()

        if not pending:
            print(f"\n❌ No pending items found for job {job_id}")
            return

        print(f"\n📋 Found {len(pending)} pending items:")
        for item in pending:
            print(f"   - {item.item_name}")

        # Create mock OCR items with slight variations
        ocr_items = [
            {
                "item_name": item.item_name.replace("Stainless Steel", "SS").replace("12 Volt", "12V"),
                "quantity": 1,
                "unit_price": 50.0
            }
            for item in pending[:3]  # Test first 3 items
        ]

        print(f"\n📄 Mock OCR items (with variations):")
        for item in ocr_items:
            print(f"   - {item['item_name']}")

        print(f"\n🤖 Running matcher...")
        matches = match_ocr_items_to_pending(job_id, ocr_items)

        if matches:
            print(f"\n✅ Matched {len(matches)} items:")
            for match in matches:
                print(f"   - {match['ocr_item']['item_name']}")
                print(f"     Confidence: {match['confidence']:.1%}")
                print(f"     Line ID: {match['matched_line_item_id']}")
        else:
            print(f"\n❌ No matches found")

    finally:
        session.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Test with real job ID
        job_id = sys.argv[1]
        test_with_real_job(job_id)
    else:
        # Test with mock data
        test_llm_matching()
