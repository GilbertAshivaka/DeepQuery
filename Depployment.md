## **Deploying DeepQuery to Railway.app**

---

## **Step 1: Prepare Your Railway Project**

1. Go to **[railway.app](https://railway.app)** and log in
2. Create a **new project**
3. Connect your GitHub repository (`GilbertAshivaka/DeepQuery`)

---

## **Step 2: Add Services to Your Railway Project**

Railway will deploy each component as a separate service:

### **Service 1: Frontend (React/Vite)**
- Click **"+ New Service"** → **Deploy from GitHub**
- Select your repo
- **Set Dockerfile path:** `frontend/Dockerfile` (if it exists) OR use `npm`
- **Root Directory:** `frontend`
- **Start Command:** `npm run build && npm run preview`
- **Port:** `5173` or `3000`

### **Service 2: Backend API (FastAPI)**
- Click **"+ New Service"** → **Deploy from GitHub**
- **Set Dockerfile path:** `docker/Dockerfile.backend` 
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port 8000`
- **Port:** `8000`
- **Root Directory:** `backend`

### **Service 3: Celery Worker**
- Click **"+ New Service"** → **Deploy from GitHub**
- **Set Dockerfile path:** `docker/Dockerfile.backend` (same as backend)
- **Start Command:** `celery -A tasks.celery_app worker --loglevel=info --pool=solo`
- **Port:** (no port needed, it's a worker)

### **Service 4: Redis (Plugin)**
- Click **"+ New"** → **Add Plugin** → **Redis**
- Railway will auto-provision Redis

### **Service 5: ChromaDB (Optional - via Docker)**
- Click **"+ New Service"** → **Deploy from GitHub**
- **Set Dockerfile:** Custom image: `chromadb/chroma:latest`
- **Port:** `8000`

### **Service 6: Neo4j (Optional - via Docker)**
- Click **"+ New Service"** → **Deploy from GitHub**
- **Set Dockerfile:** Custom image: `neo4j:latest`
- **Port:** `7687`

---

## **Step 3: Configure Environment Variables**

For **Backend API** service, set in Railway dashboard:

```
GOOGLE_API_KEY=your-google-api-key
GROQ_API_KEY=your-groq-api-key
REDIS_URL=${{ Redis.REDIS_URL }}
CHROMA_URL=http://chromadb:8000
NEO4J_URL=bolt://neo4j:password@neo4j:7687
DATABASE_URL=your-postgres-url (if using external DB)
```

For **Celery Worker** service, set the same:

```
GOOGLE_API_KEY=your-google-api-key
GROQ_API_KEY=your-groq-api-key
REDIS_URL=${{ Redis.REDIS_URL }}
CHROMA_URL=http://chromadb:8000
NEO4J_URL=bolt://neo4j:password@neo4j:7687
```

---

## **Step 4: Update Your `.env` Files (Local Reference)**

Before deploying, your local `backend/.env` should look like:

```dotenv
GOOGLE_API_KEY=your-key
GROQ_API_KEY=your-key
REDIS_URL=redis://localhost:6379/0  # Local dev
CHROMA_URL=http://localhost:8100
```

Railway will override these via the dashboard UI.

---

## **Step 5: Deploy**

1. Each service will auto-trigger on commit push to `main`
2. Monitor **Deployments** tab in Railway
3. Check **Logs** for errors in each service
4. Once all services are **"Running"**, your app is live!

---

## **Step 6: Access Your Deployed App**

| Component | URL |
|-----------|-----|
| **Frontend** | `https://your-railway-domain.railway.app` |
| **Backend API** | `https://backend-service.railway.app` |
| **API Docs** | `https://backend-service.railway.app/docs` |
| **Health Check** | `https://backend-service.railway.app/health` |

---

## **Important Notes**

- **Railway generates unique URLs** for each service automatically
- **Update frontend API calls** to point to Railway Backend URL (e.g., `https://backend-service.railway.app`)
- **Celery & Frontend must know the Backend URL** → set via environment variables in Railway
- **Redis is internal to Railway** → services connect via `${{ Redis.REDIS_URL }}`
- **Dockerfiles in `docker/` folder** will be used automatically if they exist

---

## **Troubleshooting on Railway**

| Issue | Solution |
|-------|----------|
| **Services can't communicate** | Use Railway's internal network (`redis`, `chromadb`, etc. as hostnames) |
| **Environment variables not set** | Use Railway dashboard syntax: `${{ ServiceName.ENV_VAR }}` |
| **Celery tasks failing** | Check logs in Railway → ensure Redis URL is correct |
| **Frontend can't reach backend** | Set `REACT_APP_API_URL` to Railway backend domain in frontend service |
| **Port conflicts** | Railway auto-assigns ports; don't hardcode |

---
