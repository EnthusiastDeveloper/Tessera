import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getSettings } from '../../api/settings';
import { TimezoneNotice } from '../../components/TimezoneNotice';
import { TaskForm } from './TaskForm';

export function CreateTaskPage(): JSX.Element {
  const navigate = useNavigate();
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
      <TaskForm mode="create" onSaved={() => navigate('/')} onCancel={() => navigate('/')} />
    </div>
  );
}
