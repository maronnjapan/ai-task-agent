<script lang="ts">
  import { onMount } from 'svelte';
  import { api, ApiError } from '../api/client';
  import type { TaskOut } from '../api/types';
  import { onEvent } from '../stores/events.svelte';
  import StatusBadge from '../components/StatusBadge.svelte';
  import Loading from '../components/Loading.svelte';
  import TaskInfoTab from '../components/task/TaskInfoTab.svelte';
  import ChatPanel from '../components/task/ChatPanel.svelte';
  import TaskArtifactsTab from '../components/task/TaskArtifactsTab.svelte';
  import TaskDecisionsTab from '../components/task/TaskDecisionsTab.svelte';
  import TaskHistoryTab from '../components/task/TaskHistoryTab.svelte';
  import TaskExecutionTab from '../components/task/TaskExecutionTab.svelte';
  import TaskMemoryTab from '../components/task/TaskMemoryTab.svelte';
  import { ASSIGNEE_LABELS, formatDateTime, formatRelative, isOverdue, label } from '../lib/format';
  import { links } from '../lib/router.svelte';

  let { id, query = {} }: { id: string; query?: Record<string, string> } = $props();

  type Tab = 'info' | 'chat' | 'artifacts' | 'decisions' | 'history' | 'execution' | 'memory';
  const tabs: { id: Tab; label: string }[] = [
    { id: 'info', label: '基本情報' },
    { id: 'chat', label: 'チャット' },
    { id: 'artifacts', label: '成果物' },
    { id: 'decisions', label: '決定事項' },
    { id: 'history', label: '変更履歴' },
    { id: 'execution', label: '実行履歴' },
    { id: 'memory', label: '記憶' }
  ];

  let task: TaskOut | null = $state(null);
  let notFound = $state(false);
  let tab: Tab = $state((tabs.some((t) => t.id === query.tab) ? (query.tab as Tab) : 'info'));

  async function load() {
    try {
      task = await api.tasks.get(id, { silent: true });
      notFound = false;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) notFound = true;
    }
  }

  function selectTab(next: Tab) {
    tab = next;
    try {
      const url = new URL(window.location.href);
      url.hash = `${links.task(id)}${next === 'info' ? '' : `?tab=${next}`}`;
      history.replaceState(null, '', url.toString());
    } catch {
      // ignore
    }
  }

  function onTabKey(event: KeyboardEvent) {
    const idx = tabs.findIndex((t) => t.id === tab);
    if (event.key === 'ArrowRight') selectTab(tabs[(idx + 1) % tabs.length].id);
    else if (event.key === 'ArrowLeft') selectTab(tabs[(idx - 1 + tabs.length) % tabs.length].id);
    else return;
    event.preventDefault();
    (document.getElementById(`tab-${tab}`) as HTMLElement | null)?.focus();
  }

  onMount(() => {
    void load();
    return onEvent(['task.updated', 'task.deleted', 'artifact.created', 'artifact.updated', 'plan.updated'], (event) => {
      if ((event.data as { task_id?: string }).task_id === id) void load();
    });
  });
</script>

<div class="page page-wide">
  <nav class="small muted" aria-label="パンくず" style="margin-bottom:0.5rem"><a href={links.tasks()}>タスク一覧</a> › タスク詳細</nav>

  {#if notFound}
    <div class="card"><div class="alert alert-warning">タスクが見つかりません。削除された可能性があります。</div></div>
  {:else if !task}
    <Loading />
  {:else}
    <header class="page-header">
      <div style="min-width:0">
        <h1 class="title">{task.title}</h1>
        <div class="row small muted">
          <StatusBadge status={task.status} kind="task" />
          {#if task.is_deleted}<span class="badge badge-danger">削除済み</span>{/if}
          <span>担当: {label(ASSIGNEE_LABELS, task.assignee)}</span>
          {#if task.category_name}<span>カテゴリー: {task.category_name}</span>{/if}
          <span class:overdue={isOverdue(task.due_at, task.status)}>期限: {task.due_at ? `${formatDateTime(task.due_at)} (${formatRelative(task.due_at)})` : 'なし'}</span>
          {#if task.ai_activity}<span class="badge badge-info">{task.ai_activity}</span>{/if}
          {#if task.pending_artifacts}<span class="badge badge-warning">確認待ち {task.pending_artifacts}</span>{/if}
        </div>
      </div>
    </header>

    <div class="tabs" role="tablist" aria-label="タスク詳細" onkeydown={onTabKey}>
      {#each tabs as t (t.id)}
        <button type="button" role="tab" id="tab-{t.id}" aria-selected={tab === t.id} aria-controls="panel-{t.id}" tabindex={tab === t.id ? 0 : -1} onclick={() => selectTab(t.id)}>
          {t.label}
          {#if t.id === 'artifacts' && task.pending_artifacts}<span class="count">{task.pending_artifacts}</span>{/if}
          {#if t.id === 'chat' && task.open_chats}<span class="count">{task.open_chats}</span>{/if}
        </button>
      {/each}
    </div>

    <div role="tabpanel" id="panel-{tab}" aria-labelledby="tab-{tab}">
      {#if tab === 'info'}
        <TaskInfoTab {task} onchange={(t) => (task = t)} />
      {:else if tab === 'chat'}
        <ChatPanel taskId={id} />
      {:else if tab === 'artifacts'}
        <TaskArtifactsTab taskId={id} />
      {:else if tab === 'decisions'}
        <TaskDecisionsTab taskId={id} />
      {:else if tab === 'history'}
        <TaskHistoryTab taskId={id} onreverted={(t) => (task = t)} />
      {:else if tab === 'execution'}
        <TaskExecutionTab taskId={id} />
      {:else if tab === 'memory'}
        <TaskMemoryTab taskId={id} />
      {/if}
    </div>
  {/if}
</div>

<style>
  .title {
    word-break: break-word;
    margin-bottom: 0.25rem;
  }
</style>
