import { test, expect } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing (see tasks.spec.ts's comment) - this only needs to
// run after login.spec.ts ("l" < "t").
test.describe('fixed-task creation conflict against the real backend', () => {
  test('a second fixed task overlapping the first is refused and the form stays open', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();

    // 19:00 is outside the default 09:00-17:00 active-hours window, so no flexible task
    // placed by an earlier spec can be sitting in this slot (see timeline.spec.ts), and
    // no other spec uses it - the only possible collision is the one this test creates.
    await page.getByRole('button', { name: 'New task' }).click();
    await page.getByLabel('Name').fill('Conflict anchor');
    await page.getByLabel('Fixed').check();
    await page.getByLabel('Time of day').fill('19:00');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page).toHaveURL('http://localhost:4173/');
    await expect(page.locator('.banner-error')).toHaveCount(0);

    // Design doc §6.5: a fixed task colliding with another fixed task is a hard block
    // (`creation_conflict`), surfaced on the form rather than silently saved.
    await page.getByRole('button', { name: 'New task' }).click();
    await page.getByLabel('Name').fill('Conflict overlapper');
    await page.getByLabel('Fixed').check();
    await page.getByLabel('Time of day').fill('19:15');
    const createResponse = page.waitForResponse(
      (response) => response.url().includes('/api/v1/task-templates') && response.request().method() === 'POST'
    );
    await page.getByRole('button', { name: 'Save' }).click();
    const response = await createResponse;
    expect(response.status()).toBe(409);
    expect(((await response.json()) as { code: string }).code).toBe('creation_conflict');

    await expect(page.locator('.banner-error')).toBeVisible();
    await expect(page).toHaveURL(/\/tasks\/new$/);
    await expect(page.getByLabel('Name')).toHaveValue('Conflict overlapper');
  });
});
