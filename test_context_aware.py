import requests
import json
import time
import re

BASE_URL = 'http://localhost:8000'

def strip_emojis(text):
    """Remove emojis for Windows console compatibility"""
    return text.encode('ascii', 'ignore').decode('ascii')

def login(username, password):
    response = requests.post(f'{BASE_URL}/token', data={'username': username, 'password': password})
    return response.json()

def send_message(message, conversation_id, state, token):
    response = requests.post(
        f'{BASE_URL}/chat',
        json={'message': message, 'conversation_id': conversation_id, 'state': state},
        headers={'Authorization': f'Bearer {token}'}
    )
    return response.json()

print("="*80)
print("TESTING CONTEXT-AWARE PRICE COMPARISON")
print("="*80)

# Login
login_resp = login('kesava', '123456')
token = login_resp['access_token']
print('\n[OK] Logged in successfully')

# Step 1: Ask about vacuum cleaner price
print("\n" + "="*80)
print("STEP 1: Initial price comparison query")
print("="*80)
print("[USER] Is 1500 AED a good price for a vacuum cleaner?")
resp1 = send_message('Is 1500 AED a good price for a vacuum cleaner?', None, None, token)
conv_id = resp1['conversation_id']
state = resp1['state']
print(f"\n[SYSTEM] {strip_emojis(resp1['response'])[:100]}...")

# Step 2: Select product
print("\n" + "="*80)
print("STEP 2: User selects product")
print("="*80)
print("[USER] 1")
time.sleep(1)
resp2 = send_message('1', conv_id, state, token)
state = resp2['state']
if "Good Price" in resp2['response'] or "Great Deal" in resp2['response']:
    print("[SYSTEM] [OK] Price comparison shown successfully")
else:
    print("[SYSTEM] [WARN] Price comparison may not have triggered")

# Step 3: Ask about THIS vacuum cleaner with different price (CONTEXT-AWARE TEST)
print("\n" + "="*80)
print("STEP 3: Context-aware comparison (THIS vacuum cleaner)")
print("="*80)
print("[USER] Is 2000 AED too expensive for this vacuum cleaner?")
time.sleep(1)
resp3 = send_message('Is 2000 AED too expensive for this vacuum cleaner?', conv_id, state, token)
print("\n[SYSTEM Response]:")
print(strip_emojis(resp3['response']))

# Check if it worked
if "Price Comparison" in resp3['response'] and "Current Quote:" in resp3['response']:
    print("\n[OK] SUCCESS! Context-aware comparison triggered!")
    print("[OK] Used previously selected vacuum cleaner without re-selection")
else:
    print("\n[WARN] Context awareness may not have worked")

# Step 4: Test with "for this" at end of sentence (edge case)
print("\n" + "="*80)
print("STEP 4: Context-aware with 'for this' (end of string test)")
print("="*80)
print("[USER] what if i was quoted 2000 aed for this")
time.sleep(1)
resp4 = send_message('what if i was quoted 2000 aed for this', conv_id, state, token)
print("\n[SYSTEM Response]:")
print(strip_emojis(resp4['response']))

if "Price Comparison" in resp4['response'] and "Current Quote:" in resp4['response']:
    print("\n[OK] SUCCESS! Edge case handled correctly!")
    print("[OK] Detected 'for this' without trailing space")
else:
    print("\n[WARN] Edge case failed - 'for this' not recognized")

# Step 5: Test with "the same item we were discussing"
print("\n" + "="*80)
print("STEP 5: Context-aware with 'the same item'")
print("="*80)
print("[USER] how about 1800 for the same item")
time.sleep(1)
resp5 = send_message('how about 1800 for the same item', conv_id, state, token)
print("\n[SYSTEM Response]:")
print(strip_emojis(resp5['response']))

if "Price Comparison" in resp5['response'] and "Current Quote:" in resp5['response']:
    print("\n[OK] SUCCESS! 'the same item' recognized correctly!")
else:
    print("\n[WARN] 'the same item' not recognized")

print("\n" + "="*80)
print("TEST COMPLETED")
print("="*80)
