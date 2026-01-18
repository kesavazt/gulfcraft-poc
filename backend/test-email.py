import requests
import config
# ============== CONFIG =================
TENANT_ID = config.MS_GRAPH_TENANT_ID
CLIENT_ID = config.MS_GRAPH_CLIENT_ID
CLIENT_SECRET = config.MS_GRAPH_CLIENT_SECRET

USER_EMAIL = "ai.zaintech@gulfcraftinc.com"  # mailbox to read
# ======================================


def get_access_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }

    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()["access_token"]


def get_unread_emails(token):
    url = (
        f"https://graph.microsoft.com/v1.0/users/{USER_EMAIL}/mailFolders/Inbox/messages"
        "?$filter=isRead eq false"
        "&$select=subject,from,receivedDateTime"
        "&$top=25"
    )

    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()["value"]


if __name__ == "__main__":
    
    print(TENANT_ID)
    print(CLIENT_ID)
    print(CLIENT_SECRET)

    token = get_access_token()
    print(token)
    messages = get_unread_emails(token)

    for msg in messages:
        print(
            msg["receivedDateTime"],
            msg["from"]["emailAddress"]["address"],
            msg["subject"],
        )
