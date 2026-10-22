// Date formatting (browser local timezone) and Japanese labels for API enums.

const TZ_SUFFIX = /(Z|[+-]\d{2}:?\d{2})$/;

/** Parse an ISO-8601 string from the API. Strings without a timezone are UTC. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const text = TZ_SUFFIX.test(value) ? value : `${value}Z`;
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

const dateTimeFmt = new Intl.DateTimeFormat('ja-JP', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
const dateFmt = new Intl.DateTimeFormat('ja-JP', { year: 'numeric', month: '2-digit', day: '2-digit' });
const timeFmt = new Intl.DateTimeFormat('ja-JP', { hour: '2-digit', minute: '2-digit' });

export function formatDateTime(value: string | null | undefined, fallback = '—'): string {
  const date = parseDate(value);
  return date ? dateTimeFmt.format(date) : fallback;
}

export function formatDate(value: string | null | undefined, fallback = '—'): string {
  const date = parseDate(value);
  return date ? dateFmt.format(date) : fallback;
}

export function formatTime(value: string | null | undefined, fallback = ''): string {
  const date = parseDate(value);
  return date ? timeFmt.format(date) : fallback;
}

/** "3分前" / "2時間後" style relative time. */
export function formatRelative(value: string | null | undefined, now: Date = new Date()): string {
  const date = parseDate(value);
  if (!date) return '—';
  const diff = date.getTime() - now.getTime();
  const abs = Math.abs(diff);
  const suffix = diff < 0 ? '前' : '後';
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (abs < minute) return diff < 0 ? 'たった今' : 'まもなく';
  if (abs < hour) return `${Math.round(abs / minute)}分${suffix}`;
  if (abs < day) return `${Math.round(abs / hour)}時間${suffix}`;
  if (abs < 30 * day) return `${Math.round(abs / day)}日${suffix}`;
  return dateFmt.format(date);
}

export function isOverdue(dueAt: string | null | undefined, status?: string | null, now: Date = new Date()): boolean {
  if (status === 'completed') return false;
  const date = parseDate(dueAt);
  return !!date && date.getTime() < now.getTime();
}

/** Convert an ISO timestamp into a value for <input type="datetime-local"> (local time). */
export function toDateTimeLocal(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Convert a datetime-local input value into an ISO-8601 UTC string (or null). */
export function fromDateTimeLocal(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx++;
  }
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds)) return '—';
  const s = Math.floor(seconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const parts: string[] = [];
  if (d) parts.push(`${d}日`);
  if (h) parts.push(`${h}時間`);
  parts.push(`${m}分`);
  return parts.join(' ');
}

// ---- Labels ---------------------------------------------------------------

export const TASK_STATUS_LABELS: Record<string, string> = {
  todo: '未着手',
  in_progress: '進行中',
  review_pending: '確認待ち',
  blocked: 'ブロック',
  completed: '完了'
};

export const TASK_STATUS_ORDER = ['todo', 'in_progress', 'review_pending', 'blocked', 'completed'] as const;

export const ASSIGNEE_LABELS: Record<string, string> = {
  user: 'ユーザー',
  ai: 'AI',
  shared: '共同'
};

export const PLAN_STATUS_LABELS: Record<string, string> = {
  planned: '計画済み',
  running: '実行中',
  reviewing: 'レビュー中',
  review_pending: '確認待ち',
  completed: '完了',
  done: '完了',
  failed: '失敗',
  cancelled: 'キャンセル',
  blocked: 'ブロック',
  superseded: '再計画済み'
};

export const WORK_ITEM_STATUS_LABELS: Record<string, string> = {
  pending: '待機',
  running: '実行中',
  done: '完了',
  succeeded: '完了',
  failed: '失敗',
  blocked: 'ブロック',
  cancelled: 'キャンセル',
  skipped: 'スキップ'
};

export const RUN_STATUS_LABELS: Record<string, string> = {
  running: '実行中',
  succeeded: '成功',
  completed: '成功',
  failed: '失敗',
  cancelled: 'キャンセル'
};

export const REVIEW_STATUS_LABELS: Record<string, string> = {
  passed: '合格',
  failed: '不合格',
  pending: '保留'
};

export const ARTIFACT_STATUS_LABELS: Record<string, string> = {
  draft: '下書き',
  review_pending: '確認待ち',
  approved: '承認済み',
  revision_requested: '修正依頼中',
  user_revision: 'ユーザー編集'
};

export const APPROVAL_STATUS_LABELS: Record<string, string> = {
  pending: '承認待ち',
  approved: '承認',
  rejected: '却下'
};

export const SCHEDULE_STATUS_LABELS: Record<string, string> = {
  pending: '予定',
  processed: '実行済み',
  cancelled: 'キャンセル',
  failed: '失敗'
};

export const DECISION_STATUS_LABELS: Record<string, string> = {
  active: '有効',
  superseded: '上書き済み',
  revoked: '取消'
};

export const MANAGER_STATE_LABELS: Record<string, string> = {
  idle: '待機中',
  running: '実行中',
  paused: '一時停止',
  disabled: '無効',
  error: 'エラー',
  starting: '起動中'
};

export const AGENT_TYPE_LABELS: Record<string, string> = {
  manager: 'Manager',
  worker: 'Worker',
  review: 'Review',
  chat: 'チャット',
  instruction: '指示'
};

export const ACTOR_LABELS: Record<string, string> = {
  user: 'ユーザー',
  ai: 'AI',
  system: 'システム',
  assistant: 'AI',
  manager: 'Manager AI'
};

export const AUTHOR_LABELS: Record<string, string> = {
  user: 'あなた',
  ai: 'AI',
  assistant: 'AI',
  system: 'システム'
};

export const NOTIFICATION_LEVEL_LABELS: Record<string, string> = {
  low: '低',
  normal: '通常',
  high: '高',
  urgent: '緊急',
  info: '情報',
  warning: '警告',
  error: 'エラー'
};

export const MEMORY_KIND_LABELS: Record<string, string> = {
  hypothesis: '仮説',
  ai_inference: 'AI推論',
  research: '調査結果',
  decision: '決定'
};

export const MEMORY_SCOPE_LABELS: Record<string, string> = {
  global: '全体',
  category: 'カテゴリー',
  task: 'タスク'
};

export const TASK_FIELD_LABELS: Record<string, string> = {
  title: 'タイトル',
  description: '説明',
  due_at: '期限',
  category_id: 'カテゴリー',
  status: 'ステータス',
  assignee: '担当'
};

export const TOOL_PERMISSION_LABELS: Record<string, string> = {
  read: '読み取り',
  internal_write: '内部書き込み',
  external_write: '外部書き込み (要承認)'
};

export const AUTONOMY_LABELS: Record<string, string> = {
  conservative: '控えめ',
  balanced: 'バランス',
  proactive: '積極的'
};

export const REMINDER_LABELS: Record<string, string> = {
  quiet: '控えめ',
  normal: '通常',
  aggressive: '積極的'
};

export const NOTIFICATION_SETTING_LEVELS: Record<string, string> = {
  minimal: '最小限',
  normal: '通常',
  verbose: '詳細'
};

export function label(map: Record<string, string>, key: string | null | undefined, fallback?: string): string {
  if (key === null || key === undefined || key === '') return fallback ?? '—';
  return map[key] ?? fallback ?? key;
}

export function truncate(text: string | null | undefined, max = 80): string {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function pluralCount(count: number | null | undefined, unit = '件'): string {
  return `${count ?? 0}${unit}`;
}
