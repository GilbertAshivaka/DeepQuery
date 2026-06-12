import { useState } from 'react';
import { Highlight } from 'prism-react-renderer';
import { Copy, Check } from 'lucide-react';

/**
 * A warm, light code block matching Deep Query's cream/rust/violet design language
 * (the default prism dark themes clash with it). Syntax colors are drawn from the
 * app palette: rust keywords, green strings, violet functions, ink body text.
 * `not-prose` keeps the markdown typography styles from bleeding in.
 */
const warmLight = {
  plain: { color: '#44403C', backgroundColor: 'transparent' },
  styles: [
    { types: ['comment', 'prolog', 'doctype', 'cdata'], style: { color: '#A89A86', fontStyle: 'italic' } },
    { types: ['punctuation'], style: { color: '#8A7E6F' } },
    { types: ['property', 'tag', 'symbol', 'attr-name', 'variable'], style: { color: '#9E3B0F' } },
    { types: ['boolean', 'number', 'constant'], style: { color: '#C24D3D' } },
    { types: ['string', 'char', 'attr-value', 'inserted'], style: { color: '#1B7A56' } },
    { types: ['operator', 'entity', 'url'], style: { color: '#57534E' } },
    { types: ['atrule', 'keyword', 'selector'], style: { color: '#7F3210' } },
    { types: ['function', 'class-name', 'builtin'], style: { color: '#7C3AED' } },
    { types: ['regex', 'important', 'deleted'], style: { color: '#D95F4E' } },
  ],
};

export default function CodeBlock({ code, language }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="not-prose my-3 rounded-xl overflow-hidden border border-cream-200 bg-cream-100">
      <div className="flex items-center justify-between px-3 py-1.5 bg-cream-200/50 border-b border-cream-200">
        <span className="text-[10px] uppercase tracking-wide text-sand-600 font-mono">
          {language || 'code'}
        </span>
        <button
          onClick={copy}
          className="inline-flex items-center gap-1 text-[11px] text-ink-600 hover:text-ink-900 transition-colors"
          title="Copy code"
        >
          {copied ? <><Check size={12} className="text-forest-500" /> Copied</> : <><Copy size={12} /> Copy</>}
        </button>
      </div>
      <Highlight code={code} language={language || 'text'} theme={warmLight}>
        {({ tokens, getLineProps, getTokenProps }) => (
          <pre
            className="text-xs leading-relaxed p-3.5 overflow-x-auto text-ink-700"
            style={{ margin: 0, background: 'transparent' }}
          >
            {tokens.map((line, i) => {
              const { key: _lk, ...lineProps } = getLineProps({ line });
              return (
                <div key={i} {...lineProps}>
                  {line.map((token, k) => {
                    const { key: _tk, ...tokenProps } = getTokenProps({ token });
                    return <span key={k} {...tokenProps} />;
                  })}
                </div>
              );
            })}
          </pre>
        )}
      </Highlight>
    </div>
  );
}
