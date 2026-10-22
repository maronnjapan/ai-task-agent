import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// The FastAPI backend serves frontend/dist in production; in development the
// Vite dev server proxies /api to the backend so the app stays same-origin.
export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false
      }
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    target: 'es2022'
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts']
  }
});
