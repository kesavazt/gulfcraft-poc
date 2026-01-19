import os
import sys

# Add backend to path
sys.path.append(os.path.join(os.getcwd()))

from main import invoke_agent

def test_selection_flow():
    # Step 1: Search and get results
    print("Step 1: Searching for quotations")
    msg1 = "I need polishing for Majesty 120"
    result1 = invoke_agent(msg1)
    
    similar = result1['state'].get('similar_quotations')
    if not similar:
        print("FAILURE: No search results found.")
        return
    
    # Step 2: Select the first one
    print("\nStep 2: Selecting first quotation")
    selected_id = similar[0]['quotation_id']
    line_num = similar[0]['line_num']
    msg2 = f"{selected_id}:{line_num}"
    
    print(f"User: {msg2}")
    result2 = invoke_agent(msg2, session_state=result1['state'])
    print(f"AI: {result2['response']}")
    
    # Verify details are present
    if "Included Items:" in result2['response']:
        print("SUCCESS: Detailed estimation items found in response.")
    else:
        print("FAILURE: Detailed items missing from response.")
        
    if "AED" in result2['response']:
        print("SUCCESS: AED currency found in response.")
    else:
        print("FAILURE: AED currency missing from response.")

    # Step 3: Confirm
    print("\nStep 3: Confirming selection")
    msg3 = "Yes"
    print(f"User: {msg3}")
    result3 = invoke_agent(msg3, session_state=result2['state'])
    print(f"AI: {result3['response']}")
    
    if "Proceeding to create costing job" in result3['response']:
        print("SUCCESS: Confirmation identified correctly!")
    else:
        print("FAILURE: Confirmation failed. Check state persistence.")

if __name__ == "__main__":
    test_selection_flow()
