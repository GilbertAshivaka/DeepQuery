import { useEffect, useState } from 'react';
import { useSettingsStore } from '../../store/settingsStore';
import Switch from '../ui/Switch';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Zap,
  Lock,
  Brain,
  AlertTriangle,
} from 'lucide-react';

// Local (no-cloud) providers — the only ones allowed when deployment is air-gapped.
const LOCAL_PROVIDERS = new Set(['ollama', 'openai_compatible', 'vllm']);
// Providers that require a base_url, and those where it's an optional override.
const BASEURL_REQUIRED = new Set(['openai_compatible', 'vllm']);
const BASEURL_OPTIONAL = new Set(['openai']);

// Example model ids — placeholders only; the field stays free-text (handoff §6).
const MODEL_HINTS = {
  groq: 'e.g. openai/gpt-oss-120b, llama-3.3-70b-versatile',
  google: 'e.g. gemini-2.0-flash, gemini-2.5-pro',
  anthropic: 'e.g. claude-sonnet-4-6, claude-opus-4-1',
  openai: 'e.g. gpt-4o-mini, gpt-4o',
  deepseek: 'e.g. deepseek-chat, deepseek-reasoner',
  qwen: 'e.g. qwen-plus, qwen-max, qwq-32b',
  ollama: 'e.g. llama3, deepseek-r1:7b',
  openai_compatible: 'model id served by your endpoint',
  vllm: 'model id served by your vLLM server',
};

const ROLE_LABELS = {
  orchestration: 'Orchestration',
  generation: 'Generation',
  verification: 'Verification',
  chat: 'Chat (answer generation)',
  self_correction: 'Self-correction',
  extraction: 'Extraction',
};
const ROLE_DESCRIPTIONS = {
  orchestration: 'Plans and routes agent steps. Needs strong tool/function calling.',
  generation: 'Writes agent answers from retrieved context.',
  verification: 'Checks agent answers for grounding.',
  chat: 'Classic RAG answer generation.',
  self_correction: 'Verifies classic-pipeline answers.',
  extraction: 'Entity, metadata, and query-entity extraction.',
};
const AGENT_ROLES = ['orchestration', 'generation', 'verification'];
const PIPELINE_ROLES = ['chat', 'self_correction', 'extraction'];

export default function ModelsSection() {
  const { modelConfig, thinking, loading, loadModelConfig, setThinking } =
    useSettingsStore();

  useEffect(() => {
    loadModelConfig();
  }, [loadModelConfig]);

  if (loading.models && !modelConfig) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="text-violet-500 animate-spin" />
      </div>
    );
  }
  if (!modelConfig) return null;

  const {
    roles,
    providers,
    supported_providers,
    llm_roles,
    deployment_mode,
    db_enabled,
  } = modelConfig;
  const airGapped = deployment_mode === 'air-gapped';
  const readOnly = !db_enabled;

  const availableProviders = supported_providers.filter(
    (p) => !airGapped || LOCAL_PROVIDERS.has(p)
  );

  const agent = AGENT_ROLES.filter((r) => llm_roles.includes(r));
  const pipeline = PIPELINE_ROLES.filter((r) => llm_roles.includes(r));

  return (
    <div className="space-y-8 animate-fade-in">
      {readOnly && (
        <Banner
          icon={Lock}
          tone="warn"
          text="DB-backed model config is disabled (model_config_db_enabled=False). Models are shown read-only and resolve from environment defaults."
        />
      )}
      {airGapped && (
        <Banner
          icon={AlertTriangle}
          tone="info"
          text="Air-gapped deployment — only local providers (Ollama, OpenAI-compatible, vLLM) are selectable."
        />
      )}

      <RoleGroup
        title="Agent layer"
        roles={agent}
        roles_cfg={roles}
        providers={providers}
        availableProviders={availableProviders}
        readOnly={readOnly}
      />
      <RoleGroup
        title="Classic pipeline"
        roles={pipeline}
        roles_cfg={roles}
        providers={providers}
        availableProviders={availableProviders}
        readOnly={readOnly}
      />

      {/* Reasoning / extended thinking */}
      <section className="card p-6">
        <div className="flex items-center gap-2 mb-1">
          <Brain size={16} className="text-violet-500" />
          <h3 className="font-semibold text-ink-900">Extended thinking</h3>
        </div>
        <p className="text-sm text-ink-600 mb-4">
          {thinking?.note ||
            'Applies to Anthropic models only. Other providers surface chain-of-thought automatically.'}
        </p>
        <div className="flex items-center justify-between">
          <div className="pr-6">
            <p className="text-sm font-medium text-ink-900">
              Enable Anthropic extended thinking
            </p>
            <p className="text-xs text-ink-600 mt-0.5">
              {thinking
                ? `Currently ${thinking.enabled ? 'on' : 'off'} (source: ${thinking.source}${
                    thinking.budget_tokens ? `, budget ${thinking.budget_tokens} tokens` : ''
                  }).`
                : 'Loading…'}
            </p>
          </div>
          <Switch
            checked={!!thinking?.enabled}
            disabled={readOnly || !thinking}
            onChange={(v) => setThinking(v)}
            label="Enable Anthropic extended thinking"
          />
        </div>
      </section>
    </div>
  );
}

