import { api } from '../api/client';
import type { CategoryOut, TaskListParams, TaskOut } from '../api/types';
import { debounced, onEvent } from './events.svelte';

export interface TaskFilters {
  status: string;
  category_id: string;
  assignee: string;
  search: string;
  include_completed: boolean;
  order: 'due' | 'created' | 'updated';
}

export const PAGE_SIZE = 50;

export const tasks: {
  items: TaskOut[];
  total: number;
  offset: number;
  loading: boolean;
  loaded: boolean;
  error: string | null;
  filters: TaskFilters;
} = $state({
  items: [],
  total: 0,
  offset: 0,
  loading: false,
  loaded: false,
  error: null,
  filters: { status: '', category_id: '', assignee: '', search: '', include_completed: false, order: 'due' }
});

export const categories: { items: CategoryOut[]; loaded: boolean } = $state({ items: [], loaded: false });

let requestSeq = 0;

export async function loadTasks(offset = tasks.offset): Promise<void> {
  const seq = ++requestSeq;
  tasks.loading = true;
  tasks.error = null;
  const f = tasks.filters;
  const params: TaskListParams = {
    status: f.status || undefined,
    category_id: f.category_id || undefined,
    assignee: f.assignee || undefined,
    search: f.search.trim() || undefined,
    include_completed: f.include_completed,
    order: f.order,
    limit: PAGE_SIZE,
    offset
  };
  try {
    const page = await api.tasks.list(params);
    if (seq !== requestSeq) return; // a newer request superseded this one
    tasks.items = page.items;
    tasks.total = page.total;
    tasks.offset = page.offset;
    tasks.loaded = true;
  } catch (err) {
    if (seq !== requestSeq) return;
    tasks.error = err instanceof Error ? err.message : String(err);
  } finally {
    if (seq === requestSeq) tasks.loading = false;
  }
}

export async function loadCategories(): Promise<void> {
  try {
    categories.items = await api.categories.list();
    categories.loaded = true;
  } catch {
    // handled by the global banner
  }
}

export function categoryName(id: string | null | undefined): string {
  if (!id) return '';
  return categories.items.find((c) => c.id === id)?.name ?? '';
}

/** Patch a task in the list in place (after a local update) without a refetch. */
export function upsertTask(task: TaskOut): void {
  const idx = tasks.items.findIndex((t) => t.id === task.id);
  if (idx >= 0) {
    tasks.items[idx] = task;
  } else {
    tasks.items = [task, ...tasks.items];
    tasks.total += 1;
  }
}

export function removeTask(id: string): void {
  const before = tasks.items.length;
  tasks.items = tasks.items.filter((t) => t.id !== id);
  if (tasks.items.length !== before) tasks.total = Math.max(0, tasks.total - 1);
}

let bound = false;

export function bindTaskEvents(): void {
  if (bound) return;
  bound = true;
  const refresh = debounced(() => {
    if (tasks.loaded) void loadTasks();
  }, 400);
  onEvent(
    ['task.created', 'task.updated', 'task.deleted', 'artifact.created', 'artifact.updated', 'plan.created', 'plan.updated', 'work_item.updated', 'agent_run.finished', 'system.restored'],
    refresh
  );
  onEvent(['task.created', 'task.deleted', 'system.restored'], debounced(() => void loadCategories(), 800));
}
