import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing (see tasks.spec.ts's comment) - this only needs to
// run after login.spec.ts ("l" < "r").

async function logIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Username').fill('admin');
  await page.getByLabel('Password').fill(VALID_PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();
}

/** Creates a daily fixed task through the form and returns its template and first
 * instance ids. Each caller picks its own time, outside the default 09:00-17:00
 * active-hours window and distinct from every other spec's, so no creation can collide
 * (see timeline.spec.ts). */
async function createDailyFixedTask(page: Page, name: string, timeOfDay: string): Promise<{ templateId: string; instanceId: string }> {
  await page.getByRole('button', { name: 'New task' }).click();
  await page.getByLabel('Name').fill(name);
  await page.getByLabel('Fixed').check();
  await page.getByLabel('Repeats').selectOption('daily');
  await page.getByLabel('Time of day').fill(timeOfDay);
  const createResponse = page.waitForResponse(
    (response) => response.url().includes('/api/v1/task-templates') && response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Save' }).click();
  const body = (await (await createResponse).json()) as { template: { id: string }; instance: { id: string } };
  await expect(page).toHaveURL('http://localhost:4173/');
  return { templateId: body.template.id, instanceId: body.instance.id };
}

test.describe('recurring task edit and delete scopes against the real backend', () => {
  test('a "this occurrence" edit detaches the instance and leaves the series alone; "this and future" edits the series', async ({
    page,
  }) => {
    await logIn(page);
    const { templateId, instanceId } = await createDailyFixedTask(page, 'Daily standup', '20:00');

    // Design doc §3.10: a recurring task must ask for the scope before saving, and
    // "this occurrence" hides every template-only field.
    await page.goto(`/tasks/${instanceId}/edit`);
    await expect(page.getByRole('button', { name: 'Save' })).toBeDisabled();
    await page.getByLabel('This occurrence only').check();
    await expect(page.getByLabel('Time of day')).toHaveCount(0);
    await page.getByLabel('Name').fill('Standup in the big room');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page).toHaveURL('http://localhost:4173/');

    await page.goto(`/tasks/${instanceId}`);
    await expect(page.getByRole('heading', { name: 'Standup in the big room' })).toBeVisible();
    await expect(page.getByText('Detached', { exact: true })).toBeVisible();
    const templateAfterOccurrenceEdit = await page.request.get(`/api/v1/task-templates/${templateId}`);
    expect(((await templateAfterOccurrenceEdit.json()) as { name: string }).name).toBe('Daily standup');

    // "This and future" keeps the template-only fields and writes the template.
    await page.goto(`/tasks/${instanceId}/edit`);
    await page.getByLabel('This and future occurrences').check();
    await expect(page.getByLabel('Time of day')).toBeVisible();
    await page.getByLabel('Name').fill('Daily sync');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page).toHaveURL('http://localhost:4173/');
    await expect(page.locator('.banner-error')).toHaveCount(0);

    const templateAfterSeriesEdit = await page.request.get(`/api/v1/task-templates/${templateId}`);
    expect(((await templateAfterSeriesEdit.json()) as { name: string }).name).toBe('Daily sync');
  });

  test('deleting a recurring task requires a scope, and "this and future" ends the series', async ({ page }) => {
    await logIn(page);
    const { templateId, instanceId } = await createDailyFixedTask(page, 'Nightly backup check', '22:00');

    await page.goto(`/tasks/${instanceId}/edit`);
    await page.getByRole('button', { name: 'Delete task' }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Delete task' });
    await expect(dialog.getByRole('button', { name: 'Delete' })).toBeDisabled();
    await dialog.getByLabel('This and future occurrences').check();
    await expect(dialog.getByText('This ends the recurring series')).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete' }).click();
    await expect(page).toHaveURL('http://localhost:4173/');

    const instances = (await (await page.request.get('/api/v1/task-instances')).json()) as { id: string }[];
    expect(instances.map((instance) => instance.id)).not.toContain(instanceId);
    const template = (await (await page.request.get(`/api/v1/task-templates/${templateId}`)).json()) as { archived: boolean };
    expect(template.archived).toBe(true);
  });
});
