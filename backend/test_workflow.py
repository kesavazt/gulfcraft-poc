import requests
import time
import uuid

API_URL = "http://localhost:8000"

def test_workflow():
    print("--- Starting Verification Test ---")
    
    # 1. Register
    username = f"testuser_{uuid.uuid4().hex[:6]}"
    password = "password123"
    print(f"Registering user: {username}")
    res = requests.post(f"{API_URL}/auth/register", json={"username": username, "password": password})
    if res.status_code != 200:
        print(f"Registration Failed: {res.text}")
        return
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Registration Successful.")

    # 2. Chat - Casual
    print("Sending Casual Message...")
    res = requests.post(f"{API_URL}/chat", json={"message": "Hello there!", "conversation_id": None}, headers=headers)
    print(f"Agent Response: {res.json()['response']}")
    conversation_id = res.json()["conversation_id"]

    # 3. Chat - Search (Fail/New Item)
    print("Searching for new item...")
    res = requests.post(f"{API_URL}/chat", json={"message": "Search for Custom Titanium Propeller", "conversation_id": conversation_id}, headers=headers)
    print(f"Agent Response: {res.json()['response']}")

    # 4. Chat - Create Job & Specify Category
    print("Creating Job...")
    res = requests.post(f"{API_URL}/chat", json={"message": "Create a costing job. The category is Engine Parts.", "conversation_id": conversation_id}, headers=headers)
    print(f"Agent Response: {res.json()['response']}")

    # 5. Chat - Add Vendor
    print("Adding Vendor...")
    res = requests.post(f"{API_URL}/chat", json={"message": "Add vendor newsupplier@engines.com", "conversation_id": conversation_id}, headers=headers)
    print(f"Agent Response: {res.json()['response']}")

    # 6. Chat - Send Emails
    print("Sending Emails...")
    res = requests.post(f"{API_URL}/chat", json={"message": "Proceed to send emails.", "conversation_id": conversation_id}, headers=headers)
    print(f"Agent Response: {res.json()['response']}")

    # 7. Chat - Download & Upload
    print("Requesting Download/Upload...")
    res = requests.post(f"{API_URL}/chat", json={"message": "Yes, download the sheet and upload to SharePoint.", "conversation_id": conversation_id}, headers=headers)
    response_text = res.json()['response']
    print(f"Agent Response: {response_text}")

    # Check for download link
    if "/download/" in response_text:
        filename = response_text.split("/download/")[1].split()[0].strip().rstrip('.')
        print(f"Attempting to download: {filename}")
        res = requests.get(f"{API_URL}/download/{filename}", headers=headers)
        if res.status_code == 200:
            print("Download Successful!")
        else:
            print(f"Download Failed: {res.status_code}")

    print("--- Verification Complete ---")

if __name__ == "__main__":
    try:
        test_workflow()
    except Exception as e:
        print(f"Test Failed: {e}")
