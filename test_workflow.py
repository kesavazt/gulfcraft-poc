import requests
import json
import time

BASE_URL = "http://localhost:8000"

def send_message(message, conversation_id=None, state=None, token=None):
    """Send a message to the chat endpoint"""
    payload = {
        "message": message,
        "conversation_id": conversation_id,
        "state": state
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.post(f"{BASE_URL}/chat", json=payload, headers=headers)
    return response.json()

def print_response(step, response):
    """Pretty print the response"""
    try:
        print(f"\n{'='*80}")
        print(f"STEP {step}")
        print(f"{'='*80}")
        # Handle Unicode characters by encoding to ascii with error handling
        response_text = response.get('response', 'N/A')
        if response_text:
            # Replace emojis and non-ascii chars with placeholder
            response_text = response_text.encode('ascii', 'ignore').decode('ascii')
        print(f"Response: {response_text}")
        print(f"Agent: {response.get('agent', 'N/A')}")
        if response.get('generated_file'):
            print(f"Generated File: {response['generated_file']}")

        # Print state debugging info
        state = response.get('state', {})
        if state:
            print(f"\n[STATE DEBUG]")
            print(f"  last_mentioned_job_id: {state.get('last_mentioned_job_id', 'NOT SET')}")

            # Safely handle last_viewed_product
            last_viewed = state.get('last_viewed_product')
            if last_viewed and isinstance(last_viewed, dict):
                print(f"  last_viewed_product: {last_viewed.get('item_name', 'NOT SET')}")

            # Safely handle pending_disambiguation
            pending = state.get('pending_disambiguation')
            if pending and isinstance(pending, dict):
                print(f"  pending_disambiguation: {pending.get('disambiguation_type', 'None')}")

        print(f"{'='*80}\n")
    except Exception as e:
        print(f"[ERROR] Failed to print response: {e}")
    return response

def login(username, password):
    """Login and get access token"""
    payload = {
        "username": username,
        "password": password
    }
    # OAuth2PasswordRequestForm requires form data, not JSON
    response = requests.post(f"{BASE_URL}/token", data=payload)
    return response.json()

def test_complete_workflow():
    """Test the complete workflow"""

    print("\n" + "="*80)
    print("TESTING COMPLETE WORKFLOW")
    print("="*80)

    # Step 0: Login
    print("\n[LOGIN] Authenticating with username: kesava")
    login_response = login("kesava", "123456")
    print(f"Login Response: {login_response}")

    if not login_response.get('access_token'):
        print("[X] Login failed!")
        return {"success": False, "error": "Login failed"}

    print(f"[OK] Login successful! Token: {login_response['access_token'][:20]}...")

    conversation_id = None
    state = None

    print("\n" + "="*80)
    print("STARTING WORKFLOW TESTS")
    print("="*80)

    token = login_response['access_token']

    # Step 1: User asks for current jobs
    print("\n[USER] show me current jobs")
    response = send_message("show me current jobs", conversation_id, state, token)
    result = print_response(1, response)
    conversation_id = result.get('conversation_id')
    state = result.get('state')
    time.sleep(1)

    # Step 2: Looks for details on a specific job
    # We need to extract a job ID from the response
    print("\n[USER] show me details for the first job")
    response = send_message("show me details for the first job", conversation_id, state, token)
    result = print_response(2, response)
    state = result.get('state')
    time.sleep(1)

    # Step 3: Wants to look for a product
    print("\n[USER] i want to look for a product")
    response = send_message("i want to look for a product", conversation_id, state, token)
    result = print_response(3, response)
    state = result.get('state')
    time.sleep(1)

    # Step 4: Searches for a vacuum cleaner
    print("\n[USER] vacuum cleaner")
    response = send_message("vacuum cleaner", conversation_id, state, token)
    result = print_response(4, response)
    state = result.get('state')
    time.sleep(1)

    # Step 5: Selects one vacuum cleaner (assuming first one is option 1)
    print("\n[USER] 1")
    response = send_message("1", conversation_id, state, token)
    result = print_response(5, response)
    state = result.get('state')
    time.sleep(1)

    # Step 6: Mentions to add this to my job
    print("\n[USER] add this to my job")
    response = send_message("add this to my job", conversation_id, state, token)
    result = print_response(6, response)
    state = result.get('state')
    time.sleep(1)

    # Step 7: Provides quantity (agent already knows job ID and product!)
    print("\n[USER] 3")
    response = send_message("3", conversation_id, state, token)
    result = print_response(7, response)
    state = result.get('state')
    time.sleep(1)

    # Step 7b: Approves it
    print("\n[USER] yes")
    response = send_message("yes", conversation_id, state, token)
    result = print_response("7b", response)
    state = result.get('state')
    time.sleep(1)

    # Step 8: Sends it to supervisor email to be notified of update
    print("\n[USER] send to supervisor email")
    response = send_message("send to supervisor email", conversation_id, state, token)
    result = print_response(8, response)
    state = result.get('state')
    time.sleep(1)

    # Step 9: Changes the job status to approved
    print("\n[USER] approve job COST-EB919F19")
    response = send_message("approve job COST-EB919F19", conversation_id, state, token)
    result = print_response(9, response)
    state = result.get('state')

    print("\n" + "="*80)
    print("WORKFLOW TEST COMPLETED")
    print("="*80)

    return {
        "conversation_id": conversation_id,
        "final_state": state,
        "success": True
    }

if __name__ == "__main__":
    try:
        result = test_complete_workflow()
        print(f"\n[OK] Test completed successfully!")
        print(f"Conversation ID: {result['conversation_id']}")
    except Exception as e:
        print(f"\n[FAILED] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
