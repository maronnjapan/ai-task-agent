<script lang="ts">
  // MCP 連携 (SPEC 17.13): list, create/edit, test, tools, OAuth, delete.
  import { onMount } from 'svelte';
  import { api } from '../../api/client';
  import type { AdapterPresetOut, ConnectionTestOut, IntegrationCreate, IntegrationOut, IntegrationUpdate, ToolOut } from '../../api/types';
  import { onEvent } from '../../stores/events.svelte';
  import { toast } from '../../stores/toasts.svelte';
  import ConfirmDialog from '../ConfirmDialog.svelte';
  import IntegrationForm from './IntegrationForm.svelte';
  import Loading from '../Loading.svelte';
  import { TOOL_PERMISSION_LABELS, formatDateTime, label } from '../../lib/format';

  let items: IntegrationOut[] = $state([]);
  let presets: AdapterPresetOut[] = $state([]);
  let loading = $state(true);
  let editing: IntegrationOut | null = $state(null);
  let creating = $state(false);
  let saving = $state(false);
  let busy: Record<string, boolean> = $state({});
  let testResults: Record<string, ConnectionTestOut> = $state({});
  let tools: Record<string, ToolOut[]> = $state({});
  let dialog: ConfirmDialog | undefined = $state();

  async function load() {
    try {
      [items, presets] = await Promise.all([api.integrations.list(), api.integrations.presets()]);
    } catch {
      // banner
    } finally {
      loading = false;
    }
  }

  async function save(data: IntegrationCreate | IntegrationUpdate) {
    saving = true;
    try {
      if (editing) {
        await api.integrations.update(editing.id, data as IntegrationUpdate);
        toast.success('接続先を更新しました');
      } else {
        await api.integrations.create(data as IntegrationCreate);
        toast.success('接続先を追加しました');
      }
      editing = null;
      creating = false;
      await load();
    } catch {
      // banner
    } finally {
      saving = false;
    }
  }

  async function test(c: IntegrationOut) {
    busy[c.id] = true;
    try {
      testResults[c.id] = await api.integrations.test(c.id);
      if (testResults[c.id].ok) toast.success(`接続成功: ${c.name}`, testResults[c.id].message);
      else toast.error(`接続失敗: ${c.name}`, testResults[c.id].message);
      await load();
    } catch {
      // banner
    } finally {
      busy[c.id] = false;
    }
  }

  async function listTools(c: IntegrationOut) {
    busy[c.id] = true;
    try {
      tools[c.id] = await api.integrations.tools(c.id);
    } catch {
      // banner
    } finally {
      busy[c.id] = false;
    }
  }

  async function oauthStart(c: IntegrationOut) {
    busy[c.id] = true;
    try {
      const result = await api.integrations.oauthStart(c.id);
      if (result.authorization_url) {
        window.open(result.authorization_url, '_blank', 'noopener');
        toast.info('ブラウザで認証を完了してください', '認証が終わると自動で反映されます。');
      } else {
        toast.warning('認証 URL を取得できませんでした');
      }
    } catch {
      // banner
    } finally {
      busy[c.id] = false;
    }
  }

  async function oauthRevoke(c: IntegrationOut) {
    const ok = await dialog?.confirm({ title: `${c.name} の認証を解除しますか？`, confirmLabel: '解除', danger: true });
    if (!ok) return;
    busy[c.id] = true;
    try {
      await api.integrations.oauthRevoke(c.id);
      toast.success('認証を解除しました');
      await load();
    } catch {
      // banner
    } finally {
      busy[c.id] = false;
    }
  }

  async function toggleEnabled(c: IntegrationOut) {
    busy[c.id] = true;
    try {
      await api.integrations.update(c.id, { enabled: !c.enabled });
      await load();
    } catch {
      // banner
    } finally {
      busy[c.id] = false;
    }
  }

  async function remove(c: IntegrationOut) {
    const ok = await dialog?.confirm({ title: `接続先「${c.name}」を削除しますか？`, message: '保存されている認証情報も削除されます。', confirmLabel: '削除', danger: true });
    if (!ok) return;
    busy[c.id] = true;
    try {
      await api.integrations.remove(c.id);
      toast.success('接続先を削除しました');
      await load();
    } catch {
      busy[c.id] = false;
    }
  }

  onMount(() => {
    void load();
    return onEvent('integration.oauth', (event) => {
      const data = event.data as { connection_id?: string; status?: string };
      toast.success('OAuth 認証が完了しました');
      if (data.connection_id) void load();
    });
  });
</script>

<ConfirmDialog bind:this={dialog} />

