import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError } from '../../api/client';
import { createTemplate } from '../../api/taskTemplates';
import { useDisplayPreferences } from '../../display/DisplayPreferences';
import { formatDurationCompact } from '../../lib/duration';
import { formatTime, formatWeekdayDayMonth } from '../../lib/dates';
import { MAX_DESCRIPTION_LENGTH, MAX_LOCATION_LENGTH, MAX_NAME_LENGTH } from '../../lib/limits';
import type { TaskType } from '../../types/task';
import { DependenciesPicker } from '../tasks/DependenciesPicker';
import { quickCreatePayload, toPrefill, type QuickTaskPrefill, type SelectedSlot, type SlotSelection } from './quickCreate';

const PANEL_WIDTH = 360;
const GUTTER = 16;

interface QuickCreatePanelProps {
  selection: SlotSelection;
  slot: SelectedSlot;
  /** Where the selection was made, to open beside it; null centres the panel. */
  point: { x: number; y: number } | null;
  onClose: () => void;
  onCreated: () => void;
  onOpenFullForm: (prefill: QuickTaskPrefill) => void;
}

/** Beside the selection: to its right if there is room, else to its left, level with
 * where it was made, and moved up as far as needed for all of it to fit on screen. */
function panelPosition(point: { x: number; y: number } | null, height: number): { left: number; top: number } {
  const width = Math.min(PANEL_WIDTH, window.innerWidth - 2 * GUTTER);
  const highest = Math.max(GUTTER, window.innerHeight - height - GUTTER);
  if (!point) return { left: (window.innerWidth - width) / 2, top: Math.min(96, highest) };
  const fitsRight = point.x + GUTTER + width <= window.innerWidth - GUTTER;
  const left = fitsRight ? point.x + GUTTER : Math.max(GUTTER, point.x - GUTTER - width);
  return { left, top: Math.min(Math.max(GUTTER, point.y - 40), highest) };
}

/** The Timeline's quick create (design doc 8.1 screen 2, Rev 18): name, description,
 * location, type and dependencies, with the selection supplying date and duration. Fixed
 * by default, since a selection is a time. Saves through the ordinary create path, so its
 * refusals (a fixed clash, a flexible task too long for the day) are shown here. */
export function QuickCreatePanel({ selection, slot, point, onClose, onCreated, onOpenFullForm }: QuickCreatePanelProps): JSX.Element {
  const { dateFormat, timeFormat } = useDisplayPreferences();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [location, setLocation] = useState('');
  const [type, setType] = useState<TaskType>('fixed');
  const [dependencies, setDependencies] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const nameField = useRef<HTMLInputElement>(null);
  const [isPhone] = useState(() => window.matchMedia?.('(max-width: 640px)').matches ?? false);
  const [height, setHeight] = useState(0);

  // Measured before paint, so the panel is placed where it fits without a visible jump.
  useLayoutEffect(() => {
    const element = panel.current;
    if (!element) return;
    const measure = (): void => setHeight(element.offsetHeight);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    nameField.current?.focus();
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose();
    };
    const onPointer = (event: MouseEvent | TouchEvent): void => {
      if (panel.current && !panel.current.contains(event.target as Node)) onClose();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('touchstart', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('touchstart', onPointer);
    };
  }, [onClose]);

  const fields = { name, description, location, type, dependencies };
  const end = new Date(selection.start.getTime() + slot.durationMinutes * 60_000);
  const day = formatWeekdayDayMonth(selection.start, dateFormat);
  const length = formatDurationCompact(slot.durationMinutes);

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    if (!name.trim()) {
      setError('Give the task a name.');
      nameField.current?.focus();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createTemplate(quickCreatePayload(slot, fields));
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the server.');
      setSaving(false);
    }
  };

  const position = panelPosition(point, height);
  return (
    <div
      ref={panel}
      role="dialog"
      aria-label="New task"
      className={
        isPhone
          ? 'quick-create fixed inset-x-0 bottom-0 z-50 max-h-[85vh] overflow-y-auto rounded-t-lg border border-border bg-surface p-4 shadow-card'
          : 'quick-create fixed z-50 max-h-[calc(100vh-2rem)] overflow-y-auto rounded-lg border border-border bg-surface p-4 shadow-card'
      }
      style={isPhone ? undefined : { left: position.left, top: position.top, width: Math.min(PANEL_WIDTH, window.innerWidth - 2 * GUTTER) }}
    >
      <form onSubmit={(event) => void handleSubmit(event)} noValidate>
        <p className="mb-3 text-sm text-text-muted" data-testid="quick-create-when">
          {type === 'fixed'
            ? `${day}, ${formatTime(selection.start, timeFormat)} - ${formatTime(end, timeFormat)}`
            : `${day}, ${length}. Tessera picks the time, by the end of the day.`}
        </p>
        {error && (
          <div className="banner-error" role="alert">
            {error}
          </div>
        )}
        <div className="field">
          <label htmlFor="quick-name">Name</label>
          <input
            id="quick-name"
            ref={nameField}
            type="text"
            value={name}
            maxLength={MAX_NAME_LENGTH}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <fieldset className="field">
          <legend>Type</legend>
          <div className="flex gap-4">
            <label className="flex items-center gap-2">
              <input type="radio" name="quick-type" checked={type === 'fixed'} onChange={() => setType('fixed')} />
              Fixed
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="quick-type" checked={type === 'flexible'} onChange={() => setType('flexible')} />
              Flexible
            </label>
          </div>
        </fieldset>
        <div className="field">
          <label htmlFor="quick-description">Description</label>
          <input
            id="quick-description"
            type="text"
            value={description}
            maxLength={MAX_DESCRIPTION_LENGTH}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="quick-location">Location</label>
          <input
            id="quick-location"
            type="text"
            value={location}
            maxLength={MAX_LOCATION_LENGTH}
            onChange={(event) => setLocation(event.target.value)}
          />
        </div>
        <div className="max-h-40 overflow-y-auto">
          <DependenciesPicker selected={dependencies} onChange={setDependencies} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button type="button" className="text-sm" onClick={() => onOpenFullForm(toPrefill(slot, fields))}>
            Open full form
          </button>
          <div className="flex-1" />
          <button type="button" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={saving}>
            {saving ? 'Saving…' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  );
}
