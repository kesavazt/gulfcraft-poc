import os
import requests
from dotenv import load_dotenv

def resolve_site():
    load_dotenv()
    
    tenant_id = os.getenv("MS_GRAPH_TENANT_ID")
    client_id = os.getenv("MS_GRAPH_CLIENT_ID")
    client_secret = os.getenv("MS_GRAPH_CLIENT_SECRET")
    
    # Target Site URL
    site_url = "gulfcraftinc.sharepoint.com:/sites/GCITPortal"
    
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
    
    # Resolve Site ID
    graph_url = f"https://graph.microsoft.com/v1.0/sites/{site_url}"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    response = requests.get(graph_url, headers=headers)
    response.raise_for_status()
    site_id = response.json().get("id")
    print(f"Site ID: {site_id}")

if __name__ == "__main__":
    resolve_site()
