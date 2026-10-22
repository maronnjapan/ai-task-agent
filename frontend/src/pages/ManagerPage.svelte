<script lang="ts">
  // AIマネージャー画面: status, controls, user state, plans, runs, schedule, notifications, audit.
  import { onMount } from 'svelte';
  import { api } from '../api/client';
  import type { AgentRunOut, AuditEventOut, ExecutionPlanOut, NotificationOut, ScheduledActionOut, UserStateOut } from '../api/types';
  import { debounced, onEvent } from '../stores/events.svelte';
  import { isPaused, loadManagerStatus, manager, pauseManager, resumeManager, runManagerNow } from '../stores/manager.svelte';
  import { toast } from '../stores/toasts.svelte';
  import StatusBadge from '../components/StatusBadge.svelte';
  import PlanDetail from '../components/PlanDetail.svelte';
  import AgentRunList from '../components/AgentRunList.svelte';
  import Loading from '../components/Loading.svelte';
  import ConfirmDialog from '../components/ConfirmDialog.svelte';
  import { MANAGER_STATE_LABELS, NOTIFICATION_LEVEL_LABELS, formatDateTime, formatRelative, label } from '../lib/format';
  import { links } from '../lib/router.svelte';

  let dialog: ConfirmDialog | undefined = $state();

  // ---- User state ---------------------------------------------------------
  let userState: UserStateOut | null = $state(null);
  let condition = $state('');
  let expiresIn = $state<number | null>(120);
  let savingState = $state(false);

  async function loadUserState() {
    try {
      userState = await api.userState.get();
      condition = userState.active ? userState.condition : '';
    } catch {
      // banner
    }
  }

  async function saveUserState() {
    const text = condition.trim();
    if (!text || savingState) return;
    savingState = true;
    try {
      userState = await api.userState.set({ condition: text, expires_in_minutes: expiresIn, source: 'user' });
      toast.success('状態を更新しました');
    } catch {
      // banner
    } finally {
      savingState = false;
    }
  }

  // ---- Plans --------------------------------------------------------------
  let plans: ExecutionPlanOut[] = $state([]);
  let plansLoading = $state(true);
  let planStatus = $state('');
  let openPlans: Record<string, boolean> = $state({});
  const planStatuses = ['planned', 'running', 'reviewing', 'review_pending', 'completed', 'failed', 'cancelled'];

  async function loadPlans() {
    plansLoading = true;
    try {
      plans = await api.plans.list({ status: planStatus || undefined, limit: 50 });
    } catch {
      // banner
    } finally {
      plansLoading = false;
    }
  }

  // ---- Runs ---------------------------------------------------------------
  let runs: AgentRunOut[] = $state([]);
  let runsLoading = $state(true);
  let runType = $state('');

  async function loadRuns() {
    runsLoading = true;
    try {
      runs = await api.manager.runs({ agent_type: runType || undefined, limit: 50 });
    } catch {
      // banner
    } finally {
      runsLoading = false;
    }
  }

  // ---- Schedule -----------------------------------------------------------
  let schedule: ScheduledActionOut[] = $state([]);

  async function loadSchedule() {
    try {
      schedule = await api.manager.schedule(50);
    } catch {
      // banner
    }
  }

  async function cancelAction(a: ScheduledActionOut) {
    const ok = await dialog?.confirm({ title: 'この予定をキャンセルしますか？', message: `${a.action_type} — ${formatDateTime(a.scheduled_at)}`, confirmLabel: 'キャンセル', cancelLabel: '戻る', danger: true });
    if (!ok) return;
    try {
      await api.manager.cancelSchedule(a.id);
      toast.success('予定をキャンセルしました');
      await loadSchedule();
    } catch {
      // banner
    }
  }

  // ---- Notifications & audit -------------------------------------------------
  let history: NotificationOut[] = $state([]);
  let historyTotal = $state(0);
  let audit: AuditEventOut[] = $state([]);
  let auditTotal = $state(0);
  let auditLoaded = $state(false);
  let auditOpen = $state(false);

  async function loadHistory() {
    try {
      const page = await api.notifications.list({ unread_only: false, limit: 50 });
      history = page.items;
      historyTotal = page.total;
    } catch {
      // banner
    }
  }

  async function loadAudit() {
    try {
      const page = await api.audit.list({ limit: 100 });
      audit = page.items;
      auditTotal = page.total;
      auditLoaded = true;
    } catch {
      // banner
    }
  }

  function onAuditToggle(event: Event) {
    auditOpen = (event.currentTarget as HTMLDetailsElement).open;
    if (auditOpen && !auditLoaded) void loadAudit();
  }

  onMount(() => {
    void loadManagerStatus();
    void loadUserState();
    void loadPlans();
    void loadRuns();
    void loadSchedule();
    void loadHistory();
    const offPlans = onEvent(['plan.created', 'plan.updated', 'work_item.updated', 'review.recorded'], debounced(() => void loadPlans(), 500));
    const offRuns = onEvent(['agent_run.started', 'agent_run.finished'], debounced(() => {
      void loadRuns();
      void loadSchedule();
      if (auditOpen) void loadAudit();
    }, 500));
    const offNotif = onEvent(['notification.created', 'notification.read'], debounced(() => void loadHistory(), 500));
    return () => {
      offPlans();
      offRuns();
      offNotif();
    };
  });

  const stateClass = $derived(
    manager.status?.state === 'running' ? 'badge-accent' : manager.status?.state === 'paused' ? 'badge-warning' : manager.status?.state === 'error' ? 'badge-danger' : 'badge-success'
  );
