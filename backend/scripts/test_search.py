from search import hybrid_search
from database import init_db

def test_search():
    print("Testing search functionality...")
    
    test_cases = [
        {
            "description": "Installation of Dinghy stand and set the Dinghy",
            "boat_model": "MAJESTY125"
        },
        {
            "description": "At Sundeck The coffee machine needs a sliding mechanism for better use. And need additional sockets inside forward portside storage cabinet.",
            "boat_model": "MAJESTY120"
        },
        {
            "description": "I want to get my boat's chiller system chemically cleaned.",
            "boat_model": "MAJESTY62" # Or NA
        }
    ]

    for i, case in enumerate(test_cases):
        print(f"\n--- Test Case {i+1} ---")
        print(f"Description: {case['description']}")
        print(f"Boat Model: {case['boat_model']}")
        
        results = hybrid_search(case['description'], case['boat_model'], top_k=3)
        
        if results:
            print(f"Found {len(results)} results:")
            for j, res in enumerate(results):
                print(f"  {j+1}. [{res['id']}:{res['line_num']}] {res['description'][:100]}... (Price: {res['price']})")
        else:
            print("No results found.")

if __name__ == "__main__":
    test_search()
