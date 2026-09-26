import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing (see tasks.spec.ts's comment) - this only needs to
// run after login.spec.ts ("l" < "m").

async function logIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Username').fill('admin');
  await page.getByLabel('Password').fill(VALID_PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();
}

async function createFlexibleTask(page: Page, name: string): Promise<string> {
  await page.getByRole('button', { name: 'New task' }).click();
  await page.getByLabel('Name').fill(name);
  const createResponse = page.waitForResponse(
    (response) => response.url().includes('/api/v1/task-templates') && response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Save' }).click();
  const body = (await (await createResponse).json()) as { instance: { id: string } };
  await expect(page).toHaveURL('http://localhost:4173/');
  return body.instance.id;
}

function toDatetimeLocal(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

test.describe('missed and skipped flexible tasks against the real backend', () => {
  test('a missed task can have its deadline extended and goes back to being scheduled', async ({ page }) => {
    await logIn(page);
    const instanceId = await createFlexibleTask(page, 'Renew passport');

    // Waiting out a real deadline would make the test minutes long. A "this occurrence"
    // deadline edit into the past takes the same §6.7 gate the deadline job does, so the
    // instance lands in `missed` straight away.
    const pastDeadline = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const patch = await page.request.patch(`/api/v1/task-instances/${instanceId}`, { data: { deadline: pastDeadline } });
    expect(patch.ok()).toBe(true);

    await page.goto(`/tasks/${instanceId}`);
    await expect(page.getByRole('strong').filter({ hasText: 'missed' })).toBeVisible();

    await page.getByRole('button', { name: 'Extend deadline' }).click();
    const newDeadline = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
    await page.getByLabel('New deadline').fill(toDatetimeLocal(newDeadline));
    await page.getByRole('button', { name: 'Confirm extension' }).click();

    // Design doc §6.7: extending the deadline re-enters §6.2, and a week of default
    // active hours always has room for a 30-minute task.
    await expect(page.getByRole('strong').filter({ hasText: 'scheduled' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Extend deadline' })).toHaveCount(0);
  });

  test('skipping an occurrence dismisses it and removes the status actions', async ({ page }) => {
    await logIn(page);
    const instanceId = await createFlexibleTask(page, 'Optional stretch session');

    await page.goto(`/tasks/${instanceId}`);
    await page.getByRole('button', { name: 'Skip this occurrence' }).click();
    await expect(page.getByRole('strong').filter({ hasText: 'dismissed' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Mark complete' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Skip this occurrence' })).toHaveCount(0);
  });
});
