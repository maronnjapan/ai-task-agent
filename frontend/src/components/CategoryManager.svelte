<script lang="ts">
  // Inline category CRUD (SPEC 9.4). Keeps the shared `categories` store in sync.
  import { api } from '../api/client';
  import { categories, loadCategories } from '../stores/tasks.svelte';
  import { toast } from '../stores/toasts.svelte';
  import ConfirmDialog from './ConfirmDialog.svelte';

  let newName = $state('');
  let editingId: string | null = $state(null);
  let editingName = $state('');
  let busy = $state(false);
  let dialog: ConfirmDialog | undefined = $state();

  async function create() {
    const name = newName.trim();
    if (!name) return;
    busy = true;
    try {
      await api.categories.create(name);
      newName = '';
      await loadCategories();
      toast.success('カテゴリーを追加しました');
    } catch {
      // banner
    } finally {
      busy = false;
    }
  }

  function startEdit(id: string, name: string) {
    editingId = id;
    editingName = name;
  }

  async function saveEdit() {
    if (!editingId) return;
    const name = editingName.trim();
    if (!name) return;
    busy = true;
    try {
      await api.categories.update(editingId, name);
      editingId = null;
      await loadCategories();
    } catch {
      // banner
    } finally {
      busy = false;
    }
  }

  async function remove(id: string, name: string, count: number) {
    const ok = await dialog?.confirm({
      title: `カテゴリー「${name}」を削除しますか？`,
      message: count > 0 ? `${count} 件のタスクに設定されています。削除するとタスクのカテゴリーは未設定になります。` : undefined,
      confirmLabel: '削除',
      danger: true
    });
    if (!ok) return;
    busy = true;
    try {
      await api.categories.remove(id);
      await loadCategories();
      toast.success('カテゴリーを削除しました');
    } catch {
      // banner
    } finally {
      busy = false;
    }
  }
</script>

<ConfirmDialog bind:this={dialog} />

<div class="stack">
  <form class="row" onsubmit={(e) => { e.preventDefault(); void create(); }}>
    <input type="text" placeholder="新しいカテゴリー名" aria-label="新しいカテゴリー名" bind:value={newName} maxlength="120" style="flex:1;min-width:160px" />
    <button type="submit" class="btn btn-primary btn-sm" disabled={busy || !newName.trim()}>追加</button>
  </form>
  {#if categories.items.length === 0}
    <div class="empty">カテゴリーはまだありません</div>
  {:else}
    <ul class="list-plain">
      {#each categories.items as c (c.id)}
        <li class="row row-between">
          {#if editingId === c.id}
            <form class="row" style="flex:1" onsubmit={(e) => { e.preventDefault(); void saveEdit(); }}>
              <input type="text" bind:value={editingName} aria-label="カテゴリー名" maxlength="120" style="flex:1;min-width:120px" />
              <button type="submit" class="btn btn-primary btn-sm" disabled={busy}>保存</button>
              <button type="button" class="btn btn-sm" onclick={() => (editingId = null)}>取消</button>
            </form>
          {:else}
            <span>{c.name} <span class="small muted">({c.task_count ?? 0} 件)</span></span>
            <span class="row">
              <button type="button" class="btn btn-ghost btn-sm" onclick={() => startEdit(c.id, c.name)}>名前変更</button>
              <button type="button" class="btn btn-ghost btn-sm text-danger" disabled={busy} onclick={() => void remove(c.id, c.name, c.task_count ?? 0)}>削除</button>
            </span>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>
