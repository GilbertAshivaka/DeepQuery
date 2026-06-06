# Deep Query — Latency Optimization Guide
**Supplementary to the Copilot Build Guide**
*Covers all agreed performance improvements to reduce query response time from 60+ seconds to under 20 seconds. No code is included — this document describes architectural changes, data flow modifications, and implementation contracts.*

---

## Scope & Decisions

The following optimizations are to be implemented:

| # | Optimization | Expected Impact |
|---|---|---|
| 1 | Parallel pipeline execution | 40–60% latency reduction |
| 2 | Non-blocking self-correction | Eliminates one full LLM round-trip from perceived wait time |
| 3 | Redis query cache | Sub-100ms response on cache hits |
| 4 | BM25 index permanently in memory | Eliminates disk I/O on every query |
| 5 | Neo4j subgraph caching | Eliminates repeated graph queries for popular entities |
| 6 | Cross-encoder pre-filter | Halves the reranker's workload |
| 7 | Connection pre-warming | Eliminates cold-start cost on first request |

The following were explicitly excluded and must remain unchanged:
- Prompt size and context window sent to the LLM — full context is preserved.
- The cross-encoder reranker model — it stays as-is, only the input volume changes.
- LLM model selection — `llama-3.3-70b-versatile` is used for all LLM calls without exception.
- Groq API integration — no changes to how Groq is called.

---

## Implementation Order

Implement in this exact sequence. Each step produces a measurable before/after latency benchmark. Do not skip ahead — later steps build on earlier ones, and caching added too early will mask the true pipeline speed making benchmarking inaccurate.

1. BM25 index in memory
2. Parallel pipeline execution
3. Connection pre-warming
4. Cross-encoder pre-filter
5. Redis query cache
6. Neo4j subgraph caching
7. Non-blocking self-correction

---

## 1. BM25 Index Permanently in Memory

### Problem Being Solved
The BM25 sparse search index is currently loaded from disk or rebuilt on every query. This adds significant latency before the search even begins.

### What Changes
The BM25 index must be built once during server startup and held as an application-level in-memory object for the lifetime of the server process. It is never loaded from disk at query time.

### Startup Behaviour
During FastAPI's `startup` event, after all other services have initialised, the BM25 index builder runs. It fetches the text content of all chunks from the document metadata store, partitions them by ChromaDB collection name (`academic`, `departmental`, `administrative`, `management`), and builds one BM25 index per collection. All four indexes are stored as application state variables accessible to the query pipeline.

Building four indexes at startup takes a few seconds — this is acceptable as a one-time cost. The server is not considered ready to serve traffic until all indexes are built.

### Query Time Behaviour
At query time, the BM25 search immediately uses the in-memory indexes corresponding to the collections the user has access to. No disk read, no index construction, no file I/O of any kind.

### Keeping the Index Current
When the Celery ingestion pipeline finishes ingesting a new document, it publishes a message to a Redis pub/sub channel named `bm25_update`. The message contains the collection name and the new chunk texts that were added. The FastAPI process subscribes to this channel and updates the relevant in-memory BM25 index incrementally — appending the new chunks to the existing corpus without rebuilding from scratch.

This means the BM25 index stays current without requiring a server restart after every document ingestion.

### Collections Partitioning
Maintaining one BM25 index per collection is required — not optional. It enforces the same access control on sparse retrieval that ChromaDB enforces on dense retrieval. A user with access to only the `academic` collection must only search the `academic` BM25 index.

---

## 2. Parallel Pipeline Execution

### Problem Being Solved
The current query pipeline is almost entirely sequential. Steps that have no dependency on each other are waiting for previous steps to finish unnecessarily. The cumulative wait across 10 sequential steps is the primary source of the 60+ second latency.

### Dependency Map
Before implementing parallelism, the dependency relationships between pipeline steps must be clearly understood:

**Group A — no dependencies, can start the instant the query arrives:**
- Gemini Embedding 2 call (takes the raw query string as input)
- BM25 sparse search (takes the raw query string as input — no embedding required)
- Llama 3 entity extraction (takes the raw query string as input — no embedding required)

**Group B — each depends on one Group A result, but are independent of each other:**
- ChromaDB dense vector search (depends on the embedding from Group A)
- Neo4j graph traversal (depends on the entities extracted in Group A)

**Group C — depends on all Group B results being available:**
- Reciprocal Rank Fusion (depends on BM25 results from Group A and dense results from Group B)
- Cross-encoder reranking (depends on RRF output)
- Context assembly (depends on reranked chunks and Neo4j context)

