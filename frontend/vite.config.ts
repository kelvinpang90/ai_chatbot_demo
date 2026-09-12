import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/console/stream': 'http://localhost:8000',
      '/console/tools': 'http://localhost:8000',
      '/console/demo-summary': 'http://localhost:8000',
      '/console/handover': 'http://localhost:8000',
      '/console/reply': 'http://localhost:8000',
      // Left out when task 37.2 added the transcript page, and nothing noticed
      // until backend/tests/test_console_routing.py went looking: under
      // `npm run dev` the history fetch was being answered by index.html.
      '/console/history': 'http://localhost:8000',
    },
  },
})
