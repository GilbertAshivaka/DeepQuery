import { useEffect, useState, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search, RefreshCw, AlertTriangle, ZoomIn,
  FileText, X, ExternalLink, Calendar, Tag,
} from 'lucide-react';
import { getSimilarityMap } from '../services/corpusService';
import { recomputeSimilarityMap } from '../services/adminService';
import { useAuthStore } from '../store/authStore';

const COLOR_BY_OPTIONS = [
  { value: 'document_type', label: 'Document Type' },
  { value: 'collection',    label: 'Collection' },
  { value: 'upload_year',   label: 'Upload Year' },
];

const PALETTE = [
  '#7c3aed','#d97706','#059669','#dc2626','#2563eb',
  '#db2777','#ea580c','#16a34a','#9333ea','#0891b2',
  '#65a30d','#be185d','#b45309','#0d9488','#7c2d12',
];

function buildColorMap(points, colorBy) {
  const values = [...new Set(points.map((p) => String(p[colorBy] ?? 'Unknown')))].sort();
  return Object.fromEntries(values.map((v, i) => [v, PALETTE[i % PALETTE.length]]));
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

// ── SVG scatter plot ─────────────────────────────────────────
const PAD = 24;

function ScatterPlot({ seriesGroups, colorMap, onDocClick }) {
  const svgRef   = useRef(null);
  const [tooltip, setTooltip] = useState(null);

  const allPts = useMemo(() => Object.values(seriesGroups).flat(), [seriesGroups]);

  const { minX, maxX, minY, maxY } = useMemo(() => {
    if (!allPts.length) return { minX: 0, maxX: 1, minY: 0, maxY: 1 };
    const xs = allPts.map((p) => p.x);
    const ys = allPts.map((p) => p.y);
    return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  }, [allPts]);

  const W = 800, H = 560;
  const rX = maxX - minX || 1;
  const rY = maxY - minY || 1;

  const toSvg = (x, y) => ({
    cx: PAD + ((x - minX) / rX) * (W - 2 * PAD),
    cy: H - PAD - ((y - minY) / rY) * (H - 2 * PAD),
  });

  if (!allPts.length) return null;

  return (
    <div className="relative w-full h-full">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-full"
        style={{ overflow: 'visible' }}
        onMouseLeave={() => setTooltip(null)}
      >
        {Object.entries(seriesGroups).map(([key, pts]) =>
          pts.map((p, i) => {
            const { cx, cy } = toSvg(p.x, p.y);
            const fill = colorMap[key] ?? '#9ca3af';
            return (
              <circle
                key={`${key}-${i}`}
                cx={cx} cy={cy} r={5}
                fill={fill}
                fillOpacity={0.82}
                stroke="rgba(0,0,0,0.15)"
                strokeWidth={0.5}
                style={{ cursor: 'pointer' }}
                onMouseEnter={(e) => setTooltip({ doc: p, svgX: cx, svgY: cy, fill })}
                onMouseLeave={() => setTooltip(null)}
                onClick={() => onDocClick?.(p)}
              />
            );
          })
        )}
        {/* Inline tooltip rendered inside SVG for reliable positioning */}
        {tooltip && (() => {
          const tx = tooltip.svgX + 10;
          const ty = tooltip.svgY - 10;
          const lines = [
            tooltip.doc.document_name,
            tooltip.doc.document_type ?? 'document',
            tooltip.doc.collection,
            formatDate(tooltip.doc.upload_date),
          ].filter(Boolean);
          const boxW = 180, lineH = 16, boxH = lines.length * lineH + 12;
          return (
            <g pointerEvents="none">
              <rect x={tx} y={ty - boxH} width={boxW} height={boxH}
                rx={6} fill="white" stroke="#e5d3be" strokeWidth={1}
                filter="drop-shadow(0 2px 4px rgba(0,0,0,0.12))" />
              {lines.map((line, i) => (
                <text key={i} x={tx + 8} y={ty - boxH + 14 + i * lineH}
                  fontSize={10} fill={i === 0 ? '#1c1917' : '#78716c'}
                  fontWeight={i === 0 ? 600 : 400}
                  style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
                  {line.length > 24 ? line.slice(0, 24) + '…' : line}
                </text>
              ))}
            </g>
          );
        })()}
      </svg>
    </div>
  );
}

// ── Legend ───────────────────────────────────────────────────
function ColorLegend({ colorMap }) {
  const entries = Object.entries(colorMap);
  if (!entries.length) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 px-2 pt-1">
      {entries.map(([key, color]) => (
        <span key={key} className="flex items-center gap-1 text-[10px] text-ink-600 capitalize">
          <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
          {key}
        </span>
      ))}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────
export default function CorpusExplorerPage() {
  const { user }   = useAuthStore();
  const navigate   = useNavigate();
  const isAdmin    = user?.role === 'admin';

  const [rawPoints, setRawPoints]       = useState([]);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState(null);
  const [lastComputed, setLastComputed] = useState(null);
  const [colorBy, setColorBy]           = useState('document_type');
  const [search, setSearch]             = useState('');
  const [typeFilter, setTypeFilter]     = useState('all');
  const [selectedDoc, setSelectedDoc]   = useState(null);
  const [recomputing, setRecomputing]   = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true); setError(null);
      try {
        const resp = await getSimilarityMap();
        setRawPoints(resp.points ?? []);
        setLastComputed(resp.last_computed_at);
      } catch (e) {
        setError(
          e?.response?.status === 404
            ? 'UMAP coordinates have not been computed yet. Ask an admin to trigger computation.'
            : 'Failed to load similarity map.'
        );
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const documentTypes = useMemo(
    () => ['all', ...new Set(rawPoints.map((p) => p.document_type ?? 'other'))],
    [rawPoints]
  );

  const filteredPoints = useMemo(() => {
    let pts = rawPoints;
    if (typeFilter !== 'all') pts = pts.filter((p) => p.document_type === typeFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      pts = pts.filter((p) => p.document_name.toLowerCase().includes(q));
    }
    return pts;
  }, [rawPoints, typeFilter, search]);

  const colorMap = useMemo(
    () => (rawPoints.length ? buildColorMap(rawPoints, colorBy) : {}),
    [rawPoints, colorBy]
  );

  const seriesGroups = useMemo(() => {
    const groups = {};
    for (const p of filteredPoints) {
      const key =
        colorBy === 'upload_year'
          ? String(new Date(p.upload_date ?? 0).getFullYear())
          : String(p[colorBy] ?? 'Unknown');
      if (!groups[key]) groups[key] = [];
      groups[key].push({ ...p });
    }
    return groups;
  }, [filteredPoints, colorBy]);

  const handleRecompute = async () => {
    setRecomputing(true);
    try {
      await recomputeSimilarityMap();
      alert('Recomputation queued — refresh in a few minutes.');
    } catch {
      alert('Failed to queue recomputation.');
    } finally {
      setRecomputing(false);
    }
  };

  const isStale = lastComputed && Date.now() - new Date(lastComputed).getTime() > 24 * 60 * 60 * 1000;

  return (
    <div className="h-full flex flex-col overflow-hidden bg-gradient-to-br from-cream-50 to-white">
      {/* Header */}
      <div className="bg-white/80 backdrop-blur-sm border-b border-cream-200 px-6 py-4 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-violet-500/10 flex items-center justify-center">
              <ZoomIn size={18} className="text-violet-500" />
            </div>
            <div>
              <h1 className="font-serif text-lg font-bold text-ink-900">Corpus Explorer</h1>
              <p className="text-xs text-ink-500">
                Semantic similarity map of the document corpus
                {lastComputed && ` · computed ${formatDate(lastComputed)}`}
              </p>
            </div>
          </div>
          {isAdmin && (
            <button onClick={handleRecompute} disabled={recomputing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-cream-200 text-ink-600 hover:bg-cream-50 disabled:opacity-50 transition">
              <RefreshCw size={13} className={recomputing ? 'animate-spin' : ''} />
              Recompute map
            </button>
          )}
        </div>
        {isStale && (
          <div className="mt-2 flex items-center gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            <AlertTriangle size={13} />
            This map is over 24 hours old and may not reflect recently ingested documents.
          </div>
        )}
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Control panel */}
        <div className="w-56 border-r border-cream-200 bg-white/60 overflow-y-auto p-4 space-y-5 flex-shrink-0">
          <div>
            <label className="block text-xs font-semibold text-ink-600 mb-1.5">Find document</label>
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
              <input type="text" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-7 pr-3 py-1.5 text-xs rounded-lg border border-cream-200 bg-white focus:outline-none focus:ring-2 focus:ring-violet-300" />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-ink-600 mb-1.5">Color by</label>
            {COLOR_BY_OPTIONS.map((o) => (
              <button key={o.value} onClick={() => setColorBy(o.value)}
                className={`w-full text-left px-3 py-1.5 text-xs rounded-lg mb-1 transition
                  ${colorBy === o.value ? 'bg-violet-100 text-violet-800 font-medium' : 'text-ink-600 hover:bg-cream-50'}`}>
                {o.label}
              </button>
            ))}
          </div>

          <div>
            <label className="block text-xs font-semibold text-ink-600 mb-1.5">Filter by type</label>
            {documentTypes.map((t) => (
              <button key={t} onClick={() => setTypeFilter(t)}
                className={`w-full text-left px-3 py-1.5 text-xs rounded-lg mb-1 transition capitalize
                  ${typeFilter === t ? 'bg-amber-100 text-amber-800 font-medium' : 'text-ink-600 hover:bg-cream-50'}`}>
                {t}
              </button>
            ))}
          </div>

          <p className="text-[10px] text-ink-400 pt-2 border-t border-cream-100">
            {filteredPoints.length} of {rawPoints.length} documents shown
          </p>
        </div>

        {/* Chart canvas */}
        <div className="flex-1 overflow-hidden flex flex-col p-3 gap-2">
          {loading ? (
            <div className="flex-1 flex flex-col items-center justify-center text-ink-400 gap-2">
              <RefreshCw size={20} className="animate-spin text-violet-400" />
              <p className="text-sm">Loading similarity map…</p>
            </div>
          ) : error ? (
            <div className="flex-1 flex flex-col items-center justify-center text-ink-400 gap-3 px-8 text-center">
              <AlertTriangle size={28} className="text-amber-400" />
              <p className="text-sm">{error}</p>
            </div>
          ) : filteredPoints.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-ink-400 text-sm">
              No documents match the current filter.
            </div>
          ) : (
            <>
              <div className="flex-1 overflow-hidden">
                <ScatterPlot seriesGroups={seriesGroups} colorMap={colorMap} onDocClick={setSelectedDoc} />
              </div>
              <ColorLegend colorMap={colorMap} />
            </>
          )}
        </div>
      </div>

      {/* Document detail drawer */}
      {selectedDoc && (
        <div className="fixed inset-0 z-50 flex" onClick={() => setSelectedDoc(null)}>
          <div className="flex-1 bg-black/20" />
          <div className="w-80 bg-white shadow-2xl h-full flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between px-5 py-4 border-b border-cream-200 bg-cream-50">
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-sm text-ink-900 leading-snug">{selectedDoc.document_name}</h3>
                <p className="text-xs text-ink-500 mt-0.5 capitalize">{selectedDoc.document_type ?? 'document'}</p>
              </div>
              <button onClick={() => setSelectedDoc(null)} className="p-1.5 hover:bg-cream-100 rounded-lg ml-2 flex-shrink-0">
                <X size={15} className="text-ink-600" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2 text-ink-600">
                  <FileText size={14} className="text-ink-400 flex-shrink-0" />
                  <span className="capitalize">{selectedDoc.collection} collection</span>
                </div>
                <div className="flex items-center gap-2 text-ink-600">
                  <Calendar size={14} className="text-ink-400 flex-shrink-0" />
                  <span>{formatDate(selectedDoc.upload_date)}</span>
                </div>
                {selectedDoc.page_count && (
                  <div className="flex items-center gap-2 text-ink-600">
                    <FileText size={14} className="text-ink-400 flex-shrink-0" />
                    <span>{selectedDoc.page_count} pages</span>
                  </div>
                )}
              </div>
              {selectedDoc.topic_tags?.length > 0 && (
                <div>
                  <div className="flex items-center gap-1 text-xs font-semibold text-ink-600 mb-1.5">
                    <Tag size={11} /> Topic tags
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {selectedDoc.topic_tags.map((tag) => (
                      <span key={tag} className="px-2 py-0.5 text-[11px] bg-violet-50 text-violet-700 border border-violet-200 rounded-full">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <button onClick={() => navigate(`/documents/${selectedDoc.id}`)}
                className="w-full flex items-center justify-center gap-2 py-2 rounded-xl bg-amber-800 text-white text-sm font-medium hover:bg-amber-900 transition mt-2">
                <ExternalLink size={14} />
                Open document
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
