<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../api/client';
  import type { Assignee, InstructionOut } from '../api/types';
  import { PAGE_SIZE, categories, loadCategories, loadTasks, tasks, upsertTask } from '../stores/tasks.svelte';
  import { isPaused, manager, pauseManager, resumeManager, runManagerNow } from '../stores/manager.svelte';
  import { toast } from '../stores/toasts.svelte';
  import StatusBadge from '../components/StatusBadge.svelte';
  import Loading from '../components/Loading.svelte';
  import Pager from '../components/Pager.svelte';
  import ApprovalList from '../components/ApprovalList.svelte';
  import CategoryManager from '../components/CategoryManager.svelte';
  import { ASSIGNEE_LABELS, TASK_STATUS_LABELS, TASK_STATUS_ORDER, formatDateTime, formatRelative, fromDateTimeLocal, isOverdue, label } from '../lib/format';
  import { links } from '../lib/router.svelte';

  // ---- Manager instruction -------------------------------------------------
  let instruction = $state('');
  let instructing = $state(false);
  let instructionResult: InstructionOut | null = $state(null);
  let selected: Record<string, boolean> = $state({});
  const selectedIds = $derived(Object.keys(selected).filter((id) => selected[id]));

  async function sendInstruction() {
    const text = instruction.trim();
    if (!text || instructing) return;
    instructing = true;
    instructionResult = null;
    try {
      instructionResult = await api.manager.instruct(text, selectedIds);
      instruction = '';
      selected = {};
      toast.success('Manager AI が指示を処理しました');
      void loadTasks();
    } catch {
      // banner
    } finally {
      instructing = false;
    }
  }

  function onInstructionKey(event: KeyboardEvent) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      void sendInstruction();
    }
  }

  // ---- Quick create ----------------------------------------------------------
  let newTitle = $state('');
  let newDue = $state('');
  let newCategory = $state('');
  let newAssignee: Assignee = $state('shared');
  let creating = $state(false);

  async function createTask() {
    const title = newTitle.trim();
    if (!title || creating) return;
    creating = true;
    try {
      const task = await api.tasks.create({
        title,
        due_at: fromDateTimeLocal(newDue),
        category_id: newCategory || null,
        assignee: newAssignee
      });
      upsertTask(task);
      newTitle = '';
      newDue = '';
      toast.success('タスクを作成しました', task.title);
      void loadTasks();
      void loadCategories();
    } catch {
      // banner
    } finally {
      creating = false;
    }
  }

  // ---- Filters ---------------------------------------------------------------
  let searchTimer: ReturnType<typeof setTimeout> | null = null;
  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void loadTasks(0), 300);
  }
  function applyFilters() {
    void loadTasks(0);
  }
  function resetFilters() {
    tasks.filters.status = '';
    tasks.filters.category_id = '';
    tasks.filters.assignee = '';
    tasks.filters.search = '';
    tasks.filters.include_completed = false;
    void loadTasks(0);
  }

  const hasFilters = $derived(!!(tasks.filters.status || tasks.filters.category_id || tasks.filters.assignee || tasks.filters.search || tasks.filters.include_completed));

  onMount(() => {
    void loadTasks(0);
    if (!categories.loaded) void loadCategories();
  });

  const changeSummary = (change: Record<string, unknown>) => {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(change)) parts.push(`${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`);
    return parts.join(' / ');
  };
</script>

