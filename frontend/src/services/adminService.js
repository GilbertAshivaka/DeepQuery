import api from './api';

// ── Users ──
export async function getUsers(skip = 0, limit = 50) {
  const { data } = await api.get('/api/admin/users', { params: { skip, limit } });
  return data;
}

export async function createUser(userData) {
  const { data } = await api.post('/api/admin/users', userData);
  return data;
}

export async function updateUser(userId, userData) {
  const { data } = await api.put(`/api/admin/users/${userId}`, userData);
  return data;
}

export async function deleteUser(userId) {
  await api.delete(`/api/admin/users/${userId}`);
}

// ── Stats ──
export async function getStats() {
  const { data } = await api.get('/api/admin/stats');
  return data;
}

// ── Analytics ──
export async function getTrendingTopics(days = 7) {
  const { data } = await api.get('/api/admin/trending-topics', { params: { days } });
  return data;
}

export async function getKnowledgeGaps(days = 30) {
  const { data } = await api.get('/api/admin/knowledge-gaps', { params: { days } });
  return data;
}

// ── Knowledge Graph ──
export async function getEntities(skip = 0, limit = 50) {
  const { data } = await api.get('/api/graph/entities', { params: { skip, limit } });
  return data;
}

export async function getEntity(entityId) {
  const { data } = await api.get(`/api/graph/entity/${entityId}`);
  return data;
}
