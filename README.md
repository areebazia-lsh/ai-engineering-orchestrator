# AI Engineering Orchestrator

An agentic AI system for software engineering teams. Understands codebases, plans tasks, generates patches, and maintains long-term project knowledge.

## Architecture Overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Context    │────▶│   Router    │────▶│   Planner   │
│  Manager    │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
                    ┌─────────────┐     ┌─────────────┐
                    │ Knowledge   │────▶│  Response   │
                    │   Agent     │     │ Generator   │
                    └─────────────┘     └─────────────┘
                    ┌─────────────┐
                    │ CodeIntel   │
                    │   Agent     │
                    └─────────────┘
                    ┌─────────────┐
                    │  Coding     │
                    │   Agent     │
                    └─────────────┘
                    ┌─────────────┐     ┌─────────────┐
                    │  Testing    │────▶│ Validation  │
                    │   Agent     │     │   Agent     │
                    └─────────────┘     └─────────────┘
```

## Phases

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Core orchestrator (Context, Router, Planner, Response) | ✅ Done |
| 2 | RAG (Vector storage, embeddings, KnowledgeAgent) | ✅ Done |
| 3 | Code Intelligence (AST analysis, dependencies) | ✅ Done |
| 4 | Code Modification (Patch generation, validation) | ✅ Done |
| 5 | Memory (Long-term storage, context summarization) | ✅ Done |
| 6 | Testing (Test generation, validation, retry loop) | ✅ Done |
| Frontend | Chat, DiffViewer, PatchApproval | ✅ Done |

## Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Supabase project (free tier works)
- LLM API key (OpenAI, Anthropic, or Groq)

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your values
# - SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
# - LLM_API_KEY (one of OpenAI, Anthropic, or Groq)

# Run the database schema (in Supabase Dashboard → SQL Editor)
# Copy and run the contents of supabase_schema.sql

# Start the server
uvicorn app.main:app --reload
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Copy environment template
cp .env.example .env.local

# Edit .env.local if needed

# Start dev server
npm run dev
```

## Usage

1. Open http://localhost:3000
2. Create a new project or select an existing one
3. Upload files or use the CLI to ingest your codebase
4. Ask questions about your code or request changes
5. Review and approve patches via the DiffViewer

## CLI Ingestion

```bash
# Ingest a repository
python scripts/ingest_repo.py --path /path/to/repo --name "Project Name"

# Check ingestion status
python scripts/check_vectors.py
```

## API Endpoints

- `POST /api/v1/chat/messages` - Send a chat message
- `GET /api/v1/projects` - List projects
- `POST /api/v1/projects` - Create a project
- `POST /api/v1/projects/{id}/ingest` - Trigger ingestion
- `GET /api/v1/projects/{id}/ingest/status` - Get ingestion status
- `POST /api/v1/patches/apply` - Apply a patch
- `POST /api/v1/patches/rollback` - Rollback a patch
- `GET /api/v1/patches/history/{project_id}` - Get patch history

## Deploy with Docker

```bash
# Copy .env files with your configuration
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local

# Build and run
docker compose up --build
```

## Project Structure

```
ai-engineering-orchestrator/
├── backend/
│   ├── app/
│   │   ├── agents/         # Agent implementations
│   │   ├── analysis/       # AST analysis
│   │   ├── api/            # API routes
│   │   ├── core/           # Core utilities
│   │   ├── database/       # Database utilities
│   │   ├── ingestion/      # Ingestion pipeline
│   │   ├── knowledge/      # Vector storage
│   │   ├── memory/         # Long-term memory
│   │   ├── models/         # LLM providers
│   │   ├── orchestration/  # LangGraph workflow
│   │   └── services/       # Business logic
│   ├── scripts/            # CLI scripts
│   ├── supabase_schema.sql
│   └── requirements.txt
├── frontend/
│   ├── app/                # Next.js pages
│   ├── components/         # React components
│   ├── lib/                # Utilities
│   └── package.json
└── infra/
    ├── docker-compose.yml
    └── docker/
```

## Troubleshooting

### Backend won't start
- Check .env file exists with valid values
- Verify Supabase connection
- Check LLM API key is valid

### Frontend won't connect to backend
- Verify NEXT_PUBLIC_API_URL in .env.local
- Check CORS settings in backend .env
- Ensure backend is running

### Ingestion fails
- Check Supabase permissions
- Verify file paths are correct
- Check logs for specific errors

## License

MIT