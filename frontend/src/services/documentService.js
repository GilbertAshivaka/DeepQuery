import api from './api';

export async function uploadDocument(file, collection, onProgress) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('collection', collection);

  const { data } = await api.post('/api/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded * 100) / e.total));
      }
    },
  });
  return data;
}

export async function getDocuments(page = 1, perPage = 20) {
  const { data } = await api.get('/api/documents/', { params: { page, per_page: perPage } });
  return data;
}

export async function getDocument(id) {
  const { data } = await api.get(`/api/documents/${id}`);
  return data;
}

export async function deleteDocument(id) {
  await api.delete(`/api/documents/${id}`);
}

export function getDocumentFileUrl(id) {
  const token = localStorage.getItem('access_token');
  return `/api/documents/${id}/file?token=${encodeURIComponent(token)}`;
}

export async function getDocumentFileBlob(id) {
  const { data } = await api.get(`/api/documents/${id}/file`, { responseType: 'blob' });
  return data;
}

export async function getIngestionStatus(jobId) {
  const { data } = await api.get(`/api/documents/status/${jobId}`);
  return data;
}
