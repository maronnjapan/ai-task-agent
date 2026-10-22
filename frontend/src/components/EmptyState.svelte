<script lang="ts">
  import type { Snippet } from 'svelte';
  let { text = 'データがありません', children }: { text?: string; children?: Snippet } = $props();
</script>

<div class="empty">
  <p>{text}</p>
  {#if children}{@render children()}{/if}
</div>
