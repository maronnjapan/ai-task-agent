<script lang="ts">
  // 基本情報: edit fields, approve/reopen, revision requests, delete, open contexts.
  import { onMount } from 'svelte';
  import { api } from '../../api/client';
  import type { Assignee, TaskContextOut, TaskOut, TaskStatus, TaskUpdate } from '../../api/types';
  import { categories, loadCategories, removeTask, upsertTask } from '../../stores/tasks.svelte';
  import { toast } from '../../stores/toasts.svelte';
  import ConfirmDialog from '../ConfirmDialog.svelte';
  import { ASSIGNEE_LABELS, TASK_STATUS_LABELS, TASK_STATUS_ORDER, formatDateTime, fromDateTimeLocal, toDateTimeLocal } from '../../lib/format';
  import { navigate } from '../../lib/router.svelte';

  let { task, onchange }: { task: TaskOut; onchange: (task: TaskOut) => void } = $props();

  let dialog: ConfirmDialog | undefined = $state();

  // Editable copy of the task fields.
  let form = $state({ title: '', description: '', due: '', category_id: '', status: 'todo' as TaskStatus, assignee: 'shared' as Assignee, change_summary: '' });
  let saving = $state(false);
  let busy = $state(false);

  function resetForm(t: TaskOut) {
    form = {
      title: t.title,
      description: t.description ?? '',
      due: toDateTimeLocal(t.due_at),
      category_id: t.category_id ?? '',
      status: t.status as TaskStatus,
      assignee: t.assignee as Assignee,
      change_summary: ''
    };
  }

  // Reload the form when the task changes, unless the user has unsaved edits (SSE reloads must not
  // discard them). A different task id always resets.
  let formTaskId = $state('');
  $effect(() => {
    const incoming = task;
    if (incoming.id !== formTaskId) {
      formTaskId = incoming.id;
      resetForm(incoming);
      return;
    }
    if (!dirty) resetForm(incoming);
  });

  // Compare the due date at minute precision: that is all <input type="datetime-local"> can express.
  const dueChanged = $derived(form.due !== toDateTimeLocal(task.due_at));
  const dirty = $derived(
    form.title !== task.title ||
      form.description !== (task.description ?? '') ||
      dueChanged ||
      form.category_id !== (task.category_id ?? '') ||
      form.status !== task.status ||
      form.assignee !== task.assignee
  );

  async function save() {
    if (!dirty || saving) return;
    const body: TaskUpdate = {};
    const clear: string[] = [];
    if (form.title.trim() && form.title !== task.title) body.title = form.title.trim();
    if (form.description !== (task.description ?? '')) {
      if (form.description.trim() === '') clear.push('description');
      else body.description = form.description;
    }
    if (dueChanged) {
      const due = fromDateTimeLocal(form.due);
      if (due === null) clear.push('due_at');
      else body.due_at = due;
    }
    if (form.category_id !== (task.category_id ?? '')) {
      if (form.category_id === '') clear.push('category_id');
      else body.category_id = form.category_id;
    }
    if (form.status !== task.status) body.status = form.status;
    if (form.assignee !== task.assignee) body.assignee = form.assignee;
    if (form.change_summary.trim()) body.change_summary = form.change_summary.trim();
    if (clear.length) body.clear = clear;
    saving = true;
    try {
      const updated = await api.tasks.update(task.id, body);
      upsertTask(updated);
      onchange(updated);
      toast.success('タスクを更新しました');
    } catch {
      // banner
    } finally {
      saving = false;
    }
  }

  async function approve() {
    const ok = await dialog?.confirm({ title: 'このタスクを承認して完了にしますか？', message: '確認待ちの成果物も承認済みになります。', confirmLabel: '承認' });
    if (!ok) return;
    busy = true;
    try {
      const updated = await api.tasks.approve(task.id, {});
      upsertTask(updated);
      onchange(updated);
      toast.success('タスクを承認しました');
    } catch {
      // banner
    } finally {
      busy = false;
    }
  }

  async function reopen() {
    busy = true;
    try {
      const updated = await api.tasks.reopen(task.id, {});
      upsertTask(updated);
      onchange(updated);
      toast.success('タスクを再開しました');
    } catch {
      // banner
    } finally {
      busy = false;
    }
  }

  async function remove() {
    const ok = await dialog?.confirm({ title: `タスク「${task.title}」を削除しますか？`, message: '削除したタスクは一覧に表示されなくなります。', confirmLabel: '削除', danger: true });
    if (!ok) return;
    busy = true;
    try {
      await api.tasks.remove(task.id);
      removeTask(task.id);
      toast.success('タスクを削除しました');
      navigate('/');
    } catch {
      busy = false;
    }
  }

  // ---- Revision request ------------------------------------------------------
  let revisionKind = $state<'revision' | 'additional_research' | 'hold'>('revision');
  let revisionText = $state('');
  let requesting = $state(false);
  const revisionKinds: { value: 'revision' | 'additional_research' | 'hold'; label: string; hint: string }[] = [
    { value: 'revision', label: '修正依頼', hint: '成果物や進め方の修正を AI に依頼します' },
    { value: 'additional_research', label: '追加調査依頼', hint: '不足している情報の追加調査を依頼します' },
    { value: 'hold', label: '保留', hint: 'AI の作業を一旦止めて保留にします' }
  ];

  async function requestRevision() {
    const instructions = revisionText.trim();
    if (!instructions || requesting) return;
    requesting = true;
    try {
      const updated = await api.tasks.revision(task.id, { instructions, kind: revisionKind });
      upsertTask(updated);
      onchange(updated);
      revisionText = '';
      toast.success(`${revisionKinds.find((k) => k.value === revisionKind)?.label}を記録しました`);
      void loadContexts();
    } catch {
      // banner
    } finally {
      requesting = false;
    }
  }

  // ---- Contexts ----------------------------------------------------------------
  let contexts: TaskContextOut[] = $state([]);
  let contextText = $state('');
  let contextSource = $state('');
  let addingContext = $state(false);
  let showAllContexts = $state(false);

  async function loadContexts() {
    try {
      contexts = await api.tasks.contexts(task.id);
    } catch {
      // banner
    }
  }

  async function addContext() {
    const text = contextText.trim();
    if (!text || addingContext) return;
    addingContext = true;
    try {
      await api.tasks.addContext(task.id, { context: text, source: contextSource.trim() || null });
      contextText = '';
      contextSource = '';
      await loadContexts();
      toast.success('補足情報を追加しました');
    } catch {
      // banner
    } finally {
      addingContext = false;
    }
  }

  const visibleContexts = $derived(showAllContexts ? contexts : contexts.filter((c) => c.status === 'open'));

  onMount(() => {
    void loadContexts();
    if (!categories.loaded) void loadCategories();
  });
