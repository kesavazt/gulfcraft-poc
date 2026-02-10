# Gulf Craft AI Costing Assistant

An enterprise multi-agent AI system for streamlining yacht maintenance and repair costing. Combines intelligent quotation search, automated vendor coordination, price tracking, and comprehensive job lifecycle management.

## Features

- **12-Agent Workflow**: Supervisor routing to specialized agents (search, costing, editing, quotes, pricing, vendor intelligence, and more)
- **Hybrid Search**: Semantic (embeddings) + PostgreSQL full-text search across historical quotations with boat model filtering
- **Automated Costing**: Price resolution from multiple sources, Excel sheet generation, and vendor quote requests
- **Quote Management**: SMTP/IMAP email automation with PDF OCR extraction (Mistral AI) for vendor quote processing
- **Job Lifecycle**: Create, edit, approve, duplicate, and distribute costing jobs with SharePoint sync
- **Pricing Intelligence**: Historical price analysis, anomaly detection, and vendor performance tracking
- **Observability**: Hierarchical Langfuse tracing (conversation > job > operation)
- **JWT Authentication**: Role-based access control (admin/user) with scoped data visibility

## Architecture

### Backend
- **Framework**: FastAPI 0.104+
- **AI Orchestration**: LangGraph + LangChain
- **LLM**: Azure OpenAI (GPT-4)
- **Embeddings**: Azure OpenAI (text-embedding-3-small)
- **OCR**: Mistral AI (Azure-hosted)
- **Database**: PostgreSQL 15+ with pgvector
- **ORM**: SQLAlchemy 2.0+
- **Observability**: Langfuse 3.12.1+
- **Auth**: JWT (python-jose) + bcrypt

### Frontend
- **Framework**: React 18+
- **Routing**: React Router v7
- **HTTP Client**: Axios
- **Styling**: Tailwind CSS
- **Icons**: Lucide React
- **Build**: Vite 5

### Integrations
- **Microsoft Graph API**: Mail and SharePoint operations
- **Email**: Office 365 SMTP/IMAP for vendor quote management
- **SharePoint**: Job status tracking and list management
- **Cloud**: Azure App Service with GitHub Actions CI/CD

## Agent System

```
User Query --> Supervisor Agent (intent routing)
                    |
    +-------+-------+--------+--------+--------+--------+
    |       |       |        |        |        |        |
 Search  Status  EditJob  Quote   Pricing  Vendor  Explainer
 Agent   Agent   Agent    Mgmt    Advisor  Info    Agent
    |                     Agent   Agent    Agent
    v
 Refinement --> Selection --> Costing Agent
 Agent          Agent            |
                          +------+------+
                          |      |      |
                       Resolve Generate Send
                       Prices  Sheet   Quotes
```

### Agents

| Agent | Purpose |
|-------|---------|
| **Supervisor** | Routes user intent to the appropriate agent |
| **Search** | Hybrid semantic + keyword quotation search |
| **Refinement** | Formats and presents search results |
| **Selection** | Handles quotation selection and confirmation |
| **Costing** | Creates jobs with price resolution, sheet generation, and email dispatch |
| **Status** | Conversational job status updates |
| **Edit Job** | Add, remove, or update items on existing jobs |
| **Quote Management** | Vendor quote requests, resends, cancellations, and OCR matching |
| **Job Lifecycle** | Approve, distribute, duplicate, and cancel jobs |
| **Pricing Advisor** | Historical price analysis with statistics and anomaly detection |
| **Vendor Info** | Vendor performance metrics and supply history |
| **Explainer** | Answers "why" questions about system behavior |

## Prerequisites

### Required
- **Python**: 3.10 or 3.11 (recommended)
- **Node.js**: 16+ (for frontend)
- **Database**: PostgreSQL 15+ with pgvector extension
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```

### External Services
1. **Azure OpenAI** - GPT-4 deployment for chat, text-embedding-3-small for embeddings
2. **Microsoft Graph API** - Azure AD App Registration with Mail.Send, Sites.ReadWrite.All permissions
3. **Mistral AI** - OCR for PDF quote extraction
4. **Langfuse** (optional) - Observability and tracing

## Installation

### 1. Clone Repository
```bash
git clone <repo_url>
cd gulfcraft
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

