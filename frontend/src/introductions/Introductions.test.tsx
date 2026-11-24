import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as settingsApi from '../api/settings';
import { IntroductionsProvider, useIntroduction } from './Introductions';
import type { UserSettings } from '../types/settings';

vi.mock('../api/settings');
const mocked = vi.mocked(settingsApi);

const SETTINGS = { introductions_seen: [] as string[] } as unknown as UserSettings;

function Probe(): JSX.Element {
  const { show, dismiss } = useIntroduction('optimize_schedule');
  return show ? <button onClick={dismiss}>Got it</button> : <p>hidden</p>;
}

describe('one-time introductions (design doc 3.7, Rev 19)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.markIntroductionSeen.mockResolvedValue(SETTINGS);
  });

  it('shows an introduction the account has not seen, and records the dismissal', async () => {
    mocked.getSettings.mockResolvedValue(SETTINGS);
    render(
      <IntroductionsProvider>
        <Probe />
      </IntroductionsProvider>
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Got it' }));
    expect(screen.getByText('hidden')).toBeInTheDocument();
    expect(mocked.markIntroductionSeen).toHaveBeenCalledWith('optimize_schedule');
  });

  it('stays hidden while loading and when the settings cannot be read', async () => {
    mocked.getSettings.mockRejectedValue(new Error('offline'));
    render(
      <IntroductionsProvider>
        <Probe />
      </IntroductionsProvider>
    );
    await waitFor(() => expect(mocked.getSettings).toHaveBeenCalled());
    expect(screen.getByText('hidden')).toBeInTheDocument();
  });

  it('stays hidden for the rest of the visit if saving the dismissal fails', async () => {
    mocked.getSettings.mockResolvedValue(SETTINGS);
    mocked.markIntroductionSeen.mockRejectedValue(new Error('offline'));
    render(
      <IntroductionsProvider>
        <Probe />
      </IntroductionsProvider>
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Got it' }));
    await waitFor(() => expect(mocked.markIntroductionSeen).toHaveBeenCalled());
    expect(screen.getByText('hidden')).toBeInTheDocument();
  });

  it('introduces nothing outside a provider', () => {
    render(<Probe />);
    expect(screen.getByText('hidden')).toBeInTheDocument();
  });
});
