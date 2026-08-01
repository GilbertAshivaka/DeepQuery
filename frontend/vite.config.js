import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(process.cwd(), 'src'),
    },
  },
  optimizeDeps: {
    include: ['vis-network', 'vis-data'],
  },
  server: {
  port: 5173,
  allowedHosts: ['pseudoresident-toni-effervescently.ngrok-free.dev'],
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
    '/auth': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
  },
  build: {
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-vis':   ['vis-network', 'vis-data'],
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
});
