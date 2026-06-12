# Deep Query — Setup & Run Guide

> Semantic Knowledge Management Ecosystem — Pwani University

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| **Python** | 3.11+ | Backend API & Celery worker |
| **Node.js** | 18+ | Frontend build tooling |
| **Docker** | 20+ | Redis, ChromaDB, Neo4j containers |
| **Git** | any | Version control |

---

## 1. Clone & Configure

```bash
git clone <repo-url> DeepQuery
cd DeepQuery
```

### Create the backend `.env` file

```bash
cp .env.example backend/.env
```

Edit `backend/.env` and fill in your API keys:

```dotenv
# ---- Google AI (Gemini Embedding 2) ----
GOOGLE_API_KEY=your-google-api-key-here

# ---- Groq (Llama 3.3 70B) ----
GROQ_API_KEY=your-groq-api-key-here
```

> Get a Google API key at https://aistudio.google.com/apikey
> Get a Groq API key at https://console.groq.com/keys

---

## 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate it
# Windows (Git Bash / MINGW):
source venv/Scripts/activate
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Also install the new Google GenAI SDK (required for embeddings)
pip install google-genai
```

---

## 3. Frontend Setup

```bash
cd frontend

# Install Node.js dependencies
npm install
```

---

## 4. Start Docker Containers

Open a terminal and run these commands to start the infrastructure services:

### Redis (Celery broker + agent run state)

Redis 8 is required (bundles the RedisJSON + RediSearch modules used by the agent
checkpointer). AOF persistence (`--appendonly yes`) is **mandatory**: paused agent runs
(awaiting approval/answers) live in Redis checkpoints, so Redis must survive restarts
without losing them. The named volume keeps the AOF across container recreations.

```bash
docker run -d \
  --name deepquery-redis \
  -p 6379:6379 \
  -v deepquery_redis_data:/data \
  redis:8-alpine \
  redis-server --appendonly yes --appendfsync everysec
```

### ChromaDB (vector database)

```bash
docker run -d \
  --name deepquery-chroma \
  -p 8100:8000 \
  -e IS_PERSISTENT=TRUE \
  -e ANONYMIZED_TELEMETRY=FALSE \
  chromadb/chroma:latest
```

### Neo4j (knowledge graph) — Optional

```bash
docker run -d \
  --name deepquery-neo4j \
  -p 7474:7474 \
  -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/deepquery_dev_password \
  neo4j:latest
```

> Neo4j is optional. The pipeline will skip the knowledge graph stage gracefully if Neo4j is not running.

### Verify containers are running

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected output:

```
NAMES              STATUS         PORTS
deepquery-redis    Up X minutes   0.0.0.0:6379->6379/tcp
deepquery-chroma   Up X minutes   0.0.0.0:8100->8000/tcp
deepquery-neo4j    Up X minutes   0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

---

## 5. Start All Services

You need **4 terminals** running simultaneously:

### Terminal 1 — Backend API (FastAPI)

```bash
cd backend
source venv/Scripts/activate        # or your OS equivalent
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at **http://localhost:8000**
Health check: http://localhost:8000/health

### Terminal 2 — Celery Worker (async document processing)

```bash
cd backend
source venv/Scripts/activate        # or your OS equivalent
celery -A tasks.celery_app worker --loglevel=info --pool=solo
```

> **Windows note:** The `--pool=solo` flag is required on Windows. On Linux/macOS you can omit it or use `--pool=prefork --concurrency=2`.

### Terminal 3 — Frontend (Vite dev server)

```bash
cd frontend
npm run dev
```

The app will be available at **http://localhost:5173**

### Terminal 4 — (Free terminal for Docker, Git, etc.)

Keep one terminal free for running Docker commands, checking logs, etc.

---

## 6. Access the Application

| URL | Purpose |
|-----|---------|
| http://localhost:5173 | **Frontend** (main app) |
| http://localhost:8000 | **Backend API** |
| http://localhost:8000/docs | **Swagger API docs** |
| http://localhost:8000/health | **Health check** |
| http://localhost:7474 | **Neo4j Browser** (if running) |

### Default Admin Credentials

```
Username: admin
Password: admin1234
```

> A default admin user is automatically created on first startup.

---

## 7. Common Operations

### Re-queue failed ingestion jobs

```bash
cd backend
source venv/Scripts/activate
python requeue_pending.py
```

### Flush Celery queues (clear queued tasks)

> ⚠️ Do **not** use `FLUSHALL` or `FLUSHDB` on db 0 anymore — db 0 also holds durable
> agent run state (checkpoints for paused/resumable runs; RediSearch requires db 0).
> Delete only Celery's queue key, and flush db 1 (results only) if needed:

```bash
docker exec deepquery-redis redis-cli -n 0 DEL celery
docker exec deepquery-redis redis-cli -n 1 FLUSHDB
```

### Restart a Docker container

```bash
docker restart deepquery-redis
docker restart deepquery-chroma
docker restart deepquery-neo4j
```

### Stop all Docker containers

```bash
docker stop deepquery-redis deepquery-chroma deepquery-neo4j
```

### Start all Docker containers (after a reboot)

```bash
docker start deepquery-redis deepquery-chroma deepquery-neo4j
```

### Remove and recreate a container (fresh start)

```bash
docker rm -f deepquery-redis
docker run -d --name deepquery-redis -p 6379:6379 -v deepquery_redis_data:/data \
  redis:8-alpine redis-server --appendonly yes --appendfsync everysec
