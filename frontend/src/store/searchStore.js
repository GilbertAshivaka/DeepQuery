import { create } from 'zustand';
import * as queryService from '../services/queryService';

export const useSearchStore = create((set) => ({
  // State
  query: '',
  results: [],
  isSearching: false,
  error: null,
  filters: {
    collection: null,
    document_type: null,
  },

  // Actions
  setQuery: (query) => set({ query }),

  setFilter: (key, value) =>
    set((state) => ({
      filters: { ...state.filters, [key]: value },
    })),

  clearFilters: () =>
    set({
      filters: { collection: null, document_type: null },
    }),

  search: async () => {
    const { query, filters } = useSearchStore.getState();
    if (!query.trim()) return;

    set({ isSearching: true, error: null });
    try {
      const cleanFilters = {};
      Object.entries(filters).forEach(([k, v]) => {
        if (v) cleanFilters[k] = v;
      });

      const data = await queryService.search(query, cleanFilters);
      set({ results: data.results || [], isSearching: false });
    } catch (err) {
      set({
        error: err.response?.data?.detail || 'Search failed',
        isSearching: false,
      });
    }
  },

  clearResults: () => set({ results: [], query: '', error: null }),
}));
