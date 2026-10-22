import { api } from '../api/client';
import type { ManagerStatusOut } from '../api/types';
import { debounced, onEvent } from './events.svelte';
import { toast } from './toasts.svelte';

export const manager: { status: ManagerStatusOut | null; busy: boolean; loaded: boolean } = $state({
  status: null,
  busy: false,
  loaded: false
});

export async function loadManagerStatus(): Promise<void> {
  try {
    manager.status = await api.manager.status({ silent: true });
    manager.loaded = true;
  } catch {
    // leave the previous status in place
  }
}

export const isPaused = () => manager.status?.state === 'paused';
export const isRunning = () => manager.status?.state === 'running';

export async function runManagerNow(): Promise<void> {
  manager.busy = true;
  try {
    const result = await api.manager.run();
    toast.success('Manager AI を起動しました', result.message || undefined);
    await loadManagerStatus();
  } finally {
    manager.busy = false;
  }
}

export async function pauseManager(): Promise<void> {
  manager.busy = true;
  try {
    manager.status = await api.manager.pause();
    toast.info('Manager AI を一時停止しました');
  } finally {
    manager.busy = false;
  }
}

export async function resumeManager(): Promise<void> {
  manager.busy = true;
  try {
    manager.status = await api.manager.resume();
    toast.success('Manager AI を再開しました');
  } finally {
    manager.busy = false;
  }
}

let bound = false;

export function bindManagerEvents(): void {
  if (bound) return;
  bound = true;
  const refresh = debounced(() => void loadManagerStatus(), 500);
  onEvent('manager.status', (event) => {
    const data = event.data as { state?: string; activity?: string | null; run_id?: string | null };
    if (manager.status) {
      manager.status = {
        ...manager.status,
        state: data.state ?? manager.status.state,
        activity: data.activity ?? null,
        current_run_id: data.run_id ?? null
      };
    }
    refresh();
  });
  onEvent('hello', (event) => {
    const data = event.data as { manager?: ManagerStatusOut | null };
    if (data.manager) {
      manager.status = data.manager;
      manager.loaded = true;
    }
  });
  onEvent(['agent_run.started', 'agent_run.finished', 'plan.updated', 'plan.created', 'settings.updated', 'system.restored'], refresh);
}
