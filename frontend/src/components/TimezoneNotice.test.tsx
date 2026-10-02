import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { TimezoneNotice } from './TimezoneNotice';
import * as timezone from '../lib/timezone';

describe('TimezoneNotice (design doc §14.1, Rev 11)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderWith(settingsTimezone: string | null, device: string, forTimeEntry = false): void {
    vi.spyOn(timezone, 'deviceTimezone').mockReturnValue(device);
    render(
      <MemoryRouter>
        <TimezoneNotice settingsTimezone={settingsTimezone} forTimeEntry={forTimeEntry} />
      </MemoryRouter>
    );
  }

  it('names both zones and links to Settings when they differ', () => {
    renderWith('America/New_York', 'Europe/London');
    const note = screen.getByRole('note');
    expect(note.textContent).toContain('America/New_York');
    expect(note.textContent).toContain('Europe/London');
    expect(note.textContent).toContain('shown in this device’s time');
    expect(screen.getByRole('link', { name: 'Change the timezone setting' })).toHaveAttribute('href', '/settings');
  });

  it('on the task form, says which zone entered times are in', () => {
    renderWith('America/New_York', 'Europe/London', true);
    expect(screen.getByRole('note').textContent).toContain('Times of day you enter here are in America/New_York.');
  });

  it('shows nothing when the zones match or the setting is not loaded yet', () => {
    renderWith('Europe/London', 'Europe/London');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    renderWith(null, 'Europe/London');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });
});
