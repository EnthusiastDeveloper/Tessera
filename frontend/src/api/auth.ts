import { apiClient } from './client';
import type { User } from '../types/auth';

export function setup(token: string, password: string): Promise<User> {
  return apiClient.post<User>('/auth/setup', { token, password });
}

export function login(username: string, password: string): Promise<User> {
  return apiClient.post<User>('/auth/login', { username, password });
}

export function logout(): Promise<void> {
  return apiClient.post<void>('/auth/logout');
}

export function me(): Promise<User> {
  return apiClient.get<User>('/auth/me');
}

/** `POST /auth/change-password` (design doc §3.6/§8.1 screen 6 "Account: change
 * password", Stage 9f). Revokes every other session - the backend rotates a fresh
 * session cookie onto this response so the caller's own device stays logged in
 * (`app.auth.service.change_password`'s own docstring), matching `login()`'s
 * rotate-on-success behavior. Nothing to do with the cookie here: `apiClient` already
 * runs with `credentials: 'include'`, so the browser applies the `Set-Cookie` itself. */
export function changePassword(currentPassword: string, newPassword: string): Promise<User> {
  return apiClient.post<User>('/auth/change-password', { current_password: currentPassword, new_password: newPassword });
}
