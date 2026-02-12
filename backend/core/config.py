import os
from dotenv import load_dotenv
load_dotenv()

# --- Application Config ---
TOP_K_ITEMS = 5
PRICE_THRESHOLD = 1000.0  # Items above this price require quotation
PROFIT_MARGIN = float(os.getenv("PROFIT_MARGIN", "1.5"))  # Multiplier for profit (1.5 = 50% margin)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMP_DOWNLOADS_DIR = os.path.join(BASE_DIR, "temp_downloads")

# --- SharePoint Config ---
SHAREPOINT_SITE_URL = os.getenv("SHAREPOINT_SITE_URL", "https://gulfcraft.sharepoint.com/sites/costing")
SHAREPOINT_TENANT_ID = os.getenv("SHAREPOINT_TENANT_ID", os.getenv("MS_GRAPH_TENANT_ID", ""))
SHAREPOINT_CLIENT_ID = os.getenv("SHAREPOINT_CLIENT_ID", os.getenv("MS_GRAPH_CLIENT_ID", ""))
SHAREPOINT_CLIENT_SECRET = os.getenv("SHAREPOINT_CLIENT_SECRET", os.getenv("MS_GRAPH_CLIENT_SECRET", ""))
SHAREPOINT_LIST_NAME = os.getenv("SP_LIST_ID", os.getenv("SHAREPOINT_LIST_NAME", "CostingJobs"))
SHAREPOINT_DRIVE_NAME = os.getenv("SHAREPOINT_DRIVE_NAME", "Documents")
SHAREPOINT_SITE_ID = os.getenv("SP_SITE_ID", os.getenv("SHAREPOINT_SITE_ID", ""))

# --- D365 Config (Mock) ---
D365_API_URL = os.getenv("D365_API_URL", "https://gulfcraft.operations.dynamics.com")
D365_TENANT_ID = os.getenv("D365_TENANT_ID", "mock_tenant_id")
D365_CLIENT_ID = os.getenv("D365_CLIENT_ID", "mock_d365_client_id")
D365_CLIENT_SECRET = os.getenv("D365_CLIENT_SECRET", "mock_d365_client_secret")

# --- Email Config ---
# SMTP config (for sending)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", os.getenv("SMTP_EMAIL", ""))

# IMAP config (for receiving/polling)
IMAP_SERVER = os.getenv("IMAP_SERVER", "outlook.office365.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_EMAIL = os.getenv("IMAP_EMAIL", os.getenv("SMTP_EMAIL", ""))
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", os.getenv("SMTP_PASSWORD", ""))

# Microsoft Graph API OAuth2 Config
MS_GRAPH_TENANT_ID = os.getenv("MS_GRAPH_TENANT_ID", os.getenv("D365_TENANT_ID", ""))
MS_GRAPH_CLIENT_ID = os.getenv("MS_GRAPH_CLIENT_ID", "")
MS_GRAPH_CLIENT_SECRET = os.getenv("MS_GRAPH_CLIENT_SECRET", "")
MS_GRAPH_SENDER_EMAIL = os.getenv("MS_GRAPH_SENDER_EMAIL", "")

# --- Database Config ---
# Default to local SQLite for dev, Postgres for prod
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gulfcraft.db")
# Example Postgres URL: "postgresql+psycopg2://user:password@localhost:5432/gulfcraft"

# --- Embedding Config ---
OPENAI_API_TYPE = os.getenv("OPENAI_API_TYPE", "azure") # 'openai' or 'azure'
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")  # Used for Azure OpenAI
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "2024-08-01-preview")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://gtech.openai.azure.com")
AZURE_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")  # Use OPENAI_API_KEY for Azure
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small")
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-4.1")
AZURE_OPENAI_MATCHER_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_MATCHER_DEPLOYMENT_NAME", os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-4.1-mini"))  # For OCR matching, defaults to chat deployment
EMBEDDING_MODEL = "text-embedding-3-small"

# --- Security ---
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# --- Templates ---
COSTING_TEMPLATE_PATH = os.getenv("COSTING_TEMPLATE_PATH", "templates/costing_template.xlsx")

# --- Langfuse ---
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

# --- Mistral API ---
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# --- Azure Mistral Document AI ---
AZURE_MISTRAL_ENDPOINT = os.getenv("AZURE_MISTRAL_ENDPOINT", "")  # e.g. https://<name>.<region>.models.ai.azure.com
AZURE_MISTRAL_API_KEY = os.getenv("AZURE_MISTRAL_API_KEY", "")

# --- Vendor Config ---
VENDOR_DEFAULT_EMAIL = os.getenv("VENDOR_DEFAULT_EMAIL", "")

# --- Email Monitor ---
EMAIL_POLL_INTERVAL = int(os.getenv("EMAIL_POLL_INTERVAL", "60"))
