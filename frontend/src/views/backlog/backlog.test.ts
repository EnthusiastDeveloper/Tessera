import { describe, expect, it } from 'vitest';
import type { Notification } from '../../types/notification';
import type { TaskInstance } from '../../types/task';
import { buildBacklogGroups } from './backlog';

function task(overrides: Partial<TaskInstance> & Pick<TaskInstance, 'id'>): TaskInstance {
  return {
    template_id: `template-${overrides.id}`,
    name: overrides.id,
    description: null,
    location: null,
    type: 'flexible',
    priority: 'medium',
    estimated_duration_minutes: 60,
    detached: false,
    scheduled_time: null,
    deadline: '2026-12-01T12:00:00Z',
    nominal_date: '2026-11-30',
    status: 'pending',
    status_history: [],
    dependencies: [],
    completed_at: null,
    generated_at: '2026-11-01T00:00:00Z',
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    version: 1,
    ...overrides,
  };
}

function unschedulable(instanceId: string, message: string): Notification {
  return { id: `n-${instanceId}`, type: 'unschedulable', related_instance_id: instanceId, message, created_at: '2026-11-01T00:00:00Z' };
}

describe('buildBacklogGroups', () => {
  it('groups missed first, then unschedulable, then blocked, and leaves out empty groups', () => {
    const blocked = task({ id: 'blocked', status: 'blocked' });
    const missed = task({ id: 'missed', status: 'missed' });
    const groups = buildBacklogGroups([blocked, missed], [blocked, missed], []);
    expect(groups.map((group) => group.key)).toEqual(['missed', 'blocked']);
  });

  it('treats a pending backlog instance as unschedulable and gives the notification as the reason', () => {
    const pending = task({ id: 'p', status: 'pending' });
    const groups = buildBacklogGroups([pending], [pending], [
      unschedulable('p', 'No free slot before the deadline.'),
      { ...unschedulable('other', 'Not this one'), id: 'n-2' },
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe('unschedulable');
    expect(groups[0].items[0].reason).toBe('No free slot before the deadline.');
  });

  it('ignores a status that does not belong in the backlog', () => {
    const scheduled = task({ id: 's', status: 'scheduled' });
    expect(buildBacklogGroups([scheduled], [scheduled], [])).toEqual([]);
  });

  it('names dependencies in both directions, and a deleted one without a status', () => {
    const prerequisite = task({ id: 'prep', name: 'Prepare car', status: 'scheduled' });
    const blocked = task({ id: 'inspect', name: 'Inspection', status: 'blocked', dependencies: ['prep', 'gone'] });
    const after = task({ id: 'drive', name: 'Road trip', status: 'blocked', dependencies: ['inspect'] });
    const all = [prerequisite, blocked, after];
    const [group] = buildBacklogGroups([blocked, after], all, []);
    const inspection = group.items.find((item) => item.instance.id === 'inspect');
    expect(inspection?.waitingOn).toEqual([
      { id: 'prep', name: 'Prepare car', status: 'scheduled' },
      { id: 'gone', name: 'A deleted task' },
    ]);
    expect(inspection?.waitedOnBy).toEqual([{ id: 'drive', name: 'Road trip', status: 'blocked' }]);
  });

  it('orders a group by priority, then the earliest deadline, then name', () => {
    const items = [
      task({ id: 'b-late', status: 'missed', priority: 'high', deadline: '2026-11-20T00:00:00Z' }),
      task({ id: 'low', status: 'missed', priority: 'low', deadline: '2026-11-01T00:00:00Z' }),
      task({ id: 'a-early', status: 'missed', priority: 'high', deadline: '2026-11-10T00:00:00Z' }),
      task({ id: 'critical', status: 'missed', priority: 'critical', deadline: null }),
    ];
    const [group] = buildBacklogGroups(items, items, []);
    expect(group.items.map((item) => item.instance.id)).toEqual(['critical', 'a-early', 'b-late', 'low']);
  });
});
