# Gulf Craft Costing Agent

An intelligent agentic workflow for automating costing operations, integrated with SharePoint, Microsoft Graph, and AI services.

## Architecture

*   **Backend**: FastAPI, LangGraph, SQLAlchemy (PostgreSQL/SQLite).
*   **AI**: Azure OpenAI (GPT-4), Mistral AI (OCR).
*   **Integrations**: Microsoft Graph API (Email, SharePoint), SMTP/IMAP.

## Deployment Guide

### 1. Prerequisites

*   **Python**: 3.10+
*   **Database**: PostgreSQL 15+ with `pgvector` extension enabled. (SQLite supported for dev).
*   **External Accounts**:
    *   **Azure OpenAI**: For LLM and Embeddings.
    *   **Microsoft Graph**: App Registration with permissions for Mail and SharePoint.
    *   **Mistral AI**: API Key for OCR.

### 2. Environment Configuration

Create a `.env` file in the root directory with the following variables:

```ini
# --- Database ---
# Use PostgreSQL for production
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/gulfcraft

# --- Azure OpenAI ---
OPENAI_API_TYPE=azure
OPENAI_API_KEY=<your_azure_key>
OPENAI_API_VERSION=2023-05-15
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=gpt-4
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small

# --- Microsoft Graph API (SharePoint & Email) ---
MS_GRAPH_TENANT_ID=<tenant_id>
MS_GRAPH_CLIENT_ID=<client_id>
MS_GRAPH_CLIENT_SECRET=<client_secret>
MS_GRAPH_SENDER_EMAIL=<sender_email>

# --- SharePoint Configuration ---
SHAREPOINT_SITE_ID=<site_id>
SHAREPOINT_LIST_NAME=CostingJobs

# --- Mistral AI (OCR) ---
MISTRAL_API_KEY=<your_mistral_key>

# --- Email Monitor (IMAP) ---
# For Gmail, use App Password
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
SMTP_EMAIL=<email>
SMTP_PASSWORD=<app_password>
```

### 3. Installation

1.  **Clone the repository**:
    ```bash
    git clone <repo_url>
    cd gulfcraft
    ```

2.  **Activate the environment**:
    ```bash
    conda activate ocr-dev
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

### 4. Database Setup

Initialize the database tables (this will drop existing tables if run directly):

```bash
# Verify DATABASE_URL in .env first
cd backend
python -m core.database
```

### 5. Running the Application

The system consists of two main components that should run simultaneously:

#### A. Backend API (FastAPI)
Handles the agent workflow, chat endpoints, and file downloads.

```bash
cd backend
uvicorn core.api:app --host 0.0.0.0 --port 8000 --reload
```
*   API Docs: `http://localhost:8000/docs`

#### B. Email Monitor Service
Runs in the background to poll for vendor quotes and process PDF attachments.

```bash
python backend/services/email_monitor.py run
```

#### C. Frontend (React)
User Interface for interacting with the agent and viewing costing sheets.

```bash
cd frontend
npm install
npm run dev
```
*   Access UI: `http://localhost:5173` (or port shown in terminal)

### 6. Verification

1.  **Health Check**: Visit `http://localhost:8000/docs`.
2.  **Interactive Test**: Run `python backend/main.py` to chat with the agent in the terminal.
3.  **Email Test**: Send a mock quotation email to the configured inbox with subject "JOB-TEST Price Quotation" and verify logs in `email_monitor.py`.
