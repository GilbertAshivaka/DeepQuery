import api from './api';

/**
 * Run the Orchestrator agent via SSE (POST /api/agents/run).
 *
 * EventSource can't set the Authorization header, so we use fetch + a stream
 * reader (the same pattern as queryService.streamChat). Each SSE frame is
 * `data: {json}\n\n`; we parse and hand the typed event to onEvent.
 *
 * Returns an AbortController — aborting it stops the run (handoff §4: the
 * backend cancels, the user turn is kept, the assistant turn is not saved).
 */
export function runAgent({ query, conversationId, attachmentIds }, onEvent, onDone, onError) {
  const controller = new AbortController();

  const body = { query };
  if (conversationId) body.conversation_id = conversationId;
  if (attachmentIds?.length) body.attachment_ids = attachmentIds;

  const token = localStorage.getItem('access_token');

  fetch('/api/agents/run', {
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
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6);
          if (payload === '[DONE]') {
            onDone?.();
            return;
          }
          try {
            onEvent?.(JSON.parse(payload));
          } catch {
            // ignore malformed frames
          }
        }
      }

      onDone?.();
    })
    .catch((err) => {
      if (err.name !== 'AbortError') onError?.(err);
    });

  return controller;
}

/**
 * Resume a paused durable run via SSE (POST /api/agents/threads/{id}/resume).
 *
 * The continuation streams on the SAME thread (step_status → reasoning →
 * answer_token×N → action_result → done), so the agent reports back what it did
 * in the same conversation. `body` is one of:
 *   { decision: 'approve'|'reject' }                  — single gate
 *   { batch_decisions: { [pending_id]: 'approve'|'reject' } } — batch gate (R6)
 *   { answer: '<the user's reply>' }                   — question gate (R7)
 *
 * Same fetch+reader pattern as runAgent (EventSource can't set the auth header).
 * Returns an AbortController.
 */
export function resumeThread(threadId, body, onEvent, onDone, onError) {
  return streamSSE(`/api/agents/threads/${threadId}/resume`, {
    method: 'POST',
    body: JSON.stringify(body || {}),
  }, onEvent, onDone, onError);
}

/**
 * Subscribe to a run's live event stream (GET /api/agents/threads/{id}/events).
 *
 * Replays from `lastEventId` (via ?last_event_id=) then tails live, so the UI can
 * reattach after a reload/disconnect. Each frame carries an SSE `id:`; we surface
 * it as `event.__seq` so the caller can track the cursor. Returns an AbortController.
 */
export function subscribeThreadEvents(threadId, lastEventId, onEvent, onDone, onError) {
  const qs = lastEventId ? `?last_event_id=${encodeURIComponent(lastEventId)}` : '';
  return streamSSE(`/api/agents/threads/${threadId}/events${qs}`, { method: 'GET' },
    onEvent, onDone, onError);
}

/** Steer a running controller run (JSON, not SSE). mode ∈ augment|cancel_step|cancel_run. */
export async function interjectThread(threadId, message, mode = 'augment') {
  const { data } = await api.post(`/api/agents/threads/${threadId}/interject`, { message, mode });
  return data; // {thread_id, queued, mode}
}

/** One-GET paint snapshot of a run (GET /api/agents/threads/{id}/state). */
export async function getThreadState(threadId) {
  const { data } = await api.get(`/api/agents/threads/${threadId}/state`);
  return data; // {run_status, plan, trace, answer, citations, pending_approval, ...}
}

/**
 * Shared SSE driver: fetch + stream-reader, parsing `data:`/`id:` frames. Tracks
 * the SSE `id:` and attaches it to each event as `__seq` (for reconnect cursors).
 * Returns an AbortController — abort to stop reading (the run continues server-side).
 */
function streamSSE(url, init, onEvent, onDone, onError) {
  const controller = new AbortController();
  const token = localStorage.getItem('access_token');

  fetch(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(init.headers || {}),
    },
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
      let lastSeq = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        // SSE frames are separated by a blank line; split on \n and track id:/data:.
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('id: ')) {
            lastSeq = line.slice(4).trim();
            continue;
          }
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6);
          if (payload === '[DONE]') {
            onDone?.(lastSeq);
            return;
          }
          try {
            const event = JSON.parse(payload);
            if (lastSeq != null) event.__seq = lastSeq;
            onEvent?.(event);
          } catch {
            // ignore malformed / heartbeat frames
          }
        }
      }
      onDone?.(lastSeq);
    })
    .catch((err) => {
      if (err.name !== 'AbortError') onError?.(err);
    });

  return controller;
}

// ── Attachments (user-provided docs/images) ─────────────────
export async function uploadAttachment(file, conversationId) {
  const form = new FormData();
  form.append('file', file);
  if (conversationId) form.append('conversation_id', conversationId);
  // Let the browser set the multipart boundary — don't force the content-type.
  const { data } = await api.post('/api/agents/attachments', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data; // {id, filename, kind, chars}
}

export async function getAttachment(id) {
  const { data } = await api.get(`/api/agents/attachments/${id}`);
  return data; // metadata + extracted_text
}

// The raw file as a Blob (authed). Callers wrap it in an object URL for an
// <img>/<iframe> src — those can't carry the Authorization header themselves.
export async function getAttachmentBlob(id) {
  const { data } = await api.get(`/api/agents/attachments/${id}/content`, {
    responseType: 'blob',
  });
  return data;
}

// Download a produced deliverable (or any authed file URL) to disk. Fetches the blob
// with the auth header (a plain <a href> can't), then triggers a browser save.
export async function downloadFile(url, filename) {
  const { data } = await api.get(url, { responseType: 'blob' });
  const objectUrl = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename || 'document';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

// ── Conversation history (separate store from chat) ──────────
export async function getConversations() {
  const { data } = await api.get('/api/agents/conversations');
  return data;
}

export async function getConversation(conversationId) {
  const { data } = await api.get(`/api/agents/conversations/${conversationId}`);
  return data;
}

export async function deleteConversation(conversationId) {
  const { data } = await api.delete(`/api/agents/conversations/${conversationId}`);
  return data;
}

// ── Approval-gate resume (returns JSON, not SSE) ─────────────
export async function approveAction(pendingId) {
  const { data } = await api.post(`/api/agents/actions/${pendingId}/approve`);
  return data;
}

export async function rejectAction(pendingId) {
  const { data } = await api.post(`/api/agents/actions/${pendingId}/reject`);
  return data;
}

// ── Health (model slots, capabilities, deployment mode) ──────
export async function getHealth() {
  const { data } = await api.get('/api/agents/health');
  return data;
}
