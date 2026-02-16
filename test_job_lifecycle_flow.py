import requests
import json

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

def login(username, password):
    """Login and get access token"""
    payload = {"username": username, "password": password}
    response = requests.post(f"{BASE_URL}/token", data=payload)
    return response.json()

def test_job_lifecycle_flow():
    """Test the job lifecycle flow with job ID disambiguation"""
    print("\n" + "="*80)
    print("TESTING JOB LIFECYCLE FLOW")
    print("="*80)

    # Login
    print("\n[LOGIN] Authenticating...")
    login_response = login("kesava", "123456")
    if not login_response.get('access_token'):
        print("[X] Login failed!")
        return

    token = login_response['access_token']
    print(f"[OK] Login successful!")

    conversation_id = None
    state = None

    # Test 1: Send to supervisor (without job ID)
    print("\n[TEST 1] User: 'send to supervisor'")
    response = send_message("send to supervisor", conversation_id, state, token)
    response_text = response.get('response', 'N/A').encode('ascii', 'ignore').decode('ascii')[:150]
    print(f"Agent: {response_text}...")
    conversation_id = response.get('conversation_id')
    state = response.get('state')

    # Provide job ID
    print("\n[TEST 1] User: 'COST-DA0C9748'")
    response = send_message("COST-DA0C9748", conversation_id, state, token)
    response_text = response.get('response', 'N/A').encode('ascii', 'ignore').decode('ascii')[:200]
    print(f"Agent: {response_text}...")
    state = response.get('state')

    # Test 2: Approve job (without job ID)
    print("\n[TEST 2] User: 'send job for approval'")
    response = send_message("send job for approval", conversation_id, state, token)
    response_text = response.get('response', 'N/A').encode('ascii', 'ignore').decode('ascii')[:150]
    print(f"Agent: {response_text}...")
    state = response.get('state')

    # Provide job ID
    print("\n[TEST 2] User: 'COST-DA0C9748'")
    response = send_message("COST-DA0C9748", conversation_id, state, token)
    response_text = response.get('response', 'N/A').encode('ascii', 'ignore').decode('ascii')[:200]
    print(f"Agent: {response_text}...")

    print("\n" + "="*80)
    print("TEST COMPLETED")
    print("="*80)

if __name__ == "__main__":
    try:
        test_job_lifecycle_flow()
    except Exception as e:
        print(f"\n[FAILED] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