```

### Check Celery worker registered tasks

Look for the `[tasks]` section in the Celery startup output. You should see:

```
[tasks]
  . tasks.run_ingestion_pipeline
```

---

## 8. Docker Compose (Alternative)

Instead of running individual containers, you can use Docker Compose to start **everything** (including backend, frontend, and Celery worker):

```bash
cd docker
docker-compose up -d
```

To stop:

```bash
docker-compose down
```

> Note: The compose setup uses different internal hostnames (e.g., `chroma` instead of `localhost`). The environment variables are overridden in `docker-compose.yml`.

---

## 9. Project Architecture

```
DeepQuery/
├── backend/
│   ├── main.py                  # FastAPI entry point
│   ├── .env                     # Environment variables (secrets)
│   ├── requirements.txt         # Python dependencies
│   ├── api/                     # REST API routes
│   │   ├── router.py            # Main router
│   │   ├── auth.py              # Login / logout / refresh
│   │   ├── documents.py         # Upload, list, delete documents
│   │   ├── query.py             # Chat / semantic search
│   │   └── admin.py             # Admin panel endpoints
│   ├── core/                    # App config, DB, constants
│   │   ├── config.py            # Pydantic settings
│   │   ├── database.py          # SQLAlchemy setup
│   │   └── constants.py         # Enums (roles, job status)
│   ├── models/                  # SQLAlchemy & Pydantic models
│   │   ├── database.py          # ORM models (User, Document, etc.)
│   │   └── schemas.py           # API request/response schemas
│   ├── ingestion/               # Document processing pipeline
│   │   ├── pipeline.py          # 6-stage orchestrator
│   │   ├── parser_pdf.py        # PDF → blocks (PyMuPDF)
│   │   ├── parser_docx.py       # DOCX → blocks
│   │   ├── chunker.py           # Blocks → semantic chunks
│   │   └── ocr_module.py        # Tesseract OCR (scanned pages)
│   ├── embeddings/
│   │   └── gemini_embedder.py   # Gemini Embedding 2 (google-genai SDK)
│   ├── vectorstore/
│   │   └── chroma_store.py      # ChromaDB client
│   ├── knowledge_graph/
│   │   └── neo4j_store.py       # Neo4j client
│   ├── retrieval/               # Search & RAG pipeline
│   │   ├── pipeline.py          # Hybrid retrieval + reranking + LLM
│   │   ├── bm25_retriever.py    # BM25 sparse retrieval
│   │   └── reranker.py          # Cross-encoder reranker
│   ├── llm/                     # LLM integration
│   │   └── groq_client.py       # Groq Llama 3.3 70B
│   ├── tasks/                   # Celery async tasks
│   │   ├── celery_app.py        # Celery configuration
│   │   └── ingestion_task.py    # Ingestion pipeline task
│   └── auth/                    # JWT token management
│       └── jwt_handler.py
├── frontend/
│   ├── src/
│   │   ├── components/          # React components
│   │   ├── pages/               # Route pages
│   │   ├── store/               # Zustand state management
│   │   └── services/            # API service layer
│   ├── package.json
│   └── vite.config.js
└── docker/
    ├── docker-compose.yml       # Full stack compose
    ├── Dockerfile.backend
    ├── Dockerfile.frontend
    └── nginx.conf
```

---

## 10. Ingestion Pipeline Stages

When a document is uploaded, the Celery worker processes it through 6 stages:

| Stage | Name | Service | Description |
|-------|------|---------|-------------|
| 1 | **Parse** | PyMuPDF / python-docx | Extract text blocks, images, tables |
| 2 | **Chunk** | Custom chunker | Split into ~500-token semantic chunks |
| 3 | **OCR** | Tesseract (optional) | OCR scanned pages for BM25 index |
| 4a | **Embed** | Google Gemini API | Generate 3072-dim vectors per chunk |
| 4b | **Entities** | Groq Llama 3.3 70B | Extract named entities from each chunk |
| 4c | **Metadata** | Groq Llama 3.3 70B | Generate summary, tags, category |
| 5 | **ChromaDB** | ChromaDB | Store vectors + metadata |
| 6 | **Neo4j** | Neo4j (optional) | Build knowledge graph |

---

## 11. Troubleshooting

### "ModuleNotFoundError: No module named 'ingestion'"
The Celery worker can't find sibling packages. This is already handled in the code with `sys.path` fixes. Make sure you're running Celery **from the `backend/` directory**.

### Documents stuck at "PENDING"
- Check that the Celery worker is running and shows the task `tasks.run_ingestion_pipeline`
- Check Redis is running: `docker ps | grep redis`
- Flush stale tasks: `docker exec deepquery-redis redis-cli -n 0 DEL celery` (never `FLUSHALL`/`FLUSHDB 0` — they would wipe agent run state)
- Re-queue: `python requeue_pending.py`

### "document closed" error on PDFs
Restart the Celery worker to pick up the latest code. The worker caches Python modules.

### Embeddings failing
- Verify your `GOOGLE_API_KEY` in `backend/.env` is valid
- Test it: `python -c "from google import genai; c=genai.Client(api_key='YOUR_KEY'); print(c.models.embed_content(model='gemini-embedding-2-preview', contents='test'))"`

### Celery worker won't start on Windows
Always use `--pool=solo` on Windows:
```bash
celery -A tasks.celery_app worker --loglevel=info --pool=solo
```

### Port already in use
```bash
# Find what's using port 8000 (Windows)
netstat -ano | findstr :8000
# Kill it
taskkill /PID <pid> /F
```
