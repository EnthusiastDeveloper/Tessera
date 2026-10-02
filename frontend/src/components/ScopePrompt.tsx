import type { EditScope } from '../types/task';

interface ScopePromptProps {
  value: EditScope | null;
  onChange: (scope: EditScope) => void;
  /** Distinguishes the radio group's `name` when an edit prompt and a delete prompt
   * could theoretically both exist on the page at once. */
  name?: string;
  /** The second option's wording. Deleting reaches the whole open series, not only
   * this and later occurrences (design doc §3.8, Rev 11), so it says so. */
  seriesLabel?: string;
}

/** Design doc §3.10's two-way edit-scope choice, reused verbatim for deletion (§3.8) -
 * "using the same control as the edit-scope prompt". Only rendered for a recurring
 * (non-`one_time`) template - the caller decides that, this component doesn't know
 * about templates at all. */
export function ScopePrompt({
  value,
  onChange,
  name = 'edit-scope',
  seriesLabel = 'This and future occurrences',
}: ScopePromptProps): JSX.Element {
  return (
    <fieldset className="field">
      <legend>Apply to</legend>
      <label style={{ display: 'block' }}>
        <input
          type="radio"
          name={name}
          value="this_occurrence"
          checked={value === 'this_occurrence'}
          onChange={() => onChange('this_occurrence')}
        />{' '}
        This occurrence only
      </label>
      <label style={{ display: 'block' }}>
        <input
          type="radio"
          name={name}
          value="this_and_future"
          checked={value === 'this_and_future'}
          onChange={() => onChange('this_and_future')}
        />{' '}
        {seriesLabel}
      </label>
    </fieldset>
  );
}
