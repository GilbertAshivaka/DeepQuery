# Deep Query — Visualization Guide
**Supplementary to the Copilot Build Guide**
*Covers the four visualization features to be integrated into the Deep Query frontend. No code is included — this document describes data flow, component responsibilities, API contracts, library configuration, and rendering behaviour.*

---

## Table of Contents

1. [Overview & Philosophy](#1-overview--philosophy)
2. [Knowledge Graph Visualization (Neovis.js)](#2-knowledge-graph-visualization-neovisjs)
3. [Document Similarity Map](#3-document-similarity-map)
4. [Query Retrieval Confidence Chart](#4-query-retrieval-confidence-chart)
5. [Knowledge Gap Heatmap](#5-knowledge-gap-heatmap)
6. [Shared Frontend Integration Notes](#6-shared-frontend-integration-notes)
7. [New Backend Endpoints Required](#7-new-backend-endpoints-required)

---

## 1. Overview & Philosophy

These four visualizations are not decorative additions — each one reveals a specific dimension of the system's knowledge and behaviour that cannot be communicated as effectively through text or tables alone.

| Visualization | What It Reveals | Primary Audience |
|---|---|---|
| Knowledge Graph | Relationships between entities across the entire document corpus | Researchers, Admins |
| Document Similarity Map | The semantic shape and clustering of the document corpus | Researchers, Admins |
| Query Retrieval Confidence | How certain the system was about each source used to answer a query | All users |
| Knowledge Gap Heatmap | Topics users are asking about that the system cannot answer | Admins |

All four visualizations are read-only for all user roles. No visualization allows editing of the underlying data. Admins and researchers see all four. Students and staff see the Query Retrieval Confidence chart only (it appears inline with every answer), since the others expose corpus-level intelligence that is scoped to privileged roles.

---

## 2. Knowledge Graph Visualization (Neovis.js)

### Purpose
This is the most architecturally significant visualization in Deep Query. It renders the Neo4j knowledge graph as an interactive, explorable network of entities and relationships extracted from all ingested institutional documents. A user can search for any entity — a researcher, a concept, a department, a topic — and see the entire web of connections the system has built around it.

### Why Neovis.js
Neovis.js is purpose-built for rendering Neo4j graph data in the browser. It connects directly to a Neo4j database via the Bolt protocol and renders using Vis.js as its underlying physics-based network engine. This eliminates the need to manually transform Neo4j query results into a graph format — Neovis handles node and edge mapping natively. It also supports Cypher query configuration directly in the frontend initialisation, meaning the graph rendered can be controlled by changing the Cypher query rather than restructuring the component.

### Where It Lives in the UI
The knowledge graph lives on a dedicated **"Knowledge Graph" page** accessible from the main sidebar, visible only to `researcher` and `admin` roles. It is not embedded inline in the chat or search views — it is a full-page exploration tool.

### Layout & Interaction Design
The page is divided into two sections. The left side (approximately 30% width) is a control panel. The right side (approximately 70% width) is the graph canvas where Neovis renders the network.

**Control Panel contains:**
- A search input where the user types an entity name (person, concept, organisation, topic) to center the graph on.
- A depth selector (1 hop, 2 hops, 3 hops) controlling how far the graph traversal extends from the focal entity. Default is 2 hops.
- Node type filter checkboxes allowing the user to show or hide specific node types: Person, Organisation, Concept, Document, Location, Event.
- A relationship type filter allowing the user to show or hide specific edge types: AUTHORED_BY, AFFILIATED_WITH, REFERENCES, DEFINES, RELATED_TO, etc.
- A "Reset" button that clears the current graph and returns to the default full-corpus overview.
- A "Focus on selected node" button that re-centers the graph around whatever node the user has clicked.

**Graph Canvas behaviour:**
- On page load, the graph renders a default overview showing the top 50 most connected entities in the corpus, regardless of type. This gives users a starting point without requiring a search.
- Nodes are colour-coded by type. Each node type has a distinct colour defined in the Neovis configuration. For example: Person nodes are one colour, Concept nodes are another, Document nodes are another, and so on. A colour legend is displayed in the control panel.
- Node size scales with the number of connections (degree centrality). Highly connected entities appear larger, making important hubs immediately visible.
- Edge labels show the relationship type (e.g., AUTHORED_BY, AFFILIATED_WITH).
- Edge thickness scales with relationship frequency — if two entities are connected by multiple documents mentioning the same relationship, the edge is thicker.
- Hovering over a node shows a tooltip with the entity name, type, and a count of its connections.
- Clicking a node opens a detail panel on the right side of the control panel showing: the entity name, type, a list of its direct relationships, and a list of source documents that mentioned this entity. Each source document in the list is a link that opens the document in the document viewer.
- Clicking an edge shows a tooltip identifying which source documents contain the relationship.
- The graph is physics-simulated — nodes repel each other and edges act as springs. The user can drag nodes to rearrange them. The simulation can be paused via a button in the control panel.
- Double-clicking a node triggers a graph expansion — the graph re-queries Neo4j with that node as the new focal point at the configured hop depth, effectively navigating the graph by clicking through it.

### Data Flow

**Step 1 — Default load:**
The frontend calls `GET /graph/overview` on page load. The backend runs a Neo4j Cypher query returning the top 50 most-connected entities and their direct relationships, serialised as a node-edge list. Neovis renders this.

**Step 2 — Entity search:**
When the user types in the search input and submits, the frontend calls `GET /graph/search?entity={name}&depth={n}&node_types={list}&relationship_types={list}`. The backend runs a parameterised Cypher query traversing outward from the matched entity to the requested depth, filtered by the specified node and relationship types. The result is returned as a node-edge list and Neovis re-renders.

**Step 3 — Node click detail:**
When the user clicks a node, the frontend calls `GET /graph/entity/{entity_id}` to fetch the entity's full detail (name, type, all relationships, source documents). This populates the detail panel without re-rendering the full graph.

**Step 4 — Double-click expand:**
Treated the same as an entity search using the double-clicked node's name and ID as the focal entity.

### Neovis.js Configuration Details
Neovis is initialised with a configuration object that specifies:
- The Neo4j connection details (bolt URI, username, password — passed from environment variables through the backend, never exposed directly to the frontend client).
- The Cypher query to run on initialisation.
- The node label to use for display text on each node type.
- The property to use for node sizing (degree centrality, pre-computed and stored as a property on each node in Neo4j).
- The property to use for node colouring (entity type).
- The relationship property to use for edge thickness (frequency count).

**Important:** Neovis connects to Neo4j via Bolt. For security, the Neo4j Bolt port must not be directly exposed to the browser. The recommended approach is to route Neovis connections through a lightweight WebSocket proxy in the backend, or to use Neovis in server-side rendering mode where the backend executes the Cypher query and returns the result as a standard JSON graph structure for Neovis to render. This keeps Neo4j credentials server-side at all times.

### Performance Considerations
- Limit all graph queries to a maximum of 200 nodes and 500 edges in a single render. Beyond this, the physics simulation becomes slow and the graph becomes unreadable.
- For the default overview, pre-compute the top N most-connected entities as a cached result (refreshed nightly) rather than running a full degree-centrality query on every page load.
- The hop depth selector should max out at 3. Allowing deeper traversal on a large graph will produce queries that time out.

---

## 3. Document Similarity Map

### Purpose
This visualization reduces the entire document corpus — potentially thousands of documents — down to a 2D scatter plot where proximity equals semantic similarity. Documents that are about similar topics cluster together. Documents that are outliers appear isolated. The user can explore the shape of the entire knowledge base at a glance, discover clusters they did not know existed, and find individual documents by clicking on them.

### How It Works Technically
Each document in ChromaDB has a full 3072-dimension embedding vector representing its semantic content. These vectors cannot be plotted directly in 2D. A dimensionality reduction algorithm is applied to project each document's embedding down to 2 dimensions while preserving relative distances. Documents that were close in 3072-dimensional space remain close in 2D space.

**Dimensionality reduction algorithm: UMAP**
UMAP (Uniform Manifold Approximation and Projection) is preferred over t-SNE for this use case because it is significantly faster on large datasets, preserves both local and global structure better, and produces more stable results across runs. UMAP runs on the backend as a scheduled job (not on every page load) and its 2D output coordinates are stored in the document metadata table. The frontend simply fetches and renders these pre-computed coordinates.

**Rendering library: Recharts or Plotly (via react-plotly.js)**
Plotly is the stronger choice here because it natively supports interactive scatter plots with zoom, pan, hover tooltips, and click events at the scale of thousands of data points without performance degradation. Recharts handles smaller datasets well but may struggle with thousands of simultaneous points. Use Plotly for this visualization.

### Where It Lives in the UI
The document similarity map lives on a dedicated **"Corpus Explorer"** page accessible from the sidebar, visible to `researcher` and `admin` roles only. It is a full-page visualization.

### Layout & Interaction Design
The page is split into a control panel (left, ~25% width) and the map canvas (right, ~75% width).

**Control Panel contains:**
- A colour-by selector allowing the user to colour data points by: document type, access collection, upload date range, or topic tag. Changing this re-colours the points without re-fetching data.
- A filter by document type multi-select.
- A filter by date range picker.
- A search input that, when a document name is typed, highlights that document's point on the map and zooms to it.
- A legend showing the colour mapping for the currently selected colour-by dimension.

**Map Canvas behaviour:**
- Each point represents one document. Point colour is determined by the currently selected colour-by dimension.
- Hovering over a point shows a tooltip with: document name, document type, upload date, and the top 3 topic tags.
- Clicking a point opens a side drawer on the right showing the document's full metadata and a button to open it in the document viewer.
- Cluster regions that are densely packed can be zoomed into using standard Plotly zoom controls.
- A "Zoom to fit" button resets the view to show all points.
- Points belonging to the same ChromaDB collection (access tier) can be shown or hidden using the filter controls.

### Data Flow

**UMAP computation (backend, scheduled):**
A Celery beat (scheduled task) runs the UMAP computation nightly or whenever 10+ new documents have been ingested since the last run. The process fetches all document-level embeddings from ChromaDB, runs UMAP to produce (x, y) coordinates for each document, and stores these coordinates back into the document metadata table alongside the document ID.

**Frontend fetch:**
The Corpus Explorer page calls `GET /documents/similarity-map` which returns the pre-computed 2D coordinates for all documents the user's role has access to, along with the metadata needed for tooltips (document name, type, tags, collection). The frontend renders this with Plotly.

**On new document ingestion:**
A flag is set indicating the similarity map is stale. A banner on the Corpus Explorer page informs the user "The map is being updated — showing data as of [last computed timestamp]."

### Performance Considerations
- UMAP is run on the backend, never in the browser. The browser only receives 2D coordinates.
- For a corpus of up to 10,000 documents, UMAP runs in under a minute on CPU. For larger corpora, consider running it on a subset (e.g., one embedding per document, not per chunk).
- Use document-level embeddings (average of all chunk embeddings for a document) not chunk-level embeddings for this map. Plotting every chunk would produce tens of thousands of points and lose the document-level clarity.

---

## 4. Query Retrieval Confidence Chart

### Purpose
Every time a user receives an answer in the chat interface or search dashboard, they should be able to see exactly which source chunks the system retrieved, how relevant each one was to their query, and whether the self-correction layer verified or corrected the answer. This chart makes the RAG pipeline transparent and builds user trust by showing its reasoning.

### What Is Being Visualized
After retrieval and reranking, each source chunk has a relevance score (the cosine similarity score from ChromaDB, adjusted by the reranker). These scores, alongside the source metadata, are visualized as a horizontal bar chart where each bar represents one retrieved source chunk.

### Where It Lives in the UI
This visualization appears **inline within every chat response and every search result**, directly below the answer text and above the citations list. It is visible to all authenticated user roles. It is compact by default and expandable.

### Layout & Interaction Design

**Default (collapsed) state:**
A small bar chart showing up to 5 bars, each representing one of the top retrieved source chunks. The chart is approximately 200px tall. A label "Sources used to generate this answer" sits above it. A "Show all sources" toggle expands it.

**Expanded state:**
All retrieved chunks (up to 8, as per the retrieval pipeline design) are shown. Each bar displays:
- The bar length representing the relevance score (0.0 to 1.0 scale, displayed as a percentage).
- A label on the left showing the source document name and page number (e.g., "Coastal Erosion Study 2022 — p.14").
- The relevance score value displayed as a number at the end of the bar (e.g., "0.87").
- A colour indicator: bars above 0.75 are rendered in a strong colour (high confidence), bars between 0.50 and 0.75 in a medium colour (moderate confidence), bars below 0.50 in a muted colour (low confidence).

**Self-correction status badge:**
Directly above the chart, a small badge displays one of three states:
- ✓ Verified — the self-correction layer confirmed the answer is grounded in the sources shown.
- ↻ Corrected — the self-correction layer modified the answer. A tooltip on this badge explains what was changed.
- ⚠ Insufficient Context — the system could not find enough relevant sources. The chart still shows what was retrieved but all bars are muted.

**Click interaction:**
Clicking any bar in the chart scrolls the citations section below the answer to that specific citation, and highlights it. This connects the visual confidence representation to the actual source text.

**Rendering library: Recharts**
The query retrieval confidence chart uses Recharts (not Plotly) because it is a simple, small inline chart that does not need Plotly's heavy interactive features. Recharts renders cleanly within the chat message component and is already part of the frontend dependency tree from other dashboard uses.

### Data Flow

**At query time:**
The backend's `/query/chat` and `/query/search` endpoints already retrieve chunks with relevance scores as part of the pipeline. These scores are currently only used internally. They must now be included in the API response payload alongside the answer text and citations.

The response payload must include a `sources` array where each item contains: `chunk_id`, `document_name`, `page_number`, `relevance_score`, `chunk_summary`, and `self_correction_status`.

**Frontend rendering:**
The chat component receives the `sources` array and passes it to the RetrievalConfidenceChart component, which renders synchronously after the streaming answer completes. The chart does not appear while the answer is still streaming — it appears only once the full response (including self-correction) has been received.

### Backend Changes Required
The `/query/chat` endpoint response schema must be extended to include the `sources` array with relevance scores. The self-correction result (VERIFIED, CORRECTED, or INSUFFICIENT_CONTEXT) must also be included in the response. See Section 7 for the full updated endpoint contract.

---

## 5. Knowledge Gap Heatmap

### Purpose
Every time the self-correction layer returns `INSUFFICIENT_CONTEXT`, the query is logged as a knowledge gap. Over time, these gaps accumulate into a picture of what the institution's users need to know but the system cannot answer. The knowledge gap heatmap visualizes this accumulation so admins can make informed decisions about which documents to prioritise for ingestion.

### What Is Being Visualized
The logged gap queries are processed by extracting their topic tags (using the same Llama 3 metadata generation pipeline applied to answers, or a simpler keyword frequency approach). The frequency of each topic across all gap queries over a selected time window is computed and rendered as a heatmap or weighted word cloud — larger, darker terms indicate more frequent unanswered demand.

### Where It Lives in the UI
The knowledge gap heatmap lives on the **Admin Panel** under a "Knowledge Gaps" tab. It is visible to `admin` role only.

### Layout & Interaction Design
The page has a control section at the top and the heatmap below it.

**Control section contains:**
- A time window selector: Last 7 days / Last 30 days / Last 90 days / All time.
- A minimum frequency threshold slider — filters out topics that have only appeared once or twice (noise), allowing the admin to focus on persistent gaps. Default threshold: 3 occurrences.
- An "Export as CSV" button that downloads the full gap log as a spreadsheet with columns: query text, date, extracted topics, frequency count.

**Heatmap display:**
The primary display is a **topic frequency heatmap** — a grid where rows represent topic categories and columns represent time periods (weeks or months depending on the selected time window). Each cell is colour-coded by frequency: light colour for low frequency, dark saturated colour for high frequency. This shows not just what is missing but when the gaps are growing.

Below the heatmap, a **top 10 gaps list** shows the ten most frequently unanswered topics as a simple ranked list with occurrence counts. Each item in the list has a "Mark as resolved" button that an admin can click after ingesting relevant documents, which suppresses that topic from the heatmap going forward (it is archived, not deleted).

**Click interaction:**
Clicking any cell in the heatmap or any item in the top 10 list opens a side drawer showing all the individual queries that contributed to that gap, along with their dates and the user role that submitted them (but not the user identity — privacy is preserved). This gives admins the actual question text so they know precisely what kind of document would fill the gap.

**Rendering library: Recharts or Plotly**
Use Plotly for the heatmap grid since Recharts does not have a native heatmap component and implementing one from scratch adds unnecessary complexity. Plotly's heatmap trace type handles this directly. The top 10 list below the heatmap is plain HTML, not a chart component.

### Data Flow

**Gap logging (backend):**
When the self-correction layer returns `INSUFFICIENT_CONTEXT`, the backend writes a record to a `knowledge_gaps` table with: the query text, timestamp, user role, extracted topic tags (produced by a short Llama 3 call or keyword extraction), and a `resolved` boolean (default false).

**Aggregation (backend, scheduled):**
A Celery beat task runs daily to aggregate the gap log into a frequency matrix — topics by time period — and cache the result. This avoids running the aggregation query on every admin panel load.

**Frontend fetch:**
The Knowledge Gaps tab calls `GET /admin/knowledge-gaps?window={days}&min_frequency={n}` which returns the cached frequency matrix and the top 10 list. The frontend renders these with Plotly and HTML respectively.

**Mark as resolved:**
The "Mark as resolved" button calls `PATCH /admin/knowledge-gaps/{topic}/resolve` which sets the `resolved` flag to true for all gap records with that topic. These records are excluded from future aggregation queries. They are not deleted — the historical record is preserved for reporting.

### Important Design Note on Privacy
The knowledge gap log stores the query text submitted by users. This is sensitive — a student's research query could reveal what dissertation they are working on, or an admin's query could reveal internal concerns. The heatmap and the gap detail drawer must show topic-level aggregations and query text only. They must never display which individual user submitted a query. User identity must be stripped from all admin-facing gap reports. Only the user's role (student, researcher, staff) is permissible to show.

---

## 6. Shared Frontend Integration Notes

### New Page Routes
Three new routes must be added to the React application:
- `/graph` — Knowledge Graph Visualization (researcher and admin roles only)
- `/corpus` — Document Similarity Map (researcher and admin roles only)
- `/admin/gaps` — Knowledge Gap Heatmap (admin role only)

The Query Retrieval Confidence chart does not need a new route — it is a component rendered inline within the existing chat and search pages.

### Sidebar Navigation Updates
The sidebar must be updated to include links to the Knowledge Graph and Corpus Explorer pages for researcher and admin users. The Knowledge Gaps link lives inside the Admin Panel section of the sidebar.

### Role-Based Route Guards
All three new pages must be wrapped in a route guard component that checks the user's role from the auth store (Zustand) before rendering. Unauthorized users attempting to access these routes directly via URL must be redirected to the home page with an "Access denied" message.

### New Frontend Dependencies
The following libraries must be added to the frontend:
- `neovis.js` — for the knowledge graph visualization.
- `react-plotly.js` and `plotly.js` — for the document similarity map and knowledge gap heatmap.
- `umap-js` is NOT needed on the frontend — UMAP runs on the backend only.

Recharts is already included in the frontend dependencies from the admin stats dashboard and does not need to be added again.

### Loading States
All four visualizations involve non-trivial data fetching or computation. Each must display a meaningful loading state:
- Knowledge Graph: a spinner with the text "Loading graph..." while the initial Cypher query runs.
- Document Similarity Map: a skeleton placeholder of the scatter plot area while coordinates are fetched.
- Query Retrieval Confidence: the chart appears after the streaming answer completes, not during streaming. No special loading state needed beyond the natural stream completion.
- Knowledge Gap Heatmap: a skeleton placeholder of the heatmap grid while the aggregation data is fetched.

### Stale Data Banners
The Document Similarity Map and the Knowledge Gap Heatmap both depend on data that is computed periodically rather than in real time. Both pages must display a banner showing the timestamp of the last computation and, if the data is more than 24 hours old, a warning: "This view may not reflect recently ingested documents."

---

## 7. New Backend Endpoints Required

The following new or modified endpoints are needed to support the four visualizations. All require a valid JWT token.

### Knowledge Graph Endpoints
- `GET /graph/overview` — returns the top 50 most-connected entities and their direct relationships as a node-edge list. Accessible by `researcher` and `admin` roles.
- `GET /graph/search` — accepts query parameters `entity` (string), `depth` (integer 1–3), `node_types` (comma-separated list), `relationship_types` (comma-separated list). Returns a filtered subgraph as a node-edge list. Accessible by `researcher` and `admin`.
- `GET /graph/entity/{entity_id}` — returns full detail for a single entity: name, type, all relationships, and list of source documents. Accessible by `researcher` and `admin`.

### Document Similarity Map Endpoints
- `GET /documents/similarity-map` — returns pre-computed UMAP (x, y) coordinates for all documents accessible to the requesting user's role, along with document metadata (name, type, collection, tags, upload date). Returns a 404-style response with a descriptive message if UMAP coordinates have not yet been computed.

### Query Retrieval Confidence
- No new endpoint required. The existing `/query/chat` and `/query/search` endpoints must be **modified** to include a `sources` array in their response payload. Each source item must contain: `chunk_id`, `document_name`, `page_number`, `relevance_score` (float, 0.0–1.0), `chunk_summary`, and `self_correction_status` (one of VERIFIED, CORRECTED, INSUFFICIENT_CONTEXT).

### Knowledge Gap Endpoints
- `GET /admin/knowledge-gaps` — accepts query parameters `window` (integer, number of days) and `min_frequency` (integer). Returns the aggregated frequency matrix (topics × time periods) and the top 10 gap list. Admin role only.
- `GET /admin/knowledge-gaps/detail/{topic}` — returns the list of individual queries that contributed to a specific topic gap, with timestamp and user role (not user identity). Admin role only.
- `PATCH /admin/knowledge-gaps/{topic}/resolve` — marks all gap records for a topic as resolved. Admin role only.

### UMAP Computation Endpoint (Internal / Admin)
- `POST /admin/recompute-similarity-map` — manually triggers the UMAP computation Celery task. Admin role only. Returns a job ID that the frontend can poll for completion status. This complements the automatic nightly scheduled run and allows admins to force a refresh after a large batch of documents has been ingested.

---

*End of Deep Query Visualization Guide*
*Supplement to: Deep Query Copilot Build Guide*
*Author: Gilbert 
