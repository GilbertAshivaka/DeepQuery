import { useState } from 'react';
import { Loader2, AlertCircle, ExternalLink, ShieldCheck, KeyRound } from 'lucide-react';
import Modal from '../ui/Modal';
import * as connectorService from '../../services/connectorService';

/**
 * The per-user auth step when enabling a connector (UI guide §11).
 * - oauth2  → a plain-language pre-handoff explanation + launch to the provider.
 * - api_key / basic / mtls → least-privilege static credential entry.
 * In air-gapped mode OAuth is refused upstream; the error surfaces here.
 */
export default function EnableModal({ connector, onClose, onDone }) {
  const id = connector.connector_id || connector.id;
  const method = connector.auth_method || 'none';

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // static credential fields
  const [token, setToken] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [certPath, setCertPath] = useState('');
  const [keyPath, setKeyPath] = useState('');

  const scopes = connector.scopes || connector.auth_config?.scopes || [];

  const startOAuth = async () => {
    setError(null);
    setBusy(true);
    try {
      const { authorization_url } = await connectorService.authStart(id);
      // Hand off to the provider's consent screen (returns to /connectors?connected=1).
      window.location.href = authorization_url;
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not start authentication.');
      setBusy(false);
    }
  };

  const saveCredential = async () => {
    setError(null);
    let body;
    if (method === 'api_key') body = { method, token: token.trim() };
    else if (method === 'basic') body = { method, username: username.trim(), password };
    else if (method === 'mtls') body = { method, client_cert_path: certPath.trim(), client_key_path: keyPath.trim() };
    setBusy(true);
    try {
      await connectorService.setCredential(id, body);
      onDone?.();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save the credential.');
      setBusy(false);
    }
  };

  const isOAuth = method === 'oauth2';

  return (
    <Modal
      title={`Connect ${connector.name}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          {isOAuth ? (
            <button onClick={startOAuth} disabled={busy} className="btn-primary text-sm">
              {busy ? <><Loader2 size={15} className="animate-spin" /> Redirecting…</>
                    : <>Continue <ExternalLink size={14} /></>}
            </button>
          ) : (
            <button onClick={saveCredential} disabled={busy} className="btn-primary text-sm">
              {busy ? <><Loader2 size={15} className="animate-spin" /> Saving…</> : 'Connect'}
            </button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        {error && (
          <div className="flex items-start gap-2 text-terra-500 text-sm bg-terra-500/5 border border-terra-500/20 rounded-lg p-2.5">
            <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {isOAuth ? (
          <>
            <div className="flex items-start gap-2.5">
              <ShieldCheck size={18} className="text-violet-500 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-ink-700 leading-relaxed">
                You'll be sent to <span className="font-medium text-ink-900">{connector.name}</span> to sign in and
                authorize access. Deep Query only requests the access listed below.
              </p>
            </div>
            <div className="rounded-xl border border-cream-200 bg-cream-50/60 p-3.5">
              <p className="text-xs text-sand-500 mb-1.5">This connector will be able to access:</p>
              {scopes.length ? (
                <ul className="space-y-1">
                  {scopes.map((s) => (
                    <li key={s} className="text-xs text-ink-700 font-mono">{s}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-ink-600">The least-privilege scopes this connector declares.</p>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="flex items-start gap-2.5">
              <KeyRound size={18} className="text-violet-500 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-ink-700 leading-relaxed">
                Enter the credential for <span className="font-medium text-ink-900">{connector.name}</span>. It's stored
                encrypted and used only for your requests.
              </p>
            </div>

            {method === 'api_key' && (
              <Field label="API key">
                <input type="password" className="input font-mono text-xs" value={token} onChange={(e) => setToken(e.target.value)} />
              </Field>
            )}
            {method === 'basic' && (
              <>
                <Field label="Username">
                  <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} />
                </Field>
                <Field label="Password">
                  <input type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
                </Field>
              </>
            )}
            {method === 'mtls' && (
              <>
                <Field label="Client certificate path">
                  <input className="input font-mono text-xs" value={certPath} onChange={(e) => setCertPath(e.target.value)} />
                </Field>
                <Field label="Client key path">
                  <input className="input font-mono text-xs" value={keyPath} onChange={(e) => setKeyPath(e.target.value)} />
                </Field>
              </>
            )}
            {method === 'none' && (
              <p className="text-sm text-ink-600">This connector needs no credentials — it's ready to use.</p>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="block text-xs text-sand-500 mb-1">{label}</span>
      {children}
    </label>
  );
}
