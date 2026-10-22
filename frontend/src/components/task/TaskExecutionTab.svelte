<script lang="ts">
  // 実行履歴: execution plans (expandable to work items / reviews) and agent runs for one task.
  import { onMount } from 'svelte';
  import { api } from '../../api/client';
  import type { AgentRunOut, ExecutionPlanOut } from '../../api/types';
  import { debounced, onEvent } from '../../stores/events.svelte';
  import StatusBadge from '../StatusBadge.svelte';
  import PlanDetail from '../PlanDetail.svelte';
  import AgentRunList from '../AgentRunList.svelte';
  import Loading from '../Loading.svelte';
  import { formatDateTime } from '../../lib/format';

  let { taskId }: { taskId: string } = $props();

  let plans: ExecutionPlanOut[] = $state([]);
  let runs: AgentRunOut[] = $state([]);
  let loading = $state(true);
  let open: Record<string, boolean> = $state({});

  async function load() {
    try {
      [plans, runs] = await Promise.all([api.tasks.plans(taskId), api.tasks.runs(taskId, 50)]);
    } catch {
      // banner
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void load();
    return onEvent(['plan.created', 'plan.updated', 'agent_run.started', 'agent_run.finished', 'review.recorded'], debounced(() => void load(), 500));
  });
</script>

<div class="stack">
  <section class="card" aria-labelledby="plans-title">
    <div class="card-title"><h3 id="plans-title">実行計画 <span class="muted small">({plans.length})</span></h3></div>
    {#if loading}
      <Loading />
    {:else if plans.length === 0}
      <div class="empty">実行計画はまだありません。Manager AI がタスクを評価すると作成されます。</div>
    {:else}
      <ul class="list-plain">
        {#each plans as plan (plan.id)}
          <li>
            <div class="row">
              <StatusBadge status={plan.status} kind="plan" />
              <span style="flex:1;min-width:200px">{plan.objective}</span>
              <span class="small muted nowrap">Work Item {plan.work_item_count ?? 0} 件 · {formatDateTime(plan.updated_at)}</span>
              <button type="button" class="btn btn-ghost btn-sm" aria-expanded={!!open[plan.id]} onclick={() => (open[plan.id] = !open[plan.id])}>
                {open[plan.id] ? '閉じる' : '詳細'}
              </button>
            </div>
            {#if open[plan.id]}<PlanDetail {plan} />{/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="card" aria-labelledby="runs-title">
    <div class="card-title"><h3 id="runs-title">Agent Run <span class="muted small">({runs.length})</span></h3></div>
    {#if loading}
      <Loading />
    {:else}
      <AgentRunList {runs} compact />
    {/if}
  </section>
</div>
