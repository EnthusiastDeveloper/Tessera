import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing (see tasks.spec.ts's comment) - this needs to run
// after login.spec.ts, hence "task-backlog" rather than "backlog".

async function logIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Username').fill('admin');
  await page.getByLabel('Password').fill(VALID_PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();
}

async function createFlexibleTask(page: Page, name: string): Promise<string> {
  await page.goto('/');
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

test.describe('Backlog view against the real backend', () => {
  test('lists blocked and missed work, links dependencies both ways, and updates as tasks finish', async ({ page }) => {
    await logIn(page);
    const prepId = await createFlexibleTask(page, 'Backlog prep task');
    const waitingId = await createFlexibleTask(page, 'Backlog waiting task');
    const lateId = await createFlexibleTask(page, 'Backlog late task');

    // Waiting on an unfinished task blocks it (design doc 6.1, Rev 17).
    const deps = await page.request.put(`/api/v1/task-instances/${waitingId}/dependencies`, {
      data: { dependencies: [prepId] },
    });
    expect(deps.ok()).toBe(true);
    // A deadline in the past takes the same 6.7 gate the deadline job does.
    const pastDeadline = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const patch = await page.request.patch(`/api/v1/task-instances/${lateId}`, { data: { deadline: pastDeadline } });
    expect(patch.ok()).toBe(true);

    await page.getByRole('link', { name: 'Backlog', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Backlog', level: 2 })).toBeVisible();

    const waiting = page.getByRole('region', { name: /Waiting on other tasks/ });
    const waitingItem = waiting.getByRole('listitem').filter({ hasText: 'Backlog waiting task' });
    await expect(waitingItem.getByRole('link', { name: 'Backlog prep task' })).toHaveAttribute('href', `/tasks/${prepId}`);

    const missed = page.getByRole('region', { name: /Missed deadline/ });
    await expect(missed.getByRole('link', { name: 'Backlog late task' })).toBeVisible();

    // The other direction, from the prerequisite's own page.
    await waitingItem.getByRole('link', { name: 'Backlog prep task' }).click();
    await expect(page).toHaveURL(new RegExp(`/tasks/${prepId}$`));
    await expect(page.getByRole('heading', { name: 'Backlog prep task' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Backlog waiting task' })).toHaveAttribute('href', `/tasks/${waitingId}`);

    // Finishing the prerequisite frees the waiting task (6.9), so it stops waiting. Whether
    // it then lands on the Timeline or under "Couldn't be scheduled" depends on the hour the
    // test runs at (its deadline is the end of today), so only "no longer waiting" is checked.
    const complete = await page.request.post(`/api/v1/task-instances/${prepId}/complete`);
    expect(complete.ok()).toBe(true);
    await page.goto('/backlog');
    await expect(page.getByRole('link', { name: 'Backlog late task' })).toBeVisible();
    await expect(page.getByRole('region', { name: /Waiting on other tasks/ })).toHaveCount(0);

    // Skipping from the Backlog takes the task out of it.
    await page.getByRole('button', { name: 'Skip Backlog late task' }).click();
    await expect(page.getByRole('link', { name: 'Backlog late task' })).toHaveCount(0);
  });
});
