import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
    plugins: [vue()],
    server: {
        host: '0.0.0.0',
        proxy: {
            '/openclaw-api': {
                target: 'http://192.168.31.197:18789',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/openclaw-api/, ''),
            },
            '/speech-api': {
                target: 'http://127.0.0.1:8787',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/speech-api/, ''),
            },
        },
    },
})
