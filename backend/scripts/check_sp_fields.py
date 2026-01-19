import os
import requests
from dotenv import load_dotenv

def check_fields():
    load_dotenv()
    
    tenant_id = os.getenv("MS_GRAPH_TENANT_ID")
    client_id = os.getenv("MS_GRAPH_CLIENT_ID")
    client_secret = os.getenv("MS_GRAPH_CLIENT_SECRET")
    site_id = "gulfcraftinc.sharepoint.com,23c3c870-99cb-4d48-99c4-793ea6243810,3d048e98-0320-4b31-abe2-501faf8b6486"
    
    # Get Token
    auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    auth_data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default"
    }
    
    auth_response = requests.post(auth_url, data=auth_data)
    auth_response.raise_for_status()
    token = auth_response.json().get("access_token")
    
    # Get Lists to find 'zaintech'
    lists_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(lists_url, headers=headers)
    response.raise_for_status()
    lists = response.json().get("value", [])
    
    zaintech_id = None
    print("Available Lists:")
    for l in lists:
        print(f"- {l.get('displayName')} ({l.get('name')}) -> {l.get('id')}")
        if l.get('name') == 'zaintech' or l.get('displayName') == 'zaintech':
            zaintech_id = l.get('id')

    if not zaintech_id:
        print("List 'zaintech' not found!")
        return

    print(f"\n--- Columns in 'zaintech' ({zaintech_id}) ---")
    columns_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{zaintech_id}/columns"
    col_response = requests.get(columns_url, headers=headers)
    col_response.raise_for_status()
    columns = col_response.json().get("value", [])
    
    for col in columns:
        col_type = ""
        if 'text' in col: col_type = "Text"
        elif 'number' in col: col_type = "Number"
        elif 'dateTime' in col: col_type = "DateTime"
        elif 'choice' in col: col_type = "Choice"
        elif 'lookup' in col: col_type = "Lookup"
        elif 'boolean' in col: col_type = "Boolean"
        else: col_type = "Other"
        
        print(f"- {col.get('displayName')} -> {col.get('name')} ({col_type})")

if __name__ == "__main__":
    check_fields()
