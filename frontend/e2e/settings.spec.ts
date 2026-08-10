import { test, expect } from '@playwright/test';

const VALID_PASSWORD = 'correcthorsebatterystaple';

/**
 * Filename ordering is load-bearing (see notifications.spec.ts's comment): "settings"
 * sorts after "login" alphabetically, so this always runs after login.spec.ts has
 * completed first-run setup against the one shared backend process. Otherwise
 * independent of every other spec file - it never creates a task.
 *
 * **OAuth e2e scope, decided here per this stage's own "figure out the right scope"
 * instruction:** `tests/fixtures/calendar_providers.py`'s `MockCalendarProvider` is a
 * Python object swapped in via `monkeypatch` at the pytest level - there is nothing
 * listening on a real HTTP port for a genuine browser to complete a full OAuth
 * round-trip against in this (or any) CI run, and standing up a stub HTTP OAuth server
 * just for this one e2e test was judged more machinery than the marginal coverage is
 * worth, given the rest of the flow already has real integration-test coverage below.
 * Scoped down to what a real browser genuinely exercises: clicking "Connect Google
 * Calendar" performs a real `GET /calendar-connections/google/connect` against the live
 * backend (`backend/app/calendar_sync/providers/google.py`'s real, unmocked
 * `build_authorize_url`) and then a real top-level navigation to the URL it returns.
 * `page.route` intercepts only the outbound request to `accounts.google.com` itself
 * (fulfilled locally, never leaves the test's own process) so the assertions below are
 * on request parameters actually produced by the real backend, not stubbed ones - state,
 * redirect_uri, and client_id are exactly what `google.py`'s `build_authorize_url` put
 * there. Token exchange, connection persistence, and disconnect are already covered
 * end-to-end against `MockCalendarProvider` in
 * `backend/tests/integration/api/test_calendar_connections_routes.py`
 * (`TestCallback`/`TestDisconnect`) - real HTTP through FastAPI's `TestClient`, just not
 * through an actual browser, which is the established precedent implementation-plan §7
 * set for this exact provider-mocking rule.
 */
test.describe('settings screen against the real backend', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { name: 'Timeline' })).toBeVisible();

    await page.getByRole('link', { name: 'Settings' }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
  });

  test('clicking "Connect Google Calendar" navigates to a real authorize URL carrying the expected state and redirect_uri', async ({
    page,
  }) => {
    let capturedRequestUrl: URL | null = null;
    await page.route('https://accounts.google.com/**', async (route) => {
      capturedRequestUrl = new URL(route.request().url());
      await route.fulfill({ status: 200, contentType: 'text/html', body: '<html><body>stub provider page</body></html>' });
    });

    await page.getByRole('button', { name: 'Connect Google Calendar' }).click();
    await page.waitForURL(/accounts\.google\.com/);

    expect(capturedRequestUrl).not.toBeNull();
    const url = capturedRequestUrl as unknown as URL;
    expect(url.origin + url.pathname).toBe('https://accounts.google.com/o/oauth2/v2/auth');
    expect(url.searchParams.get('client_id')).toBe('e2e-test-google-client-id');
    expect(url.searchParams.get('response_type')).toBe('code');
    expect(url.searchParams.get('redirect_uri')).toBe('http://localhost:8000/api/v1/calendar-connections/google/callback');
    expect(url.searchParams.get('state')).toBeTruthy();
  });

  test('changing the account password signs out other sessions but keeps this one logged in', async ({ page, context }) => {
    // A second, independent "device" - its own cookie jar - logged in before the
    // change, to prove §3.6's "every session...revoked" against something other than
    // the tab performing the change.
    const otherDevice = await context.browser()?.newContext();
    if (!otherDevice) throw new Error('expected a browser to open a second context from');
    const otherPage = await otherDevice.newPage();
    await otherPage.goto('/login');
    await otherPage.getByLabel('Username').fill('admin');
    await otherPage.getByLabel('Password').fill(VALID_PASSWORD);
    await otherPage.getByRole('button', { name: 'Log in' }).click();
    await expect(otherPage.getByRole('heading', { name: 'Timeline' })).toBeVisible();

    const newPassword = 'a-freshly-chosen-password-123';
    await page.getByLabel('Current password').fill(VALID_PASSWORD);
    await page.getByLabel('New password', { exact: true }).fill(newPassword);
    await page.getByLabel('Confirm new password').fill(newPassword);
    await page.getByRole('button', { name: 'Change password' }).click();
    await expect(page.getByText('Every other signed-in device has been signed out.')).toBeVisible();

    // This tab's own session survived the change (no redirect to /login).
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();

    // The other device's session did not - its next request bounces to /login.
    await otherPage.reload();
    await expect(otherPage).toHaveURL(/\/login$/);
    await otherDevice.close();

    // Restore the shared account's password so every spec file after this one (which
    // all log in with VALID_PASSWORD) keeps working, regardless of file execution order
    // relative to this test within this file.
    await page.getByLabel('Current password').fill(newPassword);
    await page.getByLabel('New password', { exact: true }).fill(VALID_PASSWORD);
    await page.getByLabel('Confirm new password').fill(VALID_PASSWORD);
    await page.getByRole('button', { name: 'Change password' }).click();
    await expect(page.getByText('Every other signed-in device has been signed out.')).toBeVisible();
  });

  test('saving the scheduling window persists across a reload', async ({ page }) => {
    // Every day defaults to a custom 09:00-17:00 window (`app.settings.service.
    // DEFAULT_ACTIVE_HOURS`) - exclude Sunday to get an observable change, then restore
    // it so later runs/spec files see the same starting state.
    await expect(page.getByLabel('Sunday active hours')).toHaveValue('custom');
    await page.getByLabel('Sunday active hours').selectOption('excluded');
    await page.getByRole('button', { name: 'Save scheduling window' }).click();
    await expect(page.getByText('Scheduling window saved.')).toBeVisible();

    await page.reload();
    await expect(page.getByLabel('Sunday active hours')).toHaveValue('excluded');

    await page.getByLabel('Sunday active hours').selectOption('custom');
    await page.getByRole('button', { name: 'Save scheduling window' }).click();
    await expect(page.getByText('Scheduling window saved.')).toBeVisible();
  });
});
