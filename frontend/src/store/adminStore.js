import { create } from 'zustand';
import * as adminService from '../services/adminService';
import * as documentService from '../services/documentService';

export const useAdminStore = create((set, get) => ({
  // State
  users: [],
  documents: [],
  stats: null,
  trendingTopics: [],
  knowledgeGaps: [],
  entities: [],
  isLoading: false,
  activeTab: 'upload',
  uploadJobs: [], // { jobId, fileName, status, progress }

  // ── Tab ──
  setActiveTab: (tab) => set({ activeTab: tab }),

  // ── Users ──
  loadUsers: async () => {
    set({ isLoading: true });
    try {
      const data = await adminService.getUsers();
      set({ users: data, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  createUser: async (userData) => {
    const data = await adminService.createUser(userData);
    set((s) => ({ users: [...s.users, data] }));
    return data;
  },

  updateUser: async (userId, userData) => {
    const data = await adminService.updateUser(userId, userData);
    set((s) => ({
      users: s.users.map((u) => (u.id === userId ? data : u)),
    }));
    return data;
  },

  deleteUser: async (userId) => {
    await adminService.deleteUser(userId);
    set((s) => ({
      users: s.users.filter((u) => u.id !== userId),
    }));
  },

  // ── Documents ──
  loadDocuments: async () => {
    set({ isLoading: true });
    try {
      const data = await documentService.getDocuments(1, 100);
      set({ documents: data.documents || [], isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  uploadDocument: async (file, collection) => {
    const tempId = `upload-${Date.now()}`;
    set((s) => ({
      uploadJobs: [
        ...s.uploadJobs,
        { id: tempId, fileName: file.name, status: 'uploading', progress: 0 },
      ],
    }));

    try {
      const data = await documentService.uploadDocument(file, collection, (progress) => {
        set((s) => ({
          uploadJobs: s.uploadJobs.map((j) =>
            j.id === tempId ? { ...j, progress } : j
          ),
        }));
      });

      set((s) => ({
        uploadJobs: s.uploadJobs.map((j) =>
          j.id === tempId
            ? { ...j, jobId: data.job_id, status: 'processing', progress: 100 }
            : j
        ),
      }));

      // Poll for completion
      get().pollJobStatus(tempId, data.job_id);
      return data;
    } catch (err) {
      set((s) => ({
        uploadJobs: s.uploadJobs.map((j) =>
          j.id === tempId ? { ...j, status: 'failed' } : j
        ),
      }));
      throw err;
    }
  },

  pollJobStatus: async (tempId, jobId) => {
    const poll = async () => {
      try {
        const data = await documentService.getIngestionStatus(jobId);
        const status = data.status;

        set((s) => ({
          uploadJobs: s.uploadJobs.map((j) =>
            j.id === tempId ? { ...j, status } : j
          ),
        }));

        if (status === 'complete' || status === 'completed' || status === 'failed') {
          if (status === 'complete' || status === 'completed') {
            get().loadDocuments();
          }
          return;
        }

        setTimeout(poll, 3000);
      } catch {
        // Retry on error
        setTimeout(poll, 5000);
      }
    };
    poll();
  },

  deleteDocument: async (docId) => {
    await documentService.deleteDocument(docId);
    set((s) => ({
      documents: s.documents.filter((d) => d.id !== docId),
    }));
  },

  // ── Stats & Analytics ──
  loadStats: async () => {
    try {
      const data = await adminService.getStats();
      set({ stats: data });
    } catch {
      // Silently fail
    }
  },

  loadTrendingTopics: async (days = 7) => {
    try {
      const data = await adminService.getTrendingTopics(days);
      set({ trendingTopics: data });
    } catch {
      // Silently fail
    }
  },

  loadKnowledgeGaps: async (days = 30) => {
    try {
      const data = await adminService.getKnowledgeGaps(days);
      set({ knowledgeGaps: data });
    } catch {
      // Silently fail
    }
  },

  // ── Knowledge Graph ──
  loadEntities: async () => {
    try {
      const data = await adminService.getEntities();
      set({ entities: data });
    } catch {
      // Silently fail
    }
  },

  clearUploadJobs: () => set({ uploadJobs: [] }),
}));
