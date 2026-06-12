import api from './api';

/**
 * Connector Infrastructure API (/api/connectors/*).
 * Admin: register, directory, approve/revoke, health.
 * User:  available, enable/disable, OAuth handoff, static credentials.
 */

// ── Registry / directory ────────────────────────────────────
export async function listConnectors() {
  const { data } = await api.get('/api/connectors');
  return data; // [{id, name, version, transport, requires_network}]
}

export async function registerConnector(body) {
  const { data } = await api.post('/api/connectors', body);
  return data; // {id, name, version, transport, requires_network}
}

// Delete a connector from the registry entirely (admin) — purges approval,
// enablements, and credentials, then removes it from the directory.
export async function deleteConnector(connectorId) {
  await api.delete(`/api/connectors/${connectorId}`);
}

export async function getDirectory() {
  const { data } = await api.get('/api/connectors/directory');
  return data; // [{connector_id, name, version, auth_method, approved, approved_version, allowed_roles}]
}

export async function discover(connectorId) {
  const { data } = await api.post(`/api/connectors/${connectorId}/discover`);
  return data; // {connector, server_label, supports, tools[], resources[], prompts[]}
}

// OAuth auto-configuration (§9): discovery chain + Dynamic Client Registration.
// Returns the discovered endpoints/scopes and whether a manual OAuth client is still
// needed (the 🔐 servers without DCR — GitHub/Atlassian/Box).
export async function autoconfigureOAuth(connectorId, { scopes = null, clientName = null } = {}) {
  const { data } = await api.post(`/api/connectors/${connectorId}/oauth/autoconfigure`, {
    scopes,
    client_name: clientName,
  });
  // {authorize_endpoint, token_endpoint, scopes, supports_dcr, client_id, needs_manual_client, message}
  return data;
}

// ── Admin governance (allowlist) ────────────────────────────
export async function approveConnector(connectorId, { allowedRoles = null, version = null } = {}) {
  await api.post(`/api/connectors/${connectorId}/approve`, {
    allowed_roles: allowedRoles,
    version,
  });
}

export async function revokeApproval(connectorId) {
  await api.delete(`/api/connectors/${connectorId}/approve`);
}

// ── User enablement ─────────────────────────────────────────
export async function getAvailable() {
  const { data } = await api.get('/api/connectors/available');
  return data; // [{connector_id, name, version, auth_method, ..., enabled}]
}

export async function enableConnector(connectorId) {
  await api.post(`/api/connectors/${connectorId}/enable`);
}

export async function disableConnector(connectorId) {
  await api.delete(`/api/connectors/${connectorId}/enable`);
}

// ── OAuth handoff + static credentials (§11) ────────────────
export async function authStart(connectorId) {
  const { data } = await api.post(`/api/connectors/${connectorId}/auth/start`);
  return data; // {authorization_url}
}

export async function setCredential(connectorId, body) {
  // body: {method, token? | username?,password? | client_cert_path?,client_key_path?}
  await api.post(`/api/connectors/${connectorId}/credentials`, body);
}

export async function revokeCredential(connectorId) {
  await api.delete(`/api/connectors/${connectorId}/credentials`);
}

export async function getCredentialStatus(connectorId) {
  const { data } = await api.get(`/api/connectors/${connectorId}/credentials/status`);
  return data; // {connector_id, connected}
}

// ── Health & deployment mode ────────────────────────────────
export async function getDeploymentMode() {
  const { data } = await api.get('/api/connectors/deployment-mode');
  return data; // {mode}
}

export async function getHealth(connectorId) {
  const { data } = await api.get(`/api/connectors/${connectorId}/health`);
  return data; // circuit-breaker health (shape varies)
}
