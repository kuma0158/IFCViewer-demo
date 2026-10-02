import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    // Cloudflare Tunnel 経由の公開ホスト名からのアクセスを許可する
    allowedHosts: ['ifc.shinobuabe.com'],
    // /api へのリクエストを FastAPI (Step 2) に転送する
    proxy: {
      '/api': 'http://127.0.0.1:8001',
    },
  },
})
