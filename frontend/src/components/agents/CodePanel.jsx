import { X, FileCode2 } from 'lucide-react';
import CodeBlock from './CodeBlock';

/**
 * Right-hand side panel showing the script that built a document — opened from the
 * `script.py` pill on a produce turn. Mirrors AttachmentViewer's panel chrome so the
 * agent page has one consistent side-panel language (keeps the conversation in view).
 */
export default function CodePanel({ artifact, onClose }) {
  return (
    <div className="w-96 flex-shrink-0 border-l border-cream-200 bg-white flex flex-col h-full animate-slide-right">
      {/* Header */}
      <div className="flex items-center justify-between px-5 h-14 border-b border-cream-200 flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <FileCode2 size={16} className="text-violet-500 flex-shrink-0" />
          <h3 className="font-semibold text-ink-900 text-sm truncate">{artifact.title || 'script.py'}</h3>
        </div>
        <button onClick={onClose} className="btn-ghost !p-1" title="Close">
          <X size={18} />
        </button>
      </div>

      {/* Body — the syntax-highlighted script (CodeBlock carries its own copy button) */}
      <div className="flex-1 overflow-y-auto p-3">
        <p className="text-[11px] text-sand-500 mb-1 px-1">
          The script that generated this document — run in the sandbox, not on your machine.
        </p>
        <CodeBlock code={artifact.code || ''} language={artifact.language || 'python'} />
      </div>
    </div>
  );
}
