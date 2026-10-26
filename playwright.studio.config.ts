import { defineConfig } from '@playwright/test'
import path from 'node:path'
const python = path.resolve(process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')
export default defineConfig({
  testDir: './studio-e2e', workers: 1, timeout: 300000,
  expect: { timeout: 15000 },
  use: { baseURL: 'http://127.0.0.1:5179', browserName: 'chromium', channel: 'chromium' },
  webServer: [
    { command: `"${python}" -m backend.browser_server`, url: 'http://127.0.0.1:8766/api/studio/status', timeout: 60000 },
    { command: 'npm run dev -- --port 5179 --strictPort', url: 'http://127.0.0.1:5179', env: { STUDIO_API_TARGET: 'http://127.0.0.1:8766' } },
  ],
})
