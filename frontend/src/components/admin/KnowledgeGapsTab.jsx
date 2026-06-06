import { useEffect, useState, useCallback } from 'react';
import {
  AlertTriangle, CheckCircle2, Download, RefreshCw, ChevronRight, X,
} from 'lucide-react';
import * as adminService from '../../services/adminService';

const WINDOW_OPTIONS = [
  { label: 'Last 7 days',  value: 7 },
  { label: 'Last 30 days', value: 30 },
  { label: 'Last 90 days', value: 90 },
  { label: 'All time',     value: 0 },
];

// ── Pure-CSS heatmap grid ────────────────────────────────────
function HeatmapGrid({ topics, periods, data }) {
  if (!topics.length || !periods.length) return null;
  const maxVal = Math.max(...data.flatMap((row) => row), 1);

  function cellBg(val) {
    if (val === 0) return '#fdf8f0';
    const t = val / maxVal;
    if (t < 0.33) return `rgba(251,191,36,${0.2 + t * 1.2})`;
    if (t < 0.66) return `rgba(217,119,6,${0.4 + t * 0.8})`;
    return `rgba(146,64,14,${0.5 + t * 0.5})`;
  }
  function cellText(val) {
    return (val / maxVal) > 0.45 ? '#fff' : '#5c3a1e';
  }

  return (
    <div className="overflow-x-auto">
      <div style={{ minWidth: Math.max(periods.length * 64 + 176, 480) }}>
        <div className="flex mb-1 ml-44">
          {periods.map((p) => (
            <div key={p} className="flex-1 text-center text-[10px] text-ink-500 font-medium truncate px-0.5">
              {p}
            </div>
          ))}
        </div>
        {topics.map((topic, tIdx) => (
          <div key={topic} className="flex items-center mb-1">
            <div className="w-44 pr-3 text-xs text-ink-700 truncate text-right flex-shrink-0 capitalize" title={topic}>
              {topic}
            </div>
            {periods.map((_, pIdx) => {
              const val = data[tIdx][pIdx];
              return (
                <div
                  key={pIdx}
                  className="flex-1 mx-0.5 h-7 rounded flex items-center justify-center text-[10px] font-semibold cursor-default"
                  style={{ backgroundColor: cellBg(val), color: cellText(val) }}
                  title={`${topic} · ${periods[pIdx]}: ${val}`}
                >
                  {val > 0 ? val : ''}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Pure-CSS horizontal bar chart ────────────────────────────
function GapsBarChart({ gaps }) {
  const max = Math.max(...gaps.map((g) => g.count), 1);
  return (
    <div className="space-y-2">
      {gaps.map((g, idx) => {
        const pct = Math.round((g.count / max) * 100);
        return (
          <div key={idx} className="flex items-center gap-3 text-xs">
            <span className="w-40 text-ink-700 truncate text-right flex-shrink-0 capitalize" title={g.topic}>
              {g.topic}
            </span>
            <div className="flex-1 h-5 bg-cream-100 rounded overflow-hidden">
              <div
                className="h-full bg-amber-600 rounded flex items-center justify-end pr-1.5"
                style={{ width: `${pct}%`, transition: 'width 0.4s ease' }}
              >
                {pct > 15 && (
                  <span className="text-white text-[10px] font-bold">{g.count}</span>
                )}
              </div>
            </div>
            {pct <= 15 && (
              <span className="text-ink-600 text-[10px] font-semibold w-5">{g.count}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────
export default function KnowledgeGapsTab() {
  const [windowDays, setWindowDays]       = useState(30);
  const [minFreq, setMinFreq]             = useState(2);
  const [data, setData]                   = useState(null);
  const [loading, setLoading]             = useState(true);
  const [resolving, setResolving]         = useState(null);
  const [detailTopic, setDetailTopic]     = useState(null);
  const [detailData, setDetailData]       = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await adminService.getKnowledgeGapsMatrix(windowDays, minFreq);
      setData(resp);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [windowDays, minFreq]);

  useEffect(() => { load(); }, [load]);

  const handleResolve = async (topic) => {
    setResolving(topic);
    try {
      await adminService.resolveGapTopic(topic);
      await load();
    } finally {
      setResolving(null);
    }
  };

  const openDetail = async (topic) => {
    setDetailTopic(topic);
    setDetailLoading(true);
    setDetailData(null);
    try {
      const resp = await adminService.getGapDetail(topic, windowDays);
      setDetailData(resp);
    } finally {
      setDetailLoading(false);
    }
  };

  const exportCsv = () => {
    if (!data?.top_gaps) return;
    const rows = [['Topic', 'Count', 'Last Asked']];
    for (const g of data.top_gaps) rows.push([g.topic, g.count, g.last_asked ?? '']);
    const csv  = rows.map((r) => r.map((c) => `"${c}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a'); a.href = url;
    a.download = `knowledge-gaps-${windowDays}d.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  const matrix  = data?.frequency_matrix;
  const hasData = matrix?.topics?.length > 0 && matrix?.periods?.length > 0;

  return (
    <div className="p-6 space-y-6">
      {/* Controls */}
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label className="block text-xs font-semibold text-ink-600 mb-1">Time window</label>
          <div className="flex gap-1">
            {WINDOW_OPTIONS.map((o) => (
              <button
                key={o.value}
                onClick={() => setWindowDays(o.value)}
                className={`px-3 py-1.5 text-xs rounded-lg border font-medium transition-all
                  ${windowDays === o.value
                    ? 'bg-amber-800 text-white border-amber-800'
                    : 'bg-white text-ink-700 border-cream-200 hover:border-amber-800/40'}`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-ink-600 mb-1">
            Min frequency: <span className="text-amber-800 font-bold">{minFreq}</span>
          </label>
          <input
            type="range" min={1} max={10} value={minFreq}
            onChange={(e) => setMinFreq(Number(e.target.value))}
            className="w-32 accent-amber-700"
          />
        </div>

        <div className="flex gap-2 ml-auto">
          <button onClick={load} className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-cream-200 text-ink-600 hover:bg-cream-50 transition">
            <RefreshCw size={13} /> Refresh
          </button>
          <button onClick={exportCsv} disabled={!data?.top_gaps?.length} className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-cream-200 text-ink-600 hover:bg-cream-50 disabled:opacity-40 transition">
            <Download size={13} /> Export CSV
          </button>
        </div>
      </div>

      {/* Summary pills */}
      {data && (
        <div className="flex gap-3 text-sm flex-wrap">
          <div className="px-4 py-2 rounded-xl bg-amber-50 border border-amber-200">
            <span className="font-bold text-amber-800">{data.total_gaps}</span>
            <span className="text-amber-700 ml-1">unanswered queries</span>
          </div>
          {data.resolved_topics?.length > 0 && (
            <div className="px-4 py-2 rounded-xl bg-emerald-50 border border-emerald-200">
              <span className="font-bold text-emerald-700">{data.resolved_topics.length}</span>
              <span className="text-emerald-600 ml-1">topics resolved</span>
            </div>
          )}
        </div>
      )}

      {loading ? (
        <div className="h-48 flex items-center justify-center text-ink-500 text-sm gap-2">
          <RefreshCw size={16} className="animate-spin" /> Loading gap analysis…
        </div>
      ) : !hasData ? (
        <div className="h-48 flex flex-col items-center justify-center text-ink-400 gap-2">
          <AlertTriangle size={26} className="text-amber-400" />
          <p className="text-sm">No gaps found for this window / frequency threshold.</p>
        </div>
      ) : (
        <>
          <div className="rounded-2xl border border-cream-200 bg-white/70 p-5">
            <h3 className="text-sm font-semibold text-ink-800 mb-4">Topic Frequency by Period</h3>
            <HeatmapGrid topics={matrix.topics} periods={matrix.periods} data={matrix.data} />
            <div className="flex items-center gap-3 mt-4 text-[10px] text-ink-500">
              {[['Low','rgba(251,191,36,0.4)'],['Medium','rgba(217,119,6,0.7)'],['High','rgba(146,64,14,0.9)']].map(([label, color]) => (
                <span key={label} className="flex items-center gap-1">
                  <span className="inline-block w-3 h-3 rounded-sm" style={{ backgroundColor: color }} />
                  {label}
                </span>
              ))}
            </div>
          </div>

          {data.top_gaps?.length > 0 && (
            <div className="rounded-2xl border border-cream-200 bg-white/70 p-5">
              <h3 className="text-sm font-semibold text-ink-800 mb-4">Top Knowledge Gaps — Occurrence Frequency</h3>
              <GapsBarChart gaps={data.top_gaps} />
            </div>
          )}

          <div className="rounded-2xl border border-cream-200 bg-white/70 overflow-hidden">
            <div className="px-5 py-3 border-b border-cream-200 bg-cream-50">
              <h3 className="text-sm font-semibold text-ink-800">Top Knowledge Gaps</h3>
            </div>
            <ul>
              {(data.top_gaps ?? []).map((g, idx) => (
                <li key={g.topic} className="flex items-center gap-3 px-5 py-3 border-b border-cream-100 last:border-0 hover:bg-cream-50/60 transition">
                  <span className="w-6 h-6 rounded-full bg-amber-100 text-amber-800 text-xs font-bold flex items-center justify-center flex-shrink-0">
                    {idx + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-ink-800 truncate capitalize">{g.topic}</p>
                    <p className="text-[11px] text-ink-500">
                      {g.count} occurrence{g.count !== 1 ? 's' : ''}
                      {g.last_asked && ` · last asked ${new Date(g.last_asked).toLocaleDateString()}`}
                    </p>
                  </div>
                  <button onClick={() => openDetail(g.topic)} className="flex items-center gap-1 text-[11px] text-violet-600 hover:text-violet-800 transition flex-shrink-0">
                    View <ChevronRight size={12} />
                  </button>
                  {g.resolved ? (
                    <span className="flex items-center gap-1 text-[11px] text-emerald-600 flex-shrink-0">
                      <CheckCircle2 size={13} /> Resolved
                    </span>
                  ) : (
                    <button onClick={() => handleResolve(g.topic)} disabled={resolving === g.topic}
                      className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg border border-emerald-200 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 transition flex-shrink-0">
                      {resolving === g.topic ? <RefreshCw size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
                      Mark resolved
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </>
      )}

      {/* Detail drawer */}
      {detailTopic && (
        <div className="fixed inset-0 z-50 flex" onClick={() => setDetailTopic(null)}>
          <div className="flex-1 bg-black/20" />
          <div className="w-96 bg-white shadow-2xl h-full flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-cream-200 bg-cream-50">
              <div>
                <h3 className="font-semibold text-ink-900 capitalize">{detailTopic}</h3>
                <p className="text-xs text-ink-500 mt-0.5">Queries contributing to this gap</p>
              </div>
              <button onClick={() => setDetailTopic(null)} className="p-1.5 hover:bg-cream-100 rounded-lg">
                <X size={16} className="text-ink-600" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {detailLoading ? (
                <div className="flex justify-center py-10 text-ink-400"><RefreshCw size={16} className="animate-spin" /></div>
              ) : detailData?.queries?.length ? (
                detailData.queries.map((q, idx) => (
                  <div key={idx} className="rounded-xl border border-cream-200 bg-cream-50 p-3">
                    <p className="text-sm text-ink-800">{q.query_text}</p>
                    <div className="flex items-center gap-2 mt-1.5 text-[10px] text-ink-400">
                      <span>{new Date(q.submitted_at).toLocaleString()}</span>
                      <span>·</span>
                      <span className="capitalize">{q.user_role}</span>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-sm text-ink-400 text-center py-10">No queries found.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
