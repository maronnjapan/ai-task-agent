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
  try {
    await api.notifications.markRead(null);
    notifications.unread = 0;
    notifications.items = notifications.items.map((n) => ({ ...n, status: 'read' }));
  } catch {
    // reported by the global error banner
  }
}

export async function markRead(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  try {
    await api.notifications.markRead(ids);
    const set = new Set(ids);
    notifications.items = notifications.items.map((n) => (set.has(n.id) ? { ...n, status: 'read' } : n));
    notifications.unread = Math.max(0, notifications.unread - ids.length);
  } catch {
    // reported by the global error banner
  }
}

let bound = false;

/** Hook notification events to the store (call once from the app shell). */
export function bindNotificationEvents(): void {
  if (bound) return;
  bound = true;
  const refresh = debounced(() => void loadNotifications(), 400);
  onEvent('notification.created', (event) => {
    const data = event.data as { notification_id?: string; title?: string; body?: string; level?: string; task_id?: string | null; quiet?: boolean; channel?: string };
    const level = data.level ?? 'normal';
    // 通知停止時間帯 (quiet hours): keep the history, skip the toast.
    if (!data.quiet) {
      pushToast(data.title ?? '新しい通知', {
        kind: level === 'high' ? 'warning' : 'info',
        body: data.channel === 'manager_message' && data.body ? data.body.slice(0, 400) : data.body,
        href: data.task_id ? links.task(data.task_id) : undefined,
        timeout: data.channel === 'manager_message' ? 10000 : 7000
      });
    }
    refresh();
  });
  onEvent(['notification.read', 'system.restored'], refresh);
}
