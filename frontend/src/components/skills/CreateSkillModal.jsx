import { useState } from 'react';
import { Loader2, AlertCircle } from 'lucide-react';
import Modal from '../ui/Modal';
import * as skillService from '../../services/skillService';

/**
 * Create a skill file — either from structured fields or by pasting a full SKILL.md
 * (Anthropic Agent-Skills format). The name must be lowercase-hyphen, ≤64 chars,
 * and may not contain "claude"/"anthropic" (validated server-side).
 */
export default function CreateSkillModal({ onClose, onCreated }) {
  const [mode, setMode] = useState('fields'); // 'fields' | 'markdown'
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [kind, setKind] = useState('assistant');
  const [body, setBody] = useState('');
  const [markdown, setMarkdown] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      const payload =
        mode === 'markdown'
          ? { markdown }
          : { name: name.trim(), description: description.trim(), kind, body };
      const created = await skillService.createSkill(payload);
      onCreated?.(created);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not create the skill.');
      setBusy(false);
    }
  };

  return (
    <Modal
      title="New skill file"
      onClose={onClose}
      maxWidth="max-w-xl"
      footer={
        <>
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={busy} className="btn-primary text-sm">
            {busy ? <><Loader2 size={15} className="animate-spin" /> Creating…</> : 'Create'}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {error && (
          <div className="flex items-start gap-2 text-terra-500 text-sm bg-terra-500/5 border border-terra-500/20 rounded-lg p-2.5">
            <AlertCircle size={15} className="flex-shrink-0 mt-0.5" /><span>{error}</span>
          </div>
        )}

        {/* Mode toggle */}
        <div className="inline-flex rounded-lg border border-cream-200 p-0.5 bg-cream-50">
          {['fields', 'markdown'].map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                mode === m ? 'bg-white text-amber-900 shadow-warm-sm' : 'text-ink-600 hover:text-ink-900'}`}
            >
              {m === 'fields' ? 'Fields' : 'Paste SKILL.md'}
            </button>
          ))}
        </div>

        {mode === 'fields' ? (
          <>
            <Field label="Name (lowercase-hyphen, ≤64 chars)">
              <input className="input font-mono text-xs" value={name} onChange={(e) => setName(e.target.value)} placeholder="marine-research-assistant" />
            </Field>
            <Field label="Description (third-person — what it does and when)">
              <textarea className="input" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
            <Field label="Kind">
              <input className="input" value={kind} onChange={(e) => setKind(e.target.value)} placeholder="assistant" />
            </Field>
            <Field label="Instructions (human intent — Skill Sync never edits this)">
              <textarea className="input font-mono text-xs" rows={6} value={body} onChange={(e) => setBody(e.target.value)} />
            </Field>
          </>
        ) : (
          <Field label="SKILL.md">
            <textarea
              className="input font-mono text-xs"
              rows={14}
              value={markdown}
              onChange={(e) => setMarkdown(e.target.value)}
              placeholder={'---\nname: my-skill\ndescription: …\n---\n\n# Instructions\n…'}
            />
          </Field>
        )}
      </div>
    </Modal>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="block text-xs text-sand-500 mb-1">{label}</span>
      {children}
    </label>
  );
}