function RoleGroup({ title, roles, roles_cfg, providers, availableProviders, readOnly }) {
  if (!roles.length) return null;
  return (
    <section>
      <h3 className="font-semibold text-ink-900 mb-3">{title}</h3>
      <div className="space-y-4">
        {roles.map((role) => (
          <RoleCard
            key={role}
            role={role}
            config={roles_cfg[role]}
            providers={providers}
            availableProviders={availableProviders}
            readOnly={readOnly}
          />
        ))}
      </div>
    </section>
  );
}

function RoleCard({ role, config, providers, availableProviders, readOnly }) {
  const { testRole, saveRole, savingRole } = useSettingsStore();
  const [draft, setDraft] = useState({
    provider: config?.provider || '',
    model: config?.model || '',
    base_url: config?.base_url || '',
    temperature: config?.params?.temperature ?? '',
    max_tokens: config?.params?.max_tokens ?? '',
  });
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);

  // Re-seed when the upstream config changes (after a save reload).
  useEffect(() => {
    setDraft({
      provider: config?.provider || '',
      model: config?.model || '',
      base_url: config?.base_url || '',
      temperature: config?.params?.temperature ?? '',
      max_tokens: config?.params?.max_tokens ?? '',
    });
    setTestResult(null);
  }, [config?.provider, config?.model, config?.base_url]);

  const saving = savingRole === role;
  const needsBaseUrl = BASEURL_REQUIRED.has(draft.provider);
  const showBaseUrl = needsBaseUrl || BASEURL_OPTIONAL.has(draft.provider);
  const providerAvail = providers[draft.provider];

  const dirty =
    draft.provider !== (config?.provider || '') ||
    draft.model !== (config?.model || '') ||
    (draft.base_url || '') !== (config?.base_url || '') ||
    String(draft.temperature) !== String(config?.params?.temperature ?? '') ||
    String(draft.max_tokens) !== String(config?.params?.max_tokens ?? '');

  const valid =
    draft.provider && draft.model.trim() && (!needsBaseUrl || draft.base_url.trim());

  const buildPayload = () => {
    const params = {};
    if (draft.temperature !== '') params.temperature = Number(draft.temperature);
    if (draft.max_tokens !== '') params.max_tokens = Number(draft.max_tokens);
    return {
      provider: draft.provider,
      model: draft.model.trim(),
      base_url: showBaseUrl && draft.base_url.trim() ? draft.base_url.trim() : null,
      ...(Object.keys(params).length ? { params } : {}),
    };
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    const { provider, model, base_url } = buildPayload();
    const res = await testRole(role, { provider, model, base_url });
    setTestResult(res);
    setTesting(false);
  };

  const handleSave = async () => {
    const ok = await saveRole(role, buildPayload());
    if (ok) setTestResult(null);
  };

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-ink-900">{ROLE_LABELS[role] || role}</p>
            <SourceBadge source={config?.source} />
          </div>
          <p className="text-xs text-ink-600 mt-0.5">{ROLE_DESCRIPTIONS[role]}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-ink-700 mb-1">Provider</label>
          <select
            value={draft.provider}
            disabled={readOnly}
            onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
            className="input !py-2 text-sm"
          >
            {!availableProviders.includes(draft.provider) && draft.provider && (
              <option value={draft.provider}>{draft.provider}</option>
            )}
            {availableProviders.map((p) => {
              const a = providers[p];
              const unavailable = a && !a.available;
              return (
                <option key={p} value={p}>
                  {p}
                  {unavailable ? ' — no key' : a?.byok ? ' — BYOK' : ''}
                </option>
              );
            })}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-ink-700 mb-1">Model</label>
          <input
            value={draft.model}
            disabled={readOnly}
            onChange={(e) => setDraft({ ...draft, model: e.target.value })}
            placeholder={MODEL_HINTS[draft.provider] || 'model id'}
            className="input !py-2 text-sm"
          />
        </div>

        {showBaseUrl && (
          <div className="col-span-2">
            <label className="block text-xs font-medium text-ink-700 mb-1">
              Base URL {needsBaseUrl ? '(required)' : '(optional)'}
            </label>
            <input
              value={draft.base_url}
              disabled={readOnly}
              onChange={(e) => setDraft({ ...draft, base_url: e.target.value })}
              placeholder="https://host:port/v1"
              className="input !py-2 text-sm"
            />
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-ink-700 mb-1">
            Temperature <span className="text-ink-500">(optional)</span>
          </label>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={draft.temperature}
            disabled={readOnly}
            onChange={(e) => setDraft({ ...draft, temperature: e.target.value })}
            placeholder="default"
            className="input !py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-700 mb-1">
            Max tokens <span className="text-ink-500">(optional)</span>
          </label>
          <input
            type="number"
            min="1"
            value={draft.max_tokens}
            disabled={readOnly}
            onChange={(e) => setDraft({ ...draft, max_tokens: e.target.value })}
            placeholder="default"
            className="input !py-2 text-sm"
          />
        </div>
      </div>

      {/* Availability hint */}
      {providerAvail && !providerAvail.available && (
        <p className="mt-3 text-xs text-terra-500 flex items-center gap-1">
          <AlertTriangle size={12} /> No usable key for {draft.provider}. Add one in API Keys,
          or pick another provider.
        </p>
      )}
      {providerAvail?.available && (
        <p className="mt-3 text-xs text-ink-600">
          Key source: <span className="font-medium">{providerAvail.key_source}</span>
          {providerAvail.hint ? ` (•••• ${providerAvail.hint})` : ''}
        </p>
      )}

      {/* Test result */}
      {testResult && (
        <div
          className={`mt-3 flex items-start gap-2 p-3 rounded-xl text-xs ${
            testResult.ok
              ? 'bg-forest-500/10 text-forest-500'
              : 'bg-terra-500/10 text-terra-500'
          }`}
        >
          {testResult.ok ? (
            <CheckCircle2 size={14} className="flex-shrink-0 mt-0.5" />
          ) : (
            <XCircle size={14} className="flex-shrink-0 mt-0.5" />
          )}
          <span className="break-words">
            {testResult.ok
              ? `OK — ${testResult.latency_ms}ms${
                  testResult.sample ? ` · "${testResult.sample}"` : ''
                }`
              : testResult.error}
          </span>
        </div>
      )}

      {!readOnly && (
        <div className="flex items-center justify-end gap-2 mt-4">
          <button
            onClick={handleTest}
            disabled={!valid || testing || saving}
            className="btn-secondary text-sm !py-2"
          >
            {testing ? <Loader2 size={15} className="animate-spin" /> : <Zap size={15} />}
            Test
          </button>
          <button
            onClick={handleSave}
            disabled={!valid || !dirty || saving}
            className="btn-primary text-sm !py-2"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : null}
            Save
          </button>
        </div>
      )}
    </div>
  );
}

function SourceBadge({ source }) {
  if (source === 'db') return <span className="badge-info text-[10px]">custom</span>;
  return <span className="badge-warning text-[10px]">env default</span>;
}

function Banner({ icon: Icon, text, tone = 'info' }) {
  const tones = {
    info: 'bg-violet-500/10 text-violet-600 border-violet-500/20',
    warn: 'bg-sand-500/10 text-sand-600 border-sand-500/20',
  };
  return (
    <div className={`flex items-start gap-2 p-3 rounded-xl border text-sm ${tones[tone]}`}>
      <Icon size={16} className="flex-shrink-0 mt-0.5" />
      <span>{text}</span>
    </div>
  );
}
