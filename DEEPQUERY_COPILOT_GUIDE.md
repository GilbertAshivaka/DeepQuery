# Deep Query — Copilot Build Guide
**Semantic Knowledge Management Ecosystem for Pwani University**
*A technical implementation guide. No code is included — this document describes architecture, data flow, component responsibilities, and integration contracts.*

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Technology Stack](#2-technology-stack)
3. [Repository & Project Structure](#3-repository--project-structure)
4. [System Architecture Overview](#4-system-architecture-overview)
5. [Pipeline 1: Data Ingestion & Processing](#5-pipeline-1-data-ingestion--processing)
6. [Pipeline 2: Query & Retrieval](#6-pipeline-2-query--retrieval)
7. [Knowledge Graph Subsystem](#7-knowledge-graph-subsystem)
8. [Backend API Layer](#8-backend-api-layer)
9. [Frontend Application](#9-frontend-application)
10. [Authentication & RBAC](#10-authentication--rbac)
11. [LangChain Orchestration Design](#11-langchain-orchestration-design)
12. [Gemini Embedding 2 Integration](#12-gemini-embedding-2-integration)
13. [ChromaDB Vector Store Design](#13-chromadb-vector-store-design)
14. [Groq + Llama 3 Integration](#14-groq--llama-3-integration)
15. [Self-Correction Mechanism](#15-self-correction-mechanism)
16. [Metadata & Proactive Knowledge Discovery](#16-metadata--proactive-knowledge-discovery)
17. [Testing & Evaluation Strategy](#17-testing--evaluation-strategy)
18. [Environment Configuration](#18-environment-configuration)
19. [Development Phases & Sprint Map](#19-development-phases--sprint-map)

---

## 1. Project Overview

Deep Query is a Semantic Knowledge Management Ecosystem designed to replace keyword-based search within institutional academic settings, beginning with Pwani University. It ingests diverse document types, converts them into semantically meaningful vector representations, and allows users to query the knowledge base through either a conversational chat interface or a structured document search dashboard.

The system produces synthesized, cited answers rather than returning a list of documents. It reasons across multiple documents using a combination of a vector similarity search pipeline and a knowledge graph that captures explicit entity relationships.

The two users of the system are:
- **Staff and students** who query the knowledge base.
- **Administrators** who upload, manage, and curate documents.

---

## 2. Technology Stack

### Backend
| Concern | Technology |
|---|---|
| Primary language | Python 3.11+ |
| Web framework | FastAPI |
| RAG orchestration | LangChain |
| Embedding model | Gemini Embedding 2 (`gemini-embedding-exp-03-07`) via Google AI API |
| LLM for generation & extraction | Llama 3.3 70B via Groq API |
| Vector database | ChromaDB (persistent, local) |
| Knowledge graph database | Neo4j (local or AuraDB) |
| OCR engine | Tesseract OCR via `pytesseract` wrapper — used only for BM25 sparse index text extraction from scanned pages, not for embedding |
| Document parsing | PyMuPDF (for PDFs), `python-docx` (for Word), BeautifulSoup (for HTML) |
| NER / entity extraction | Llama 3 via Groq (LLM-based extraction) |
| Task queue (async ingestion) | Celery with Redis as broker |
| Authentication | JWT (JSON Web Tokens) |

### Frontend
| Concern | Technology |
|---|---|
| Framework | React 18 |
| Styling | Tailwind CSS |
| State management | Zustand |
| HTTP client | Axios |
| Chat UI rendering | Custom React components with streaming support |
| Markdown & citation rendering | `react-markdown` with custom citation component |
| Document viewer | `react-pdf` for inline PDF display |

### Infrastructure
| Concern | Technology |
|---|---|
| Containerisation | Docker + Docker Compose |
| Reverse proxy | Nginx |
| Storage (raw documents) | Local filesystem (mapped Docker volume) |
| Environment management | `.env` files with `python-dotenv` |

---

## 3. Repository & Project Structure

The project should be organised as a monorepo with clear separation between the backend, frontend, and supporting services.

```
deep-query/
├── backend/
│   ├── api/                  # FastAPI route handlers
│   ├── core/                 # Config, settings, constants
│   ├── ingestion/            # Data ingestion pipeline modules
│   ├── retrieval/            # Query pipeline modules
│   ├── knowledge_graph/      # Neo4j interaction and graph building
│   ├── embeddings/           # Gemini Embedding 2 wrapper
│   ├── llm/                  # Groq/Llama 3 wrapper and prompt templates
│   ├── vectorstore/          # ChromaDB wrapper and collection management
│   ├── auth/                 # JWT auth, RBAC middleware
│   ├── models/               # Pydantic data models and schemas
│   ├── tasks/                # Celery async tasks (ingestion jobs)
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── components/       # Reusable UI components
│   │   ├── pages/            # Route-level page components
│   │   ├── store/            # Zustand state slices
│   │   ├── services/         # API service layer (Axios calls)
│   │   └── utils/
│   └── public/
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.backend
│   └── Dockerfile.frontend
├── chroma_data/              # Persisted ChromaDB volume
├── neo4j_data/               # Persisted Neo4j volume
├── document_store/           # Raw uploaded documents
├── .env.example
└── README.md
```

---

## 4. System Architecture Overview

The system has two distinct operational pipelines that share the same data stores.

### Ingestion-Time (Document enters the system)
A document uploaded by an admin triggers the ingestion pipeline. The pipeline preprocesses the document, splits it into semantic chunks, generates multimodal embeddings using Gemini Embedding 2, and stores both the vectors (ChromaDB) and extracted entity relationships (Neo4j). This process runs asynchronously via a Celery task queue so the upload endpoint returns immediately without blocking.

### Query-Time (User asks a question)
A user query is embedded using the same Gemini Embedding 2 model. The embedded query is sent to the Retrieval Orchestration Layer, which runs a hybrid search (dense vector similarity + sparse BM25 keyword search) against ChromaDB. The top results are reranked for relevance. In parallel, the knowledge graph is queried for related entities. The merged context is passed through a LangChain RAG chain backed by Llama 3 on Groq, which produces a synthesized answer. A self-correction step verifies the answer for factual grounding before returning it to the user with inline citations.

### Shared Data Stores
- **ChromaDB**: Stores document chunk embeddings and associated metadata (source document, page number, chunk index, document type, access role, timestamp).
- **Neo4j**: Stores entities (people, organisations, concepts, topics, places) and their typed relationships as extracted from documents.
- **Local filesystem**: Stores the original raw uploaded documents for reference and for the document viewer in the UI.

---

## 5. Pipeline 1: Data Ingestion & Processing

This pipeline is triggered when an admin uploads a document through the UI. Each stage must be treated as a discrete, testable module.

### Stage 1: Document Reception & Storage
- The FastAPI upload endpoint accepts files in PDF, DOCX, and HTML formats.
- The raw file is saved to the `document_store/` directory with a UUID-based filename.
- File metadata (original filename, uploader user ID, upload timestamp, document type, assigned access role/collection) is recorded in a lightweight SQLite or PostgreSQL metadata table.
- The upload endpoint enqueues a Celery task with the file path and metadata, then returns a `202 Accepted` response to the client with a job ID that the frontend can poll.

### Stage 2: Data Ingestion Engine
The ingestion engine is the core pre-processing module. It receives a file path and determines the document type, then routes to the appropriate parser.

**PDF Parser (PyMuPDF)**
- Extract text layer directly when the PDF contains selectable text.
- Detect pages with no text layer (scanned pages). These pages are handled in two ways: the page image is stored for direct embedding via Gemini Embedding 2 (native image input), and separately passed through the OCR sub-module to produce text for the BM25 sparse search index only.
- Extract table structures from PDF pages using layout analysis. Complex visually-structured tables (merged cells, colour-coded headers) should be stored as images for direct multimodal embedding. Simple flat tables can be converted to structured text.
- Extract embedded images and store them as separate assets (PNG/JPEG) linked back to their source document and page number. These assets are passed directly to Gemini Embedding 2 — they are not OCR'd before embedding.
- Preserve page number metadata for every extracted block of text.

**Word Document Parser (python-docx)**
- Extract paragraph text while preserving heading hierarchy (H1, H2, H3 etc.) as structural metadata.
- Extract embedded tables as structured text.
- Extract embedded images and store them as separate PNG/JPEG assets for direct multimodal embedding via Gemini Embedding 2.

**HTML Parser (BeautifulSoup)**
- Strip navigation, headers, footers, and boilerplate elements.
- Extract main content body.
- Preserve link context where the link text is meaningful to the surrounding content.

**OCR Sub-module (Tesseract) — Sparse Index Only**
- The role of OCR has changed significantly with Gemini Embedding 2. Tesseract is no longer used to convert images into text before embedding. That step is eliminated entirely — images are now embedded natively and directly.
- Tesseract is retained for one specific purpose: extracting text from scanned pages or image-only documents to feed the BM25 sparse keyword search index. BM25 operates on raw text and has no multimodal capability, so it still needs a text representation of scanned content.
- Pre-process scanned page images (deskew, binarise, noise reduction) before passing to Tesseract to improve OCR output quality.
- OCR output text is written only to the BM25 index. It is never passed to the embedding API.
- The `ocr_flag` metadata field in ChromaDB should be set to `true` for any chunk whose BM25 text representation was produced by OCR, signalling to downstream components that the sparse search text for this chunk may be lower-confidence than normal.
- If OCR quality is very poor for a given page (very low confidence score from Tesseract), that page is still embedded natively as an image — it simply will not participate in sparse BM25 retrieval. The dense vector retrieval path remains unaffected.

### Stage 3: Semantic Chunking
After raw text extraction, content must be split into chunks that preserve semantic coherence. This is not simple character-based splitting.

**Chunking strategy:**
- Use LangChain's `RecursiveCharacterTextSplitter` as the base, but configure it to split first on paragraph boundaries, then on sentence boundaries, only resorting to character limits as a last resort.
- Target chunk size: approximately 400–600 tokens. This balances retrieval precision against embedding quality.
- Overlap between consecutive chunks: 50–80 tokens. This ensures that a sentence at the boundary of one chunk is also represented in the next, preventing retrieval misses at chunk edges.
- Tables extracted from documents should be treated as atomic chunks and not split mid-table.
- Heading context should be prepended to each chunk so that a chunk from a section titled "Environmental Impact Assessment" retains that context even when retrieved in isolation.
- Images extracted from documents are treated as their own separate chunks. They are stored as image assets and passed directly to Gemini Embedding 2's image input at embedding time — no text conversion occurs. Each image chunk carries metadata linking it back to its source document, page number, and any associated caption text found nearby.

### Stage 4: Feature Extraction
Three sub-processes run on each chunk in parallel after chunking.

**4a. Embedding Generation (Gemini Embedding 2)**

Gemini Embedding 2 handles all three chunk types through a single API, eliminating the old requirement to convert everything to text first.

- **Text chunks**: passed as plain text strings. Maximum 8192 tokens per request, well within the 400–600 token chunk target.
- **Image chunks**: passed as base64-encoded PNG or JPEG directly. The model embeds the visual semantic content of the image natively — diagrams, charts, figures, and scanned pages all produce meaningful vectors without any OCR pre-processing.
- **Mixed chunks** (a figure caption paired with its diagram): both the text and the image are passed together as interleaved multimodal input in a single API request. The resulting embedding captures the relationship between the caption and the visual content, which is more accurate than embedding them separately.

Output dimension for all chunk types: 3072 (default, highest quality). This can be downscaled to 1536 for storage optimisation later if needed. See Section 12 for full Gemini Embedding 2 integration details.

**4b. Entity & Relationship Extraction (Llama 3 via Groq)**
- Each chunk is passed to Llama 3 with a structured prompt asking it to identify named entities (people, organisations, locations, concepts, research topics, policies, dates) and the relationships between them.
- The LLM should be prompted to respond in a structured JSON format listing entities and directed relationship triples: `(subject_entity, relationship_type, object_entity)`.
- These triples are written to Neo4j.
- See Section 7 for knowledge graph design details.

**4c. Automated Metadata Generation (Llama 3 via Groq)**
- Each chunk (and the document as a whole) is passed to Llama 3 with a prompt asking it to generate:
  - A short descriptive summary of the chunk (2–3 sentences).
  - A list of 3–7 relevant topic tags.
  - A document category classification (research paper, thesis, policy document, administrative record, departmental report).
  - A confidence score for the category classification.
- This metadata is stored alongside the embedding in ChromaDB as filterable fields.

### Stage 5: Vector Storage
- Each chunk's embedding vector, along with its metadata payload, is upserted into ChromaDB.
- The metadata payload stored per chunk must include: `source_document_id`, `original_filename`, `page_number`, `chunk_index`, `document_type`, `access_role`, `summary`, `topic_tags`, `upload_timestamp`, `has_image`, `ocr_flag`.
- Collections in ChromaDB are organised by access role (see Section 13).

---

## 6. Pipeline 2: Query & Retrieval

This pipeline is triggered when a user submits a query through either the chat interface or the search dashboard.

### Stage 1: Query Embedding
- The user's raw query string is passed to Gemini Embedding 2 to produce a query vector.
- The same model and dimensionality used at ingestion time must be used here. Consistency is critical for similarity search to work correctly.
- If the user uploads an image as part of their query (e.g., attaching a diagram and asking "find documents related to this"), the image is also embedded using Gemini Embedding 2's image input and used as part of or alongside the text embedding.

### Stage 2: Retrieval Orchestration Layer (Hybrid Search)
The retrieval layer combines two complementary search strategies and merges the results.

**Dense Retrieval (Vector Similarity)**
- Query the ChromaDB collection(s) that the user's role grants them access to.
- Retrieve the top-20 most similar chunks by cosine similarity.

**Sparse Retrieval (BM25 Keyword Search)**
- Maintain a BM25 index (using `rank_bm25` or similar) over the text content of all chunks accessible to the user.
- Run the raw query string (not the embedding) against this index.
- Retrieve the top-20 results.

**Reciprocal Rank Fusion (RRF)**
- Merge the two ranked lists using Reciprocal Rank Fusion. This method combines ranks from both lists without requiring score normalisation.
- The fused list represents the initial candidate set.

**Reranking**
- The top 20 candidates from RRF are passed through a cross-encoder reranker to reorder by true relevance to the query.
- Use a LangChain-compatible reranker. A lightweight cross-encoder model (e.g., `cross-encoder/ms-marco-MiniLM` via Hugging Face) can run locally without GPU for a project of this scale.
- The final top-5 to top-8 chunks are selected as the context window for the LLM.

### Stage 3: Knowledge Graph Augmentation
In parallel with vector retrieval, the query is processed to identify entities mentioned.

- Llama 3 is called with a short prompt to extract the key entities named in the query.
- Those entities are looked up in Neo4j.
- The graph is traversed up to 2 hops from each found entity to retrieve related entities and their relationship descriptions.
- This graph context is serialised into a short natural-language summary (e.g., "Professor Kamau is affiliated with the Department of Marine Biology and has co-authored papers on coastal erosion") and appended to the retrieval context.
- This graph augmentation step gives the LLM relational context that would not be apparent from isolated text chunks alone.

### Stage 4: Contextual Retrieval & Answer Generation (LangChain RAG Chain)
- The top reranked chunks plus the knowledge graph context summary are assembled into a structured prompt.
- The prompt instructs Llama 3 to answer the query using only the provided context, to cite every factual claim inline using a `[Source N]` notation, and to explicitly state if the context does not contain enough information to answer fully.
- The LLM is called via the Groq API with streaming enabled so the frontend receives tokens as they are generated.
- The response format must be: answer body with inline `[Source N]` citations, followed by a structured references section mapping each `[Source N]` to its source document name, page number, and chunk summary.

### Stage 5: Self-Correction
Before the answer is streamed to the user, a verification step runs.

- A second, shorter LLM call (also Llama 3 via Groq) receives the generated answer alongside the original context chunks and is asked to verify:
  - Does every cited claim appear to be supported by the cited source chunk?
  - Does the answer contradict anything in the context?
  - Does the answer make claims not supported by any chunk in the context (hallucination check)?
- If the verifier detects an issue, it returns a corrected answer or flags the problematic claims.
- The verified or corrected answer is what gets returned to the user.
- See Section 15 for full self-correction design.

---

## 7. Knowledge Graph Subsystem

The knowledge graph in Neo4j stores the structured relational knowledge extracted from all ingested documents. It augments the semantic similarity search with explicit reasoning capabilities.

### Node Types
- **Person**: researchers, authors, staff members, administrative personnel named in documents.
- **Organisation**: departments, faculties, external institutions, companies.
- **Concept**: academic topics, research areas, technical terms, policy areas.
- **Document**: each ingested source document as a node.
- **Location**: geographic or institutional locations mentioned in documents.
- **Event**: conferences, dates, milestones referenced in documents.

### Relationship Types
The LLM extraction prompt should aim to produce these relationship types among others:
- `AUTHORED_BY`, `AFFILIATED_WITH`, `REFERENCES`, `DEFINES`, `PART_OF`, `FUNDED_BY`, `LOCATED_AT`, `PUBLISHED_IN`, `RELATED_TO`, `PRECEDED_BY`

### Extraction Prompt Design
The prompt sent to Llama 3 for entity extraction should specify:
- The expected output schema (JSON with `entities` array and `relationships` array).
- That relationships must be directed triples: subject, predicate, object.
- That entities should be normalised (e.g., "Prof. Omondi" and "Professor Omondi" should resolve to the same entity).
- That confidence should be expressed by omitting uncertain extractions rather than including low-confidence ones.

### Graph Querying at Retrieval Time
- When a user query mentions an entity found in the graph, traverse outward to find connected entities and their relationship types.
- Limit traversal to 2 hops to avoid context explosion.
- Prioritise relationship paths that pass through Document nodes (i.e., the context is always grounded in a real document).
- Format the graph traversal result as a natural-language paragraph for injection into the RAG prompt.

---

## 8. Backend API Layer

The FastAPI backend exposes a RESTful API. All endpoints require a valid JWT token except the authentication endpoints. All response payloads should be JSON.

### Authentication Endpoints
- `POST /auth/login` — accepts username and password, returns a JWT access token and a refresh token.
- `POST /auth/refresh` — accepts a refresh token, returns a new access token.
- `POST /auth/logout` — invalidates the refresh token.

### Document Management Endpoints (Admin only)
- `POST /documents/upload` — accepts a multipart file upload, stores the file, enqueues the ingestion task, returns a job ID.
- `GET /documents/` — returns a paginated list of all ingested documents with their metadata.
- `GET /documents/{document_id}` — returns metadata and status for a specific document.
- `DELETE /documents/{document_id}` — removes the document from storage, ChromaDB, and Neo4j.
- `GET /documents/status/{job_id}` — returns the current ingestion status of a queued job (pending, processing, complete, failed).

### Query Endpoints (All authenticated users)
- `POST /query/chat` — accepts a query string (and optionally an image), returns a streaming server-sent event (SSE) response with the generated answer and citations.
- `POST /query/search` — accepts a query string and optional filters (document type, date range, topic tags), returns a structured list of top matching chunks with relevance scores and source metadata. This powers the search dashboard view (non-chat mode).
- `GET /query/history` — returns the query history for the authenticated user.

### Knowledge Graph Endpoints (Admin and Researcher roles)
- `GET /graph/entities` — returns a paginated list of all entities in the graph.
- `GET /graph/entity/{entity_id}` — returns a specific entity and its direct relationships.

### Admin Endpoints
- `GET /admin/users` — list all registered users.
- `POST /admin/users` — create a new user with a specified role.
- `PATCH /admin/users/{user_id}` — update a user's role or access collections.
- `GET /admin/stats` — returns system statistics (document count, query count, average retrieval time).

---

## 9. Frontend Application

The frontend is a React 18 + Tailwind CSS single-page application with two primary functional areas: the Chat Interface and the Search Dashboard.

### Global Layout
- A persistent left sidebar contains: the application logo, navigation links (Chat, Search, Document Library, Admin Panel — visible only to admin role), and user profile / logout.
- The main content area switches between the Chat and Search views based on navigation.

### Chat Interface
The chat interface is the primary interaction mode for most users.

**Behaviour:**
- A conversation thread is displayed top-down.
- User messages appear right-aligned. AI responses appear left-aligned.
- AI responses are streamed token by token as they arrive from the SSE endpoint, giving the impression of live typing.
- Inline citation markers (e.g., `[1]`, `[2]`) within the response text are rendered as clickable superscripts.
- Clicking a citation opens a side drawer showing the source chunk text, the document name, page number, and a link to view the full document in the document viewer.
- At the bottom of each AI response, a collapsible "Sources" section lists all cited documents.
- The input area supports text entry and image attachment (drag and drop or click to upload).
- A new conversation button clears the thread and starts fresh.
- Conversation history is accessible from a sidebar or dropdown.

### Search Dashboard
The search dashboard provides a more structured, filterable retrieval experience.

**Behaviour:**
- A prominent search bar at the top accepts the user's query.
- Below the search bar, filter controls allow narrowing by: document type, upload date range, and topic tags.
- Results are displayed as cards, each showing: a snippet from the most relevant chunk, the source document name, page number, topic tags, and a relevance score indicator.
- Clicking a result card opens the document in the Document Viewer panel on the right side of the screen, scrolled to the relevant page/section.
- The search is triggered on submission (not on keystroke).

### Document Viewer
- Rendered inline in a side panel on the search dashboard.
- For PDFs: use `react-pdf` to render the document page by page, with the relevant page highlighted/scrolled into view.
- For DOCX and HTML: render a plain text / formatted HTML representation.
- A download button allows the user to download the original file, subject to their access role.

### Admin Panel (Admin role only)
- **Upload tab**: drag-and-drop document upload with progress indicator. Shows current ingestion job queue with status badges (pending, processing, complete, failed).
- **Document library tab**: a table of all ingested documents with columns for filename, type, upload date, uploader, status, and actions (view, delete).
- **User management tab**: a table of all users with their roles. Ability to create new users and change roles.
- **System stats tab**: shows total documents, total queries, average retrieval time, and a simple chart of query volume over time.

### State Management (Zustand)
- `authStore`: current user, JWT token, role, expiry.
- `chatStore`: current conversation thread, loading state, streaming buffer.
- `searchStore`: current query, filters, results list, selected result.
- `adminStore`: document list, user list, job queue status.

---

## 10. Authentication & RBAC

### User Roles
Four roles map directly to the stakeholder types identified in the proposal:

| Role | Description |
|---|---|
| `student` | Can query the knowledge base. Access limited to academic documents (research papers, theses). Cannot upload or manage documents. |
| `researcher` | Can query the knowledge base and view graph entities. Access to academic documents and departmental reports. Cannot manage users or upload bulk documents, but can request document additions. |
| `staff` | Can query the knowledge base. Access to administrative documents and policy records, but not to student theses or personal research data. Cannot upload. |
| `admin` | Full access to all collections, document management, user management, and system statistics. Can create and delete users. Can assign roles. |

### JWT Token Design
- Access tokens are short-lived (15–30 minutes).
- Refresh tokens are long-lived (7 days) and stored server-side for revocation.
- The JWT payload must include: `user_id`, `username`, `role`, `allowed_collections` (list of ChromaDB collection names the user may query).
- Every protected API endpoint must validate the token and check the role against a permissions map before executing.

### Document-Level Access Control via ChromaDB Collections
Documents are ingested into different ChromaDB collections based on their type. The user's `allowed_collections` list in their JWT token determines which collections are queried at retrieval time.

| Collection | Contains | Accessible by |
|---|---|---|
| `academic` | Research papers, theses, dissertations | student, researcher, admin |
| `departmental` | Departmental reports, datasets, lecture notes | researcher, admin |
| `administrative` | Policy documents, compliance records, operational manuals | staff, admin |
| `management` | Strategic planning documents, financial reports | admin |

At query time, the retrieval layer filters ChromaDB queries to only search collections present in the user's `allowed_collections` list.

---

## 11. LangChain Orchestration Design

LangChain is used as the orchestration framework connecting all components. The following chains and components must be built:

### Ingestion Chain
A sequential chain that takes a document chunk as input and runs embedding generation and metadata extraction in parallel (using LangChain's `RunnableParallel`), then combines outputs for writing to ChromaDB.

### Retrieval Chain
A chain that takes a query string as input, runs dense retrieval and sparse retrieval in parallel, performs RRF fusion and reranking, then queries Neo4j for graph augmentation, assembles the final context, and passes it to the generation chain.

### Generation Chain
A chain that takes the assembled context and original query, formats them into the RAG prompt template, calls the Groq/Llama 3 LLM, and returns a streaming response.

### Self-Correction Chain
A chain that takes the generated answer and the original context, calls Llama 3 with the verification prompt, and returns either the original answer (if verified) or a corrected answer.

### Prompt Templates
All prompts must be defined as LangChain `ChatPromptTemplate` objects and stored in a dedicated `prompts/` directory as separate files (not hardcoded inline). This makes them easy to iterate on without changing application logic.

Key prompt templates needed:
- `rag_generation_prompt`: instructs the LLM to answer from context with citations.
- `self_correction_prompt`: instructs the LLM to verify and correct the generated answer.
- `entity_extraction_prompt`: instructs the LLM to extract structured entities and relationships from a text chunk.
- `metadata_generation_prompt`: instructs the LLM to generate summary, tags, and category for a chunk.
- `query_entity_extraction_prompt`: instructs the LLM to identify entities in a user query for graph lookup.

---

## 12. Gemini Embedding 2 Integration

Gemini Embedding 2 (`gemini-embedding-exp-03-07`) is the sole embedding model for both document ingestion and query processing. Using a single model for both is essential — mixing embedding models across ingestion and query time will break similarity search.

### What This Model Changes About the Pipeline

Previously, every piece of content — text, images, tables, scanned pages — had to be converted into plain text before it could be embedded. Images were OCR'd into text (losing all visual meaning). Diagrams became meaningless strings. Charts became nothing. The embedding model only understood words.

Gemini Embedding 2 is natively multimodal. It maps text, images, and mixed content into the same vector space, meaning a text query like "show me diagrams of the university's organisational structure" can return a match against an image of an org chart, even if that image has no text on it at all. The pipeline simplification is real and significant: the OCR-before-embedding step is completely eliminated for all image content.

### API Access
- Access via the Google AI Gemini API (not Vertex AI) for simplicity in a development/prototype context.
- The API key must be stored in environment variables and never hardcoded.
- The LangChain `GoogleGenerativeAIEmbeddings` integration class should be used as the embedding wrapper, configured with the `gemini-embedding-exp-03-07` model identifier.

### Text Embedding
- Input: a plain text string (document chunk or user query).
- Maximum input: 8192 tokens per request. Chunks at 400–600 tokens are well within this limit.
- Output dimension: 3072 (default). Store in ChromaDB.

### Image Embedding (Native — No OCR Required)
- Input: a base64-encoded PNG or JPEG image extracted from a document.
- The image is passed directly to the Gemini Embedding 2 API as an image modality input. No text conversion, no OCR, no pre-processing beyond standard image format validation.
- Output: a 3072-dimension vector stored in ChromaDB, with metadata linking it to its source document, page number, and any nearby caption text.
- The model understands the visual semantic content of the image — a diagram of a chemical reaction and a diagram of a campus map will produce meaningfully different vectors even if neither contains any text.
- The API accepts up to 6 images per request in PNG or JPEG format.

### Interleaved Multimodal Input (Caption + Image Together)
- When a document chunk contains both a figure caption (text) and the associated image, pass both together as interleaved multimodal input in a single API call.
- The resulting embedding captures the semantic relationship between what is written about the image and what the image actually shows.
- This is more accurate than embedding the caption and image separately and produces better retrieval results for visual content in research papers and reports.
- Example: a chunk containing the text "Figure 3: Phytoplankton distribution across Kilifi Creek, 2023" and the accompanying heatmap chart should be passed as interleaved input, not split into two separate embedding calls.

### Short Document Section Embedding (Native PDF Input)
- The model accepts PDF input natively, up to 6 pages per request.
- For very short standalone documents or self-contained appendices that are 6 pages or fewer, the PDF section can be passed directly without text extraction.
- This does NOT replace chunking for full documents. A 100-page thesis must still be chunked and processed page-by-page or section-by-section. The 6-page native PDF input is useful for short reference documents, policy clauses, or cover pages.

### What This Model Does NOT Eliminate
To be explicit about what the pipeline still requires:
- **Chunking is still required.** The model embeds what you give it per request. You cannot pass a 150-page thesis as one input and get a useful single embedding back. Chunk-level embeddings are essential for precise retrieval.
- **Document parsing is still required.** PyMuPDF, python-docx, and BeautifulSoup are still needed to extract and separate text, images, and structural metadata from documents.
- **OCR (Tesseract) is still required** — but only for populating the BM25 sparse search index, not for embedding. See the OCR Sub-module section in the ingestion pipeline.
- **Entity extraction is still required.** Gemini Embedding 2 produces vectors, not structured knowledge. Llama 3 still needs to extract entities and relationships for the knowledge graph.

### Matryoshka Dimension Flexibility
- The model supports output dimensions of 3072, 1536, and 768 via the `output_dimensionality` parameter.
- Use 3072 for the prototype (highest quality). If storage becomes a constraint, migrate to 1536 — this requires re-embedding all documents from scratch, so the decision is reversible but not free.
- All chunk types (text, image, mixed) must use the same output dimension consistently across the entire corpus.

### Rate Limiting
- The Google AI API has rate limits. The ingestion pipeline (which runs via Celery) must include a retry mechanism with exponential backoff for all embedding API calls.
- Batch text embedding calls where possible — pass multiple text chunks in a single batched request to reduce API call volume.
- Image embedding calls cannot be batched in the same way as text but the API accepts up to 6 images per request, so bundle image chunks from the same document together.

---

## 13. ChromaDB Vector Store Design

ChromaDB is run in persistent mode, with its data directory mounted as a Docker volume so embeddings survive container restarts.

### Collections
Four named collections are created at startup, corresponding to the four access tiers defined in the RBAC section:
- `academic`
- `departmental`
- `administrative`
- `management`

Each collection stores embeddings with the following metadata schema per document:

| Field | Type | Description |
|---|---|---|
| `source_document_id` | string | UUID of the source document |
| `original_filename` | string | Human-readable filename |
| `page_number` | integer | Page the chunk was extracted from |
| `chunk_index` | integer | Sequential index of the chunk within the document |
| `document_type` | string | e.g., `research_paper`, `thesis`, `policy_document` |
| `access_role` | string | The collection name this chunk belongs to |
| `summary` | string | LLM-generated chunk summary |
| `topic_tags` | list of strings | LLM-generated topic tags |
| `upload_timestamp` | string | ISO 8601 datetime |
| `has_image` | boolean | Whether this chunk includes an embedded image |
| `ocr_flag` | boolean | Whether this chunk's BM25 sparse index text was produced by OCR (dense embedding is unaffected) |
| `uploader_id` | string | User ID of the uploading admin |

### Query Filters
ChromaDB's `where` filter clause must be used at retrieval time to restrict results to only the collections the user has access to, and optionally to filter by `document_type`, `topic_tags`, or `upload_timestamp` range when the user applies filters in the search dashboard.

### Persistence
- The ChromaDB data directory must be a named Docker volume.
- No data should be written to the container's ephemeral layer.
- A backup script should be documented that snapshots the `chroma_data/` directory.

---

## 14. Groq + Llama 3 Integration

All LLM calls — for RAG generation, self-correction, entity extraction, and metadata generation — go through the Groq API using the `llama-3.3-70b-versatile` model.

### LangChain Integration
Use LangChain's `ChatGroq` class as the LLM wrapper. This integrates directly into LangChain chains without custom wrapper code.

### Streaming
- The RAG generation chain must use streaming mode (`streaming=True` on the `ChatGroq` instance).
- The FastAPI endpoint for `/query/chat` must use Server-Sent Events (SSE) to forward the streamed tokens to the frontend as they arrive.
- The self-correction chain does NOT stream — it runs as a blocking call after generation completes and before the final response is returned.

### Temperature Settings
Different tasks require different temperature configurations:

| Task | Temperature | Reasoning |
|---|---|---|
| RAG answer generation | 0.2 | Low creativity, high faithfulness to context |
| Self-correction verification | 0.0 | Deterministic fact-checking |
| Entity extraction | 0.0 | Deterministic structured output |
| Metadata generation (tags, summary) | 0.3 | Slight creativity for richer tag diversity |

### Token Budget Management
- The total context window for Llama 3.3 70B on Groq is 128k tokens — generous for this use case.
- The assembled RAG prompt (system instructions + context chunks + user query) should be budgeted to stay under 8000 tokens to keep latency low and cost manageable.
- If the reranker returns more context than fits the budget, trim to the highest-ranked chunks.

### Error Handling
- All Groq API calls must be wrapped in retry logic with exponential backoff.
- If the Groq API is unavailable, the system must return a clear error message to the user rather than silently failing.

---

## 15. Self-Correction Mechanism

The self-correction step is a critical quality gate that reduces hallucination before the answer reaches the user.

### How It Works
After the RAG generation chain produces an answer, a second LLM call is made with the self-correction prompt. This prompt presents the LLM with:
1. The original user query.
2. The answer that was generated.
3. The exact source chunks that were provided as context.

The LLM is asked to evaluate the answer on three criteria:
- **Groundedness**: Is every factual claim in the answer traceable to a specific source chunk?
- **Consistency**: Does the answer contradict any information in the source chunks?
- **Completeness**: If the query cannot be fully answered from the context, does the answer clearly state this?

### Output of Self-Correction
The self-correction LLM call returns one of three outcomes:
- `VERIFIED`: The answer is correct and grounded. Return it as-is.
- `CORRECTED`: The answer had issues. The corrected version is returned.
- `INSUFFICIENT_CONTEXT`: The context does not contain enough information to answer the query. A standard "I could not find sufficient information in the available documents" response is returned, along with the closest partial results.

### Transparency to the User
- The frontend should display a small indicator on each AI response showing whether it passed self-correction verification.
- This builds user trust in the system's outputs.

---

## 16. Metadata & Proactive Knowledge Discovery

Beyond answering queries reactively, the system should proactively surface insights to admin and researcher users.

### Automated Metadata Generation
Already described in the ingestion pipeline (Stage 4c). Every document and chunk gets: a summary, topic tags, and a category classification. This metadata enables the filter system on the search dashboard.

### Trend Analysis (Admin/Researcher Dashboard Widget)
- Periodically (e.g., daily), run an aggregation over all stored topic tags across recently ingested documents.
- Identify the most frequently emerging topics over the past 30 days.
- Surface these as a "Trending Topics" widget on the admin panel and researcher view.
- This is a simple frequency count over the `topic_tags` metadata field in ChromaDB — no additional LLM call needed.

### Knowledge Gap Detection
- When the self-correction layer returns `INSUFFICIENT_CONTEXT` for a query, log the query and the identified gap.
- Aggregate these gaps and surface them in the admin panel as a "Knowledge Gap Report" — topics that users are asking about that the system cannot answer from its current document corpus.
- This guides admins on what documents to prioritise for ingestion.

### Related Document Suggestions
- After returning an answer in chat mode, perform a secondary ChromaDB query using the answer embedding (not the query embedding) to find 3 additional related documents.
- Surface these as "You might also find these relevant" cards below the answer.
- This uses the same retrieval infrastructure already built — it's an additional query with a different input.

---

## 17. Testing & Evaluation Strategy

### Unit Tests
- Each pipeline stage (OCR, chunking, embedding, entity extraction, metadata generation, retrieval, reranking, generation, self-correction) must have isolated unit tests.
- Mock the external API calls (Gemini, Groq) in unit tests using response fixtures.

### Integration Tests
- Test the full ingestion pipeline end-to-end with a sample PDF, DOCX, and HTML document.
- Verify that embeddings are correctly written to ChromaDB with the expected metadata fields.
- Verify that entity triples are correctly written to Neo4j.

### Retrieval Evaluation
- Assemble a curated test set of 50 questions derived from the Pwani University document corpus, with known correct answers.
- Measure **Precision@5** (how many of the top 5 retrieved chunks are relevant) and **Recall@5** (how many relevant chunks appear in the top 5).
- Measure **Mean Reciprocal Rank (MRR)** — how highly the first correct result is ranked.
- Compare hybrid search (dense + sparse + RRF) against dense-only search to validate the hybrid approach's benefit.

### Answer Quality Evaluation
- For the same 50-question test set, evaluate generated answers on:
  - **Faithfulness**: does the answer only contain information from the source context? (Measured using the self-correction mechanism's own output as a proxy).
  - **Answer relevance**: does the answer address the question? (Manually rated by a small group of subject-matter experts from the university).
- Target: approximately 99% faithfulness (as stated in the proposal), and >90% answer relevance by expert assessment.

### Performance Benchmarking
- Measure end-to-end query response time (from query submission to first token received) for 10 diverse queries.
- Target: >50% reduction in retrieval time compared to a baseline keyword search implementation.
- Measure ingestion throughput: how many pages per minute can the pipeline process?

---

## 18. Environment Configuration

All sensitive values and environment-specific configuration must be stored in a `.env` file that is never committed to version control. An `.env.example` file with placeholder values must be committed instead.

### Required Environment Variables

```
# Google AI (Gemini Embedding 2)
GOOGLE_API_KEY=

# Groq (Llama 3)
GROQ_API_KEY=

# ChromaDB
CHROMA_PERSIST_DIRECTORY=./chroma_data
CHROMA_HOST=chroma
CHROMA_PORT=8000

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=

# JWT Authentication
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Celery / Redis
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# Document Storage
DOCUMENT_STORE_PATH=./document_store

# Application
APP_ENV=development
APP_PORT=8000
FRONTEND_URL=http://localhost:3000
```

---

## 19. Development Phases & Sprint Map

This maps to the 3-month Agile-Scrum plan from the proposal, broken into 2-week sprints.

### Phase 1 — Foundation & Data Ingestion (Month 1, Weeks 1–4)

**Sprint 1 (Weeks 1–2): Environment & Document Pre-processing**
- Set up Docker Compose with FastAPI, ChromaDB, Neo4j, Redis, Celery containers.
- Implement document parsers for PDF (PyMuPDF), DOCX (python-docx), and HTML (BeautifulSoup).
- Implement OCR sub-module with Tesseract.
- Implement semantic chunking with LangChain's text splitter.
- Write unit tests for all parsers and chunkers.

**Sprint 2 (Weeks 3–4): Embedding, Metadata, and Vector Storage**
- Integrate Gemini Embedding 2 via the Google AI API.
- Implement image embedding for extracted document images.
- Implement Llama 3 metadata generation (summary, tags, category) via Groq.
- Implement ChromaDB collection setup and chunk upsert logic.
- Implement the Celery async ingestion task queue.
- Implement the document upload API endpoint.

### Phase 2 — Core RAG & Knowledge Graph (Month 2, Weeks 5–8)

**Sprint 3 (Weeks 5–6): Retrieval Pipeline & LLM Integration**
- Implement dense vector retrieval from ChromaDB with metadata filtering.
- Implement BM25 sparse retrieval index.
- Implement Reciprocal Rank Fusion.
- Implement cross-encoder reranking.
- Integrate Llama 3 via `ChatGroq` into LangChain.
- Implement the RAG generation chain with the citation-aware prompt template.
- Implement SSE streaming on the `/query/chat` endpoint.

**Sprint 4 (Weeks 7–8): Knowledge Graph & Self-Correction**
- Implement Llama 3-based entity and relationship extraction.
- Set up Neo4j schema and implement entity upsert logic.
- Implement graph traversal query for augmenting retrieval context.
- Implement the self-correction chain and verification prompt.
- Implement the `/query/search` endpoint for the dashboard view.
- Build the JWT authentication system and RBAC middleware.

### Phase 3 — Frontend, Advanced Features & Evaluation (Month 3, Weeks 9–12)

**Sprint 5 (Weeks 9–10): Frontend Application**
- Build the React application shell with sidebar navigation and Tailwind styling.
- Build the Chat Interface with streaming response rendering, inline citations, and citation drawer.
- Build the Search Dashboard with filter controls and results cards.
- Build the Document Viewer panel with `react-pdf`.
- Integrate all frontend components with the backend API via the service layer.

**Sprint 6 (Weeks 11–12): Admin Panel, Evaluation & Documentation**
- Build the Admin Panel (upload, document library, user management, system stats).
- Implement the Trending Topics and Knowledge Gap Report widgets.
- Implement the Related Documents suggestion feature.
- Run the full retrieval and answer quality evaluation suite.
- Perform end-to-end performance benchmarking.
- Write final project documentation and deployment instructions.

---

*End of Deep Query Copilot Build Guide*
*Author: Gilbert Ashivaka — SB30/PU/43466/21, Pwani University, March 2026*
