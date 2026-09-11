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
    },
  },
})
