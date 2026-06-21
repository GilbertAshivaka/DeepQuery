import { useEffect, useState } from 'react';
import {
  X, Loader2, AlertCircle, User, Database, Link2, History, RotateCcw, Bot, Pencil,
} from 'lucide-react';
import * as skillService from '../../services/skillService';
import CreateSkillModal from './CreateSkillModal';

/**
 * Skill file detail (UI guide §13). Visually separates the two content kinds —
 * human intent (the body, off-limits to Skill Sync) vs corpus-derived fact sections
 * (maintained by Skill Sync) — and shows declared dependencies + attributable,
 * reversible version history.
 */
function attribution(triggeredBy) {
  const t = triggeredBy || '';
  if (t === 'create') return { label: 'Created', sync: false };
  if (t.startsWith('admin:')) return { label: 'Edited by an admin', sync: false };
  if (t.startsWith('skill_sync:doc:')) return { label: `Skill Sync · doc ${t.slice('skill_sync:doc:'.length)}`, sync: true };
  if (t.startsWith('rollback:v')) return { label: `Rolled back to ${t.slice('rollback:'.length)}`, sync: false };
  return { label: t || 'Update', sync: false };
}

function factEntries(factSections) {
  if (!factSections) return [];
  if (Array.isArray(factSections)) {
    return factSections.map((f, i) => (typeof f === 'string' ? { name: `Section ${i + 1}`, content: f } : { name: f.name || `Section ${i + 1}`, content: f.content ?? '' }));
  }
  return Object.entries(factSections).map(([name, content]) => ({ name, content: String(content) }));
}

export default function SkillDetailPanel({ skillId, onClose, onChanged }) {
  const [skill, setSkill] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [rollingBack, setRollingBack] = useState(null);
  const [editing, setEditing] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setSkill(await skillService.getSkill(skillId));
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load this skill.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [skillId]);

  const doRollback = async (versionNo) => {
    setRollingBack(versionNo);
    try {
      await skillService.rollbackSkill(skillId, versionNo);
      await load();
      onChanged?.();
    } catch { /* ignore */ } finally { setRollingBack(null); }
  };

  const facts = factEntries(skill?.fact_sections);

  return (
    <div className="w-96 flex-shrink-0 border-l border-cream-200 bg-white flex flex-col h-full animate-slide-right">
      <div className="flex items-center justify-between px-5 h-14 border-b border-cream-200 flex-shrink-0">
        <div className="min-w-0">
          <h3 className="font-semibold text-ink-900 text-sm truncate font-mono">{skill?.name || 'Skill'}</h3>
          {skill && <p className="text-[11px] text-sand-500">{skill.kind} · v{skill.current_version}</p>}
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {skill && (
            <button onClick={() => setEditing(true)} className="btn-ghost !p-1" title="Edit skill">
              <Pencil size={15} />
            </button>
          )}
          <button onClick={onClose} className="btn-ghost !p-1" title="Close"><X size={18} /></button>
        </div>
      </div>

      {editing && skill && (
        <CreateSkillModal
          skill={skill}
          onClose={() => setEditing(false)}
          onCreated={async () => { setEditing(false); await load(); onChanged?.(); }}
        />
      )}

      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {loading ? (
          <div className="flex items-center justify-center py-12"><Loader2 size={20} className="text-violet-500 animate-spin" /></div>
        ) : error ? (
          <div className="flex flex-col items-center text-center py-8">
            <AlertCircle size={26} className="text-terra-500 mb-2" />
            <p className="text-sm text-terra-500">{error}</p>
          </div>
        ) : skill ? (
          <>
            {skill.description && <p className="text-xs text-ink-600 leading-relaxed">{skill.description}</p>}

            {/* Human intent — off-limits to Skill Sync */}
            <Section icon={User} label="Human intent" accent="violet" note="Skill Sync never edits this">
              {skill.body ? (
                <pre className="text-xs text-ink-700 whitespace-pre-wrap font-sans leading-relaxed">{skill.body}</pre>
              ) : <Empty>No instructions yet.</Empty>}
            </Section>

            {/* Corpus-derived facts — maintained by Skill Sync */}
            <Section icon={Database} label="Corpus facts" accent="amber" note="Maintained by Skill Sync">
              {facts.length ? (
                <div className="space-y-2">
                  {facts.map((f) => (
                    <div key={f.name} className="rounded-lg border border-cream-200 bg-cream-50/60 px-3 py-2">
                      <p className="text-[11px] font-medium text-amber-900 mb-1 font-mono">{f.name}</p>
                      <pre className="text-xs text-ink-700 whitespace-pre-wrap font-sans leading-relaxed">{f.content}</pre>
                    </div>
                  ))}
                </div>
              ) : <Empty>No corpus-derived facts.</Empty>}
            </Section>

            {/* Dependencies */}
            <Section icon={Link2} label="Dependencies">
              {skill.dependencies?.length ? (
                <div className="space-y-1.5">
                  {skill.dependencies.map((d, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="badge bg-cream-200 text-ink-600 capitalize">{d.dep_type}</span>
                      <span className="text-ink-700 font-mono truncate flex-1" title={d.dep_ref}>{d.dep_ref_name || d.dep_ref}</span>
                      <span className={`badge ${d.declared ? 'bg-forest-500/10 text-forest-500' : 'bg-sand-500/10 text-sand-600'}`}>
                        {d.declared ? 'explicit' : 'inferred'}
                      </span>
                    </div>
                  ))}
                </div>
              ) : <Empty>No declared dependencies.</Empty>}
            </Section>

            {/* Version history */}
            <Section icon={History} label="Version history">
              <div className="space-y-1.5">
                {(skill.versions || []).slice().reverse().map((v) => {
                  const a = attribution(v.triggered_by);
                  const isCurrent = v.version_no === skill.current_version;
                  return (
                    <div key={v.version_no} className="flex items-start gap-2 rounded-lg border border-cream-200 px-3 py-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-semibold text-ink-800">v{v.version_no}</span>
                          {isCurrent && <span className="badge-info">current</span>}
                          {a.sync && <Bot size={11} className="text-amber-700" />}
                        </div>
                        <p className="text-[11px] text-ink-600">{a.label}</p>
                        {v.change_summary && <p className="text-[11px] text-sand-500 truncate">{v.change_summary}</p>}
                      </div>
                      {!isCurrent && (
                        <button
                          onClick={() => doRollback(v.version_no)}
                          disabled={rollingBack === v.version_no}
                          className="btn-ghost !p-1 text-ink-600"
                          title={`Roll back to v${v.version_no}`}
                        >
                          {rollingBack === v.version_no ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </Section>
          </>
        ) : null}
      </div>
    </div>
  );
}

function Section({ icon: Icon, label, note, accent, children }) {
  const accentCls = accent === 'violet' ? 'text-violet-500' : accent === 'amber' ? 'text-amber-700' : 'text-sand-500';
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={14} className={accentCls} />
        <h4 className="text-xs font-semibold text-ink-800 uppercase tracking-wide">{label}</h4>
        {note && <span className="text-[10px] text-sand-500 italic ml-auto">{note}</span>}
      </div>
      {children}
    </div>
  );
}

function Empty({ children }) {
  return <p className="text-xs text-sand-500 italic">{children}</p>;
}
