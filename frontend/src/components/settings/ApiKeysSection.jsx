import { useEffect, useState } from 'react';
import { useSettingsStore } from '../../store/settingsStore';
import { Loader2, KeyRound, Check, X, Trash2, Plus } from 'lucide-react';

export default function ApiKeysSection() {
  const { providerKeys, loading, loadProviderKeys } = useSettingsStore();

  useEffect(() => {
    loadProviderKeys();
  }, [loadProviderKeys]);

  if (loading.keys && !providerKeys) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="text-violet-500 animate-spin" />
      </div>
    );
  }
  if (!providerKeys) return null;

  const entries = Object.entries(providerKeys.keys || {}).sort(([a], [b]) =>
    a.localeCompare(b)
  );

  return (
    <div className="space-y-6 animate-fade-in">
      <section className="card p-6">
        <h3 className="font-semibold text-ink-900 mb-1">Provider API keys</h3>
        <p className="text-sm text-ink-600 mb-5">
          Bring your own key (BYOK) per provider. BYOK keys are stored encrypted and take
          precedence over managed environment keys. Keys are never shown in full — only the
          last 4 characters.
        </p>

        <div className="divide-y divide-cream-200">
          {entries.map(([provider, status]) => (
            <KeyRow key={provider} provider={provider} status={status} />
          ))}
        </div>
      </section>
    </div>
  );
}

function KeyRow({ provider, status }) {
  const { saveProviderKey, removeProviderKey } = useSettingsStore();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);

  const handleSave = async () => {
    if (!value.trim()) return;
    setBusy(true);
    const ok = await saveProviderKey(provider, value.trim());
    setBusy(false);
    if (ok) {
      setValue('');
      setEditing(false);
    }
  };

  const handleRemove = async () => {
    setBusy(true);
    await removeProviderKey(provider);
    setBusy(false);
  };

  return (
    <div className="py-4">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink-900">{provider}</p>
          <p className="text-xs text-ink-600 mt-0.5">
            <SourcePill status={status} />
          </p>
        </div>

        {!editing && (
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => setEditing(true)}
              className="btn-secondary text-xs !py-1.5 !px-3"
            >
              {status.byok ? 'Replace key' : <><Plus size={13} /> Add key</>}
            </button>
            {status.byok && (
              <button
                onClick={handleRemove}
                disabled={busy}
                className="btn-ghost !p-2 text-ink-500 hover:text-terra-500"
                title="Remove BYOK key (revert to managed)"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              </button>
            )}
          </div>
        )}
      </div>

      {editing && (
        <div className="flex items-center gap-2 mt-3">
          <div className="relative flex-1">
            <KeyRound
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-500"
            />
            <input
              type="password"
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSave()}
              placeholder={`Paste ${provider} API key`}
              className="input !py-2 !pl-9 text-sm"
            />
          </div>
          <button
            onClick={handleSave}
            disabled={!value.trim() || busy}
            className="btn-primary text-xs !py-2 !px-3"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            Save
          </button>
          <button
            onClick={() => {
              setEditing(false);
              setValue('');
            }}
            className="btn-ghost !p-2"
          >
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

function SourcePill({ status }) {
  if (status.byok) {
    return (
      <span className="text-forest-500 font-medium">
        BYOK{status.hint ? ` · •••• ${status.hint}` : ''}
      </span>
    );
  }
  if (status.managed) return <span className="text-violet-500 font-medium">Managed (env)</span>;
  if (status.needs_key === false)
    return <span className="text-ink-500">No key required (local)</span>;
  return <span className="text-sand-600">Not configured</span>;
}
