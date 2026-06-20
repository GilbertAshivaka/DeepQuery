import { useState } from 'react';
import { motion } from 'framer-motion';
import { User, Bot, AlertCircle, Copy, Check, RefreshCw, FileText, Image as ImageIcon } from 'lucide-react';
import SelfCorrectionBadge from './SelfCorrectionBadge';
import AnswerMarkdown from '../agents/AnswerMarkdown';
import CitationChips from '../agents/CitationChips';

export default function MessageBubble({ message, isStreaming, onSourceClick, onAttachmentClick, onRetry }) {
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
          {/* Attachment chips on the user's turn (uploaded files / images) */}
          {message.attachments?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {message.attachments.map((a) => (
                <button
                  key={a.id}
                  onClick={() => onAttachmentClick?.(a)}
                  className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-md
                             bg-white/60 border border-white/40 text-ink-700 hover:bg-white/80 transition-all"
                >
                  {a.kind === 'image' ? <ImageIcon size={11} /> : <FileText size={11} />}
                  <span className="truncate max-w-[120px]">{a.filename}</span>
                </button>
              ))}
            </div>
          )}
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        </div>
      ) : (
        /* ── Assistant message: plain text, full width ── */
        <div className="w-full">
          {isError ? (
            <div className="flex items-start gap-2 text-terra-500 text-sm">
              <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p>{message.content}</p>
                {onRetry && (
                  <button
                    onClick={onRetry}
                    className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                               bg-cream-100 text-ink-700 border border-cream-200 hover:bg-cream-200 active:scale-[0.98] transition-all"
                  >
                    <RefreshCw size={13} /> Try again
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div className="relative">
              {/* Borrowed from the agent surface: inline [Source N] become clickable
                  citation chips (wired to the source drawer), plus GFM tables + code
                  highlighting the plain renderer lacked. */}
              <AnswerMarkdown
                content={message.content}
                citations={sources}
                onDocumentClick={onSourceClick}
              />
              {isStreaming && (
                <span className="inline-flex gap-0.5 ml-1 align-middle">
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" style={{ animationDelay: '300ms' }} />
                </span>
              )}
            </div>
          )}

          {/* Grouped citation chips (borrowed from the agent surface): documents, full
              documents, and attached files, each in its own labelled group. */}
          <CitationChips
            citations={sources}
            onDocumentClick={onSourceClick}
            onAttachmentClick={onAttachmentClick}
          />

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
