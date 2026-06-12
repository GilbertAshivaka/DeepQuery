import { FileText, Layers, Radio, Paperclip, Clock } from 'lucide-react';

/**
 * The four citation source-kinds (handoff §7), each rendered distinctly so a reader
 * can tell at a glance which facts rest on stable documents vs a live snapshot:
 *   document      → rust [Source N]   — stable, click opens the source drawer
 *   document_full → rust [Doc N]      — whole doc pulled in, drawer
 *   live          → violet [Live N]   — connector + "as of {time}", click → deep_link
 *   attachment    → [Attachment N]    — user-provided, opens the viewer
 *
 * Color is never the only signal — each kind also carries its own glyph and label.
 */

const KIND = {
  document: 'document',
  document_full: 'document_full',
  live: 'live',
  attachment: 'attachment',
};

function timeOf(retrievedAt) {
  if (!retrievedAt) return null;
  const d = new Date(retrievedAt);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function Chip({ children, onClick, className, title }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium
                  rounded-lg border transition-all ${className}`}
    >
      {children}
    </button>
  );
}

function Numeral({ n, className }) {
  return (
    <span className={`w-4 h-4 rounded-full text-white text-[10px] flex items-center justify-center flex-shrink-0 ${className}`}>
      {n}
    </span>
  );
}

export default function CitationChips({ citations = [], onDocumentClick, onAttachmentClick }) {
  if (!citations.length) return null;

  const groups = {
    document: citations.filter((c) => c.source_type === KIND.document),
    document_full: citations.filter((c) => c.source_type === KIND.document_full),
    live: citations.filter((c) => c.source_type === KIND.live),
    attachment: citations.filter((c) => c.source_type === KIND.attachment),
    // Anything without a recognized source_type falls back to the document chip.
    other: citations.filter((c) => !Object.values(KIND).includes(c.source_type)),
  };

  const sections = [
    { key: 'document', label: 'Documents', items: [...groups.document, ...groups.other] },
    { key: 'document_full', label: 'Full documents', items: groups.document_full },
    { key: 'live', label: 'Live', items: groups.live },
    { key: 'attachment', label: 'Attached', items: groups.attachment },
  ].filter((s) => s.items.length);

  return (
    <div className="mt-3 space-y-2">
      {sections.map((section) => (
        <div key={section.key} className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-wide text-sand-500 mr-0.5">
            {section.label}
          </span>

          {section.items.map((c, idx) => {
            // ── Live ──
            if (section.key === 'live') {
              const t = timeOf(c.retrieved_at);
              return (
                <Chip
                  key={idx}
                  onClick={() => c.deep_link && window.open(c.deep_link, '_blank', 'noopener')}
                  title={c.mutability_note || 'Live source — may have changed'}
                  className="bg-violet-500/10 text-violet-600 border-violet-500/20 hover:bg-violet-500/20"
                >
                  <Radio size={12} className="flex-shrink-0" />
                  <span className="truncate max-w-[160px]">
                    {c.connector_name || c.title_or_label || 'Live'}
                  </span>
                  {t && (
                    <span className="inline-flex items-center gap-0.5 text-[10px] text-violet-500/80">
                      <Clock size={9} /> {t}
                    </span>
                  )}
                </Chip>
              );
            }

            // ── Attachment ──
            if (section.key === 'attachment') {
              return (
                <Chip
                  key={idx}
                  onClick={() => onAttachmentClick?.(c)}
                  title="Attached by you"
                  className="bg-sand-500/10 text-sand-600 border-sand-500/25 hover:bg-sand-500/20"
                >
                  <Paperclip size={12} className="flex-shrink-0" />
                  <span className="truncate max-w-[160px]">
                    {c.filename || `Attachment ${c.attachment_number || idx + 1}`}
                  </span>
                </Chip>
              );
            }

            // ── Full document ──
            if (section.key === 'document_full') {
              return (
                <Chip
                  key={idx}
                  onClick={() => onDocumentClick?.(c)}
                  title="Full document"
                  className="bg-cream-100 text-amber-900 border-cream-200 hover:bg-amber-900/10 hover:border-amber-900/20"
                >
                  <Layers size={12} className="flex-shrink-0 text-amber-800" />
                  <span className="truncate max-w-[160px]">
                    {c.document_name || `Doc ${c.doc_number || idx + 1}`}
                  </span>
                </Chip>
              );
            }

            // ── Document (default) ──
            return (
              <Chip
                key={idx}
                onClick={() => onDocumentClick?.(c)}
                title={c.chunk_summary || c.document_name}
                className="bg-cream-100 text-amber-900 border-cream-200 hover:bg-amber-900/10 hover:border-amber-900/20"
              >
                <Numeral n={c.source_number || idx + 1} className="bg-amber-900" />
                <span className="truncate max-w-[160px]">
                  {c.document_name || `Source ${c.source_number || idx + 1}`}
                </span>
              </Chip>
            );
          })}
        </div>
      ))}
    </div>
  );
}
