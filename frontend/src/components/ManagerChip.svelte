<script lang="ts">
  import { manager } from '../stores/manager.svelte';
  import { label, MANAGER_STATE_LABELS } from '../lib/format';
  import { links } from '../lib/router.svelte';

  const state = $derived(manager.status?.state ?? '');
  const dotClass = $derived(
    state === 'running' ? 'dot-accent dot-pulse' : state === 'paused' ? 'dot-warning' : state === 'error' || manager.status?.llm_ready === false ? 'dot-danger' : state === 'idle' ? 'dot-success' : ''
  );
  const text = $derived(manager.status ? label(MANAGER_STATE_LABELS, state) : '接続中…');
  const activity = $derived(manager.status?.activity ?? '');
  const title = $derived(manager.status?.llm_issue ? `LLM: ${manager.status.llm_issue}` : activity || text);
</script>

<a class="chip" href={links.manager()} {title} aria-label="AIマネージャー状態: {text}{activity ? ' ' + activity : ''}">
  <span class="dot {dotClass}"></span>
  <span class="label">{text}</span>
  {#if activity}<span class="activity muted">{activity}</span>{/if}
  {#if manager.status?.llm_ready === false}<span class="badge badge-danger">LLM未設定</span>{/if}
</a>

<style>
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.25rem 0.6rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.8rem;
    color: var(--text);
    background: var(--bg-elevated);
    max-width: 320px;
  }
  .chip:hover {
    text-decoration: none;
    background: var(--bg-hover);
  }
  .activity {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  @media (max-width: 720px) {
    .activity {
      display: none;
    }
  }
</style>
