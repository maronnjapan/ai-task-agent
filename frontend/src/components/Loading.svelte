<script lang="ts">
  let { text = '読み込み中…', inline = false }: { text?: string; inline?: boolean } = $props();
</script>

{#if inline}
  <span class="row small muted" role="status" aria-live="polite"><span class="spinner"></span>{text}</span>
{:else}
  <div class="loading-block" role="status" aria-live="polite"><span class="spinner"></span> {text}</div>
{/if}
