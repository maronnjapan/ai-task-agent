<script lang="ts">
  // Expanded view of one execution plan: work items + reviews (SPEC 10-12). Loaded lazily on mount.
  import { onMount } from 'svelte';
  import { api } from '../api/client';
  import type { ExecutionPlanOut, ReviewOut, WorkItemOut } from '../api/types';
  import { debounced, onEvent } from '../stores/events.svelte';
  import StatusBadge from './StatusBadge.svelte';
  import Loading from './Loading.svelte';
  import { formatDateTime } from '../lib/format';
  import { links } from '../lib/router.svelte';

  let { plan }: { plan: ExecutionPlanOut } = $props();

  let workItems: WorkItemOut[] = $state([]);
  let reviews: ReviewOut[] = $state([]);
  let loading = $state(true);
  let showResult: Record<string, boolean> = $state({});

  async function load() {
    try {
      [workItems, reviews] = await Promise.all([api.plans.workItems(plan.id), api.plans.reviews(plan.id)]);
    } catch {
      // banner
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void load();
    const refresh = debounced(() => void load(), 400);
    return onEvent(['work_items.created', 'work_item.updated', 'review.recorded', 'agent_run.finished'], (event) => {
      const data = event.data as { plan_id?: string };
      if (!data.plan_id || data.plan_id === plan.id) refresh();
    });
  });

  const resultText = (result: Record<string, unknown> | null) => {
    if (!result) return '';
    if (typeof result.summary === 'string') return result.summary;
    return JSON.stringify(result, null, 2);
  };
</script>

<div class="plan-detail">
  <dl class="kv">
    <dt>目的</dt>
    <dd class="prewrap">{plan.objective}</dd>
    <dt>受け入れ基準</dt>
    <dd class="prewrap">{plan.acceptance_criteria || '—'}</dd>
    <dt>再計画回数</dt>
    <dd>{plan.replanning_attempt}</dd>
    {#if plan.parent_plan_id}
      <dt>親計画</dt>
      <dd class="mono">{plan.parent_plan_id}</dd>
    {/if}
    {#if plan.task_links && plan.task_links.length > 0}
      <dt>関連タスク</dt>
      <dd>
        {#each plan.task_links as link (link.task_id)}
          <a href={links.task(link.task_id)}>{link.task_title ?? link.task_id}</a>{' '}
        {/each}
      </dd>
    {/if}
  </dl>

  {#if loading}
    <Loading inline />
  {:else}
    <h4 style="margin-top:0.75rem">Work Item ({workItems.length})</h4>
    {#if workItems.length === 0}
      <div class="empty">Work Item はまだありません</div>
    {:else}
      <ol class="list-plain">
        {#each workItems as item (item.id)}
          <li>
            <div class="row row-between">
              <span><span class="muted small">#{item.order_index + 1}</span> <strong>{item.title}</strong></span>
              <span class="row">
                {#if item.retry_count > 0}<span class="badge badge-outline">再試行 {item.retry_count}</span>{/if}
                <StatusBadge status={item.status} kind="work_item" />
              </span>
            </div>
            {#if item.description}<div class="small muted prewrap" style="margin-top:0.2rem">{item.description}</div>{/if}
            {#if item.depends_on && item.depends_on.length > 0}
              <div class="small faint">依存: {item.depends_on.length} 件</div>
            {/if}
            {#if item.result}
              <button type="button" class="btn btn-ghost btn-sm" onclick={() => (showResult[item.id] = !showResult[item.id])} aria-expanded={!!showResult[item.id]}>
                {showResult[item.id] ? '結果を隠す' : '結果を表示'}
              </button>
              {#if showResult[item.id]}<pre class="small">{resultText(item.result)}</pre>{/if}
            {/if}
          </li>
        {/each}
      </ol>
    {/if}

    <h4 style="margin-top:0.75rem">レビュー ({reviews.length})</h4>
    {#if reviews.length === 0}
      <div class="empty">レビューはまだありません</div>
    {:else}
      <ul class="list-plain">
        {#each reviews as review (review.id)}
          <li>
            <div class="row">
              <StatusBadge status={review.status} kind="review" />
              <span class="small muted">{formatDateTime(review.created_at)}</span>
            </div>
            <div class="prewrap small" style="margin-top:0.25rem">{review.feedback}</div>
            {#if review.task_results && review.task_results.length > 0}
              <ul class="small" style="margin:0.25rem 0 0;padding-left:1.1rem">
                {#each review.task_results as tr (tr.task_id)}
                  <li><a href={links.task(tr.task_id)}>タスク</a> — <StatusBadge status={tr.status} kind="review" /> {tr.feedback ?? ''}</li>
                {/each}
              </ul>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>

<style>
  .plan-detail {
    padding: 0.5rem 0 0.25rem;
  }
</style>