**Group D — final sequential step:**
- Llama 3 generation (depends on the assembled context from Group C, streams to user)

### LangChain Implementation
LangChain's `RunnableParallel` is the correct tool for Groups A and B. Group A is implemented as a `RunnableParallel` with three branches: embedding, BM25 search, and entity extraction. These three branches execute concurrently. Group B is implemented as a second `RunnableParallel` with two branches: ChromaDB dense search and Neo4j traversal, both of which receive the outputs they need from Group A.

`RunnableParallel` handles the concurrency internally — there is no need to manually manage async tasks or thread pools for these steps. LangChain resolves the branches and waits for all to complete before passing outputs to the next step in the chain.

### FastAPI Async Coordination
The FastAPI endpoint handler for `/query/chat` and `/query/search` must be defined as an `async` function. Any calls made outside of LangChain chains (such as cache lookups, Redis writes, or background task dispatch) must use `await` rather than blocking calls to avoid stalling the event loop.

### Race Condition Risk
Parallel execution introduces the possibility of race conditions if shared state is written by multiple concurrent branches. The pipeline has no shared mutable state between branches — each branch reads input and produces output independently. This is safe by design, but must be preserved. Do not introduce any shared mutable variables that multiple parallel branches write to.

### Testing After Implementation
After implementing parallel execution, run the 50-question evaluation set and confirm that retrieval precision and answer quality are unchanged. Parallelism must not change what the system retrieves — only how fast it retrieves it.

---

## 3. Connection Pre-Warming

### Problem Being Solved
On a cold server start, the first query pays the cost of establishing TCP connections, completing TLS handshakes, and initialising connection pools to every external service. This can add 2–5 seconds to the first request.

### What Changes
During FastAPI's `startup` event, after the BM25 indexes are built, the server makes one minimal no-op call to each external service. The purpose of each call is solely to establish the connection — not to do any useful work.

### Warmup Calls Required

**Gemini Embedding 2 (Google AI API):**
Embed a single short string such as "warmup". The result is discarded. This establishes the HTTPS connection and completes the TLS handshake with the Google AI API endpoint.

**Groq API:**
Make a completion call with `max_tokens=1` and a trivial single-word prompt. The result is discarded. This establishes the connection to Groq's inference endpoint.

**ChromaDB:**
Run a simple collection list query. No search, no vectors. This opens the connection to the ChromaDB server.

**Neo4j:**
Run the simplest valid read Cypher query — something that returns a single constant. This opens the Bolt connection and initialises the driver's connection pool.

**Redis:**
Send a `PING` command. Verify the `PONG` response. This confirms Redis is reachable and opens the connection pool.

### Error Handling for Warmup
If any warmup call fails, the server must log a clear warning but must still start. A warmup failure is not a fatal error — it means the first real request will pay the cold start cost, but the system remains functional. Do not block server startup on warmup success.

### Placement in Startup Sequence
The startup sequence must follow this order:
1. Load configuration from environment variables.
2. Initialise all service clients (ChromaDB, Neo4j driver, Redis client, Groq client, Gemini client).
3. Build BM25 indexes (requires ChromaDB and Redis to be ready).
4. Run connection warmup calls.
5. Mark server as ready to accept traffic.

---

## 4. Cross-Encoder Pre-Filter

### Problem Being Solved
The cross-encoder reranker currently receives all candidates produced by RRF fusion — up to 40 items (top 20 dense + top 20 BM25, deduplicated). Scoring 40 candidate pairs on CPU is the primary source of reranking latency. The reranker model itself is not changed.

### What Changes
A cosine similarity threshold filter is inserted between the RRF fusion step and the cross-encoder reranker. Any candidate chunk whose cosine similarity score (from the ChromaDB dense search result) falls below the threshold is removed from the candidate list before it reaches the reranker.

The reranker then processes a smaller, higher-quality candidate set — typically 15–20 items instead of 40. The reranker model, its configuration, and its output remain identical.

### Threshold Value
The starting threshold is **0.45**. This means any chunk with a cosine similarity below 0.45 is discarded before reranking.

After running the 50-question evaluation set, this threshold should be tuned:
- If retrieval precision drops noticeably, raise the threshold toward 0.50 — you are discarding too aggressively.
- If reranking is still slow and precision is holding, lower the threshold toward 0.40.
- Never go below 0.35 — chunks below that score are almost certainly irrelevant and their inclusion would harm answer quality.

