import api from './api';

// ── Account (self-service) ───────────────────────────────────────
export async function getMe() {
  const { data } = await api.get('/auth/me');
  return data;
}

export async function updateProfile(payload) {
  // payload: { full_name?, email? }
  const { data } = await api.patch('/auth/me', payload);
  return data;
}

export async function changePassword(currentPassword, newPassword) {
  const { data } = await api.post('/auth/me/password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
  return data;
}

// ── Model config (admin) ─────────────────────────────────────────
export async function getModelConfig() {
  const { data } = await api.get('/api/admin/model-config');
  return data;
}

export async function setRoleConfig(role, payload) {
  // payload: { provider, model, base_url?, params? }
  const { data } = await api.put(`/api/admin/model-config/${role}`, payload);
  return data;
}

export async function testRoleConfig(role, payload) {
  // payload: { provider, model, base_url? }
  const { data } = await api.post(`/api/admin/model-config/${role}/test`, payload);
  return data;
}

// ── Reasoning / extended-thinking toggle (admin) ─────────────────
export async function getThinkingConfig() {
  const { data } = await api.get('/api/admin/model-config/thinking');
  return data;
}

export async function setThinkingConfig(enabled) {
  const { data } = await api.put('/api/admin/model-config/thinking', { enabled });
  return data;
}

// ── Provider keys / BYOK (admin) ─────────────────────────────────
export async function getProviderKeys() {
  const { data } = await api.get('/api/admin/provider-keys');
  return data;
}

export async function setProviderKey(provider, apiKey) {
  const { data } = await api.put(`/api/admin/provider-keys/${provider}`, {
    api_key: apiKey,
  });
  return data;
}

export async function deleteProviderKey(provider) {
  const { data } = await api.delete(`/api/admin/provider-keys/${provider}`);
  return data;
}

// ── Embeddings / re-index (admin) ────────────────────────────────
export async function getEmbeddingConfig() {
  const { data } = await api.get('/api/admin/embedding');
  return data;
}

export async function startReindex(payload) {
  // payload: { provider, model, dimensions, base_url? }
  const { data } = await api.post('/api/admin/embedding/reindex', payload);
  return data;
}

export async function getReindexStatus() {
  const { data } = await api.get('/api/admin/embedding/reindex/status');
  return data;
}
