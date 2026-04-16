import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
    plugins: [vue()],
    server: {
        proxy: {
            '/openclaw-api': {
                target: 'http://127.0.0.1:18789',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/openclaw-api/, ''),
            },
        },
    },
})
