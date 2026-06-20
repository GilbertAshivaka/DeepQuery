import { useEffect, useState } from 'react';
import { Loader2, RotateCcw } from 'lucide-react';
import { useSettingsStore } from '../../store/settingsStore';

/**
 * Per-user agent retrieval knobs (Settings → Agent). Sliders bounded to the
 * server-provided [min,max] ranges; values are also clamped server-side, so the UI
 * can't push the agent out of safe bounds. Changes apply to new agent runs.
 */
export default function AgentSection() {
  const { agentPrefs, loadAgentPrefs, saveAgentPrefs } = useSettingsStore();
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!agentPrefs) loadAgentPrefs();
  }, [agentPrefs, loadAgentPrefs]);

  useEffect(() => {
    if (agentPrefs?.prefs) setDraft({ ...agentPrefs.prefs });
  }, [agentPrefs]);

  if (!agentPrefs || !draft) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={22} className="text-violet-500 animate-spin" />
      </div>
    );
  }

  const { bounds, defaults, page_chars } = agentPrefs;
  const dirty = Object.keys(draft).some((k) => draft[k] !== agentPrefs.prefs[k]);
  const set = (k, v) => setDraft((d) => ({ ...d, [k]: v }));

  const save = async () => {
    setSaving(true);
    await saveAgentPrefs(draft);
    setSaving(false);
  };
  const reset = () => setDraft({ ...defaults });

  const pages = draft.whole_doc_max_pages;
  const approxChars = pages * (page_chars || 3000);

  return (
    <div className="space-y-8 animate-fade-in">
      <section className="card p-6">
        <div className="flex items-start justify-between mb-1">
          <h3 className="font-semibold text-ink-900">Retrieval</h3>
          <button
            onClick={reset}
            className="inline-flex items-center gap-1 text-[11px] text-ink-500 hover:text-ink-800 transition-colors"
            title="Reset to defaults"
          >
            <RotateCcw size={12} /> Reset to defaults
          </button>
        </div>
        <p className="text-sm text-ink-600 mb-5">
          How the agent gathers context for your runs. Lower values keep answers tighter
          and faster; higher values pull in more at the cost of speed. Changes apply to
          new runs.
        </p>

        <div className="divide-y divide-cream-200">
          <SliderRow
            title="Parallel searches per step"
            description="How many distinct lookups the agent may run at once in a single research step. Fewer means tighter, less noisy results."
            value={draft.max_parallel_reads}
            bounds={bounds.max_parallel_reads}
            onChange={(v) => set('max_parallel_reads', v)}
            suffix={(v) => (v === 1 ? '1 search' : `${v} searches`)}
          />
          <SliderRow
            title="Pull a full document after"
            description="When this many passages come from the same document, the agent loads that document's full text for richer context."
            value={draft.whole_doc_min_chunks}
            bounds={bounds.whole_doc_min_chunks}
            onChange={(v) => set('whole_doc_min_chunks', v)}
            suffix={(v) => `${v} passages`}
          />
          <SliderRow
            title="Full documents per step"
            description="The maximum number of different documents the agent may load in full during one research step."
            value={draft.whole_doc_max_docs}
            bounds={bounds.whole_doc_max_docs}
            onChange={(v) => set('whole_doc_max_docs', v)}
            suffix={(v) => (v === 1 ? '1 document' : `${v} documents`)}
          />
          <SliderRow
            title="Full-document length"
            description="How much of each full document to read in, measured in pages. The agent's overall context budget still applies."
            value={pages}
            bounds={bounds.whole_doc_max_pages}
            onChange={(v) => set('whole_doc_max_pages', v)}
            suffix={(v) => `${v} pages`}
            footnote={`≈ ${approxChars.toLocaleString()} characters (~${Math.round(approxChars / 4 / 1000)}k tokens) per document`}
          />
        </div>

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            onClick={save}
            disabled={!dirty || saving}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg
              bg-violet-500 text-white hover:bg-violet-600 disabled:opacity-40 active:scale-[0.98] transition-all"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : null}
            Save changes
          </button>
        </div>
      </section>
    </div>
  );
}

function SliderRow({ title, description, value, bounds, onChange, suffix, footnote }) {
  const [lo, hi] = bounds;
  return (
    <div className="py-4">
      <div className="flex items-center justify-between gap-6">
        <div className="pr-2">
          <p className="text-sm font-medium text-ink-900">{title}</p>
          <p className="text-xs text-ink-600 mt-0.5">{description}</p>
        </div>
        <span className="flex-shrink-0 text-sm font-semibold text-violet-700 tabular-nums min-w-[92px] text-right">
          {suffix(value)}
        </span>
      </div>
      <div className="flex items-center gap-3 mt-3">
        <span className="text-[10px] text-ink-400 tabular-nums w-4 text-right">{lo}</span>
        <input
          type="range"
          min={lo}
          max={hi}
          step={1}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1 accent-violet-500 cursor-pointer"
        />
        <span className="text-[10px] text-ink-400 tabular-nums w-4">{hi}</span>
      </div>
      {footnote && <p className="text-[11px] text-ink-500 mt-1.5 ml-7">{footnote}</p>}
    </div>
  );
}
