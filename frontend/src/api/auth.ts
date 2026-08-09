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
