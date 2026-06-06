import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

const STATUS_META = {
  VERIFIED:             { label: 'Verified',            cls: 'text-emerald-700 bg-emerald-50 border-emerald-200' },
  CORRECTED:            { label: 'Self-corrected',       cls: 'text-amber-700 bg-amber-50 border-amber-200' },
  INSUFFICIENT_CONTEXT: { label: 'Insufficient context', cls: 'text-red-700 bg-red-50 border-red-200' },
};

function barColor(score) {
  if (score >= 0.75) return '#059669';
  if (score >= 0.5)  return '#d97706';
  return '#9ca3af';
}

function ConfidenceBar({ label, score }) {
  const pct = Math.round(score * 100);
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-36 text-ink-600 truncate text-right flex-shrink-0" title={label}>
        {label}
      </span>
      <div className="flex-1 h-3 bg-cream-100 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, backgroundColor: barColor(score), transition: 'width 0.4s ease' }}
        />
      </div>
      <span className="w-7 text-right text-ink-500 flex-shrink-0">{pct}%</span>
    </div>
  );
}

export default function RetrievalConfidenceChart({ sources, selfCorrectionStatus }) {
  const [expanded, setExpanded] = useState(false);

  const scored = sources
    .map((s, i) => ({
      label: s.document_name || s.document_title || `Source ${i + 1}`,
      score: typeof s.relevance_score === 'number' ? s.relevance_score : 0.5,
    }))
    .sort((a, b) => b.score - a.score);

  const visible = expanded ? scored.slice(0, 8) : scored.slice(0, 5);
  const meta    = STATUS_META[selfCorrectionStatus] ?? null;

  return (
    <div className="mt-3 mb-1 rounded-xl border border-cream-200 bg-cream-50/60 px-4 py-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-ink-600 uppercase tracking-wide">
          Retrieval Confidence
        </span>
        {meta && (
          <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${meta.cls}`}>
            {meta.label}
          </span>
        )}
      </div>

      <div className="space-y-1.5">
        {visible.map((s, i) => (
          <ConfidenceBar key={i} label={s.label} score={s.score} />
        ))}
      </div>

      {scored.length > 5 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-[11px] text-ink-500 hover:text-ink-700 transition mt-1"
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {expanded ? 'Show fewer' : `Show ${scored.length - 5} more`}
        </button>
      )}

      <div className="flex items-center gap-3 pt-1 text-[10px] text-ink-400 border-t border-cream-200">
        {[['#059669','High ≥75%'],['#d97706','Medium ≥50%'],['#9ca3af','Low <50%']].map(([c,l]) => (
          <span key={l} className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full inline-block flex-shrink-0" style={{ backgroundColor: c }} />
            {l}
          </span>
        ))}
      </div>
    </div>
  );
}