<div class="stack">
  {#if loading}
    <Loading />
  {:else}
    {#if !creating && !editing}
      <div class="row">
        <button type="button" class="btn btn-primary btn-sm" onclick={() => (creating = true)}>接続先を追加</button>
        <span class="small faint">MCP サーバー経由で Jira / Slack / Google Drive / Confluence などの情報源に接続します。</span>
      </div>
    {/if}

    {#if creating || editing}
      <div class="card">
        <h4>{editing ? `「${editing.name}」を編集` : '接続先を追加'}</h4>
        <IntegrationForm integration={editing} {presets} {saving} onsave={(d) => void save(d)} oncancel={() => { creating = false; editing = null; }} />
      </div>
    {/if}

    {#if items.length === 0}
      <div class="empty">接続先はまだありません</div>
    {:else}
      <ul class="list-plain">
        {#each items as c (c.id)}
          <li>
            <div class="row">
              <strong>{c.name}</strong>
              <span class="badge badge-outline">{c.adapter}</span>
              <span class="badge">{c.transport}</span>
              <span class="badge">{c.auth_type}</span>
              {#if c.enabled}<span class="badge badge-success">有効</span>{:else}<span class="badge">無効</span>{/if}
              {#if c.auth_type === 'oauth2'}
                {#if c.oauth_authorized}<span class="badge badge-success">認証済み</span>{:else}<span class="badge badge-warning">未認証</span>{/if}
              {:else if c.has_secret}
                <span class="badge badge-info">シークレット設定済み</span>
              {/if}
              <span class="spacer"></span>
              <span class="small faint">最終テスト: {c.last_tested_at ? formatDateTime(c.last_tested_at) : '—'}</span>
            </div>
            <div class="small mono muted" style="margin-top:0.2rem">
              {#if c.transport === 'stdio'}{c.command ?? ''} {c.args.join(' ')}{:else}{c.url ?? ''}{/if}
            </div>
            {#if c.last_error}
              <div class="alert alert-danger small" style="margin-top:0.35rem">{c.last_error}</div>
            {/if}
            {#if c.tool_permissions.length > 0}
              <div class="row small" style="margin-top:0.35rem">
                {#each c.tool_permissions as p (p.tool_name)}
                  <span class="badge {p.enabled ? (p.permission === 'external_write' ? 'badge-warning' : 'badge-outline') : ''}" title={label(TOOL_PERMISSION_LABELS, p.permission)}>{p.tool_name}: {label(TOOL_PERMISSION_LABELS, p.permission)}{p.enabled ? '' : ' (無効)'}</span>
                {/each}
              </div>
            {/if}
            <div class="row" style="margin-top:0.5rem">
              <button type="button" class="btn btn-sm" disabled={busy[c.id]} onclick={() => void test(c)}>接続テスト</button>
              <button type="button" class="btn btn-sm" disabled={busy[c.id]} onclick={() => void listTools(c)}>ツール一覧</button>
              {#if c.auth_type === 'oauth2'}
                <button type="button" class="btn btn-sm" disabled={busy[c.id]} onclick={() => void oauthStart(c)}>OAuth 認証</button>
                {#if c.oauth_authorized}<button type="button" class="btn btn-sm" disabled={busy[c.id]} onclick={() => void oauthRevoke(c)}>認証解除</button>{/if}
              {/if}
              <button type="button" class="btn btn-sm" disabled={busy[c.id]} onclick={() => void toggleEnabled(c)}>{c.enabled ? '無効にする' : '有効にする'}</button>
              <button type="button" class="btn btn-sm" disabled={busy[c.id]} onclick={() => { editing = c; creating = false; }}>編集</button>
              <button type="button" class="btn btn-sm btn-danger" disabled={busy[c.id]} onclick={() => void remove(c)}>削除</button>
            </div>
            {#if testResults[c.id]}
              {@const r = testResults[c.id]}
              <div class="alert {r.ok ? 'alert-success' : 'alert-danger'} small" style="margin-top:0.5rem">
                {r.ok ? '接続成功' : '接続失敗'}: {r.message} {#if r.server_name}({r.server_name}){/if} {#if r.duration_ms}· {r.duration_ms} ms{/if}
                {#if r.tools && r.tools.length > 0}
                  <div style="margin-top:0.25rem">ツール: {r.tools.map((t) => t.name).join(', ')}</div>
                {/if}
              </div>
            {/if}
            {#if tools[c.id]}
              <div class="table-wrap" style="margin-top:0.5rem">
                <table class="table">
                  <thead><tr><th>ツール</th><th>権限</th><th>有効</th><th>説明</th></tr></thead>
                  <tbody>
                    {#if tools[c.id].length === 0}
                      <tr><td colspan="4" class="empty">ツールがありません</td></tr>
                    {/if}
                    {#each tools[c.id] as t (t.name)}
                      <tr>
                        <td class="mono small">{t.name}</td>
                        <td class="small">{label(TOOL_PERMISSION_LABELS, t.permission ?? 'read')}</td>
                        <td class="small">{t.enabled === false ? '無効' : '有効'}</td>
                        <td class="small muted">{t.description ?? ''}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>
