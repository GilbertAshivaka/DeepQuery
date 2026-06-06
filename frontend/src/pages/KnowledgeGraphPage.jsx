import { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search, RefreshCw, Pause, Play, ZoomIn, ZoomOut,
  Maximize2, ChevronDown, ChevronRight, X, ExternalLink,
  Loader2, AlertCircle, Network as NetworkIcon,
} from 'lucide-react';
import { graphService } from '../services/graphService';

// ── Static configuration ─────────────────────────────────────

const NODE_TYPES = ['Person', 'Organisation', 'Concept', 'Document', 'Location', 'Event'];

const REL_TYPES = [
  'AUTHORED_BY', 'AFFILIATED_WITH', 'REFERENCES',
  'DEFINES', 'RELATED_TO', 'MENTIONED_IN',
];

const NODE_PALETTE = {
  Person:       { bg: '#ddd6fe', border: '#7c3aed', hl: '#c4b5fd' },
  Organisation: { bg: '#bfdbfe', border: '#2563eb', hl: '#93c5fd' },
  Concept:      { bg: '#bbf7d0', border: '#059669', hl: '#86efac' },
  Document:     { bg: '#fed7aa', border: '#d97706', hl: '#fdba74' },
  Location:     { bg: '#fecaca', border: '#dc2626', hl: '#fca5a5' },
  Event:        { bg: '#e9d5ff', border: '#9333ea', hl: '#d8b4fe' },
};

function buildVisOptions(physicsEnabled) {
  return {
    autoResize: true,
    height: '100%',
    width: '100%',
    nodes: {
      shape: 'dot',
      font: {
        size: 13,
        color: '#3d1a00',
        face: 'Inter, system-ui, sans-serif',
        strokeWidth: 2,
        strokeColor: '#fffbf5',
      },
      borderWidth: 2,
      borderWidthSelected: 3,
      scaling: {
        min: 8,
        max: 36,
        label: { enabled: true, min: 11, max: 15, drawThreshold: 5 },
      },
      shadow: false,
    },
    edges: {
      width: 1.5,
      selectionWidth: 2.5,
      arrows: { to: { enabled: true, scaleFactor: 0.55 } },
      font: {
        size: 10,
        color: '#78716c',
        align: 'middle',
        strokeWidth: 2,
        strokeColor: '#fdf8f0',
      },
      color: {
        color: '#d1c7bd',
        highlight: '#c4a882',
        hover: '#a8896c',
        inherit: false,
      },
      smooth: { enabled: true, type: 'dynamic' },
    },
    physics: {
      enabled: physicsEnabled,
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: -80,
        centralGravity: 0.006,
        springLength: 130,
        springConstant: 0.08,
        damping: 0.6,
        avoidOverlap: 0.5,
      },
      stabilization: {
        enabled: true,
        iterations: 300,
        updateInterval: 25,
        fit: true,
      },
      minVelocity: 0.5,
    },
    interaction: {
      hover: true,
      tooltipDelay: 200,
      hideEdgesOnDrag: true,
      hideNodesOnDrag: false,
      navigationButtons: false,
      keyboard: false,
      zoomView: true,
      dragView: true,
    },
    groups: Object.fromEntries(
      Object.entries(NODE_PALETTE).map(([type, c]) => [
        type,
        {
          color: {
            background: c.bg,
            border: c.border,
            highlight: { background: c.hl, border: c.border },
            hover: { background: c.hl, border: c.border },
          },
        },
      ])
    ),
  };
}

// ── Main page component ──────────────────────────────────────

