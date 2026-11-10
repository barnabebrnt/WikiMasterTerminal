import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// En dev : le front tourne sur :5173 et relaie /api (HTTP + WebSocket) vers le backend.
// WM_API permet de pointer vers le SBC, ex. WM_API=http://rock5t.local:8000 npm run dev
const target = process.env.WM_API ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: { '/api': { target, ws: true, changeOrigin: true } },
  },
});
