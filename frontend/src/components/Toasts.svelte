<script lang="ts">
  import { dismissToast, toasts } from '../stores/toasts.svelte';
</script>

<div class="toasts" aria-live="polite" aria-atomic="false">
  {#each toasts.items as t (t.id)}
    <div class="toast toast-{t.kind}" role="status">
      <div class="toast-body">
        <strong>{t.title}</strong>
        {#if t.body}<div class="small prewrap">{t.body}</div>{/if}
        {#if t.href}<a class="small" href={t.href} onclick={() => dismissToast(t.id)}>開く →</a>{/if}
      </div>
      <button type="button" class="btn btn-ghost btn-sm" aria-label="閉じる" onclick={() => dismissToast(t.id)}>×</button>
    </div>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    right: 1rem;
    bottom: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    z-index: 1000;
    max-width: min(92vw, 380px);
  }
  .toast {
    display: flex;
    gap: 0.5rem;
    align-items: flex-start;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-left: 4px solid var(--info);
    border-radius: var(--radius-sm);
    padding: 0.6rem 0.75rem;
    box-shadow: var(--shadow-lg);
    font-size: 0.9rem;
  }
  .toast-body {
    flex: 1;
    min-width: 0;
    word-break: break-word;
  }
  .toast-success {
    border-left-color: var(--success);
  }
  .toast-warning {
    border-left-color: var(--warning);
  }
  .toast-error {
    border-left-color: var(--danger);
  }
</style>
