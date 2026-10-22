<script lang="ts">
  // 設定画面: LLM / Manager / 通知 / ローカル情報源 / バックアップ / API キー / 自動起動 / MCP 連携 / システム情報
  import { onMount } from 'svelte';
  import { api } from '../api/client';
  import type { BackupOut, BackupSettings, LLMAgentSettings, LocalSourceSettings, ManagerSettingsOut, NotificationSettings, ProviderKeyStatus, SettingsOut, SystemStatusOut } from '../api/types';
  import { onEvent } from '../stores/events.svelte';
  import { toast } from '../stores/toasts.svelte';
  import ConfirmDialog from '../components/ConfirmDialog.svelte';
  import Loading from '../components/Loading.svelte';
  import IntegrationsSection from '../components/settings/IntegrationsSection.svelte';
  import { AUTONOMY_LABELS, NOTIFICATION_SETTING_LEVELS, REMINDER_LABELS, formatBytes, formatDateTime, formatDuration } from '../lib/format';

  let settings: SettingsOut | null = $state(null);
  let system: SystemStatusOut | null = $state(null);
  let dialog: ConfirmDialog | undefined = $state();

  // Local editable copies per section
  type AgentKey = 'manager' | 'worker' | 'review';
  const agentKeys: { key: AgentKey; label: string }[] = [
    { key: 'manager', label: 'Manager AI' },
    { key: 'worker', label: 'Worker AI' },
    { key: 'review', label: 'Review AI' }
  ];
  let llm: Record<AgentKey, Required<Omit<LLMAgentSettings, 'extra'>>> = $state({
    manager: blankAgent(),
    worker: blankAgent(),
    review: blankAgent()
  });
  let managerForm: Required<ManagerSettingsOut> = $state(blankManager());
  let notifForm = $state({ level: 'normal', desktop_enabled: true, quiet_hours_start: '', quiet_hours_end: '', min_interval_seconds: 60, dedupe_window_minutes: 60, pending_review_reminder_hours: 24 });
  let localForm = $state({ directories: '', extensions: '', max_file_size_kb: 512 });
  let backupForm = $state({ directory: '', auto_backup_interval_hours: 0, keep_last: 10 });
  let saving: Record<string, boolean> = $state({});

  function blankAgent(): Required<Omit<LLMAgentSettings, 'extra'>> {
    return { provider: 'openai', model: '', temperature: 0.2, timeout_seconds: 120, max_retries: 2, custom_prompt: '' };
  }
  function blankManager(): Required<ManagerSettingsOut> {
    return { custom_prompt: '', autonomy_level: 'balanced', reminder_aggressiveness: 'normal', reevaluation_interval_minutes: 30, max_replanning_attempts: 3, max_worker_retries: 2, max_consecutive_no_progress: 2 };
  }

  function fillForms(s: SettingsOut) {
    for (const { key } of agentKeys) {
      const a = s.llm[key] ?? {};
      llm[key] = { ...blankAgent(), ...stripExtra(a) };
    }
    managerForm = { ...blankManager(), ...s.manager };
    const n = s.notifications;
    notifForm = {
      level: n.level ?? 'normal',
      desktop_enabled: n.desktop_enabled ?? true,
      quiet_hours_start: n.quiet_hours_start ?? '',
      quiet_hours_end: n.quiet_hours_end ?? '',
      min_interval_seconds: n.min_interval_seconds ?? 60,
      dedupe_window_minutes: n.dedupe_window_minutes ?? 60,
      pending_review_reminder_hours: n.pending_review_reminder_hours ?? 24
    };
    localForm = { directories: (s.local_sources.directories ?? []).join('\n'), extensions: (s.local_sources.extensions ?? []).join(', '), max_file_size_kb: s.local_sources.max_file_size_kb ?? 512 };
    backupForm = { directory: s.backup.directory ?? '', auto_backup_interval_hours: s.backup.auto_backup_interval_hours ?? 0, keep_last: s.backup.keep_last ?? 10 };
  }

  function stripExtra(a: LLMAgentSettings): Omit<LLMAgentSettings, 'extra'> {
    const { extra: _extra, ...rest } = a;
    return rest;
  }

  async function load() {
    try {
      settings = await api.settings.get();
      fillForms(settings);
    } catch {
      // banner
    }
  }

  async function loadSystem() {
    try {
      system = await api.system.status();
    } catch {
      // banner
    }
  }

  async function saveSection(section: 'llm' | 'manager' | 'notifications' | 'local_sources' | 'backup') {
    saving[section] = true;
    try {
      let patch;
      if (section === 'llm') {
        patch = { llm: { manager: { ...llm.manager, extra: settings?.llm.manager?.extra ?? {} }, worker: { ...llm.worker, extra: settings?.llm.worker?.extra ?? {} }, review: { ...llm.review, extra: settings?.llm.review?.extra ?? {} } } };
      } else if (section === 'manager') {
        patch = { manager: { ...managerForm } };
      } else if (section === 'notifications') {
        const n: NotificationSettings = { ...notifForm, quiet_hours_start: notifForm.quiet_hours_start || null, quiet_hours_end: notifForm.quiet_hours_end || null };
        patch = { notifications: n };
      } else if (section === 'local_sources') {
        const ls: LocalSourceSettings = {
          directories: localForm.directories.split('\n').map((d) => d.trim()).filter(Boolean),
          extensions: localForm.extensions.split(/[\s,]+/).map((e) => e.trim()).filter(Boolean).map((e) => (e.startsWith('.') ? e : `.${e}`)),
          max_file_size_kb: Number(localForm.max_file_size_kb) || 512
        };
        patch = { local_sources: ls };
      } else {
        const b: BackupSettings = { directory: backupForm.directory.trim() || null, auto_backup_interval_hours: Number(backupForm.auto_backup_interval_hours) || 0, keep_last: Math.max(1, Number(backupForm.keep_last) || 10) };
        patch = { backup: b };
      }
      settings = await api.settings.patch(patch);
      fillForms(settings);
      toast.success('設定を保存しました');
    } catch {
      // banner
    } finally {
      saving[section] = false;
    }
  }

  // ---- API keys -----------------------------------------------------------------
  let keyInputs: Record<string, string> = $state({});
  let keyBusy: Record<string, boolean> = $state({});

  const providers = $derived.by(() => {
    const set = new Set<string>(settings?.app.providers ?? []);
    for (const k of settings?.api_keys ?? []) set.add(k.provider);
    return [...set].sort();
  });
  const keyStatus = (provider: string): ProviderKeyStatus | undefined => settings?.api_keys.find((k) => k.provider === provider);

  async function setKey(provider: string) {
    const value = keyInputs[provider]?.trim();
    if (!value) return;
    keyBusy[provider] = true;
    try {
      const statuses = await api.settings.setApiKey(provider, value);
      if (settings) settings.api_keys = statuses;
      keyInputs[provider] = '';
      toast.success(`${provider} の API キーを保存しました`);
    } catch {
      // banner
    } finally {
      keyBusy[provider] = false;
    }
  }

  async function deleteKey(provider: string) {
    const ok = await dialog?.confirm({ title: `${provider} の API キーを削除しますか？`, confirmLabel: '削除', danger: true });
    if (!ok) return;
    keyBusy[provider] = true;
    try {
      const statuses = await api.settings.deleteApiKey(provider);
      if (settings) settings.api_keys = statuses;
      toast.success(`${provider} の API キーを削除しました`);
    } catch {
      // banner
    } finally {
      keyBusy[provider] = false;
    }
  }

  // ---- Autostart ---------------------------------------------------------------
  let autostartBusy = $state(false);
  async function setAutostart(enabled: boolean) {
    autostartBusy = true;
    try {
      const result = await api.settings.autostart(enabled);
      if (settings) settings.autostart_installed = enabled;
      toast.success(enabled ? '自動起動を有効にしました' : '自動起動を無効にしました', result.message || undefined);
    } catch {
      // banner
    } finally {
      autostartBusy = false;
    }
  }

  // ---- Backups ------------------------------------------------------------------
  let backups: BackupOut[] = $state([]);
  let backupBusy = $state(false);
  let restoreBusy = $state(false);

  async function loadBackups() {
    try {
      backups = await api.system.backups();
    } catch {
      // banner
    }
  }

  async function backupNow() {
    backupBusy = true;
    try {
      const result = await api.system.backup();
      toast.success('バックアップを作成しました', result.path);
      await loadBackups();
    } catch {
      // banner
    } finally {
      backupBusy = false;
    }
  }

  async function restore(b: BackupOut) {
    const ok = await dialog?.confirm({
      title: 'バックアップから復元しますか？',
      message: `${b.path}\n(${formatDateTime(b.created_at)})\n\n現在のデータは安全のため別途バックアップされたうえで置き換えられます。復元後は画面を再読み込みしてください。`,
      confirmLabel: '復元する',
      danger: true,
      requireText: '復元'
    });
    if (!ok) return;
    restoreBusy = true;
    try {
      const result = await api.system.restore(b.path);
      toast.success('復元が完了しました', result.message);
      await Promise.all([load(), loadSystem(), loadBackups()]);
    } catch {
      // banner
    } finally {
      restoreBusy = false;
    }
  }

  async function openDataDir() {
    try {
      await api.system.openDataDir();
    } catch {
      // banner
    }
  }

  onMount(() => {
    void load();
    void loadSystem();
    void loadBackups();
    return onEvent('settings.updated', () => void load());
  });