Create `.env` in the root directory:

```ini
# Application
TOP_K_ITEMS=5
PRICE_THRESHOLD=1000.0
PROFIT_MARGIN=1.5

# Database
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/gulfcraft

# Azure OpenAI
OPENAI_API_TYPE=azure
OPENAI_API_KEY=<key>
OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=gpt-4.1
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
AZURE_OPENAI_MATCHER_DEPLOYMENT_NAME=gpt-4.1-mini

# Microsoft Graph API
MS_GRAPH_TENANT_ID=<tenant_id>
MS_GRAPH_CLIENT_ID=<client_id>
MS_GRAPH_CLIENT_SECRET=<client_secret>
MS_GRAPH_SENDER_EMAIL=<sender_email>

# SharePoint
SHAREPOINT_SITE_URL=https://gulfcraft.sharepoint.com/sites/costing
SP_SITE_ID=<site_id>
SP_LIST_ID=<list_id>
SHAREPOINT_LIST_NAME=CostingJobs

# Email (Office 365)
SMTP_SERVER=smtp.office365.com
SMTP_PORT=587
SMTP_EMAIL=<email>
SMTP_PASSWORD=<password>
IMAP_SERVER=outlook.office365.com
IMAP_PORT=993
NOTIFICATION_EMAIL=<email>
VENDOR_DEFAULT_EMAIL=<vendor_email>

# OCR (Mistral)
AZURE_MISTRAL_ENDPOINT=<endpoint>
AZURE_MISTRAL_API_KEY=<key>

# Security
SECRET_KEY=<secret>
ACCESS_TOKEN_EXPIRE_MINUTES=30
ALGORITHM=HS256

# Langfuse (Optional)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# Templates
COSTING_TEMPLATE_PATH=templates/costing_template.xlsx

# Monitoring
EMAIL_POLL_INTERVAL=60
```

### 4. Initialize Database
```bash
cd backend
python -c "from core.database import init_db; init_db()"
```

### 5. Frontend Setup
```bash
cd frontend
npm install
```

## Running the Application

### Development

#### Terminal 1: Backend API
```bash
cd backend
python -m uvicorn core.api:app --host 0.0.0.0 --port 8000 --reload
```
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

#### Terminal 2: Email Monitor (Optional)
```bash
python backend/services/email_monitor.py
```
Polls inbox for vendor quote responses via IMAP.

#### Terminal 3: Frontend
```bash
cd frontend
npm run dev
```
- UI: http://localhost:5173

### Production

Deployed on Azure App Service with GitHub Actions CI/CD. See [AZURE_DEPLOYMENT.md](AZURE_DEPLOYMENT.md) and [DEPLOYMENT_QUICKSTART.md](DEPLOYMENT_QUICKSTART.md).

## Usage

### Web UI (Recommended)

1. Navigate to http://localhost:5173
2. Login with your credentials
3. Use the **Chat** tab for conversational interaction or the **Requests** tab to view/manage jobs

#### Example conversations:

**Search & Create Jobs**
```
"I need boat polishing for MAJESTY62"
"Find quotations for hydraulic pump repair"
"Show me 10 results"
```

**Modify Jobs**
```
"Add 50 meters of cable to this job"
"Remove the anchor winch"
"Change quantity of pump to 5"
"Update price to 850 AED"
```

**Quote Management**
```
"Vendor quoted 1200 AED for the hydraulic pump"
"Resend quote request to vendor@example.com"
"Cancel the quote request for item 3"
```

**Job Lifecycle**
```
"Approve this job"
"Download costing sheet for COST-12345"
"Duplicate this job for a different boat"
"Send costing sheet to manager@gulfcraft.com"
```

**Pricing Intelligence**
```
"What did we pay for hydraulic pumps before?"
"Average price for item XYZ-123"
"Is 1500 AED a good price for this item?"
```

**Vendor Information**
```
"Tell me about vendor@example.com"
"Who supplies hydraulic parts?"
"Which vendor is best for electrical items?"
```

**Status**
```
"Show my jobs"
"Status of COST-12345"
"What's pending?"
```

