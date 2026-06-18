import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';
import { useAuthStore } from '../store/authStore';
import * as connectorService from '../services/connectorService';
import Modal from '../components/ui/Modal';
import RegisterConnectorModal from '../components/connectors/RegisterConnectorModal';
import ConnectorDetailPanel from '../components/connectors/ConnectorDetailPanel';
import EnableModal from '../components/connectors/EnableModal';
import {
  Plug, Plus, Search, Loader2, Check, X, ShieldCheck, ShieldQuestion,
  Trash2, FileSearch, Globe, Server, CheckCircle2, AlertCircle,
} from 'lucide-react';

// Decorative backdrop — a soft warm "mesh" of on-palette radial glows plus a faint grain,
// so the page reads as crafted rather than flat. Kept very low-opacity to never compete
// with the cards. Colors are straight from the theme (amber / sand / deep-brown / a violet hint).
const MESH_BG = {
  backgroundImage: [
    'radial-gradient(at 0% 0%, rgba(255,126,17,0.06) 0px, transparent 45%)',     // amber-500
    'radial-gradient(at 100% 0%, rgba(193,154,107,0.13) 0px, transparent 52%)',  // sand-500
    'radial-gradient(at 88% 100%, rgba(139,92,246,0.05) 0px, transparent 45%)',  // violet hint
    'radial-gradient(at 8% 96%, rgba(127,50,16,0.06) 0px, transparent 50%)',     // amber-900
  ].join(', '),
};
const GRAIN_BG = {
  backgroundImage:
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
  opacity: 0.03,
};

// Action buttons reveal on card hover/focus, rising gently into place.
const HOVER_ACTIONS =
  'opacity-0 translate-y-1 group-hover:opacity-100 group-hover:translate-y-0 ' +
  'focus-within:opacity-100 focus-within:translate-y-0 transition-all duration-200';

// The actions area collapses to zero height until hover (grid-rows 0fr→1fr animates the
// expand), so the status row above it sinks to the bottom when idle and lifts as the
// buttons appear — no empty gap, no layout jump.
const ACTIONS_COLLAPSE =
  'grid grid-rows-[0fr] group-hover:grid-rows-[1fr] focus-within:grid-rows-[1fr] ' +
  'transition-[grid-template-rows] duration-300 ease-out';

function PageBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0" style={MESH_BG} />
      <div className="absolute inset-0 mix-blend-multiply" style={GRAIN_BG} />
    </div>
  );
}

function healthInfo(h) {
  if (!h) return null;
  const state = String(h.state || h.status || '').toLowerCase();
  if (h.healthy === true || state === 'closed' || state === 'healthy')
    return { label: 'healthy', cls: 'bg-forest-500/10 text-forest-500', dot: 'bg-forest-500' };
  if (state === 'half_open' || state === 'degraded')
    return { label: 'degraded', cls: 'bg-sand-500/10 text-sand-600', dot: 'bg-sand-500' };
  if (h.healthy === false || state === 'open' || state === 'unavailable')
    return { label: 'unavailable', cls: 'bg-terra-500/10 text-terra-500', dot: 'bg-terra-500' };
  return { label: state || 'unknown', cls: 'bg-cream-200 text-ink-600', dot: 'bg-cream-400' };
}

