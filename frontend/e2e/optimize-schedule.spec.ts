import { test, expect, type Page } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

// Filename ordering is load-bearing (see tasks.spec.ts's comment): only needs to run after
// login.spec.ts. Every task here lives 30+ days out, away from the other specs' tasks, and
// the assertions name the tasks they care about rather than counting changes - the
// optimization is global and may also tidy something an earlier spec left behind.

function localDate(offsetDays: number): string {
  const day = new Date(Date.now() + offsetDays * 24 * 60 * 60 * 1000);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

interface Instance {
  id: string;
  name: string;
  status: string;
  scheduled_time: string | null;
}

async function login(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Username').fill('admin');
  await page.getByLabel('Password').fill(VALID_PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();
}

/** A one-time flexible task due `deadlineOffsetMinutes` after the start of `startDate`. */
async function createTask(
  page: Page,
  task: {
    name: string;
    minutes: number;
    priority: string;
    startDate: string;
    deadlineOffsetMinutes: number;
  }
): Promise<void> {
  const response = await page.request.post('/api/v1/task-templates', {
    data: {
      name: task.name,
      type: 'flexible',
      recurrence: { pattern: 'one_time', anchor: 'calendar' },
      priority: task.priority,
      start_date: task.startDate,
      estimated_duration_minutes: task.minutes,
      deadline_offset_minutes: task.deadlineOffsetMinutes,
    },
  });
  expect(response.status(), await response.text()).toBe(201);
}

async function instanceNamed(page: Page, name: string): Promise<Instance> {
  const instances = (await (await page.request.get('/api/v1/task-instances')).json()) as Instance[];
  const found = instances.find((i) => i.name === name);
  expect(found, `no task named ${name}`).toBeDefined();
  return found as Instance;
}

function dateOf(instance: Instance): string | null {
  if (!instance.scheduled_time) return null;
  const when = new Date(instance.scheduled_time);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

test.describe('Optimize Schedule against the real backend (design doc §6.11)', () => {
  test('a clean improvement applies at once, shows what changed, and can be undone', async ({
    page,
  }) => {
    await login(page);
    const day = localDate(30);
    const nextDay = localDate(31);
    // X arrives first and takes the morning of `day`; Y, due that same day, then has no room.
    await createTask(page, {
      name: 'Optimize X',
      minutes: 300,
      priority: 'low',
      startDate: day,
      deadlineOffsetMinutes: 2880,
    });
    await createTask(page, {
      name: 'Optimize Y',
      minutes: 240,
      priority: 'medium',
      startDate: day,
      deadlineOffsetMinutes: 1440,
    });
    expect((await instanceNamed(page, 'Optimize X')).status).toBe('scheduled');
    expect((await instanceNamed(page, 'Optimize Y')).status).toBe('pending');

    // The button invites the press: it names the gain and wears the attention-seeking border.
    await page.goto('/');
    const optimizeButton = page.getByRole('button', { name: 'Optimize Schedule' });
    await expect(page.getByText(/\d+ more tasks? could be scheduled/)).toBeVisible();
    await expect(optimizeButton).toBeEnabled();
    await expect(optimizeButton).toHaveClass(/optimize-button--attention/);
    await optimizeButton.click();

    const dialog = page.getByRole('dialog', { name: 'Schedule optimized' });
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog.getByRole('heading', { name: 'Newly scheduled' })).toBeVisible();
    await expect(dialog.getByText('Optimize Y')).toBeVisible();
    await expect(dialog.getByRole('heading', { name: 'Moved' })).toBeVisible();
    await expect(dialog.getByText('Optimize X')).toBeVisible();
    expect((await instanceNamed(page, 'Optimize Y')).status).toBe('scheduled');
    expect(dateOf(await instanceNamed(page, 'Optimize Y'))).toBe(day);
    expect(dateOf(await instanceNamed(page, 'Optimize X'))).toBe(nextDay);

    // Editing is unlocked again; it did what it could, so the button is grayed out - but still there.
    await expect(page.getByRole('link', { name: 'New task' })).toBeVisible();
    await expect(page.getByText('Nothing to improve right now')).toBeVisible();
    await expect(optimizeButton).toBeDisabled();

    // Undo puts everything back, and the opportunity comes back with it.
    await dialog.getByRole('button', { name: 'Undo' }).click();
    await expect(page.getByRole('dialog', { name: 'Schedule restored' })).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click();
    await expect(page.getByText(/\d+ more tasks? could be scheduled/)).toBeVisible();
    expect((await instanceNamed(page, 'Optimize Y')).status).toBe('pending');
    expect(dateOf(await instanceNamed(page, 'Optimize X'))).toBe(day);
  });

  test('a plan that would take a scheduled task away waits for approval, and cancelling changes nothing', async ({
    page,
  }) => {
    await login(page);
    const day = localDate(40);
    // Long (low) arrives first and fills most of the day; Urgent (high) and Short (low) then have
    // no room. Globally the two short ones fit and Long does not: a net gain of one task, at the
    // price of Long's place - so it needs the user's approval.
    await createTask(page, {
      name: 'Approve Long',
      minutes: 420,
      priority: 'low',
      startDate: day,
      deadlineOffsetMinutes: 1440,
    });
    await createTask(page, {
      name: 'Approve Urgent',
      minutes: 120,
      priority: 'high',
      startDate: day,
      deadlineOffsetMinutes: 1440,
    });
    await createTask(page, {
      name: 'Approve Short',
      minutes: 120,
      priority: 'low',
      startDate: day,
      deadlineOffsetMinutes: 1440,
    });
    expect((await instanceNamed(page, 'Approve Long')).status).toBe('scheduled');
    expect((await instanceNamed(page, 'Approve Urgent')).status).toBe('pending');
    expect((await instanceNamed(page, 'Approve Short')).status).toBe('pending');

    await page.goto('/');
    await expect(
      page.getByText(/\d+ more tasks? could be scheduled - needs your approval/)
    ).toBeVisible();
    await page.getByRole('button', { name: 'Optimize Schedule' }).click();

    const approval = page.getByRole('dialog', { name: /approval needed/ });
    await expect(approval).toBeVisible({ timeout: 15_000 });
    await expect(approval.getByRole('heading', { name: 'Would lose their place' })).toBeVisible();
    await expect(approval.getByText('Approve Long')).toBeVisible();
    await expect(approval.getByText(/Nothing has changed yet/)).toBeVisible();
    expect((await instanceNamed(page, 'Approve Long')).status).toBe('scheduled'); // nothing written yet

    await approval.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect((await instanceNamed(page, 'Approve Long')).status).toBe('scheduled');
    await expect(page.getByRole('button', { name: /Undo optimization/ })).toHaveCount(0); // nothing to undo

    // Asking again and approving applies it.
    await page.getByRole('button', { name: 'Optimize Schedule' }).click();
    const again = page.getByRole('dialog', { name: /approval needed/ });
    await expect(again).toBeVisible({ timeout: 15_000 });
    await again.getByRole('button', { name: 'Apply' }).click();
    const result = page.getByRole('dialog', { name: 'Schedule optimized' });
    await expect(result).toBeVisible({ timeout: 15_000 });
    expect((await instanceNamed(page, 'Approve Urgent')).status).toBe('scheduled');
    expect((await instanceNamed(page, 'Approve Short')).status).toBe('scheduled');
    expect((await instanceNamed(page, 'Approve Long')).status).toBe('pending');
    await result.getByRole('button', { name: 'Close' }).click();
    await expect(
      page.getByRole('button', { name: /Undo optimization \(\d+:\d\d\)/ })
    ).toBeVisible();
  });
});
