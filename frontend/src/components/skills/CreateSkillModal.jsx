import { useState } from 'react';
import { Loader2, AlertCircle } from 'lucide-react';
import Modal from '../ui/Modal';
import * as skillService from '../../services/skillService';

/**
 * Create OR edit a skill file — from structured fields or by pasting a full SKILL.md
 * (Anthropic Agent-Skills format). Pass `skill` to edit an existing one (name is locked —
 * it's the trigger identity). The name must be lowercase-hyphen, ≤64 chars, and may not
 * contain "claude"/"anthropic" (validated server-side).
 */
export default function CreateSkillModal({ onClose, onCreated, skill = null }) {
  const editing = !!skill;
  const [mode, setMode] = useState('fields'); // 'fields' | 'markdown'
  const [name, setName] = useState(skill?.name || '');
  const [description, setDescription] = useState(skill?.description || '');
  const [kind, setKind] = useState(skill?.kind || 'assistant');
  const [body, setBody] = useState(skill?.body || '');
  const [markdown, setMarkdown] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      let saved;
      if (editing) {
        const payload = mode === 'markdown' ? { markdown } : { description: description.trim(), body };
        saved = await skillService.updateSkill(skill.id, payload);
      } else {
        const payload =
          mode === 'markdown'
            ? { markdown }
            : { name: name.trim(), description: description.trim(), kind, body };
        saved = await skillService.createSkill(payload);
      }
      onCreated?.(saved);
    } catch (e) {
      setError(e.response?.data?.detail || `Could not ${editing ? 'save' : 'create'} the skill.`);
      setBusy(false);
    }
  };

  return (
    <Modal
      title={editing ? `Edit skill · ${skill.name}` : 'New skill file'}
      onClose={onClose}
      maxWidth="max-w-xl"
      footer={
        <>
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={busy} className="btn-primary text-sm">
            {busy
              ? <><Loader2 size={15} className="animate-spin" /> {editing ? 'Saving…' : 'Creating…'}</>
              : (editing ? 'Save changes' : 'Create')}
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
            <Field label={editing ? 'Name (cannot be changed)' : 'Name (lowercase-hyphen, ≤64 chars)'}>
              <input
                className="input font-mono text-xs disabled:opacity-60"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={editing}
                placeholder="marine-research-assistant"
              />
            </Field>
            <Field label="Description (third-person — what it does and when)">
              <textarea className="input" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
            {!editing && (
              <Field label="Kind">
                <input className="input" value={kind} onChange={(e) => setKind(e.target.value)} placeholder="assistant" />
              </Field>
            )}
            <Field label="Instructions (human intent — Skill Sync never edits this)">
              <textarea className="input font-mono text-xs" rows={editing ? 14 : 6} value={body} onChange={(e) => setBody(e.target.value)} />
            </Field>
          </>
        ) : (
          <Field label={editing ? 'SKILL.md (replaces body/description; name must match)' : 'SKILL.md'}>
            <textarea
              className="input font-mono text-xs"
              rows={16}
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
