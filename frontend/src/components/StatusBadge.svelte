<script lang="ts">
  import {
    ARTIFACT_STATUS_LABELS,
    APPROVAL_STATUS_LABELS,
    DECISION_STATUS_LABELS,
    PLAN_STATUS_LABELS,
    REVIEW_STATUS_LABELS,
    RUN_STATUS_LABELS,
    SCHEDULE_STATUS_LABELS,
    TASK_STATUS_LABELS,
    WORK_ITEM_STATUS_LABELS,
    label
  } from '../lib/format';

  type Kind = 'task' | 'plan' | 'work_item' | 'run' | 'review' | 'artifact' | 'approval' | 'schedule' | 'decision' | 'generic';

  let { status, kind = 'generic', title = '' }: { status: string | null | undefined; kind?: Kind; title?: string } = $props();

  const maps: Record<Kind, Record<string, string>> = {
    task: TASK_STATUS_LABELS,
    plan: PLAN_STATUS_LABELS,
    work_item: WORK_ITEM_STATUS_LABELS,
    run: RUN_STATUS_LABELS,
    review: REVIEW_STATUS_LABELS,
    artifact: ARTIFACT_STATUS_LABELS,
    approval: APPROVAL_STATUS_LABELS,
    schedule: SCHEDULE_STATUS_LABELS,
    decision: DECISION_STATUS_LABELS,
    generic: {}
  };

  const tone: Record<string, string> = {
    todo: 'badge-outline',
    in_progress: 'badge-accent',
    running: 'badge-accent',
    reviewing: 'badge-info',
    planned: 'badge-info',
    pending: 'badge-outline',
    review_pending: 'badge-warning',
    revision_requested: 'badge-warning',
    blocked: 'badge-danger',
    failed: 'badge-danger',
    rejected: 'badge-danger',
    revoked: 'badge-danger',
    error: 'badge-danger',
    completed: 'badge-success',
    done: 'badge-success',
    succeeded: 'badge-success',
    approved: 'badge-success',
    passed: 'badge-success',
    active: 'badge-success',
    processed: 'badge-success',
    cancelled: '',
    superseded: '',
    draft: 'badge-outline',
    user_revision: 'badge-info'
  };

  const text = $derived(label(maps[kind], status));
  const cls = $derived(tone[status ?? ''] ?? '');
</script>

<span class="badge {cls}" title={title || status || ''}>{text}</span>
