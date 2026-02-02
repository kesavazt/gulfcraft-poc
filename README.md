# Gulf Craft Costing Agent

An intelligent AI-powered costing system with multi-agent workflow automation, integrated observability, and enterprise integrations.

## 🚀 Features

- **Multi-Agent Workflow**: Supervisor, Search, Selection, Costing, and Status agents working together
- **Conversational AI**: Natural language interaction with context-aware responses
- **Hierarchical Tracing**: Complete observability with Langfuse (conversation → job → operation levels)
- **Smart Search**: Search items by name OR code with intelligent ranking
- **Enterprise Integration**: SharePoint, Microsoft Graph API, Email (SMTP/IMAP)
- **Real-time Status**: LLM-powered conversational status updates
- **Automated Workflows**: Price resolution, quote requests, sheet generation

## 📋 Architecture

### Backend Stack
- **Framework**: FastAPI 0.104+
- **AI Orchestration**: LangGraph + LangChain
- **Database**: PostgreSQL 15+ with pgvector extension
- **ORM**: SQLAlchemy 2.0+

### AI Services
- **LLM**: Azure OpenAI (GPT-4)
- **Embeddings**: Azure OpenAI (text-embedding-3-small)
- **OCR**: Mistral AI
- **Observability**: Langfuse 3.12.1+

### Integrations
- **Microsoft Graph API**: Mail & SharePoint operations
- **Email**: SMTP/IMAP for quote management
- **SharePoint**: List item management and file storage

### Frontend
- **Framework**: React 18+ with TypeScript
- **Routing**: React Router v6
- **HTTP Client**: Axios
- **Styling**: Tailwind CSS (optional)

## 🛠️ Prerequisites

### Required
- **Python**: 3.10 or 3.11 (recommended)
- **Node.js**: 16+ (for frontend)
- **Database**: PostgreSQL 15+ with pgvector extension
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```

### External Services
1. **Azure OpenAI**
   - GPT-4 deployment for chat
   - text-embedding-3-small deployment for embeddings

2. **Microsoft Graph API**
   - Azure AD App Registration
   - Permissions: Mail.Send, Sites.ReadWrite.All

3. **Mistral AI**
   - API key for OCR functionality

4. **Langfuse** (optional but recommended)
   - Cloud account at https://cloud.langfuse.com
   - Public and Secret keys

## 📦 Installation

### 1. Clone Repository
```bash
git clone <repo_url>
cd gulfcraft
```

### 2. Backend Setup

#### Create Virtual Environment
```bash
# Using conda (recommended)
conda create -n gulfcraft python=3.11
conda activate gulfcraft

# Or using venv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
```

#### Install Dependencies
```bash
pip install -r requirements.txt
```

#### Configure Environment
Create `.env` file in the root directory:

```ini
# Application Config
TOP_K_ITEMS=3
PRICE_THRESHOLD=1000.0
PROFIT_MARGIN=1.5

# Database
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/gulfcraft

# Azure OpenAI
OPENAI_API_TYPE=azure
OPENAI_API_KEY=<your_azure_key>
OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=gpt-4.1
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small

# Microsoft Graph API
MS_GRAPH_TENANT_ID=<tenant_id>
MS_GRAPH_CLIENT_ID=<client_id>
MS_GRAPH_CLIENT_SECRET=<client_secret>
MS_GRAPH_SENDER_EMAIL=<sender_email>

# SharePoint
SP_SITE_ID=<site_id>
SP_LIST_ID=<list_id>
SHAREPOINT_LIST_NAME=<list_name>

# Email Config
SMTP_EMAIL=<email>
SMTP_PASSWORD=<password>
GMAIL_APP_PASSWORD=<app_password>  # If using Gmail
NOTIFICATION_EMAIL=<notification_email>
VENDOR_DEFAULT_EMAIL=<vendor_email>

# Langfuse (Optional)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# Mistral AI
MISTRAL_API_KEY=<your_mistral_key>

