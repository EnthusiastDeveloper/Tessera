import { test, expect } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing (see tasks.spec.ts's comment) - this only needs to
// run after login.spec.ts ("l" < "t"), which is the one file allowed to perform the
// zero-accounts-to-one-account transition on the shared backend.
test.describe('task detail view against the real backend', () => {
  test('navigating to a task shows its status and marking it complete updates the view', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();

    await page.getByRole('button', { name: 'New task' }).click();
    await expect(page).toHaveURL(/\/tasks\/new$/);
    await page.getByLabel('Name').fill('Detail view task');

    const createResponse = page.waitForResponse(
      (response) => response.url().includes('/api/v1/task-templates') && response.request().method() === 'POST'
    );
    await page.getByRole('button', { name: 'Save' }).click();
    const body = (await (await createResponse).json()) as { instance: { id: string } };

    await page.goto(`/tasks/${body.instance.id}`);
    await expect(page.getByRole('heading', { name: 'Detail view task' })).toBeVisible();

    await page.getByRole('button', { name: 'Mark complete' }).click();
    await expect(page.getByRole('strong').filter({ hasText: 'completed' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Mark complete' })).toHaveCount(0);
  });
});
