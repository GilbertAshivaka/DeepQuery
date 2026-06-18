# Deploying DeepQuery

DeepQuery is a **stateful, multi-service** system, not a stateless API. Any deployment
must run, with durable storage, all of:

| Service | Image / entrypoint | State | Notes |
|---|---|---|---|
| Backend API | `uvicorn backend.main:app` | — | FastAPI; serves `/api`, `/auth`, SSE |
| Celery worker | `celery -A backend.tasks.celery_app worker` | — | ingestion + skill-sync; **long-running** |
| Redis | `redis:8-alpine` (AOF on) | volume | broker **and** durable agent checkpoints — needs RedisJSON + RediSearch (Redis 8) |
| ChromaDB | `chromadb/chroma` | volume | vector store |
| Neo4j | `neo4j:5-community` | volume | knowledge graph |
| Frontend | static build → nginx | — | React/Vite SPA |
| nginx | `nginx:alpine` | — | reverse proxy (single public origin) |

Two traits decide the platform:

1. **Durable, long-lived processes.** Celery workers carry *resumable* agent state, and
   SSE streams survive disconnect. These need always-on compute with tolerant timeouts —
   **not** ephemeral functions (Lambda / Vercel / Cloud-Run-for-everything won't fit).
2. **A hard Redis constraint.** `langgraph-checkpoint-redis` needs **Redis 8 with
   RedisJSON + RediSearch** and **AOF persistence** (paused agent runs are a source of
   truth — see `RESUMABLE_AGENT_SPEC_V2`). A generic "managed Redis" / cache instance
   will silently break durable agents.

The repo already ships a complete compose stack — see [docker/docker-compose.yml](docker/docker-compose.yml),
[docker/Dockerfile.backend](docker/Dockerfile.backend), [docker/Dockerfile.frontend](docker/Dockerfile.frontend),
and [docker/nginx.conf](docker/nginx.conf) — so the deployment story is "run my compose
on persistent compute."

---

## Route A — Single VM + Docker Compose  *(recommended now)*

The least-surprising path: one dedicated-CPU VM running the existing compose. Full control
over the Redis modules, volumes, and the Tesseract-bearing backend image; cheapest; no
per-service re-plumbing. Trade-off: you own backups/updates and it's single-host (no HA).

### 1. Provision a host

- **Size:** 4–8 vCPU (dedicated), **16–32 GB RAM**. Neo4j, ChromaDB, and the
  sentence-transformers reranker are the memory-hungry pieces.
- **Disk:** 50–100 GB SSD (document store + Chroma + Neo4j + Redis AOF grow over time).
- **Providers:** Hetzner (best price/perf, e.g. CCX23/CCX33), DigitalOcean, AWS Lightsail/EC2.
- Install Docker Engine + the compose plugin. No need to install Python/Tesseract on the
  host — they're baked into the backend image.

### 2. Configure secrets

Create a `.env` at the repo root (compose reads it via `env_file`). **Generate real values** —
do not ship the dev defaults:

```dotenv
APP_ENV=production

# Auth + credential encryption (generate strong values)
JWT_SECRET_KEY=<openssl rand -hex 32>
# Fernet key — REQUIRED in prod, or stored connector credentials are lost on every restart:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CONNECTOR_ENCRYPTION_KEY=<fernet-key>

# External AI providers
GOOGLE_API_KEY=<gemini-embedding key>
GROQ_API_KEY=<groq key>

# Neo4j (must match the neo4j service's NEO4J_AUTH — see step 3)
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<strong-password>

# Public origin (single domain; everything is proxied through nginx)
FRONTEND_URL=https://deepquery.example.com
CORS_ORIGINS=https://deepquery.example.com
```

### 3. Three required edits to docker-compose.yml

The committed compose is tuned for local dev. Before deploying, change:

1. **Add `AGENT_REDIS_URL`** to the `backend` **and** `celery-worker` `environment:` blocks —
   it is currently unset, so inside the container it defaults to `localhost` and **durable
   agents silently fall back to non-resumable**:
   ```yaml
   - AGENT_REDIS_URL=redis://redis:6379/0
   ```
2. **Parameterize Neo4j auth** so it matches `.env` (compose hard-codes the dev password):
   ```yaml
   neo4j:
     environment:
       - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
   ```
3. **Remove the dev conveniences from `backend` / `celery-worker`:** delete the
   `../backend:/app/backend` source bind-mount, and drop `--reload` from the backend command
   (override the image `CMD` or edit [docker/Dockerfile.backend](docker/Dockerfile.backend)) so the
   container runs the baked code, not a live mount.

> The frontend talks to the backend via **relative URLs** through nginx (`/api`, `/auth`),
> so there is **no API URL to bake into the frontend build** — one origin, no CORS gymnastics.
> nginx already disables buffering on the SSE route and allows 100 MB uploads
> (see [docker/nginx.conf](docker/nginx.conf)).

### 4. Launch

```bash
git clone <repo> && cd DeepQuery
# create .env (step 2) and apply the compose edits (step 3)
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f backend
```

App is served by nginx on port 80. Put a TLS terminator in front (Caddy/Traefik, or a
cloud load balancer) for HTTPS — with a **long read timeout / no idle cap** on the SSE path
so streaming agent runs aren't cut off.

### 5. Back up the volumes

The durable state lives entirely in named volumes: `redis_data` (agent checkpoints + queue),
`chroma_data`, `neo4j_data`, `document_store`, `sqlite_data`. Snapshot the VM disk and/or
`docker run --rm -v <vol>:/data ... tar` these on a schedule. Redis AOF + `everysec` fsync
bounds loss to ≤1 s.

---

## Before real traffic — hardening checklist  *(do when ready)*

Not required to boot, but do these before production load:

- [ ] **Migrate SQLite → Postgres.** Compose ships `DATABASE_URL=sqlite:///./deepquery.db`.
      Fine for a pilot on one host; replace with Postgres before scaling the backend
      horizontally or under heavy concurrent Celery writes.
- [ ] **Real secrets management** (not a committed `.env`): Docker secrets, SOPS, or the
      platform's secret store. Rotate `JWT_SECRET_KEY`, `CONNECTOR_ENCRYPTION_KEY`, provider keys.
- [ ] **TLS + a reverse proxy** with sticky-friendly, long-lived SSE handling.
- [ ] **Resource limits / healthchecks** per service; pin image digests.
- [ ] **Confirm Redis durability** survives restart (AOF file present in `redis_data`).
- [ ] **Backups tested** (restore drill), not just taken.

---

## Route B — Railway / Render  *(later: managed, push-to-deploy)*

When you want push-to-deploy + managed Postgres + less server babysitting. Viable, **but**
this stack has three gotchas that the naive "add the Redis plugin" approach gets wrong:

1. **Do NOT use the managed/plugin Redis.** It's vanilla Redis — no RedisJSON/RediSearch, so
   resumable agents break. Deploy **`redis:8-alpine` as a custom service with a volume and
   `--appendonly yes`**, exactly like the compose definition.
2. **Chroma and Neo4j are core, not optional.** Each needs its **own attached persistent
   volume/disk** — without it, data is wiped on every redeploy.
3. **Use managed Postgres** (both platforms offer it) and point `DATABASE_URL` at it; drop
   SQLite. Also switch the Celery worker off `--pool=solo` (a Windows-dev workaround) to
   prefork concurrency on Linux.

Map the services as: Backend (web), Celery (background worker, no port), Redis 8 (custom +
volume), Chroma (custom + volume), Neo4j (custom + volume), Frontend (static/nginx), Postgres
(managed). Set the same env vars as Route A, with internal service hostnames for the URLs and
`AGENT_REDIS_URL` pointing at the Redis 8 service. Render maps slightly more cleanly (explicit
Background Worker + private services + disks); Railway is fine too.

---

## Route C — Kubernetes  *(only at real scale)*

Worth it once you need HA + independent autoscaling of many Celery workers, or multi-tenant
scale. StatefulSets (or managed equivalents: Neo4j Aura, Redis Cloud with modules, managed
Postgres) for the stateful tier; HPA on the worker deployment. The compose→k8s jump is
straightforward later — don't pay this ops tax now.

---

## Quick reference — service env vars

Read by the backend/worker (names are case-insensitive; see [backend/core/config.py](backend/core/config.py)):

| Var | Compose value | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./deepquery.db` | relational metadata (→ Postgres in prod) |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | task queue |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | task results |
| `AGENT_REDIS_URL` | `redis://redis:6379/0` | **durable agent checkpoints (must set!)** |
| `CHROMA_HOST` / `CHROMA_PORT` | `chroma` / `8000` | vector store |
| `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` | `bolt://neo4j:7687` / `neo4j` / … | knowledge graph |
| `GOOGLE_API_KEY` / `GROQ_API_KEY` | — | Gemini embeddings / Groq LLM |
| `JWT_SECRET_KEY` | — | auth signing (set in prod) |
| `CONNECTOR_ENCRYPTION_KEY` | — | Fernet key for stored credentials (set in prod) |
| `FRONTEND_URL` / `CORS_ORIGINS` | localhost defaults | public origin |
