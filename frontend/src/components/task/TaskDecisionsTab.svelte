<script lang="ts">
  // 決定事項 (SPEC 15): active decisions, manual add, revoke, optional history.
  import { onMount } from 'svelte';
  import { api } from '../../api/client';
  import type { DecisionOut } from '../../api/types';
  import { debounced, onEvent } from '../../stores/events.svelte';
  import { toast } from '../../stores/toasts.svelte';
  import ConfirmDialog from '../ConfirmDialog.svelte';
  import StatusBadge from '../StatusBadge.svelte';
  import Loading from '../Loading.svelte';
  import { ACTOR_LABELS, formatDateTime, label } from '../../lib/format';

  let { taskId }: { taskId: string } = $props();

  let items: DecisionOut[] = $state([]);
  let loading = $state(true);
  let includeHistory = $state(false);
  let content = $state('');
  let adding = $state(false);
  let dialog: ConfirmDialog | undefined = $state();

  async function load() {
    try {
      items = await api.tasks.decisions(taskId, includeHistory);
    } catch {
      // banner
    } finally {
      loading = false;
    }
  }

  async function add() {
    const text = content.trim();
    if (!text || adding) return;
    adding = true;
    try {
      await api.tasks.addDecision(taskId, { content: text });
      content = '';
      toast.success('決定事項を記録しました');
      await load();
    } catch {
      // banner
    } finally {
      adding = false;
    }
  }

  async function revoke(d: DecisionOut) {
    const ok = await dialog?.confirm({ title: 'この決定事項を取り消しますか？', message: d.content.slice(0, 300), confirmLabel: '取り消す', danger: true });
    if (!ok) return;
    try {
      await api.decisions.revoke(d.id);
      toast.success('決定事項を取り消しました');
      await load();
    } catch {
      // banner
    }
  }

  let supersedes: DecisionOut | null = $state(null);

  async function supersede() {
    const text = content.trim();
    if (!text || adding || !supersedes) return;
    adding = true;
    try {
      await api.tasks.addDecision(taskId, { content: text, supersedes_id: supersedes.id });
      content = '';
      supersedes = null;
      toast.success('決定事項を置き換えました', '以前の決定は履歴として残ります');
      await load();
    } catch {
      // banner
    } finally {
      adding = false;
    }
  }

  onMount(() => {
    void load();
    const reload = debounced(() => void load(), 200);
    return onEvent('decision.recorded', (event) => {
      if ((event.data as { task_id?: string }).task_id === taskId) reload();
    });
  });
</script>

<ConfirmDialog bind:this={dialog} />

<div class="grid-2">
  <section class="card" aria-labelledby="dec-title">
    <div class="card-title">
      <h3 id="dec-title">決定事項</h3>
      <label class="field field-inline small"><input type="checkbox" bind:checked={includeHistory} onchange={() => queueMicrotask(() => void load())} /><span>履歴も表示</span></label>
    </div>
    {#if loading}
      <Loading />
    {:else if items.length === 0}
      <div class="empty">決定事項はまだありません。チャットのメッセージから「決定として記録」するか、右のフォームから追加できます。</div>
    {:else}
      <ol class="list-plain">
        {#each items as d (d.id)}
          <li class:inactive={d.status !== 'active'}>
            <div class="prewrap">{d.content}</div>
            <div class="row small faint" style="margin-top:0.25rem">
              <StatusBadge status={d.status} kind="decision" />
              <span>{label(ACTOR_LABELS, d.decided_by)} · {formatDateTime(d.decided_at)}</span>
              {#if d.source_message_id}<span title={d.source_message_id}>チャット由来</span>{/if}
              <span class="spacer"></span>
              {#if d.status === 'active'}
                <button type="button" class="btn btn-ghost btn-sm" onclick={() => { supersedes = d; content = d.content; }}>置き換える</button>
                <button type="button" class="btn btn-ghost btn-sm text-danger" onclick={() => void revoke(d)}>取り消す</button>
              {/if}
            </div>
          </li>
        {/each}
      </ol>
    {/if}
  </section>

  <section class="card" aria-labelledby="dec-add-title">
    <div class="card-title"><h3 id="dec-add-title">{supersedes ? '決定事項を置き換える' : '決定事項を追加'}</h3></div>
    {#if supersedes}
      <div class="alert alert-info small">「{supersedes.content.slice(0, 80)}」を新しい決定で置き換えます。以前の決定は「上書き済み」として履歴に残ります。</div>
    {:else}
      <p class="small muted">ここに記録した内容は正式な決定として扱われ、AI は以降の作業でこれに従います。</p>
    {/if}
    <form class="stack" onsubmit={(e) => { e.preventDefault(); void (supersedes ? supersede() : add()); }}>
      <label class="field">
        <span class="sr-only">決定内容</span>
        <textarea rows="4" bind:value={content} placeholder="例: 報告書の対象期間は 2026年Q3 とする" disabled={adding}></textarea>
      </label>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary" disabled={adding || !content.trim()}>{supersedes ? '置き換えて記録する' : '記録する'}</button>
        {#if supersedes}<button type="button" class="btn" disabled={adding} onclick={() => { supersedes = null; content = ''; }}>キャンセル</button>{/if}
      </div>
    </form>
  </section>
</div>

<style>
  li.inactive {
    opacity: 0.65;
  }
</style>
