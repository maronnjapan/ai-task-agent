<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../../api/client';
  import type { ArtifactOut } from '../../api/types';
  import { debounced, onEvent } from '../../stores/events.svelte';
  import StatusBadge from '../StatusBadge.svelte';
  import Loading from '../Loading.svelte';
  import { formatDateTime } from '../../lib/format';
  import { links } from '../../lib/router.svelte';

  let { taskId }: { taskId: string } = $props();

  let items: ArtifactOut[] = $state([]);
  let loading = $state(true);

  async function load() {
    try {
      items = await api.tasks.artifacts(taskId);
    } catch {
      // banner
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void load();
    return onEvent(['artifact.created', 'artifact.updated'], debounced(() => void load(), 300));
  });
</script>

<section class="card" aria-label="成果物">
  {#if loading}
    <Loading />
  {:else if items.length === 0}
    <div class="empty">成果物はまだありません。AI が作業を進めるとここに表示されます。</div>
  {:else}
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>タイトル</th>
            <th>状態</th>
            <th class="num">版</th>
            <th>更新</th>
            <th>ファイル</th>
          </tr>
        </thead>
        <tbody>
          {#each items as a (a.id)}
            <tr>
              <td><a href={links.artifact(a.id)}>{a.title}</a></td>
              <td><StatusBadge status={a.status} kind="artifact" /></td>
              <td class="num">v{a.version}</td>
              <td class="small nowrap">{formatDateTime(a.updated_at)}</td>
              <td class="small mono muted">{a.file_path}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>