# Templates
COSTING_TEMPLATE_PATH=templates/costing_template.xlsx
```

#### Initialize Database
```bash
cd backend
python -c "from core.database import init_db; init_db()"
```

### 3. Frontend Setup

```bash
cd frontend
npm install
```

## 🚀 Running the Application

### Development Mode

Run all three components simultaneously:

#### Terminal 1: Backend API
```bash
cd backend
python -m uvicorn core.api:app --host 0.0.0.0 --port 8000 --reload
```
- API Documentation: http://localhost:8000/docs
- Interactive docs: http://localhost:8000/redoc

#### Terminal 2: Email Monitor (Optional)
```bash
python backend/services/email_monitor.py run
```
Monitors inbox for vendor quote responses.

#### Terminal 3: Frontend
```bash
cd frontend
npm run dev
```
- Access UI: http://localhost:5173

### Production Mode

See [AZURE_DEPLOYMENT.md](AZURE_DEPLOYMENT.md) for production deployment instructions.

## 📖 Usage

### Via Web UI (Recommended)

1. Navigate to http://localhost:5173
2. Login with your credentials
3. Start a conversation:
   - **Search**: "I need boat polishing for MAJESTY62"
   - **Status**: "What's the status of my jobs?"
   - **Details**: "Show me details for COST-ABC12345"

### Via CLI (Testing)

```bash
cd backend
python main.py
```

Example conversation:
```
User: I need engine maintenance for NOMAD95
Agent: [Searches similar quotations]

User: 1
Agent: [Confirms selection]

User: Yes
Agent: [Creates costing job COST-XXXXXXXX]

User: What's the status?
Agent: [Shows job status conversationally]
```

### Via API

```bash
# Create conversation
curl -X POST http://localhost:8000/conversations \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "I need boat polishing for MAJESTY62"}'

# Get status
curl http://localhost:8000/conversations/1 \
  -H "Authorization: Bearer <token>"

# Search items (for adding to jobs)
curl "http://localhost:8000/products/search?q=pump" \
  -H "Authorization: Bearer <token>"
```

See API documentation at http://localhost:8000/docs for full endpoint list.

## 🧪 Testing

### Run Unit Tests
```bash
cd backend
python tests/test_status_agent.py
python tests/test_item_search.py
```

### Test Complete Workflow
```bash
cd backend
python main.py
```
Then follow the prompts to test search → selection → costing flow.

### Verify Langfuse Tracing
1. Run a complete workflow
2. Visit https://cloud.langfuse.com
3. Navigate to Traces → find your conversation ID
4. Verify hierarchical structure:
   - Trace (conversation)
   - Sessions (costing jobs)
   - Spans (agents, tools)

## 📊 System Features

### Agent Workflow

```
User Query → Supervisor Agent
              ↓
    ┌─────────┼─────────┐
    ↓         ↓         ↓
SearchAgent  SelectionAgent  StatusAgent
    ↓         ↓         ↓
Quotations   Confirmation   Job Status
             ↓
         CostingAgent
             ↓
    ┌────────┼────────┐
    ↓        ↓        ↓
Resolve    Generate  Send
Prices     Sheet    Quotes
```

### Hierarchical Tracing

```
📊 Trace: conv_123 (Conversation)
  ├─ Span: supervisor_node
  ├─ Span: search_node
  │  └─ Span: search_similar_quotations (tool)
  ├─ Span: selection_node
  └─ Session: COST-ABC123 (Costing Job)
     ├─ Span: costing_node
     ├─ Span: resolve_prices
     │  ├─ Span: get_product_price (Item 1)
     │  └─ Span: get_product_price (Item N)
     ├─ Span: generate_sheet
     └─ Span: send_quote_emails
```

### Item Search

Search by name OR code:
```bash
GET /products/search?q=pump

