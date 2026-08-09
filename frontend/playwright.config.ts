import { defineConfig, devices } from '@playwright/test';

const FRONTEND_PORT = 4173;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // a single shared backend process - tests must not race each other
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['line'], ['html', { open: 'never' }]] : 'line',
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
    url: `http://localhost:${FRONTEND_PORT}`,
    reuseExistingServer: !process.env.CI,
  },
});
