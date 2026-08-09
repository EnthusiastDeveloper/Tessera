import { startBackend } from './backend-process';

export default async function globalSetup(): Promise<void> {
  const { setupToken } = await startBackend();
  // Playwright forks test workers from this same process after globalSetup resolves,
  // so env set here is visible to every test - the documented way to hand data from
  // globalSetup to the tests themselves.
  process.env.TESSERA_E2E_SETUP_TOKEN = setupToken;
}
