import { defineConfig, devices } from '@playwright/test'

// Minimal E2E config. Runs against a locally-served production build so the
// tests exercise the same bundle that ships. The Vite preview server proxies
// /api to the local Flask backend (which must be running on :5000).
export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  expect: { timeout: 5000 },
  fullyParallel: false,
  retries: 0,
  // One worker: the local Flask dev backend is single-threaded, so parallel
  // browser contexts firing auth + data calls at once overwhelm it and login
  // requests time out. Serial keeps the dev server responsive.
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 5'] } },
  ],
  // Build + preview the frontend; assumes the Flask backend is already up on :5000.
  webServer: {
    command: 'npm run build && npm run preview -- --port 4173',
    port: 4173,
    reuseExistingServer: true,
    timeout: 120000,
  },
})
