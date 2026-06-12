import { useState } from 'react';
import { motion } from 'framer-motion';
import { AlertCircle, Copy, Check, ShieldQuestion, Loader2, FileText, Image as ImageIcon, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react';
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

      {/* Approval gate — a minimal inline card; the action's description renders
          above it as normal output. Decide right here (Approve/Reject). */}
      {turn.approval && (
        <ApprovalGate approval={turn.approval} onResolve={onResolveApproval} />
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
  executed: { Icon: CheckCircle2, color: 'text-forest-500', word: 'Action completed' },
  rejected: { Icon: XCircle, color: 'text-ink-500', word: 'Action rejected' },
  failed: { Icon: AlertTriangle, color: 'text-terra-500', word: 'Action failed' },
};

// Minimal inline action card. The agent's description of the action streams above it
// as the answer body; this card just marks that an action happened here, with a short
// label and its status — Approve/Reject inline while pending. No raw payload.
function ApprovalGate({ approval, onResolve }) {
  const { connector, capability, status, error } = approval;
  const label = actionLabel(connector, capability);
  const resolved = ['executed', 'rejected', 'failed'].includes(status);
  const approving = status === 'approving';
  const cfg = resolved ? RESOLVED[status] : null;
  const ResolvedIcon = cfg?.Icon;

  return (
    <div className="mt-3">
      {/* Minimal action card */}
      <div
        className={`rounded-xl border px-3.5 py-3 flex items-center gap-3 ${
          resolved ? 'border-cream-200 bg-cream-50/60' : 'border-amber-700/30 bg-amber-50/50'
        }`}
      >
        {resolved && ResolvedIcon ? (
          <ResolvedIcon size={17} className={`flex-shrink-0 ${cfg.color}`} />
        ) : (
          <ShieldQuestion size={17} className="flex-shrink-0 text-amber-700" />
        )}

        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-ink-900 truncate">{label}</p>
          <p className="text-[11px] text-ink-600">
            {resolved
              ? status === 'failed'
                ? error || 'The action did not complete.'
                : cfg.word
              : approving
                ? 'Working…'
                : 'Needs your approval'}
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