### Chunks That Fall Below the Threshold
Chunks below the threshold are silently discarded. They do not appear in the sources array, are not sent to the LLM, and are not shown in the Query Retrieval Confidence chart. This is correct behaviour — they were not relevant enough to use.

### Interaction With Minimum Context Requirement
If the pre-filter removes so many candidates that fewer than 3 chunks remain for the reranker, the threshold must be relaxed for that query. In this situation, take the top 5 candidates by cosine similarity score regardless of threshold and send those to the reranker. This prevents the edge case where a very niche query produces low similarity scores across all candidates but still has some useful context available.

---

## 5. Redis Query Cache

### Problem Being Solved
Many queries submitted by university users are repetitive — especially common policy questions, well-known research topics, and frequently asked administrative queries. Running the full pipeline for every instance of the same question wastes time and API credits.

### Cache Key Construction
The cache key must be constructed from two components:
- A hash (SHA-256) of the normalised query string. Normalisation means: lowercase, strip leading/trailing whitespace, collapse multiple spaces to one. This ensures "What is the data retention policy?" and "what is the data retention policy ?" resolve to the same key.
- The user's `allowed_collections` list, sorted alphabetically and joined as a string before hashing.

Both components are hashed together into a single key. This ensures that two users with different access roles asking the same question receive results appropriate to their role, not each other's.

### Cache Lookup Position
The cache lookup is the very first operation in the query endpoint handler — before embedding, before BM25, before anything. If the cache returns a hit, the full pipeline is skipped and the cached payload is returned immediately.

### What Is Cached
The complete response payload is cached, including: the answer text, the sources array (with relevance scores and citation metadata), the self-correction status, and the knowledge graph context summary. Everything the frontend needs to render the full response.

### What Is Never Cached
INSUFFICIENT_CONTEXT responses must never be written to the cache. These responses mean the system could not find relevant information — but new documents are being ingested continuously, and a future query might now be answerable. Caching a "not found" response would serve stale negative results even after relevant documents have been added.

### TTL (Time to Live)
Default TTL: **24 hours**. After 24 hours the cache entry expires and the next query for that key runs the full pipeline, refreshing the cache.

For a university setting where the document corpus changes slowly, this TTL can safely be extended to 48 hours during stable periods.

### Cache Invalidation on Ingestion
When the Celery ingestion pipeline successfully completes ingesting a new document into a specific collection, it must publish that collection name to a Redis pub/sub channel named `cache_invalidation`. The FastAPI process subscribes to this channel and flushes all cache entries whose key includes that collection name.

This ensures that after a new policy document is ingested into the `administrative` collection, users querying about that policy get a fresh pipeline result rather than a cached answer that predates the new document.

### Admin Cache Control
A cache management section must be added to the admin panel backend. Expose the following endpoints:
- `DELETE /admin/cache/flush` — flushes the entire query cache. Admin role only.
- `DELETE /admin/cache/flush/{collection}` — flushes only cache entries for a specific collection. Admin role only.

These give admins manual control to force cache refresh after large batch ingestion events without waiting for TTL expiry.

### Cache Hit Indicator
When a cached response is returned, the API response must include a metadata flag `cache_hit: true`. The frontend should display a subtle indicator (e.g., a small "cached" badge near the answer timestamp) so that users and admins are aware the response came from cache. This is important for an accuracy-positioned product — users should know when they are receiving a cached answer versus a freshly computed one.

---

## 6. Neo4j Subgraph Caching

### Problem Being Solved
The Neo4j graph traversal runs on every query that contains named entities, even when the same entity has been looked up many times in the past hour. Graph traversal queries, especially at 2-hop depth on a growing corpus, contribute measurable latency.

### What Is Cached
Two types of Neo4j results are cached in Redis:

**Entity subgraph results:** The serialised subgraph (nodes, edges, and natural-language context summary) for each entity lookup. Cache key: `neo4j:entity:{entity_name_normalised}:{hop_depth}`. TTL: **6 hours**.

**Graph overview result:** The top-50-most-connected entities and their relationships, used by the Knowledge Graph visualization page on load. Cache key: `neo4j:overview`. TTL: **12 hours**.

### Cache Lookup at Query Time
After entity extraction produces a list of named entities from the user's query, each entity is looked up in the Redis cache before any Neo4j query is made. Only entities not present in the cache trigger a Neo4j traversal. All results — whether from cache or from Neo4j — are merged into the same context assembly step.

If all entities in a query are cache hits, Neo4j receives zero queries for that request. The knowledge graph context is assembled entirely from cached subgraphs.