### CLI (Testing)

```bash
cd backend
python main.py
```

### API

```bash
# Authenticate
curl -X POST http://localhost:8000/token \
  -d "username=user&password=pass"

# Chat
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "I need boat polishing for MAJESTY62"}'

# List jobs
curl http://localhost:8000/requests \
  -H "Authorization: Bearer <token>"

# Search products
curl "http://localhost:8000/products/search?q=pump" \
  -H "Authorization: Bearer <token>"
```

Full API documentation at http://localhost:8000/docs.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/token` | Login (OAuth2 password flow) |
| `GET` | `/users/me` | Current user info |
| `POST` | `/chat` | Send message to agent |
| `GET` | `/chat/history/{id}` | Conversation history |
| `POST` | `/chat/upload-quote` | Upload PDF for OCR extraction |
| `POST` | `/chat/confirm-quote-matches` | Confirm OCR-matched quotes |
| `GET` | `/requests` | List all costing jobs |
| `GET` | `/requests/{job_id}` | Job details |
| `POST` | `/requests/{job_id}/items` | Add line item |
| `PUT` | `/requests/{job_id}/items/{item_id}` | Update line item |
| `DELETE` | `/requests/{job_id}/items/{item_id}` | Delete line item |
| `POST` | `/requests/{job_id}/approve` | Approve job |
| `GET` | `/requests/{job_id}/download` | Download costing sheet |
| `GET` | `/products/search` | Search products by name or code |
| `GET` | `/health` | Health check |

## Project Structure

```
gulfcraft/
├── backend/
│   ├── agents/
│   │   ├── supervisor.py          # Intent routing
│   │   ├── search.py              # Quotation search
│   │   ├── refinement.py          # Result formatting
│   │   ├── selection.py           # User selection handling
│   │   ├── costing.py             # Job creation & pricing
│   │   ├── status.py              # Job status queries
│   │   ├── edit_job.py            # Item modifications
│   │   ├── quote_management.py    # Vendor quote handling
│   │   ├── job_lifecycle.py       # Approval & distribution
│   │   ├── pricing_advisor.py     # Price history analysis
│   │   ├── explainer.py           # Explanation agent
│   │   └── vendor_info.py         # Vendor intelligence
│   ├── core/
│   │   ├── api.py                 # FastAPI app & endpoints
│   │   ├── config.py              # Configuration
│   │   ├── database.py            # SQLAlchemy models
│   │   └── state.py               # LangGraph AgentState
│   ├── services/
│   │   ├── email_monitor.py       # IMAP polling service
│   │   ├── pdf_extractor.py       # PDF quote extraction
│   │   └── ocr_matcher.py         # OCR item matching
│   ├── utils/
│   │   ├── llm.py                 # LLM initialization
│   │   ├── prompts.py             # Prompt templates
│   │   ├── tools.py               # Tool implementations
│   │   ├── langfuse_tracing.py    # Tracing decorators
│   │   └── lifecycle_tracing.py   # Job lifecycle metrics
│   ├── templates/
│   │   └── costing_template.xlsx  # Excel template
│   ├── tests/                     # Unit tests
│   └── main.py                    # CLI entry point
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Login.jsx          # Authentication page
│   │   │   └── Dashboard.jsx      # Main UI (chat, requests, job details)
│   │   ├── components/            # Reusable components
│   │   ├── api.js                 # Axios API client
│   │   ├── App.jsx                # Router setup
│   │   └── main.jsx               # React entry point
│   ├── package.json
│   └── vite.config.js
├── .github/workflows/             # CI/CD pipelines
│   ├── deploy-azure.yml           # Backend deployment
│   ├── deploy-frontend.yml        # Frontend deployment
│   └── deploy-email-monitor.yml   # Email service deployment
├── requirements.txt
├── .env
└── README.md
```

## Configuration

