<script lang="ts">
  // 成果物画面 (SPEC 16.3 / 22.4): preview, source, edit, copy, open, versions, diff, approve, revision.
  import { onMount } from 'svelte';
  import { api, ApiError } from '../api/client';
  import type { ArtifactDiffOut, ArtifactOut, ArtifactVersionOut } from '../api/types';
  import { debounced, onEvent } from '../stores/events.svelte';
  import { toast } from '../stores/toasts.svelte';
  import StatusBadge from '../components/StatusBadge.svelte';
  import Loading from '../components/Loading.svelte';
  import MarkdownView from '../components/MarkdownView.svelte';
  import DiffView from '../components/DiffView.svelte';
  import ConfirmDialog from '../components/ConfirmDialog.svelte';
  import { ACTOR_LABELS, formatDateTime, label } from '../lib/format';
  import { links } from '../lib/router.svelte';

  let { id }: { id: string; query?: Record<string, string> } = $props();

  type Mode = 'preview' | 'source' | 'edit';

  let artifact: ArtifactOut | null = $state(null);
  let content = $state('');
  let contentVersion = $state(0);
  let notFound = $state(false);
  let loadingContent = $state(true);
  let mode = $state<Mode>('preview');
  let draft = $state('');
  let changeNote = $state('');
  let saving = $state(false);
  let busy = $state(false);
  let versions: ArtifactVersionOut[] = $state([]);
  let viewingVersion: number | null = $state(null);
  let diffFrom: number | null = $state(null);
  let diffTo: number | null = $state(null);
  let diff: ArtifactDiffOut | null = $state(null);
  let diffLoading = $state(false);
  let revisionText = $state('');
  let showRevision = $state(false);
  let dialog: ConfirmDialog | undefined = $state();

  const dirty = $derived(mode === 'edit' && draft !== content);

  async function load() {
    try {
      artifact = await api.artifacts.get(id, { silent: true });
      notFound = false;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) notFound = true;
      return;
    }
    await Promise.all([loadContent(viewingVersion ?? undefined), loadVersions()]);
  }

  async function loadContent(version?: number) {
    loadingContent = true;
    try {
      const out = await api.artifacts.content(id, version);
      content = out.content;
      contentVersion = out.version;
      if (mode !== 'edit') draft = out.content;
    } catch {
      // banner
    } finally {
      loadingContent = false;
    }
  }

  async function loadVersions() {
    try {
      const rows = await api.artifacts.versions(id);
      versions = [...rows].sort((a, b) => b.version - a.version);
      if (diffFrom === null && versions.length >= 2) {
        diffFrom = versions[1].version;
        diffTo = versions[0].version;
      }
    } catch {
      // banner
    }
  }

  function setMode(next: Mode) {
    if (next === 'edit') {
      if (viewingVersion !== null) {
        toast.warning('過去のバージョンは編集できません', '最新版を表示してから編集してください。');
        return;
      }
      draft = content;
      changeNote = '';
    }
    mode = next;
  }

  async function save() {
    if (!dirty || saving) return;
    saving = true;
    try {
      artifact = await api.artifacts.updateContent(id, draft, changeNote.trim() || null);
      content = draft;
      changeNote = '';
      mode = 'preview';
      toast.success('成果物を保存しました', `v${artifact.version}`);
      await Promise.all([loadContent(), loadVersions()]);
    } catch {
      // banner
    } finally {
      saving = false;
    }
  }

  async function cancelEdit() {
    if (dirty) {
      const ok = await dialog?.confirm({ title: '編集内容を破棄しますか？', confirmLabel: '破棄', danger: true });
      if (!ok) return;
    }
    draft = content;
    mode = 'preview';
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(mode === 'edit' ? draft : content);
      toast.success('クリップボードにコピーしました');
    } catch {
      toast.error('コピーできませんでした', 'ブラウザの権限設定を確認してください。');
    }
  }

  async function openFile() {
    busy = true;
    try {
      const result = await api.artifacts.open(id);
      toast.success(result.message || 'ファイルを開きました');
    } catch {
      // banner
    } finally {
      busy = false;
    }
  }

  async function approve() {
    const ok = await dialog?.confirm({ title: 'この成果物を承認しますか？', confirmLabel: '承認' });
    if (!ok) return;
    busy = true;
    try {
      artifact = await api.artifacts.approve(id);
      toast.success('成果物を承認しました');
    } catch {
      // banner
    } finally {
      busy = false;
    }
  }

  async function requestRevision() {
    const instructions = revisionText.trim();
    if (!instructions) return;
    busy = true;
    try {
      artifact = await api.artifacts.revision(id, instructions, 'revision');
      revisionText = '';
      showRevision = false;
      toast.success('修正依頼を送りました');
    } catch {
      // banner
    } finally {
      busy = false;
    }
  }

  async function viewVersion(version: number | null) {
    if (mode === 'edit' && dirty) {
      const ok = await dialog?.confirm({ title: '編集内容を破棄して別のバージョンを表示しますか？', confirmLabel: '破棄', danger: true });
      if (!ok) return;
    }
    viewingVersion = version;
    if (mode === 'edit') mode = 'preview';
    await loadContent(version ?? undefined);
  }

  async function restore(version: number) {
    const ok = await dialog?.confirm({ title: `バージョン ${version} を復元しますか？`, message: '復元した内容は新しいバージョンとして保存されます。', confirmLabel: '復元' });
    if (!ok) return;
    busy = true;
    try {
      artifact = await api.artifacts.restore(id, version);
      viewingVersion = null;
      toast.success(`バージョン ${version} を復元しました`);
      await Promise.all([loadContent(), loadVersions()]);
    } catch {
      // banner
    } finally {
      busy = false;
    }
  }

  async function loadDiff() {
    if (diffFrom === null) return;
    diffLoading = true;
    try {
      diff = await api.artifacts.diff(id, diffFrom, diffTo ?? undefined);
    } catch {
      diff = null;
    } finally {
      diffLoading = false;
    }
  }

  function beforeUnload(event: BeforeUnloadEvent) {
    if (dirty) event.preventDefault();
  }

  onMount(() => {
    void load();
    window.addEventListener('beforeunload', beforeUnload);
    const off = onEvent('artifact.updated', (event) => {
      if ((event.data as { artifact_id?: string }).artifact_id === id && mode !== 'edit') debounced(() => void load(), 300)();
    });
    return () => {
      window.removeEventListener('beforeunload', beforeUnload);
      off();
    };
  });

  const linkedTasks = $derived.by(() => {
    if (!artifact) return [] as string[];
    const ids = new Set<string>(artifact.linked_task_ids ?? []);
    if (artifact.task_id) ids.add(artifact.task_id);
    return [...ids];
  });
