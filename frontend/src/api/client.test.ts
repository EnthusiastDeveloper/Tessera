import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiClient, setSessionExpiredHandler } from './client';

function mockFetchResponse(status: number, body: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      status,
      ok: status >= 200 && status < 300,
      text: () => Promise.resolve(JSON.stringify(body)),
    })
  );
}

describe('apiClient', () => {
  afterEach(() => {
    setSessionExpiredHandler(null);
    vi.unstubAllGlobals();
  });

  it('notifies the registered session-expired handler before throwing', async () => {
    mockFetchResponse(401, { code: 'session_expired', message: 'Authentication required.' });
    const handler = vi.fn();
    setSessionExpiredHandler(handler);

    await expect(apiClient.get('/task-instances')).rejects.toThrow(ApiError);

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('does not notify the handler for an unrelated error code', async () => {
    mockFetchResponse(422, { code: 'invalid_field', message: 'Bad field.' });
    const handler = vi.fn();
    setSessionExpiredHandler(handler);

    await expect(apiClient.get('/task-instances')).rejects.toThrow(ApiError);

    expect(handler).not.toHaveBeenCalled();
  });

  it('does nothing special when no handler is registered', async () => {
    mockFetchResponse(401, { code: 'session_expired', message: 'Authentication required.' });

    await expect(apiClient.get('/task-instances')).rejects.toThrow(ApiError);
  });
});
