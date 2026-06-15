import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertCircle, Copy, Check, ShieldQuestion, Loader2, FileText, Image as ImageIcon,
  CheckCircle2, XCircle, AlertTriangle, Sparkles, HelpCircle, Send, Link2,
} from 'lucide-react';
import SelfCorrectionBadge from '../chat/SelfCorrectionBadge';
import PlanChecklist from './PlanChecklist';
import ThinkingPanel from './ThinkingPanel';
import CitationChips from './CitationChips';
import AnswerMarkdown from './AnswerMarkdown';

export default function AgentMessage({
  turn,
  isStreaming,
  onDocumentClick,
  onAttachmentClick,
  onResolveApproval,
  onResolveBatch,
  onAnswerQuestion,
}) {
  const isUser = turn.role === 'user';
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(turn.content);
      } else {
        const ta = document.createElement('textarea');
        ta.value = turn.content;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className="flex justify-end"
      >
        <div className="inline-block text-left rounded-2xl rounded-br-md px-4 py-3 bg-violet-500/20 text-ink-900 shadow-warm-sm max-w-[75%]">
          {/* Attachment chips on the user's turn (rehydrated from history) */}
          {turn.attachments?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {turn.attachments.map((a) => (
                <button
                  key={a.id}
                  onClick={() => onAttachmentClick?.(a)}
                  className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-md bg-white/60 border border-white/40 text-ink-700 hover:bg-white/80 transition-all"
                >
                  {a.kind === 'image' ? <ImageIcon size={11} /> : <FileText size={11} />}
                  <span className="truncate max-w-[120px]">{a.filename}</span>
                </button>
              ))}
            </div>
          )}
          <p className="text-sm whitespace-pre-wrap">{turn.content}</p>
        </div>
      </motion.div>
    );
  }

  const verificationOutcome = turn.verification?.outcome;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="w-full"
    >
      {/* Loaded playbooks (skill_loaded) — quiet, above the plan */}
      <SkillChips skills={turn.skills} />

      {/* Plan checklist (states by color + icon, no labels) */}
      <PlanChecklist steps={turn.plan} />

      {/* Anthropic-style CoT timeline (auto-collapses when done) */}
      <ThinkingPanel trace={turn.trace} isStreaming={isStreaming} />

      {/* Answer */}
      {turn.isError ? (
        <div className="flex items-start gap-2 text-terra-500 text-sm">
          <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
          <p>{turn.content}</p>
        </div>
      ) : turn.content ? (
        <div className="relative">
          <AnswerMarkdown
            content={turn.content}
            citations={turn.citations}
            onDocumentClick={onDocumentClick}
            onAttachmentClick={onAttachmentClick}
          />
          {isStreaming && (
            <span className="inline-flex gap-0.5 ml-1 align-middle">
              <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" style={{ animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" style={{ animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" style={{ animationDelay: '300ms' }} />
            </span>
          )}
        </div>
      ) : null}

      {/* Citations — four source kinds, grouped */}
      <CitationChips
        citations={turn.citations}
        onDocumentClick={onDocumentClick}
        onAttachmentClick={onAttachmentClick}
      />

      {/* Single-action approval gate — minimal inline card, task-specific label. */}
      {turn.approval && (
        <ApprovalGate approval={turn.approval} onResolve={onResolveApproval} />
      )}

      {/* Multi-action batch gate — one approval, per-action toggle. */}
      {turn.batch && (
        <BatchApprovalGate batch={turn.batch} threadId={turn.threadId} onResolve={onResolveBatch} />
      )}

      {/* The agent asked a question — inline answer input. */}
      {turn.question && (
        <QuestionGate question={turn.question} threadId={turn.threadId} onAnswer={onAnswerQuestion} />
      )}

      {/* Footer: verification badge + copy */}
      {!isStreaming && turn.content && !turn.isError && (
        <div className="mt-1.5 flex items-center gap-2">
          {verificationOutcome && <SelfCorrectionBadge status={verificationOutcome} />}
          <button
            onClick={handleCopy}
            className="inline-flex items-center gap-1 px-2 py-1 text-[11px] text-ink-600 hover:text-ink-900 hover:bg-cream-100 rounded-md transition-all"
            title="Copy response"
          >
            {copied ? (
              <><Check size={12} className="text-forest-500" /> Copied!</>
            ) : (
              <><Copy size={12} /> Copy</>
            )}
          </button>
        </div>
      )}
    </motion.div>
  );
}

