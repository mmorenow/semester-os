import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The API port. 8790 is the default in config.yaml; SEMESTER_OS_PORT overrides
// it for the dev proxy the same way it overrides it for the server.
const apiPort = process.env.SEMESTER_OS_PORT ?? '8790'

// Tailwind v4 runs through the official Vite plugin, never the PostCSS plugin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${apiPort}`,
        // The server enforces a Host allowlist (see app/server/security.py), so
        // the proxied request must carry Host: 127.0.0.1:<port> rather than
        // localhost:5173.
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            // The server rejects cross-origin mutations. In dev the
            // page origin is :5173, so strip these headers and let the request
            // read as same-origin, which is what it effectively is.
            proxyReq.removeHeader('origin')
            proxyReq.removeHeader('referer')
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // Markdown rendering is only needed where an agent's prose is shown.
        manualChunks: {
          markdown: ['react-markdown', 'remark-gfm'],
        },
      },
    },
  },
})
