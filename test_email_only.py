import requests
import time

BASE_URL = "http://localhost:8000"

def login(username, password):
    payload = {
        "username": username,
        "password": password
    }
    response = requests.post(f"{BASE_URL}/token", data=payload)
    return response.json()

def send_message(message, conversation_id, state, token):
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "message": message,
        "conversation_id": conversation_id,
        "state": state
    }
    response = requests.post(f"{BASE_URL}/chat", json=payload, headers=headers)
    return response.json()

# Login
print("Logging in...")
login_response = login("kesava", "123456")
token = login_response["access_token"]
print(f"Token: {token[:20]}...")

# Start conversation
conversation_id = None
state = {}

# Test email sending with job ID
print("\nTest: Send to supervisor email for job COST-EB919F19")
response = send_message("send costing sheet for COST-EB919F19 to supervisor email", conversation_id, state, token)
response_text = response.get('response', 'N/A')
# Strip non-ASCII characters
response_text = response_text.encode('ascii', 'ignore').decode('ascii')
print(f"Response: {response_text[:200]}")
if 'state' in response:
    state = response['state']
    conversation_id = response.get('conversation_id')
    print(f"Conversation ID: {conversation_id}")
else:
    print("No state in response")

print("\nDone!")
