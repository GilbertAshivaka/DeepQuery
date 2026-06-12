import { Loader2, FileText, ShieldCheck, AlertTriangle, Check, X, ExternalLink } from 'lucide-react';

/**
 * Skill-diff review (UI guide §12). Shows the proposed change to one fact section as
 * a before/after diff (restrained green/rust, not harsh red/green), the document
 * change that triggered it, and an explicit-vs-inferred confidence cue so admins
 * scrutinize low-confidence proposals harder. Approve writes a new reversible version.
 */

function lineDiff(oldText, newText) {
  const a = (oldText || '').split('\n');
  const b = (newText || '').split('\n');
  const n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const rows = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { rows.push({ type: 'same', text: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { rows.push({ type: 'del', text: a[i] }); i++; }
    else { rows.push({ type: 'add', text: b[j] }); j++; }
  }
  while (i < n) rows.push({ type: 'del', text: a[i++] });
  while (j < m) rows.push({ type: 'add', text: b[j++] });
  return rows;
}

const ROW = {
  same: { cls: 'text-ink-600', prefix: ' ' },
  add: { cls: 'bg-forest-500/10 text-forest-600', prefix: '+' },
  del: { cls: 'bg-amber-900/8 text-amber-900', prefix: '−' },
};

export default function SkillDiffReview({ proposal, skillName, busy, resolved, onApprove, onReject, onViewSkill }) {
  const inferred = proposal.confidence === 'inferred';
  const rows = lineDiff(proposal.old_content, proposal.new_content);

  return (
    <div className="card p-4 space-y-3">
      {/* Header: skill + fact section + confidence */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <button onClick={onViewSkill} className="text-sm font-semibold text-ink-900 hover:text-amber-900 inline-flex items-center gap-1 font-mono">
            {skillName || proposal.skill_id}
            <ExternalLink size={12} className="text-sand-500" />
          </button>
          <p className="text-[11px] text-sand-500">
            fact section: <span className="font-mono">{proposal.fact_section}</span>
          </p>
        </div>
        {inferred ? (
          <span className="badge bg-sand-500/15 text-sand-600 gap-1 flex-shrink-0">
            <AlertTriangle size={11} /> inferred · review carefully
          </span>
        ) : (
          <span className="badge bg-forest-500/10 text-forest-500 gap-1 flex-shrink-0">
            <ShieldCheck size={11} /> explicit
          </span>
        )}
      </div>

      {/* The diff */}
      <div className="rounded-lg border border-cream-200 overflow-hidden">
        <pre className="text-xs font-mono leading-relaxed overflow-x-auto">
          {rows.map((r, i) => (
            <div key={i} className={`px-3 py-px ${ROW[r.type].cls}`}>
              <span className="select-none opacity-50 mr-2">{ROW[r.type].prefix}</span>
              {r.text || ' '}
            </div>
          ))}
        </pre>
      </div>

      {/* The trigger — what changed in the corpus */}
      <div className="rounded-lg bg-cream-50/70 border border-cream-200 px-3 py-2">
        <div className="flex items-center gap-1.5 mb-1">
          <FileText size={12} className="text-sand-500" />
          <span className="text-[11px] font-medium text-ink-700">Triggered by a document change</span>
        </div>
        {proposal.trigger_summary && <p className="text-xs text-ink-600 leading-snug">{proposal.trigger_summary}</p>}
        {proposal.trigger_document_id && (
          <p className="text-[10px] text-sand-500 font-mono mt-0.5">doc: {proposal.trigger_document_id}</p>
        )}
      </div>

      {/* Controls / resolved state */}
      {resolved ? (
        <p className={`text-xs font-medium ${proposal.status === 'approved' ? 'text-forest-500' : 'text-ink-600'}`}>
          {proposal.status === 'approved' ? 'Approved — new version written.' : 'Rejected — nothing changed.'}
        </p>
      ) : (
        <div className="flex items-center gap-2">
          <button onClick={onApprove} disabled={busy} className="btn-primary !py-1.5 !px-3 text-xs">
            {busy ? <Loader2 size={13} className="animate-spin" /> : <><Check size={13} /> Approve</>}
          </button>
          <button onClick={onReject} disabled={busy} className="btn-secondary !py-1.5 !px-3 text-xs">
            <X size={13} /> Reject
          </button>
        </div>
      )}
    </div>
  );
}
