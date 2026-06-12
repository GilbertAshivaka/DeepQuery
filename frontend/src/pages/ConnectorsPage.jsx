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
  Plug, Plus, Search, Loader2, Check, X, ShieldCheck, ShieldQuestion, Activity,
  Trash2, FileSearch, Globe, Server, CheckCircle2, AlertCircle,
} from 'lucide-react';

function healthInfo(h) {
  if (!h) return null;
  const state = String(h.state || h.status || '').toLowerCase();
  if (h.healthy === true || state === 'closed' || state === 'healthy')
    return { label: 'healthy', cls: 'bg-forest-500/10 text-forest-500' };
  if (state === 'half_open' || state === 'degraded')
    return { label: 'degraded', cls: 'bg-sand-500/10 text-sand-600' };
  if (h.healthy === false || state === 'open' || state === 'unavailable')
    return { label: 'unavailable', cls: 'bg-terra-500/10 text-terra-500' };
  return { label: state || 'unknown', cls: 'bg-cream-200 text-ink-600' };
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
      <div className="flex-1 min-w-0 flex flex-col h-full">
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

function AvailableCard({ item, busy, onEnable, onDisable }) {
  const enabled = !!item.enabled;
  return (
    <div className="card p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink-900 truncate">{item.name}</h3>
          {item.version && <p className="text-[11px] text-sand-500">v{item.version}</p>}
        </div>
        <AuthBadge method={item.auth_method} />
      </div>
      <div className="flex items-center justify-between mt-auto">
        {enabled ? (
          <span className="badge-success gap-1"><Check size={11} /> Enabled</span>
        ) : <span className="badge bg-cream-200 text-ink-600">Not enabled</span>}
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
  );
}

function DirectoryCard({ item, health, busy, onManifest, onApprove, onRevoke, onDelete }) {
  return (
    <div className="card p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink-900 truncate">{item.name}</h3>
          <p className="text-[11px] text-sand-500">
            {item.version ? `v${item.version}` : 'unversioned'}
            {item.approved && item.approved_version ? ` · pinned v${item.approved_version}` : ''}
          </p>
        </div>
        <AuthBadge method={item.auth_method} />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {item.approved ? (
          <span className="badge-success gap-1"><ShieldCheck size={11} /> Approved</span>
        ) : (
          <span className="badge bg-sand-500/10 text-sand-600 gap-1"><ShieldQuestion size={11} /> Pending</span>
        )}
        {item.allowed_roles?.length > 0 && (
          <span className="badge bg-violet-500/10 text-violet-500">{item.allowed_roles.join(', ')}</span>
        )}
        {health && (
          <span className={`badge gap-1 ${health.cls}`}><Activity size={11} /> {health.label}</span>
        )}
      </div>

      <div className="flex items-center gap-1.5 mt-auto">
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
  );
}
