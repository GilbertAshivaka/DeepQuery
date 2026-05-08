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
      // Map backend 'citations' to frontend 'sources' so they persist on reload
      const messages = (data.messages || []).map((m) => ({
        ...m,
        sources: m.sources || m.citations || [],
      }));
      set({ messages });
    } catch {
      set({ messages: [] });
    }
  },

  startNewConversation: () => {
    set({ activeConversationId: null, messages: [] });
  },

  // ── Streaming chat ──
  sendMessage: (query) => {
    const { activeConversationId, messages, streamController } = get();

    // Cancel any existing stream
    if (streamController) {
      streamController.abort();
    }

    // Add user message optimistically
    const userMessage = {
      id: `temp-user-${Date.now()}`,
      role: 'user',
      content: query,
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
        if (chunk.type === 'token') {
          last.content += chunk.content || '';
        } else if (chunk.type === 'citations') {
          last.sources = chunk.content || [];
        } else if (chunk.type === 'status') {
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
      }
    );

    set({ streamController: controller });
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