// Quiet "following your <playbook>" chips when the agent loaded a skill.
function SkillChips({ skills }) {
  if (!skills?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mb-2">
      {skills.map((sk) => (
        <span
          key={sk.name}
          className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-violet-500/8 border border-violet-500/20 text-[11px] text-violet-700"
          title={`Playbook v${sk.version}`}
        >
          <Sparkles size={11} className="text-violet-500" />
          Following your <span className="font-medium italic">{sk.name}</span> playbook
        </span>
      ))}
    </div>
  );
}

// A friendly, minimal label for an action from its connector + capability,
// e.g. ("Notion", "notion-create-pages") → "Create pages · Notion".
function actionLabel(connector, capability) {
  let cap = (capability || 'action').replace(/[-_]/g, ' ').trim();
  if (connector && cap.toLowerCase().startsWith(connector.toLowerCase() + ' ')) {
    cap = cap.slice(connector.length + 1).trim();
  }
  cap = cap ? cap.charAt(0).toUpperCase() + cap.slice(1) : 'Action';
  return connector ? `${cap} · ${connector}` : cap;
}

const RESOLVED = {
  executed: { Icon: CheckCircle2, color: 'text-forest-500', word: 'Completed' },
  rejected: { Icon: XCircle, color: 'text-ink-500', word: 'Rejected' },
  failed: { Icon: AlertTriangle, color: 'text-terra-500', word: 'Didn’t complete' },
  blocked: { Icon: AlertTriangle, color: 'text-amber-700', word: 'Held back — needs a fresh approval' },
};

// The status sub-line for an action card. With a `target` the primary line shows the
// specific thing (the page title / recipient); this line carries the action + status.
function statusLine(status, { connector, capability, target, error }) {
  const label = actionLabel(connector, capability);
  const word =
    status === 'approving' ? 'Working…'
    : status === 'pending' ? 'Needs your approval'
    : status === 'failed' ? (error || RESOLVED.failed.word)
    : RESOLVED[status]?.word || status;
  // When the primary line already shows the target, repeat the action label here for
  // context; otherwise the label is the primary line and we only show the status word.
  return target ? `${label} · ${word}` : word;
}

// Minimal inline action card. The agent's description of the action streams above it as
// the answer body; this card marks that an action happened here — now task-specific (the
// page title / recipient on top) with its status. No raw payload, no "why".
function ApprovalGate({ approval, onResolve }) {
  const { connector, capability, target, status, error } = approval;
  const label = actionLabel(connector, capability);
  const primary = target || label;
  const resolved = ['executed', 'rejected', 'failed', 'blocked'].includes(status);
  const approving = status === 'approving';
  const cfg = resolved ? RESOLVED[status] : null;
  const ResolvedIcon = cfg?.Icon;
  const calm = resolved && status !== 'failed' && status !== 'blocked';

  return (
    <div className="mt-3">
      <div
        className={`rounded-xl border px-3.5 py-3 flex items-center gap-3 ${
          calm ? 'border-cream-200 bg-cream-50/60'
          : resolved ? 'border-amber-700/30 bg-amber-50/40'
          : 'border-amber-700/30 bg-amber-50/50'
        }`}
      >
        {resolved && ResolvedIcon ? (
          <ResolvedIcon size={17} className={`flex-shrink-0 ${cfg.color}`} />
        ) : (
          <ShieldQuestion size={17} className="flex-shrink-0 text-amber-700" />
        )}

        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-ink-900 truncate">{primary}</p>
          <p className="text-[11px] text-ink-600 truncate">
            {statusLine(status, { connector, capability, target, error })}
          </p>
        </div>

        {!resolved &&
          (approving ? (
            <Loader2 size={15} className="animate-spin text-ink-600 flex-shrink-0" />
          ) : (
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={() => onResolve?.(approval.pending_id, 'reject')}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-cream-100 text-ink-700 border border-cream-200 hover:bg-cream-200 active:scale-[0.98] transition-all"
              >
                Reject
              </button>
              <button
                onClick={() => onResolve?.(approval.pending_id, 'approve')}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-amber-900 text-white hover:bg-amber-950 active:scale-[0.98] transition-all"
              >
                Approve
              </button>
            </div>
          ))}
      </div>
    </div>
  );
}

