import api from './api';

export async function getSimilarityMap() {
  const { data } = await api.get('/api/documents/similarity-map');
  return data;
}
