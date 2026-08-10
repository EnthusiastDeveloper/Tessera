/**
 * Boots the real Stage 8 backend (uvicorn) for Playwright's globalSetup/globalTeardown,
 * against an isolated temp SQLite file. Not a mock - see implementation-plan Stage 9a's
 * "one real Playwright test against the live Stage 8 backend".
 */
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const BACKEND_DIR = join(__dirname, '..', '..', 'backend');
const HOST = '127.0.0.1';
const PORT = 8000;
export const BACKEND_URL = `http://${HOST}:${PORT}`;

const SETUP_TOKEN_PATTERN = /Setup token \(use it at POST \/api\/v1\/auth\/setup\): (\S+)/;
const STATE_FILE = join(tmpdir(), 'tessera-e2e-backend-state.json');

interface BackendState {
  pid: number;
  dbDir: string;
}

async function waitForHealth(deadlineMs: number): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < deadlineMs) {
    try {
      const response = await fetch(`${BACKEND_URL}/health`);
      if (response.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Backend did not become healthy within ${deadlineMs}ms`);
}

function run(pythonBin: string, args: string[], env: NodeJS.ProcessEnv): Promise<void> {
  return new Promise((resolve, reject) => {
    const proc = spawn(pythonBin, args, { cwd: BACKEND_DIR, env });
    let output = '';
    proc.stdout.on('data', (chunk: Buffer) => (output += chunk.toString()));
    proc.stderr.on('data', (chunk: Buffer) => (output += chunk.toString()));
    proc.on('exit', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${pythonBin} ${args.join(' ')} exited with code ${code}:\n${output}`));
    });
  });
}

export async function startBackend(): Promise<{ setupToken: string }> {
  const dbDir = mkdtempSync(join(tmpdir(), 'tessera-e2e-'));
  const pythonBin = process.env.TESSERA_BACKEND_PYTHON ?? 'python3';
  const env = {
    ...process.env,
    DATABASE_PATH: join(dbDir, 'tessera.db'),
    SECRET_KEY: 'e2e-test-secret-key-not-for-production-use',
    SESSION_COOKIE_SECURE: 'false',
    // APP_BASE_URL (backend's own origin, matching the single-container same-origin
    // deployment topology - see CLAUDE.md's "FastAPI serves them directly") + fake
    // Google OAuth client credentials, both needed only so settings.spec.ts's real
    // `GET /calendar-connections/google/connect` reaches a genuine authorize_url
    // instead of 400ing on `app_base_url_not_configured`/`provider_not_configured`
    // first. No real Google endpoint is ever contacted (see that spec's own comment on
    // why - the round trip is scoped down to what a real browser can complete without
    // a live provider).
    APP_BASE_URL: 'http://localhost:8000',
    GOOGLE_CLIENT_ID: 'e2e-test-google-client-id',
    GOOGLE_CLIENT_SECRET: 'e2e-test-google-client-secret',
  };

  // Mirrors docker/entrypoint.sh: migrations must run before the app queries the users
  // table at startup (setup-token issuance) - nothing else applies the schema here.
  await run(pythonBin, ['-m', 'alembic', 'upgrade', 'head'], env);

  const child: ChildProcessWithoutNullStreams = spawn(
    pythonBin,
    ['-m', 'uvicorn', 'app.main:app', '--host', HOST, '--port', String(PORT)],
    { cwd: BACKEND_DIR, env }
  );

  let setupToken: string | null = null;
  const captureToken = (chunk: Buffer): void => {
    const match = SETUP_TOKEN_PATTERN.exec(chunk.toString());
    if (match) setupToken = match[1];
  };
  child.stdout.on('data', captureToken);
  child.stderr.on('data', captureToken);

  child.on('exit', (code) => {
    if (code !== null && code !== 0) {
      console.error(`Backend process exited early with code ${code}`);
    }
  });

  await waitForHealth(20_000);

  if (!setupToken) {
    // The health check passing means startup logging already ran - give the async
    // stream handlers one more tick to flush before giving up.
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (!setupToken) {
    throw new Error('Backend became healthy but no setup token was observed in its logs.');
  }

  writeFileSync(STATE_FILE, JSON.stringify({ pid: child.pid, dbDir } satisfies BackendState));
  child.unref();

  return { setupToken };
}

export function stopBackend(): void {
  let state: BackendState;
  try {
    state = JSON.parse(readFileSync(STATE_FILE, 'utf-8')) as BackendState;
  } catch {
    return; // nothing to tear down
  }
  try {
    process.kill(state.pid);
  } catch {
    // already gone
  }
  rmSync(state.dbDir, { recursive: true, force: true });
}
