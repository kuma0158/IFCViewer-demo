import { defineConfig } from 'vite'

// 開発（npm run dev）と本番（npm run build → npm run serve）で同じ設定を使う
// /api へのリクエストを FastAPI（バックエンド :8001）に転送する
const proxy = { '/api': 'http://127.0.0.1:8001' }
// Cloudflare Tunnel 経由の公開ホスト名からのアクセスを許可する
const allowedHosts = ['ifc.shinobuabe.com']

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
    allowedHosts,
    proxy,
  },
  // 本番用: dist/（ビルド済みファイル）だけを配信する。トンネルの転送先を変えずに済むよう、開発時と同じ 5173 番で動かす
  preview: {
    port: 5173,
    strictPort: true,
    allowedHosts,
    proxy,
  },
})
