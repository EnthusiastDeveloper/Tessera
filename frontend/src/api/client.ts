/**
 * Thin fetch wrapper for the `/api/v1` backend (architecture-plan §3). Same-origin,
 * session-cookie auth (`credentials: 'include'`) - no token handling here on purpose.
 */

const BASE_URL = '/api/v1';

/** Mirrors the backend's error envelope (architecture-plan §3): status + machine code
 * + human message, with an optional `details` payload for validation errors. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Normalises anything a failed request can throw into an `ApiError`: API errors pass
 * through unchanged; anything else (a network failure, typically) becomes `fallback`. */
export function toApiError(
  err: unknown,
  fallback: ApiError = new ApiError(0, 'network_error', 'Could not reach the server.')
): ApiError {
  return err instanceof ApiError ? err : fallback;
}

interface ErrorEnvelope {
  code?: string;
  message?: string;
  details?: unknown;
}

type SessionExpiredHandler = () => void;

let sessionExpiredHandler: SessionExpiredHandler | null = null;

/** Registered once by `AuthProvider` (`src/auth/AuthContext.tsx`) - the one place this
 * framework-agnostic module can announce "the session died mid-app" without importing
 * React or creating a dependency cycle on AuthContext. `session_expired` is a distinct
 * code (architecture-plan §3) specifically so every call site doesn't have to remember
 * to check for it itself - this is the single place that does. */
export function setSessionExpiredHandler(handler: SessionExpiredHandler | null): void {
  sessionExpiredHandler = handler;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...init.headers,
    },
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  const body: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const envelope = (body ?? {}) as ErrorEnvelope;
    const code = envelope.code ?? 'unknown_error';
    if (code === 'session_expired') {
      sessionExpiredHandler?.();
    }
    throw new ApiError(
      response.status,
      code,
      envelope.message ?? 'Something went wrong.',
      envelope.details
    );
  }

  return body as T;
}

export const apiClient = {
  get: <T>(path: string): Promise<T> => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string): Promise<T> => request<T>(path, { method: 'DELETE' }),
};
