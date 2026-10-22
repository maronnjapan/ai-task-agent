// Typed fetch wrapper for the local FastAPI backend (same origin, no auth).
// Every non-GET request carries `X-Requested-With: AIWM` (CSRF guard, SPEC 6.4).
import type * as T from './types';

export const CSRF_HEADER = 'X-Requested-With';
export const CSRF_VALUE = 'AIWM';

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly path: string;

  constructor(status: number, message: string, detail: unknown, path: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.path = path;
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue>;

type ErrorListener = (error: ApiError) => void;
const errorListeners = new Set<ErrorListener>();

/** Register a global listener (used by the error banner). Returns an unsubscribe function. */
export function onApiError(listener: ErrorListener): () => void {
  errorListeners.add(listener);
  return () => errorListeners.delete(listener);
}

/** Build a query string, skipping empty / undefined values. */
export function buildQuery(params?: Query): string {
  if (!params) return '';
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

/** Turn a FastAPI error body into a readable Japanese message. */
export function describeError(status: number, body: unknown): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const parts = detail.map((item) => {
        if (item && typeof item === 'object') {
          const loc = Array.isArray((item as { loc?: unknown }).loc) ? ((item as { loc: unknown[] }).loc as unknown[]).filter((p) => p !== 'body').join('.') : '';
          const msg = String((item as { msg?: unknown }).msg ?? '');
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(item);
      });
      return `入力内容に誤りがあります (${parts.join(' / ')})`;
    }
  }
  if (status === 0) return 'サーバーに接続できません';
  if (status === 403) return '操作が拒否されました (403)';
  if (status === 404) return '対象が見つかりません (404)';
  if (status >= 500) return `サーバーエラー (${status})`;
  return `リクエストに失敗しました (${status})`;
}

export interface RequestOptions {
  /** When true the global error listeners are not notified (caller handles the error itself). */
  silent?: boolean;
  signal?: AbortSignal;
}

export async function request<R>(method: Method, path: string, body?: unknown, options: RequestOptions = {}): Promise<R> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') {
    headers[CSRF_HEADER] = CSRF_VALUE;
    headers['Content-Type'] = 'application/json';
  }
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      signal: options.signal
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    const error = new ApiError(0, describeError(0, null), null, path);
    if (!options.silent) errorListeners.forEach((fn) => fn(error));
    throw error;
  }
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!response.ok) {
    const error = new ApiError(response.status, describeError(response.status, parsed), parsed, path);
    if (!options.silent) errorListeners.forEach((fn) => fn(error));
    throw error;
  }
  return parsed as R;
}

const get = <R>(path: string, query?: Query, options?: RequestOptions) => request<R>('GET', path + buildQuery(query), undefined, options);
const post = <R>(path: string, body?: unknown, options?: RequestOptions) => request<R>('POST', path, body, options);
const put = <R>(path: string, body?: unknown, options?: RequestOptions) => request<R>('PUT', path, body, options);
const patch = <R>(path: string, body?: unknown, options?: RequestOptions) => request<R>('PATCH', path, body, options);
const del = <R>(path: string, body?: unknown, options?: RequestOptions) => request<R>('DELETE', path, body, options);

const enc = encodeURIComponent;