# Returns:
[
  {
    "item_code": "PUMP-1200",
    "item_name": "Bilge Pump 1200 GPH",
    "unit_cost": 89.99,
    "vendor_email": "marine@supplier.com",
    "source": "estimation"
  }
]
```

## 📁 Project Structure

```
gulfcraft/
├── backend/
│   ├── agents/              # Agent nodes (supervisor, search, costing, etc.)
│   ├── core/                # Core modules (api, config, database, state)
│   ├── services/            # Services (email monitor, search)
│   ├── utils/               # Utilities (LLM, tools, prompts, tracing)
│   ├── tests/               # Unit tests
│   └── main.py              # CLI entry point
├── frontend/
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── pages/           # Page components
│   │   └── App.tsx          # Main app
│   └── package.json
├── templates/               # Excel templates
├── .env                     # Environment configuration
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## 🔧 Configuration

### Key Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | ✅ |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint | ✅ |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | GPT-4 deployment name | ✅ |
| `MS_GRAPH_CLIENT_ID` | Azure AD app client ID | ✅ |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | ⚠️ Optional |
| `PROFIT_MARGIN` | Markup multiplier (default: 1.5) | ❌ |
| `PRICE_THRESHOLD` | Quote threshold (default: 1000) | ❌ |

### Database Schema

Main tables:
- `users` - User accounts
- `conversations` - Chat conversations
- `messages` - Conversation messages
- `costing_requests` - Costing jobs
- `costing_line_items` - Job line items
- `pending_quote_requests` - Quote tracking
- `products` - Product catalog
- `quotation_lines` - Historical quotations
- `estimation_lines` - Item estimations

## 📚 Documentation

- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Complete implementation details
- **[LANGFUSE_TRACING_PLAN.md](LANGFUSE_TRACING_PLAN.md)** - Tracing architecture
- **[STATUS_AGENT_UPDATE.md](STATUS_AGENT_UPDATE.md)** - Status agent documentation
- **[ITEM_SEARCH_API.md](ITEM_SEARCH_API.md)** - Item search API guide
- **[AZURE_DEPLOYMENT.md](AZURE_DEPLOYMENT.md)** - Azure deployment guide
- **[COMPLETE_CHANGES_SUMMARY.md](COMPLETE_CHANGES_SUMMARY.md)** - All changes summary

## 🐛 Troubleshooting

### Database Connection Issues
```bash
# Test connection
psql $DATABASE_URL -c "SELECT 1"

# Check pgvector extension
psql $DATABASE_URL -c "SELECT * FROM pg_extension WHERE extname='vector'"
```

### Langfuse Not Tracking
```bash
# Verify environment variables
echo $LANGFUSE_PUBLIC_KEY
echo $LANGFUSE_SECRET_KEY

# Check logs for initialization
grep -i langfuse backend/logs/*
```

### Email Monitor Issues
```bash
# Test IMAP connection
python -c "import imaplib; imaplib.IMAP4_SSL('imap.gmail.com', 993)"

# Check credentials
python backend/services/email_monitor.py test
```

## 🚀 Deployment

See [AZURE_DEPLOYMENT.md](AZURE_DEPLOYMENT.md) for:
- Azure App Service vs Container Apps comparison
- Step-by-step deployment instructions
- Environment configuration
- Database setup on Azure
- CI/CD pipeline configuration

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## 📝 License

[Your License Here]

## 🆘 Support

For issues or questions:
1. Check documentation in the docs folder
2. Review error logs in `backend/logs/`
3. Contact: [Your Support Email]

## 📊 Version

**Current Version**: 2.0.0

**Recent Updates**:
- ✅ Hierarchical Langfuse tracing (3-level: conversation → job → operation)
- ✅ Conversational status agent with LLM-powered responses
- ✅ Enhanced item search (search by name OR code)
- ✅ Cleaned up tracing module (40% reduction in code)
- ✅ Complete observability with Langfuse 3.12.1

See [COMPLETE_CHANGES_SUMMARY.md](COMPLETE_CHANGES_SUMMARY.md) for detailed changelog.
