<script lang="ts">
  // 変更履歴 (SPEC 9.5): task versions with per-field diffs and revert.
  import { onMount } from 'svelte';
  import { api } from '../../api/client';
  import type { TaskOut, TaskVersionOut } from '../../api/types';
  import { debounced, onEvent } from '../../stores/events.svelte';
  import { upsertTask } from '../../stores/tasks.svelte';
  import { toast } from '../../stores/toasts.svelte';
  import ConfirmDialog from '../ConfirmDialog.svelte';
  import DiffView from '../DiffView.svelte';
  import Loading from '../Loading.svelte';
  import { diffRecords, type FieldDiff } from '../../lib/diff';
  import { ACTOR_LABELS, TASK_FIELD_LABELS, formatDateTime, label } from '../../lib/format';

  let { taskId, onreverted }: { taskId: string; onreverted: (task: TaskOut) => void } = $props();

  let versions: TaskVersionOut[] = $state([]);
  let loading = $state(true);
  let open: Record<string, boolean> = $state({});
  let reverting = $state(false);
  let dialog: ConfirmDialog | undefined = $state();

  const diffs = new Map<string, FieldDiff[]>();

  function diffFor(v: TaskVersionOut): FieldDiff[] {
    let cached = diffs.get(v.id);
    if (!cached) {
      cached = diffRecords(v.previous_content, v.revised_content);
      diffs.set(v.id, cached);
    }
    return cached;
  }

  async function load() {
    try {
      const rows = await api.tasks.history(taskId);
      versions = [...rows].sort((a, b) => b.version - a.version);
    } catch {
      // banner
    } finally {
      loading = false;
    }
  }

  async function revert(v: TaskVersionOut) {
    const ok = await dialog?.confirm({ title: `バージョン ${v.version} の内容に戻しますか？`, message: '現在の内容は新しいバージョンとして履歴に残ります。', confirmLabel: '戻す' });
    if (!ok) return;
    reverting = true;
    try {
      const task = await api.tasks.revert(taskId, { version: v.version });
      upsertTask(task);
      onreverted(task);
      toast.success(`バージョン ${v.version} に戻しました`);
      await load();
    } catch {
      // banner
    } finally {
      reverting = false;
    }
  }

  const actorClass = (who: string) => (who === 'ai' || who === 'assistant' ? 'badge-info' : who === 'system' ? '' : 'badge-accent');

  onMount(() => {
    void load();
    return onEvent('task.updated', (event) => {
      if ((event.data as { task_id?: string }).task_id === taskId) debounced(() => void load(), 300)();
    });
  });
</script>

<ConfirmDialog bind:this={dialog} />

<section class="card" aria-label="変更履歴">
  {#if loading}
    <Loading />
  {:else if versions.length === 0}
    <div class="empty">変更履歴はまだありません</div>
  {:else}
    <ol class="list-plain">
      {#each versions as v, i (v.id)}
        {@const changed = diffFor(v)}
        <li>
          <div class="row">
            <strong>v{v.version}</strong>
            <span class="badge {actorClass(v.changed_by)}">{label(ACTOR_LABELS, v.changed_by)}</span>
            <span class="small muted">{formatDateTime(v.created_at)}</span>
            <span class="small">{v.change_summary ?? ''}</span>
            <span class="spacer"></span>
            {#if changed.length > 0}
              <button type="button" class="btn btn-ghost btn-sm" aria-expanded={!!open[v.id]} onclick={() => (open[v.id] = !open[v.id])}>
                {open[v.id] ? '差分を隠す' : `差分を表示 (${changed.length} 項目)`}
              </button>
            {:else}
              <span class="small faint">差分なし</span>
            {/if}
            {#if i !== 0}
              <button type="button" class="btn btn-sm" disabled={reverting} onclick={() => void revert(v)}>このバージョンに戻す</button>
            {:else}
              <span class="badge badge-success">現在</span>
            {/if}
          </div>
          {#if open[v.id]}
            <div class="stack" style="margin-top:0.5rem">
              {#each changed as fd (fd.field)}
                <div>
                  <div class="small muted" style="margin-bottom:0.2rem">{label(TASK_FIELD_LABELS, fd.field)}</div>
                  <DiffView lines={fd.lines} maxHeight="260px" showStats={false} />
                </div>
              {/each}
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</section>
