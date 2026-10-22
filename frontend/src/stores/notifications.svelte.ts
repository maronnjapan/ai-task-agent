import { api } from '../api/client';
import type { NotificationOut } from '../api/types';
import { debounced, onEvent } from './events.svelte';
import { pushToast } from './toasts.svelte';
import { links } from '../lib/router.svelte';

export const notifications: { items: NotificationOut[]; unread: number; total: number; loading: boolean; loaded: boolean } = $state({
  items: [],
  unread: 0,
  total: 0,
  loading: false,
  loaded: false
});

export async function loadNotifications(unreadOnly = true, limit = 30): Promise<void> {
  notifications.loading = true;
  try {
    const page = await api.notifications.list({ unread_only: unreadOnly, limit }, { silent: true });
    notifications.items = page.items;
    notifications.unread = page.unread;
    notifications.total = page.total;
    notifications.loaded = true;
  } catch {
    // keep the previous state; the bell shows what it had
  } finally {
    notifications.loading = false;
  }
}

export async function markAllRead(): Promise<void> {
  await api.notifications.markRead(null);
  notifications.unread = 0;
  notifications.items = notifications.items.map((n) => ({ ...n, status: 'read' }));
}

export async function markRead(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  await api.notifications.markRead(ids);
  const set = new Set(ids);
  notifications.items = notifications.items.map((n) => (set.has(n.id) ? { ...n, status: 'read' } : n));
  notifications.unread = Math.max(0, notifications.unread - ids.length);
}

let bound = false;

/** Hook notification events to the store (call once from the app shell). */
export function bindNotificationEvents(): void {
  if (bound) return;
  bound = true;
  const refresh = debounced(() => void loadNotifications(), 400);
  onEvent('notification.created', (event) => {
    const data = event.data as { notification_id?: string; title?: string; body?: string; level?: string; task_id?: string | null };
    const level = data.level ?? 'normal';
    pushToast(data.title ?? '新しい通知', {
      kind: level === 'urgent' || level === 'error' ? 'error' : level === 'high' || level === 'warning' ? 'warning' : 'info',
      body: data.body,
      href: data.task_id ? links.task(data.task_id) : undefined,
      timeout: 7000
    });
    refresh();
  });
  onEvent(['notification.read', 'system.restored'], refresh);
}
