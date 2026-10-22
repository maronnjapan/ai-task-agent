<script lang="ts">
  import { renderMarkdown } from '../lib/markdown';

  let { source }: { source: string } = $props();
  const html = $derived(renderMarkdown(source));
</script>

<!-- renderMarkdown() sanitizes with DOMPurify before this is injected -->
<div class="markdown">{@html html}</div>