</script>

<ConfirmDialog bind:this={dialog} />

<div class="page">
  <header class="page-header"><h1>設定</h1></header>

  {#if !settings}
    <Loading />
  {:else}
    <div class="stack">
      <details class="collapse" open>
        <summary>LLM</summary>
        <div class="collapse-body">
          <p class="small muted">エージェントごとにプロバイダーとモデルを設定します。API キーは下の「API キー」で登録してください。</p>
          <div class="agents">
            {#each agentKeys as { key, label: name } (key)}
              <fieldset class="agent">
                <legend>{name}</legend>
                <div class="form-grid">
                  <label class="field">
                    <span>プロバイダー</span>
                    <select bind:value={llm[key].provider}>
                      {#if !providers.includes(llm[key].provider)}<option value={llm[key].provider}>{llm[key].provider}</option>{/if}
                      {#each providers as p (p)}<option value={p}>{p}</option>{/each}
                    </select>
                  </label>
                  <label class="field">
                    <span>モデル</span>
                    <input type="text" bind:value={llm[key].model} class="mono" />
                  </label>
                  <label class="field">
                    <span>Temperature (0–2)</span>
                    <input type="number" min="0" max="2" step="0.1" bind:value={llm[key].temperature} />
                  </label>
                  <label class="field">
                    <span>タイムアウト (秒)</span>
                    <input type="number" min="1" max="3600" bind:value={llm[key].timeout_seconds} />
                  </label>
                  <label class="field">
                    <span>最大リトライ</span>
                    <input type="number" min="0" max="10" bind:value={llm[key].max_retries} />
                  </label>
                  <label class="field full">
                    <span>カスタムプロンプト</span>
                    <textarea rows="3" bind:value={llm[key].custom_prompt} placeholder="このエージェントへの追加指示"></textarea>
                  </label>
                </div>
              </fieldset>
            {/each}
          </div>
          <div class="form-actions"><button type="button" class="btn btn-primary" disabled={saving.llm} onclick={() => void saveSection('llm')}>LLM 設定を保存</button></div>
        </div>
      </details>

      <details class="collapse">
        <summary>Manager AI</summary>
        <div class="collapse-body">
          <div class="form-grid">
            <label class="field full">
              <span>カスタムプロンプト</span>
              <textarea rows="4" bind:value={managerForm.custom_prompt} placeholder="例: 期限の2日前には必ず確認を依頼すること。社外向け文書は丁寧語で。"></textarea>
            </label>
            <label class="field">
              <span>自律性</span>
              <select bind:value={managerForm.autonomy_level}>
                {#each Object.entries(AUTONOMY_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
                {#if !(managerForm.autonomy_level in AUTONOMY_LABELS)}<option value={managerForm.autonomy_level}>{managerForm.autonomy_level}</option>{/if}
              </select>
            </label>
            <label class="field">
              <span>リマインドの積極性</span>
              <select bind:value={managerForm.reminder_aggressiveness}>
                {#each Object.entries(REMINDER_LABELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
                {#if !(managerForm.reminder_aggressiveness in REMINDER_LABELS)}<option value={managerForm.reminder_aggressiveness}>{managerForm.reminder_aggressiveness}</option>{/if}
              </select>
            </label>
            <label class="field">
              <span>再評価間隔 (分)</span>
              <input type="number" min="1" bind:value={managerForm.reevaluation_interval_minutes} />
            </label>
            <label class="field">
              <span>再計画の最大回数</span>
              <input type="number" min="0" bind:value={managerForm.max_replanning_attempts} />
            </label>
            <label class="field">
              <span>Worker の最大再試行回数</span>
              <input type="number" min="0" bind:value={managerForm.max_worker_retries} />
            </label>
            <label class="field">
              <span>連続無進捗の上限</span>
              <input type="number" min="1" bind:value={managerForm.max_consecutive_no_progress} />
            </label>
          </div>
          <div class="form-actions"><button type="button" class="btn btn-primary" disabled={saving.manager} onclick={() => void saveSection('manager')}>Manager 設定を保存</button></div>
        </div>
      </details>

      <details class="collapse">
        <summary>通知</summary>
        <div class="collapse-body">
          <div class="form-grid">
            <label class="field">
              <span>通知レベル</span>
              <select bind:value={notifForm.level}>
                {#each Object.entries(NOTIFICATION_SETTING_LEVELS) as [value, text] (value)}<option {value}>{text}</option>{/each}
                {#if !(notifForm.level in NOTIFICATION_SETTING_LEVELS)}<option value={notifForm.level}>{notifForm.level}</option>{/if}
              </select>
            </label>
            <label class="field field-inline" style="align-self:end">
              <input type="checkbox" bind:checked={notifForm.desktop_enabled} />
              <span>デスクトップ通知を使う</span>
            </label>
            <label class="field">
              <span>静音時間 開始</span>
              <input type="time" bind:value={notifForm.quiet_hours_start} />
            </label>
            <label class="field">
              <span>静音時間 終了</span>
              <input type="time" bind:value={notifForm.quiet_hours_end} />
            </label>
            <label class="field">
              <span>最小通知間隔 (秒)</span>
              <input type="number" min="0" bind:value={notifForm.min_interval_seconds} />
            </label>
            <label class="field">
              <span>重複抑制ウィンドウ (分)</span>
              <input type="number" min="0" bind:value={notifForm.dedupe_window_minutes} />
            </label>
            <label class="field">
              <span>確認待ちリマインド (時間)</span>
              <input type="number" min="0" bind:value={notifForm.pending_review_reminder_hours} />
            </label>
          </div>
          <div class="form-actions"><button type="button" class="btn btn-primary" disabled={saving.notifications} onclick={() => void saveSection('notifications')}>通知設定を保存</button></div>
        </div>
      </details>

      <details class="collapse">
        <summary>ローカル情報源</summary>
        <div class="collapse-body">
          <p class="small muted">AI が参照できるローカルディレクトリと拡張子を指定します (SPEC 17.12)。</p>
          <div class="form-grid">
            <label class="field full">
              <span>ディレクトリ (1行に1つ)</span>
              <textarea class="code" rows="4" bind:value={localForm.directories} placeholder="/Users/me/Documents/projects"></textarea>
            </label>
            <label class="field">
              <span>拡張子 (カンマ区切り)</span>
              <input type="text" bind:value={localForm.extensions} placeholder=".md, .txt, .pdf" class="mono" />
            </label>
            <label class="field">
              <span>最大ファイルサイズ (KB)</span>
              <input type="number" min="1" bind:value={localForm.max_file_size_kb} />
            </label>
          </div>
          <div class="form-actions"><button type="button" class="btn btn-primary" disabled={saving.local_sources} onclick={() => void saveSection('local_sources')}>ローカル情報源を保存</button></div>
        </div>
      </details>

      <details class="collapse">
        <summary>バックアップ</summary>
        <div class="collapse-body">
          <div class="form-grid">
            <label class="field full">
              <span>保存先ディレクトリ (空欄でデータディレクトリ内)</span>
              <input type="text" bind:value={backupForm.directory} class="mono" />
            </label>
            <label class="field">
              <span>自動バックアップ間隔 (時間・0で無効)</span>
              <input type="number" min="0" bind:value={backupForm.auto_backup_interval_hours} />
            </label>
            <label class="field">
              <span>保持する世代数</span>
              <input type="number" min="1" bind:value={backupForm.keep_last} />
            </label>
          </div>
          <div class="form-actions">
            <button type="button" class="btn btn-primary" disabled={saving.backup} onclick={() => void saveSection('backup')}>バックアップ設定を保存</button>
            <button type="button" class="btn" disabled={backupBusy} onclick={() => void backupNow()}>{backupBusy ? '作成中…' : '今すぐバックアップ'}</button>
            <button type="button" class="btn btn-ghost btn-sm" onclick={() => void loadBackups()}>一覧を更新</button>
          </div>
          <h4 style="margin-top:1rem">バックアップ一覧</h4>
          {#if backups.length === 0}
            <div class="empty">バックアップはまだありません</div>
          {:else}
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>作成日時</th><th>パス</th><th class="num">サイズ</th><th></th></tr></thead>
                <tbody>
                  {#each backups as b (b.path)}
                    <tr>
                      <td class="nowrap small">{formatDateTime(b.created_at)}</td>
                      <td class="mono small" style="word-break:break-all">{b.path}</td>
                      <td class="num small">{formatBytes(b.size_bytes)}</td>
                      <td><button type="button" class="btn btn-sm btn-danger" disabled={restoreBusy} onclick={() => void restore(b)}>復元</button></td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </div>
      </details>

      <details class="collapse">
        <summary>API キー</summary>
        <div class="collapse-body">
          <p class="small muted">キーは OS のシークレットストア ({settings.secret_backend}) に保存され、画面には表示されません。</p>
          {#if providers.length === 0}
            <div class="empty">利用可能なプロバイダーがありません</div>
          {:else}
            <ul class="list-plain">
              {#each providers as p (p)}
                {@const st = keyStatus(p)}
                <li class="row">
                  <strong style="min-width:110px">{p}</strong>
                  {#if st?.configured}<span class="badge badge-success">設定済み</span>{:else}<span class="badge badge-warning">未設定</span>{/if}
                  <span class="small faint mono">{st?.secret_name ?? ''}</span>
                  <input type="password" bind:value={keyInputs[p]} placeholder={st?.configured ? '新しいキーで上書き' : 'API キーを入力'} aria-label="{p} の API キー" autocomplete="off" style="flex:1;min-width:200px" />
                  <button type="button" class="btn btn-sm btn-primary" disabled={keyBusy[p] || !keyInputs[p]?.trim()} onclick={() => void setKey(p)}>保存</button>
                  {#if st?.configured}<button type="button" class="btn btn-sm btn-danger" disabled={keyBusy[p]} onclick={() => void deleteKey(p)}>削除</button>{/if}
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      </details>

      <details class="collapse">
        <summary>自動起動</summary>
        <div class="collapse-body">
          <div class="row">
            <label class="field field-inline">
              <input type="checkbox" checked={settings.autostart_installed} disabled={autostartBusy} onchange={(e) => void setAutostart((e.currentTarget as HTMLInputElement).checked)} />
              <span>OS ログイン時にアプリを自動起動する</span>
            </label>
            {#if settings.autostart_installed}<span class="badge badge-success">有効</span>{:else}<span class="badge">無効</span>{/if}
          </div>
          <p class="help">macOS は LaunchAgent、Windows はスタートアップ、Linux/WSL は systemd user unit に登録します。</p>
        </div>
      </details>

      <details class="collapse">
        <summary>MCP 連携</summary>
        <div class="collapse-body"><IntegrationsSection /></div>
      </details>

      <details class="collapse">
        <summary>システム情報</summary>
        <div class="collapse-body">
          {#if !system}
            <Loading inline />
          {:else}
            <dl class="kv">
              <dt>バージョン</dt><dd>{system.version}</dd>
              <dt>プラットフォーム</dt><dd class="mono small">{Object.entries(system.platform).map(([k, v]) => `${k}=${v}`).join(' ')}</dd>
              <dt>データディレクトリ</dt><dd class="mono small">{system.data_directory} <button type="button" class="btn btn-ghost btn-sm" onclick={() => void openDataDir()}>開く</button></dd>
              <dt>データベース</dt><dd class="mono small">{system.database_path}</dd>
              <dt>設定ファイル</dt><dd class="mono small">{settings.env_file}</dd>
              <dt>稼働時間</dt><dd>{formatDuration(system.uptime_seconds)}</dd>
              <dt>PID</dt><dd>{system.pid}</dd>
              <dt>SSE 接続数</dt><dd>{system.sse_subscribers}</dd>
              <dt>シークレット保存先</dt><dd>{system.secret_backend}</dd>
              <dt>件数</dt>
              <dd>{Object.entries(system.counts).map(([k, v]) => `${k}: ${v}`).join(' / ')}</dd>
              <dt>サーバー</dt><dd class="mono small">{settings.app.host}:{settings.app.port}</dd>
            </dl>
          {/if}
        </div>
      </details>
    </div>
  {/if}
</div>

<style>
  .agents {
    display: grid;
    gap: 0.75rem;
  }
  .agent {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 0.5rem 0.75rem 0.75rem;
  }
  .agent legend {
    font-weight: 600;
    font-size: 0.9rem;
  }
</style>
