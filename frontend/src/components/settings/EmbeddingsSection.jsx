import { useEffect, useRef, useState } from 'react';
import { useSettingsStore } from '../../store/settingsStore';
import {
  Loader2,
  AlertTriangle,
  Layers,
  RefreshCw,
  CheckCircle2,
  XCircle,
} from 'lucide-react';

const LOCAL = new Set(['ollama']);
const MODEL_HINTS = {
  google: 'gemini-embedding-2-preview',
  openai: 'text-embedding-3-small / -large',
  qwen: 'text-embedding-v3',
  ollama: 'nomic-embed-text',
};
const DIM_HINTS = { google: 3072, openai: 1536, qwen: 1024, ollama: 768 };

export default function EmbeddingsSection() {
  const { embedding, loading, loadEmbedding, refreshReindexStatus } = useSettingsStore();

  useEffect(() => {
    loadEmbedding();
  }, [loadEmbedding]);

  // Poll while a re-index is running.
  const running = embedding?.reindex_status?.state === 'running';
  const pollRef = useRef(null);
  useEffect(() => {
    if (running) {
      pollRef.current = setInterval(refreshReindexStatus, 2500);
      return () => clearInterval(pollRef.current);
    }
  }, [running, refreshReindexStatus]);

  if (loading.embedding && !embedding) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="text-violet-500 animate-spin" />
      </div>
    );
  }
  if (!embedding) return null;

  const { active, supported_providers, providers, deployment_mode, warning, reindex_status } =
    embedding;
  const airGapped = deployment_mode === 'air-gapped';
  const choices = (supported_providers || []).filter((p) => !airGapped || LOCAL.has(p));

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Active embedder */}
      <section className="card p-6">
        <div className="flex items-center gap-2 mb-4">
          <Layers size={16} className="text-violet-500" />
          <h3 className="font-semibold text-ink-900">Active embedding model</h3>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <Field label="Provider" value={active?.provider} />
          <Field label="Model" value={active?.model} />
          <Field label="Dimensions" value={active?.params?.dimensions} />
        </div>
        {active?.params?.collection_version && (
          <p className="mt-3 text-xs text-ink-600">
            Collection version: <span className="font-mono">{active.params.collection_version}</span>
          </p>
        )}
      </section>

      {/* Warning */}
      <div className="flex items-start gap-2 p-4 rounded-xl border border-sand-500/30 bg-sand-500/10 text-sm text-sand-600">
        <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" />
        <span>{warning}</span>
      </div>

      {/* Progress (if a job exists) */}
      {reindex_status && reindex_status.state !== 'idle' && (
        <ReindexProgress status={reindex_status} />
      )}

      {/* Re-index form */}
      <ReindexForm
        choices={choices}
        providers={providers}
        disabled={reindex_status?.state === 'running'}
      />
    </div>
  );
}

function ReindexForm({ choices, providers, disabled }) {
  const { startReindex, loadEmbedding } = useSettingsStore();
  const [form, setForm] = useState({ provider: choices[0] || '', model: '', dimensions: '', base_url: '' });
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const needsBaseUrl = form.provider === 'ollama';
  const valid =
    form.provider && form.model.trim() && Number(form.dimensions) > 0 &&
    (!needsBaseUrl || true); // ollama base_url optional (defaults to configured)

  const onProvider = (provider) =>
    setForm((f) => ({ ...f, provider, dimensions: f.dimensions || DIM_HINTS[provider] || '' }));

  const submit = async () => {
    setBusy(true);
    const res = await startReindex({
      provider: form.provider,
      model: form.model.trim(),
      dimensions: Number(form.dimensions),
      base_url: form.base_url.trim() || null,
    });
    setBusy(false);
    setConfirming(false);
    if (res) {
      setForm({ provider: choices[0] || '', model: '', dimensions: '', base_url: '' });
      loadEmbedding();
    }
  };

  return (
    <section className="card p-6">
      <h3 className="font-semibold text-ink-900 mb-1">Switch embedding model</h3>
      <p className="text-sm text-ink-600 mb-5">
        Runs a blue-green re-index. The current embedder keeps serving until the new one is
        verified and promoted.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-ink-700 mb-1">Provider</label>
          <select
            value={form.provider}
            disabled={disabled}
            onChange={(e) => onProvider(e.target.value)}
            className="input !py-2 text-sm"
          >
            {choices.map((p) => {
              const a = providers?.[p];
              return (
                <option key={p} value={p}>
                  {p}
                  {a && !a.available ? ' — no key' : ''}
                </option>
              );
            })}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-700 mb-1">Model</label>
          <input
            value={form.model}
            disabled={disabled}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
            placeholder={MODEL_HINTS[form.provider] || 'model id'}
            className="input !py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-700 mb-1">Dimensions</label>
          <input
            type="number"
            min="1"
            value={form.dimensions}
            disabled={disabled}
            onChange={(e) => setForm({ ...form, dimensions: e.target.value })}
            placeholder={String(DIM_HINTS[form.provider] || '')}
            className="input !py-2 text-sm"
          />
        </div>
        {needsBaseUrl && (
          <div>
            <label className="block text-xs font-medium text-ink-700 mb-1">
              Base URL (optional)
            </label>
            <input
              value={form.base_url}
              disabled={disabled}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              placeholder="http://localhost:11434"
              className="input !py-2 text-sm"
            />
          </div>
        )}
      </div>

      <div className="flex justify-end mt-4">
        <button
          onClick={() => setConfirming(true)}
          disabled={!valid || disabled}
          className="btn-primary text-sm"
        >
          <RefreshCw size={15} /> Start re-index
        </button>
      </div>

      {confirming && (
        <ConfirmModal
          form={form}
          busy={busy}
          onCancel={() => setConfirming(false)}
          onConfirm={submit}
        />
      )}
    </section>
  );
}

