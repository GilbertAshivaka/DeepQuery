import { X, FileText, ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';

export default function SourceDrawer({ source, onClose }) {
  // Tolerate both chat and agent citation shapes:
  //   chat:  { document_name, score, text, ... }
  //   agent: { document_name, relevance_score, chunk_summary, page_number, ... }
  const score = source.score ?? source.relevance_score;
  const passage = source.text || source.chunk_summary;

  return (
    <div className="w-80 flex-shrink-0 border-l border-cream-200 bg-white flex flex-col h-full animate-slide-right">
      {/* Header */}
      <div className="flex items-center justify-between px-5 h-14 border-b border-cream-200 flex-shrink-0">
        <h3 className="font-semibold text-ink-900 text-sm truncate">Source Details</h3>
        <button onClick={onClose} className="btn-ghost !p-1">
          <X size={18} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* Document title */}
        <div>
          <p className="text-xs text-sand-500 mb-1">Document</p>
          <div className="flex items-start gap-2">
            <FileText size={16} className="text-violet-500 mt-0.5 flex-shrink-0" />
            <p className="text-sm font-medium text-ink-900">
              {source.document_name || source.document_title || source.title || 'Unknown Document'}
            </p>
          </div>
        </div>

        {/* Collection */}
        {source.collection && (
          <div>
            <p className="text-xs text-sand-500 mb-1">Collection</p>
            <span className="badge-info capitalize">{source.collection}</span>
          </div>
        )}

        {/* Page number (agent document citations) */}
        {source.page_number != null && (
          <div>
            <p className="text-xs text-sand-500 mb-1">Page</p>
            <span className="badge-info">Page {source.page_number}</span>
          </div>
        )}

        {/* Relevance Score */}
        {score != null && (
          <div>
            <p className="text-xs text-sand-500 mb-1">Relevance Score</p>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 bg-cream-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-violet-500 rounded-full transition-all"
                  style={{ width: `${Math.round(score * 100)}%` }}
                />
              </div>
              <span className="text-xs font-medium text-ink-700">
                {Math.round(score * 100)}%
              </span>
            </div>
          </div>
        )}

        {/* Chunk text */}
        {passage && (
          <div>
            <p className="text-xs text-sand-500 mb-1">Relevant Passage</p>
            <div className="p-3 bg-cream-50 rounded-xl border border-cream-200 text-sm text-ink-700 leading-relaxed">
              {passage}
            </div>
          </div>
        )}

        {/* Metadata */}
        {source.metadata && Object.keys(source.metadata).length > 0 && (
          <div>
            <p className="text-xs text-sand-500 mb-1">Metadata</p>
            <div className="space-y-1">
              {Object.entries(source.metadata)
                .filter(([, v]) => v != null && v !== '')
                .map(([key, value]) => (
                  <div
                    key={key}
                    className="flex items-start gap-2 text-xs"
                  >
                    <span className="text-sand-500 capitalize min-w-[80px]">
                      {key.replace(/_/g, ' ')}:
                    </span>
                    <span className="text-ink-700">{String(value)}</span>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* View document link */}
        {source.document_id && (
          <Link
            to={`/documents/${source.document_id}`}
            className="btn-secondary w-full"
          >
            <ExternalLink size={16} />
            View Full Document
          </Link>
        )}
      </div>
    </div>
  );
}
