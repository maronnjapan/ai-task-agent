export type ToastKind = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  body?: string;
  href?: string;
  timeout: number;
}

let nextId = 1;

export const toasts: { items: Toast[] } = $state({ items: [] });

const timers = new Map<number, ReturnType<typeof setTimeout>>();

export function pushToast(title: string, options: { kind?: ToastKind; body?: string; href?: string; timeout?: number } = {}): number {
  const toast: Toast = {
    id: nextId++,
    kind: options.kind ?? 'info',
    title,
    body: options.body,
    href: options.href,
    timeout: options.timeout ?? (options.kind === 'error' ? 8000 : 5000)
  };
  toasts.items = [...toasts.items, toast].slice(-6);
  if (toast.timeout > 0) {
    timers.set(toast.id, setTimeout(() => dismissToast(toast.id), toast.timeout));
  }
  return toast.id;
}

export function dismissToast(id: number): void {
  const timer = timers.get(id);
  if (timer) clearTimeout(timer);
  timers.delete(id);
  toasts.items = toasts.items.filter((t) => t.id !== id);
}

export const toast = {
  info: (title: string, body?: string) => pushToast(title, { kind: 'info', body }),
  success: (title: string, body?: string) => pushToast(title, { kind: 'success', body }),
  warning: (title: string, body?: string) => pushToast(title, { kind: 'warning', body }),
  error: (title: string, body?: string) => pushToast(title, { kind: 'error', body })
};

// ---- Global error banner ----------------------------------------------------

export interface BannerError {
  message: string;
  detail?: string;
  at: number;
}

export const errorBanner: { current: BannerError | null } = $state({ current: null });

export function showError(message: string, detail?: string): void {
  errorBanner.current = { message, detail, at: Date.now() };
}

export function clearError(): void {
  errorBanner.current = null;
}
