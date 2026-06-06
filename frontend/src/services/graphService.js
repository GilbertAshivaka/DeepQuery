import api from './api';

export const graphService = {
  getOverview: (limit = 50) =>
    api.get('/api/graph/overview', { params: { limit } }),

  searchGraph: (entity, depth = 2, nodeTypes = [], relTypes = []) =>
    api.get('/api/graph/search', {
      params: {
        entity,
        depth,
        ...(nodeTypes.length && { node_types: nodeTypes.join(',') }),
        ...(relTypes.length && { relationship_types: relTypes.join(',') }),
      },
    }),

  getEntityDetail: (entityName) =>
    api.get(`/api/graph/entity/${encodeURIComponent(entityName)}`),
};
