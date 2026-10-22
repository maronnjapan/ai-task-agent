// Minimal hash router: #/ , #/tasks/:id , #/artifacts/:id , #/manager , #/settings

export type RouteName = 'tasks' | 'task' | 'artifact' | 'manager' | 'settings' | 'notfound';

export interface Route {
  name: RouteName;
  params: Record<string, string>;
  query: Record<string, string>;
  path: string;
}

function parseHash(hash: string): Route {
  let raw = hash.startsWith('#') ? hash.slice(1) : hash;
  if (!raw.startsWith('/')) raw = `/${raw}`;
  const [pathPart, queryPart = ''] = raw.split('?');
  const query: Record<string, string> = {};
  for (const [key, value] of new URLSearchParams(queryPart)) query[key] = value;
  const segments = pathPart.split('/').filter(Boolean).map(decodeURIComponent);
  const base = { query, path: pathPart };
  if (segments.length === 0) return { name: 'tasks', params: {}, ...base };
  if (segments[0] === 'tasks' && segments.length === 2) return { name: 'task', params: { id: segments[1] }, ...base };
  if (segments[0] === 'artifacts' && segments.length === 2) return { name: 'artifact', params: { id: segments[1] }, ...base };
  if (segments[0] === 'manager' && segments.length === 1) return { name: 'manager', params: {}, ...base };
  if (segments[0] === 'settings' && segments.length === 1) return { name: 'settings', params: {}, ...base };
  return { name: 'notfound', params: {}, ...base };
}

const initial = typeof window === 'undefined' ? parseHash('#/') : parseHash(window.location.hash);

export const route: Route = $state(initial);

function apply(next: Route): void {
  route.name = next.name;
  route.params = next.params;
  route.query = next.query;
  route.path = next.path;
}

if (typeof window !== 'undefined') {
  window.addEventListener('hashchange', () => apply(parseHash(window.location.hash)));
}

/** Navigate to a hash path such as "/tasks/abc". */
export function navigate(path: string, replace = false): void {
  const target = path.startsWith('#') ? path : `#${path.startsWith('/') ? path : `/${path}`}`;
  if (replace) {
    window.location.replace(target);
    apply(parseHash(target));
  } else if (window.location.hash !== target) {
    window.location.hash = target;
  }
}

export const links = {
  tasks: () => '#/',
  task: (id: string) => `#/tasks/${encodeURIComponent(id)}`,
  artifact: (id: string) => `#/artifacts/${encodeURIComponent(id)}`,
  manager: () => '#/manager',
  settings: () => '#/settings'
};

export { parseHash };