### Cache Invalidation on Ingestion
When the Celery ingestion pipeline writes new entity triples to Neo4j, it publishes the list of affected entity names to a Redis pub/sub channel named `neo4j_cache_invalidation`. The FastAPI process subscribes to this channel and deletes the cache entries for the affected entities.

The graph overview cache (`neo4j:overview`) is invalidated whenever any new entity is added to Neo4j, since the overview includes degree centrality which changes with every new relationship.

### Serialisation Format
Neo4j subgraph results are serialised as JSON before writing to Redis. The JSON structure contains: a list of node objects (id, name, type, properties), a list of edge objects (source id, target id, relationship type), and the pre-generated natural-language context summary string that gets injected into the RAG prompt. Deserialisation at cache hit time reconstructs this structure and proceeds directly to context assembly.

---

## 7. Non-Blocking Self-Correction

### Problem Being Solved
The self-correction step currently runs as a blocking sequential call after generation completes. This means the user waits for two full LLM round trips before seeing any response: one for generation, one for verification. The self-correction step contributes the same latency as the generation step — effectively doubling the wait time.

### Architectural Change
Self-correction becomes a background task that runs concurrently with the answer being streamed to the user. The user receives the first streaming token within seconds of the generation starting. Self-correction runs in parallel on the server. If corrections are needed, they are pushed to the user after the stream completes.

### SSE Event Types
The existing `/query/chat` SSE endpoint must support two distinct event types:

**`answer_token`:** One event per generated token, sent as the LLM streams its response. This is the existing behaviour, unchanged.

**`verification_result`:** A single event sent after self-correction completes, carrying the verification outcome. This event has three possible payloads:
- `{ status: "VERIFIED" }` — no action needed, the answer stands as streamed.
- `{ status: "CORRECTED", amendments: [...] }` — one or more claims were corrected. The amendments array lists which citations were affected and what the correction is.
- `{ status: "INSUFFICIENT_CONTEXT", message: "..." }` — the system could not find sufficient grounding. A warning message is included.

The SSE connection remains open after the last `answer_token` event, waiting for the `verification_result` event. Once the `verification_result` event is sent, the connection closes.

### Frontend Handling
The frontend SSE handler must be updated to process both event types:

For `answer_token` events: existing streaming behaviour — append each token to the chat bubble as it arrives.

For `verification_result` events: check the status field and update the UI accordingly.
- `VERIFIED`: display the verified badge on the answer. No changes to the answer text.
- `CORRECTED`: display the corrected badge. Append an amendment section below the answer text listing which citations were revised and what changed. The original streamed text is not retroactively edited — the amendment appears as a clearly labelled addendum.
- `INSUFFICIENT_CONTEXT`: display the warning badge. Append the insufficient context message below the answer.

### Timing of the Verification Call
The self-correction Llama 3 call is dispatched using FastAPI's `BackgroundTasks` mechanism at the same moment the generation stream begins — not after it ends. By the time the generation stream completes (typically 10–15 seconds), the self-correction call has often already finished running in the background. In the best case, the `verification_result` SSE event fires within 1–2 seconds of the last `answer_token` event. In the worst case (both finish at similar times), there is a short pause before verification arrives — but the user already has the answer and is reading it.

### Cache Interaction
Self-correction results must be included in the Redis query cache payload. When a cached response is returned, the frontend receives the pre-verified answer with the verification status already embedded — no background self-correction task is dispatched for cache hits. The user immediately sees a verified answer with the appropriate badge.

### Self-Correction Is Still Mandatory
Making self-correction non-blocking does not make it optional. Every query that runs the full pipeline must trigger a self-correction task. The change is only in when the result is delivered to the user, not whether verification happens.

---

## Latency Benchmarking

After implementing all changes, run a structured benchmark using the 50-question evaluation set. Measure the following for each query:

- **Time to first token (TTFT):** From query submission to the first `answer_token` SSE event arriving at the frontend. Target: under 4 seconds.
- **Time to last token (TTLT):** From query submission to the last `answer_token` event. Target: 10–20 seconds (varies by answer length and full context size).
- **Time to verification result:** From query submission to the `verification_result` SSE event. Target: within 3 seconds of TTLT.
- **Cache hit response time:** For repeated queries. Target: under 150ms end-to-end.

Compare these benchmarks against a baseline measurement taken before any optimizations are applied. Document the before/after for each optimization step so the impact of each individual change is recorded.

---

*End of Deep Query Latency Optimization Guide*
*Supplement to: Deep Query Copilot Build Guide*
*Author: Gilbert 