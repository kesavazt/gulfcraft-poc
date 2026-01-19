
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import invoke_agent

def test_search():
    query = "I need a quotation for boat polishing work. My boat model is Majesty 120"
    print(f"Testing agent with query: {query}")
    print("-" * 50)
    
    try:
        result = invoke_agent(query)
        print("\nResult Response:")
        print(result['response'])
        print("\nResult State:")
        print(result['state'])
    except Exception as e:
        print(f"Error invoking agent: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_search()