</script>

<ConfirmDialog bind:this={dialog} />

<div class="page page-wide">
  <header class="page-header">
    <h1>AIマネージャー</h1>
    <div class="row">
      <button type="button" class="btn btn-primary" disabled={manager.busy} onclick={() => void runManagerNow()}>今すぐ実行</button>
      {#if isPaused()}
        <button type="button" class="btn btn-success" disabled={manager.busy} onclick={() => void resumeManager()}>再開</button>
      {:else}
        <button type="button" class="btn" disabled={manager.busy} onclick={() => void pauseManager()}>一時停止</button>
      {/if}
    </div>
  </header>

  <div class="grid-2">
    <section class="card" aria-labelledby="status-title">
      <div class="card-title"><h2 id="status-title">状態</h2></div>
      {#if !manager.status}
        <Loading inline />
      {:else}
        {@const s = manager.status}
        <dl class="kv">
          <dt>状態</dt>
          <dd><span class="badge {stateClass}">{label(MANAGER_STATE_LABELS, s.state)}</span> {#if s.activity}<span class="muted">{s.activity}</span>{/if}</dd>
          <dt>LLM</dt>
          <dd>{#if s.llm_ready === false}<span class="text-danger">利用不可: {s.llm_issue ?? '設定を確認してください'}</span> <a href={links.settings()}>設定へ</a>{:else}<span class="text-success">利用可能</span>{/if}</dd>
          <dt>最終実行</dt>
          <dd>{s.last_run_at ? `${formatDateTime(s.last_run_at)} (${formatRelative(s.last_run_at)})` : '—'}</dd>
          <dt>最終結果</dt>
          <dd class="prewrap">{s.last_result ?? '—'}</dd>
          <dt>次回予定</dt>
          <dd>{s.next_scheduled_at ? `${formatDateTime(s.next_scheduled_at)} (${formatRelative(s.next_scheduled_at)})` : '—'}</dd>
          <dt>確認待ち</dt>
          <dd>{s.pending_review_count ?? 0} 件</dd>
          <dt>進行中の計画</dt>
          <dd>{s.active_plan_count ?? 0} 件</dd>
          <dt>待機イベント</dt>
          <dd>{s.queued_events ?? 0} 件</dd>
          {#if s.consecutive_no_progress}
            <dt>連続無進捗</dt>
            <dd class="text-warning">{s.consecutive_no_progress} 回</dd>
          {/if}
        </dl>
      {/if}
    </section>

    <section class="card" aria-labelledby="ustate-title">
      <div class="card-title"><h2 id="ustate-title">あなたの状態</h2></div>
      <p class="small muted">Manager AI は通知のタイミングや作業の進め方をこの状態に合わせて判断します (SPEC 19)。</p>
      {#if userState && userState.active}
        <p class="small">現在: <strong>{userState.condition}</strong> <span class="faint">({userState.source} · {userState.expires_at ? `${formatDateTime(userState.expires_at)} まで` : '期限なし'})</span></p>
      {/if}
      <form class="stack" onsubmit={(e) => { e.preventDefault(); void saveUserState(); }}>
        <label class="field">
          <span>状態</span>
          <input type="text" bind:value={condition} maxlength="200" placeholder="例: 会議中 / 集中作業中 / 外出中" list="condition-suggestions" />
          <datalist id="condition-suggestions">
            <option value="集中作業中"></option>
            <option value="会議中"></option>
            <option value="外出中"></option>
            <option value="休憩中"></option>
            <option value="通常"></option>
          </datalist>
        </label>
        <label class="field">
          <span>有効期間 (分・空欄で無期限)</span>
          <input type="number" min="1" bind:value={expiresIn} />
        </label>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary" disabled={savingState || !condition.trim()}>更新</button>
        </div>
      </form>
    </section>
  </div>

  <section class="card" aria-labelledby="plans-title">
    <div class="card-title">
      <h2 id="plans-title">実行計画 <span class="muted small">({plans.length})</span></h2>
      <select aria-label="状態で絞り込み" bind:value={planStatus} onchange={() => queueMicrotask(() => void loadPlans())} style="width:auto">
        <option value="">すべて</option>
        {#each planStatuses as s (s)}<option value={s}>{label({ planned: '計画済み', running: '実行中', reviewing: 'レビュー中', review_pending: '確認待ち', completed: '完了', failed: '失敗', cancelled: 'キャンセル' }, s)}</option>{/each}
      </select>
    </div>
    {#if plansLoading && plans.length === 0}
      <Loading />
    {:else if plans.length === 0}
      <div class="empty">実行計画はありません</div>
    {:else}
      <ul class="list-plain">
        {#each plans as plan (plan.id)}
          <li>
            <div class="row">
              <StatusBadge status={plan.status} kind="plan" />
              <span style="flex:1;min-width:200px">{plan.objective}</span>
              {#if plan.task_links && plan.task_links.length > 0}
                <span class="small">
                  {#each plan.task_links as link (link.task_id)}<a href={links.task(link.task_id)} style="margin-right:0.4rem">{link.task_title ?? 'タスク'}</a>{/each}
                </span>
              {/if}
              <span class="small muted nowrap">{plan.work_item_count ?? 0} items · {formatRelative(plan.updated_at)}</span>
              <button type="button" class="btn btn-ghost btn-sm" aria-expanded={!!openPlans[plan.id]} onclick={() => (openPlans[plan.id] = !openPlans[plan.id])}>{openPlans[plan.id] ? '閉じる' : '詳細'}</button>
            </div>
            {#if openPlans[plan.id]}<PlanDetail {plan} />{/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="card" aria-labelledby="runs-title">
    <div class="card-title">
      <h2 id="runs-title">Agent Run</h2>
      <select aria-label="種別で絞り込み" bind:value={runType} onchange={() => queueMicrotask(() => void loadRuns())} style="width:auto">
        <option value="">すべて</option>
        <option value="manager">Manager</option>
        <option value="worker">Worker</option>
        <option value="review">Review</option>
        <option value="chat">チャット</option>
      </select>
    </div>
    {#if runsLoading && runs.length === 0}<Loading />{:else}<AgentRunList {runs} />{/if}
  </section>

  <section class="card" aria-labelledby="schedule-title">
    <div class="card-title"><h2 id="schedule-title">予定されたアクション <span class="muted small">({schedule.length})</span></h2></div>
    {#if schedule.length === 0}
      <div class="empty">予定されたアクションはありません</div>
    {:else}
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>予定時刻</th><th>種類</th><th>状態</th><th>対象</th><th>内容</th><th></th></tr></thead>
          <tbody>
            {#each schedule as a (a.id)}
              <tr>
                <td class="nowrap small">{formatDateTime(a.scheduled_at)}<br /><span class="faint">{formatRelative(a.scheduled_at)}</span></td>
                <td class="mono small">{a.action_type}</td>
                <td><StatusBadge status={a.status} kind="schedule" /></td>
                <td class="small">{#if a.task_id}<a href={links.task(a.task_id)}>タスク</a>{:else if a.execution_plan_id}計画{:else}—{/if}</td>
                <td class="small mono muted">{a.payload ? JSON.stringify(a.payload).slice(0, 120) : ''}</td>
                <td>{#if a.status === 'pending'}<button type="button" class="btn btn-ghost btn-sm text-danger" onclick={() => void cancelAction(a)}>キャンセル</button>{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section class="card" aria-labelledby="notif-title">
    <div class="card-title"><h2 id="notif-title">通知履歴 <span class="muted small">({historyTotal})</span></h2></div>
    {#if history.length === 0}
      <div class="empty">通知はまだありません</div>
    {:else}
      <ul class="list-plain">
        {#each history as n (n.id)}
          <li class="row" style="align-items:flex-start">
            <span class="badge {n.level === 'urgent' || n.level === 'error' ? 'badge-danger' : n.level === 'high' || n.level === 'warning' ? 'badge-warning' : 'badge-outline'}">{label(NOTIFICATION_LEVEL_LABELS, n.level)}</span>
            <div style="flex:1;min-width:0">
              <div class:muted={n.status === 'read'}><strong>{n.title}</strong> {#if n.body}<span class="small">— {n.body}</span>{/if}</div>
              <div class="small faint">{formatDateTime(n.created_at)} · {n.channel} · {n.source} {#if n.task_id}· <a href={links.task(n.task_id)}>タスク</a>{/if}</div>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <details class="collapse" ontoggle={onAuditToggle}>
    <summary>監査ログ {#if auditLoaded}<span class="muted small">({auditTotal})</span>{/if}</summary>
    <div class="collapse-body">
      {#if !auditLoaded}
        <Loading inline />
      {:else if audit.length === 0}
        <div class="empty">監査ログはありません</div>
      {:else}
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>日時</th><th>イベント</th><th>対象</th><th>実行者</th><th>詳細</th></tr></thead>
            <tbody>
              {#each audit as e (e.id)}
                <tr>
                  <td class="nowrap small">{formatDateTime(e.created_at)}</td>
                  <td class="mono small">{e.event_type}</td>
                  <td class="small">{e.entity_type ?? ''} <span class="mono faint">{e.entity_id ? e.entity_id.slice(0, 8) : ''}</span></td>
                  <td class="small">{e.actor}</td>
                  <td class="small mono muted" style="max-width:420px;word-break:break-all">{e.details ? JSON.stringify(e.details).slice(0, 200) : ''}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>
  </details>
</div>
