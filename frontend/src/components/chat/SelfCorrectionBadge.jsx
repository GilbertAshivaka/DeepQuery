import { useState } from 'react';
import { RefreshCw, AlertTriangle } from 'lucide-react';

// Maps the pipeline's self-correction outcome to a compact, icon-only trust
// indicator (the label is kept for the tooltip / accessibility only).
// VERIFIED is intentionally omitted — a badge on every grounded answer would
// raise alarm for no reason. Only the noteworthy states are surfaced.
const BADGES = {
  CORRECTED: {
    icon: RefreshCw,
    label: 'Corrected',
    tip: 'Corrected — the self-correction layer revised this answer to better align it with the retrieved sources.',
    color: 'text-amber-800',
  },
  INSUFFICIENT_CONTEXT: {
    icon: AlertTriangle,
    label: 'Insufficient context',
    tip: 'Insufficient context — the system could not find enough relevant sources to fully answer this, so the response may be incomplete.',
    color: 'text-terra-500',
  },
};

export default function SelfCorrectionBadge({ status }) {
  const [hovered, setHovered] = useState(false);
  const cfg = BADGES[status];
  if (!cfg) return null;

  const Icon = cfg.icon;
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span
        aria-label={cfg.label}
        className={`inline-flex items-center justify-center p-1 rounded-md cursor-default
                    hover:bg-cream-100 transition-colors ${cfg.color}`}
      >
        <Icon size={12} />
      </span>
      {hovered && (
        <span
          role="tooltip"
          className="absolute left-0 bottom-full mb-1.5 z-30 w-60 px-2.5 py-1.5
                     text-[11px] leading-snug text-ink-700 bg-white rounded-lg
                     border border-cream-200 shadow-warm-lg animate-fade-in"
        >
          {cfg.tip}
        </span>
      )}
    </span>
  );
}