<div class="page page-wide">
  <section class="card instruct" aria-labelledby="instruct-title">
    <div class="card-title">
      <h2 id="instruct-title">Manager AI への指示</h2>
      <div class="row">
        <button type="button" class="btn btn-sm" disabled={manager.busy} onclick={() => void runManagerNow()}>今すぐ実行</button>
        {#if isPaused()}
          <button type="button" class="btn btn-sm btn-success" disabled={manager.busy} onclick={() => void resumeManager()}>再開</button>
        {:else}
          <button type="button" class="btn btn-sm" disabled={manager.busy} onclick={() => void pauseManager()}>一時停止</button>
        {/if}
      </div>
    </div>
    {#if manager.status?.llm_ready === false}
      <div class="alert alert-warning" style="margin-bottom:0.5rem">
        LLM が利用できません: {manager.status.llm_issue ?? 'API キーまたはモデル設定を確認してください'} — <a href={links.settings()}>設定を開く</a>
      </div>
    {/if}
    <label class="field">
      <span class="sr-only">指示内容</span>
      <textarea
        rows="3"
        placeholder="例: 来週の報告会に向けて、調査タスクの優先順位を見直して資料のたたき台を作って (Ctrl+Enter で送信)"
        bind:value={instruction}
        onkeydown={onInstructionKey}
        disabled={instructing}
      ></textarea>
    </label>
    <div class="form-actions">
      <button type="button" class="btn btn-primary" disabled={instructing || !instruction.trim()} onclick={() => void sendInstruction()}>
        {#if instructing}<span class="spinner"></span> 処理中…{:else}指示を送る{/if}
      </button>
      {#if selectedIds.length > 0}
        <span class="small muted">対象タスク: {selectedIds.length} 件 <button type="button" class="btn btn-ghost btn-sm" onclick={() => (selected = {})}>解除</button></span>
      {:else}
        <span class="small faint">一覧でタスクにチェックを入れると、そのタスクを対象にした指示になります</span>
      {/if}
    </div>
    {#if instructionResult}
      <div class="alert alert-info" style="margin-top:0.75rem">
        <div class="row row-between">
          <strong>Manager AI の応答</strong>
          <button type="button" class="btn btn-ghost btn-sm" onclick={() => (instructionResult = null)} aria-label="応答を閉じる">×</button>
        </div>
        <div class="prewrap">{instructionResult.response}</div>
        {#if instructionResult.changes && instructionResult.changes.length > 0}
          <ul class="small" style="margin:0.5rem 0 0;padding-left:1.1rem">
            {#each instructionResult.changes as change, i (i)}
              <li>{changeSummary(change)}</li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  </section>

  <ApprovalList />

  <section class="card" aria-labelledby="create-title">
    <h2 id="create-title" class="sr-only">タスクを追加</h2>
    <form class="row create" onsubmit={(e) => { e.preventDefault(); void createTask(); }}>
      <input type="text" placeholder="新しいタスクのタイトル" aria-label="タスクのタイトル" bind:value={newTitle} maxlength="500" required style="flex:2;min-width:200px" />
      <input type="datetime-local" aria-label="期限" bind:value={newDue} style="flex:1;min-width:170px" />
      <select aria-label="カテゴリー" bind:value={newCategory} style="flex:1;min-width:130px">
        <option value="">カテゴリーなし</option>
        {#each categories.items as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
      </select>
      <select aria-label="担当" bind:value={newAssignee} style="min-width:110px">
        {#each Object.entries(ASSIGNEE_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
      </select>
      <button type="submit" class="btn btn-primary" disabled={creating || !newTitle.trim()}>追加</button>
    </form>
  </section>

  <section class="card" aria-labelledby="list-title">
    <div class="card-title">
      <h2 id="list-title">タスク一覧 <span class="muted small">({tasks.total} 件)</span></h2>
      <details class="catmgr">
        <summary class="btn btn-sm">カテゴリー管理</summary>
        <div class="catmgr-body card"><CategoryManager /></div>
      </details>
    </div>

    <div class="filters row" role="search">
      <input type="search" placeholder="検索 (タイトル・説明)" aria-label="検索" bind:value={tasks.filters.search} oninput={onSearchInput} style="flex:2;min-width:180px" />
      <select aria-label="ステータスで絞り込み" bind:value={tasks.filters.status} onchange={applyFilters}>
        <option value="">すべてのステータス</option>
        {#each TASK_STATUS_ORDER as s (s)}<option value={s}>{TASK_STATUS_LABELS[s]}</option>{/each}
      </select>
      <select aria-label="カテゴリーで絞り込み" bind:value={tasks.filters.category_id} onchange={applyFilters}>
        <option value="">すべてのカテゴリー</option>
        {#each categories.items as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
      </select>
      <select aria-label="担当で絞り込み" bind:value={tasks.filters.assignee} onchange={applyFilters}>
        <option value="">すべての担当</option>
        {#each Object.entries(ASSIGNEE_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
      </select>
      <select aria-label="並び順" bind:value={tasks.filters.order} onchange={applyFilters}>
        <option value="due">期限順</option>
        <option value="updated">更新順</option>
        <option value="created">作成順</option>
      </select>
      <label class="field field-inline">
        <input type="checkbox" bind:checked={tasks.filters.include_completed} onchange={applyFilters} />
        <span>完了を含む</span>
      </label>
      {#if hasFilters}<button type="button" class="btn btn-ghost btn-sm" onclick={resetFilters}>条件をクリア</button>{/if}
      {#if tasks.loading}<Loading inline text="" />{/if}
    </div>

    {#if tasks.error && tasks.items.length === 0}
      <div class="alert alert-danger">タスクを読み込めませんでした: {tasks.error}</div>
    {:else if tasks.loaded && tasks.items.length === 0}
      <div class="empty">
        {#if hasFilters}条件に一致するタスクはありません{:else}タスクはまだありません。上のフォームから追加するか、Manager AI に指示してください。{/if}
      </div>
    {:else if !tasks.loaded}
      <Loading />
    {:else}
      <div class="table-wrap">
        <table class="table tasks">
          <thead>
            <tr>
              <th class="chk"><span class="sr-only">選択</span></th>
              <th>タイトル</th>
              <th>期限</th>
              <th>ステータス</th>
              <th>カテゴリー</th>
              <th>担当</th>
              <th>AI作業状況</th>
              <th class="num">確認待ち</th>
            </tr>
          </thead>
          <tbody>
            {#each tasks.items as t (t.id)}
              <tr class:done={t.status === 'completed'}>
                <td class="chk"><input type="checkbox" bind:checked={selected[t.id]} aria-label="「{t.title}」を指示対象にする" /></td>
                <td>
                  <a class="title" href={links.task(t.id)}>{t.title}</a>
                  {#if t.open_chats}<span class="small faint" title="チャット数"> 💬{t.open_chats}</span>{/if}
                </td>
                <td class="nowrap small" class:overdue={isOverdue(t.due_at, t.status)} title={formatDateTime(t.due_at, '')}>
                  {#if t.due_at}{formatDateTime(t.due_at)}<span class="faint"> ({formatRelative(t.due_at)})</span>{:else}—{/if}
                </td>
                <td><StatusBadge status={t.status} kind="task" /></td>
                <td class="small">{t.category_name ?? '—'}</td>
                <td class="small">{label(ASSIGNEE_LABELS, t.assignee)}</td>
                <td class="small">{#if t.ai_activity}<span class="badge badge-info">{t.ai_activity}</span>{:else}<span class="faint">—</span>{/if}</td>
                <td class="num">{#if t.pending_artifacts}<span class="badge badge-warning">{t.pending_artifacts}</span>{:else}<span class="faint">0</span>{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <Pager offset={tasks.offset} limit={PAGE_SIZE} total={tasks.total} onchange={(o) => void loadTasks(o)} />
    {/if}
  </section>
</div>

<style>
  .instruct {
    border-color: var(--accent);
  }
  .create {
    align-items: stretch;
  }
  .filters {
    margin-bottom: 0.75rem;
  }
  .filters select {
    width: auto;
  }
  .tasks .chk {
    width: 2rem;
    text-align: center;
  }
  .tasks tr.done .title {
    color: var(--text-muted);
    text-decoration: line-through;
  }
  .catmgr {
    position: relative;
  }
  .catmgr summary {
    list-style: none;
  }
  .catmgr summary::-webkit-details-marker {
    display: none;
  }
  .catmgr-body {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    width: min(92vw, 420px);
    z-index: 30;
    box-shadow: var(--shadow-lg);
  }
</style>