// A small live status dot — a soft ping ring around a solid core. Pulses for "healthy"
// and "unavailable" (live states worth noticing); steady otherwise.
function StatusDot({ color, pulse = true }) {
  return (
    <span className="relative flex h-1.5 w-1.5">
      {pulse && (
        <span className={`absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping ${color}`} />
      )}
      <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${color}`} />
    </span>
  );
}

// Faint on-palette glows tucked into the card corners, so each card has a touch of warmth
// and depth instead of flat white. They brighten slightly on hover.
function CardArt() {
  return (
    <>
      <div aria-hidden
           className="pointer-events-none absolute -top-10 -right-10 w-36 h-36 rounded-full -z-10 opacity-50 group-hover:opacity-90 transition-opacity duration-500"
           style={{ background: 'radial-gradient(closest-side, rgba(255,126,17,0.10), transparent)' }} />
      <div aria-hidden
           className="pointer-events-none absolute -bottom-12 -left-8 w-32 h-32 rounded-full -z-10 opacity-40 group-hover:opacity-70 transition-opacity duration-500"
           style={{ background: 'radial-gradient(closest-side, rgba(193,154,107,0.16), transparent)' }} />
    </>
  );
}

export default function ConnectorsPage() {
  const { user } = useAuthStore();
  const isAdmin = user?.role === 'admin';
  const [searchParams, setSearchParams] = useSearchParams();

  const [tab, setTab] = useState(isAdmin ? 'directory' : 'available');
  const [deploymentMode, setDeploymentMode] = useState(null);
  const [available, setAvailable] = useState([]);
  const [directory, setDirectory] = useState([]);
  const [health, setHealth] = useState({});
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  const [detail, setDetail] = useState(null);
  const [showRegister, setShowRegister] = useState(false);
  const [enableTarget, setEnableTarget] = useState(null);
  const [approveTarget, setApproveTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const loadAvailable = async () => {
    try { setAvailable(await connectorService.getAvailable()); } catch { /* ignore */ }
  };
  const loadDirectory = async () => {
    try {
      const d = await connectorService.getDirectory();
      setDirectory(d);
      d.forEach(async (it) => {
        try {
          const h = await connectorService.getHealth(it.connector_id);
          setHealth((prev) => ({ ...prev, [it.connector_id]: h }));
        } catch { /* unreachable — leave unknown */ }
      });
    } catch { /* ignore */ }
  };

  useEffect(() => {
    (async () => {
      setLoading(true);
      try { setDeploymentMode((await connectorService.getDeploymentMode()).mode); } catch { /* ignore */ }
      await loadAvailable();
      if (isAdmin) await loadDirectory();
      setLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  // OAuth return (provider → /api/.../auth/callback → /connectors?connected=1|error=…)
  useEffect(() => {
    if (searchParams.get('connected')) {
      setNotice({ type: 'success', message: 'Connector connected.' });
      loadAvailable();
      setSearchParams({}, { replace: true });
    } else if (searchParams.get('error')) {
      setNotice({ type: 'error', message: `Connection failed: ${searchParams.get('error')}` });
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onEnable = async (it) => {
    const id = it.connector_id || it.id;
    setBusyId(id);
    try {
      await connectorService.enableConnector(id);
      if ((it.auth_method || 'none') !== 'none') {
        setEnableTarget(it); // auth step (OAuth handoff / credential entry)
      } else {
        setNotice({ type: 'success', message: `${it.name} enabled.` });
        await loadAvailable();
      }
    } catch (e) {
      setNotice({ type: 'error', message: e.response?.data?.detail || 'Could not enable this connector.' });
    } finally {
      setBusyId(null);
    }
  };

  const onDisable = async (it) => {
    const id = it.connector_id || it.id;
    setBusyId(id);
    try {
      await connectorService.disableConnector(id);
      await loadAvailable();
    } catch { /* ignore */ } finally { setBusyId(null); }
  };

  const onRevoke = async (it) => {
    setBusyId(it.connector_id);
    try { await connectorService.revokeApproval(it.connector_id); await loadDirectory(); await loadAvailable(); }
    catch { /* ignore */ } finally { setBusyId(null); }
  };

  const onDelete = async (it) => {
    setBusyId(it.connector_id);
    try {
      await connectorService.deleteConnector(it.connector_id);
      setDeleteTarget(null);
      if (detail?.connector_id === it.connector_id || detail?.id === it.connector_id) setDetail(null);
      setNotice({ type: 'success', message: `${it.name} deleted.` });
      await loadDirectory();
      await loadAvailable();
    } catch (e) {
      setNotice({ type: 'error', message: e.response?.data?.detail || 'Could not delete the connector.' });
    } finally { setBusyId(null); }
  };

  const filtered = (items) =>
    !query.trim() ? items : items.filter((i) => (i.name || '').toLowerCase().includes(query.toLowerCase()));

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 flex flex-col h-full relative isolate">
        <PageBackdrop />
        {/* Header */}
        <div className="flex items-center justify-between px-4 md:px-8 h-14 border-b border-cream-200 flex-shrink-0">
          <div className="flex items-center gap-2">
            <Plug size={18} className="text-amber-900" />
            <h2 className="font-semibold text-ink-900 text-sm">Connectors</h2>
            {deploymentMode && (
              <span className="badge bg-cream-200 text-ink-600 ml-1 capitalize">{deploymentMode}</span>
            )}
          </div>
          {isAdmin && tab === 'directory' && (
            <button onClick={() => setShowRegister(true)} className="btn-primary !py-1.5 !px-3 text-xs">
              <Plus size={15} /> Add connector
            </button>
          )}
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 px-4 md:px-8 pt-3 border-b border-cream-200">
          <TabButton active={tab === 'available'} onClick={() => setTab('available')}>Available to you</TabButton>
          {isAdmin && (
            <TabButton active={tab === 'directory'} onClick={() => setTab('directory')}>Directory</TabButton>
          )}
        </div>

        {/* Notice banner */}
        {notice && (
          <div className={`mx-4 md:mx-8 mt-3 flex items-center gap-2 text-sm rounded-lg px-3 py-2 ${
            notice.type === 'success'
              ? 'bg-forest-500/10 text-forest-500'
              : 'bg-terra-500/10 text-terra-500'}`}>
            {notice.type === 'success' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
            <span className="flex-1">{notice.message}</span>
            <button onClick={() => setNotice(null)} className="hover:opacity-70"><X size={14} /></button>
          </div>
        )}

        {/* Search */}
        <div className="px-4 md:px-8 pt-4">
          <div className="relative max-w-md">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-cream-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search connectors…"
              className="input !pl-9"
            />
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-16"><Loader2 size={22} className="text-violet-500 animate-spin" /></div>
          ) : tab === 'available' ? (
            <CardGrid>
              {filtered(available).length ? filtered(available).map((it) => (
                <AvailableCard
                  key={it.connector_id || it.id}
                  item={it}
                  busy={busyId === (it.connector_id || it.id)}
                  onEnable={() => onEnable(it)}
                  onDisable={() => onDisable(it)}
                />
              )) : <EmptyNote>No connectors are available to you yet. An admin approves connectors into your institution first.</EmptyNote>}
            </CardGrid>
          ) : (
            <CardGrid>
              {filtered(directory).length ? filtered(directory).map((it) => (
                <DirectoryCard
                  key={it.connector_id}
                  item={it}
                  health={healthInfo(health[it.connector_id])}
                  busy={busyId === it.connector_id}
                  onManifest={() => setDetail(it)}
                  onApprove={() => setApproveTarget(it)}
                  onRevoke={() => onRevoke(it)}
                  onDelete={() => setDeleteTarget(it)}
                />
              )) : <EmptyNote>No connectors registered yet. Use “Add connector” to register one.</EmptyNote>}
            </CardGrid>
          )}
        </div>
      </div>

      {/* Detail / manifest side panel */}
      <AnimatePresence>
        {detail && <ConnectorDetailPanel connector={detail} onClose={() => setDetail(null)} />}
      </AnimatePresence>

      {/* Register modal */}
      <AnimatePresence>
        {showRegister && (
          <RegisterConnectorModal
            onClose={() => setShowRegister(false)}
            onRegistered={async (created) => {
              setShowRegister(false);
              setNotice({ type: 'success', message: `${created.name} registered.` });
              await loadDirectory();
              setDetail({ connector_id: created.id, name: created.name, version: created.version });
            }}
          />
        )}
      </AnimatePresence>

      {/* Enable / auth modal */}
      <AnimatePresence>
        {enableTarget && (
          <EnableModal
            connector={enableTarget}
            onClose={() => { setEnableTarget(null); loadAvailable(); }}
            onDone={() => { setEnableTarget(null); setNotice({ type: 'success', message: 'Connected.' }); loadAvailable(); }}
          />
        )}
      </AnimatePresence>

      {/* Approve modal */}
      <AnimatePresence>
        {approveTarget && (
          <ApproveModal
            connector={approveTarget}
            onClose={() => setApproveTarget(null)}
            onApproved={async () => { setApproveTarget(null); setNotice({ type: 'success', message: 'Connector approved.' }); await loadDirectory(); await loadAvailable(); }}
          />
        )}
      </AnimatePresence>

      {/* Delete confirmation */}
      <AnimatePresence>
        {deleteTarget && (
          <Modal
            title={`Delete ${deleteTarget.name}?`}
            onClose={() => setDeleteTarget(null)}
            footer={
              <>
                <button onClick={() => setDeleteTarget(null)} className="btn-secondary text-sm">Cancel</button>
                <button
                  onClick={() => onDelete(deleteTarget)}
                  disabled={busyId === deleteTarget.connector_id}
                  className="btn-danger text-sm"
                >
                  {busyId === deleteTarget.connector_id
                    ? <><Loader2 size={15} className="animate-spin" /> Deleting…</>
                    : <><Trash2 size={15} /> Delete connector</>}
                </button>
              </>
            }
          >
            <p className="text-sm text-ink-700 leading-relaxed">
              This removes <span className="font-medium text-ink-900">{deleteTarget.name}</span> from the registry
              entirely — its allowlist approval, every user's enablement, and stored credentials are purged. This can't
              be undone (the audit trail is kept). To keep it but drop access, use <span className="font-medium">Revoke</span> instead.
            </p>
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Approve modal (allowlist: role restriction + version pin) ──
function ApproveModal({ connector, onClose, onApproved }) {
  const [roles, setRoles] = useState((connector.allowed_roles || []).join(', '));
  const [version, setVersion] = useState(connector.version || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const allowedRoles = roles.trim() ? roles.split(',').map((r) => r.trim()).filter(Boolean) : null;
      await connectorService.approveConnector(connector.connector_id, { allowedRoles, version: version.trim() || null });
      onApproved?.();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not approve.');
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Approve ${connector.name}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={busy} className="btn-primary text-sm">
            {busy ? <><Loader2 size={15} className="animate-spin" /> Approving…</> : 'Approve'}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {error && (
          <div className="flex items-start gap-2 text-terra-500 text-sm bg-terra-500/5 border border-terra-500/20 rounded-lg p-2.5">
            <AlertCircle size={15} className="flex-shrink-0 mt-0.5" /><span>{error}</span>
          </div>
        )}
        <p className="text-sm text-ink-600 leading-relaxed">
          Approving adds <span className="font-medium text-ink-900">{connector.name}</span> to the institution's
          allowlist. Any actions it exposes still require per-use approval at run time.
        </p>
        <label className="block">
          <span className="block text-xs text-sand-500 mb-1">Restrict to roles (comma-separated, blank = all roles)</span>
          <input className="input" value={roles} onChange={(e) => setRoles(e.target.value)} placeholder="researcher, admin" />
        </label>
        <label className="block">
          <span className="block text-xs text-sand-500 mb-1">Pin version (blank = current registered version)</span>
          <input className="input font-mono text-xs" value={version} onChange={(e) => setVersion(e.target.value)} placeholder="1.0.0" />
        </label>
      </div>
    </Modal>
  );
}

// ── Cards & bits ──
function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
        active ? 'border-amber-900 text-amber-900' : 'border-transparent text-ink-600 hover:text-ink-900'}`}
    >
      {children}
    </button>
  );
}