function ConfirmModal({ form, busy, onCancel, onConfirm }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/30 backdrop-blur-sm">
      <div className="card w-full max-w-md mx-4 p-6 animate-slide-up">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={18} className="text-sand-600" />
          <h3 className="font-semibold text-ink-900">Confirm re-index</h3>
        </div>
        <p className="text-sm text-ink-700 mb-4">
          This re-embeds the entire corpus into new collections using{' '}
          <span className="font-medium">{form.provider}</span> /{' '}
          <span className="font-mono">{form.model}</span> ({form.dimensions} dims). It can take a
          while and cannot be undone in place. The current model keeps serving until the new
          one is promoted.
        </p>
        <div className="flex gap-3">
          <button onClick={onCancel} className="btn-secondary flex-1" disabled={busy}>
            Cancel
          </button>
          <button onClick={onConfirm} className="btn-primary flex-1" disabled={busy}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
            Start re-index
          </button>
        </div>
      </div>
    </div>
  );
}

function ReindexProgress({ status }) {
  const collections = status.collections || {};
  const stateColor =
    {
      running: 'text-violet-500',
      complete: 'text-forest-500',
      failed: 'text-terra-500',
    }[status.state] || 'text-ink-600';

  return (
    <section className="card p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-ink-900">Re-index status</h3>
        <span className={`text-sm font-medium capitalize flex items-center gap-1.5 ${stateColor}`}>
          {status.state === 'running' && <Loader2 size={14} className="animate-spin" />}
          {status.state === 'complete' && <CheckCircle2 size={14} />}
          {status.state === 'failed' && <XCircle size={14} />}
          {status.state}
        </span>
      </div>

      {status.target && (
        <p className="text-xs text-ink-600 mb-4">
          Target: {status.target.provider} / <span className="font-mono">{status.target.model}</span>
          {status.target.dimensions ? ` (${status.target.dimensions} dims)` : ''}
        </p>
      )}

      <div className="space-y-3">
        {Object.entries(collections).map(([name, c]) => {
          const total = c.total || 0;
          const written = c.written || 0;
          const pct = total ? Math.min(100, Math.round((written / total) * 100)) : 0;
          return (
            <div key={name}>
              <div className="flex justify-between text-xs text-ink-700 mb-1">
                <span>{name}</span>
                <span>
                  {written}/{total}
                </span>
              </div>
              <div className="h-2 rounded-full bg-cream-200 overflow-hidden">
                <div
                  className="h-full bg-violet-500 transition-all duration-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {status.error && (
        <p className="mt-4 text-xs text-terra-500 flex items-start gap-1">
          <XCircle size={13} className="flex-shrink-0 mt-0.5" /> {status.error}
        </p>
      )}
    </section>
  );
}

function Field({ label, value }) {
  return (
    <div>
      <p className="text-xs font-medium text-ink-700 mb-1">{label}</p>
      <p className="text-sm text-ink-900 font-medium break-words">
        {value ?? <span className="text-ink-500">—</span>}
      </p>
    </div>
  );
}
