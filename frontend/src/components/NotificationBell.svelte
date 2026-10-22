<script lang="ts">
  import { onMount } from 'svelte';
  import { loadNotifications, markAllRead, markRead, notifications } from '../stores/notifications.svelte';
  import { formatRelative, label, NOTIFICATION_LEVEL_LABELS } from '../lib/format';
  import { links } from '../lib/router.svelte';

  let open = $state(false);
  let root: HTMLElement | undefined = $state();

  function toggle() {
    open = !open;
    if (open) void loadNotifications(false, 20);
  }

  function onDocumentClick(event: MouseEvent) {
    if (open && root && !root.contains(event.target as Node)) open = false;
  }

  function onKey(event: KeyboardEvent) {
    if (event.key === 'Escape') open = false;
  }

  onMount(() => {
    document.addEventListener('click', onDocumentClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', onDocumentClick);
      document.removeEventListener('keydown', onKey);
    };
  });

  const levelClass = (level: string) => (level === 'urgent' || level === 'error' ? 'dot-danger' : level === 'high' || level === 'warning' ? 'dot-warning' : 'dot-accent');
</script>

<div class="bell" bind:this={root}>
  <button type="button" class="btn btn-ghost btn-icon" aria-label="通知 {notifications.unread} 件未読" aria-expanded={open} aria-haspopup="true" onclick={toggle} title="通知">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </svg>
    {#if notifications.unread > 0}
      <span class="count" aria-hidden="true">{notifications.unread > 99 ? '99+' : notifications.unread}</span>
    {/if}
  </button>

  {#if open}
    <div class="panel card" role="dialog" aria-label="通知一覧">
      <div class="card-title">
        <h3>通知</h3>
        <button type="button" class="btn btn-sm" disabled={notifications.unread === 0} onclick={() => void markAllRead()}>すべて既読</button>
      </div>
      {#if notifications.loading && notifications.items.length === 0}
        <div class="empty">読み込み中…</div>
      {:else if notifications.items.length === 0}
        <div class="empty">通知はありません</div>
      {:else}
        <ul class="list-plain items">
          {#each notifications.items as n (n.id)}
            <li class:unread={n.status === 'unread'}>
              <div class="row" style="align-items:flex-start">
                <span class="dot {levelClass(n.level)}" style="margin-top:0.45rem" title={label(NOTIFICATION_LEVEL_LABELS, n.level)}></span>
                <div style="flex:1;min-width:0">
                  <div class="title">{n.title}</div>
                  {#if n.body}<div class="small muted prewrap">{n.body}</div>{/if}
                  <div class="small faint row">
                    <span>{formatRelative(n.created_at)}</span>
                    {#if n.task_id}<a href={links.task(n.task_id)} onclick={() => (open = false)}>タスクを開く</a>{/if}
                    {#if n.status === 'unread'}
                      <button type="button" class="btn btn-ghost btn-sm" onclick={() => void markRead([n.id])}>既読にする</button>
                    {/if}
                  </div>
                </div>
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
</div>

<style>
  .bell {
    position: relative;
  }
  .count {
    position: absolute;
    top: -2px;
    right: -2px;
    background: var(--danger);
    color: #fff;
    font-size: 0.65rem;
    font-weight: 700;
    border-radius: 999px;
    padding: 0 0.3rem;
    min-width: 1rem;
    line-height: 1rem;
    text-align: center;
  }
  .panel {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    width: min(92vw, 380px);
    max-height: 70vh;
    overflow: auto;
    z-index: 50;
    box-shadow: var(--shadow-lg);
  }
  .items li.unread .title {
    font-weight: 600;
  }
  .title {
    word-break: break-word;
  }
</style>
