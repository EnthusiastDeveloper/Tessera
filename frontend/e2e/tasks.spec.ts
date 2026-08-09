import { test, expect } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing: Playwright runs spec files alphabetically within
// this single-worker project (playwright.config.ts), and this file relies on
// login.spec.ts ("l" < "t") having already completed first-run setup against the one
// shared backend process (frontend/e2e/backend-process.ts). It does not repeat setup
// itself - only login.spec.ts's account-creation test may touch that one-time
// transition, see its own comment for why.
test.describe('creating a task against the real backend', () => {
  test('a new flexible task is created and lands back on the timeline', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();

    await page.getByRole('button', { name: 'New task' }).click();
    await expect(page).toHaveURL(/\/tasks\/new$/);

    await page.getByLabel('Name').fill('Water the plants');
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(page).toHaveURL('http://localhost:4173/');
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();
    await expect(page.locator('.banner-error')).toHaveCount(0);
  });
});
