import { Check, X, AlertTriangle, ShieldQuestion, Loader2, Circle } from 'lucide-react';

/**
 * The orchestrator's plan as an ordered checklist (Claude-Code style). Each step's
 * state is carried by COLOR + ICON SHAPE only — never a text status label. The icon
 * shape keeps the meaning legible for color-blind users; the status word lives in
 * aria-label for screen readers, not on screen.
 */

// Normalize the various status spellings the backend may emit.
const norm = (s) => (s || 'pending').toLowerCase().replace(/[\s_]+/g, '-');

const STATE = {
  pending:             { Icon: Circle,         color: 'text-cream-400',  spin: false, label: 'Pending' },
  running:             { Icon: Loader2,        color: 'text-violet-500', spin: true,  label: 'In progress' },
  'in-progress':       { Icon: Loader2,        color: 'text-violet-500', spin: true,  label: 'In progress' },
  done:                { Icon: Check,          color: 'text-forest-500', spin: false, label: 'Done' },
  'awaiting-approval': { Icon: ShieldQuestion, color: 'text-amber-700',  spin: false, label: 'Awaiting approval' },
  rejected:            { Icon: X,              color: 'text-terra-500',  spin: false, label: 'Rejected' },
  failed:              { Icon: AlertTriangle,  color: 'text-terra-500',  spin: false, label: 'Failed' },
};

export default function PlanChecklist({ steps }) {
  if (!steps?.length) return null;

  return (
    <div className="mb-3 rounded-xl border border-cream-200 bg-cream-50/60 px-3.5 py-2.5">
      <ul className="space-y-1.5">
        {steps.map((step) => {
          const cfg = STATE[norm(step.status)] || STATE.pending;
          const { Icon } = cfg;
          const isDone = norm(step.status) === 'done';
          const isPending = norm(step.status) === 'pending';
          return (
            <li key={step.id} className="flex items-center gap-2.5 text-sm">
              <span
                role="img"
                aria-label={cfg.label}
                title={cfg.label}
                className={`flex-shrink-0 ${cfg.color}`}
              >
                <Icon size={15} className={cfg.spin ? 'animate-spin' : ''} strokeWidth={2.25} />
              </span>
              <span
                className={`leading-snug transition-colors
                  ${isDone ? 'text-ink-600' : isPending ? 'text-cream-400' : 'text-ink-800'}`}
              >
                {step.label}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