// Multi-action gate (R6): one approval covering several actions, each with an
// approve/deselect toggle. Parameterized actions are flagged ("derived"). Resume once.
function BatchApprovalGate({ batch, threadId, onResolve }) {
  const [decisions, setDecisions] = useState(() =>
    Object.fromEntries(batch.items.map((it) => [it.pending_id, 'approve']))
  );
  const pending = batch.status === 'pending';
  const working = batch.status === 'approving';
  const toggle = (id) =>
    setDecisions((d) => ({ ...d, [id]: d[id] === 'approve' ? 'reject' : 'approve' }));
  const approveCount = Object.values(decisions).filter((v) => v === 'approve').length;

  return (
    <div className="mt-3 rounded-xl border border-amber-700/30 bg-amber-50/50 overflow-hidden">
      <div className="px-3.5 py-2.5 flex items-center gap-2 border-b border-amber-700/15">
        <ShieldQuestion size={15} className="text-amber-700 flex-shrink-0" />
        <p className="text-xs font-medium text-ink-900">
          {batch.items.length} actions need your approval
        </p>
      </div>

      <div className="divide-y divide-cream-200/70">
        {batch.items.map((it) => {
          const primary = it.target || actionLabel(it.connector, it.capability);
          const resolved = ['executed', 'rejected', 'failed', 'blocked'].includes(it.status);
          const cfg = resolved ? RESOLVED[it.status] : null;
          const ResolvedIcon = cfg?.Icon;
          const selected = decisions[it.pending_id] === 'approve';
          return (
            <div key={it.pending_id} className="px-3.5 py-2.5 flex items-center gap-3">
              {resolved && ResolvedIcon ? (
                <ResolvedIcon size={16} className={`flex-shrink-0 ${cfg.color}`} />
              ) : pending ? (
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => toggle(it.pending_id)}
                  className="flex-shrink-0 w-4 h-4 accent-amber-900 cursor-pointer"
                />
              ) : (
                <Loader2 size={15} className="animate-spin text-ink-500 flex-shrink-0" />
              )}

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <p className={`text-sm font-medium truncate ${pending && !selected ? 'text-ink-400 line-through' : 'text-ink-900'}`}>
                    {primary}
                  </p>
                  {it.preview_status === 'parameterized' && (
                    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium bg-violet-500/10 text-violet-700 flex-shrink-0" title="Its arguments derive from an earlier action's result, within approved bounds.">
                      <Link2 size={9} /> derived
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-ink-600 truncate">
                  {resolved
                    ? statusLine(it.status, { connector: it.connector, capability: it.capability, target: it.target, error: it.error })
                    : actionLabel(it.connector, it.capability)}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {pending && (
        <div className="px-3.5 py-2.5 flex items-center justify-end gap-2 border-t border-amber-700/15">
          <button
            onClick={() => onResolve?.(threadId, Object.fromEntries(batch.items.map((it) => [it.pending_id, 'reject'])))}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-cream-100 text-ink-700 border border-cream-200 hover:bg-cream-200 active:scale-[0.98] transition-all"
          >
            Reject all
          </button>
          <button
            onClick={() => onResolve?.(threadId, decisions)}
            disabled={approveCount === 0}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-amber-900 text-white hover:bg-amber-950 disabled:opacity-40 active:scale-[0.98] transition-all"
          >
            {approveCount === batch.items.length ? 'Approve all' : `Approve ${approveCount}`}
          </button>
        </div>
      )}
      {working && (
        <div className="px-3.5 py-2 text-[11px] text-ink-600 border-t border-amber-700/15">Carrying out the approved actions…</div>
      )}
    </div>
  );
}

// Question gate (R7): the agent is blocked and asks the user. Inline answer input.
function QuestionGate({ question, threadId, onAnswer }) {
  const [value, setValue] = useState('');
  const answered = question.status === 'answered';

  const submit = (e) => {
    e.preventDefault();
    const text = value.trim();
    if (!text) return;
    onAnswer?.(threadId, text);
  };

  return (
    <div className="mt-3 rounded-xl border border-violet-500/25 bg-violet-500/[0.04] px-3.5 py-3">
      <div className="flex items-start gap-2.5">
        <HelpCircle size={16} className="text-violet-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-ink-900">{question.text}</p>
          {question.context && <p className="text-[11px] text-ink-600 mt-0.5">{question.context}</p>}

          {answered ? (
            <p className="mt-2 text-xs text-ink-700">
              <span className="text-ink-500">You answered:</span> {question.answer}
            </p>
          ) : (
            <form onSubmit={submit} className="mt-2 flex items-end gap-2">
              <textarea
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) submit(e); }}
                rows={1}
                autoFocus
                placeholder="Type your answer…"
                className="flex-1 resize-none min-h-[36px] max-h-28 py-2 px-2.5 rounded-lg bg-white border border-cream-200
                  text-ink-900 placeholder:text-cream-400 text-sm focus:outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-500/20 transition-all"
              />
              <button
                type="submit"
                disabled={!value.trim()}
                className="flex-shrink-0 p-2 rounded-lg bg-violet-500 text-white hover:bg-violet-600 disabled:opacity-30 active:scale-95 transition-all"
                title="Send answer"
              >
                <Send size={15} />
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
