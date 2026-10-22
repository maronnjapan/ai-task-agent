<script lang="ts">
  import type { AgentRunOut } from '../api/types';
  import StatusBadge from './StatusBadge.svelte';
  import { AGENT_TYPE_LABELS, formatDateTime, label, parseDate } from '../lib/format';

  let { runs, compact = false }: { runs: AgentRunOut[]; compact?: boolean } = $props();

  let open: Record<string, boolean> = $state({});

  function duration(run: AgentRunOut): string {
    const start = parseDate(run.started_at);
    const end = parseDate(run.finished_at);
    if (!start || !end) return run.finished_at ? '—' : '実行中';
    const sec = Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000));
    return sec < 60 ? `${sec}秒` : `${Math.floor(sec / 60)}分${sec % 60}秒`;
  }
</script>

{#if runs.length === 0}
  <div class="empty">Agent Run はまだありません</div>
{:else}
  <div class="table-wrap">
    <table class="table">
      <thead>
        <tr>
          <th>開始</th>
          <th>種別</th>
          <th>状態</th>
          {#if !compact}<th>モデル</th><th>トリガー</th>{/if}
          <th>所要</th>
          <th>概要</th>
        </tr>
      </thead>
      <tbody>
        {#each runs as run (run.id)}
          <tr>
            <td class="nowrap small">{formatDateTime(run.started_at)}</td>
            <td>{label(AGENT_TYPE_LABELS, run.agent_type)}</td>
            <td><StatusBadge status={run.status} kind="run" /></td>
            {#if !compact}<td class="small mono">{run.model ?? '—'}</td><td class="small">{run.trigger ?? '—'}</td>{/if}
            <td class="small nowrap">{duration(run)}</td>
            <td>
              <div class="small">{run.result_summary ?? run.input_summary ?? '—'}</div>
              {#if run.error_message}<div class="small text-danger prewrap">{run.error_message}</div>{/if}
              {#if run.input_summary && run.result_summary}
                <button type="button" class="btn btn-ghost btn-sm" onclick={() => (open[run.id] = !open[run.id])} aria-expanded={!!open[run.id]}>
                  {open[run.id] ? '入力を隠す' : '入力を表示'}
                </button>
                {#if open[run.id]}<div class="small muted prewrap">{run.input_summary}</div>{/if}
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}