function CardGrid({ children }) {
  return <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">{children}</div>;
}

function EmptyNote({ children }) {
  return <p className="col-span-full text-sm text-sand-500 py-8 text-center max-w-md mx-auto">{children}</p>;
}

function AuthBadge({ method }) {
  const m = method || 'none';
  const Icon = m === 'oauth2' ? Globe : m === 'none' ? Server : ShieldCheck;
  return (
    <span className="badge bg-cream-200 text-ink-600 gap-1 capitalize">
      <Icon size={11} /> {m === 'none' ? 'no auth' : m}
    </span>
  );
}

// Connector logo: the server's own icon (or domain favicon) when available, otherwise a
// colored monogram. Falls back to the monogram if the image fails to load.
function ConnectorIcon({ name, iconUrl, size = 36 }) {
  const [failed, setFailed] = useState(false);
  const letter = (name || '?').trim().charAt(0).toUpperCase();
  const base = 'flex-shrink-0 rounded-lg flex items-center justify-center overflow-hidden';
  if (iconUrl && !failed) {
    return (
      <img src={iconUrl} alt="" width={size} height={size}
           onError={() => setFailed(true)}
           className={`${base} bg-white border border-cream-200 object-contain`}
           style={{ width: size, height: size }} />
    );
  }
  return (
    <div className={`${base} bg-violet-500/10 text-violet-600 font-semibold`}
         style={{ width: size, height: size, fontSize: size * 0.42 }}>
      {letter}
    </div>
  );
}

