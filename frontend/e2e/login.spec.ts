import { test, expect } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

test.describe.serial('login against the real backend', () => {
  test('a fresh instance redirects straight to first-run setup', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/setup$/);
    await expect(page.getByRole('heading', { name: 'Set up Tessera' })).toBeVisible();
  });

  test('completing setup, then logging in, reaches the app shell', async ({ page }) => {
    const setupToken = process.env.TESSERA_E2E_SETUP_TOKEN;
    if (!setupToken) {
      throw new Error('TESSERA_E2E_SETUP_TOKEN was not set by globalSetup');
    }

    await page.goto('/setup');
    await page.getByLabel('Setup token').fill(setupToken);
    await page.getByLabel('Password', { exact: true }).fill(VALID_PASSWORD);
    await page.getByLabel('Confirm password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Create account' }).click();

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText('Account created. Log in below.')).toBeVisible();

    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();

    await expect(page).toHaveURL('http://localhost:4173/');
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();
    await expect(page.getByText('admin')).toBeVisible();
  });

  test('an invalid password is rejected with the error banner', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill('the-wrong-password');
    await page.getByRole('button', { name: 'Log in' }).click();

    await expect(page.getByRole('alert')).toHaveText('Incorrect username or password.');
    await expect(page).toHaveURL(/\/login$/);
  });

  test('logging out returns to the login screen', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();

    await page.getByRole('button', { name: 'Log out' }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
});
