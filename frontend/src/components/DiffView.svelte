<script lang="ts">
  import type { DiffLine } from '../api/types';
  import { diffStats } from '../lib/diff';

  let { lines, maxHeight = '420px', showStats = true }: { lines: DiffLine[]; maxHeight?: string; showStats?: boolean } = $props();

  const stats = $derived(diffStats(lines));
  const signs: Record<string, string> = { added: '+', removed: '−', context: ' ' };
</script>

{#if showStats}
  <div class="row small muted" style="margin-bottom:0.35rem">
    <span class="text-success">+{stats.added}</span>
    <span class="text-danger">−{stats.removed}</span>
    <span>{lines.length} 行</span>
  </div>
{/if}
{#if lines.length === 0}
  <div class="empty">差分はありません</div>
{:else}
  <div class="diff" style="max-height:{maxHeight}" role="region" aria-label="差分">
    {#each lines as line, i (i)}
      <div class="diff-line diff-{line.type}">
        <span class="sign" aria-hidden="true">{signs[line.type] ?? ' '}</span>
        <span class="text">{line.text || ' '}</span>
      </div>
    {/each}
  </div>
{/if}
