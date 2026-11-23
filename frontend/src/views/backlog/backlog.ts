import type { Notification } from '../../types/notification';
import type { Priority, TaskInstance, TaskInstanceStatus } from '../../types/task';

/** Design doc 8.1 screen 5a: the three kinds of work the Backlog view lists. */
export type BacklogGroupKey = 'blocked' | 'unschedulable' | 'missed';

export interface DependencyLink {
  id: string;
  name: string;
  /** Unknown when the task is no longer in the list (it was deleted). */
  status?: TaskInstanceStatus;
}

export interface BacklogItem {
  instance: TaskInstance;
  /** What it waits on (6.1) - the forward direction of the dependency relation. */
  waitingOn: DependencyLink[];
  /** What waits on it - the reverse direction (5a: "navigable in both directions"). */
  waitedOnBy: DependencyLink[];
  /** The active `unschedulable` notification's message, which says why (6.2). */
  reason: string | null;
}

export interface BacklogGroup {
  key: BacklogGroupKey;
  items: BacklogItem[];
}

const GROUP_ORDER: BacklogGroupKey[] = ['missed', 'unschedulable', 'blocked'];

const PRIORITY_RANK: Record<Priority, number> = { critical: 0, high: 1, medium: 2, low: 3 };

function groupOf(instance: TaskInstance): BacklogGroupKey | null {
  if (instance.status === 'blocked') return 'blocked';
  if (instance.status === 'missed') return 'missed';
  // The server lists a `pending` instance only when it has an active `unschedulable`
  // notification (design doc 5a), so `pending` here means exactly that.
  if (instance.status === 'pending') return 'unschedulable';
  return null;
}

function deadlineValue(instance: TaskInstance): number {
  return instance.deadline ? new Date(instance.deadline).getTime() : Number.POSITIVE_INFINITY;
}

/** Most urgent first: priority, then the earliest deadline, then name. */
function compareItems(a: BacklogItem, b: BacklogItem): number {
  return (
    PRIORITY_RANK[a.instance.priority] - PRIORITY_RANK[b.instance.priority] ||
    deadlineValue(a.instance) - deadlineValue(b.instance) ||
    a.instance.name.localeCompare(b.instance.name)
  );
}

function toLink(instance: TaskInstance): DependencyLink {
  return { id: instance.id, name: instance.name, status: instance.status };
}

/** Builds the Backlog view's groups from the backlog filter's result (`?view=backlog`),
 * every instance (to name dependencies in both directions) and the active notifications
 * (for the reason a task could not be placed). Missed work comes first since its deadline
 * has already passed; empty groups are left out. */
export function buildBacklogGroups(
  backlog: TaskInstance[],
  allInstances: TaskInstance[],
  notifications: Notification[]
): BacklogGroup[] {
  const byId = new Map(allInstances.map((instance) => [instance.id, instance]));
  const reasons = new Map<string, string>();
  for (const notification of notifications) {
    if (notification.type === 'unschedulable' && !reasons.has(notification.related_instance_id)) {
      reasons.set(notification.related_instance_id, notification.message);
    }
  }

  const grouped = new Map<BacklogGroupKey, BacklogItem[]>();
  for (const instance of backlog) {
    const key = groupOf(instance);
    if (key === null) continue;
    const item: BacklogItem = {
      instance,
      waitingOn: instance.dependencies.map((id) => {
        const found = byId.get(id);
        return found ? toLink(found) : { id, name: 'A deleted task' };
      }),
      waitedOnBy: allInstances.filter((other) => other.dependencies.includes(instance.id)).map(toLink),
      reason: key === 'unschedulable' ? (reasons.get(instance.id) ?? null) : null,
    };
    grouped.set(key, [...(grouped.get(key) ?? []), item]);
  }

  return GROUP_ORDER.filter((key) => grouped.has(key)).map((key) => ({
    key,
    items: [...(grouped.get(key) ?? [])].sort(compareItems),
  }));
}
