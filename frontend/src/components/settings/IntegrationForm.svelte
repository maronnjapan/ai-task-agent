<script lang="ts">
  // Create / edit form for one MCP connection (SPEC 17.3-17.6, 17.13-17.14).
  import type { AdapterPresetOut, IntegrationCreate, IntegrationOut, IntegrationUpdate, ToolPermissionIn } from '../../api/types';
  import { TOOL_PERMISSION_LABELS } from '../../lib/format';

  let {
    integration = null,
    presets,
    saving = false,
    onsave,
    oncancel
  }: {
    integration?: IntegrationOut | null;
    presets: AdapterPresetOut[];
    saving?: boolean;
    onsave: (data: IntegrationCreate | IntegrationUpdate) => void;
    oncancel: () => void;
  } = $props();

  type Perm = { tool_name: string; permission: string; enabled: boolean };

  let form = $state({
    name: '',
    adapter: 'generic',
    transport: 'stdio',
    command: '',
    args: '',
    env: '',
    url: '',
    headers: '',
    auth_type: 'none',
    auth_config: '{}',
    secret: '',
    timeout_seconds: 30,
    enabled: true,
    tool_permissions: [] as Perm[]
  });
  let presetKey = $state('');
  let authConfigError = $state('');
  let envHints: Record<string, string> = $state({});

  const kvToLines = (obj: Record<string, string> | null | undefined) => Object.entries(obj ?? {}).map(([k, v]) => `${k}=${v}`).join('\n');
  const linesToKv = (text: string): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const raw of text.split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const idx = line.indexOf('=');
      if (idx <= 0) continue;
      out[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
    }
    return out;
  };
  const linesToList = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean);

  $effect(() => {
    if (integration) {
      form = {
        name: integration.name,
        adapter: integration.adapter,
        transport: integration.transport,
        command: integration.command ?? '',
        args: integration.args.join('\n'),
        env: kvToLines(integration.env),
        url: integration.url ?? '',
        headers: kvToLines(integration.headers),
        auth_type: integration.auth_type,
        auth_config: JSON.stringify(integration.auth_config ?? {}, null, 2),
        secret: '',
        timeout_seconds: integration.timeout_seconds,
        enabled: integration.enabled,
        tool_permissions: integration.tool_permissions.map((p) => ({ ...p }))
      };
    }
  });

  function applyPreset(key: string) {
    presetKey = key;
    const preset = presets.find((p) => p.adapter === key);
    if (!preset) return;
    form.adapter = preset.adapter;
    form.transport = preset.transport;
    form.command = preset.command ?? '';
    form.args = (preset.args ?? []).join('\n');
    form.url = preset.url ?? '';
    form.auth_type = preset.auth_type ?? 'none';
    form.auth_config = JSON.stringify(preset.auth_config ?? {}, null, 2);
    form.tool_permissions = (preset.tool_permissions ?? []).map((p: ToolPermissionIn) => ({ tool_name: p.tool_name, permission: p.permission ?? 'read', enabled: p.enabled ?? true }));
    envHints = preset.env_hints ?? {};
    if (!form.name) form.name = preset.label;
    if (Object.keys(envHints).length > 0 && !form.env) form.env = Object.keys(envHints).map((k) => `${k}=`).join('\n');
  }

  function addPermission() {
    form.tool_permissions = [...form.tool_permissions, { tool_name: '', permission: 'read', enabled: true }];
  }
  function removePermission(i: number) {
    form.tool_permissions = form.tool_permissions.filter((_, idx) => idx !== i);
  }

  function submit() {
    authConfigError = '';
    let authConfig: Record<string, unknown> = {};
    if (form.auth_config.trim()) {
      try {
        const parsed = JSON.parse(form.auth_config);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('object expected');
        authConfig = parsed;
      } catch {
        authConfigError = '認証設定は JSON オブジェクトで入力してください';
        return;
      }
    }
    const data: IntegrationCreate = {
      name: form.name.trim(),
      adapter: form.adapter.trim() || 'generic',
      transport: form.transport,
      command: form.transport === 'stdio' ? form.command.trim() || null : null,
      args: form.transport === 'stdio' ? linesToList(form.args) : [],
      env: form.transport === 'stdio' ? linesToKv(form.env) : {},
      url: form.transport === 'streamable_http' ? form.url.trim() || null : null,
      headers: form.transport === 'streamable_http' ? linesToKv(form.headers) : {},
      auth_type: form.auth_type,
      auth_config: authConfig,
      timeout_seconds: Number(form.timeout_seconds) || 30,
      enabled: form.enabled,
      tool_permissions: form.tool_permissions.filter((p) => p.tool_name.trim()).map((p) => ({ tool_name: p.tool_name.trim(), permission: p.permission, enabled: p.enabled }))
    };
    // Only send the secret when the user typed one (never echo stored secrets back).
    if (form.secret) data.secret = form.secret;
    onsave(data);
  }

  const oauthHint = '{\n  "client_id": "...",\n  "authorization_url": "https://.../authorize",\n  "token_url": "https://.../token",\n  "scope": "read write",\n  "redirect_uri": "http://127.0.0.1:8765/api/integrations/oauth/callback"\n}';
</script>

