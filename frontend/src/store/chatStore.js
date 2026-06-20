import { create } from 'zustand';
import * as queryService from '../services/queryService';

export const useChatStore = create((set, get) => ({
  // State
  conversations: [],
  activeConversationId: null,
  messages: [],
  isStreaming: false,
  streamController: null,
  isLoadingHistory: false,

  // ── Conversations list ──
  loadConversations: async () => {
    set({ isLoadingHistory: true });
    try {
      const data = await queryService.getConversations(0, 50);
      set({ conversations: data, isLoadingHistory: false });
    } catch {
      set({ isLoadingHistory: false });
    }
  },

  setActiveConversation: async (conversationId) => {
    if (!conversationId) {
      set({ activeConversationId: null, messages: [] });
      return;
    }

    set({ activeConversationId: conversationId });
    try {
      const data = await queryService.getConversation(conversationId);
      // Map backend 'citations' to frontend 'sources' so they persist on reload. A user
      // turn's citations are attachment refs → rehydrate them as chips on the bubble.
      const messages = (data.messages || []).map((m) => {
        const cits = m.sources || m.citations || [];
        if (m.role === 'user') {
          const attachments = cits
            .filter((c) => c.source_type === 'attachment')
            .map((c) => ({ id: c.attachment_id, filename: c.filename, kind: c.kind }));
          return { ...m, attachments };
        }
        return { ...m, sources: cits };
      });
      set({ messages });
    } catch {
      set({ messages: [] });
    }
  },

  startNewConversation: () => {
    set({ activeConversationId: null, messages: [] });
  },

  // ── Streaming chat ──
  // `attachments` = [{ id, filename, kind }] already uploaded to the shared store.
  sendMessage: (query, attachments = []) => {
    const { activeConversationId, messages, streamController } = get();

    // Cancel any existing stream
    if (streamController) {
      streamController.abort();
    }

    // Add user message optimistically (attachments shown as chips on the bubble)
    const userMessage = {
      id: `temp-user-${Date.now()}`,
      role: 'user',
      content: query,
      attachments,
      created_at: new Date().toISOString(),
    };

    // Add placeholder for assistant
    const assistantMessage = {
      id: `temp-assistant-${Date.now()}`,
      role: 'assistant',
      content: '',
      sources: [],
      metadata: {},
      created_at: new Date().toISOString(),
    };

    set({
      messages: [...messages, userMessage, assistantMessage],
      isStreaming: true,
    });

    const controller = queryService.streamChat(
      query,
      activeConversationId,
      // onChunk
      (chunk) => {
        const currentMessages = get().messages;
        const lastIdx = currentMessages.length - 1;
        if (lastIdx < 0) return;

        const updated = [...currentMessages];
        const last = { ...updated[lastIdx] };

        // Handle backend SSE event types: {type, content}
        if (chunk.type === 'answer_token') {
          // NEW: answer_token event (replaces old 'token')
          last.content += chunk.content || '';
        } else if (chunk.type === 'token') {
          // LEGACY: support old token event for backwards compatibility
          last.content += chunk.content || '';
        } else if (chunk.type === 'citations') {
          last.sources = chunk.content || [];
        } else if (chunk.type === 'verification_result') {
          // NEW: verification result from non-blocking self-correction
          const status = chunk.content?.status || 'VERIFIED';
          last.metadata = {
            ...last.metadata,
            self_correction_status: status,
            verification_result: chunk.content,
          };
          // If corrected, show amendments
          if (status === 'CORRECTED' && chunk.content?.amendments) {
            last.content += '\n\n---\n**Corrections Applied:**\n' + chunk.content.amendments;
          }
          // If insufficient context, show message
          if (status === 'INSUFFICIENT_CONTEXT' && chunk.content?.message) {
            last.content += '\n\n---\n⚠️ ' + chunk.content.message;
          }
        } else if (chunk.type === 'cache_hit') {
          // NEW: cache hit indicator
          last.metadata = { ...last.metadata, cache_hit: chunk.content };
        } else if (chunk.type === 'status') {
          // LEGACY: old status event
          last.metadata = { ...last.metadata, self_correction_status: chunk.content };
        } else if (chunk.type === 'related') {
          last.metadata = { ...last.metadata, related_documents: chunk.content };
        } else if (chunk.type === 'done') {
          set({ activeConversationId: chunk.conversation_id });
        } else if (chunk.type === 'error') {
          last.content = `Sorry, something went wrong: ${chunk.content}`;
          last.isError = true;
        }

        // Also support legacy flat format
        if (chunk.token) {
          last.content += chunk.token;
        }
        if (chunk.sources) {
          last.sources = chunk.sources;
        }
        if (chunk.conversation_id && !chunk.type) {
          set({ activeConversationId: chunk.conversation_id });
        }

        updated[lastIdx] = last;
        set({ messages: updated });
      },
      // onDone
      () => {
        set({ isStreaming: false, streamController: null });
        // Refresh conversations list
        get().loadConversations();
      },
      // onError
      (err) => {
        const currentMessages = get().messages;
        const lastIdx = currentMessages.length - 1;
        if (lastIdx >= 0) {
          const updated = [...currentMessages];
          updated[lastIdx] = {
            ...updated[lastIdx],
            content: `Sorry, something went wrong: ${err.message}`,
            isError: true,
          };
          set({ messages: updated });
        }
        set({ isStreaming: false, streamController: null });
      },
      // attachment ids → folded into the answer context as [Attachment N]
      attachments.map((a) => a.id).filter(Boolean)
    );

    set({ streamController: controller });
  },

  // Re-run the last turn (used by the "Try again" affordance on a failed answer): drop the
  // failed assistant reply and its prompting user message, then resend with the same text
  // and attachments.
  retryLast: () => {
    const { messages, isStreaming } = get();
    if (isStreaming || messages.length === 0) return;
    const next = [...messages];
    if (next[next.length - 1]?.role === 'assistant') next.pop();
    const lastUser = next[next.length - 1];
    if (!lastUser || lastUser.role !== 'user') return;
    next.pop();
    set({ messages: next });
    get().sendMessage(lastUser.content, lastUser.attachments || []);
  },

  deleteConversation: async (conversationId) => {
    try {
      await queryService.deleteConversation(conversationId);
      set((s) => ({
        conversations: s.conversations.filter((c) => c.id !== conversationId),
        ...(s.activeConversationId === conversationId
          ? { activeConversationId: null, messages: [] }
          : {}),
      }));
    } catch (err) {
      console.error('Failed to delete conversation:', err);
    }
  },

  togglePinConversation: async (conversationId) => {
    try {
      const result = await queryService.togglePinConversation(conversationId);
      set((s) => ({
        conversations: s.conversations.map((c) =>
          c.id === conversationId ? { ...c, is_pinned: result.is_pinned } : c
        ),
      }));
    } catch (err) {
      console.error('Failed to toggle pin:', err);
    }
  },

  cancelStream: () => {
    const { streamController } = get();
    if (streamController) {
      streamController.abort();
      set({ isStreaming: false, streamController: null });
    }
  },
}));
