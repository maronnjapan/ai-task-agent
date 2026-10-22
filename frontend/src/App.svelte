<script lang="ts">
  import { onMount } from 'svelte';
  import type { Component } from 'svelte';
  import TopBar from './components/TopBar.svelte';
  import ErrorBanner from './components/ErrorBanner.svelte';
  import Toasts from './components/Toasts.svelte';
  import Loading from './components/Loading.svelte';
  import { route, type RouteName } from './lib/router.svelte';
  import { onApiError } from './api/client';
  import { connectEvents, onEvent } from './stores/events.svelte';
  import { bindNotificationEvents, loadNotifications } from './stores/notifications.svelte';
  import { bindManagerEvents, loadManagerStatus } from './stores/manager.svelte';
  import { bindTaskEvents } from './stores/tasks.svelte';
  import { showError, toast } from './stores/toasts.svelte';

  // Pages are code-split; each is fetched the first time its route is visited.
  type PageModule = { default: Component<Record<string, unknown>> };
  const loaders: Record<RouteName, () => Promise<PageModule>> = {
    tasks: () => import('./pages/TaskListPage.svelte') as Promise<PageModule>,
    task: () => import('./pages/TaskDetailPage.svelte') as Promise<PageModule>,
    artifact: () => import('./pages/ArtifactPage.svelte') as Promise<PageModule>,
    manager: () => import('./pages/ManagerPage.svelte') as Promise<PageModule>,
    settings: () => import('./pages/SettingsPage.svelte') as Promise<PageModule>,
    notfound: () => import('./pages/NotFoundPage.svelte') as Promise<PageModule>
  };

  const page = $derived(loaders[route.name]());

  onMount(() => {
    const offError = onApiError((err) => showError(err.message, `${err.status || 'network'} ${err.path}`));
    connectEvents();
    bindNotificationEvents();
    bindManagerEvents();
    bindTaskEvents();
    void loadManagerStatus();
    void loadNotifications();
    const offRestored = onEvent('system.restored', () => toast.warning('バックアップから復元されました', '最新の状態を表示するには画面を再読み込みしてください。'));
    return () => {
      offError();
      offRestored();
    };
  });
</script>

<TopBar />
<ErrorBanner />
<main id="main">
  {#key route.path}
    {#await page}
      <Loading />
    {:then mod}
      {@const Page = mod.default}
      <Page {...route.params} query={route.query} />
    {:catch err}
      <div class="page"><div class="alert alert-danger">画面の読み込みに失敗しました: {err?.message ?? err}</div></div>
    {/await}
  {/key}
</main>
<Toasts />