<form class="stack" onsubmit={(e) => { e.preventDefault(); submit(); }}>
  {#if !integration && presets.length > 0}
    <label class="field">
      <span>プリセットから入力</span>
      <select value={presetKey} onchange={(e) => applyPreset((e.currentTarget as HTMLSelectElement).value)}>
        <option value="">選択してください</option>
        {#each presets as p (p.adapter)}<option value={p.adapter}>{p.label} — {p.description}</option>{/each}
      </select>
    </label>
  {/if}

  <div class="form-grid">
    <label class="field">
      <span>名前 *</span>
      <input type="text" bind:value={form.name} required maxlength="120" />
    </label>
    <label class="field">
      <span>アダプター</span>
      <input type="text" bind:value={form.adapter} list="adapter-list" placeholder="generic" />
      <datalist id="adapter-list">
        {#each presets as p (p.adapter)}<option value={p.adapter}></option>{/each}
      </datalist>
    </label>
    <label class="field">
      <span>接続方式</span>
      <select bind:value={form.transport}>
        <option value="stdio">stdio (ローカルプロセス)</option>
        <option value="streamable_http">Streamable HTTP</option>
      </select>
    </label>
    <label class="field">
      <span>タイムアウト (秒)</span>
      <input type="number" min="1" max="600" bind:value={form.timeout_seconds} />
    </label>
  </div>

  {#if form.transport === 'stdio'}
    <div class="form-grid">
      <label class="field full">
        <span>コマンド</span>
        <input type="text" bind:value={form.command} placeholder="例: npx" class="mono" />
      </label>
      <label class="field">
        <span>引数 (1行に1つ)</span>
        <textarea class="code" rows="4" bind:value={form.args} placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;/path/to/dir"></textarea>
      </label>
      <label class="field">
        <span>環境変数 (KEY=VALUE、1行に1つ)</span>
        <textarea class="code" rows="4" bind:value={form.env} placeholder="API_TOKEN=..."></textarea>
        {#if Object.keys(envHints).length > 0}
          <span class="help">必要な環境変数: {Object.entries(envHints).map(([k, v]) => `${k} (${v})`).join(', ')}</span>
        {/if}
      </label>
    </div>
  {:else}
    <div class="form-grid">
      <label class="field full">
        <span>URL</span>
        <input type="url" bind:value={form.url} placeholder="https://example.com/mcp" />
      </label>
      <label class="field full">
        <span>追加ヘッダー (KEY=VALUE、1行に1つ)</span>
        <textarea class="code" rows="3" bind:value={form.headers}></textarea>
      </label>
    </div>
  {/if}

  <div class="form-grid">
    <label class="field">
      <span>認証方式</span>
      <select bind:value={form.auth_type}>
        <option value="none">なし</option>
        <option value="api_token">API トークン</option>
        <option value="bearer">Bearer トークン</option>
        <option value="oauth2">OAuth 2.0</option>
        <option value="custom">カスタム</option>
      </select>
    </label>
    {#if form.auth_type !== 'none'}
      <label class="field">
        <span>{form.auth_type === 'oauth2' ? 'クライアントシークレット' : 'トークン / シークレット'} {#if integration?.has_secret}<span class="faint">(保存済み・変更する場合のみ入力)</span>{/if}</span>
        <input type="password" bind:value={form.secret} autocomplete="new-password" placeholder={integration?.has_secret ? '••••••••' : ''} />
      </label>
    {/if}
  </div>

  {#if form.auth_type !== 'none'}
    <label class="field">
      <span>認証設定 (JSON)</span>
      <textarea class="code" rows="6" bind:value={form.auth_config} placeholder={form.auth_type === 'oauth2' ? oauthHint : '{ "header": "X-Api-Key" }'}></textarea>
      {#if form.auth_type === 'oauth2'}<span class="help">client_id, authorization_url, token_url, scope, redirect_uri を指定します。</span>{/if}
      {#if authConfigError}<span class="text-danger small">{authConfigError}</span>{/if}
    </label>
  {/if}

  <fieldset class="perm">
    <legend>ツール権限</legend>
    <p class="help">外部書き込み (external_write) は実行前にユーザー承認が必要です。未登録のツールは接続テスト後に自動で追加されます。</p>
    {#if form.tool_permissions.length === 0}
      <div class="empty small">ツール権限はまだありません</div>
    {/if}
    {#each form.tool_permissions as p, i (i)}
      <div class="row perm-row">
        <input type="text" bind:value={p.tool_name} placeholder="ツール名" aria-label="ツール名" class="mono" style="flex:2;min-width:140px" />
        <select bind:value={p.permission} aria-label="権限" style="flex:1;min-width:150px">
          {#each Object.entries(TOOL_PERMISSION_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
        </select>
        <label class="field field-inline small"><input type="checkbox" bind:checked={p.enabled} /><span>有効</span></label>
        <button type="button" class="btn btn-ghost btn-sm text-danger" aria-label="削除" onclick={() => removePermission(i)}>×</button>
      </div>
    {/each}
    <button type="button" class="btn btn-sm" onclick={addPermission}>ツールを追加</button>
  </fieldset>

  <label class="field field-inline"><input type="checkbox" bind:checked={form.enabled} /><span>この接続を有効にする</span></label>

  <div class="form-actions">
    <button type="submit" class="btn btn-primary" disabled={saving || !form.name.trim()}>{saving ? '保存中…' : integration ? '更新' : '追加'}</button>
    <button type="button" class="btn" onclick={oncancel}>キャンセル</button>
  </div>
</form>

<style>
  .perm {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 0.5rem 0.75rem 0.75rem;
  }
  .perm legend {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text-muted);
  }
  .perm-row {
    margin-bottom: 0.4rem;
  }
</style>
