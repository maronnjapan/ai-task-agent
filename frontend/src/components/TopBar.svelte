<script lang="ts">
  import NotificationBell from './NotificationBell.svelte';
  import ManagerChip from './ManagerChip.svelte';
  import { links, route } from '../lib/router.svelte';
  import { sse } from '../stores/events.svelte';

  const nav = [
    { href: links.tasks(), label: 'タスク', names: ['tasks', 'task', 'artifact'] },
    { href: links.manager(), label: 'AIマネージャー', names: ['manager'] },
    { href: links.settings(), label: '設定', names: ['settings'] }
  ];
</script>

<header class="topbar">
  <a class="brand" href={links.tasks()}>
    <span class="logo" aria-hidden="true">AI</span>
    <span class="name">Autonomous AI Work Manager</span>
  </a>
  <nav aria-label="メインナビゲーション">
    {#each nav as item (item.href)}
      <a href={item.href} aria-current={item.names.includes(route.name) ? 'page' : undefined}>{item.label}</a>
    {/each}
  </nav>
  <div class="spacer"></div>
  <ManagerChip />
  {#if !sse.connected}
    <span class="badge badge-warning" title="サーバーとのイベント接続が切れています">オフライン</span>
  {/if}
  <NotificationBell />
</header>

<style>
  .topbar {
    position: sticky;
    top: 0;
    z-index: 40;
    display: flex;
    align-items: center;
    gap: 1rem;
    height: var(--topbar-h);
    padding: 0 1.25rem;
    background: var(--bg-elevated);
    border-bottom: 1px solid var(--border);
  }
  .brand {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--text);
    font-weight: 700;
    white-space: nowrap;
  }
  .brand:hover {
    text-decoration: none;
  }
  .logo {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 6px;
    background: var(--accent);
    color: #fff;
    font-size: 0.7rem;
    font-weight: 800;
  }
  nav {
    display: flex;
    gap: 0.25rem;
  }
  nav a {
    padding: 0.35rem 0.7rem;
    border-radius: var(--radius-sm);
    color: var(--text-muted);
    font-weight: 500;
  }
  nav a:hover {
    text-decoration: none;
    background: var(--bg-hover);
    color: var(--text);
  }
  nav a[aria-current="page"] {
    color: var(--accent);
    background: var(--accent-soft);
  }
  @media (max-width: 720px) {
    .topbar {
      gap: 0.5rem;
      padding: 0 0.75rem;
    }
    .name {
      display: none;
    }
    nav a {
      padding: 0.35rem 0.5rem;
      font-size: 0.85rem;
    }
  }
</style>
