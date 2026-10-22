import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, CSRF_HEADER, CSRF_VALUE, api, buildQuery, describeError, onApiError, request } from './client';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('buildQuery', () => {
  it('skips empty, null and undefined values', () => {
    expect(buildQuery({ a: 1, b: '', c: null, d: undefined, e: false, f: 'x y' })).toBe('?a=1&e=false&f=x+y');
    expect(buildQuery({})).toBe('');
    expect(buildQuery(undefined)).toBe('');
  });
});

describe('describeError', () => {
  it('uses a string detail as-is', () => {
    expect(describeError(400, { detail: 'bad' })).toBe('bad');
  });

  it('summarises FastAPI validation errors', () => {
    const body = { detail: [{ loc: ['body', 'title'], msg: 'field required', type: 'missing' }] };
    expect(describeError(422, body)).toContain('title: field required');
  });

  it('has Japanese fallbacks per status', () => {
    expect(describeError(0, null)).toContain('接続できません');
    expect(describeError(404, {})).toContain('404');
    expect(describeError(500, 'oops')).toContain('500');
  });
});

describe('request', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends GET without the CSRF header and parses JSON', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }));
    const out = await api.tasks.list({ status: 'todo', include_completed: false });
    expect(out.total).toBe(0);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/tasks?status=todo&include_completed=false');
    expect(init?.method).toBe('GET');
    expect((init?.headers as Record<string, string>)[CSRF_HEADER]).toBeUndefined();
    expect(init?.body).toBeUndefined();
  });

  it('adds X-Requested-With and JSON content type on writes', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 't1', title: 'x' }));
    await api.tasks.create({ title: 'x' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/tasks');
    expect(init?.method).toBe('POST');
    const headers = init?.headers as Record<string, string>;
    expect(headers[CSRF_HEADER]).toBe(CSRF_VALUE);
    expect(headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(String(init?.body))).toEqual({ title: 'x' });
  });

  it('sends a JSON body with DELETE (api key removal)', async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.settings.deleteApiKey('openai');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/settings/api-keys');
    expect(init?.method).toBe('DELETE');
    expect(JSON.parse(String(init?.body))).toEqual({ provider: 'openai' });
  });

  it('encodes path parameters', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'a/b' }));
    await api.tasks.get('a/b');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/tasks/a%2Fb');
  });

  it('throws ApiError with the server detail and notifies listeners', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Task not found' }, 404));
    const seen: ApiError[] = [];
    const off = onApiError((e) => seen.push(e));
    await expect(request('GET', '/api/tasks/nope')).rejects.toMatchObject({ status: 404, message: 'Task not found' });
    off();
    expect(seen).toHaveLength(1);
    expect(seen[0]).toBeInstanceOf(ApiError);
  });

  it('does not notify listeners for silent requests', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'nope' }, 403));
    const listener = vi.fn();
    const off = onApiError(listener);
    await expect(api.manager.status({ silent: true })).rejects.toBeInstanceOf(ApiError);
    off();
    expect(listener).not.toHaveBeenCalled();
  });

  it('maps a network failure to status 0', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(request('GET', '/api/system/status')).rejects.toMatchObject({ status: 0 });
  });

  it('returns null for an empty body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }));
    await expect(request('POST', '/api/manager/run')).resolves.toBeNull();
  });
});
