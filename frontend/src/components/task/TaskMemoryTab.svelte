<script lang="ts">
  // 記憶 (SPEC 14): task-scoped long-term memories.
  import { onMount } from 'svelte';
  import { api } from '../../api/client';
  import type { MemoryKind, MemoryOut } from '../../api/types';
  import { toast } from '../../stores/toasts.svelte';
  import ConfirmDialog from '../ConfirmDialog.svelte';
  import Loading from '../Loading.svelte';
  import { MEMORY_KIND_LABELS, formatDateTime, label } from '../../lib/format';

  let { taskId }: { taskId: string } = $props();

  let items: MemoryOut[] = $state([]);
  let loading = $state(true);
  let content = $state('');
  let kind: MemoryKind = $state('research');
  let adding = $state(false);
  let dialog: ConfirmDialog | undefined = $state();

  async function load() {
    try {
      items = await api.memories.list({ task_id: taskId, limit: 200 });
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
      await api.memories.create({ scope: 'task', task_id: taskId, content: text, kind, confirmed: true, source: 'user' });
      content = '';
      toast.success('記憶を追加しました');
      await load();
    } catch {
      // banner
    } finally {
      adding = false;
    }
  }

  async function toggleConfirmed(m: MemoryOut) {
    try {
      const updated = await api.memories.update(m.id, { confirmed: !m.confirmed });
      items = items.map((x) => (x.id === m.id ? updated : x));
    } catch {
      // banner
    }
  }

  async function remove(m: MemoryOut) {
    const ok = await dialog?.confirm({ title: 'この記憶を削除しますか？', message: m.content.slice(0, 300), confirmLabel: '削除', danger: true });
    if (!ok) return;
    try {
      await api.memories.remove(m.id);
      items = items.filter((x) => x.id !== m.id);
    } catch {
      // banner
    }
  }

  onMount(() => void load());
</script>

<ConfirmDialog bind:this={dialog} />

<div class="grid-2">
  <section class="card" aria-labelledby="mem-title">
    <div class="card-title"><h3 id="mem-title">このタスクの記憶 <span class="muted small">({items.length})</span></h3></div>
    {#if loading}
      <Loading />
    {:else if items.length === 0}
      <div class="empty">記憶はまだありません</div>
    {:else}
      <ul class="list-plain">
        {#each items as m (m.id)}
          <li>
            <div class="row small">
              <span class="badge {m.kind === 'decision' ? 'badge-success' : m.kind === 'hypothesis' ? 'badge-warning' : m.kind === 'ai_inference' ? 'badge-info' : 'badge-outline'}">{label(MEMORY_KIND_LABELS, m.kind)}</span>
              {#if m.confirmed}<span class="badge badge-success">確認済み</span>{:else}<span class="badge">未確認</span>{/if}
              <span class="faint">{m.source ?? ''} · {formatDateTime(m.updated_at)}</span>
              <span class="spacer"></span>
              <button type="button" class="btn btn-ghost btn-sm" onclick={() => void toggleConfirmed(m)}>{m.confirmed ? '未確認にする' : '確認済みにする'}</button>
              <button type="button" class="btn btn-ghost btn-sm text-danger" onclick={() => void remove(m)}>削除</button>
            </div>
            <div class="prewrap" style="margin-top:0.2rem">{m.content}</div>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="card" aria-labelledby="mem-add-title">
    <div class="card-title"><h3 id="mem-add-title">記憶を追加</h3></div>
    <form class="stack" onsubmit={(e) => { e.preventDefault(); void add(); }}>
      <label class="field">
        <span>種類</span>
        <select bind:value={kind}>
          {#each Object.entries(MEMORY_KIND_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
        </select>
      </label>
      <label class="field">
        <span>内容</span>
        <textarea rows="4" bind:value={content} placeholder="AI に覚えておいてほしいこと" disabled={adding}></textarea>
      </label>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary" disabled={adding || !content.trim()}>追加</button>
      </div>
    </form>
  </section>
</div>
