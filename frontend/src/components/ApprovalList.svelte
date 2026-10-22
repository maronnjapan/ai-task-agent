<script lang="ts">
  // Pending tool approvals (external_write MCP calls, SPEC 17.14).
  import { onMount } from 'svelte';
  import { api } from '../api/client';
  import type { ApprovalOut } from '../api/types';
  import { debounced, onEvent } from '../stores/events.svelte';
  import { toast } from '../stores/toasts.svelte';
  import { formatRelative } from '../lib/format';
  import { links } from '../lib/router.svelte';

  let items: ApprovalOut[] = $state([]);
  let loading = $state(true);
  let busy: Record<string, boolean> = $state({});
  let comments: Record<string, string> = $state({});
  let expanded: Record<string, boolean> = $state({});

  async function load() {
    try {
      items = await api.approvals.list('pending');
    } catch {
      // banner
    } finally {
      loading = false;
    }
  }

  async function resolve(id: string, approve: boolean) {
    busy[id] = true;
    try {
      await api.approvals.resolve(id, { approve, comment: comments[id]?.trim() || null });
      toast.success(approve ? '承認しました' : '却下しました');
      items = items.filter((a) => a.id !== id);
    } catch {
      // banner
    } finally {
      busy[id] = false;
    }
  }

  onMount(() => {
    void load();
    return onEvent(['approval.requested', 'approval.resolved', 'system.restored'], debounced(() => void load(), 300));
  });
</script>

{#if !loading && items.length > 0}
  <section class="card approvals" aria-label="承認待ちの操作">
    <div class="card-title">
      <h2>承認待ちの操作 <span class="badge badge-warning">{items.length}</span></h2>
    </div>
    <p class="small muted">外部への書き込みを伴うツール実行です。内容を確認して承認または却下してください。</p>
    <ul class="list-plain">
      {#each items as a (a.id)}
        <li>
          <div class="row row-between">
            <div>
              <strong class="mono">{a.tool_name}</strong>
              <span class="small muted">({a.kind}) · {formatRelative(a.created_at)}</span>
              {#if a.task_id}<a class="small" href={links.task(a.task_id)}>対象タスク</a>{/if}
            </div>
            <button type="button" class="btn btn-ghost btn-sm" onclick={() => (expanded[a.id] = !expanded[a.id])} aria-expanded={!!expanded[a.id]}>
              {expanded[a.id] ? '引数を隠す' : '引数を表示'}
            </button>
          </div>
          {#if a.reason}<div class="small prewrap" style="margin-top:0.25rem">{a.reason}</div>{/if}
          {#if expanded[a.id]}
            <pre class="small">{JSON.stringify(a.arguments, null, 2)}</pre>
          {/if}
          <div class="row" style="margin-top:0.5rem">
            <input type="text" placeholder="コメント (任意)" aria-label="コメント" bind:value={comments[a.id]} style="flex:1;min-width:160px" />
            <button type="button" class="btn btn-success btn-sm" disabled={busy[a.id]} onclick={() => void resolve(a.id, true)}>承認</button>
            <button type="button" class="btn btn-danger btn-sm" disabled={busy[a.id]} onclick={() => void resolve(a.id, false)}>却下</button>
          </div>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  .approvals {
    border-color: var(--warning);
  }
</style>
