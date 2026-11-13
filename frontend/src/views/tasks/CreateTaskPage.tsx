import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getSettings } from '../../api/settings';
import { TimezoneNotice } from '../../components/TimezoneNotice';
import type { QuickTaskPrefill } from '../timeline/quickCreate';
import { TaskForm } from './TaskForm';

export function CreateTaskPage(): JSX.Element {
  const navigate = useNavigate();
  // From the Timeline's "Open full form" (design doc 8.1 screen 3, Rev 18).
  const prefill = (useLocation().state as { prefill?: QuickTaskPrefill } | null)?.prefill;
  const [settingsTimezone, setSettingsTimezone] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((settings) => {
        if (!cancelled) setSettingsTimezone(settings.timezone);
      })
      .catch(() => {
        // Only the timezone notice needs it; the form works without.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h2>New task</h2>
      <TimezoneNotice settingsTimezone={settingsTimezone} forTimeEntry />
      <TaskForm mode="create" prefill={prefill} onSaved={() => navigate('/')} onCancel={() => navigate('/')} />
    </div>
  );
}
