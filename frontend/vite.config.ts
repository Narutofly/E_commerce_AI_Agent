import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  cacheDir: '.vite-sales',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: process.env.SALES_API_TARGET || 'http://127.0.0.1:8011',
        changeOrigin: true,
      },
    },
  },
})
