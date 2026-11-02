import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // Auto-update: a new deploy silently refreshes the installed app on next launch.
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        // Generic install name — the in-app title is driven by FAMILY_NAME at runtime,
        // but the home-screen label is baked at build time, so keep it family-agnostic.
        name: 'Family Dashboard',
        short_name: 'Family',
        description: 'Shared family calendar, chores, meal planning and shopping list.',
        theme_color: '#863bff',
        background_color: '#863bff',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        scope: '/',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          // Same art flagged maskable so Android can mask it to the launcher shape.
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Cache the app shell (JS/CSS/HTML/icons) for offline launch. API calls are
        // NEVER cached — the dashboard is always a live client of the Flask backend.
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallbackDenylist: [/^\/api/],
        runtimeCaching: [],
      },
      devOptions: {
        // Keep the SW off in `vite dev` so it never interferes with the proxy/HMR.
        enabled: false,
      },
    }),
  ],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  // `vite preview` (used by the Playwright e2e run) also proxies /api so the
  // built bundle can reach the local Flask backend.
  preview: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
})
