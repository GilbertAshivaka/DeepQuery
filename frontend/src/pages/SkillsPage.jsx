import { useEffect, useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import * as skillService from '../services/skillService';
import { useAuthStore } from '../store/authStore';
import CreateSkillModal from '../components/skills/CreateSkillModal';
import SkillDetailPanel from '../components/skills/SkillDetailPanel';
import SkillDiffReview from '../components/skills/SkillDiffReview';
import {
  ScrollText, Plus, Search, Loader2, Archive, GitBranch, CheckCircle2, AlertCircle, X, Trash2,
} from 'lucide-react';

export default function SkillsPage() {
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin');
  const [tab, setTab] = useState('files');
  const [skills, setSkills] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  const [detailId, setDetailId] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [notice, setNotice] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const loadSkills = async () => {
    try { setSkills(await skillService.listSkills()); } catch { /* ignore */ }
  };
  const loadProposals = async () => {
    try { setProposals(await skillService.listProposals('pending')); } catch { /* ignore */ }
  };

  useEffect(() => {
    (async () => {
      setLoading(true);
      await Promise.all([loadSkills(), loadProposals()]);
      setLoading(false);
    })();
  }, []);

  const skillName = (id) => skills.find((s) => s.id === id)?.name;

  const onDelete = async (s) => {
    if (!window.confirm(`Delete the skill “${s.name}”? This removes it and its version history, and can't be undone.`)) return;
    setBusyId(s.id);
    try {
      await skillService.deleteSkill(s.id);
      if (detailId === s.id) setDetailId(null);
      setNotice({ type: 'success', message: `Skill “${s.name}” deleted.` });
      await loadSkills();
    } catch (e) {
      setNotice({ type: 'error', message: e.response?.data?.detail || 'Could not delete the skill.' });
    } finally { setBusyId(null); }
  };

  const onApprove = async (p) => {
    setBusyId(p.id);
    try {
      await skillService.approveProposal(p.id);
      setNotice({ type: 'success', message: 'Proposal approved — a new skill version was written.' });
      await Promise.all([loadProposals(), loadSkills()]);
    } catch (e) {
      setNotice({ type: 'error', message: e.response?.data?.detail || 'Could not approve the proposal.' });
    } finally { setBusyId(null); }
  };

  const onReject = async (p) => {
    setBusyId(p.id);
    try {
      await skillService.rejectProposal(p.id);
      setNotice({ type: 'success', message: 'Proposal rejected.' });
      await loadProposals();
    } catch (e) {
      setNotice({ type: 'error', message: e.response?.data?.detail || 'Could not reject the proposal.' });
    } finally { setBusyId(null); }
  };

  const filteredSkills = !query.trim()
    ? skills
    : skills.filter((s) => `${s.name} ${s.description}`.toLowerCase().includes(query.toLowerCase()));

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center justify-between px-4 md:px-8 h-14 border-b border-cream-200 flex-shrink-0">
          <div className="flex items-center gap-2">
            <ScrollText size={18} className="text-amber-900" />
            <h2 className="font-semibold text-ink-900 text-sm">Skills</h2>
          </div>
          {tab === 'files' && (
            <button onClick={() => setShowCreate(true)} className="btn-primary !py-1.5 !px-3 text-xs">
              <Plus size={15} /> New skill
            </button>
          )}
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 px-4 md:px-8 pt-3 border-b border-cream-200">
          <TabButton active={tab === 'files'} onClick={() => setTab('files')}>Skill files</TabButton>
          <TabButton active={tab === 'proposals'} onClick={() => setTab('proposals')}>
            <span className="inline-flex items-center gap-1.5">
              Proposals
              {proposals.length > 0 && (
                <span className="px-1.5 py-px rounded-full bg-amber-900 text-white text-[10px]">{proposals.length}</span>
              )}
            </span>
          </TabButton>
        </div>

        {/* Notice */}
        {notice && (
          <div className={`mx-4 md:mx-8 mt-3 flex items-center gap-2 text-sm rounded-lg px-3 py-2 ${
            notice.type === 'success' ? 'bg-forest-500/10 text-forest-500' : 'bg-terra-500/10 text-terra-500'}`}>
            {notice.type === 'success' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
            <span className="flex-1">{notice.message}</span>
            <button onClick={() => setNotice(null)} className="hover:opacity-70"><X size={14} /></button>
          </div>
        )}

        {/* Search (files tab) */}
        {tab === 'files' && (
          <div className="px-4 md:px-8 pt-4">
            <div className="relative max-w-md">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-cream-400" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search skills…" className="input !pl-9" />
            </div>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-16"><Loader2 size={22} className="text-violet-500 animate-spin" /></div>
          ) : tab === 'files' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {filteredSkills.length ? filteredSkills.map((s) => (
                <div
                  key={s.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setDetailId(s.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setDetailId(s.id); } }}
                  className={`group relative card p-4 text-left hover:shadow-warm transition-all cursor-pointer ${detailId === s.id ? 'ring-2 ring-violet-500/30' : ''}`}
                >
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <h3 className="text-sm font-semibold text-ink-900 truncate font-mono">{s.name}</h3>
                    {s.is_archived && <Archive size={13} className="text-sand-500 flex-shrink-0" title="Archived" />}
                  </div>
                  {s.description && <p className="text-xs text-ink-600 leading-snug line-clamp-3">{s.description}</p>}
                  <div className="flex items-center gap-2 mt-2.5">
                    <span className="badge bg-cream-200 text-ink-600">{s.kind}</span>
                    <span className="inline-flex items-center gap-1 text-[10px] text-sand-500">
                      <GitBranch size={10} /> v{s.current_version}
                    </span>
                  </div>
                  {/* Admin-only delete — revealed on hover */}
                  {isAdmin && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onDelete(s); }}
                      disabled={busyId === s.id}
                      className="absolute top-2 right-2 p-1.5 rounded-md text-ink-500 opacity-0 group-hover:opacity-100 focus:opacity-100
                        hover:bg-terra-500/10 hover:text-terra-500 transition-all"
                      title="Delete skill"
                    >
                      {busyId === s.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    </button>
                  )}
                </div>
              )) : <EmptyNote>No skill files yet. Use “New skill” to create one.</EmptyNote>}
            </div>
          ) : (
            <div className="space-y-3 max-w-2xl">
              {proposals.length ? proposals.map((p) => (
                <SkillDiffReview
                  key={p.id}
                  proposal={p}
                  skillName={skillName(p.skill_id)}
                  busy={busyId === p.id}
                  onApprove={() => onApprove(p)}
                  onReject={() => onReject(p)}
                  onViewSkill={() => { setTab('files'); setDetailId(p.skill_id); }}
                />
              )) : <EmptyNote>No pending proposals. The Skill Sync Agent opens these when a source document changes.</EmptyNote>}
            </div>
          )}
        </div>
      </div>

      {/* Detail side panel */}
      <AnimatePresence>
        {detailId && (
          <SkillDetailPanel
            skillId={detailId}
            onClose={() => setDetailId(null)}
            onChanged={loadSkills}
          />
        )}
      </AnimatePresence>

      {/* Create modal */}
      <AnimatePresence>
        {showCreate && (
          <CreateSkillModal
            onClose={() => setShowCreate(false)}
            onCreated={async (created) => {
              setShowCreate(false);
              setNotice({ type: 'success', message: `Skill “${created.name}” created.` });
              await loadSkills();
              setDetailId(created.id);
            }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
        active ? 'border-amber-900 text-amber-900' : 'border-transparent text-ink-600 hover:text-ink-900'}`}
    >
      {children}
    </button>
  );
}

function EmptyNote({ children }) {
  return <p className="col-span-full text-sm text-sand-500 py-8 text-center max-w-md mx-auto">{children}</p>;
}
