import os
import sys

# Add backend to path
sys.path.append(os.path.join(os.getcwd()))

from main import invoke_agent
from langchain_core.messages import HumanMessage, AIMessage

def test_multiturn_search():
    print("Step 1: Providing only description")
    msg1 = "I want to do some polishing work"
    print(f"User: {msg1}")
    
    result1 = invoke_agent(msg1)
    print(f"AI: {result1['response']}")
    
    # Store history for the next turn in dictionary format
    history = [
        {"role": "user", "content": msg1},
        {"role": "assistant", "content": result1['response']}
    ]
    
    print("\n" + "-"*50)
    print("Step 2: Providing boat model")
    msg2 = "My boat is Majesty 120"
    print(f"User: {msg2}")
    
    result2 = invoke_agent(msg2, conversation_history=history)
    print(f"AI: {result2['response']}")
    
    # Check if we got quotations
    if "similar_quotations" in result2['state'] and result2['state']['similar_quotations']:
        print("\nSUCCESS: Found similar quotations in multi-turn conversation!")
    else:
        print("\nFAILURE: No quotations found. Check agent routing and extraction.")

if __name__ == "__main__":
    test_multiturn_search()