### Key Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint | Yes |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | GPT-4 deployment name | Yes |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME` | Embedding model deployment | Yes |
| `OPENAI_API_KEY` | Azure OpenAI API key | Yes |
| `MS_GRAPH_CLIENT_ID` | Azure AD app client ID | Yes |
| `MS_GRAPH_CLIENT_SECRET` | Azure AD app secret | Yes |
| `MS_GRAPH_TENANT_ID` | Azure AD tenant ID | Yes |
| `SECRET_KEY` | JWT signing key | Yes |
| `SMTP_EMAIL` | Email for sending quotes | Yes |
| `SMTP_PASSWORD` | Email password | Yes |
| `AZURE_MISTRAL_API_KEY` | Mistral OCR API key | Yes |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | Optional |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | Optional |
| `PROFIT_MARGIN` | Markup multiplier (default: 1.5) | No |
| `PRICE_THRESHOLD` | Quote threshold in AED (default: 1000) | No |
| `TOP_K_ITEMS` | Default search results count (default: 5) | No |

### Database Schema

| Table | Purpose |
|-------|---------|
| `users` | User accounts with roles |
| `conversations` | Chat sessions |
| `messages` | Conversation messages |
| `costing_requests` | Costing jobs with status tracking |
| `costing_line_items` | Job line items with price sources |
| `products` | Product catalog with vendor info |
| `quotation_lines` | Historical quotations with embeddings |
| `estimation_lines` | Item estimations and pricing |

### Price Sources

Items track prices from multiple sources:
- **Products** - Database catalog lookup
- **Quotation** - Vendor email responses
- **Manual** - User-entered prices
- **Labour** - Hourly rate calculations
- **Pending** - Awaiting vendor quote

## Observability

### Langfuse Tracing (3-Level Hierarchy)

```
Trace: conv_123 (Conversation)
  +-- Span: supervisor_node
  +-- Span: search_node
  |     +-- Span: search_similar_quotations (tool)
  +-- Span: selection_node
  +-- Session: COST-ABC123 (Costing Job)
        +-- Span: costing_node
        +-- Span: resolve_prices
        |     +-- Span: get_product_price (Item 1)
        |     +-- Span: get_product_price (Item N)
        +-- Span: generate_sheet
        +-- Span: send_quote_emails
```

## Deployment

Azure App Service with GitHub Actions CI/CD. See:
- [DEPLOYMENT_QUICKSTART.md](DEPLOYMENT_QUICKSTART.md) - Quick setup
- [AZURE_DEPLOYMENT.md](AZURE_DEPLOYMENT.md) - Full guide
- [AZURE_MONITORING_SETUP.md](AZURE_MONITORING_SETUP.md) - Monitoring

## Documentation

- [capabilities.md](capabilities.md) - Detailed feature reference
- [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) - Implementation details
- [LANGFUSE_TRACING_PLAN.md](LANGFUSE_TRACING_PLAN.md) - Tracing architecture
- [FRONTEND_BACKEND_INTEGRATION.md](FRONTEND_BACKEND_INTEGRATION.md) - API integration guide
- [OCR Matcher](backend/services/OCR_MATCHER_README.md) - OCR matching documentation

## Troubleshooting

### Database Connection
```bash
psql $DATABASE_URL -c "SELECT 1"
psql $DATABASE_URL -c "SELECT * FROM pg_extension WHERE extname='vector'"
```

### Langfuse Not Tracking
Verify `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set in `.env`. Check application logs for Langfuse initialization errors.

### Email Monitor Issues
```bash
# Test IMAP connection
python -c "import imaplib; imaplib.IMAP4_SSL('outlook.office365.com', 993)"
```

Verify `SMTP_EMAIL`, `SMTP_PASSWORD`, `IMAP_SERVER`, and `IMAP_PORT` are configured correctly.

## Version

**Current Version**: 2.0.0

**Recent Updates**:
- 12-agent multi-agent system with LangGraph orchestration
- Hybrid semantic + keyword search with boat model filtering
- Job editing agent (add/remove/update items)
- Quote management with PDF OCR extraction
- Job lifecycle management (approve/duplicate/distribute)
- Pricing advisor with historical analysis and anomaly detection
- Vendor performance tracking and intelligence
- React web UI with chat and requests tabs
- Azure deployment with GitHub Actions CI/CD
- Hierarchical Langfuse tracing (conversation > job > operation)

See [COMPLETE_CHANGES_SUMMARY.md](COMPLETE_CHANGES_SUMMARY.md) for detailed changelog.
