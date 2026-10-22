import { describe, expect, it } from 'vitest';
import { diffLines, diffRecords, diffStats, valueToText } from './diff';

describe('diffLines', () => {
  it('returns an empty list for two empty inputs', () => {
    expect(diffLines('', '')).toEqual([]);
  });

  it('marks identical text as context only', () => {
    const lines = diffLines('a\nb\nc', 'a\nb\nc');
    expect(lines.every((l) => l.type === 'context')).toBe(true);
    expect(lines.map((l) => l.text)).toEqual(['a', 'b', 'c']);
  });

  it('detects an inserted line', () => {
    const lines = diffLines('a\nc', 'a\nb\nc');
    expect(lines).toEqual([
      { type: 'context', text: 'a' },
      { type: 'added', text: 'b' },
      { type: 'context', text: 'c' }
    ]);
  });

  it('detects a removed and a changed line', () => {
    const lines = diffLines('one\ntwo\nthree', 'one\nTWO');
    expect(diffStats(lines)).toEqual({ added: 1, removed: 2 });
    expect(lines.filter((l) => l.type === 'removed').map((l) => l.text)).toEqual(['two', 'three']);
    expect(lines.filter((l) => l.type === 'added').map((l) => l.text)).toEqual(['TWO']);
  });

  it('handles CRLF and a trailing newline', () => {
    const lines = diffLines('a\r\nb\r\n', 'a\nb\n');
    expect(lines.every((l) => l.type === 'context')).toBe(true);
    expect(lines).toHaveLength(2);
  });

  it('falls back to a plain listing when the input is too large for the DP table', () => {
    const lines = diffLines('x\ny', 'p\nq', 1);
    expect(lines.map((l) => l.type)).toEqual(['removed', 'removed', 'added', 'added']);
  });
});

describe('diffRecords', () => {
  it('only reports fields whose values differ', () => {
    const result = diffRecords({ title: 'A', status: 'todo', due_at: null }, { title: 'B', status: 'todo', due_at: '2026-01-01T00:00:00Z' });
    expect(result.map((r) => r.field)).toEqual(['due_at', 'title']);
    const title = result.find((r) => r.field === 'title')!;
    expect(title.lines).toEqual([
      { type: 'removed', text: 'A' },
      { type: 'added', text: 'B' }
    ]);
  });

  it('treats a missing previous snapshot as empty', () => {
    const result = diffRecords(null, { title: 'New' });
    expect(result).toHaveLength(1);
    expect(result[0].lines).toEqual([{ type: 'added', text: 'New' }]);
  });
});

describe('valueToText', () => {
  it('stringifies non-string values and maps null to an empty string', () => {
    expect(valueToText(null)).toBe('');
    expect(valueToText('x')).toBe('x');
    expect(valueToText({ a: 1 })).toBe('{\n  "a": 1\n}');
  });
});