export default function KnowledgeGraphPage() {
  const navigate = useNavigate();

  // Graph display state
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [focalEntity, setFocalEntity] = useState(null);

  // Control state
  const [searchQuery, setSearchQuery] = useState('');
  const [depth, setDepth] = useState(2);
  const [activeNodeTypes, setActiveNodeTypes] = useState(new Set(NODE_TYPES));
  const [activeRelTypes, setActiveRelTypes] = useState(new Set(REL_TYPES));
  const [physicsRunning, setPhysicsRunning] = useState(true);
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Entity detail panel
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [entityDetail, setEntityDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Vis refs
  const containerRef = useRef(null);
  const networkRef = useRef(null);

  // Keep callbacks stable across re-renders without recreating the network
  const onNodeClickRef = useRef(null);
  const onNodeDblClickRef = useRef(null);

  // ── Vis-network lifecycle ────────────────────────────────────

  const buildNetwork = useCallback(async (data) => {
    if (!containerRef.current || !data) return;

    const { Network, DataSet } = await import('vis-network/standalone');

    // Destroy previous instance cleanly
    if (networkRef.current) {
      networkRef.current.destroy();
      networkRef.current = null;
    }

    const nodes = new DataSet(data.nodes);
    const edges = new DataSet(data.edges);

    const network = new Network(
      containerRef.current,
      { nodes, edges },
      buildVisOptions(physicsRunning),
    );

    // Fit after stabilisation
    network.on('stabilizationIterationsDone', () => {
      network.setOptions({ physics: { stabilization: { enabled: false } } });
      network.fit({ animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
    });

    // Single click → entity detail
    network.on('click', (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        setSelectedNodeId(nodeId);
        onNodeClickRef.current?.(nodeId);
      } else if (params.edges.length === 0) {
        setSelectedNodeId(null);
        setEntityDetail(null);
      }
    });

    // Double click → re-centre graph on that node
    network.on('doubleClick', (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        onNodeDblClickRef.current?.(nodeId);
      }
    });

    networkRef.current = network;
  }, [physicsRunning]);

  // ── Data fetchers ────────────────────────────────────────────

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    setFocalEntity(null);
    setSelectedNodeId(null);
    setEntityDetail(null);
    setSearchQuery('');
    try {
      const { data } = await graphService.getOverview();
      setGraphData(data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load knowledge graph.');
    } finally {
      setLoading(false);
    }
  }, []);

  const runSearch = useCallback(
    async (query) => {
      const q = (query ?? searchQuery).trim();
      if (!q) return;
      setLoading(true);
      setError(null);
      setSelectedNodeId(null);
      setEntityDetail(null);
      try {
        const nodeFilter = activeNodeTypes.size < NODE_TYPES.length ? [...activeNodeTypes] : [];
        const relFilter = activeRelTypes.size < REL_TYPES.length ? [...activeRelTypes] : [];
        const { data } = await graphService.searchGraph(q, depth, nodeFilter, relFilter);
        setGraphData(data);
        setFocalEntity(data.focal);
      } catch (err) {
        if (err.response?.status === 404) {
          setError(`No entity found matching "${q}".`);
        } else {
          setError(err.response?.data?.detail || 'Graph search failed.');
        }
      } finally {
        setLoading(false);
      }
    },
    [searchQuery, depth, activeNodeTypes, activeRelTypes],
  );

  const loadEntityDetail = useCallback(async (nodeId) => {
    setDetailLoading(true);
    setEntityDetail(null);
    try {
      const { data } = await graphService.getEntityDetail(nodeId);
      setEntityDetail(data);
    } catch {
      // Non-fatal — graph stays usable
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // Wire stable callbacks into refs so event handlers always see latest
  useEffect(() => {
    onNodeClickRef.current = loadEntityDetail;
  }, [loadEntityDetail]);

  useEffect(() => {
    onNodeDblClickRef.current = (nodeId) => {
      setSearchQuery(nodeId);
      runSearch(nodeId);
    };
  }, [runSearch]);

  // ── Effects ──────────────────────────────────────────────────

  useEffect(() => { loadOverview(); }, [loadOverview]);

  useEffect(() => {
    if (graphData) buildNetwork(graphData);
    return () => {
      networkRef.current?.destroy();
      networkRef.current = null;
    };
  }, [graphData]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Toolbar actions ──────────────────────────────────────────

  const togglePhysics = () => {
    const next = !physicsRunning;
    setPhysicsRunning(next);
    networkRef.current?.setOptions({ physics: { enabled: next } });
  };

  const fitGraph = () =>
    networkRef.current?.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });

  const zoomIn = () => {
    if (!networkRef.current) return;
    networkRef.current.moveTo({
      scale: networkRef.current.getScale() * 1.35,
      animation: { duration: 200 },
    });
  };

  const zoomOut = () => {
    if (!networkRef.current) return;
    networkRef.current.moveTo({
      scale: networkRef.current.getScale() / 1.35,
      animation: { duration: 200 },
    });
  };

  const focusSelected = () => {
    if (!selectedNodeId || !networkRef.current) return;
    networkRef.current.focus(selectedNodeId, {
      scale: 1.4,
      animation: { duration: 500, easingFunction: 'easeInOutQuad' },
    });
  };

  const toggleNodeType = (type) =>
    setActiveNodeTypes((prev) => {
      const next = new Set(prev);
      next.has(type) ? next.delete(type) : next.add(type);
      return next;
    });

  const toggleRelType = (type) =>
    setActiveRelTypes((prev) => {
      const next = new Set(prev);
      next.has(type) ? next.delete(type) : next.add(type);
      return next;
    });

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    runSearch();
  };

  // ── Render ───────────────────────────────────────────────────

  const nodeCount = graphData?.nodes?.length ?? 0;
  const edgeCount = graphData?.edges?.length ?? 0;

  return (
    <div className="flex h-full overflow-hidden bg-cream-50">

      {/* ══════ Control panel (left) ══════ */}
      <aside className="w-80 flex-shrink-0 flex flex-col bg-white/70 border-r border-cream-200 overflow-y-auto">

        {/* Header */}
        <div className="px-4 pt-5 pb-3 border-b border-cream-100 flex-shrink-0">
          <div className="flex items-center gap-2 mb-0.5">
            <NetworkIcon size={16} className="text-amber-700" />
            <h1 className="text-sm font-bold text-ink-900">Knowledge Graph</h1>
          </div>
          <p className="text-xs text-ink-500">
            {nodeCount > 0
              ? `${nodeCount} entities · ${edgeCount} relationships`
              : 'Explore institutional knowledge connections'}
          </p>
          {focalEntity && (
            <p className="mt-1 text-xs text-amber-700 font-medium truncate">
              Centred on: {focalEntity}
            </p>
          )}
        </div>

        {/* Search & depth */}
        <div className="px-4 py-4 border-b border-cream-100 flex-shrink-0 space-y-3">
          <form onSubmit={handleSearchSubmit} className="flex gap-2">
            <div className="relative flex-1">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search entity name..."
                className="w-full pl-8 pr-3 py-2 text-sm rounded-lg border border-cream-200
                  bg-cream-50 focus:outline-none focus:ring-2 focus:ring-amber-500/30
                  focus:border-amber-400 placeholder-ink-400 transition-colors"
              />
            </div>
            <button
              type="submit"
              disabled={!searchQuery.trim() || loading}
              className="px-3 py-2 rounded-lg bg-amber-800 hover:bg-amber-700 disabled:opacity-50
                disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
            >
              Go
            </button>
          </form>

          <div className="flex items-center gap-3">
            <span className="text-xs text-ink-600 flex-shrink-0">Hop depth</span>
            <div className="flex gap-1">
              {[1, 2, 3].map((d) => (
                <button
                  key={d}
                  onClick={() => setDepth(d)}
                  className={`w-8 h-7 text-xs rounded-md font-semibold transition-colors
                    ${depth === d
                      ? 'bg-amber-800 text-white shadow-sm'
                      : 'bg-cream-100 text-ink-600 hover:bg-cream-200'
                    }`}
                >
                  {d}
                </button>
              ))}
            </div>
            <span className="text-xs text-ink-400">hops from focal</span>
          </div>
        </div>

        {/* Filters (collapsible) */}
        <div className="border-b border-cream-100 flex-shrink-0">
          <button
            onClick={() => setFiltersOpen(!filtersOpen)}
            className="flex items-center justify-between w-full px-4 py-3 text-xs font-semibold
              text-ink-700 hover:bg-cream-50 transition-colors"
          >
            <span>Filters</span>
            {filtersOpen
              ? <ChevronDown size={13} />
              : <ChevronRight size={13} />
            }
          </button>

          {filtersOpen && (
            <div className="px-4 pb-4 space-y-4">
              {/* Node type toggles */}
              <div>
                <p className="text-[10px] font-semibold text-ink-400 uppercase tracking-wider mb-2">
                  Node types
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {NODE_TYPES.map((type) => {
                    const c = NODE_PALETTE[type];
                    const active = activeNodeTypes.has(type);
                    return (
                      <button
                        key={type}
                        onClick={() => toggleNodeType(type)}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs
                          font-medium border transition-all
                          ${active ? 'opacity-100' : 'opacity-35'}`}
                        style={{
                          backgroundColor: c.bg,
                          borderColor: c.border,
                          color: c.border,
                        }}
                      >
                        <span
                          className="w-2 h-2 rounded-full flex-shrink-0"
                          style={{ backgroundColor: c.border }}
                        />
                        {type}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Relationship type toggles */}
              <div>
                <p className="text-[10px] font-semibold text-ink-400 uppercase tracking-wider mb-2">
                  Relationship types
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {REL_TYPES.map((type) => {
                    const active = activeRelTypes.has(type);
                    return (
                      <button
                        key={type}
                        onClick={() => toggleRelType(type)}
                        className={`px-2 py-1 rounded-full text-[10px] font-medium border
                          transition-all
                          ${active
                            ? 'bg-amber-50 border-amber-300 text-amber-800'
                            : 'bg-cream-50 border-cream-200 text-ink-400'
                          }`}
                      >
                        {type.replace(/_/g, ' ')}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Quick actions */}
        <div className="px-4 py-3 border-b border-cream-100 flex-shrink-0 flex flex-wrap gap-2">
          <button
            onClick={loadOverview}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
              bg-cream-100 hover:bg-cream-200 text-ink-700 disabled:opacity-50 transition-colors"
          >
            <RefreshCw size={12} />
            Reset to overview
          </button>
          {selectedNodeId && (
            <button
              onClick={focusSelected}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200 transition-colors"
            >
              <ZoomIn size={12} />
              Focus selected
            </button>
          )}
        </div>

        {/* Colour legend */}
        <div className="px-4 py-3 border-b border-cream-100 flex-shrink-0">
          <p className="text-[10px] font-semibold text-ink-400 uppercase tracking-wider mb-2">
            Node legend
          </p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            {NODE_TYPES.map((type) => (
              <div key={type} className="flex items-center gap-1.5">
                <span
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: NODE_PALETTE[type].border }}
                />
                <span className="text-xs text-ink-600">{type}</span>
              </div>
            ))}
          </div>
          {focalEntity && (
            <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-cream-100">
              <span
                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: '#ea580c' }}
              />
              <span className="text-xs text-ink-600">Focal entity (highlighted)</span>
            </div>
          )}
        </div>

        {/* Entity detail panel — shown when a node is clicked */}
        {(selectedNodeId || detailLoading) && (
          <div className="flex-1 overflow-y-auto px-4 py-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-semibold text-ink-400 uppercase tracking-wider">
                Entity Detail
              </p>
              <button
                onClick={() => { setSelectedNodeId(null); setEntityDetail(null); }}
                className="p-1 rounded-md text-ink-400 hover:text-ink-600 hover:bg-cream-100 transition-colors"
                title="Close"
              >
                <X size={13} />
              </button>
            </div>

            {detailLoading ? (
              <div className="flex items-center gap-2 text-ink-500 text-xs py-2">
                <Loader2 size={13} className="animate-spin text-amber-700" />
                Loading entity details…
              </div>
            ) : entityDetail ? (
              <EntityDetailPanel detail={entityDetail} navigate={navigate} />
            ) : null}
          </div>
        )}
      </aside>

      {/* ══════ Graph canvas (right) ══════ */}
      <div className="flex-1 relative overflow-hidden bg-[#fdfaf5]">

        {/* Loading overlay */}
        {loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center
            bg-cream-50/80 backdrop-blur-sm z-20">
            <Loader2 size={30} className="animate-spin text-amber-700 mb-3" />
            <p className="text-sm font-medium text-ink-700">Loading graph…</p>
            <p className="text-xs text-ink-400 mt-1">Querying Neo4j knowledge graph</p>
          </div>
        )}

        {/* Error overlay */}
        {error && !loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-20">
            <AlertCircle size={30} className="text-red-400 mb-3" />
            <p className="text-sm font-semibold text-ink-800 mb-1">Graph unavailable</p>
            <p className="text-xs text-ink-500 mb-4 text-center max-w-xs">{error}</p>
            <button
              onClick={loadOverview}
              className="px-4 py-2 rounded-lg bg-amber-800 text-white text-sm
                font-medium hover:bg-amber-700 transition-colors"
            >
              Reload overview
            </button>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && graphData?.nodes?.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-10">
            <NetworkIcon size={40} className="text-cream-300 mb-3" />
            <p className="text-sm font-medium text-ink-600">No entities in the knowledge graph yet.</p>
            <p className="text-xs text-ink-400 mt-1">Ingest documents to populate the graph.</p>
          </div>
        )}

        {/* Vis-network mount target */}
        <div ref={containerRef} className="w-full h-full" />

        {/* Canvas toolbar (bottom-right) */}
        <div className="absolute bottom-5 right-5 flex flex-col gap-2 z-10">
          <ToolbarButton onClick={togglePhysics} title={physicsRunning ? 'Pause physics' : 'Resume physics'}>
            {physicsRunning ? <Pause size={14} /> : <Play size={14} />}
          </ToolbarButton>
          <ToolbarButton onClick={fitGraph} title="Fit to screen">
            <Maximize2 size={14} />
          </ToolbarButton>
          <ToolbarButton onClick={zoomIn} title="Zoom in">
            <ZoomIn size={14} />
          </ToolbarButton>
          <ToolbarButton onClick={zoomOut} title="Zoom out">
            <ZoomOut size={14} />
          </ToolbarButton>
        </div>

        {/* Interaction hint — shown only on first load, fades out */}
        {!loading && !error && graphData?.nodes?.length > 0 && (
          <div className="absolute bottom-5 left-1/2 -translate-x-1/2 z-10 pointer-events-none">
            <p className="text-[10px] text-ink-400 bg-white/60 backdrop-blur-sm rounded-full
              px-3 py-1 border border-cream-200">
              Click to inspect · Double-click to re-centre · Scroll to zoom
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Toolbar button helper ─────────────────────────────────────

function ToolbarButton({ onClick, title, children }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="w-9 h-9 flex items-center justify-center rounded-xl
        bg-white/85 border border-cream-200 shadow-warm-sm
        text-ink-600 hover:text-ink-900 hover:bg-white
        transition-all backdrop-blur-sm"
    >
      {children}
    </button>
  );
}

// ── Entity detail panel ───────────────────────────────────────

function EntityDetailPanel({ detail, navigate }) {
  const palette = NODE_PALETTE[detail.type] ?? NODE_PALETTE.Concept;

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="pb-3 border-b border-cream-100">
        <div className="flex items-start gap-2 mb-1">
          <span
            className="w-3 h-3 rounded-full flex-shrink-0 mt-0.5"
            style={{ backgroundColor: palette.border }}
          />
          <h2 className="text-sm font-bold text-ink-900 leading-snug break-words">
            {detail.name}
          </h2>
        </div>
        <div className="ml-5 flex items-center gap-2 flex-wrap">
          <span
            className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
            style={{ backgroundColor: palette.bg, color: palette.border }}
          >
            {detail.type || 'Entity'}
          </span>
          <span className="text-[10px] text-ink-400">
            {detail.mention_count} mention{detail.mention_count !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {/* Relationships */}
      {detail.relationships?.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold text-ink-400 uppercase tracking-wider mb-2">
            Relationships ({detail.relationships.length})
          </p>
          <ul className="space-y-2 max-h-52 overflow-y-auto pr-1">
            {detail.relationships.map((rel, i) => (
              <li key={i} className="text-xs leading-snug">
                <span
                  className="inline-block px-1.5 py-0.5 rounded text-[9px] font-semibold
                    bg-amber-50 text-amber-800 border border-amber-200 mr-1.5"
                >
                  {rel.relationship.replace(/_/g, ' ')}
                </span>
                <span className="text-ink-800 font-medium">{rel.target}</span>
                {rel.target_type && (
                  <span className="text-ink-400 text-[10px] ml-1">({rel.target_type})</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Source documents */}
      {detail.source_documents?.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold text-ink-400 uppercase tracking-wider mb-2">
            Source Documents ({detail.source_documents.length})
          </p>
          <ul className="space-y-1.5">
            {detail.source_documents.map((doc) => (
              <li key={doc.id}>
                <button
                  onClick={() => navigate(`/documents/${doc.id}`)}
                  className="flex items-start gap-1.5 text-xs text-amber-700
                    hover:text-amber-900 hover:underline text-left w-full group"
                >
                  <ExternalLink
                    size={11}
                    className="flex-shrink-0 mt-0.5 opacity-70 group-hover:opacity-100"
                  />
                  <span className="line-clamp-2">{doc.filename}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.relationships?.length === 0 && detail.source_documents?.length === 0 && (
        <p className="text-xs text-ink-400 italic">
          No relationships or source documents found for this entity.
        </p>
      )}
    </div>
  );
}