</script>

<ConfirmDialog bind:this={dialog} />

<div class="grid-2">
  <section class="card" aria-labelledby="info-title">
    <div class="card-title"><h3 id="info-title">タスク情報</h3></div>
    <form class="stack" onsubmit={(e) => { e.preventDefault(); void save(); }}>
      <label class="field">
        <span>タイトル</span>
        <input type="text" bind:value={form.title} maxlength="500" required />
      </label>
      <label class="field">
        <span>説明</span>
        <textarea rows="6" bind:value={form.description} placeholder="背景、ゴール、制約など"></textarea>
      </label>
      <div class="form-grid">
        <label class="field">
          <span>期限</span>
          <input type="datetime-local" bind:value={form.due} />
        </label>
        <label class="field">
          <span>カテゴリー</span>
          <select bind:value={form.category_id}>
            <option value="">なし</option>
            {#each categories.items as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
          </select>
        </label>
        <label class="field">
          <span>ステータス</span>
          <select bind:value={form.status}>
            {#each TASK_STATUS_ORDER as s (s)}<option value={s}>{TASK_STATUS_LABELS[s]}</option>{/each}
          </select>
        </label>
        <label class="field">
          <span>担当</span>
          <select bind:value={form.assignee}>
            {#each Object.entries(ASSIGNEE_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
          </select>
        </label>
      </div>
      {#if dirty}
        <label class="field">
          <span>変更メモ (任意・変更履歴に残ります)</span>
          <input type="text" bind:value={form.change_summary} placeholder="例: 期限を1週間延ばした" />
        </label>
      {/if}
      <div class="form-actions">
        <button type="submit" class="btn btn-primary" disabled={!dirty || saving || !form.title.trim()}>{saving ? '保存中…' : '保存'}</button>
        <button type="button" class="btn" disabled={!dirty || saving} onclick={() => resetForm(task)}>元に戻す</button>
        <span class="spacer"></span>
        <span class="small faint">作成 {formatDateTime(task.created_at)} / 更新 {formatDateTime(task.updated_at)}</span>
      </div>
    </form>
  </section>

  <div class="stack">
    <section class="card" aria-labelledby="actions-title">
      <div class="card-title"><h3 id="actions-title">操作</h3></div>
      <div class="row">
        {#if task.status === 'review_pending'}
          <button type="button" class="btn btn-success" disabled={busy} onclick={() => void approve()}>承認して完了にする</button>
        {/if}
        {#if task.status === 'completed'}
          <button type="button" class="btn" disabled={busy} onclick={() => void reopen()}>タスクを再開する</button>
        {/if}
        <span class="spacer"></span>
        <button type="button" class="btn btn-danger" disabled={busy} onclick={() => void remove()}>削除</button>
      </div>
      {#if task.ai_activity}
        <p class="small muted" style="margin:0.5rem 0 0">AI作業状況: <span class="badge badge-info">{task.ai_activity}</span></p>
      {/if}
    </section>

    <section class="card" aria-labelledby="revision-title">
      <div class="card-title"><h3 id="revision-title">AI への依頼</h3></div>
      <form class="stack" onsubmit={(e) => { e.preventDefault(); void requestRevision(); }}>
        <div class="row" role="radiogroup" aria-label="依頼の種類">
          {#each revisionKinds as k (k.value)}
            <label class="field field-inline" title={k.hint}>
              <input type="radio" name="revision-kind" value={k.value} bind:group={revisionKind} />
              <span>{k.label}</span>
            </label>
          {/each}
        </div>
        <p class="help">{revisionKinds.find((k) => k.value === revisionKind)?.hint}</p>
        <label class="field">
          <span class="sr-only">依頼内容</span>
          <textarea rows="3" bind:value={revisionText} placeholder="依頼内容を具体的に書いてください" disabled={requesting}></textarea>
        </label>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary" disabled={requesting || !revisionText.trim()}>{requesting ? '送信中…' : '送信'}</button>
        </div>
      </form>
    </section>

    <section class="card" aria-labelledby="ctx-title">
      <div class="card-title">
        <h3 id="ctx-title">補足情報 <span class="muted small">({contexts.filter((c) => c.status === 'open').length} 件が有効)</span></h3>
        {#if contexts.some((c) => c.status !== 'open')}
          <label class="field field-inline small"><input type="checkbox" bind:checked={showAllContexts} /><span>処理済みも表示</span></label>
        {/if}
      </div>
      {#if visibleContexts.length === 0}
        <div class="empty">補足情報はありません</div>
      {:else}
        <ul class="list-plain">
          {#each visibleContexts as c (c.id)}
            <li>
              <div class="prewrap small">{c.context}</div>
              <div class="small faint">{c.source ?? ''} · {formatDateTime(c.created_at)} {#if c.status !== 'open'}· <span class="badge">{c.status}</span>{/if}</div>
            </li>
          {/each}
        </ul>
      {/if}
      <form class="stack" style="margin-top:0.5rem" onsubmit={(e) => { e.preventDefault(); void addContext(); }}>
        <label class="field">
          <span>AI に伝えたい追加情報</span>
          <textarea rows="2" bind:value={contextText} placeholder="例: 顧客から仕様変更の連絡があった…" disabled={addingContext}></textarea>
        </label>
        <div class="row">
          <input type="text" bind:value={contextSource} placeholder="情報源 (任意)" aria-label="情報源" style="flex:1;min-width:140px" />
          <button type="submit" class="btn btn-sm" disabled={addingContext || !contextText.trim()}>追加</button>
        </div>
      </form>
    </section>
  </div>
</div>
