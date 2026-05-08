import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import * as authService from '../services/authService';

export const useAuthStore = create(
  persist(
    (set, get) => ({
      // State
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      // Actions
      login: async (username, password) => {
        set({ isLoading: true, error: null });
        try {
          const data = await authService.login(username, password);
          set({
            user: { username: data.username, role: data.role },
            accessToken: data.access_token,
            refreshToken: data.refresh_token,
            isAuthenticated: true,
            isLoading: false,
          });
          localStorage.setItem('access_token', data.access_token);
          return data;
        } catch (err) {
          const message =
            err.response?.data?.detail || 'Login failed. Please try again.';
          set({ error: message, isLoading: false });
          throw err;
        }
      },

      setTokens: (accessToken, refreshToken) => {
        set({ accessToken, refreshToken });
        localStorage.setItem('access_token', accessToken);
      },

      logout: () => {
        const { refreshToken } = get();
        // Clear state immediately so the user is logged out instantly
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          error: null,
        });
        localStorage.removeItem('access_token');
        // Revoke refresh token in background (fire and forget)
        if (refreshToken) {
          authService.logout(refreshToken).catch(() => {});
        }
      },

      clearError: () => set({ error: null }),
    }),
    {
      name: 'deepquery-auth',
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);
