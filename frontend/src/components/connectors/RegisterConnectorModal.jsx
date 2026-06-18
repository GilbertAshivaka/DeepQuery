import { useState } from 'react';
import { Loader2, AlertCircle, ShieldCheck, KeyRound, CheckCircle2 } from 'lucide-react';
import Modal from '../ui/Modal';
import * as connectorService from '../../services/connectorService';

// Parse "KEY=VALUE" / "Key: Value" lines into an object.
function parseKeyVals(text, sep = '=') {
  const out = {};
  (text || '').split('\n').forEach((line) => {
    const t = line.trim();
    if (!t) return;
    const i = t.indexOf(sep);
    if (i === -1) return;
    out[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  });
  return out;
}

const TRANSPORTS = ['http', 'sse', 'stdio'];
const AUTH_METHODS = ['none', 'oauth2', 'api_key', 'basic', 'mtls'];

/**
 * Add a connector. The happy path is just a URL + auth method (§9): for an OAuth
 * connector we register, then call oauth/autoconfigure (discovery + Dynamic Client
 * Registration). Manual OAuth fields appear only as a fallback — when the server
 * needs a hand-made client (needs_manual_client) or discovery fails.
 */
export default function RegisterConnectorModal({ onClose, onRegistered }) {
  // step: 'form' → (oauth) 'manualClient' (DCR unsupported) | 'manualFallback' (discovery failed)
  const [step, setStep] = useState('form');

  const [name, setName] = useState('');
  const [summary, setSummary] = useState('');
  const [transport, setTransport] = useState('http');
  const [version, setVersion] = useState('');
  const [requiresNetwork, setRequiresNetwork] = useState(true);
  const [authMethod, setAuthMethod] = useState('none');

  // stdio endpoint
  const [command, setCommand] = useState('');
  const [args, setArgs] = useState('');
  const [env, setEnv] = useState('');
  // http/sse endpoint
  const [url, setUrl] = useState('');
  const [headers, setHeaders] = useState('');

  // OAuth manual fields (fallback)
  const [authorizeEndpoint, setAuthorizeEndpoint] = useState('');
  const [tokenEndpoint, setTokenEndpoint] = useState('');
  const [scopes, setScopes] = useState('');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');

  const [created, setCreated] = useState(null); // {id, name}
  const [discovered, setDiscovered] = useState(null); // autoconfigure response
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [statusMsg, setStatusMsg] = useState(null);

  const isNetworkTransport = transport === 'http' || transport === 'sse';

  const buildEndpoint = () =>
    transport === 'stdio'
      ? { command: command.trim(), args: args.trim() ? args.trim().split(/\s+/) : [], env: parseKeyVals(env) }
      : { url: url.trim(), headers: parseKeyVals(headers, ':') };

  // Step 1: register, then (for OAuth) try auto-configuration.
  const handleRegister = async () => {
    setError(null);
    if (!name.trim()) return setError('A name is required.');
    if (isNetworkTransport && !url.trim()) return setError('A server URL is required.');

    setBusy(true);
    try {
      const createdConn = await connectorService.registerConnector({
        name: name.trim(),
        summary: summary.trim() || null,
        transport,
        endpoint: buildEndpoint(),
        version: version.trim() || null,
        requires_network: requiresNetwork,
        auth_method: authMethod,
        auth_config: null,
      });
      setCreated(createdConn);

      if (authMethod !== 'oauth2') {
        onRegistered?.(createdConn);
        return;
      }

      // OAuth: auto-configure from the server URL.
      setStatusMsg('Discovering OAuth configuration…');
      try {
        const res = await connectorService.autoconfigureOAuth(createdConn.id, { clientName: name.trim() });
        setDiscovered(res);
        setAuthorizeEndpoint(res.authorize_endpoint || '');
        setTokenEndpoint(res.token_endpoint || '');
        setScopes(Array.isArray(res.scopes) ? res.scopes.join(' ') : (res.scopes || ''));
        if (res.needs_manual_client) {
          setStatusMsg(res.message || 'This server needs a manually-created OAuth app.');
          setStep('manualClient');
        } else {
          // DCR succeeded — fully configured.
          onRegistered?.(createdConn);
        }
      } catch (e) {
        setStatusMsg(e.response?.data?.detail || 'Automatic OAuth discovery did not work — enter the details manually.');
        setStep('manualFallback');
      }
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to register the connector.');
    } finally {
      setBusy(false);
    }
  };

  // Step 2: persist the manually-supplied OAuth client (re-register = update).
  const handleSaveClient = async (withEndpoints) => {
    setError(null);
    setBusy(true);
    try {
      const updated = await connectorService.registerConnector({
        name: created.name,
        summary: summary.trim() || null,
        transport,
        endpoint: buildEndpoint(),
        version: version.trim() || null,
        requires_network: requiresNetwork,
        auth_method: 'oauth2',
        auth_config: {
          authorize_endpoint: (withEndpoints ? authorizeEndpoint : discovered?.authorize_endpoint) || authorizeEndpoint,
          token_endpoint: (withEndpoints ? tokenEndpoint : discovered?.token_endpoint) || tokenEndpoint,
          scopes: scopes.trim() ? scopes.trim().split(/[\s,]+/) : [],
          client_id: clientId.trim(),
          ...(clientSecret.trim() ? { client_secret: clientSecret.trim() } : {}),
        },
      });
      onRegistered?.(updated || created);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save the OAuth client.');
      setBusy(false);
    }
  };

  // ── Footer per step ──
  let footer;
  if (step === 'form') {
    footer = (
      <>
        <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
        <button onClick={handleRegister} disabled={busy} className="btn-primary text-sm">
          {busy ? <><Loader2 size={15} className="animate-spin" /> {statusMsg || 'Registering…'}</> : 'Register'}
        </button>
      </>
    );
  } else {
    const withEndpoints = step === 'manualFallback';
    footer = (
      <>
        <button onClick={onClose} className="btn-secondary text-sm">Done later</button>
        <button onClick={() => handleSaveClient(withEndpoints)} disabled={busy} className="btn-primary text-sm">
          {busy ? <><Loader2 size={15} className="animate-spin" /> Saving…</> : 'Save OAuth client'}
        </button>
      </>
    );
  }

  return (
    <Modal title="Add a connector" onClose={onClose} maxWidth="max-w-xl" footer={footer}>
      <div className="space-y-4">
        {error && (
          <div className="flex items-start gap-2 text-terra-500 text-sm bg-terra-500/5 border border-terra-500/20 rounded-lg p-2.5">
            <AlertCircle size={15} className="flex-shrink-0 mt-0.5" /><span>{error}</span>
          </div>
        )}

        {step === 'form' && (
          <>
            <Field label="Name">
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Linear" />
            </Field>

            <Field label="Description (helps the agent pick this connector)">
              <textarea className="input text-sm" rows={2} value={summary} onChange={(e) => setSummary(e.target.value)}
                        placeholder="e.g. Linear issue tracker — search and read issues, projects, and comments." />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Transport">
                <select className="input" value={transport} onChange={(e) => setTransport(e.target.value)}>
                  {TRANSPORTS.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </Field>
              <Field label="Auth method">
                <select className="input" value={authMethod} onChange={(e) => setAuthMethod(e.target.value)}>
                  {AUTH_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </Field>
            </div>

            {/* Endpoint — URL for network transports, command for stdio */}
            {isNetworkTransport ? (
              <Field label="Server URL">
                <input className="input font-mono text-xs" value={url} onChange={(e) => setUrl(e.target.value)}
                       placeholder="https://mcp.linear.app/mcp" />
              </Field>
            ) : (
              <>
                <Field label="Command">
                  <input className="input font-mono text-xs" value={command} onChange={(e) => setCommand(e.target.value)}
                         placeholder="path\to\venv\Scripts\server.exe" />
                </Field>
                <Field label="Arguments (space-separated)">
                  <input className="input font-mono text-xs" value={args} onChange={(e) => setArgs(e.target.value)} placeholder="--port 8000" />
                </Field>
                <Field label="Environment (KEY=VALUE per line, optional)">
                  <textarea className="input font-mono text-xs" rows={2} value={env} onChange={(e) => setEnv(e.target.value)} />
                </Field>
              </>
            )}

            {authMethod === 'oauth2' && (
              <div className="flex items-start gap-2 rounded-xl border border-violet-500/20 bg-violet-500/5 p-3">
                <ShieldCheck size={16} className="text-violet-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-ink-600 leading-relaxed">
                  OAuth endpoints, scopes, and client will be discovered and configured automatically from the
                  server URL. You'll only be asked for a client id/secret if the server can't self-register one.
                </p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 items-end">
              <Field label="Version (optional)">
                <input className="input" value={version} onChange={(e) => setVersion(e.target.value)} placeholder="1.0.0" />
              </Field>
              <label className="flex items-center gap-2 text-sm text-ink-700 pb-2.5">
                <input type="checkbox" checked={requiresNetwork} onChange={(e) => setRequiresNetwork(e.target.checked)} className="accent-violet-500" />
                Requires network
              </label>
            </div>

            {isNetworkTransport && (
              <Field label="Headers (Key: Value per line, optional)">
                <textarea className="input font-mono text-xs" rows={2} value={headers} onChange={(e) => setHeaders(e.target.value)}
                          placeholder={'Authorization: Bearer …'} />
              </Field>
            )}
          </>
        )}

        {/* Manual OAuth client — DCR unsupported (endpoints discovered, shown read-only) */}
        {step === 'manualClient' && (
          <>
            <div className="flex items-start gap-2 rounded-xl border border-sand-500/30 bg-sand-500/5 p-3">
              <KeyRound size={16} className="text-sand-600 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-ink-600 leading-relaxed">
                {statusMsg || 'This server needs an OAuth app you create. Its endpoints were discovered for you — paste the client id/secret from the app you registered with the provider.'}
              </p>
            </div>
            <Readonly label="Authorize endpoint" value={discovered?.authorize_endpoint} />
            <Readonly label="Token endpoint" value={discovered?.token_endpoint} />
            <Readonly label="Scopes" value={Array.isArray(discovered?.scopes) ? discovered.scopes.join(' ') : discovered?.scopes} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Client ID">
                <input className="input font-mono text-xs" value={clientId} onChange={(e) => setClientId(e.target.value)} />
              </Field>
              <Field label="Client secret">
                <input type="password" className="input font-mono text-xs" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} />
              </Field>
            </div>
          </>
        )}

        {/* Manual OAuth fallback — discovery failed, enter everything */}
        {step === 'manualFallback' && (
          <>
            <div className="flex items-start gap-2 rounded-xl border border-sand-500/30 bg-sand-500/5 p-3">
              <AlertCircle size={16} className="text-sand-600 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-ink-600 leading-relaxed">
                {statusMsg || 'Automatic discovery did not work — enter the OAuth details manually.'}
              </p>
            </div>
            <Field label="Authorize endpoint">
              <input className="input font-mono text-xs" value={authorizeEndpoint} onChange={(e) => setAuthorizeEndpoint(e.target.value)} />
            </Field>
            <Field label="Token endpoint">
              <input className="input font-mono text-xs" value={tokenEndpoint} onChange={(e) => setTokenEndpoint(e.target.value)} />
            </Field>
            <Field label="Scopes (space-separated)">
              <input className="input font-mono text-xs" value={scopes} onChange={(e) => setScopes(e.target.value)} placeholder="read:tickets read:projects" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Client ID">
                <input className="input font-mono text-xs" value={clientId} onChange={(e) => setClientId(e.target.value)} />
              </Field>
              <Field label="Client secret">
                <input type="password" className="input font-mono text-xs" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} />
              </Field>
            </div>
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

function Readonly({ label, value }) {
  return (
    <div>
      <span className="block text-xs text-sand-500 mb-1 inline-flex items-center gap-1">
        <CheckCircle2 size={11} className="text-forest-500" /> {label} (discovered)
      </span>
      <div className="input font-mono text-xs bg-cream-50 text-ink-600 truncate">{value || '—'}</div>
    </div>
  );
}
