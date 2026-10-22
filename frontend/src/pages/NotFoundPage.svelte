<script lang="ts">
  import { links, route } from '../lib/router.svelte';
</script>

<div class="page">
  <div class="card">
    <h1>ページが見つかりません</h1>
    <p class="muted mono">{route.path}</p>
    <a class="btn" href={links.tasks()}>タスク一覧へ戻る</a>
  </div>
</div>
