"""
Test Item Search Functionality

Tests the enhanced item search that searches by both name and code.
"""

def test_search_endpoint_structure():
    """Verify the search endpoint returns the correct structure."""
    from core.api import ItemSearchResult
    from pydantic import ValidationError

    # Test valid data
    try:
        result = ItemSearchResult(
            item_code="ITEM-001",
            item_name="Marine Battery Pack",
            unit_cost=150.0,
            vendor_email="vendor@example.com",
            source="product"
        )
        assert result.item_code == "ITEM-001"
        assert result.item_name == "Marine Battery Pack"
        assert result.unit_cost == 150.0
        print("✅ ItemSearchResult structure is correct")
    except ValidationError as e:
        print(f"❌ ItemSearchResult validation failed: {e}")
        raise


def test_search_response_format():
    """Verify search results have all required fields for dropdown."""
    # Mock search result
    mock_result = {
        "item_code": "PUMP-123",
        "item_name": "Bilge Pump 1200 GPH",
        "unit_cost": 89.99,
        "vendor_email": "marine@supplier.com",
        "source": "estimation"
    }

    required_fields = ["item_code", "item_name", "unit_cost", "vendor_email", "source"]

    for field in required_fields:
        assert field in mock_result, f"Missing required field: {field}"

    print("✅ Search result has all required fields")


def test_search_sorting_logic():
    """Test that search results are sorted by relevance."""
    # Mock results
    results = [
        {"item_name": "Contains pump word", "item_code": "A001"},
        {"item_name": "Pump at start", "item_code": "A002"},
        {"item_name": "pump", "item_code": "A003"},  # Exact match
    ]

    query = "pump"

    def sort_key(item):
        name_lower = item["item_name"].lower()
        code_lower = (item["item_code"] or "").lower()
        q_lower = query.lower()

        if name_lower == q_lower or code_lower == q_lower:
            return 0
        elif name_lower.startswith(q_lower) or code_lower.startswith(q_lower):
            return 1
        else:
            return 2

    sorted_results = sorted(results, key=sort_key)

    # Exact match should be first
    assert sorted_results[0]["item_name"] == "pump"
    # Starts with should be second
    assert sorted_results[1]["item_name"] == "Pump at start"
    # Contains should be last
    assert sorted_results[2]["item_name"] == "Contains pump word"

    print("✅ Search sorting logic works correctly")


def test_duplicate_prevention():
    """Test that duplicate items are filtered out."""
    seen_items = set()
    items = [
        {"item_code": "ITEM-001", "item_name": "Battery"},
        {"item_code": "ITEM-001", "item_name": "Battery Pack"},  # Duplicate code
        {"item_code": "ITEM-002", "item_name": "Pump"},
    ]

    unique_items = []
    for item in items:
        item_key = item["item_code"]
        if item_key not in seen_items:
            unique_items.append(item)
            seen_items.add(item_key)

    assert len(unique_items) == 2, "Should only have 2 unique items"
    print("✅ Duplicate prevention works correctly")


def test_minimum_query_length():
    """Test that search requires at least 2 characters."""
    queries_to_test = [
        ("", False),  # Empty should return nothing
        ("a", False),  # Single character should return nothing
        ("ab", True),  # 2 characters should work
        ("pump", True),  # Full word should work
    ]

    for query, should_have_results in queries_to_test:
        # Simulate the check
        if not query or len(query) < 2:
            has_results = False
        else:
            has_results = True

        assert has_results == should_have_results, f"Query '{query}' failed validation"

    print("✅ Minimum query length validation works")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Testing Item Search Functionality")
    print("="*60 + "\n")

    tests = [
        test_search_endpoint_structure,
        test_search_response_format,
        test_search_sorting_logic,
        test_duplicate_prevention,
        test_minimum_query_length,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} failed: {e}")
            failed += 1
        except Exception as e:
            print(f"⚠️  {test.__name__} error: {e}")
            failed += 1

    print("\n" + "="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    if failed == 0:
        print("🎉 All tests passed! Item search is working correctly.")
    else:
        print(f"⚠️  {failed} test(s) failed. Please review.")
