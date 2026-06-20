import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import * as settingsService from '../services/settingsService';
import { toastError, toastSuccess } from './toastStore';

/**
 * Settings store.
 *
 * Two concerns live here:
 *  - Client-side **appearance** prefs (persisted in localStorage, like authStore).
 *  - Server-side **admin config** (model roles, provider keys, embeddings, thinking) —
 *    loaded on demand, never persisted.
 */
export const useSettingsStore = create(
  persist(
    (set, get) => ({
      // ── Appearance (persisted) ──
      appearance: {
        sidebarDefaultOpen: true,
        thinkingPanelDefaultExpanded: true,
        density: 'comfortable', // 'comfortable' | 'compact'
      },
      setAppearance: (patch) =>
        set((s) => ({ appearance: { ...s.appearance, ...patch } })),

      // ── Server config (not persisted) ──
      modelConfig: null, // GET /model-config payload
      thinking: null, // GET /model-config/thinking payload
      providerKeys: null, // GET /provider-keys payload
      embedding: null, // GET /embedding payload
      loading: { models: false, keys: false, embedding: false },
      savingRole: null, // role currently being saved

      // ── Model config ──
      loadModelConfig: async () => {
        set((s) => ({ loading: { ...s.loading, models: true } }));
        try {
          const [cfg, thinking] = await Promise.all([
            settingsService.getModelConfig(),
            settingsService.getThinkingConfig().catch(() => null),
          ]);
          set((s) => ({
            modelConfig: cfg,
            thinking,
            loading: { ...s.loading, models: false },
          }));
        } catch (err) {
          set((s) => ({ loading: { ...s.loading, models: false } }));
          toastError(
            err?.response?.data?.detail || 'Failed to load model configuration.',
            'Settings'
          );
        }
      },

      testRole: async (role, payload) => {
        // Returns the probe result; caller renders it. Never throws to the UI.
        try {
          return await settingsService.testRoleConfig(role, payload);
        } catch (err) {
          return {
            ok: false,
            error: err?.response?.data?.detail || err?.message || 'Test failed.',
            kind: 'runtime',
          };
        }
      },

      saveRole: async (role, payload) => {
        set({ savingRole: role });
        try {
          await settingsService.setRoleConfig(role, payload);
          await get().loadModelConfig();
          toastSuccess(`${role} model updated.`, 'Settings');
          return true;
        } catch (err) {
          toastError(
            err?.response?.data?.detail || 'Failed to save model.',
            'Settings'
          );
          return false;
        } finally {
          set({ savingRole: null });
        }
      },

      setThinking: async (enabled) => {
        // optimistic
        const prev = get().thinking;
        set({ thinking: { ...(prev || {}), enabled, source: 'db' } });
        try {
          await settingsService.setThinkingConfig(enabled);
          toastSuccess(
            `Extended thinking ${enabled ? 'enabled' : 'disabled'}.`,
            'Settings'
          );
        } catch (err) {
          set({ thinking: prev });
          toastError(
            err?.response?.data?.detail || 'Failed to update thinking setting.',
            'Settings'
          );
        }
      },

      // ── Provider keys ──
      loadProviderKeys: async () => {
        set((s) => ({ loading: { ...s.loading, keys: true } }));
        try {
          const data = await settingsService.getProviderKeys();
          set((s) => ({ providerKeys: data, loading: { ...s.loading, keys: false } }));
        } catch (err) {
          set((s) => ({ loading: { ...s.loading, keys: false } }));
          toastError(
            err?.response?.data?.detail || 'Failed to load provider keys.',
            'Settings'
          );
        }
      },

      saveProviderKey: async (provider, apiKey) => {
        try {
          await settingsService.setProviderKey(provider, apiKey);
          await Promise.all([get().loadProviderKeys(), get().loadModelConfig()]);
          toastSuccess(`Key saved for ${provider}.`, 'Settings');
          return true;
        } catch (err) {
          toastError(
            err?.response?.data?.detail || 'Failed to save key.',
            'Settings'
          );
          return false;
        }
      },

      removeProviderKey: async (provider) => {
        try {
          await settingsService.deleteProviderKey(provider);
          await Promise.all([get().loadProviderKeys(), get().loadModelConfig()]);
          toastSuccess(`Reverted ${provider} to managed key.`, 'Settings');
          return true;
        } catch (err) {
          toastError(
            err?.response?.data?.detail || 'Failed to remove key.',
            'Settings'
          );
          return false;
        }
      },

      // ── Embeddings ──
      loadEmbedding: async () => {
        set((s) => ({ loading: { ...s.loading, embedding: true } }));
        try {
          const data = await settingsService.getEmbeddingConfig();
          set((s) => ({ embedding: data, loading: { ...s.loading, embedding: false } }));
        } catch (err) {
          set((s) => ({ loading: { ...s.loading, embedding: false } }));
          toastError(
            err?.response?.data?.detail || 'Failed to load embedding config.',
            'Settings'
          );
        }
      },

      startReindex: async (payload) => {
        try {
          const res = await settingsService.startReindex(payload);
          toastSuccess('Re-index started.', 'Embeddings');
          return res;
        } catch (err) {
          toastError(
            err?.response?.data?.detail || 'Failed to start re-index.',
            'Embeddings'
          );
          return null;
        }
      },

      refreshReindexStatus: async () => {
        try {
          const status = await settingsService.getReindexStatus();
          set((s) => ({
            embedding: s.embedding
              ? { ...s.embedding, reindex_status: status }
              : s.embedding,
          }));
          return status;
        } catch {
          return null;
        }
      },
    }),
    {
      name: 'deepquery-settings',
      partialize: (state) => ({ appearance: state.appearance }),
    }
  )
);
