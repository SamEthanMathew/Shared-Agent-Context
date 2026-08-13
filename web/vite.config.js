import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The app is served from /app by FastAPI, and its build output is committed to
// app/static/app so deploying the Python service needs no Node toolchain.
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  build: {
    outDir: '../app/static/app',
    emptyOutDir: true,
    // Long-term-cacheable filenames; index.html is served with no-store.
    assetsDir: 'assets',
  },
  server: {
    // `npm run dev` proxies the API to a local uvicorn so the dev server can
    // use the same session cookie as production.
    proxy: {
      '/v1': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
      '/console': 'http://127.0.0.1:8000',
    },
  },
})
