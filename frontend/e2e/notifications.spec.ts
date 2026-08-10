import { test, expect } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing (see tasks.spec.ts's comment): "notifications" sorts
// after "login" alphabetically, so this always runs after login.spec.ts has completed
// first-run setup against the one shared backend process. It only depends on that, not
// on any other spec file, and creates its own uniquely-named task so it can't be
// confused with a notification any other spec's task might incidentally raise.
test.describe('notifications panel against the real backend', () => {
  test('a real unschedulable notification appears on the panel and can be dismissed', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();

    // Trigger a real `unschedulable` notification (design doc §5): a flexible task whose
    // duration cannot possibly fit before its deadline, regardless of active hours or
    // time of day - 90 minutes of work with only 1 hour (60 minutes) until the deadline.
    // This is deterministic and doesn't depend on the server's current wall-clock time.
    await page.getByRole('button', { name: 'New task' }).click();
    await expect(page).toHaveURL(/\/tasks\/new$/);
    await page.getByLabel('Name').fill('Notifications smoke test task');
    await page.getByLabel('Estimated duration', { exact: true }).fill('90');
    await page.getByLabel('Deadline unit').selectOption('hours');
    await page.getByLabel('Deadline', { exact: true }).fill('1');
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(page).toHaveURL('http://localhost:4173/');
    await expect(page.locator('.banner-error')).toHaveCount(0);

    await page.getByRole('link', { name: 'Notifications' }).click();
    await expect(page).toHaveURL(/\/notifications$/);

    const row = page.locator('li', { hasText: 'Notifications smoke test task' });
    await expect(row).toBeVisible();
    await expect(row.getByText('Unschedulable')).toBeVisible();

    await row.getByRole('button', { name: 'Dismiss' }).click();
    await expect(row).toHaveCount(0);
  });
});
