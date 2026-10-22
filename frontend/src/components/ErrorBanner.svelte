<script lang="ts">
  import { clearError, errorBanner } from '../stores/toasts.svelte';
</script>

{#if errorBanner.current}
  <div class="banner" role="alert">
    <span class="msg">
      <strong>エラー:</strong> {errorBanner.current.message}
      {#if errorBanner.current.detail}<span class="muted small"> ({errorBanner.current.detail})</span>{/if}
    </span>
    <button type="button" class="btn btn-ghost btn-sm" aria-label="閉じる" onclick={clearError}>×</button>
  </div>
{/if}

<style>
  .banner {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 1.25rem;
    background: var(--danger-soft);
    color: var(--danger);
    border-bottom: 1px solid var(--danger);
    font-size: 0.9rem;
  }
  .msg {
    flex: 1;
    word-break: break-word;
  }
</style>