export const api = {
  tasks: {
    list: (params?: T.TaskListParams) => get<T.TaskListOut>('/api/tasks', params as Query),
    get: (id: string, options?: RequestOptions) => get<T.TaskOut>(`/api/tasks/${enc(id)}`, undefined, options),
    create: (data: T.TaskCreate) => post<T.TaskOut>('/api/tasks', data),
    update: (id: string, data: T.TaskUpdate) => patch<T.TaskOut>(`/api/tasks/${enc(id)}`, data),
    remove: (id: string) => del<T.TaskOut>(`/api/tasks/${enc(id)}`),
    restore: (id: string) => post<T.TaskOut>(`/api/tasks/${enc(id)}/restore`),
    approve: (id: string, data?: T.ApproveRequest) => post<T.TaskOut>(`/api/tasks/${enc(id)}/approve`, data ?? {}),
    reopen: (id: string, data?: T.ApproveRequest) => post<T.TaskOut>(`/api/tasks/${enc(id)}/reopen`, data ?? {}),
    revision: (id: string, data: T.RevisionRequest) => post<T.TaskOut>(`/api/tasks/${enc(id)}/revision`, data),
    history: (id: string) => get<T.TaskVersionOut[]>(`/api/tasks/${enc(id)}/history`),
    revert: (id: string, data: T.TaskRevert) => post<T.TaskOut>(`/api/tasks/${enc(id)}/revert`, data),
    contexts: (id: string) => get<T.TaskContextOut[]>(`/api/tasks/${enc(id)}/contexts`),
    addContext: (id: string, data: T.TaskContextCreate) => post<T.TaskContextOut>(`/api/tasks/${enc(id)}/contexts`, data),
    artifacts: (id: string) => get<T.ArtifactOut[]>(`/api/tasks/${enc(id)}/artifacts`),
    decisions: (id: string, includeHistory = false) => get<T.DecisionOut[]>(`/api/tasks/${enc(id)}/decisions`, { include_history: includeHistory }),
    addDecision: (id: string, data: T.DecisionCreate) => post<T.DecisionOut>(`/api/tasks/${enc(id)}/decisions`, data),
    plans: (id: string) => get<T.ExecutionPlanOut[]>(`/api/tasks/${enc(id)}/plans`),
    runs: (id: string, limit = 50) => get<T.AgentRunOut[]>(`/api/tasks/${enc(id)}/runs`, { limit }),
    chats: (id: string) => get<T.ChatOut[]>(`/api/tasks/${enc(id)}/chats`),
    createChat: (id: string, title?: string | null) => post<T.ChatOut>(`/api/tasks/${enc(id)}/chats`, { title: title ?? null })
  },
  categories: {
    list: () => get<T.CategoryOut[]>('/api/categories'),
    create: (name: string) => post<T.CategoryOut>('/api/categories', { name }),
    update: (id: string, name: string) => patch<T.CategoryOut>(`/api/categories/${enc(id)}`, { name }),
    remove: (id: string) => del<T.Message>(`/api/categories/${enc(id)}`)
  },
  chats: {
    remove: (chatId: string) => del<T.Message>(`/api/chats/${enc(chatId)}`),
    messages: (chatId: string, params?: { before?: string | null; limit?: number }) =>
      get<T.MessagePage>(`/api/chats/${enc(chatId)}/messages`, { before: params?.before ?? undefined, limit: params?.limit }),
    send: (chatId: string, data: T.MessageCreate) => post<T.MessageOut>(`/api/chats/${enc(chatId)}/messages`, data)
  },
  decisions: {
    revoke: (id: string) => del<T.DecisionOut>(`/api/decisions/${enc(id)}`)
  },
  manager: {
    status: (options?: RequestOptions) => get<T.ManagerStatusOut>('/api/manager/status', undefined, options),
    instruct: (instruction: string, taskIds: string[] = []) => post<T.InstructionOut>('/api/manager/instruct', { instruction, task_ids: taskIds }),
    run: () => post<T.Message>('/api/manager/run'),
    pause: () => post<T.ManagerStatusOut>('/api/manager/pause'),
    resume: () => post<T.ManagerStatusOut>('/api/manager/resume'),
    runs: (params?: { agent_type?: string; plan_id?: string; limit?: number; offset?: number }) => get<T.AgentRunOut[]>('/api/manager/runs', params),
    schedule: (limit = 50) => get<T.ScheduledActionOut[]>('/api/manager/schedule', { limit }),
    cancelSchedule: (id: string) => del<T.Message>(`/api/manager/schedule/${enc(id)}`)
  },
  plans: {
    list: (params?: { status?: string; task_id?: string; limit?: number; offset?: number }) => get<T.ExecutionPlanOut[]>('/api/execution-plans', params),
    get: (id: string) => get<T.ExecutionPlanOut>(`/api/execution-plans/${enc(id)}`),
    workItems: (id: string) => get<T.WorkItemOut[]>(`/api/execution-plans/${enc(id)}/work-items`),
    reviews: (id: string) => get<T.ReviewOut[]>(`/api/execution-plans/${enc(id)}/reviews`)
  },
  artifacts: {
    list: (params?: { status?: string; limit?: number; offset?: number }) => get<T.ArtifactOut[]>('/api/artifacts', params),
    get: (id: string, options?: RequestOptions) => get<T.ArtifactOut>(`/api/artifacts/${enc(id)}`, undefined, options),
    content: (id: string, version?: number) => get<T.ArtifactContentOut>(`/api/artifacts/${enc(id)}/content`, { version }),
    updateContent: (id: string, content: string, changeNote?: string | null) =>
      put<T.ArtifactOut>(`/api/artifacts/${enc(id)}/content`, { content, change_note: changeNote ?? null }),
    versions: (id: string) => get<T.ArtifactVersionOut[]>(`/api/artifacts/${enc(id)}/versions`),
    restore: (id: string, version: number) => post<T.ArtifactOut>(`/api/artifacts/${enc(id)}/restore`, { version }),
    diff: (id: string, from: number, to?: number) => get<T.ArtifactDiffOut>(`/api/artifacts/${enc(id)}/diff`, { from, to }),
    approve: (id: string) => post<T.ArtifactOut>(`/api/artifacts/${enc(id)}/approve`),
    revision: (id: string, instructions: string, kind = 'revision') => post<T.ArtifactOut>(`/api/artifacts/${enc(id)}/revision`, { instructions, kind }),
    open: (id: string) => post<T.Message>(`/api/artifacts/${enc(id)}/open`)
  },
  memories: {
    list: (params?: { scope?: string; task_id?: string; category_id?: string; kind?: string; q?: string; limit?: number; offset?: number }) =>
      get<T.MemoryOut[]>('/api/memories', params),
    create: (data: T.MemoryCreate) => post<T.MemoryOut>('/api/memories', data),
    update: (id: string, data: T.MemoryUpdate) => patch<T.MemoryOut>(`/api/memories/${enc(id)}`, data),
    remove: (id: string) => del<T.Message>(`/api/memories/${enc(id)}`)
  },
  userState: {
    get: () => get<T.UserStateOut>('/api/user-state'),
    set: (data: T.UserStateUpdate) => put<T.UserStateOut>('/api/user-state', data)
  },
  notifications: {
    list: (params?: { unread_only?: boolean; limit?: number; offset?: number }, options?: RequestOptions) =>
      get<T.NotificationListOut>('/api/notifications', params, options),
    markRead: (ids?: string[] | null) => post<T.Message>('/api/notifications/read', { ids: ids ?? null })
  },
  approvals: {
    list: (status: string | null = 'pending') => get<T.ApprovalOut[]>('/api/approvals', { status: status ?? '' }),
    resolve: (id: string, data: T.ApprovalDecision) => post<T.ApprovalOut>(`/api/approvals/${enc(id)}`, data)
  },
  audit: {
    list: (params?: { entity_type?: string; entity_id?: string; event_type?: string; limit?: number; offset?: number }) => get<T.AuditListOut>('/api/audit', params)
  },
  integrations: {
    list: () => get<T.IntegrationOut[]>('/api/integrations'),
    presets: () => get<T.AdapterPresetOut[]>('/api/integrations/presets'),
    get: (id: string) => get<T.IntegrationOut>(`/api/integrations/${enc(id)}`),
    create: (data: T.IntegrationCreate) => post<T.IntegrationOut>('/api/integrations', data),
    update: (id: string, data: T.IntegrationUpdate) => patch<T.IntegrationOut>(`/api/integrations/${enc(id)}`, data),
    remove: (id: string) => del<T.Message>(`/api/integrations/${enc(id)}`),
    test: (id: string) => post<T.ConnectionTestOut>(`/api/integrations/${enc(id)}/test`),
    tools: (id: string) => get<T.ToolOut[]>(`/api/integrations/${enc(id)}/tools`),
    oauthStart: (id: string) => post<T.OAuthStartOut>(`/api/integrations/${enc(id)}/oauth/start`),
    oauthRevoke: (id: string) => post<T.Message>(`/api/integrations/${enc(id)}/oauth/revoke`)
  },
  settings: {
    get: () => get<T.SettingsOut>('/api/settings'),
    patch: (data: T.SettingsPatch) => patch<T.SettingsOut>('/api/settings', data),
    setApiKey: (provider: string, apiKey: string) => post<T.ProviderKeyStatus[]>('/api/settings/api-keys', { provider, api_key: apiKey }),
    deleteApiKey: (provider: string) => del<T.ProviderKeyStatus[]>('/api/settings/api-keys', { provider }),
    autostart: (enabled: boolean) => post<T.Message>('/api/settings/autostart', { enabled })
  },
  system: {
    status: () => get<T.SystemStatusOut>('/api/system/status'),
    backup: (data?: { directory?: string | null; label?: string | null }) => post<T.BackupOut>('/api/system/backup', data ?? {}),
    backups: () => get<T.BackupOut[]>('/api/system/backups'),
    restore: (path: string) => post<T.RestoreOut>('/api/system/restore', { path, confirm: true }),
    openDataDir: () => post<{ ok: boolean; path: string }>('/api/system/open-data-dir'),
    eventsUrl: '/api/system/events'
  }
};

export type Api = typeof api;
