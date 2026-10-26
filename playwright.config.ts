import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e',
  timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:5178', browserName: 'chromium', channel: 'chromium' },
  webServer: { command: 'npm run dev -- --port 5178 --strictPort', url: 'http://127.0.0.1:5178', reuseExistingServer: false },
})
