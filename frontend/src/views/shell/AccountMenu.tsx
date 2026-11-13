import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { useNavigate } from 'react-router-dom';

/** The app bar's account menu: who is signed in, Settings, Log out. Radix handles focus,
 * keyboard navigation (arrows, Esc) and the portal; `.menu*` in index.css styles it. */
export function AccountMenu({ username, onLogout }: { username?: string; onLogout: () => void }): JSX.Element {
  const navigate = useNavigate();
  const name = username ?? 'Account';
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className="flex items-center gap-2 border-border bg-surface py-1 pr-3 pl-1">
          <span
            aria-hidden="true"
            className="flex size-7 items-center justify-center rounded-sm bg-flexible font-display text-sm font-bold text-flexible-text"
          >
            {name.charAt(0).toUpperCase()}
          </span>
          <span className="text-sm">{name}</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="menu" align="end" sideOffset={6}>
          <DropdownMenu.Label className="menu__label">Signed in as {name}</DropdownMenu.Label>
          <DropdownMenu.Item className="menu__item" onSelect={() => navigate('/settings')}>
            Settings
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="menu__separator" />
          <DropdownMenu.Item className="menu__item" onSelect={onLogout}>
            Log out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
