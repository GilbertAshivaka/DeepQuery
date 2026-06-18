import { useEffect, useState } from 'react';
import { X, Loader2, AlertCircle, ShieldAlert, BookOpen, FileBox, MessageSquareQuote, RefreshCw } from 'lucide-react';
import * as connectorService from '../../services/connectorService';

/**
 * Connector detail / manifest browser (UI guide §8). Discovers the connector's full
 * capability set and distinguishes reads from actions — actions are visibly marked
 * "requires approval" so an admin understands the risk before approving.
 */
export default function ConnectorDetailPanel({ connector, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await connectorService.discover(connector.connector_id || connector.id);
      setData(d);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not reach this connector to discover its capabilities.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connector.connector_id, connector.id]);

  const isAction = (t) => t.mutates || t.kind === 'action' || t.kind === 'control';

  return (
    <div className="w-96 flex-shrink-0 border-l border-cream-200 bg-white flex flex-col h-full animate-slide-right">
      {/* Header */}
      <div className="flex items-center justify-between px-5 h-14 border-b border-cream-200 flex-shrink-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <HeaderIcon name={connector.name} iconUrl={data?.server_icon || connector.icon_url} />
          <div className="min-w-0">
            <h3 className="font-semibold text-ink-900 text-sm truncate">{data?.server_title || connector.name}</h3>
            <p className="text-[11px] text-sand-500">
              {connector.auth_method && <span className="capitalize">{connector.auth_method}</span>}
              {connector.version ? ` · v${connector.version}` : ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={load} className="btn-ghost !p-1" title="Re-discover"><RefreshCw size={15} /></button>
          <button onClick={onClose} className="btn-ghost !p-1" title="Close"><X size={18} /></button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {loading ? (
          <div className="flex items-center justify-center py-12"><Loader2 size={20} className="text-violet-500 animate-spin" /></div>
        ) : error ? (
          <div className="flex flex-col items-center text-center py-8 px-2">
            <AlertCircle size={26} className="text-terra-500 mb-2" />
            <p className="text-sm text-terra-500">{error}</p>
            <button onClick={load} className="btn-secondary text-xs mt-3"><RefreshCw size={13} /> Retry</button>
          </div>
        ) : data ? (
          <>
            {data.server_label && (
              <p className="text-xs text-ink-600">
                Server: <span className="font-medium text-ink-800">{data.server_label}</span>
              </p>
            )}
            {data.website_url && (
              <a href={data.website_url} target="_blank" rel="noreferrer"
                 className="text-xs text-violet-600 hover:underline break-all">
                {data.website_url}
              </a>
            )}

            {/* Tools — reads vs actions */}
            <Section icon={BookOpen} label="Tools" count={data.tools?.length}>
              {data.tools?.length ? data.tools.map((t) => (
                <CapabilityRow key={t.name} name={t.name} description={t.description}>
                  {isAction(t) ? (
                    <span className="badge bg-amber-900/10 text-amber-900 gap-1">
                      <ShieldAlert size={11} /> action · requires approval
                    </span>
                  ) : (
                    <span className="badge bg-forest-500/10 text-forest-500">read</span>
                  )}
                </CapabilityRow>
              )) : <Empty>No tools advertised.</Empty>}
            </Section>

            {/* Resources */}
            <Section icon={FileBox} label="Resources" count={data.resources?.length}>
              {data.resources?.length ? data.resources.map((r) => (
                <CapabilityRow key={r.uri} name={r.name || r.uri} description={r.description}>
                  {r.is_template && <span className="badge-info">template</span>}
                </CapabilityRow>
              )) : <Empty>No resources advertised.</Empty>}
            </Section>

            {/* Prompts */}
            <Section icon={MessageSquareQuote} label="Prompts" count={data.prompts?.length}>
              {data.prompts?.length ? data.prompts.map((p) => (
                <CapabilityRow key={p.name} name={p.name} description={p.description}>
                  {p.arguments?.length ? (
                    <span className="text-[10px] text-sand-500">{p.arguments.length} args</span>
                  ) : null}
                </CapabilityRow>
              )) : <Empty>No prompts advertised.</Empty>}
            </Section>
          </>
        ) : null}
      </div>
    </div>
  );
}

// Connector logo: the server's own icon when available, else a colored monogram (with an
// image-load fallback to the monogram).
function HeaderIcon({ name, iconUrl }) {
  const [failed, setFailed] = useState(false);
  const letter = (name || '?').trim().charAt(0).toUpperCase();
  const base = 'flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center overflow-hidden';
  if (iconUrl && !failed) {
    return (
      <img src={iconUrl} alt="" onError={() => setFailed(true)}
           className={`${base} bg-white border border-cream-200 object-contain`} />
    );
  }
  return <div className={`${base} bg-violet-500/10 text-violet-600 font-semibold text-sm`}>{letter}</div>;
}

function Section({ icon: Icon, label, count, children }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={14} className="text-sand-500" />
        <h4 className="text-xs font-semibold text-ink-800 uppercase tracking-wide">{label}</h4>
        {count != null && <span className="text-[10px] text-sand-500">({count})</span>}
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function CapabilityRow({ name, description, children }) {
  return (
    <div className="rounded-lg border border-cream-200 bg-cream-50/60 px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-ink-800 font-mono break-all">{name}</span>
        <span className="flex-shrink-0">{children}</span>
      </div>
      {description && <p className="text-xs text-ink-600 mt-1 leading-snug">{description}</p>}
    </div>
  );
}

function Empty({ children }) {
  return <p className="text-xs text-sand-500 italic">{children}</p>;
}
