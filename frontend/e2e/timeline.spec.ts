import { test, expect } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing (see tasks.spec.ts's comment) - "timeline" sorts
// after "tasks" alphabetically, so this always runs after login.spec.ts has completed
// first-run setup against the one shared backend process.
test.describe('timeline view against the real backend', () => {
  test('a newly created fixed task renders as a scheduled event on the Timeline', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();

    await page.getByRole('button', { name: 'New task' }).click();
    await expect(page).toHaveURL(/\/tasks\/new$/);

    await page.getByLabel('Name').fill('Timeline smoke test task');
    await page.getByLabel('Fixed').check();
    // Explicitly outside the default 09:00-17:00 active-hours window, not the form's
    // 09:00 default - a flexible task auto-placed by an earlier spec (e.g. tasks.spec.ts,
    // task-detail.spec.ts) always lands somewhere inside that window (design doc §6.2's
    // `effective_hours` constrains every placement to it), including exactly 09:00 when
    // the suite happens to run before 09:00 local time and "now" itself falls outside the
    // window. This task's own time must stay outside that window too so a `creation_conflict`
    // 409 (§6.5, both types are obstacles per CLAUDE.md) can never depend on wall-clock time.
    await page.getByLabel('Time of day').fill('21:00');
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(page).toHaveURL('http://localhost:4173/');
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();
    await expect(page.locator('.banner-error')).toHaveCount(0);

    // A fixed task enters `scheduled` immediately (design doc §3.3/§4) - it must show up
    // as a real, clickable Timeline event, not merely "not erroring".
    const event = page.locator('.fc-event-real', { hasText: 'Timeline smoke test task' });
    await expect(event).toBeVisible();

    await event.click();
    await expect(page).toHaveURL(/\/tasks\/[^/]+$/);
    await expect(page.getByRole('heading', { name: 'Timeline smoke test task' })).toBeVisible();
  });
});
