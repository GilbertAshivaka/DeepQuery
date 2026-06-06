import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { motion } from 'framer-motion';
import { User, Bot, AlertCircle, Copy, Check } from 'lucide-react';
import SelfCorrectionBadge from './SelfCorrectionBadge';

export default function MessageBubble({ message, isStreaming, onSourceClick }) {
  const isUser = message.role === 'user';
  const isError = message.isError;
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(message.content);
      } else {
        // Fallback for non-secure contexts (e.g. HTTP)
        const textarea = document.createElement('textarea');
        textarea.value = message.content;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  // Support both 'sources' (from streaming) and 'citations' (from DB reload)
  const sources = message.sources || message.citations || [];
  // Status lives in metadata when streamed, top-level when reloaded from DB.
  const selfCorrectionStatus =
    message.metadata?.self_correction_status ?? message.self_correction_status;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className={isUser ? 'flex justify-end' : ''}
    >
      {isUser ? (
        /* ── User message: bubble aligned right ── */
        <div
          className="inline-block text-left rounded-2xl rounded-br-md px-4 py-3
            bg-violet-500/20
            text-ink-900 shadow-warm-sm max-w-[75%]"
        >
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        </div>
      ) : (
        /* ── Assistant message: plain text, full width ── */
        <div className="w-full">
          {isError ? (
            <div className="flex items-start gap-2 text-terra-500 text-sm">
              <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
              <p>{message.content}</p>
            </div>
          ) : (
            <div className="prose-warm text-sm text-ink-700">
              <ReactMarkdown>{message.content}</ReactMarkdown>
              {isStreaming && (
                <span className="inline-flex gap-0.5 ml-1 align-middle">
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" style={{ animationDelay: '300ms' }} />
                </span>
              )}
            </div>
          )}

          {/* Source citation pills */}
          {sources.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {sources.map((source, idx) => (
                <button
                  key={idx}
                  onClick={() => onSourceClick?.(source)}
                  className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium
                             bg-cream-100 text-amber-900 rounded-lg border border-cream-200
                             hover:bg-amber-900/10 hover:border-amber-900/20 transition-all"
                >
                  <span className="w-4 h-4 rounded-full bg-amber-900 text-white text-[10px] flex items-center justify-center">
                    {source.source_number || idx + 1}
                  </span>
                  <span className="truncate max-w-[150px]">
                    {source.document_name || source.document_title || `Source ${idx + 1}`}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Cache indicator and Copy button */}
          {!isStreaming && message.content && (
            <div className="mt-1.5 flex items-center gap-2">
              {/* Self-correction trust badge — icon only, left of Copy */}
              {selfCorrectionStatus && (
                <SelfCorrectionBadge status={selfCorrectionStatus} />
              )}

              <button
                onClick={handleCopy}
                className="inline-flex items-center gap-1 px-2 py-1 text-[11px] text-ink-600
                           hover:text-ink-900 hover:bg-cream-100 rounded-md transition-all"
                title="Copy response"
              >
                {copied ? (
                  <><Check size={12} className="text-forest-500" /> Copied!</>
                ) : (
                  <><Copy size={12} /> Copy</>
                )}
              </button>

              {/* Cache hit indicator */}
              {message.metadata?.cache_hit && (
                <span className="inline-flex items-center gap-1 px-2 py-1 text-[10px] text-violet-600
                                 bg-violet-50 rounded-md border border-violet-200"
                      title="Retrieved from cache (sub-100ms response)">
                  ⚡ Cached
                </span>
              )}
            </div>
          )}

        </div>
      )}
    </motion.div>
  );
}
