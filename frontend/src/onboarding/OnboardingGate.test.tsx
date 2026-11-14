import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { OnboardingGate } from './OnboardingGate';
import * as settingsApi from '../api/settings';
import type { UserSettings } from '../types/settings';

vi.mock('../api/settings');

const mockedSettingsApi = vi.mocked(settingsApi);

function renderGate(): void {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/welcome" element={<p>The setup guide</p>} />
        <Route
          path="/"
          element={
            <OnboardingGate>
              <p>The app</p>
            </OnboardingGate>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

describe('OnboardingGate', () => {
  it('sends a user who has not been through the guide to it', async () => {
    mockedSettingsApi.getSettings.mockResolvedValue({ onboarding_completed: false } as UserSettings);
    renderGate();
    expect(await screen.findByText('The setup guide')).toBeInTheDocument();
  });

  it('opens the app once the guide is done', async () => {
    mockedSettingsApi.getSettings.mockResolvedValue({ onboarding_completed: true } as UserSettings);
    renderGate();
    expect(await screen.findByText('The app')).toBeInTheDocument();
  });

  it('opens the app when the check fails', async () => {
    mockedSettingsApi.getSettings.mockRejectedValue(new Error('offline'));
    renderGate();
    expect(await screen.findByText('The app')).toBeInTheDocument();
  });
});
