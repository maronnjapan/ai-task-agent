<script lang="ts">
  // 長期記憶の管理 (SPEC 14 / 33): global・category・task memories with search, confirmation and deletion.
  import { onMount } from 'svelte';
  import { api } from '../api/client';
  import type { CategoryOut, MemoryKind, MemoryOut, MemoryScope } from '../api/types';
  import { toast } from '../stores/toasts.svelte';
  import ConfirmDialog from './ConfirmDialog.svelte';
  import Loading from './Loading.svelte';
  import { MEMORY_KIND_LABELS, MEMORY_SCOPE_LABELS, formatDateTime, label } from '../lib/format';
  import { links } from '../lib/router.svelte';

  let items: MemoryOut[] = $state([]);
  let categories: CategoryOut[] = $state([]);
  let loading = $state(true);
  let scope = $state('');
  let kind = $state('');
  let query = $state('');
  let dialog: ConfirmDialog | undefined = $state();

  let newScope: MemoryScope = $state('global');
  let newCategory = $state('');
  let newKind: MemoryKind = $state('research');
  let content = $state('');
  let adding = $state(false);

  const categoryName = $derived((id: string | null) => categories.find((c) => c.id === id)?.name ?? '');

  async function load() {
    loading = true;
    try {
      items = await api.memories.list({ scope: scope || undefined, kind: kind || undefined, q: query.trim() || undefined, limit: 200 });
    } catch {
      // banner
    } finally {
      loading = false;
    }
  }

  async function loadCategories() {
    try {
      categories = await api.categories.list();
    } catch {
      // banner
    }
  }

  async function add() {
    const text = content.trim();
    if (!text || adding) return;
    if (newScope === 'category' && !newCategory) {
      toast.error('カテゴリーを選択してください');
      return;
    }
    adding = true;
    try {
      await api.memories.create({ scope: newScope, category_id: newScope === 'category' ? newCategory : null, content: text, kind: newKind, confirmed: true, source: 'user' });
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

  onMount(() => {
    void load();
    void loadCategories();
  });
</script>

<ConfirmDialog bind:this={dialog} />

<section class="card" aria-labelledby="memory-title">
  <div class="card-title">
    <h2 id="memory-title">長期記憶 <span class="muted small">({items.length})</span></h2>
  </div>
  <form class="row" onsubmit={(e) => { e.preventDefault(); void load(); }}>
    <input type="search" placeholder="記憶を検索" bind:value={query} aria-label="記憶を検索" />
    <select bind:value={scope} aria-label="スコープ" onchange={() => void load()}>
      <option value="">すべてのスコープ</option>
      {#each Object.entries(MEMORY_SCOPE_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
    </select>
    <select bind:value={kind} aria-label="種類" onchange={() => void load()}>
      <option value="">すべての種類</option>
      {#each Object.entries(MEMORY_KIND_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
    </select>
    <button type="submit" class="btn btn-sm">検索</button>
  </form>

  {#if loading}
    <Loading />
  {:else if items.length === 0}
    <div class="empty">記憶はまだありません</div>
  {:else}
    <ul class="list-plain" style="margin-top:0.5rem">
      {#each items as m (m.id)}
        <li>
          <div class="row small">
            <span class="badge badge-outline">{label(MEMORY_SCOPE_LABELS, m.scope)}{#if m.scope === 'category' && categoryName(m.category_id)}: {categoryName(m.category_id)}{/if}</span>
            <span class="badge {m.kind === 'decision' ? 'badge-success' : m.kind === 'hypothesis' ? 'badge-warning' : m.kind === 'ai_inference' ? 'badge-info' : 'badge-outline'}">{label(MEMORY_KIND_LABELS, m.kind)}</span>
            {#if m.confirmed}<span class="badge badge-success">確認済み</span>{:else}<span class="badge">未確認</span>{/if}
            <span class="faint">{m.source ?? ''} · {formatDateTime(m.updated_at)}</span>
            {#if m.task_id}<a href={links.task(m.task_id)}>タスク</a>{/if}
            <span class="spacer"></span>
            <button type="button" class="btn btn-ghost btn-sm" onclick={() => void toggleConfirmed(m)}>{m.confirmed ? '未確認にする' : '確認済みにする'}</button>
            <button type="button" class="btn btn-ghost btn-sm text-danger" onclick={() => void remove(m)}>削除</button>
          </div>
          <div class="prewrap" style="margin-top:0.2rem">{m.content}</div>
        </li>
      {/each}
    </ul>
  {/if}

  <details class="collapse" style="margin-top:0.75rem">
    <summary>記憶を追加 (全体 / カテゴリー)</summary>
    <form class="stack collapse-body" onsubmit={(e) => { e.preventDefault(); void add(); }}>
      <div class="row">
        <label class="field">
          <span>スコープ</span>
          <select bind:value={newScope}>
            <option value="global">全体 (すべてのタスクで共有)</option>
            <option value="category">カテゴリー</option>
          </select>
        </label>
        {#if newScope === 'category'}
          <label class="field">
            <span>カテゴリー</span>
            <select bind:value={newCategory}>
              <option value="">選択してください</option>
              {#each categories as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
            </select>
          </label>
        {/if}
        <label class="field">
          <span>種類</span>
          <select bind:value={newKind}>
            {#each Object.entries(MEMORY_KIND_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
          </select>
        </label>
      </div>
      <label class="field">
        <span>内容</span>
        <textarea rows="3" bind:value={content} placeholder="例: 技術調査では公式ドキュメントを優先する" disabled={adding}></textarea>
      </label>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary" disabled={adding || !content.trim()}>追加</button>
      </div>
    </form>
  </details>
</section>
