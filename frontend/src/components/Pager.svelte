<script lang="ts">
  let { offset, limit, total, onchange }: { offset: number; limit: number; total: number; onchange: (offset: number) => void } = $props();

  const from = $derived(total === 0 ? 0 : offset + 1);
  const to = $derived(Math.min(offset + limit, total));
  const hasPrev = $derived(offset > 0);
  const hasNext = $derived(offset + limit < total);
</script>

{#if total > limit}
  <nav class="pager" aria-label="ページ送り">
    <span>{from}–{to} / {total} 件</span>
    <button type="button" class="btn btn-sm" disabled={!hasPrev} onclick={() => onchange(Math.max(0, offset - limit))}>前へ</button>
    <button type="button" class="btn btn-sm" disabled={!hasNext} onclick={() => onchange(offset + limit)}>次へ</button>
  </nav>
{/if}
