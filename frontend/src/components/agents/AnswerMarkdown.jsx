import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CodeBlock from './CodeBlock';

/**
 * Renders an agent answer, fixing two things the raw model output does badly:
 *   1. Literal HTML (`<br>`) and fullwidth citation brackets (`【Source 1】`) that
 *      ReactMarkdown would otherwise print verbatim.
 *   2. Inline source markers — turned into small clickable citation chips
 *      (Claude-style inline citations) wired to the same drawer / deep-link / viewer
 *      actions as the grouped chips below the answer.
 */

const KIND_ALIAS = { source: 'document', doc: 'document_full', live: 'live', attachment: 'attachment' };

const BR_RE = /<br\s*\/?>/gi;
const isTableRow = (line) => /^\s*\|.*\|\s*$/.test(line);

function sanitize(text) {
  if (!text) return '';
  // <br> handling is table-aware: a newline inside a GFM table row would shatter
  // the row, so within table rows we collapse <br> to a space; elsewhere it becomes
  // a real line break.
  const debr = text
    .split('\n')
    .map((line) => (isTableRow(line) ? line.replace(BR_RE, ' ') : line.replace(BR_RE, '\n')))
    .join('\n');

  return debr
    // fullwidth brackets 【 】 → ascii [ ]
    .replace(/【\s*/g, '[')
    .replace(/\s*】/g, ']')
    // A run of citation markers sitting right before sentence-ending punctuation is
    // moved to AFTER the punctuation — cleaner look, and it keeps the pills out of the
    // sentence so selecting/copying the text isn't interrupted.
    .replace(
      /\s*((?:\[(?:Source|Doc|Live|Attachment)\s+\d+\]\s*)+)([.!?])/gi,
      (_m, markers, term) => `${term} ${markers.trim()}`
    )
    // bare inline markers → cite links (skip if already a markdown link target)
    .replace(/\[(Source|Doc|Live|Attachment)\s+(\d+)\](?!\()/gi, (_m, kind, n) => {
      return `[${kind} ${n}](#cite:${kind.toLowerCase()}:${n})`;
    });
}

function resolveCitation(citations, kind, n) {
  const type = KIND_ALIAS[kind];
  const num = Number(n);
  return citations.find((c) => {
    if (type === 'document') return (c.source_type === 'document' || !c.source_type) && Number(c.source_number) === num;
    if (type === 'document_full') return c.source_type === 'document_full' && Number(c.doc_number) === num;
    if (type === 'live') return c.source_type === 'live' && Number(c.live_number) === num;
    if (type === 'attachment') return c.source_type === 'attachment' && Number(c.attachment_number) === num;
    return false;
  });
}

const CHIP_STYLE = {
  source: 'bg-amber-900/10 text-amber-900 hover:bg-amber-900/20',
  doc: 'bg-amber-900/10 text-amber-900 hover:bg-amber-900/20',
  live: 'bg-violet-500/10 text-violet-600 hover:bg-violet-500/20',
  attachment: 'bg-sand-500/10 text-sand-600 hover:bg-sand-500/20',
};

export default function AnswerMarkdown({ content, citations = [], onDocumentClick, onAttachmentClick }) {
  const handleCite = (kind, n) => {
    const citation = resolveCitation(citations, kind, n);
    if (kind === 'live') {
      if (citation?.deep_link) window.open(citation.deep_link, '_blank', 'noopener');
      return;
    }
    if (kind === 'attachment') {
      onAttachmentClick?.(citation);
      return;
    }
    if (citation) onDocumentClick?.(citation);
  };

  return (
    <div className="prose-warm text-sm text-ink-700">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Fenced code → a real highlighted block (replaces the default <pre><code>,
          // which was inheriting the inline-code styling). Inline `code` is left to the
          // prose styles (the violet pill).
          pre({ children }) {
            const codeEl = Array.isArray(children)
              ? children.find((c) => c?.type === 'code') ?? children[0]
              : children;
            const className = codeEl?.props?.className || '';
            const lang = /language-(\w+)/.exec(className)?.[1];
            const raw = codeEl?.props?.children;
            const code = (Array.isArray(raw) ? raw.join('') : String(raw ?? '')).replace(/\n$/, '');
            return <CodeBlock code={code} language={lang} />;
          },
          // Keep wide tables inside their own horizontal scroll so they can't
          // blow out the column width (and shove side panels off-screen).
          table({ node, children }) {
            void node;
            return (
              <div className="overflow-x-auto">
                <table>{children}</table>
              </div>
            );
          },
          a({ node, href, children }) {
            void node;
            if (href?.startsWith('#cite:')) {
              const [, kind, n] = href.split(':');
              return (
                <button
                  type="button"
                  onClick={() => handleCite(kind, n)}
                  contentEditable={false}
                  className={`inline-flex items-center align-baseline mx-0.5 px-1.5 py-px rounded-md
                              text-[11px] font-medium no-underline transition-colors select-none
                              ${CHIP_STYLE[kind] || CHIP_STYLE.source}`}
                >
                  {children}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {sanitize(content)}
      </ReactMarkdown>
    </div>
  );
}
