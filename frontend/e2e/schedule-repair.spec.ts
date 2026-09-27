import { test, expect } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing (see tasks.spec.ts's comment): only needs to run after
// login.spec.ts ("l" < "sc"). It restores the scheduling window before it finishes, so
// the specs after it see the default 09:00-17:00 window.

function localDate(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

test.describe('schedule repair against the real backend (design doc §6.10)', () => {
  test('narrowing the scheduling window re-places a task that no longer fits and says so', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();

    // A task on tomorrow, placed in the default 09:00-17:00 window, necessarily before 15:00
    // unless the day is almost full.
    const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
    const weekday = tomorrow.toLocaleDateString('en-US', { weekday: 'long' });
    await page.getByRole('button', { name: 'New task' }).click();
    await page.getByLabel('Name').fill('Repair me');
    await page.getByLabel('Starts on').fill(localDate(tomorrow));
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page).toHaveURL('http://localhost:4173/');

    await page.getByRole('link', { name: 'Settings' }).click();
    await page.getByLabel(`${weekday} start`).fill('16:00');
    await page.getByRole('button', { name: 'Save scheduling window' }).click();

    // The repair runs in the background; however quickly it finishes, the result is shown.
    const summary = page.getByRole('dialog', { name: 'Calendar fixed' });
    await expect(summary).toBeVisible();
    await expect(summary.getByText(/moved to a new time/)).toBeVisible();
    await summary.getByRole('button', { name: 'OK' }).click();
    await expect(summary).toHaveCount(0);

    const repair = (await (await page.request.get('/api/v1/settings/schedule-repair')).json()) as {
      status: string;
      done: number;
      total: number;
    };
    expect(repair.status).toBe('finished');
    expect(repair.done).toBe(repair.total);

    // Widening it back invalidates nothing, so nothing covers the page.
    await page.getByLabel(`${weekday} start`).fill('09:00');
    await page.getByRole('button', { name: 'Save scheduling window' }).click();
    await expect(page.getByText('Scheduling window saved.')).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });
});