</script>

<ConfirmDialog bind:this={dialog} />

<div class="page page-wide">
  <nav class="small muted" aria-label="パンくず" style="margin-bottom:0.5rem">
    <a href={links.tasks()}>タスク一覧</a>
    {#if artifact?.task_id}› <a href={links.task(artifact.task_id)}>タスク</a>{/if}
    › 成果物
  </nav>

  {#if notFound}
    <div class="card"><div class="alert alert-warning">成果物が見つかりません。</div></div>
  {:else if !artifact}
    <Loading />
  {:else}
    <header class="page-header">
      <div style="min-width:0">
        <h1 style="word-break:break-word;margin-bottom:0.25rem">{artifact.title}</h1>
        <div class="row small muted">
          <StatusBadge status={artifact.status} kind="artifact" />
          <span>v{artifact.version}</span>
          <span>{artifact.artifact_type}</span>
          <span class="mono" title={artifact.absolute_path ?? artifact.file_path}>{artifact.file_path}</span>
          <span>更新 {formatDateTime(artifact.updated_at)}</span>
        </div>
      </div>
      <div class="row">
        <button type="button" class="btn" onclick={() => void copy()}>コピー</button>
        <button type="button" class="btn" disabled={busy} onclick={() => void openFile()}>ファイルを開く</button>
        {#if artifact.status !== 'approved'}
          <button type="button" class="btn btn-success" disabled={busy} onclick={() => void approve()}>承認</button>
        {/if}
        <button type="button" class="btn" disabled={busy} aria-expanded={showRevision} onclick={() => (showRevision = !showRevision)}>修正依頼</button>
      </div>
    </header>

    {#if showRevision}
      <section class="card" aria-label="修正依頼">
        <form class="stack" onsubmit={(e) => { e.preventDefault(); void requestRevision(); }}>
          <label class="field">
            <span>修正してほしい内容</span>
            <textarea rows="3" bind:value={revisionText} placeholder="例: 第2章の比較表に価格の列を追加してください"></textarea>
          </label>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary" disabled={busy || !revisionText.trim()}>送信</button>
            <button type="button" class="btn" onclick={() => (showRevision = false)}>閉じる</button>
          </div>
        </form>
      </section>
    {/if}

    <div class="layout">
      <section class="card content" aria-label="内容">
        <div class="tabs" role="tablist" aria-label="表示モード">
          <button type="button" role="tab" aria-selected={mode === 'preview'} onclick={() => setMode('preview')}>プレビュー</button>
          <button type="button" role="tab" aria-selected={mode === 'source'} onclick={() => setMode('source')}>ソース</button>
          <button type="button" role="tab" aria-selected={mode === 'edit'} onclick={() => setMode('edit')} disabled={viewingVersion !== null}>編集</button>
          <span class="spacer"></span>
          {#if viewingVersion !== null}
            <span class="badge badge-warning" style="align-self:center">v{contentVersion} を表示中</span>
            <button type="button" class="btn btn-sm" style="align-self:center" onclick={() => void viewVersion(null)}>最新版へ</button>
          {/if}
        </div>

        {#if loadingContent}
          <Loading />
        {:else if mode === 'preview'}
          {#if content.trim() === ''}
            <div class="empty">内容はまだありません</div>
          {:else}
            <MarkdownView source={content} />
          {/if}
        {:else if mode === 'source'}
          <pre class="source">{content}</pre>
        {:else}
          <form class="stack" onsubmit={(e) => { e.preventDefault(); void save(); }}>
            <label class="field">
              <span class="sr-only">Markdown ソース</span>
              <textarea class="code editor" bind:value={draft} spellcheck="false"></textarea>
            </label>
            <div class="row">
              <input type="text" bind:value={changeNote} placeholder="変更メモ (任意)" aria-label="変更メモ" style="flex:1;min-width:160px" />
              <button type="submit" class="btn btn-primary" disabled={!dirty || saving}>{saving ? '保存中…' : '保存'}</button>
              <button type="button" class="btn" onclick={() => void cancelEdit()}>キャンセル</button>
            </div>
          </form>
        {/if}
      </section>

      <aside class="stack side">
        <section class="card" aria-labelledby="versions-title">
          <div class="card-title"><h3 id="versions-title">バージョン <span class="muted small">({versions.length})</span></h3></div>
          {#if versions.length === 0}
            <div class="empty">バージョン情報がありません</div>
          {:else}
            <ul class="list-plain">
              {#each versions as v (v.id)}
                <li>
                  <div class="row">
                    <strong>v{v.version}</strong>
                    {#if v.version === artifact.version}<span class="badge badge-success">現在</span>{/if}
                    <span class="small muted">{label(ACTOR_LABELS, v.created_by)} · {formatDateTime(v.created_at)}</span>
                  </div>
                  {#if v.change_note}<div class="small prewrap">{v.change_note}</div>{/if}
                  <div class="row" style="margin-top:0.2rem">
                    <button type="button" class="btn btn-ghost btn-sm" disabled={contentVersion === v.version && !loadingContent} onclick={() => void viewVersion(v.version === artifact?.version ? null : v.version)}>表示</button>
                    {#if v.version !== artifact.version}
                      <button type="button" class="btn btn-ghost btn-sm" disabled={busy} onclick={() => void restore(v.version)}>復元</button>
                    {/if}
                  </div>
                </li>
              {/each}
            </ul>
          {/if}
        </section>

        {#if versions.length >= 2}
          <section class="card" aria-labelledby="diff-title">
            <div class="card-title"><h3 id="diff-title">差分</h3></div>
            <form class="row" onsubmit={(e) => { e.preventDefault(); void loadDiff(); }}>
              <label class="field field-inline small">
                <span>from</span>
                <select bind:value={diffFrom} aria-label="比較元バージョン">
                  {#each versions as v (v.id)}<option value={v.version}>v{v.version}</option>{/each}
                </select>
              </label>
              <label class="field field-inline small">
                <span>to</span>
                <select bind:value={diffTo} aria-label="比較先バージョン">
                  {#each versions as v (v.id)}<option value={v.version}>v{v.version}</option>{/each}
                </select>
              </label>
              <button type="submit" class="btn btn-sm" disabled={diffLoading || diffFrom === null}>{diffLoading ? '取得中…' : '差分を表示'}</button>
            </form>
            {#if diff}
              <div style="margin-top:0.5rem">
                <div class="small muted">v{diff.from_version} → v{diff.to_version}</div>
                <DiffView lines={diff.lines} maxHeight="360px" />
              </div>
            {/if}
          </section>
        {/if}

        <section class="card" aria-labelledby="sources-title">
          <div class="card-title"><h3 id="sources-title">出典 <span class="muted small">({artifact.sources?.length ?? 0})</span></h3></div>
          {#if !artifact.sources || artifact.sources.length === 0}
            <div class="empty">出典はありません</div>
          {:else}
            <ul class="list-plain small">
              {#each artifact.sources as s (s.id)}
                <li>
                  <div><span class="badge badge-outline">{s.source_type}</span> <strong>{s.title}</strong></div>
                  <div class="mono muted" style="word-break:break-all">
                    {#if /^https?:\/\//.test(s.reference)}<a href={s.reference} target="_blank" rel="noopener noreferrer">{s.reference}</a>{:else}{s.reference}{/if}
                  </div>
                  {#if s.note}<div class="prewrap">{s.note}</div>{/if}
                </li>
              {/each}
            </ul>
          {/if}
        </section>

        <section class="card" aria-labelledby="linked-title">
          <div class="card-title"><h3 id="linked-title">関連タスク</h3></div>
          {#if linkedTasks.length === 0}
            <div class="empty">関連タスクはありません</div>
          {:else}
            <ul class="list-plain small">
              {#each linkedTasks as tid (tid)}
                <li><a href={links.task(tid)}>{tid === artifact.task_id ? '元のタスク' : 'タスク'} <span class="mono muted">{tid.slice(0, 8)}…</span></a></li>
              {/each}
            </ul>
          {/if}
          {#if artifact.execution_plan_id}
            <p class="small faint" style="margin:0.5rem 0 0">実行計画: <span class="mono">{artifact.execution_plan_id}</span></p>
          {/if}
        </section>
      </aside>
    </div>
  {/if}
</div>

<style>
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: 1rem;
    align-items: start;
  }
  .content {
    min-height: 50vh;
  }
  .source {
    max-height: 70vh;
    overflow: auto;
    font-size: 0.85rem;
  }
  .editor {
    min-height: 60vh;
    white-space: pre-wrap;
  }
  @media (max-width: 960px) {
    .layout {
      grid-template-columns: 1fr;
    }
  }
</style>
