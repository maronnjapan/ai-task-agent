import type { DiffLine } from '../api/types';

/**
 * Line-based diff (LCS) producing the same `{type, text}` shape as the backend's
 * artifact diff so one <DiffView> renders both. For very large inputs the DP table
 * would be too big, so we fall back to a plain "removed all / added all" listing.
 */
export function diffLines(oldText: string, newText: string, maxCells = 4_000_000): DiffLine[] {
  const a = splitLines(oldText);
  const b = splitLines(newText);
  if (a.length === 0 && b.length === 0) return [];

  // Trim the common prefix / suffix first: cheap and keeps the DP small.
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }

  const out: DiffLine[] = [];
  for (let i = 0; i < start; i++) out.push({ type: 'context', text: a[i] });

  const midA = a.slice(start, endA);
  const midB = b.slice(start, endB);
  if (midA.length * midB.length > maxCells) {
    for (const text of midA) out.push({ type: 'removed', text });
    for (const text of midB) out.push({ type: 'added', text });
  } else {
    out.push(...lcsDiff(midA, midB));
  }

  for (let i = endA; i < a.length; i++) out.push({ type: 'context', text: a[i] });
  return out;
}

function splitLines(text: string): string[] {
  if (text === '') return [];
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  if (lines.length > 0 && lines[lines.length - 1] === '' && text.endsWith('\n')) lines.pop();
  return lines;
}

function lcsDiff(a: string[], b: string[]): DiffLine[] {
  const n = a.length;
  const m = b.length;
  if (n === 0) return b.map((text) => ({ type: 'added', text }));
  if (m === 0) return a.map((text) => ({ type: 'removed', text }));

  // dp[i][j] = LCS length of a[i:], b[j:]
  const width = m + 1;
  const dp = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * width + j] = a[i] === b[j] ? dp[(i + 1) * width + j + 1] + 1 : Math.max(dp[(i + 1) * width + j], dp[i * width + j + 1]);
    }
  }

  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ type: 'context', text: a[i] });
      i++;
      j++;
    } else if (dp[(i + 1) * width + j] >= dp[i * width + j + 1]) {
      out.push({ type: 'removed', text: a[i] });
      i++;
    } else {
      out.push({ type: 'added', text: b[j] });
      j++;
    }
  }
  while (i < n) out.push({ type: 'removed', text: a[i++] });
  while (j < m) out.push({ type: 'added', text: b[j++] });
  return out;
}

/** Stringify an arbitrary value (task history field) for line diffing. */
export function valueToText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

export interface FieldDiff {
  field: string;
  lines: DiffLine[];
  changed: boolean;
}

/** Diff two task-version snapshots field by field. */
export function diffRecords(previous: Record<string, unknown> | null | undefined, revised: Record<string, unknown> | null | undefined): FieldDiff[] {
  const keys = new Set<string>([...Object.keys(previous ?? {}), ...Object.keys(revised ?? {})]);
  const result: FieldDiff[] = [];
  for (const field of keys) {
    const before = valueToText(previous?.[field]);
    const after = valueToText(revised?.[field]);
    if (before === after) continue;
    result.push({ field, lines: diffLines(before, after), changed: true });
  }
  return result.sort((x, y) => x.field.localeCompare(y.field));
}

export function diffStats(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of lines) {
    if (line.type === 'added') added++;
    else if (line.type === 'removed') removed++;
  }
  return { added, removed };
}
