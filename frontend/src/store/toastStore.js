import { create } from 'zustand';

// Lightweight, ephemeral notifications (errors, info). Not persisted — they slide in
// top-right, auto-dismiss, and are manually dismissible. Use for user-facing errors
// that shouldn't live permanently in a conversation.
let _seq = 0;

export const useToastStore = create((set, get) => ({
  toasts: [], // [{id, type, title, message}]

  addToast: ({ type = 'error', title, message, duration = 6000 }) => {
    const id = ++_seq;
    set((s) => ({ toasts: [...s.toasts, { id, type, title, message }] }));
    if (duration > 0) {
      setTimeout(() => get().dismiss(id), duration);
    }
    return id;
  },

  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  clear: () => set({ toasts: [] }),
}));

// Convenience helpers for non-component callers (e.g. stores/services).
export const toastError = (message, title) =>
  useToastStore.getState().addToast({ type: 'error', title, message });
export const toastInfo = (message, title) =>
  useToastStore.getState().addToast({ type: 'info', title, message, duration: 4000 });
export const toastSuccess = (message, title) =>
  useToastStore.getState().addToast({ type: 'success', title, message, duration: 4000 });
