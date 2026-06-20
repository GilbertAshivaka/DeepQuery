import api from './api';

/**
 * Stream a chat response via SSE.
 * Returns an AbortController so caller can cancel.
 */
export function streamChat(query, conversationId, onChunk, onDone, onError, attachmentIds) {
  const controller = new AbortController();

  const body = { query };
  if (conversationId) {
    body.conversation_id = conversationId;
  }
  if (attachmentIds?.length) {
    body.attachment_ids = attachmentIds;
  }

  const token = localStorage.getItem('access_token');

  fetch('/api/query/chat', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const payload = line.slice(6);
            if (payload === '[DONE]') {
              onDone?.();
              return;
            }
            try {
              const parsed = JSON.parse(payload);
              onChunk?.(parsed);
            } catch {
              // Non-JSON data chunk (plain text token)
              onChunk?.({ token: payload });
            }
          }
        }
      }

      onDone?.();
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError?.(err);
      }
    });

  return controller;
}

/**
 * Structured search (non-streaming)
 */
export async function search(query, filters = {}) {
  const body = { query, ...filters };
  const { data } = await api.post('/api/query/search', body);
  return data;
}

/**
 * Get conversation history list
 */
export async function getConversations(skip = 0, limit = 20) {
  const { data } = await api.get('/api/query/history', { params: { skip, limit } });
  return data;
}

/**
 * Get single conversation with messages
 */
export async function getConversation(conversationId) {
  const { data } = await api.get(`/api/query/conversations/${conversationId}`);
  return data;
}

/**
 * Delete a conversation
 */
export async function deleteConversation(conversationId) {
  const { data } = await api.delete(`/api/query/conversations/${conversationId}`);
  return data;
}

/**
 * Toggle pin status of a conversation
 */
export async function togglePinConversation(conversationId) {
  const { data } = await api.patch(`/api/query/conversations/${conversationId}/pin`);
  return data;
}
