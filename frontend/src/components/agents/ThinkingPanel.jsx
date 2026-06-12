import { useState, useEffect, useRef } from 'react';
import { ChevronRight, Brain, Wrench, Globe, Sparkles } from 'lucide-react';

/**
 * Anthropic-style CoT timeline. Reasoning, tool activity, and streamed thinking
 * deltas render in arrival order as a calm left-aligned trail with small per-step
 * icons. It stays expanded while the agent works, then auto-collapses to a quiet
 * summary line once done (re-expandable). Calm and low-noise — a trail, not a console.
 */

const WEB_RE = /search|web|wiki|duck|fetch|browse|http/i;

// Human-readable tool labels — users shouldn't see raw ids like "document_expand".
const TOOL_LABELS = {
  document_search: 'Document search',
  document_expand: 'Document expand',
  live_search: 'Live search',
};
const prettyTool = (t) =>
  TOOL_LABELS[t] ||
  (t ? t.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) : 'Tool');

function iconFor(item) {
  if (item.kind === 'thinking') return Brain;
  if (item.kind === 'reasoning') return Sparkles;
  if (item.kind === 'tool') return WEB_RE.test(item.tool || '') ? Globe : Wrench;
  return Sparkles;
}

export default function ThinkingPanel({ trace = [], isStreaming }) {
  const [open, setOpen] = useState(isStreaming);
  const touched = useRef(false);

  // Follow the run state (expand while working, collapse when done) until the
  // user manually toggles — then respect their choice.
  useEffect(() => {
    if (!touched.current) setOpen(isStreaming);
  }, [isStreaming]);

  if (!trace.length) return null;

  const toggle = () => {
    touched.current = true;
    setOpen((o) => !o);
  };

  return (
    <div className="mb-3">
      <button
        onClick={toggle}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-600 hover:text-ink-900 transition-colors"
      >
        <ChevronRight size={13} className={`transition-transform ${open ? 'rotate-90' : ''}`} />
        <Brain size={13} className="text-violet-500" />
        <span>{isStreaming ? 'Thinking' : 'Worked through it'}</span>
        {isStreaming ? (
          <span className="inline-flex gap-0.5 ml-0.5">
            <span className="w-1 h-1 rounded-full bg-violet-400 animate-pulse" style={{ animationDelay: '0ms' }} />
            <span className="w-1 h-1 rounded-full bg-violet-400 animate-pulse" style={{ animationDelay: '150ms' }} />
            <span className="w-1 h-1 rounded-full bg-violet-400 animate-pulse" style={{ animationDelay: '300ms' }} />
          </span>
        ) : (
          <span className="text-sand-500">· {trace.length} steps</span>
        )}
      </button>

      {open && (
        <div className="mt-2.5 pl-1 animate-slide-up">
          <ol className="relative space-y-3 border-l border-cream-200 ml-2">
            {trace.map((item, i) => {
              const Icon = iconFor(item);
              return (
                <li key={i} className="relative pl-5">
                  {/* timeline node */}
                  <span className="absolute -left-[9px] top-0.5 flex items-center justify-center w-[17px] h-[17px] rounded-full bg-cream-50 border border-cream-200">
                    <Icon size={10} className="text-sand-500" />
                  </span>

                  {item.kind === 'tool' ? (
                    <div className="flex flex-wrap items-center gap-1.5 text-xs leading-relaxed">
                      <span className="font-medium text-ink-700">{prettyTool(item.tool)}</span>
                      {item.detail && <span className="text-ink-500">· {item.detail}</span>}
                    </div>
                  ) : (
                    <p className="text-xs text-ink-600 leading-relaxed whitespace-pre-wrap">
                      {item.kind === 'thinking' ? item.content : item.text}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
}