function AvailableCard({ item, busy, onEnable, onDisable }) {
  const enabled = !!item.enabled;
  return (
    <div className="card card-hover group relative isolate overflow-hidden p-4 flex flex-col gap-3">
      <CardArt />
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5 min-w-0">
          <ConnectorIcon name={item.name} iconUrl={item.icon_url} />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-ink-900 truncate">{item.name}</h3>
            {item.version && <p className="text-[11px] text-sand-500">v{item.version}</p>}
          </div>
        </div>
        <AuthBadge method={item.auth_method} />
      </div>
      {item.summary && <p className="text-xs text-ink-600 leading-snug line-clamp-2">{item.summary}</p>}

      {/* Status sits low when idle; the action lifts it as it expands on hover. */}
      <div className="mt-auto flex flex-col">
        <div className="flex flex-wrap items-center gap-1.5">
          {enabled ? (
            <span className="badge-success gap-1.5"><StatusDot color="bg-forest-500" /> Enabled</span>
          ) : <span className="badge bg-cream-200 text-ink-600">Not enabled</span>}
        </div>
        <div className={ACTIONS_COLLAPSE}>
          <div className="overflow-hidden">
            <div className={`flex pt-2.5 ${HOVER_ACTIONS}`}>
              {enabled ? (
                <button onClick={onDisable} disabled={busy} className="btn-ghost !py-1 !px-2 text-xs text-terra-500">
                  {busy ? <Loader2 size={13} className="animate-spin" /> : <><Trash2 size={13} /> Disconnect</>}
                </button>
              ) : (
                <button onClick={onEnable} disabled={busy} className="btn-primary !py-1.5 !px-3 text-xs">
                  {busy ? <Loader2 size={13} className="animate-spin" /> : 'Enable'}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function DirectoryCard({ item, health, busy, onManifest, onApprove, onRevoke, onDelete }) {
  return (
    <div className="card card-hover group relative isolate overflow-hidden p-4 flex flex-col gap-3">
      <CardArt />
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5 min-w-0">
          <ConnectorIcon name={item.name} iconUrl={item.icon_url} />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-ink-900 truncate">{item.name}</h3>
            <p className="text-[11px] text-sand-500">
              {item.version ? `v${item.version}` : 'unversioned'}
              {item.approved && item.approved_version ? ` · pinned v${item.approved_version}` : ''}
            </p>
          </div>
        </div>
        <AuthBadge method={item.auth_method} />
      </div>
      {item.summary && <p className="text-xs text-ink-600 leading-snug line-clamp-2">{item.summary}</p>}

      {/* Bottom cluster: status badges ride at the bottom when idle, and lift up as the
          action buttons expand into view on hover. */}
      <div className="mt-auto flex flex-col">
        <div className="flex flex-wrap items-center gap-1.5 transition-transform duration-300">
          {item.approved ? (
            <span className="badge-success gap-1"><ShieldCheck size={11} /> Approved</span>
          ) : (
            <span className="badge bg-sand-500/10 text-sand-600 gap-1"><ShieldQuestion size={11} /> Pending</span>
          )}
          {item.allowed_roles?.length > 0 && (
            <span className="badge bg-violet-500/10 text-violet-500">{item.allowed_roles.join(', ')}</span>
          )}
          {health && (
            <span className={`badge gap-1.5 ${health.cls}`}>
              <StatusDot color={health.dot} pulse={health.label !== 'unknown'} /> {health.label}
            </span>
          )}
        </div>

        <div className={ACTIONS_COLLAPSE}>
          <div className="overflow-hidden">
            <div className={`flex flex-wrap items-center gap-1.5 pt-2.5 ${HOVER_ACTIONS}`}>
              <button onClick={onManifest} className="btn-secondary !py-1.5 !px-2.5 text-xs">
                <FileSearch size={13} /> Manifest
              </button>
              {item.approved ? (
                <button onClick={onRevoke} disabled={busy} className="btn-ghost !py-1.5 !px-2.5 text-xs text-terra-500">
                  {busy ? <Loader2 size={13} className="animate-spin" /> : <><X size={13} /> Revoke</>}
                </button>
              ) : (
                <button onClick={onApprove} className="btn-primary !py-1.5 !px-3 text-xs">
                  <Check size={13} /> Approve
                </button>
              )}
              <button
                onClick={onDelete}
                title="Delete connector"
                className="btn-ghost !p-1.5 ml-auto text-ink-500 hover:text-terra-500"
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
