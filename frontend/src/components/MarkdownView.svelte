<script lang="ts">
  // The Markdown renderer (marked + DOMPurify) is loaded on first use so that pages which only
  // show a few messages do not pay for it up front (SPEC 22.6 Markdownの遅延読み込み).
  type Renderer = (source: string) => string;
  let renderer = $state<Renderer | null>(null);
  let loadingRenderer: Promise<Renderer> | null = null;

  function ensureRenderer(): Promise<Renderer> {
    if (!loadingRenderer) {
      loadingRenderer = import('../lib/markdown').then((m) => {
        renderer = m.renderMarkdown;
        return m.renderMarkdown;
      });
    }
    return loadingRenderer;
  }

  let { source }: { source: string } = $props();
  const html = $derived(renderer ? renderer(source) : '');

  $effect(() => {
    if (!renderer) void ensureRenderer();
  });
</script>

{#if renderer}
  <!-- renderMarkdown() sanitizes with DOMPurify before this is injected -->
  <div class="markdown">{@html html}</div>
{:else}
  <pre class="markdown-fallback">{source}</pre>
{/if}

<style>
  .markdown-fallback {
    white-space: pre-wrap;
    font: inherit;
    margin: 0;
  }
</style>
