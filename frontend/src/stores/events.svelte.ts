// Server-Sent Events hub. One EventSource for the whole app; stores subscribe by event type.
import { api } from '../api/client';
import type { SseEvent, SseEventType } from '../api/types';

export type EventHandler = (event: SseEvent) => void;

const EVENT_TYPES: SseEventType[] = [
  'hello',
  'ping',
  'task.created',
  'task.updated',
  'task.deleted',
  'chat.created',
  'chat.message',
  'chat.typing',
  'decision.recorded',
  'artifact.created',
  'artifact.updated',
  'plan.created',
  'plan.updated',
  'work_items.created',
  'work_item.updated',
  'agent_run.started',
  'agent_run.finished',
  'review.recorded',
  'notification.created',
  'notification.read',
  'approval.requested',
  'approval.resolved',
  'manager.status',
  'settings.updated',
  'integration.oauth',
  'system.restored'
];

const handlers = new Map<string, Set<EventHandler>>();
let source: EventSource | null = null;

export const sse: { connected: boolean; lastEventAt: string | null; serverVersion: string | null } = $state({
  connected: false,
  lastEventAt: null,
  serverVersion: null
});

function dispatch(type: string, raw: MessageEvent): void {
  let event: SseEvent;
  try {
    const parsed = raw.data ? JSON.parse(raw.data) : {};
    if (type === 'hello' || type === 'ping') {
      event = { id: raw.lastEventId || 0, type, data: parsed ?? {}, created_at: new Date().toISOString() };
    } else {
      event = parsed as SseEvent;
      if (!event || typeof event !== 'object') return;
      if (!event.data) event.data = {};
    }
  } catch {
    return;
  }
  sse.lastEventAt = event.created_at ?? new Date().toISOString();
  if (type === 'hello') {
    const version = (event.data as { version?: string }).version;
    if (version) sse.serverVersion = version;
  }
  handlers.get(type)?.forEach((fn) => {
    try {
      fn(event);
    } catch (err) {
      console.error('SSE handler failed', type, err);
    }
  });
  handlers.get('*')?.forEach((fn) => fn(event));
}

/** Connect once (idempotent). EventSource reconnects on its own after errors. */
export function connectEvents(): void {
  if (source || typeof window === 'undefined' || typeof EventSource === 'undefined') return;
  source = new EventSource(api.system.eventsUrl);
  source.onopen = () => {
    sse.connected = true;
  };
  source.onerror = () => {
    sse.connected = false;
  };
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (raw) => dispatch(type, raw as MessageEvent));
  }
}

export function disconnectEvents(): void {
  source?.close();
  source = null;
  sse.connected = false;
}

/** Subscribe to one or more event types ('*' for everything). Returns an unsubscribe function. */
export function onEvent(types: (SseEventType | '*') | (SseEventType | '*')[], handler: EventHandler): () => void {
  const list = Array.isArray(types) ? types : [types];
  for (const type of list) {
    if (!handlers.has(type)) handlers.set(type, new Set());
    handlers.get(type)!.add(handler);
  }
  return () => {
    for (const type of list) handlers.get(type)?.delete(handler);
  };
}

/** Debounce helper so bursts of events trigger a single refetch. */
export function debounced(fn: () => void, wait = 300): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn();
    }, wait);
  };
}
